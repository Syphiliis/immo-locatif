"""Tests hors ligne de la fiche « données ouvertes » d'un bien.

Couvre `src/opendata/*` et `scripts/immo_fiche_opendata.py` :
  - socle HTTP (retry, 404, 4xx, User-Agent) ;
  - une analyse par source (géocodage, loyers, DVF, DPE, Géorisques, fiscalité locale) ;
  - la fiche (clés, sources, erreurs isolées par bloc, codes de sortie) et le script ;
  - médiane de référence des immeubles (DVF), commune du géocodage contrôlée,
    cadastre (API Carto) et clé du bien, mode `--point` (adresses candidates d'une annonce sans adresse).

Aucun appel réseau : tous les clients passent par `httpx.MockTransport` (classe `Routeur`, qui garde
le journal des requêtes) ; une fixture autouse fait échouer toute tentative de connexion réelle ;
`sleep` est injecté (aucune attente réelle). Les fixtures JSON/CSV sont dans
`tests/fixtures/opendata/` (à plat : `.gitignore` ignore tout dossier `data/`) : formes réelles
réduites, adresses génériques, aucune donnée personnelle.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import io
import json
import math
import re
import socket
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest

from src.opendata import adresse, batiment, cadastre, copropriete, dpe, dvf, fiscalite_locale, geocodage, georisques
from src.opendata import loyers, urbanisme
from src.opendata import fiche as fiche_mod
from src.opendata import http as oh

RACINE = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opendata"

INSEE = "99001"
LABEL = "1 Rue de Test 99100 Exempleville"
ADRESSE = "1 rue de test 99100 Exempleville"  # saisie libre de l'utilisateur (le label BAN est LABEL)
LON, LAT = 1.5021, 47.5013

# Sortie attendue de geocodage.geocoder sur la fixture geocodage_housenumber.json.
GEO: dict[str, Any] = {
    "label": LABEL, "score": 0.96, "type": "housenumber", "citycode": INSEE, "postcode": "99100",
    "city": "Exempleville", "lon": LON, "lat": LAT,
    # clés ajoutées par une évolution (ADRESSE porte le code postal 99100, premier candidat)
    "identifiant_ban": "99001_0001_00001", "controle_commune": "code postal 99100 concordant", "rang_candidat": 1,
}
GEO_COMMUNE: dict[str, Any] = {
    "label": "Exempleville", "score": 0.9471172727272725, "type": "municipality", "citycode": INSEE,
    "postcode": "99100", "city": "Exempleville", "lon": 1.5117, "lat": 47.4972,
    "identifiant_ban": INSEE, "controle_commune": "code postal 99100 concordant", "rang_candidat": 1,
}

AUJOURDHUI = date(2026, 10, 3)
# Juste après minuit (UTC+2) : la date UTC serait la veille. date_extraction et la fenêtre DVF doivent
# suivre la date LOCALE de `maintenant`, sans conversion en UTC.
MAINTENANT = datetime(2026, 10, 3, 0, 30, 5, tzinfo=timezone(timedelta(hours=2)))
GENERE_LE = "2026-10-03T00:30:05+02:00"

RESSOURCES_ATTENDUES = {
    "appartement": "55b34088-0964-415f-9df7-d87dd98a09be",
    "appartement_t1_t2": "14a1fe11-b2d1-49b3-9f6b-83d12df9482c",
    "appartement_t3_plus": "5e3b28a4-cf56-43a3-ae79-43cceeb27f8c",
    "maison": "129f764d-b613-44e4-952c-5ff50a8c9b73",
}
FIXTURES_LOYERS = {
    "appartement": "loyers_appartement.json",
    "appartement_t1_t2": "loyers_appartement_t1_t2.json",
    "appartement_t3_plus": "loyers_appartement_t3_plus.json",
    "maison": "loyers_maison.json",
}
CHAMPS_DPE_ATTENDUS = (
    "etiquette_dpe", "etiquette_ges", "conso_5_usages_par_m2_ep", "date_etablissement_dpe",
    "surface_habitable_logement", "type_batiment", "periode_construction",
    "type_energie_principale_chauffage", "adresse_ban", "code_insee_ban",
)
CLES_FICHE = (
    "adresse_demandee", "genere_le", "geocodage", "commune", "cle_bien", "cadastre", "urbanisme", "batiment",
    "copropriete", "loyers", "dvf", "dpe", "risques", "fiscalite_locale", "sources", "erreurs", "alertes",
    # `alertes` : ; `cle_bien`, `cadastre` : ; `urbanisme`, `batiment`,
    # `copropriete` : (ancien attendu : 14 clés, sans ces trois-là)
)
BLOCS_REGLEMENTAIRES = ("urbanisme", "batiment", "copropriete")
BLOCS_COLLECTES = ("urbanisme", "batiment", "copropriete", "loyers", "dvf", "dpe", "risques", "fiscalite_locale")
# ancien attendu de BLOCS_COLLECTES : ("loyers", "dvf", "dpe", "risques", "fiscalite_locale")

MOTIF_GEOCODAGE = "data.geopf.fr/geocodage/search"
MOTIF_DPE = "data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
MOTIF_RISQUES = "georisques.gouv.fr/api/v1/gaspar/risques"
MOTIF_RAPPORT = "georisques.gouv.fr/api/v1/resultats_rapport_risque"
MOTIF_PPRN = "georisques.gouv.fr/api/v1/gaspar/pprn"
MOTIF_PPRN_DETAIL = "georisques.gouv.fr/api/v1/gaspar/pprn/"
MOTIF_FISCALITE = (
    "data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/fiscalite-locale-des-particuliers-geo/records"
)
MOTIF_DVF = "files.data.gouv.fr/geo-dvf/latest/csv/"


def motif_loyers(rid: str) -> str:
    return f"tabular-api.data.gouv.fr/api/resources/{rid}/data/"


def url_dvf(annee: int) -> str:
    """URL (sans schéma) du CSV DVF de la commune pour une année."""
    return f"files.data.gouv.fr/geo-dvf/latest/csv/{annee}/communes/99/{INSEE}.csv"


def fx(nom: str) -> Any:
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


def fx_texte(nom: str) -> str:
    return (FIXTURES / nom).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Constructeurs de réponses de la Géoplateforme et de l'API Carto
# ---------------------------------------------------------------------------

MOTIF_CADASTRE = "apicarto.ign.fr/api/cadastre/parcelle"
MOTIF_INVERSE = "data.geopf.fr/geocodage/reverse"
IDU = f"{INSEE}000AB0001"


def parcelle_carto(idu: str = IDU, section: str = "AB", numero: str = "0001", contenance: Any = 500,
                   code_insee: str = INSEE, nom_com: str = "Exempleville") -> dict:
    """Une parcelle de l'API Carto (module cadastre/parcelle), forme réelle réduite."""
    proprietes: dict[str, Any] = {"idu": idu, "section": section, "numero": numero, "code_insee": code_insee,
                                  "nom_com": nom_com, "code_dep": code_insee[:2], "code_com": code_insee[2:],
                                  "com_abs": "000", "feuille": 1}
    if contenance is not None:
        proprietes["contenance"] = contenance
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[[LON, LAT]]]]},
            "properties": proprietes}


def reponse_carto(*parcelles: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(parcelles)}


def feature_parcelle_inverse(idu: str, section: str, numero: str, *, distance: float | None = 9,
                             ville: str | None = "Exempleville") -> dict:
    """Un résultat du géocodage inverse `index=parcel`, forme réelle relevée le 08/10/2026 : identifiant IDU, codes
    département / commune / préfixe / arrondissement, section, feuille, numéro, ville, distance, score ; ni contenance
    ni `citycode`."""
    proprietes: dict[str, Any] = {
        "id": idu, "departmentcode": idu[:2], "municipalitycode": idu[2:5], "oldmunicipalitycode": idu[5:8],
        "districtcode": "000", "section": section, "sheet": "01", "number": numero, "score": 0.9991,
        "_type": "parcel"}
    if ville is not None:
        proprietes["city"] = ville
    if distance is not None:
        proprietes["distance"] = distance
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LON, LAT]}, "properties": proprietes}


def feature_ban(label: str, id_ban: str, *, postcode: str | None = "99100", type_: str = "housenumber",
                score: float = 0.96, citycode: str = INSEE, city: str = "Exempleville", lon: float = LON,
                lat: float = LAT, distance: float | None = None) -> dict:
    """Un résultat de la Géoplateforme (search ou reverse), forme réelle réduite."""
    proprietes: dict[str, Any] = {"label": label, "score": score, "id": id_ban, "citycode": citycode, "city": city,
                                  "type": type_}
    if postcode is not None:
        proprietes["postcode"] = postcode
    if distance is not None:
        proprietes["distance"] = distance
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": proprietes}


def reponse_ban(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


# ---------------------------------------------------------------------------
# Infrastructure : réseau interdit, routeur MockTransport, réponses simulées
# ---------------------------------------------------------------------------

class AppelInterdit(BaseException):
    """Appel réseau réel, ou requête que le routeur de test n'a pas prévue.

    Dérive de BaseException et non d'Exception : le contrat impose à `construire_fiche` de capter toute
    `Exception` d'un collecteur ; une AssertionError y serait absorbée en simple entrée de `erreurs`
    et le test ne tomberait pas.
    """


@pytest.fixture(autouse=True)
def _reseau_interdit(monkeypatch):
    """Toute tentative de connexion ou de résolution DNS réelle fait échouer le test."""
    def interdit(*_args, **_kwargs):
        raise AppelInterdit("appel réseau interdit en test")

    monkeypatch.setattr(socket.socket, "connect", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)


def rep_json(donnees: Any, statut: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(statut, json=donnees)


def rep_texte(texte: str, statut: int = 200,
              type_mime: str = "text/plain; charset=utf-8") -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(
        statut, content=texte.encode("utf-8"), headers={"content-type": type_mime})


def rep_csv(texte: str) -> Callable[[httpx.Request], httpx.Response]:
    return rep_texte(texte, type_mime="text/csv; charset=utf-8")


def rep_statut(statut: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(statut, content=b"erreur simulee")


def rep_redirection(url: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(302, headers={"location": url})


class Appel(NamedTuple):
    methode: str
    cle: str  # hôte + chemin, sans schéma ni query
    url: str  # schéma + hôte + chemin, sans query
    params: dict[str, str]
    entetes: httpx.Headers


def _motif_correspond(motif: str, cle: str) -> bool:
    return cle.startswith(motif[:-1]) if motif.endswith("*") else cle == motif


class Routeur:
    """Transport httpx.MockTransport + journal des requêtes + surcharge des routes.

    `route(motif, reponse, si=None)` : `motif` = hôte + chemin exacts (ou préfixe si fini par `*`).
    Les routes ajoutées en DERNIER l'emportent (surcharge). `reponse` est :
      - un appelable `requete -> httpx.Response` (voir rep_json, rep_texte, rep_statut...) ;
      - une exception (instance ou classe), levée à chaque appel ;
      - une liste de ces éléments, consommée dans l'ordre (une séquence épuisée fait échouer le test).
    Une requête sans route, ou une séquence épuisée, lève AppelInterdit (BaseException : la fiche ne
    l'absorbe pas) et fait échouer le test.
    """

    def __init__(self) -> None:
        self.appels: list[Appel] = []
        self.attentes: list[float] = []
        self._routes: list[tuple[str, Callable[[httpx.Request], bool] | None, Any]] = []
        self.transport = httpx.MockTransport(self.repondre_a)

    def sleep(self, secondes: float) -> None:
        self.attentes.append(secondes)

    def client(self) -> httpx.Client:
        return oh.make_client(self.transport)

    def route(self, motif: str, reponse: Any, *, si: Callable[[httpx.Request], bool] | None = None) -> Routeur:
        self._routes.append((motif, si, reponse))
        return self

    def appels_vers(self, motif: str) -> list[Appel]:
        return [a for a in self.appels if _motif_correspond(motif, a.cle)]

    def repondre_a(self, requete: httpx.Request) -> httpx.Response:
        cle = f"{requete.url.host}{requete.url.path}"
        self.appels.append(Appel(requete.method, cle, f"{requete.url.scheme}://{cle}",
                                 dict(requete.url.params), requete.headers))
        for motif, si, reponse in reversed(self._routes):
            if _motif_correspond(motif, cle) and (si is None or si(requete)):
                return self._produire(reponse)(requete)
        raise AppelInterdit(f"requête non prévue par le routeur de test : {requete.method} {requete.url}")

    @staticmethod
    def _produire(reponse: Any) -> Callable[[httpx.Request], httpx.Response]:
        if isinstance(reponse, list):
            if not reponse:
                raise AppelInterdit("séquence de réponses épuisée : appel supplémentaire imprévu")
            reponse = reponse.pop(0)
        if isinstance(reponse, BaseException):
            raise reponse
        if isinstance(reponse, type) and issubclass(reponse, BaseException):
            raise reponse("échec simulé")
        return reponse


def _point_du_bien(requete: httpx.Request) -> bool:
    """Vrai si le paramètre `geom` de l'API Carto est le point géocodé du bien : [lon, lat], la longitude d'abord."""
    try:
        geom = json.loads(requete.url.params.get("geom", "null"))
    except ValueError:
        return False
    return geom == {"type": "Point", "coordinates": [LON, LAT]}


# ---------------------------------------------------------------------------
# Réponses des collecteurs réglementaires : urbanisme (API Carto,
# module GPU), bâtiment (BDNB), copropriété (RNIC par l'API tabulaire). Formes réelles réduites, valeurs génériques ;
# les pièges réels sont reproduits : longitude et latitude inversées -> réponse vide sans erreur ; le filtre de commune
# de l'API tabulaire est honoré ; une parcelle sans bâtiment BDNB -> relation vide.
# ---------------------------------------------------------------------------

GPU = "apicarto.ign.fr/api/gpu/"
MOTIF_GPU_COMMUNE = GPU + "municipality"
MOTIF_GPU_DOCUMENT = GPU + "document"
MOTIF_GPU_ZONE = GPU + "zone-urba"
MOTIFS_GPU_PRESCRIPTIONS = (GPU + "prescription-surf", GPU + "prescription-lin", GPU + "prescription-pct")
MOTIF_GPU_SERVITUDES = GPU + "assiette-sup-s"
MOTIFS_URBANISME = (MOTIF_GPU_COMMUNE, MOTIF_GPU_DOCUMENT, MOTIF_GPU_ZONE, *MOTIFS_GPU_PRESCRIPTIONS,
                    MOTIF_GPU_SERVITUDES)
MOTIF_BDNB_RELATION = "api.bdnb.io/v1/bdnb/donnees/rel_batiment_groupe_parcelle"
MOTIF_BDNB_GROUPES = "api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet"
MOTIF_RNIC = "tabular-api.data.gouv.fr/api/resources/3ea8e2c3-0038-464a-b17e-cd5c91f65ce2/data/"
ID_GROUPE_BDNB = "bdnb-bg-TEST-NEMO-0001"

GPU_COMMUNE = {"insee": INSEE, "name": "EXEMPLEVILLE", "is_rnu": False, "is_deleted": False}
GPU_DOCUMENT = {"id": "doc-exempleville-essai", "name": "99001_PLU_20250410", "du_type": "PLU", "gpu_status": "production",
                "gpu_timestamp": "2025-05-21T15:30:56.543Z"}
GPU_ZONE = {"libelle": "Ua1", "libelong": "Centre historique", "typezone": "U", "idurba": "99001_PLU_20250410",
            "datvalid": "20250410", "nomfic": "99001_reglement_20250410.pdf", "gpu_doc_id": "doc-exempleville-essai"}
GPU_PRESCRIPTION_LIN = {"libelle": "Linéaire d'exemple protégé", "txt": None, "typepsc": "22", "stypepsc": "03"}
GPU_AC1 = {"suptype": "ac1", "typeass": "Périmètre des abords", "nomass": "AC1_Eglise-Essai_abor",
           "nomsuplitt": "Eglise d'essai", "modegeoass": "Zone tampon", "paramcalc": 500}
GPU_PM1 = {"suptype": "pm1", "typeass": "Enveloppe des zonages réglementaires", "nomass": "PM1_PPRI_Essai_ass",
           "nomsuplitt": "Plan de prévention des risques d'inondation d'essai", "modegeoass": "Digitalisation",
           "paramcalc": 0}
GROUPE_BDNB = {
    "batiment_groupe_id": ID_GROUPE_BDNB, "annee_construction": 1900, "mat_mur_txt": "PIERRE",
    "materiaux_structure_mur_exterieur": "murs en pierre", "nb_log": 3, "nb_niveau": 3,
    "usage_niveau_1_txt": "Résidentiel collectif", "usage_principal_bdnb_open": "Résidentiel collectif",
    "numero_immat_principal": None, "nb_log_rnc": None, "nb_lot_tertiaire_rnc": None,
}


def reponse_gpu(*proprietes: dict) -> dict:
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None, "properties": p} for p in proprietes]}


def _carre_du_bien(requete: httpx.Request) -> bool:
    """Vrai si `geom` est le carré de ±0,00025° autour du point du bien : un anneau fermé de 5 sommets."""
    try:
        geom = json.loads(requete.url.params.get("geom", "null"))
        anneau = geom["coordinates"][0] if geom["type"] == "Polygon" else None
    except (ValueError, KeyError, TypeError, IndexError):
        return False
    demi = 0.00025
    coins = {(round(x, 6), round(y, 6)) for x in (LON - demi, LON + demi) for y in (LAT - demi, LAT + demi)}
    return (anneau is not None and len(anneau) == 5 and anneau[0] == anneau[-1]
            and {(round(x, 6), round(y, 6)) for x, y in anneau[:4]} == coins)


def _gpu_si(condition: Callable[[httpx.Request], bool], *proprietes: dict) -> Callable[[httpx.Request], httpx.Response]:
    """Réponse de l'API Carto GPU : les entités si la condition tient, sinon un 200 vide sans erreur (piège réel)."""
    return lambda requete: httpx.Response(200, json=reponse_gpu(*(proprietes if condition(requete) else ())))


def ligne_rnic_fiche(numero: str, nord_m: float, refs: tuple = ()) -> dict:
    """Une ligne du RNIC (colonnes de `copropriete.COLONNES`), valeurs génériques, `nord_m` mètres au nord du point."""
    ligne: dict[str, Any] = dict.fromkeys(copropriete.COLONNES)
    ligne.update(
        numero_immatriculation=numero, nom_usage_copropriete=f"Résidence d'essai {numero}",
        adresse_reference="3 Rue de Test", commune=INSEE, longitude=LON, latitude=LAT + nord_m / M_PAR_DEGRE,
        nombre_parcelles=1, nombre_total_lots=6, nombre_lots_habitation=4, nombre_lots_habitation_bureaux_commerces=5,
        nombre_lots_stationnement=2, periode_construction="avant 1949", date_immatriculation="2017-01-15",
        date_derniere_maj="2026-09-30", type_syndic="professionnel", mandat_en_cours="Oui")
    for rang, reference in enumerate(refs, start=1):
        ligne[f"reference_cadastrale_{rang}"] = reference
    return ligne


def _reponse_rnic(requete: httpx.Request) -> httpx.Response:
    """API tabulaire : filtre `commune__exact` honoré, colonnes restreintes à `columns`, une seule page."""
    lignes = [ligne_rnic_fiche("AA0000001", 15, (IDU,)), ligne_rnic_fiche("AA0000002", 35)]
    lignes = [ligne for ligne in lignes if ligne["commune"] == requete.url.params.get("commune__exact")]
    if requete.url.params.get("columns"):
        lignes = [{c: ligne.get(c) for c in requete.url.params["columns"].split(",")} for ligne in lignes]
    return httpx.Response(200, json={"data": lignes, "links": {"next": None, "prev": None},
                                     "meta": {"page": 1, "page_size": 200, "total": len(lignes)}})


def _relation_bdnb(requete: httpx.Request) -> httpx.Response:
    if requete.url.params.get("parcelle_id") != f"eq.{IDU}":  # une autre parcelle : aucun bâtiment BDNB
        return httpx.Response(200, json=[])
    return httpx.Response(200, json=[{"batiment_groupe_id": ID_GROUPE_BDNB, "parcelle_id": IDU,
                                      "parcelle_principale": True}])


def _groupes_bdnb(requete: httpx.Request) -> httpx.Response:
    champs = requete.url.params.get("select", "").split(",")
    trouve = ID_GROUPE_BDNB in requete.url.params.get("batiment_groupe_id", "")
    return httpx.Response(200, json=[{c: GROUPE_BDNB.get(c) for c in champs}] if trouve else [])


def ajouter_routes_reglementaires(r: Routeur) -> Routeur:
    """Les dix appels des trois collecteurs réglementaires, pour le bien générique de `routeur_nominal`."""
    r.route(MOTIF_GPU_COMMUNE, _gpu_si(lambda q: q.url.params.get("insee") == INSEE, GPU_COMMUNE))
    r.route(MOTIF_GPU_DOCUMENT, _gpu_si(_point_du_bien, GPU_DOCUMENT))
    r.route(MOTIF_GPU_ZONE, _gpu_si(_point_du_bien, GPU_ZONE))
    r.route(MOTIFS_GPU_PRESCRIPTIONS[0], _gpu_si(_carre_du_bien))
    r.route(MOTIFS_GPU_PRESCRIPTIONS[1], _gpu_si(_carre_du_bien, GPU_PRESCRIPTION_LIN))
    r.route(MOTIFS_GPU_PRESCRIPTIONS[2], _gpu_si(_carre_du_bien))
    r.route(MOTIF_GPU_SERVITUDES, _gpu_si(_point_du_bien, GPU_AC1, GPU_PM1))
    r.route(MOTIF_BDNB_RELATION, _relation_bdnb)
    r.route(MOTIF_BDNB_GROUPES, _groupes_bdnb)
    r.route(MOTIF_RNIC, _reponse_rnic)
    return r


def routeur_nominal() -> Routeur:
    """Routeur « tout va bien » pour l'adresse générique, qui reproduit les pièges réels des API :
    un mauvais paramètre renvoie la réponse piège (500, 404, 6 582 PPRN, 9,5 M de lignes DPE...)."""
    r = Routeur()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_housenumber.json")))

    # Cadastre : hors du bon point, l'API Carto répond 200 avec des
    # parcelles quelconques d'une autre commune (piège réel) ; seul le point exact du bien rend sa parcelle.
    r.route(MOTIF_CADASTRE, rep_json(reponse_carto(
        parcelle_carto(idu="99999000ZZ9999", code_insee="99999", nom_com="Ailleurs"))))
    r.route(MOTIF_CADASTRE, rep_json(reponse_carto(parcelle_carto())), si=_point_du_bien)

    for type_local, rid in RESSOURCES_ATTENDUES.items():
        def loyers_commune(requete, _t=type_local):
            fichier = FIXTURES_LOYERS[_t] if requete.url.params.get("INSEE_C__exact") == INSEE \
                else "loyers_commune_absente.json"
            return httpx.Response(200, json=fx(fichier))
        r.route(motif_loyers(rid), loyers_commune)

    r.route(MOTIF_DVF + "*", rep_statut(404))
    r.route(url_dvf(2024), rep_csv(fx_texte("dvf_synthetique_2024.csv")))
    r.route(url_dvf(2025), rep_csv(fx_texte("dvf_synthetique_2025.csv")))

    r.route(MOTIF_DPE, rep_json(fx("dpe_adresse_ignoree.json")))  # qs mal formé : filtre ignoré
    r.route(MOTIF_DPE, rep_json(fx("dpe_commune_total.json")),
            si=lambda q: q.url.params.get("qs") == f'code_insee_ban:"{INSEE}"')
    r.route(MOTIF_DPE, rep_json(fx("dpe_adresse.json")),
            si=lambda q: q.url.params.get("qs") == f'adresse_ban:"{LABEL}"')

    r.route(MOTIF_RISQUES, rep_statut(500))  # `codeInsee` camelCase : erreur 500 réelle
    r.route(MOTIF_RISQUES, rep_json(fx("georisques_commune.json")),
            si=lambda q: q.url.params.get("code_insee") == INSEE)
    r.route(MOTIF_RAPPORT, rep_statut(404))  # latlon inversé : 404 réel
    r.route(MOTIF_RAPPORT, rep_json(fx("georisques_rapport_risque.json")),
            si=lambda q: q.url.params.get("latlon") == f"{LON},{LAT}")
    r.route(MOTIF_PPRN, rep_json(fx("georisques_pprn_hors_filtre.json")))  # code_insee ignoré : tout le pays
    r.route(MOTIF_PPRN, rep_json(fx("georisques_pprn_99001.json")),
            si=lambda q: q.url.params.get("codeInsee") == INSEE)
    r.route(MOTIF_PPRN_DETAIL + "99DDT20000001", rep_json(fx("georisques_pprn_detail_99DDT20000001.json")))

    def fiscalite(requete):
        fichier = "fiscalite_locale_99001.json" if requete.url.params.get("where") == f'insee_com="{INSEE}"' \
            else "fiscalite_locale_vide.json"
        return httpx.Response(200, json=fx(fichier))
    r.route(MOTIF_FISCALITE, fiscalite)
    ajouter_routes_reglementaires(r)  # urbanisme, bâtiment, copropriété
    return r


def fiche_nominale(r: Routeur | None = None, **kw: Any) -> tuple[dict, Routeur]:
    r = r or routeur_nominal()
    kw.setdefault("maintenant", MAINTENANT)
    fiche = fiche_mod.construire_fiche(ADRESSE, client=r.client(), sleep=r.sleep, **kw)
    return fiche, r


def blocs_erreurs(fiche: dict) -> list[str]:
    return [e["bloc"] for e in fiche["erreurs"]]


def assert_aucun_faux_zero(fiche: dict) -> None:
    """Une donnée absente est None : jamais un 0, un {} ou un [] à la place d'un bloc."""
    for cle in ("loyers", "dvf", "dpe", "risques", "fiscalite_locale"):
        assert fiche[cle] is None or fiche[cle] not in (0, {}, [], ""), f"faux vide dans {cle}"


@pytest.fixture(scope="module")
def script():
    chemin = RACINE / "scripts" / "immo_fiche_opendata.py"
    spec = importlib.util.spec_from_file_location("immo_fiche_opendata_test", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Constructeur de CSV DVF (en-tête RÉELLE à 40 colonnes, lue dans la fixture)
# ---------------------------------------------------------------------------

DVF_COLONNES = tuple(fx_texte("dvf_synthetique_2025.csv").splitlines()[0].split(","))
M_PAR_DEGRE = 6_371_000 * math.pi / 180  # mètres par degré de latitude (R = 6 371 000 m)
CODES_TYPE_LOCAL = {"Maison": "1", "Appartement": "2", "Dépendance": "3",
                    "Local industriel. commercial ou assimilé": "4"}


def _local(type_local: str, surface: Any = "", pieces: Any = "", *, lot: str = "", culture: str = "",
           parcelle: str | None = None, autres_lots: tuple[str, ...] = ()) -> dict[str, Any]:
    """`autres_lots` : numéros des lots 2 à 5 (dans l'ordre), pour exercer chaque composante de la clé."""
    return {"type_local": type_local, "surface": str(surface), "pieces": str(pieces), "lot": lot,
            "culture": culture, "parcelle": parcelle, "autres_lots": tuple(autres_lots)}


def maison(surface: Any = 100, pieces: Any = 4, *, culture: str = "sols", parcelle: str | None = None):
    return _local("Maison", surface, pieces, culture=culture, parcelle=parcelle)


def appart(surface: Any = 60, pieces: Any = 3, *, lot: str = "1", parcelle: str | None = None,
           autres_lots: tuple[str, ...] = ()):
    return _local("Appartement", surface, pieces, lot=lot, parcelle=parcelle, autres_lots=autres_lots)


def dependance(surface: Any = ""):
    return _local("Dépendance", surface, 0)


def commercial(surface: Any = 40):
    return _local("Local industriel. commercial ou assimilé", surface, 0, culture="sols")


def terrain(parcelle: str | None = None):
    """Ligne de terrain (type_local vide), comme les « jardins » rattachés à une maison dans les données."""
    return _local("", culture="jardins", parcelle=parcelle)


def mutation(id_mutation: str, locaux: list[dict], *, date_mutation: str = "2025-11-20",
             nature: str = "Vente", valeur: Any = "200000", nord_m: float = 100.0, est_m: float = 0.0,
             numero: str = "1", suffixe: str = "", voie: str = "RUE DE TEST", longitude: str | None = None,
             latitude: str | None = None) -> list[dict[str, str]]:
    """Lignes DVF d'une mutation : une ligne par local (ou par nature de culture), valeur répétée.
    Le point est `nord_m` mètres au nord (négatif : au sud) et `est_m` mètres à l'est (négatif : à
    l'ouest) du point géocodé ; une valeur explicite de `longitude` / `latitude` (même vide) remplace la
    coordonnée calculée. Un décalage en longitude est divisé par cos(latitude) : un décalage est-ouest
    n'est mesuré correctement que si la latitude et la longitude sont bien passées dans l'ordre à haversine."""
    lignes = []
    for lo in locaux:
        ligne = dict.fromkeys(DVF_COLONNES, "")
        ligne.update({
            "id_mutation": id_mutation, "date_mutation": date_mutation, "numero_disposition": "000001",
            "nature_mutation": nature, "valeur_fonciere": str(valeur), "adresse_numero": numero,
            "adresse_suffixe": suffixe, "adresse_nom_voie": voie, "adresse_code_voie": "0001",
            "code_postal": "99100", "code_commune": INSEE, "nom_commune": "Exempleville", "code_departement": "99",
            "id_parcelle": lo["parcelle"] or f"{INSEE}000{id_mutation[-6:]}",
            "nombre_lots": "1" if lo["lot"] else "0", "code_type_local": CODES_TYPE_LOCAL.get(lo["type_local"], ""),
            "type_local": lo["type_local"], "surface_reelle_bati": lo["surface"],
            "nombre_pieces_principales": lo["pieces"], "nature_culture": lo["culture"],
            "lot1_numero": lo["lot"],
            "longitude": f"{LON + est_m / (M_PAR_DEGRE * math.cos(math.radians(LAT))):.6f}"
            if longitude is None else longitude,
            "latitude": f"{LAT + nord_m / M_PAR_DEGRE:.6f}" if latitude is None else latitude,
        })
        for rang, numero_lot in enumerate(lo["autres_lots"], start=2):
            ligne[f"lot{rang}_numero"] = numero_lot
        lignes.append(ligne)
    return lignes


def csv_dvf(*mutations: list[dict[str, str]]) -> str:
    tampon = io.StringIO()
    ecrivain = csv.DictWriter(tampon, fieldnames=DVF_COLONNES, lineterminator="\n")
    ecrivain.writeheader()
    for lignes in mutations:
        ecrivain.writerows(lignes)
    return tampon.getvalue()


def routeur_dvf(csv_par_annee: dict[int, str | int]) -> Routeur:
    """Routeur DVF seul : CSV (str) ou code HTTP (int) par année ; toute autre année répond 404."""
    r = Routeur()
    r.route(MOTIF_DVF + "*", rep_statut(404))
    for annee, contenu in csv_par_annee.items():
        r.route(url_dvf(annee), rep_statut(contenu) if isinstance(contenu, int) else rep_csv(contenu))
    return r


def collecter_dvf(csv_par_annee: dict[int, str | int], *, geo: dict | None = None, **kw: Any):
    r = routeur_dvf(csv_par_annee)
    kw.setdefault("aujourdhui", AUJOURDHUI)
    resultat = dvf.collecter(r.client(), geo or GEO, sleep=r.sleep, **kw)
    return resultat, r


def ids_comparables(resultat) -> list[str]:
    return [c["id_mutation"] for c in resultat.bloc["comparables"]]


# ===========================================================================
# 21. Garde « aucun appel réseau » et intégrité des fixtures
# ===========================================================================

def test_garde_reseau_la_fixture_autouse_est_active():
    """Un httpx.Client SANS transport mock qui tente un GET lève AppelInterdit (pas d'appel réel)."""
    with httpx.Client() as client:
        with pytest.raises(AppelInterdit, match="réseau interdit"):
            client.get("https://data.geopf.fr/geocodage/search")


def test_routeur_sans_route_fait_echouer_le_test():
    """Le routeur ne répond jamais par défaut : une requête imprévue est un échec visible."""
    r = Routeur()
    with pytest.raises(AppelInterdit, match="non prévue"):
        r.client().get("https://api.test/imprevu")


def test_fixtures_a_plat_json_valides_et_csv_a_40_colonnes():
    entrees = sorted(e for e in FIXTURES.iterdir() if not e.name.startswith("."))
    assert entrees, "aucune fixture"
    assert all(e.is_file() for e in entrees), "pas de sous-dossier : .gitignore ignore tout dossier data/"
    assert not [e for e in entrees if e.suffix == ".xlsx"]
    assert len(DVF_COLONNES) == 40
    for e in entrees:
        if e.suffix == ".json":
            json.loads(e.read_text(encoding="utf-8"))
        elif e.suffix == ".csv":
            lignes = list(csv.reader(io.StringIO(e.read_text(encoding="utf-8"))))
            assert tuple(lignes[0]) == DVF_COLONNES, e.name
            assert {len(ligne) for ligne in lignes} == {40}, e.name
        else:
            pytest.fail(f"type de fixture inattendu : {e.name}")


# ===========================================================================
# 20. Garde de compatibilité Python 3.11
# ===========================================================================

_MODULES_PRODUCTION = [
    "src/opendata/__init__.py", "src/opendata/http.py", "src/opendata/geocodage.py",
    "src/opendata/loyers.py", "src/opendata/dvf.py", "src/opendata/dpe.py",
    "src/opendata/georisques.py", "src/opendata/fiscalite_locale.py", "src/opendata/fiche.py",
    "scripts/immo_fiche_opendata.py",
]
# Tout module ajouté sous src/opendata est gardé lui aussi.
FICHIERS_PRODUCTION = sorted(
    set(_MODULES_PRODUCTION) | {p.relative_to(RACINE).as_posix() for p in (RACINE / "src/opendata").glob("*.py")})


@pytest.mark.parametrize("chemin", FICHIERS_PRODUCTION)
def test_syntaxe_python_311_maximum(chemin):
    source = (RACINE / chemin).read_text(encoding="utf-8")
    ast.parse(source, filename=chemin, feature_version=(3, 11))


@pytest.mark.parametrize("chemin", [c for c in FICHIERS_PRODUCTION if not c.endswith("__init__.py")])
def test_from_future_annotations_en_tete(chemin):
    source = (RACINE / chemin).read_text(encoding="utf-8")
    assert "from __future__ import annotations" in source


@pytest.mark.parametrize("source", ["type X = int", "def f[T](x: T) -> T: return x"])
def test_la_garde_311_detecte_bien_la_syntaxe_312(source):
    """Garde de la garde : feature_version=(3, 11) rejette bien PEP 695 (type X, def f[T])."""
    with pytest.raises(SyntaxError):
        ast.parse(source, feature_version=(3, 11))


# ===========================================================================
# 13. Socle HTTP : retry, 404, 4xx, User-Agent, corps non JSON
# ===========================================================================

URL_TEST = "https://api.test/ressource"
MOTIF_TEST = "api.test/ressource"


def test_http_constantes_du_contrat():
    assert oh.USER_AGENT == "immo-locatif-opendata/1.0"
    assert oh.TIMEOUT_S == 30.0
    assert oh.TENTATIVES == 3
    assert tuple(oh.ATTENTES_S) == (1, 2)
    assert issubclass(oh.NotFound, oh.OpendataError)


def test_make_client_timeout_redirections_et_user_agent():
    client = oh.make_client()
    try:
        assert client.follow_redirects is True
        assert client.timeout == httpx.Timeout(30.0)
        assert client.headers["User-Agent"] == "immo-locatif-opendata/1.0"
    finally:
        client.close()


def test_get_json_succes_envoie_user_agent_et_parametres_sans_attente():
    r = Routeur().route(MOTIF_TEST, rep_json({"ok": 1}))
    assert oh.get_json(r.client(), URL_TEST, {"a": "1", "b": "x y"}, sleep=r.sleep) == {"ok": 1}
    assert len(r.appels) == 1
    assert r.appels[0].methode == "GET"
    assert r.appels[0].params == {"a": "1", "b": "x y"}
    assert r.appels[0].entetes["user-agent"] == "immo-locatif-opendata/1.0"
    assert r.attentes == []


def test_get_text_succes_rend_le_corps_accents_conserves_et_user_agent():
    r = Routeur().route(MOTIF_TEST, rep_texte("a,b\nDépendance,é\n"))
    assert oh.get_text(r.client(), URL_TEST, sleep=r.sleep) == "a,b\nDépendance,é\n"
    assert r.appels[0].entetes["user-agent"] == "immo-locatif-opendata/1.0"


GETTERS = [
    pytest.param(oh.get_json, rep_json({"v": 1}), {"v": 1}, id="get_json"),
    pytest.param(oh.get_text, rep_texte("corps é"), "corps é", id="get_text"),
]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
@pytest.mark.parametrize("classe", [httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout])
def test_get_deux_echecs_de_transport_puis_succes(fonction, ok, attendu, classe):
    r = Routeur().route(MOTIF_TEST, [classe("échec 1"), classe("échec 2"), ok])
    assert fonction(r.client(), URL_TEST, sleep=r.sleep) == attendu
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
@pytest.mark.parametrize("classe", [httpx.ConnectError, httpx.ReadError])
def test_get_trois_echecs_de_transport_leve_opendata_error(fonction, ok, attendu, classe):
    r = Routeur().route(MOTIF_TEST, classe)  # classe : relevée à chaque appel
    with pytest.raises(oh.OpendataError, match="api.test") as exc:
        fonction(r.client(), URL_TEST, sleep=r.sleep)
    assert not isinstance(exc.value, oh.NotFound)
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
@pytest.mark.parametrize("statut", [500, 502, 503, 504])
def test_get_http_5xx_rejoue_puis_succes(fonction, ok, attendu, statut):
    r = Routeur().route(MOTIF_TEST, [rep_statut(statut), ok])
    assert fonction(r.client(), URL_TEST, sleep=r.sleep) == attendu
    assert len(r.appels) == 2
    assert r.attentes == [1]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
def test_get_http_500_persistant_leve_apres_trois_appels(fonction, ok, attendu):
    r = Routeur().route(MOTIF_TEST, rep_statut(500))
    with pytest.raises(oh.OpendataError, match="api.test") as exc:
        fonction(r.client(), URL_TEST, sleep=r.sleep)
    assert not isinstance(exc.value, oh.NotFound)
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
@pytest.mark.parametrize("statut", [400, 401, 403])  # 429 en est sorti : il se rejoue
def test_get_4xx_non_rejoue_un_seul_appel(fonction, ok, attendu, statut):
    r = Routeur().route(MOTIF_TEST, rep_statut(statut))
    with pytest.raises(oh.OpendataError) as exc:
        fonction(r.client(), URL_TEST, sleep=r.sleep)
    assert not isinstance(exc.value, oh.NotFound)
    assert len(r.appels) == 1
    assert r.attentes == []


# --- 429 : rejoué, attente = Retry-After plafonné, sinon le barème ------------

def rep_429(retry_after: str | None = None, statut: int = 429) -> Callable[[httpx.Request], httpx.Response]:
    entetes = {} if retry_after is None else {"retry-after": retry_after}
    return lambda requete: httpx.Response(statut, headers=entetes, content=b"trop de requetes")


def test_http_retry_after_max_est_de_30_secondes():
    assert oh.RETRY_AFTER_MAX_S == 30


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
def test_get_429_puis_200_reussit_et_attend_la_valeur_de_retry_after(fonction, ok, attendu):
    r = Routeur().route(MOTIF_TEST, [rep_429("7"), ok])
    assert fonction(r.client(), URL_TEST, sleep=r.sleep) == attendu
    assert len(r.appels) == 2
    assert r.attentes == [7]  # Retry-After, pas le 1 s du barème


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
def test_get_429_sans_retry_after_suit_le_bareme(fonction, ok, attendu):
    r = Routeur().route(MOTIF_TEST, [rep_429(), rep_429(), ok])
    assert fonction(r.client(), URL_TEST, sleep=r.sleep) == attendu
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]


@pytest.mark.parametrize("retry_after, attente", [("0", 0), ("29", 29), ("30", 30), ("31", 30), ("120", 30)])
def test_get_429_retry_after_est_plafonne_a_30_secondes(retry_after, attente):
    r = Routeur().route(MOTIF_TEST, [rep_429(retry_after), rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [attente]


@pytest.mark.parametrize("retry_after", ["Wed, 21 Oct 2026 07:28:00 GMT", "abc", "-5", "1.5", ""],
                         ids=["date_http", "texte", "negatif", "decimal", "vide"])
def test_get_429_retry_after_illisible_retombe_sur_le_bareme(retry_after):
    r = Routeur().route(MOTIF_TEST, [rep_429(retry_after), rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [1]


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
def test_get_429_a_chaque_essai_leve_opendata_error_qui_nomme_429(fonction, ok, attendu):
    r = Routeur().route(MOTIF_TEST, rep_429("2"))
    with pytest.raises(oh.OpendataError, match="429") as exc:
        fonction(r.client(), URL_TEST, sleep=r.sleep)
    assert not isinstance(exc.value, oh.NotFound)
    assert "api.test" in str(exc.value)
    assert len(r.appels) == oh.TENTATIVES == 3  # rejoué dans la limite de TENTATIVES, pas plus
    assert r.attentes == [2, 2]  # aucune attente après le dernier essai


def test_get_retry_after_d_un_429_ne_sert_pas_a_l_attente_suivante():
    """429 (Retry-After 7) puis 500 : la seconde attente est celle du barème (2 s), pas encore 7 s."""
    r = Routeur().route(MOTIF_TEST, [rep_429("7"), rep_statut(500), rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [7, 2]


def test_get_retry_after_n_est_lu_que_sur_un_429():
    r = Routeur().route(MOTIF_TEST, [rep_429("9", statut=503), rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [1]  # 503 : barème, l'en-tête est ignoré


@pytest.mark.parametrize("fonction, ok, attendu", GETTERS)
def test_get_404_leve_notfound_immediatement_sans_retry(fonction, ok, attendu):
    r = Routeur().route(MOTIF_TEST, rep_statut(404))
    with pytest.raises(oh.NotFound):
        fonction(r.client(), URL_TEST, sleep=r.sleep)
    assert len(r.appels) == 1
    assert r.attentes == []


def test_get_json_corps_non_json_leve_opendata_error():
    r = Routeur().route(MOTIF_TEST, rep_texte("<html>pas du json</html>"))
    with pytest.raises(oh.OpendataError):
        oh.get_json(r.client(), URL_TEST, sleep=r.sleep)


# ===========================================================================
# 1. Géocodage (+ 16 : échecs)
# ===========================================================================

def test_geocodage_constantes_du_contrat():
    assert geocodage.URL == "https://data.geopf.fr/geocodage/search"
    assert geocodage.SCORE_MIN == 0.5


def test_geocoder_housenumber_ordre_lon_lat_citycode_chaine_et_requete():
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_housenumber.json")))
    geo = geocodage.geocoder(r.client(), ADRESSE, sleep=r.sleep)
    assert geo == GEO
    assert geo["lon"] == 1.5021 and geo["lat"] == 47.5013  # coordinates = [lon, lat] : longitude d'abord
    assert isinstance(geo["citycode"], str)
    assert len(r.appels) == 1
    assert r.appels[0].params == {"q": ADRESSE, "limit": "5"}  # ancien attendu : "limit": "1"


def test_geocoder_type_municipality_propage():
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_commune.json")))
    geo = geocodage.geocoder(r.client(), "Exempleville 99100", sleep=r.sleep)
    assert geo == GEO_COMMUNE
    assert geo["type"] == "municipality"


def test_geocoder_postcode_et_city_absents_donnent_none():
    payload = fx("geocodage_housenumber.json")
    for cle in ("postcode", "city"):
        del payload["features"][0]["properties"][cle]
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(payload))
    # Adresse SANS code postal (ancien appel : ADRESSE) : avec 99100, un candidat sans `postcode` n'est jamais
    # concordant et le contrôle de commune lève (voir test_geocodage_un_candidat_sans_postcode_n_est_jamais_concordant).
    geo = geocodage.geocoder(r.client(), "1 rue de test Exempleville", sleep=r.sleep)
    assert geo["postcode"] is None and geo["city"] is None
    assert geo["citycode"] == INSEE


def test_geocoder_features_vide_leve_opendata_error():
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    with pytest.raises(oh.OpendataError):
        geocodage.geocoder(r.client(), "zzzz qqqq", sleep=r.sleep)


def test_geocoder_http_500_persistant_leve_apres_trois_appels():
    r = Routeur().route(MOTIF_GEOCODAGE, rep_statut(500))
    with pytest.raises(oh.OpendataError):
        geocodage.geocoder(r.client(), ADRESSE, sleep=r.sleep)
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]


@pytest.mark.parametrize("payload", [
    {},
    {"features": [{"properties": {"label": "x", "score": 0.9, "citycode": INSEE, "type": "street"}}]},
    {"features": [{"geometry": {"coordinates": [1.50]},
                   "properties": {"label": "x", "score": 0.9, "citycode": INSEE, "type": "street"}}]},
    {"features": [{"geometry": {"coordinates": [1.50, 47.50]}, "properties": {"label": "x"}}]},
], ids=["sans_features", "sans_geometrie", "coordonnees_trop_courtes", "proprietes_manquantes"])
def test_geocoder_forme_inattendue_leve_opendata_error_pas_keyerror(payload):
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(payload))
    with pytest.raises(oh.OpendataError):
        geocodage.geocoder(r.client(), ADRESSE, sleep=r.sleep)


# ===========================================================================
# 1. Loyers (carte des loyers 2025)
# ===========================================================================

# Surfaces de référence : « caractéristiques de référence » de la description du jeu sur data.gouv.fr, relue
# le 2026-10-04 (appartement toutes typologies 52 m2, T1-T2 37 m2, T3 et plus 72 m2, maison 92 m2).
SURFACES_TYPES_ATTENDUES = {"appartement": 52, "appartement_t1_t2": 37, "appartement_t3_plus": 72, "maison": 92}
SOURCE_SURFACES_ATTENDUE = ("https://www.data.gouv.fr/datasets/"
                            "carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025 "
                            "(description du jeu, lue le 2026-10-04)")

ATTENDU_LOYERS = {
    "appartement": {"valeur_m2": 12.2718, "ip_bas": 9.8833, "ip_haut": 15.0412,
                    "n": 1210, "maille": "commune", "millesime": "2025", "n_commune": 1210, "n_maille": 1302,
                    "charges": "comprises", "surface_type_m2": 52, "surface_type_source": SOURCE_SURFACES_ATTENDUE},
    "appartement_t1_t2": {"valeur_m2": 13.9047, "ip_bas": 11.2214,
                          "ip_haut": 16.8813, "n": 811, "maille": "commune", "millesime": "2025",
                          "n_commune": 811, "n_maille": 905, "charges": "comprises", "surface_type_m2": 37,
                          "surface_type_source": SOURCE_SURFACES_ATTENDUE},
    "appartement_t3_plus": {"valeur_m2": 11.4125, "ip_bas": 9.0371,
                            "ip_haut": 14.2902, "n": 402, "maille": "commune", "millesime": "2025",
                            "n_commune": 402, "n_maille": 470, "charges": "comprises", "surface_type_m2": 72,
                            "surface_type_source": SOURCE_SURFACES_ATTENDUE},
    "maison": {"valeur_m2": 9.6234, "ip_bas": 7.7105, "ip_haut": 12.0381,
               "n": 256, "maille": "commune", "millesime": "2025", "n_commune": 256, "n_maille": 421,
               "charges": "comprises", "surface_type_m2": 92, "surface_type_source": SOURCE_SURFACES_ATTENDUE},
}


def test_loyers_constantes_ressources_et_millesime():
    assert loyers.RESSOURCES == RESSOURCES_ATTENDUES
    assert loyers.MILLESIME == "2025"
    assert loyers.URL == "https://tabular-api.data.gouv.fr/api/resources/{rid}/data/"


def test_loyers_quatre_types_maille_commune_cles_a_point_et_n_nbobs_com():
    """lwr.IPm2 / upr.IPm2 (clés à point) lues telles quelles ; maille « commune » : n = nbobs_com."""
    res = loyers.collecter(routeur_nominal().client(), GEO)
    assert set(res.bloc) == set(RESSOURCES_ATTENDUES)
    assert res.bloc == ATTENDU_LOYERS
    assert res.erreurs == []
    assert all(isinstance(v["n"], int) for v in res.bloc.values())


def test_loyers_chaque_typologie_dit_charges_comprises_et_pour_quelle_surface_type():
    """Le loyer d'annonce est charges comprises, pour un bien type : les 4 typologies portent les 3 clés."""
    res = loyers.collecter(routeur_nominal().client(), GEO)
    assert set(res.bloc) == set(SURFACES_TYPES_ATTENDUES)
    for type_local, bloc in res.bloc.items():
        assert {"charges", "surface_type_m2", "surface_type_source"} <= set(bloc), type_local
        assert bloc["charges"] == "comprises"
        assert bloc["surface_type_m2"] == SURFACES_TYPES_ATTENDUES[type_local]
        assert bloc["surface_type_source"] == SOURCE_SURFACES_ATTENDUE


def test_loyers_surface_type_absente_du_texte_donne_null_et_source_null(monkeypatch):
    """Une surface qui n'est pas dans le texte relu n'est pas inventée : surface et source valent null, ensemble.
    Les autres typologies et les clés de loyer ne sont pas touchées."""
    monkeypatch.delitem(loyers.SURFACES_TYPES_M2, "maison")
    res = loyers.collecter(routeur_nominal().client(), GEO)
    assert res.bloc["maison"]["surface_type_m2"] is None and res.bloc["maison"]["surface_type_source"] is None
    assert res.bloc["maison"]["charges"] == "comprises"
    assert res.bloc["maison"]["valeur_m2"] == ATTENDU_LOYERS["maison"]["valeur_m2"]
    assert res.bloc["appartement"] == ATTENDU_LOYERS["appartement"]


def test_loyers_requetes_une_par_ressource_avec_insee_exact():
    r = routeur_nominal()
    loyers.collecter(r.client(), GEO, sleep=r.sleep)
    for rid in RESSOURCES_ATTENDUES.values():
        appels = r.appels_vers(motif_loyers(rid))
        assert len(appels) == 1
        assert appels[0].url == f"https://{motif_loyers(rid)}"
        assert appels[0].params == {"INSEE_C__exact": INSEE}


def test_loyers_sources_une_par_ressource_obtenue():
    res = loyers.collecter(routeur_nominal().client(), GEO)
    assert len(res.sources) == 4
    for s in res.sources:
        assert s["bloc"] == "loyers"
        assert s["millesime"] == "2025"
        for mot in ("Licence Ouverte 2.0", "ANIL", "SeLoger", "leboncoin"):
            assert mot in s["licence"]
    urls = {s["url"] for s in res.sources}
    assert all(s.startswith("https://tabular-api.data.gouv.fr/api/resources/") for s in urls)
    assert all(any(rid in u for u in urls) for rid in RESSOURCES_ATTENDUES.values())


def test_loyers_maille_elargie_utilise_nbobs_mail_comme_n():
    r = routeur_nominal()
    r.route(motif_loyers(RESSOURCES_ATTENDUES["appartement"]), rep_json(fx("loyers_maille_synthetique.json")))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["appartement"] == {
        "valeur_m2": 12.5, "ip_bas": 9.75, "ip_haut": 15.25, "n": 212, "maille": "maille",
        "millesime": "2025", "n_commune": 7, "n_maille": 212,
        "charges": "comprises", "surface_type_m2": 52, "surface_type_source": SOURCE_SURFACES_ATTENDUE,
    }
    assert res.bloc["maison"] == ATTENDU_LOYERS["maison"]  # les autres types ne sont pas touchés


def test_loyers_commune_absente_donne_none_et_erreur_les_autres_restent():
    r = routeur_nominal()
    r.route(motif_loyers(RESSOURCES_ATTENDUES["appartement"]), rep_json(fx("loyers_commune_absente.json")))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["appartement"] is None
    for type_local in ("appartement_t1_t2", "appartement_t3_plus", "maison"):
        assert res.bloc[type_local] == ATTENDU_LOYERS[type_local]
    assert [e["bloc"] for e in res.erreurs] == ["loyers.appartement"]
    assert INSEE in res.erreurs[0]["message"] and "absente" in res.erreurs[0]["message"]
    assert len(res.sources) == 3  # une source par ressource OBTENUE


def test_loyers_toutes_communes_absentes_quatre_none_quatre_erreurs_aucune_source():
    r = Routeur()
    for rid in RESSOURCES_ATTENDUES.values():
        r.route(motif_loyers(rid), rep_json(fx("loyers_commune_absente.json")))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc == dict.fromkeys(RESSOURCES_ATTENDUES)
    assert sorted(e["bloc"] for e in res.erreurs) == sorted(f"loyers.{t}" for t in RESSOURCES_ATTENDUES)
    assert res.sources == []


def test_loyers_erreur_http_sur_un_type_n_arrete_pas_les_autres():
    r = routeur_nominal()
    r.route(motif_loyers(RESSOURCES_ATTENDUES["maison"]), rep_statut(500))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["maison"] is None
    for type_local in ("appartement", "appartement_t1_t2", "appartement_t3_plus"):
        assert res.bloc[type_local] == ATTENDU_LOYERS[type_local]
    assert [e["bloc"] for e in res.erreurs] == ["loyers.maison"]
    assert r.attentes == [1, 2]
    assert len(res.sources) == 3


def test_loyers_forme_inattendue_donne_none_et_erreur_pas_keyerror():
    ligne_sans_loyer = fx(FIXTURES_LOYERS["maison"])
    del ligne_sans_loyer["data"][0]["loypredm2"]
    r = routeur_nominal()
    r.route(motif_loyers(RESSOURCES_ATTENDUES["maison"]), rep_json(ligne_sans_loyer))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["maison"] is None
    assert [e["bloc"] for e in res.erreurs] == ["loyers.maison"]


def test_loyers_ligne_d_une_autre_commune_filtre_ignore_donne_none_et_erreur():
    """Si le serveur ignorait INSEE_C__exact, data[0] serait la ligne d'une autre commune : le loyer de
    Grandbourg-Exemple présenté pour Exempleville. La garde compare INSEE_C à la commune demandée."""
    autre_commune = fx(FIXTURES_LOYERS["maison"])
    autre_commune["data"][0]["INSEE_C"] = "99003"
    r = routeur_nominal()
    r.route(motif_loyers(RESSOURCES_ATTENDUES["maison"]), rep_json(autre_commune))
    res = loyers.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["maison"] is None
    assert [e["bloc"] for e in res.erreurs] == ["loyers.maison"]
    assert "ignor" in res.erreurs[0]["message"] and "99003" in res.erreurs[0]["message"]
    assert len(res.sources) == 3  # pas de source pour une valeur qui n'a pas été livrée
    assert res.bloc["appartement"] == ATTENDU_LOYERS["appartement"]  # les autres types ne sont pas touchés


# ===========================================================================
# 1-8. DVF : fonctions pures
# ===========================================================================

@pytest.mark.parametrize("insee, attendu", [
    ("99001", "99"), ("75101", "75"), ("2A004", "2A"), ("97411", "974"), ("97101", "971"),
])
def test_dvf_departement(insee, attendu):
    assert dvf.departement(insee) == attendu


@pytest.mark.parametrize("aujourdhui, fenetre, attendu", [
    (date(2026, 10, 3), 24, date(2024, 10, 3)),
    (date(2026, 10, 3), 12, date(2025, 10, 3)),
    (date(2026, 3, 31), 1, date(2026, 2, 28)),    # fin de mois : 31 mars - 1 mois -> 28 février
    (date(2024, 3, 31), 1, date(2024, 2, 29)),    # année bissextile
    (date(2026, 5, 31), 3, date(2026, 2, 28)),
    (date(2026, 8, 31), 6, date(2026, 2, 28)),
    (date(2026, 1, 15), 1, date(2025, 12, 15)),   # franchissement d'année
    (date(2028, 2, 29), 12, date(2027, 2, 28)),   # 29 février - 12 mois
    (date(2026, 10, 3), 36, date(2023, 10, 3)),
], ids=lambda v: str(v))
def test_dvf_date_debut_fenetre(aujourdhui, fenetre, attendu):
    assert dvf.date_debut_fenetre(aujourdhui, fenetre) == attendu


@pytest.mark.parametrize("aujourdhui, fenetre, attendu", [
    (date(2026, 10, 3), 24, [2024, 2025, 2026]),
    (date(2026, 10, 3), 12, [2025, 2026]),
    (date(2026, 10, 3), 9, [2026]),               # début 2026-01-03
    (date(2026, 10, 3), 36, [2023, 2024, 2025, 2026]),
    (date(2026, 3, 31), 1, [2026]),
    (date(2026, 1, 15), 1, [2025, 2026]),
], ids=lambda v: str(v))
def test_dvf_annees_couvrantes(aujourdhui, fenetre, attendu):
    assert dvf.annees_couvrantes(aujourdhui, fenetre) == attendu


def test_haversine_un_degre_de_latitude_vaut_111194_93_m_rayon_6371000():
    """R = 6 371 000 m : un degré d'arc = R x pi / 180 = 111 194,93 m. Le rayon moyen 6 371 008,8 m
    donnerait 111 195,08 m, hors de la tolérance."""
    assert dvf.haversine_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(111_194.93, abs=0.01)
    assert dvf.haversine_m(47.5013, 1.5021, 47.5013, 1.5021) == 0.0


def test_haversine_ordre_des_arguments_lat1_lon1_lat2_lon2_et_symetrie():
    # Un degré de longitude à 60 N : 2 R asin(cos 60 deg x sin 0,5 deg) = 55 596,93 m (et non 111 195 m).
    assert dvf.haversine_m(60.0, 0.0, 60.0, 1.0) == pytest.approx(55_596.93, abs=0.01)
    assert dvf.haversine_m(60.0, 0.0, 60.0, 1.0) == pytest.approx(dvf.haversine_m(60.0, 1.0, 60.0, 0.0))


# ===========================================================================
# 2-3. DVF : redirection, années absentes, erreurs
# ===========================================================================

def test_dvf_redirection_302_suivie_puis_csv_lu():
    csv_2025 = csv_dvf(mutation("2025-910001", [maison(100, 4)], nord_m=100))
    r = routeur_dvf({})
    r.route(url_dvf(2025), rep_redirection("https://static.test/dvf/2025_99001.csv"))
    r.route("static.test/dvf/2025_99001.csv", rep_csv(csv_2025))
    res = dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep)
    assert [a.cle for a in r.appels if a.cle in (url_dvf(2025), "static.test/dvf/2025_99001.csv")] == [
        url_dvf(2025), "static.test/dvf/2025_99001.csv"]
    assert res.bloc["compteurs"]["retenues"] == 1
    assert ids_comparables(res) == ["2025-910001"]


def test_dvf_404_est_une_annee_absente_comptee_pas_une_erreur():
    res, r = collecter_dvf({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})
    assert res.bloc["compteurs"]["annees_absentes"] == 1
    assert res.bloc["parametres"]["annees_absentes"] == [2026]
    assert res.bloc["parametres"]["annees"] == [2024, 2025, 2026]
    assert res.erreurs == []
    assert r.attentes == []  # un 404 ne se rejoue pas


def test_dvf_toutes_annees_absentes_leve_opendata_error():
    r = routeur_dvf({})
    with pytest.raises(oh.OpendataError):
        dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep)
    assert len(r.appels) == 3  # 2024, 2025, 2026 : toutes tentées, aucune n'existe


def test_dvf_redirection_302_vers_un_404_est_une_annee_absente_pas_une_erreur():
    """Capture réelle : une année absente répond 302 vers un objet de stockage inexistant, qui répond 404."""
    r = routeur_dvf({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})
    r.route(url_dvf(2026), rep_redirection("https://static.test/dvf/2026.csv"))
    r.route("static.test/dvf/2026.csv", rep_statut(404))
    res = dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep)
    assert res.bloc["parametres"]["annees_absentes"] == [2026]
    assert res.bloc["compteurs"]["annees_absentes"] == 1
    assert res.erreurs == []
    assert r.attentes == []  # le 404 final n'est pas rejoué
    assert len(r.appels_vers("static.test/dvf/2026.csv")) == 1  # la redirection a bien été suivie
    assert sorted(s["millesime"] for s in res.sources) == ["2024", "2025"]


@pytest.mark.parametrize("statut, appels_attendus, attentes", [(500, 3, [1, 2]), (403, 1, [])],
                         ids=["500_persistant", "403"])
def test_dvf_erreur_persistante_sur_une_annee_leve_pas_de_couverture_partielle(statut, appels_attendus, attentes):
    r = routeur_dvf({2024: csv_dvf(mutation("2024-910001", [maison(100, 4)], date_mutation="2024-11-15")),
                     2025: statut})
    with pytest.raises(oh.OpendataError) as exc:
        dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep)
    assert not isinstance(exc.value, oh.NotFound)
    assert len(r.appels_vers(url_dvf(2025))) == appels_attendus
    assert r.attentes == attentes  # `sleep` injecté est bien transmis à get_text (jamais de time.sleep réel)


def test_dvf_csv_sans_la_colonne_id_mutation_leve_opendata_error_pas_keyerror():
    with pytest.raises(oh.OpendataError):
        collecter_dvf({2025: "a,b\n1,2\n"})


def test_dvf_sans_aujourdhui_la_fenetre_part_de_date_today(monkeypatch):
    """`aujourdhui=None` -> date.today(). Horloge figée au 03/10/2026 midi (heure locale : même jour civil
    quel que soit le fuseau) par `time.time`, que date.today() interroge."""
    midi = datetime(2026, 10, 3, 12, 0, 0).timestamp()
    monkeypatch.setattr(time, "time", lambda: midi)
    r = routeur_dvf({2024: csv_dvf(), 2025: csv_dvf(), 2026: csv_dvf()})
    res = dvf.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["parametres"]["date_debut_fenetre"] == "2024-10-03"
    assert res.bloc["parametres"]["annees"] == [2024, 2025, 2026]
    assert res.bloc["parametres"]["annees_absentes"] == []


def test_dvf_requetes_une_par_annee_de_la_fenetre_et_sources_par_annee_obtenue():
    res, r = collecter_dvf({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})
    assert Counter(a.cle for a in r.appels) == Counter({url_dvf(2024): 1, url_dvf(2025): 1, url_dvf(2026): 1})
    assert all(a.params == {} for a in r.appels)
    assert sorted(s["millesime"] for s in res.sources) == ["2024", "2025"]  # 2026 absente : pas de source
    assert sorted(s["url"] for s in res.sources) == [f"https://{url_dvf(2024)}", f"https://{url_dvf(2025)}"]
    assert all(s["bloc"] == "dvf" and s["licence"] for s in res.sources)


# ===========================================================================
# 4-8. DVF : regroupement par mutation, locaux, exclusions
# ===========================================================================

def test_mutation_a_deux_appartements_exclue_et_comptee():
    """DISCRIMINANT : si l'exclusion multi-locaux est désactivée, cette mutation (prix global 300 000
    répété sur les deux lignes) devient un comparable et ce test passe au rouge."""
    csv = csv_dvf(
        mutation("2025-910001", [appart(69, 3, lot="31"), appart(78, 4, lot="32")], valeur="300000"),
        mutation("2025-910002", [appart(60, 3, lot="5")], valeur="120000", nord_m=150),  # mono-local : reste
    )
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_multi_locaux"] == 1
    assert c["mutations"] == 2
    assert c["retenues"] == 1
    assert ids_comparables(res) == ["2025-910002"]  # la mutation à deux appartements est absente
    assert res.bloc["par_type"]["Appartement"]["n"] == 1  # absente aussi des statistiques
    assert res.bloc["comparables"][0]["prix"] == 120000.0


@pytest.mark.parametrize("surface_dependance", ["", "30"], ids=["surface_vide_reelle", "surface_renseignee"])
def test_ligne_dependance_ignoree_maison_plus_dependance_est_un_seul_local(surface_dependance):
    csv = csv_dvf(mutation("2025-910001", [maison(85, 4), dependance(surface_dependance)], valeur="194000",
                           nord_m=300, numero="15"))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_multi_locaux"] == 0 and c["exclues_sans_local_habitation"] == 0 and c["retenues"] == 1
    comparable = res.bloc["comparables"][0]
    assert comparable["type"] == "Maison"
    assert comparable["surface"] == 85.0  # surface de la maison, la dépendance n'y est pas ajoutée
    assert comparable["prix_m2"] == 2282.35


def test_maison_repetee_sur_plusieurs_lignes_par_nature_de_culture_est_un_seul_local():
    """Cas réel 2025-983317 : une ligne par nature de culture du terrain, valeur répétée."""
    csv = csv_dvf(mutation("2025-910001", [maison(120, 5, culture="sols"), maison(120, 5, culture="jardins"),
                                           maison(120, 5, culture="terrains d'agrément")], valeur="240000"))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["lignes_lues"] == 3 and c["mutations"] == 1
    assert c["exclues_multi_locaux"] == 0 and c["retenues"] == 1
    assert res.bloc["comparables"][0]["prix_m2"] == 2000.0  # 240000 / 120, pas 3 x


@pytest.mark.parametrize("locaux", [
    pytest.param([maison(100, 4), terrain()], id="maison_et_terrain_meme_parcelle"),
    pytest.param([maison(100, 4), terrain(parcelle="99001000ZZ9999")], id="maison_et_terrain_autre_parcelle"),
    pytest.param([maison(100, 4), dependance(), terrain()], id="maison_dependance_et_terrain"),
])
def test_ligne_terrain_type_local_vide_n_est_pas_un_local_bati(locaux):
    """Cas réel 2025-982553 : une maison accompagnée d'une ligne de jardins sans type_local. Compter le
    type vide comme un local enverrait la maison en exclues_multi_locaux."""
    csv = csv_dvf(mutation("2025-910001", locaux, valeur="200000"))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert (c["retenues"], c["exclues_multi_locaux"], c["exclues_sans_local_habitation"]) == (1, 0, 0)
    comparable = res.bloc["comparables"][0]
    assert comparable["type"] == "Maison"
    assert comparable["surface"] == 100.0
    assert comparable["prix_m2"] == 2000.0


@pytest.mark.parametrize("local_a, local_b, attendu_multi", [
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1"), 0, id="identique_donc_meme_local"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="2"), 1, id="lot1_seul_different"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1", parcelle="99001000ZZ9999"), 1,
                 id="parcelle_seule_differente"),
    pytest.param(appart(60, 3, lot="1"), appart(75, 3, lot="1"), 1, id="surface_seule_differente"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 4, lot="1"), 1, id="pieces_seules_differentes"),
    pytest.param(maison(110, 4), maison(60, 4), 1, id="deux_maisons_meme_parcelle_sans_lot_surfaces_differentes"),
    pytest.param(_local("Appartement", 60, 3), maison(60, 3), 1, id="type_seul_different"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1", autres_lots=("7",)), 1, id="lot2_seul_different"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1", autres_lots=("", "7")), 1, id="lot3_seul_different"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1", autres_lots=("", "", "7")), 1,
                 id="lot4_seul_different"),
    pytest.param(appart(60, 3, lot="1"), appart(60, 3, lot="1", autres_lots=("", "", "", "7")), 1,
                 id="lot5_seul_different"),
])
def test_cle_de_local_chaque_composante_seule_suffit_a_distinguer_deux_locaux(local_a, local_b, attendu_multi):
    """Clé = (parcelle, type, surface, pièces, lot1..lot5) : une seule composante qui varie fait deux locaux."""
    csv = csv_dvf(mutation("2025-910001", [local_a, local_b], valeur="150000"))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_multi_locaux"] == attendu_multi
    assert c["retenues"] == 1 - attendu_multi


def _appart_sans_lot():
    return _local("Appartement", 25, 1, culture="sols")


@pytest.mark.parametrize("locaux, attendu_multi", [
    # Cas réels de Exempleville (2025-988382, 2024-928058) : des appartements identiques, sans numéro de lot,
    # sur la même parcelle et la même culture, sont des locaux DISTINCTS, pas une répétition.
    pytest.param([_appart_sans_lot(), _appart_sans_lot()], 1, id="deux_appartements_identiques_sans_lot"),
    pytest.param([_appart_sans_lot() for _ in range(4)], 1, id="quatre_appartements_identiques_sans_lot"),
    # Deux maisons identiques, chacune répétée sur deux natures de culture : 2 locaux, 4 lignes.
    pytest.param([maison(90, 4, culture="sols"), maison(90, 4, culture="jardins"),
                  maison(90, 4, culture="sols"), maison(90, 4, culture="jardins")], 1,
                 id="deux_maisons_identiques_sur_deux_cultures"),
    # Témoins : UNE maison répétée par culture reste un seul local ; un lot renseigné identifie le local.
    pytest.param([maison(90, 4, culture="sols"), maison(90, 4, culture="jardins")], 0,
                 id="une_maison_sur_deux_cultures"),
    pytest.param([maison(90, 4, culture="sols"), maison(90, 4, culture="jardins"),
                  maison(90, 4, culture="vergers")], 0, id="une_maison_sur_trois_cultures"),
    pytest.param([appart(25, 1, lot="12"), appart(25, 1, lot="12")], 0, id="meme_lot_renseigne_meme_local"),
])
def test_locaux_identiques_sans_lot_distingues_par_la_repetition_de_leur_culture(locaux, attendu_multi):
    """Une répétition PAR NATURE DE CULTURE est un seul local ; la même ligne répétée avec la MÊME culture
    et sans lot, ce sont des locaux distincts. Les fusionner mettrait le prix de N logements sur la surface
    d'un seul (prix/m2 multiplié par N) dans les comparables et les quartiles."""
    csv = csv_dvf(mutation("2025-910001", locaux, valeur="200000"),
                  mutation("2025-910002", [maison(100, 4)], valeur="200000", nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_multi_locaux"] == attendu_multi
    assert c["retenues"] == 2 - attendu_multi
    assert sorted(ids_comparables(res)) == (["2025-910002"] if attendu_multi else ["2025-910001", "2025-910002"])


def test_meme_local_apparent_sur_deux_dispositions_est_deux_locaux():
    """Une disposition est une opération de vente distincte au sein de la mutation : deux lignes de même
    libellé (maison 85 m2, 4 pièces, même parcelle, sans lot) mais de dispositions différentes ne sont pas
    une répétition par culture. Sans `numero_disposition` dans la clé, le prix des deux biens serait rapporté
    à la surface d'un seul."""
    deux_dispositions = mutation("2025-910001", [maison(85, 4, culture="sols"), maison(85, 4, culture="jardins")],
                                 valeur="300000")
    deux_dispositions[1]["numero_disposition"] = "000002"
    une_disposition = mutation("2025-910003", [maison(85, 4, culture="sols"), maison(85, 4, culture="jardins")],
                               valeur="300000", nord_m=120)  # témoin : les deux cultures dans la MÊME disposition
    csv = csv_dvf(deux_dispositions, une_disposition, mutation("2025-910002", [maison(100, 4)], nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_multi_locaux"] == 1
    assert c["retenues"] == 2
    assert sorted(ids_comparables(res)) == ["2025-910002", "2025-910003"]


@pytest.mark.parametrize("locaux", [
    pytest.param([maison(110, 5), commercial(40)], id="maison_plus_local_commercial"),
    pytest.param([appart(60, 3, lot="1"), commercial(25)], id="appartement_plus_local_commercial"),
    pytest.param([maison(110, 5), maison(60, 3, parcelle="99001000ZZ9999")], id="deux_maisons"),
])
def test_mutation_avec_plusieurs_locaux_bati_dont_commercial_exclues_multi_locaux(locaux):
    csv = csv_dvf(mutation("2025-910001", locaux, valeur="260000"),
                  mutation("2025-910002", [maison(100, 4)], valeur="200000", nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    assert res.bloc["compteurs"]["exclues_multi_locaux"] == 1
    assert ids_comparables(res) == ["2025-910002"]


@pytest.mark.parametrize("locaux", [
    pytest.param([commercial(22)], id="local_commercial_seul"),
    pytest.param([terrain()], id="terrain_seul"),
    pytest.param([dependance()], id="dependance_seule"),
    pytest.param([terrain(), dependance()], id="terrain_et_dependance"),
])
def test_mutation_sans_local_d_habitation_exclues_sans_local_habitation(locaux):
    csv = csv_dvf(mutation("2025-910001", locaux, valeur="223000"),
                  mutation("2025-910002", [maison(100, 4)], valeur="200000", nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_sans_local_habitation"] == 1
    assert c["exclues_multi_locaux"] == 0
    assert ids_comparables(res) == ["2025-910002"]


CAS_SANS_COORDONNEES = [
    pytest.param("", None, id="longitude_vide"),
    pytest.param(None, "", id="latitude_vide"),
    pytest.param("", "", id="les_deux_vides"),
    pytest.param("abc", "def", id="non_numeriques"),
]


@pytest.mark.parametrize("longitude, latitude", CAS_SANS_COORDONNEES)
def test_ligne_sans_coordonnees_exclue_et_comptee(longitude, latitude):
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], longitude=longitude, latitude=latitude),
                  mutation("2025-910002", [maison(100, 4)], nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["exclues_sans_coordonnees"] == 1
    assert c["hors_rayon"] == 0
    assert ids_comparables(res) == ["2025-910002"]


def test_filtre_de_rayon_300m_retenu_et_2km_compte_hors_rayon():
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], nord_m=300),
                  mutation("2025-910002", [maison(100, 4)], nord_m=2000))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert c["retenues"] == 1 and c["hors_rayon"] == 1
    assert ids_comparables(res) == ["2025-910001"]
    assert res.bloc["comparables"][0]["distance_m"] == 300
    assert res.bloc["parametres"]["rayon_m"] == 500


def test_filtre_de_rayon_frontiere_499m_retenu_501m_exclu():
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], nord_m=499),
                  mutation("2025-910002", [maison(100, 4)], nord_m=501))
    res, _ = collecter_dvf({2025: csv})
    assert ids_comparables(res) == ["2025-910001"]
    assert res.bloc["compteurs"]["hors_rayon"] == 1


def test_filtre_de_rayon_decalage_est_ouest_latitude_et_longitude_dans_le_bon_ordre():
    """Tous les autres cas décalent le point vers le nord. Ici le décalage est en longitude : si
    lat et lon sont inversés au point d'appel de haversine (de façon cohérente pour les deux points),
    400 m vers l'est sont mesurés ~600 m (facteur 1 / cos 48,27 deg = 1,5) et sortent du rayon."""
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], est_m=400, nord_m=0),
                  mutation("2025-910002", [maison(100, 4)], est_m=600, nord_m=0))
    res, _ = collecter_dvf({2025: csv})
    assert ids_comparables(res) == ["2025-910001"]
    assert res.bloc["comparables"][0]["distance_m"] == 400
    assert res.bloc["compteurs"]["hors_rayon"] == 1


def test_dvf_comparables_de_meme_date_departages_par_id_mutation_quel_que_soit_l_ordre_du_csv():
    """Tri : date décroissante PUIS id_mutation. Le contrat ne fixe pas le sens du départage : le test
    exige seulement qu'il soit déterministe (même ordre quel que soit l'ordre des lignes du CSV) et
    qu'il suive l'id_mutation dans un sens ou dans l'autre."""
    premiere = mutation("2025-910001", [maison(100, 4)], date_mutation="2025-05-02", nord_m=100)
    seconde = mutation("2025-910002", [maison(100, 4)], date_mutation="2025-05-02", nord_m=150)
    ordres = [ids_comparables(collecter_dvf({2025: csv_dvf(*mutations)})[0])
              for mutations in ((premiere, seconde), (seconde, premiere))]
    assert ordres[0] == ordres[1]
    assert ordres[0] in (["2025-910001", "2025-910002"], ["2025-910002", "2025-910001"])


@pytest.mark.parametrize("rayon, retenues, hors_rayon", [(250, 0, 2), (2500, 2, 0)], ids=["250_m", "2500_m"])
def test_rayon_parametrable_et_reporte_dans_les_parametres(rayon, retenues, hors_rayon):
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], nord_m=300),
                  mutation("2025-910002", [maison(100, 4)], nord_m=2000))
    res, _ = collecter_dvf({2025: csv}, rayon_m=rayon)
    assert res.bloc["compteurs"]["retenues"] == retenues
    assert res.bloc["compteurs"]["hors_rayon"] == hors_rayon
    assert res.bloc["parametres"]["rayon_m"] == rayon


def test_filtre_de_fenetre_vente_anterieure_exclue_la_date_de_debut_est_retenue():
    """Aujourd'hui 2026-10-03, 24 mois : début 2024-10-03. La veille est exclue, le jour même retenu."""
    csv_2024 = csv_dvf(
        mutation("2024-940001", [maison(100, 4)], date_mutation="2024-10-02"),
        mutation("2024-940002", [maison(100, 4)], date_mutation="2024-10-03"),
        mutation("2024-940003", [maison(100, 4)], date_mutation="2024-06-10"),
    )
    res, _ = collecter_dvf({2024: csv_2024})
    c = res.bloc["compteurs"]
    assert c["exclues_hors_fenetre"] == 2
    assert c["retenues"] == 1
    assert ids_comparables(res) == ["2024-940002"]
    assert res.bloc["parametres"]["date_debut_fenetre"] == "2024-10-03"
    assert res.bloc["parametres"]["annees"] == [2024, 2025, 2026]
    assert res.bloc["parametres"]["annees_absentes"] == [2025, 2026]
    assert res.bloc["parametres"]["fenetre_mois"] == 24


def test_fenetre_12_mois_ne_lit_pas_2024_et_exclut_hors_fenetre():
    r = routeur_dvf({2025: fx_texte("dvf_synthetique_2025.csv")})
    res = dvf.collecter(r.client(), GEO, fenetre_mois=12, aujourdhui=AUJOURDHUI, sleep=r.sleep)
    p, c = res.bloc["parametres"], res.bloc["compteurs"]
    assert p["annees"] == [2025, 2026] and p["date_debut_fenetre"] == "2025-10-03"
    assert p["fenetre_mois"] == 12
    assert {a.cle for a in r.appels} == {url_dvf(2025), url_dvf(2026)}  # 2024 n'est pas demandée
    # Début 2025-10-03 : seules les ventes du 2025-12-31 (prix vide) sont dans la fenêtre ; les 2 natures
    # exclues (VEFA, échange) sont comptées AVANT la fenêtre.
    assert (c["exclues_nature"], c["exclues_hors_fenetre"], c["exclues_prix_ou_surface"], c["retenues"]) == (
        2, 12, 1, 0)
    assert (c["mutations"], c["lignes_lues"], c["annees_absentes"]) == (15, 21, 1)
    assert p["derniere_mutation"] == "2025-12-31"


@pytest.mark.parametrize("nature, retenue", [
    ("Vente", True),
    ("Adjudication", True),
    ("Vente en l'état futur d'achèvement", False),
    ("Echange", False),
    ("Vente terrain à bâtir", False),  # nature EXACTE : un simple préfixe « Vente » ne suffit pas
    ("Expropriation", False),
])
def test_nature_mutation_seules_vente_et_adjudication_sont_retenues(nature, retenue):
    csv = csv_dvf(mutation("2025-910001", [appart(60, 3, lot="1")], nature=nature, valeur="120000"))
    res, _ = collecter_dvf({2025: csv})
    c = res.bloc["compteurs"]
    assert (c["retenues"], c["exclues_nature"]) == ((1, 0) if retenue else (0, 1))


CAS_PRIX_SURFACE = [
    pytest.param("", "100", id="valeur_vide"),
    pytest.param("0", "100", id="valeur_zero"),
    pytest.param("abc", "100", id="valeur_non_numerique"),
    pytest.param("-5", "100", id="valeur_negative"),
    pytest.param("200000", "", id="surface_vide"),
    pytest.param("200000", "0", id="surface_zero"),
    pytest.param("200000", "n/a", id="surface_non_numerique"),
    pytest.param("200000", "-10", id="surface_negative"),
]


@pytest.mark.parametrize("valeur, surface", CAS_PRIX_SURFACE)
def test_valeur_ou_surface_nulle_vide_ou_non_numerique_exclue_prix_ou_surface(valeur, surface):
    csv = csv_dvf(mutation("2025-910001", [maison(surface, 4)], valeur=valeur),
                  mutation("2025-910002", [maison(100, 4)], valeur="200000", nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    assert res.bloc["compteurs"]["exclues_prix_ou_surface"] == 1
    assert ids_comparables(res) == ["2025-910002"]


def test_ordre_des_exclusions_chaque_mutation_tombe_dans_un_seul_compteur():
    """Ordre du contrat : nature, fenêtre, locaux (multi puis sans habitation), prix/surface, coordonnées,
    rayon. Chaque mutation ci-dessous échoue à PLUSIEURS critères et ne doit être comptée qu'une fois,
    dans le premier. Fenêtre de 12 mois : début 2025-10-03."""
    hors = "2025-03-01"   # avant le début de fenêtre
    dans = "2025-11-20"   # dans la fenêtre
    deux_apparts = [appart(69, 3, lot="31"), appart(78, 4, lot="32")]
    csv = csv_dvf(
        # nature ET fenêtre ET multi-locaux -> nature
        mutation("2025-950001", deux_apparts, nature="Echange", date_mutation=hors),
        # fenêtre ET multi-locaux -> fenêtre
        mutation("2025-950002", deux_apparts, date_mutation=hors),
        # multi-locaux ET prix vide ET sans coordonnées -> multi-locaux
        mutation("2025-950003", deux_apparts, date_mutation=dans, valeur="", longitude="", latitude=""),
        # sans local d'habitation ET prix vide -> sans local d'habitation
        mutation("2025-950004", [commercial(22)], date_mutation=dans, valeur=""),
        # surface nulle ET sans coordonnées -> prix/surface
        mutation("2025-950005", [maison(0, 4)], date_mutation=dans, longitude="", latitude=""),
        # sans coordonnées seul -> sans coordonnées
        mutation("2025-950006", [maison(100, 4)], date_mutation=dans, longitude="", latitude=""),
        # hors rayon seul -> hors rayon
        mutation("2025-950007", [maison(100, 4)], date_mutation=dans, nord_m=2000),
        # témoin retenu
        mutation("2025-950008", [maison(100, 4)], date_mutation=dans, nord_m=100),
    )
    res, _ = collecter_dvf({2025: csv}, fenetre_mois=12)
    c = res.bloc["compteurs"]
    assert c["mutations"] == 8
    assert (c["exclues_nature"], c["exclues_hors_fenetre"], c["exclues_multi_locaux"],
            c["exclues_sans_local_habitation"], c["exclues_prix_ou_surface"], c["exclues_sans_coordonnees"],
            c["hors_rayon"], c["retenues"]) == (1, 1, 1, 1, 1, 1, 1, 1)
    assert ids_comparables(res) == ["2025-950008"]


# ===========================================================================
# 11-12. DVF : statistiques, plafond, invariant de couverture
# ===========================================================================

def test_mediane_et_quartiles_sur_un_cas_calcule_a_la_main():
    """Quatre maisons à 1000, 2000, 3000 et 4000 EUR/m2 (surface 100 m2, valeur 100k..400k).

    Calcul à la main, méthode « inclusive » de statistics.quantiles (position (n - 1) x q, de 0 à n - 1) :
      médiane : position 3 x 0,5 = 1,5 -> (2000 + 3000) / 2 = 2500
      p25     : position 3 x 0,25 = 0,75 -> 1000 + 0,75 x (2000 - 1000) = 1750
      p75     : position 3 x 0,75 = 2,25 -> 3000 + 0,25 x (4000 - 3000) = 3250
    (la méthode « exclusive » donnerait 1250 et 3750 : c'est ce qu'écarte ce test)
    """
    csv = csv_dvf(*(
        mutation(f"2025-91000{k}", [maison(100, 4)], valeur=str(k * 100_000), nord_m=100,
                 date_mutation=f"2025-03-0{k}")
        for k in (1, 2, 3, 4)
    ))
    res, _ = collecter_dvf({2025: csv})
    assert res.bloc["par_type"]["Maison"] == {"n": 4, "mediane": 2500.0, "p25": 1750.0, "p75": 3250.0}


def test_quartiles_avec_deux_valeurs_methode_inclusive():
    """n = 2 (1000 et 2000) : inclusive -> p25 = 1000 + 0,25 x 1000 = 1250 et p75 = 1000 + 0,75 x 1000 = 1750,
    DANS [min, max] ; la méthode « exclusive » donnerait 750 et 2250, hors de l'intervalle observé (un p25
    sous le prix minimal est trompeur : Convention du moteur, )."""
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], valeur="100000"),
                  mutation("2025-910002", [maison(100, 4)], valeur="200000", nord_m=150))
    res, _ = collecter_dvf({2025: csv})
    assert res.bloc["par_type"]["Maison"] == {"n": 2, "mediane": 1500.0, "p25": 1250.0, "p75": 1750.0}


def test_moins_de_deux_comparables_stats_none_n_conserve_et_les_deux_types_presents():
    csv = csv_dvf(mutation("2025-910001", [maison(100, 4)], valeur="200000"))
    res, _ = collecter_dvf({2025: csv})
    par_type = res.bloc["par_type"]
    assert set(par_type) == {"Maison", "Appartement"}
    assert par_type["Maison"] == {"n": 1, "mediane": None, "p25": None, "p75": None}
    assert par_type["Appartement"] == {"n": 0, "mediane": None, "p25": None, "p75": None}


def test_csv_sans_aucune_ligne_derniere_mutation_none_et_stats_vides():
    res, _ = collecter_dvf({2025: csv_dvf()})
    assert res.bloc["comparables"] == []
    assert res.bloc["parametres"]["derniere_mutation"] is None
    assert res.bloc["compteurs"]["lignes_lues"] == 0 and res.bloc["compteurs"]["mutations"] == 0
    assert res.bloc["par_type"]["Maison"] == {"n": 0, "mediane": None, "p25": None, "p75": None}
    assert res.bloc["par_type"]["Appartement"] == {"n": 0, "mediane": None, "p25": None, "p75": None}


def test_plafond_de_15_comparables_tri_date_decroissante_stats_sur_tous_les_retenus():
    """17 maisons à 1000 x k EUR/m2 (k = 1..17), vendues le k-ième jour de février 2025.

    Les 15 plus récentes sont k = 17 .. 3. Les statistiques portent sur les 17 retenues (n = 17) :
      médiane = 9e valeur = 9000 (sur les 15 seules ce serait 10000)
      p25 : méthode inclusive, position (n - 1) x 0,25 = 4 -> 5e valeur = 5000
      p75 : position (n - 1) x 0,75 = 12 -> 13e valeur = 13000
    """
    csv = csv_dvf(*(
        mutation(f"2025-9{k:05d}", [maison(100, 4)], valeur=str(k * 100_000), nord_m=100,
                 date_mutation=f"2025-02-{k:02d}")
        for k in range(1, 18)
    ))
    res, _ = collecter_dvf({2025: csv})
    comparables = res.bloc["comparables"]
    assert len(comparables) == 15
    assert [c["id_mutation"] for c in comparables] == [f"2025-9{k:05d}" for k in range(17, 2, -1)]
    dates = [c["date"] for c in comparables]
    assert dates == sorted(dates, reverse=True)
    assert res.bloc["compteurs"]["retenues"] == 17
    assert res.bloc["par_type"]["Maison"] == {"n": 17, "mediane": 9000.0, "p25": 5000.0, "p75": 13000.0}


def test_comparable_forme_complete_adresse_composee_pieces_none_et_prix_decimal():
    csv = csv_dvf(
        mutation("2025-910001", [maison(50, "")], valeur="150000.5", numero="9003", suffixe="A",
                 voie="RUE DE TEST", date_mutation="2025-05-02", nord_m=250),
        mutation("2025-910002", [maison(100, 4)], valeur="200000", numero="", voie="AV DE TEST",
                 date_mutation="2025-05-01", nord_m=120),
    )
    res, _ = collecter_dvf({2025: csv})
    premier, second = res.bloc["comparables"]
    assert premier == {"date": "2025-05-02", "type": "Maison", "surface": 50.0, "pieces": None,
                       "prix": 150000.5, "prix_m2": 3000.01, "distance_m": 250,
                       "adresse": "9003 A RUE DE TEST", "id_mutation": "2025-910001",
                       "atypique": None, "motif_atypie": None}  # 2 maisons seulement : moins de 5, pas de drapeau
    assert set(second) == set(premier)
    assert second["adresse"] == "AV DE TEST"  # numéro et suffixe vides : pas d'espace parasite
    assert second["pieces"] == 4 and isinstance(second["pieces"], int)
    assert isinstance(second["distance_m"], int)


def test_stats_calculees_sur_valeurs_non_arrondies_puis_arrondies_a_2_decimales():
    """Quatre maisons de 7 m2 vendues 100000, 100001, 100002 et 100003 EUR : prix_m2 = 14285,7142...,
    14285,8571..., 14286,0 et 14286,1428... (inclusive).
      médiane = (14285,8571 + 14286,0) / 2 = 14285,9285... -> 14285,93
      p25 = 14285,7142 + 0,75 x (14285,8571 - 14285,7142) = 14285,8214... -> 14285,82
      p75 = 14286,0 + 0,25 x (14286,1428 - 14286,0) = 14286,0357... -> 14286,04
    Calculé sur les prix_m2 DÉJÀ arrondis (14285,71 / 14285,86 / 14286,0 / 14286,14), p75 vaudrait
    14286,035 -> 14286,03 : c'est ce que ce test écarte."""
    csv = csv_dvf(*(
        mutation(f"2025-91000{k}", [maison(7, 2)], valeur=str(100_000 + k), nord_m=100,
                 date_mutation=f"2025-03-0{k + 1}")
        for k in (0, 1, 2, 3)
    ))
    res, _ = collecter_dvf({2025: csv})
    assert sorted(c["prix_m2"] for c in res.bloc["comparables"]) == [14285.71, 14285.86, 14286.0, 14286.14]
    assert res.bloc["par_type"]["Maison"] == {"n": 4, "mediane": 14285.93, "p25": 14285.82, "p75": 14286.04}


# --- Comparables atypiques : barrières de Tukey par type ----------

PARAMETRES_ATYPIE = {"regle": "Tukey, 1,5 × EIQ, par type", "coefficient": 1.5, "n_min": 5,
                     "methode_quartiles": "inclusive"}


def csv_prix_m2(*, maisons=(), apparts=()) -> str:
    """Une vente par prix_m2 donné : maisons de 100 m2 et appartements de 50 m2 (valeur = prix_m2 x surface), à
    100 m du point. La date de vente croît avec le rang dans l'ordre donné (maisons d'abord) : le dernier prix
    est le plus récent."""
    ventes = [(maison(100, 4), 100, p) for p in maisons] + [(appart(50, 2), 50, p) for p in apparts]
    return csv_dvf(*(
        mutation(f"2025-92{k:04d}", [local], valeur=str(round(p * surface)), nord_m=100,
                 date_mutation=f"2025-03-{k % 28 + 1:02d}")
        for k, (local, surface, p) in enumerate(ventes)
    ))


def par_prix(res, prix_m2: float) -> dict:
    (trouve,) = [c for c in res.bloc["comparables"] if c["prix_m2"] == prix_m2]
    return trouve


def test_comparable_sous_la_barriere_basse_de_tukey_est_signale_atypique_avec_son_motif():
    """8 maisons : 500, 1800, 1900, 2000, 2000, 2100, 2200, 2300. Quartiles inclusive : p25 = 1875 et
    p75 = 2125, EIQ = 250, barrières [1875 - 375 ; 2125 + 375] = [1500 ; 2500]. 500 < 1500."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[500, 1800, 1900, 2000, 2000, 2100, 2200, 2300])})
    assert res.bloc["par_type"]["Maison"]["p25"] == 1875.0 and res.bloc["par_type"]["Maison"]["p75"] == 2125.0
    bas = par_prix(res, 500.0)
    assert bas["atypique"] is True
    assert bas["motif_atypie"] == "prix_m2 < p25 − 1,5 × EIQ (Maison, n = 8)"


def test_comparable_au_dessus_de_la_barriere_haute_de_tukey_est_signale_atypique_avec_son_motif():
    """8 maisons : 1800 .. 2300 et 4000. p25 = 1975, p75 = 2225, EIQ = 250, barrières [1600 ; 2600]. 4000 > 2600."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[1800, 1900, 2000, 2000, 2100, 2200, 2300, 4000])})
    haut = par_prix(res, 4000.0)
    assert haut["atypique"] is True
    assert haut["motif_atypie"] == "prix_m2 > p75 + 1,5 × EIQ (Maison, n = 8)"


def test_comparables_dans_les_barrieres_de_tukey_ne_sont_pas_atypiques():
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[500, 1800, 1900, 2000, 2000, 2100, 2200, 2300])})
    dedans = [c for c in res.bloc["comparables"] if c["prix_m2"] != 500.0]
    assert len(dedans) == 7
    assert all(c["atypique"] is False and c["motif_atypie"] is None for c in dedans)


def test_type_a_moins_de_5_retenus_atypique_et_motif_none_meme_avec_une_valeur_extreme():
    """4 maisons dont une à 9000 : sans le seuil de 5, la barrière haute (6637,5) la signalerait."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[2000, 2100, 2200, 9000])})
    assert res.bloc["par_type"]["Maison"]["n"] == 4
    assert len(res.bloc["comparables"]) == 4
    assert all(c["atypique"] is None and c["motif_atypie"] is None for c in res.bloc["comparables"])


def test_a_exactement_5_retenus_le_drapeau_est_pose():
    """5 maisons : 2000, 2100, 2200, 2300, 9000. p25 = 2100, p75 = 2300, barrière haute 2600 : le seuil est « au
    moins 5 », pas « plus de 5 »."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[2000, 2100, 2200, 2300, 9000])})
    assert par_prix(res, 9000.0)["atypique"] is True
    assert par_prix(res, 2000.0)["atypique"] is False


def test_barrieres_de_tukey_propres_a_chaque_type_pas_de_melange_maisons_appartements():
    """6 maisons (2000 .. 2200 et 2900 : barrière haute 2375) et 5 appartements à 4000. 2900 est atypique parmi les
    maisons ; mélangées aux appartements (barrière haute 6812,5), elle ne le serait pas. Les appartements, tous à
    4000 (EIQ = 0), restent dans leurs barrières."""
    csv = csv_prix_m2(maisons=[2000, 2050, 2100, 2150, 2200, 2900], apparts=[4000] * 5)
    res, _ = collecter_dvf({2025: csv})
    assert par_prix(res, 2900.0)["atypique"] is True
    assert par_prix(res, 2900.0)["motif_atypie"] == "prix_m2 > p75 + 1,5 × EIQ (Maison, n = 6)"
    apparts = [c for c in res.bloc["comparables"] if c["type"] == "Appartement"]
    assert len(apparts) == 5 and all(c["atypique"] is False for c in apparts)


def test_un_atypique_est_signale_pas_retire_il_reste_dans_la_liste_et_dans_par_type():
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[500, 1800, 1900, 2000, 2000, 2100, 2200, 2300])})
    assert res.bloc["compteurs"]["retenues"] == 8
    assert len(res.bloc["comparables"]) == 8
    assert par_prix(res, 500.0)["atypique"] is True
    # les statistiques portent sur les 8 retenues, l'atypique compris (sans lui : n = 7, p25 = 1900)
    assert res.bloc["par_type"]["Maison"] == {"n": 8, "mediane": 2000.0, "p25": 1875.0, "p75": 2125.0}


def test_barrieres_de_tukey_sur_tous_les_retenus_du_type_pas_sur_les_15_affiches():
    """17 maisons (16 entre 2010 et 2160, plus une à 500, la plus récente) : 15 affichées, mais le motif cite
    la population des 17, la même que `par_type`."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[2000 + 10 * k for k in range(1, 17)] + [500])})
    assert len(res.bloc["comparables"]) == 15 and res.bloc["par_type"]["Maison"]["n"] == 17
    assert par_prix(res, 500.0)["motif_atypie"] == "prix_m2 < p25 − 1,5 × EIQ (Maison, n = 17)"


# --- `atypiques` : le compte par type, sur tous les retenus ---------

def test_atypique_hors_des_15_affiches_est_compte_dans_atypiques_sans_figurer_dans_comparables():
    """17 maisons, la plus ancienne à 500 : les 15 plus récentes sont affichées, 500 n'en fait pas partie. Elle reste
    dans la population de `par_type` (n = 17) et y est atypique (p25 = 2040, p75 = 2120, EIQ = 80, barrière basse
    1920) : `atypiques` la compte, `comparables` ne la montre pas. Aucun appartement retenu : `null`."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[500] + [2000 + 10 * k for k in range(1, 17)])})
    assert res.bloc["par_type"]["Maison"]["n"] == 17
    assert len(res.bloc["comparables"]) == 15
    assert 500.0 not in [c["prix_m2"] for c in res.bloc["comparables"]]
    assert res.bloc["atypiques"] == {"Maison": 1, "Appartement": None}


def test_type_a_moins_de_5_retenus_a_atypiques_none_pas_0():
    """4 maisons dont une à 9000 : sans barrières, `atypiques` vaut `null`. « Aucun atypique » (0) et « pas de base
    pour en juger » (`null`) ne se disent pas pareil : 5 appartements au même prix ont des barrières, 0 atypique."""
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=[2000, 2100, 2200, 9000], apparts=[4000] * 5)})
    assert res.bloc["par_type"]["Maison"]["n"] == 4 and res.bloc["par_type"]["Appartement"]["n"] == 5
    assert res.bloc["atypiques"] == {"Maison": None, "Appartement": 0}


# 17 maisons, de la plus ancienne à la plus récente : 1000 et 4000 (les deux plus anciennes) sortent de l'affichage,
# 2400 (la plus récente) y reste.
MAISONS_POPULATION = [1000, 4000, 1970, 1980, 2000, 2010, 2070, 2100, 2110, 2120, 2130, 2150, 2160, 2180, 2230,
                      2250, 2400]


def test_le_drapeau_d_un_affiche_suit_la_population_des_17_retenus_pas_les_15_affiches():
    """Les deux jeux de barrières, sur les mêmes 17 ventes (épinglés par les deux premiers `assert`) :
      17 retenus   : p25 = 2010, p75 = 2180, EIQ = 170, barrières [1755 ; 2435]
      15 affichés  : p25 = 2040, p75 = 2170, EIQ = 130, barrières [1845 ; 2365]
    2400, affiché, est dedans sur les 17 et dehors sur les 15 : le code doit suivre les 17 (la population de
    `par_type`, celle que le motif cite), donc 2400 n'est PAS atypique. 1000 et 4000, hors affichage, le sont ;
    sur les 15 affichés, `atypiques` en compterait 3 au lieu de 2."""
    tous, affiches = MAISONS_POPULATION, MAISONS_POPULATION[2:]
    assert dvf._barrieres_tukey(tous) == (1755.0, 2435.0)
    assert dvf._barrieres_tukey(affiches) == (1845.0, 2365.0)
    res, _ = collecter_dvf({2025: csv_prix_m2(maisons=MAISONS_POPULATION)})
    assert res.bloc["par_type"]["Maison"]["n"] == 17 and len(res.bloc["comparables"]) == 15
    assert sorted(c["prix_m2"] for c in res.bloc["comparables"]) == sorted(float(p) for p in affiches)
    recente = par_prix(res, 2400.0)
    assert recente["atypique"] is False and recente["motif_atypie"] is None
    assert [c["prix_m2"] for c in res.bloc["comparables"] if c["atypique"]] == []
    assert res.bloc["atypiques"] == {"Maison": 2, "Appartement": None}


COMPTEURS_ATTENDUS = {
    "lignes_lues", "mutations", "exclues_nature", "exclues_hors_fenetre", "exclues_multi_locaux",
    "exclues_sans_local_habitation", "exclues_prix_ou_surface", "exclues_sans_coordonnees", "hors_rayon",
    "retenues", "annees_absentes",
}
EXCLUSIONS_ET_RETENUES = COMPTEURS_ATTENDUS - {"lignes_lues", "mutations", "annees_absentes"}


def test_invariant_de_couverture_sur_un_csv_qui_exerce_tous_les_cas():
    """Fixtures dvf_synthetique_2024/2025 (aujourd'hui 2026-10-03, 24 mois, début 2024-10-03).

    2025 : retenues 900001 (maison + dépendance), 900002 (maison sur 3 lignes), 900003 (appartement),
           900011 (adjudication) ; multi-locaux 900004 (2 appartements), 900005 (maison + commerce) ;
           sans habitation 900006 (commerce), 900007 (terrain), 900008 (dépendance) ;
           nature 900009 (VEFA), 900010 (échange) ; prix/surface 900012 (valeur vide), 900013 (surface 0) ;
           sans coordonnées 900014 ; hors rayon 900015 (2 km).
    2024 : hors fenêtre 900001 (2024-06-10) et 900004 (2024-10-02) ; retenues 900002 et 900003 (2024-10-03).
    """
    texte_2024, texte_2025 = fx_texte("dvf_synthetique_2024.csv"), fx_texte("dvf_synthetique_2025.csv")
    res, _ = collecter_dvf({2024: texte_2024, 2025: texte_2025})
    c = res.bloc["compteurs"]
    assert set(c) == COMPTEURS_ATTENDUS
    assert all(type(v) is int for v in c.values())
    lignes_attendues = sum(len(list(csv.DictReader(io.StringIO(t)))) for t in (texte_2024, texte_2025))
    assert c == {
        "lignes_lues": lignes_attendues, "mutations": 19, "exclues_nature": 2, "exclues_hors_fenetre": 2,
        "exclues_multi_locaux": 2, "exclues_sans_local_habitation": 3, "exclues_prix_ou_surface": 2,
        "exclues_sans_coordonnees": 1, "hors_rayon": 1, "retenues": 6, "annees_absentes": 1,
    }
    assert lignes_attendues == 25
    assert c["mutations"] == sum(c[k] for k in EXCLUSIONS_ET_RETENUES)  # chaque mutation dans UN compteur


def test_dvf_bloc_complet_sur_les_fixtures_forme_parametres_stats_et_comparables():
    res, _ = collecter_dvf({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})
    assert res.erreurs == []
    assert set(res.bloc) == {"parametres", "par_type", "atypiques", "comparables", "compteurs"}
    assert res.bloc["parametres"] == {
        "rayon_m": 500, "fenetre_mois": 24, "date_debut_fenetre": "2024-10-03", "annees": [2024, 2025, 2026],
        "annees_absentes": [2026], "derniere_mutation": "2025-12-31",  # lue même si la mutation est exclue
        "atypie": PARAMETRES_ATYPIE,
    }
    # Maisons (prix_m2 non arrondis) : 1500, 2000, 2100, 194000/85 = 2282,3529 -> médiane (2000 + 2100)/2,
    # inclusive : p25 = 1500 + 0,75 x 500 = 1875, p75 = 2100 + 0,25 x 182,3529 = 2145,59.
    # Appartements : 2000 et 165000/82 = 2012,1951 (n = 2 : p25 et p75 restent dans [min, max]).
    assert res.bloc["par_type"] == {
        "Maison": {"n": 4, "mediane": 2050.0, "p25": 1875.0, "p75": 2145.59},
        "Appartement": {"n": 2, "mediane": 2006.1, "p25": 2003.05, "p75": 2009.15},
    }
    # 4 maisons et 2 appartements : moins de 5 retenus par type, donc ni drapeau ni motif (null).
    assert res.bloc["comparables"] == [
        {"date": "2025-06-20", "type": "Maison", "surface": 90.0, "pieces": 3, "prix": 135000.0,
         "prix_m2": 1500.0, "distance_m": 400, "adresse": "7 RUE DU TEST", "id_mutation": "2025-900011",
         "atypique": None, "motif_atypie": None},
        {"date": "2025-04-12", "type": "Maison", "surface": 120.0, "pieces": 5, "prix": 240000.0,
         "prix_m2": 2000.0, "distance_m": 200, "adresse": "9003 A RUE DE TEST", "id_mutation": "2025-900002",
         "atypique": None, "motif_atypie": None},
        {"date": "2025-02-20", "type": "Maison", "surface": 85.0, "pieces": 4, "prix": 194000.0,
         "prix_m2": 2282.35, "distance_m": 300, "adresse": "15 RUE DE TEST", "id_mutation": "2025-900001",
         "atypique": None, "motif_atypie": None},
        {"date": "2025-01-15", "type": "Appartement", "surface": 82.0, "pieces": 4, "prix": 165000.0,
         "prix_m2": 2012.2, "distance_m": 450, "adresse": "33 AV DE TEST", "id_mutation": "2025-900003",
         "atypique": None, "motif_atypie": None},
        {"date": "2024-11-15", "type": "Appartement", "surface": 60.0, "pieces": 3, "prix": 120000.0,
         "prix_m2": 2000.0, "distance_m": 100, "adresse": "5 RUE DE TEST", "id_mutation": "2024-900002",
         "atypique": None, "motif_atypie": None},
        {"date": "2024-10-03", "type": "Maison", "surface": 100.0, "pieces": 4, "prix": 210000.0,
         "prix_m2": 2100.0, "distance_m": 350, "adresse": "2 RUE DE TEST", "id_mutation": "2024-900003",
         "atypique": None, "motif_atypie": None},
    ]


# ===========================================================================
# 17-18. DPE
# ===========================================================================

def test_dpe_constantes_du_contrat():
    assert dpe.URL == "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
    assert tuple(dpe.CHAMPS) == CHAMPS_DPE_ATTENDUS
    assert dpe.DATE_REFORME == date(2026, 1, 1)
    assert dpe.DPE_MAX_LIGNES == 200  # ancien attendu : TAILLE_ADRESSE == 20 (constante supprimée, )
    assert not hasattr(dpe, "TAILLE_ADRESSE")


@pytest.mark.parametrize("date_dpe, chauffage, attendu", [
    ("2025-12-31", "Électricité", True),            # veille de la réforme, chauffage électrique
    ("2026-01-01", "Électricité", False),           # frontière : le 01/01/2026 n'est plus « avant »
    ("2025-06-01", "Gaz naturel", False),           # avant la réforme mais pas électrique
    ("2025-12-31", "electricite", True),            # variantes d'écriture
    ("2025-12-31", "ÉLECTRICITÉ", True),
    ("2025-12-31", unicodedata.normalize("NFD", "Électricité"), True),
    ("2020-01-01", "Électricité", True),
    ("2026-06-15", "Gaz naturel", False),
    ("2025-12-31", "Réseau de Chauffage urbain", False),
    ("2025-12-31", "Bois – Bûches", False),
    (None, "Électricité", None),                    # absence rendue comme absence
    ("2025-12-31", None, None),
    (None, None, None),
    ("", "Électricité", None),
    ("pas une date", "Électricité", None),
    ("31/12/2025", "Électricité", None),            # seul le format ISO est lu
])
def test_drapeau_avant_reforme_coef_elec_dans_les_deux_sens(date_dpe, chauffage, attendu):
    assert dpe.avant_reforme_coef_elec(date_dpe, chauffage) is attendu


def test_dpe_commune_total_requete_qs_avec_guillemets_et_size_0():
    r = routeur_nominal()
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune_total"] == 4614
    appels_commune = [a for a in r.appels if a.params.get("qs", "").startswith("code_insee_ban:")]
    assert len(appels_commune) == 1
    assert appels_commune[0].url == f"https://{MOTIF_DPE}"
    assert appels_commune[0].params == {"qs": f'code_insee_ban:"{INSEE}"', "size": "0"}


def test_dpe_a_l_adresse_qs_avec_guillemets_size_et_select_dans_la_requete_emise():
    """Sans guillemets, l'API renvoie silencieusement les 9,5 M de lignes du jeu."""
    r = routeur_nominal()
    dpe.collecter(r.client(), GEO, sleep=r.sleep)
    appels_adresse = [a for a in r.appels if a.params.get("qs", "").startswith("adresse_ban:")]
    assert len(appels_adresse) == 1
    assert appels_adresse[0].params == {
        "qs": f'adresse_ban:"{LABEL}"', "size": "200", "select": ",".join(CHAMPS_DPE_ATTENDUS)}  # ancien : "20"


def test_dpe_a_l_adresse_bloc_complet_et_drapeau_sur_chaque_dpe():
    r = routeur_nominal()
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.erreurs == []
    adresse = res.bloc["a_l_adresse"]
    assert set(adresse) == {"adresse_ban", "total", "dpe", "note"}
    assert adresse["adresse_ban"] == LABEL and adresse["total"] == 4
    assert [d["avant_reforme_coef_elec"] for d in adresse["dpe"]] == [True, False, False, None]
    premier = adresse["dpe"][0]
    assert premier["etiquette_dpe"] == "D" and premier["etiquette_ges"] == "B"
    assert premier["conso_5_usages_par_m2_ep"] == 273 and premier["surface_habitable_logement"] == 90
    assert premier["date_etablissement_dpe"] == "2025-12-31"
    assert premier["type_energie_principale_chauffage"] == "Électricité"
    assert premier["periode_construction"] == "avant 1948" and premier["type_batiment"] == "maison"
    assert all(d["adresse_ban"] == LABEL and d["code_insee_ban"] == INSEE for d in adresse["dpe"])
    # Exactement CHAMPS + le drapeau : ni `_score` (champ technique de l'API), ni clé manquante.
    assert all(set(d) == set(CHAMPS_DPE_ATTENDUS) | {"avant_reforme_coef_elec"} for d in adresse["dpe"])
    assert adresse["dpe"][3]["type_energie_principale_chauffage"] is None  # absent de la ligne source : None
    assert isinstance(adresse["note"], str) and "2026" in adresse["note"]  # fait daté, pas une interprétation


@pytest.mark.parametrize("label", ['Rue "Test" 99100 Exempleville', "Rue A\\B 99100 Exempleville"],
                         ids=["guillemet", "antislash"])
def test_dpe_label_avec_guillemet_ou_antislash_est_echappe_dans_le_qs(label):
    geo = {**GEO, "label": label}
    attendu = label.replace("\\", "\\\\").replace('"', '\\"')
    reponse = {"total": 1, "results": [{**fx("dpe_adresse.json")["results"][0], "adresse_ban": label}]}
    r = Routeur().route(MOTIF_DPE, rep_json(reponse))
    res = dpe.collecter(r.client(), geo, sleep=r.sleep)
    qs_adresse = [a.params["qs"] for a in r.appels if a.params["qs"].startswith("adresse_ban:")]
    assert qs_adresse == [f'adresse_ban:"{attendu}"']
    assert res.bloc["a_l_adresse"]["total"] == 1


def test_dpe_garde_adresse_ban_differente_du_label_filtre_ignore_pas_de_donnees_etrangeres():
    """Filtre ignoré (lignes d'autres adresses) : le sous-bloc est None + erreur, jamais livré.
    La recherche commune reste valide."""
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json(fx("dpe_adresse_ignoree.json")),
            si=lambda q: q.url.params.get("qs", "").startswith("adresse_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None
    assert res.bloc["commune_total"] == 4614
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]
    assert "ignor" in res.erreurs[0]["message"]
    assert "dpe.a_l_adresse" not in {s["bloc"] for s in res.sources}


def _est_recherche_a_l_adresse(requete: httpx.Request) -> bool:
    return requete.url.params.get("qs", "").startswith("adresse_ban:")


@pytest.mark.parametrize("ordre", ["etrangere_en_derniere", "etrangere_en_premiere"])
def test_dpe_garde_une_seule_ligne_etrangere_suffit_a_lever_le_filtre_ignore(ordre):
    """La garde contrôle TOUTES les lignes : ni seulement la première, ni un filtrage silencieux des
    lignes étrangères (le filtre ignoré ne serait alors jamais signalé et le total serait faux)."""
    propre = fx("dpe_adresse.json")["results"][0]
    etrangere = fx("dpe_adresse_ignoree.json")["results"][0]
    lignes = [propre, etrangere] if ordre == "etrangere_en_derniere" else [etrangere, propre]
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json({"total": 2, "results": lignes}), si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None
    assert res.bloc["commune_total"] == 4614
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]
    assert "ignor" in res.erreurs[0]["message"]


@pytest.mark.parametrize("payload", [{"total": 1, "results": "x"}, {"total": 1}],
                         ids=["results_non_liste", "sans_results"])
def test_dpe_forme_inattendue_a_l_adresse_none_et_erreur_pas_keyerror(payload):
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json(payload), si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None
    assert res.bloc["commune_total"] == 4614
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]


def test_dpe_total_zero_est_un_resultat_valide_pas_une_erreur():
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json(fx("dpe_adresse_vide.json")),
            si=lambda q: q.url.params.get("qs", "").startswith("adresse_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.erreurs == []
    assert res.bloc["a_l_adresse"]["total"] == 0
    assert res.bloc["a_l_adresse"]["dpe"] == []
    assert res.bloc["a_l_adresse"]["adresse_ban"] == LABEL


def test_dpe_total_superieur_a_20_garde_les_20_premiers_et_le_vrai_total():
    lignes = [dict(fx("dpe_adresse.json")["results"][2]) for _ in range(20)]
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json({"total": 35, "results": lignes}),
            si=lambda q: q.url.params.get("qs", "").startswith("adresse_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"]["total"] == 35  # le total dit la vérité
    assert len(res.bloc["a_l_adresse"]["dpe"]) == 20


@pytest.mark.parametrize("type_geo", ["municipality", "street"])
def test_dpe_geocodage_sans_numero_de_rue_a_l_adresse_none_commune_total_rempli(type_geo):
    geo = {**GEO_COMMUNE, "type": type_geo}
    r = routeur_nominal()
    res = dpe.collecter(r.client(), geo, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None
    assert res.bloc["commune_total"] == 4614
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]
    assert type_geo in res.erreurs[0]["message"]
    assert len(r.appels) == 1  # aucune recherche à l'adresse n'est émise


def test_dpe_erreur_http_sur_une_recherche_n_arrete_pas_l_autre():
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_statut(500), si=lambda q: q.url.params.get("qs", "").startswith("code_insee_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune_total"] is None
    assert res.bloc["a_l_adresse"]["total"] == 4
    assert [e["bloc"] for e in res.erreurs] == ["dpe.commune_total"]
    assert r.attentes == [1, 2]

    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_statut(500), si=lambda q: q.url.params.get("qs", "").startswith("adresse_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None
    assert res.bloc["commune_total"] == 4614
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]


@pytest.mark.parametrize("payload", [{"results": []}, {"total": "abc", "results": []}, {"total": None}],
                         ids=["sans_total", "total_non_entier", "total_null"])
def test_dpe_total_commune_absent_ou_non_entier_donne_none_et_erreur(payload):
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json(payload), si=lambda q: q.url.params.get("qs", "").startswith("code_insee_ban:"))
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune_total"] is None
    assert [e["bloc"] for e in res.erreurs] == ["dpe.commune_total"]


def test_dpe_sources_une_par_sous_bloc_obtenu():
    res = dpe.collecter(routeur_nominal().client(), GEO)
    assert sorted(s["bloc"] for s in res.sources) == ["dpe.a_l_adresse", "dpe.commune_total"]
    assert all(s["url"] == dpe.URL and s["millesime"] is None and s["licence"] for s in res.sources)


# ===========================================================================
# 15 + 14. Géorisques : commune, adresse (retry), PPRN
# ===========================================================================

ATTENDU_RISQUES_COMMUNE = {
    "code_insee": INSEE, "libelle_commune": "EXEMPLEVILLE",
    "risques": [
        {"num_risque": "11", "libelle": "Inondation"},
        {"num_risque": "112", "libelle": "Par ruissellement et coulée de boue"},
        {"num_risque": "24", "libelle": "Transport de marchandises dangereuses"},
    ],
}
ATTENDU_PPRN = [{
    "id_gaspar": "99DDT20000001", "libelle": "PPRI de la vallée de l'Exemple", "modele_procedure": "PPRN-I",
    "bassin_risques": "Rivière-Exemple", "etat_revision": False, "date_modification": "20/02/2025",
    "aleas": [{"libelle": "Inondation", "date_prescription": "15/05/2003",
               "date_approbation": "22/11/2009", "date_abrogation": None}],
}]


def _risque(libelle, present, commune=None, adresse=None):
    return {"present": present, "libelle": libelle, "statut_commune": commune, "statut_adresse": adresse}


ATTENDU_RAPPORT_NATURELS = {
    "inondation": _risque("Inondation", True, "Risque Existant", "Risque Existant"),
    "remonteeNappe": _risque("Remontée de nappe", True, "Risque Existant", "Risque Existant"),
    "risqueCotier": _risque("Risques côtiers (submersion marine, tsunami)", False),
    "seisme": _risque("Séisme", True, "Risque Existant - faible", "Risque Existant - faible"),
    "mouvementTerrain": _risque("Mouvements de terrain", True, "Risque Existant", "Risque Inconnu"),
}
ATTENDU_RAPPORT_TECHNOLOGIQUES = {
    "icpe": _risque("Installations industrielles classées (ICPE)", False),
    "canalisationsMatieresDangereuses": _risque(
        "Canalisations de transport de matières dangereuses", True, "Risque Concerne", "Risque Concerne"),
    "pollutionSols": _risque("Pollution des sols", True, "Risque Concerne", "Risque Concerne"),
}


def test_georisques_constantes_du_contrat():
    assert georisques.BASE == "https://georisques.gouv.fr/api/v1"
    assert georisques.PPRN_MAX == 50


def test_georisques_commune_forme_et_parametre_code_insee_snake_case():
    r = routeur_nominal()
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune"] == ATTENDU_RISQUES_COMMUNE
    appel = r.appels_vers(MOTIF_RISQUES)[0]
    assert appel.params == {"code_insee": INSEE}
    assert "codeInsee" not in appel.params  # camelCase : erreur 500 sur cet endpoint


def test_georisques_adresse_latlon_longitude_d_abord_et_toutes_les_entrees_gardees():
    r = routeur_nominal()
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    appel = r.appels_vers(MOTIF_RAPPORT)[0]
    assert appel.params == {"latlon": "1.5021,47.5013"}  # "<lon>,<lat>", lat,lon donnerait un 404
    adresse = res.bloc["adresse"]
    assert adresse == {
        "adresse": "1 Rue de Test, 99100 Exempleville", "commune": "Exempleville",
        "url_rapport": fx("georisques_rapport_risque.json")["url"],
        "risques_naturels": ATTENDU_RAPPORT_NATURELS,
        "risques_technologiques": ATTENDU_RAPPORT_TECHNOLOGIQUES,
    }
    # « non présent » est une information : les entrées absentes sont conservées.
    assert adresse["risques_naturels"]["risqueCotier"]["present"] is False
    assert adresse["risques_technologiques"]["icpe"]["present"] is False


def test_georisques_adresse_deux_echecs_puis_succes_bloc_rempli_aucune_erreur():
    r = routeur_nominal()
    r.route(MOTIF_RAPPORT, [
        httpx.ConnectError("connexion réinitialisée 1"), httpx.ReadError("connexion réinitialisée 2"),
        rep_json(fx("georisques_rapport_risque.json")),
    ])
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["adresse"] is not None
    assert res.bloc["adresse"]["risques_naturels"] == ATTENDU_RAPPORT_NATURELS
    assert res.erreurs == []
    assert len(r.appels_vers(MOTIF_RAPPORT)) == 3
    assert r.attentes == [1, 2]
    assert "risques.adresse" in {s["bloc"] for s in res.sources}


def test_georisques_adresse_trois_echecs_none_et_exactement_une_erreur_les_autres_sous_blocs_restent():
    r = routeur_nominal()
    r.route(MOTIF_RAPPORT, httpx.ConnectError)
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["adresse"] is None
    assert [e["bloc"] for e in res.erreurs].count("risques.adresse") == 1
    assert len(res.erreurs) == 1
    assert res.bloc["commune"] == ATTENDU_RISQUES_COMMUNE
    assert res.bloc["pprn"] == ATTENDU_PPRN
    assert len(r.appels_vers(MOTIF_RAPPORT)) == 3
    assert r.attentes == [1, 2]
    assert {s["bloc"] for s in res.sources} == {"risques.commune", "risques.pprn"}


@pytest.mark.parametrize("type_geo", ["municipality", "street"])
def test_georisques_geocodage_sans_numero_adresse_none_erreur_et_aucun_appel_adresse(type_geo):
    r = routeur_nominal()
    res = georisques.collecter(r.client(), {**GEO_COMMUNE, "type": type_geo}, sleep=r.sleep)
    assert res.bloc["adresse"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.adresse"]
    assert res.erreurs[0]["message"]
    assert r.appels_vers(MOTIF_RAPPORT) == []
    assert res.bloc["commune"] is not None and res.bloc["pprn"] is not None


def test_georisques_commune_sans_donnees_none_et_erreur():
    r = routeur_nominal()
    r.route(MOTIF_RISQUES, rep_json(fx("georisques_commune_vide.json")))
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.commune"]
    assert res.bloc["adresse"] is not None and res.bloc["pprn"] == ATTENDU_PPRN


def test_georisques_commune_forme_inattendue_none_et_erreur_pas_keyerror():
    r = routeur_nominal()
    r.route(MOTIF_RISQUES, rep_json({"results": 1, "page": 1}))  # pas de clé « data »
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["commune"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.commune"]


def test_pprn_parametre_codeInsee_camelcase_envoye_et_pas_code_insee():
    r = routeur_nominal()
    georisques.collecter(r.client(), GEO, sleep=r.sleep)
    appel = r.appels_vers(MOTIF_PPRN)[0]
    assert appel.params == {"codeInsee": INSEE, "page_size": "100"}
    assert "code_insee" not in appel.params  # ignoré silencieusement : renvoie les 6 582 PPRN de France


def test_pprn_forme_detail_verifie_et_aleas_au_niveau_racine_seulement():
    r = routeur_nominal()
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["pprn"] == ATTENDU_PPRN  # le sous-aléa « Par une crue... » n'est pas remonté
    detail = r.appels_vers(MOTIF_PPRN_DETAIL + "*")
    assert [a.cle for a in detail] == [MOTIF_PPRN_DETAIL + "99DDT20000001"]
    assert "risques.pprn" in {s["bloc"] for s in res.sources}


def test_pprn_garde_total_elements_superieur_a_50_sous_bloc_none_filtre_ignore():
    r = routeur_nominal()
    r.route(MOTIF_PPRN, rep_json(fx("georisques_pprn_hors_filtre.json")))  # totalElements = 6582
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["pprn"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.pprn"]
    assert "filtre ignor" in res.erreurs[0]["message"]
    assert r.appels_vers(MOTIF_PPRN_DETAIL + "*") == []  # jamais de détail pour tout le pays
    assert res.bloc["commune"] == ATTENDU_RISQUES_COMMUNE and res.bloc["adresse"] is not None


@pytest.mark.parametrize("total, accepte", [(50, True), (51, False)], ids=["50_accepte", "51_refuse"])
def test_pprn_frontiere_de_la_garde_50_accepte_51_refuse(total, accepte):
    modele = fx("georisques_pprn_99001.json")["content"][0]
    contenu = [{**modele, "idGaspar": f"99DDT2000{k:04d}"} for k in range(total)]
    r = routeur_nominal()
    r.route(MOTIF_PPRN, rep_json({"totalElements": total, "totalPages": 1, "pageNumber": 0, "pageSize": 100,
                                  "content": contenu}))
    def detail_de_l_id_demande(requete):
        detail = fx("georisques_pprn_detail_99DDT20000001.json")
        detail["idGaspar"] = requete.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=detail)
    r.route(MOTIF_PPRN_DETAIL + "*", detail_de_l_id_demande)
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    if accepte:
        assert len(res.bloc["pprn"]) == 50
        assert len(r.appels_vers(MOTIF_PPRN_DETAIL + "*")) == 50
        assert not [e for e in res.erreurs if e["bloc"] == "risques.pprn"]
    else:
        assert res.bloc["pprn"] is None
        assert [e["bloc"] for e in res.erreurs] == ["risques.pprn"]
        assert r.appels_vers(MOTIF_PPRN_DETAIL + "*") == []  # la garde passe AVANT tout appel de détail


def _routeur_pprn(nombre: int) -> Routeur:
    """Routeur nominal avec `nombre` PPRN pour la commune, chaque détail renvoyant l'id demandé."""
    modele = fx("georisques_pprn_99001.json")["content"][0]
    contenu = [{**modele, "idGaspar": f"99DDT2000{k:04d}"} for k in range(nombre)]
    r = routeur_nominal()
    r.route(MOTIF_PPRN, rep_json({"totalElements": nombre, "totalPages": 1, "pageNumber": 0, "pageSize": 100,
                                  "content": contenu}))

    def detail_de_l_id_demande(requete):
        detail = fx("georisques_pprn_detail_99DDT20000001.json")
        detail["idGaspar"] = requete.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=detail)
    r.route(MOTIF_PPRN_DETAIL + "*", detail_de_l_id_demande)
    return r


def test_georisques_pause_pprn_est_de_0_2_seconde_cinq_appels_par_seconde():
    assert georisques.PAUSE_PPRN_S == 0.2


def test_pprn_pause_entre_deux_appels_de_detail_et_pas_avant_le_premier_ni_apres_le_dernier():
    r = _routeur_pprn(3)
    details_au_moment_de_la_pause: list[int] = []

    def sleep_espion(secondes: float) -> None:
        r.sleep(secondes)
        details_au_moment_de_la_pause.append(len(r.appels_vers(MOTIF_PPRN_DETAIL + "*")))

    res = georisques.collecter(r.client(), GEO, sleep=sleep_espion)
    assert len(res.bloc["pprn"]) == 3
    assert r.attentes == [georisques.PAUSE_PPRN_S, georisques.PAUSE_PPRN_S]  # 3 détails : 2 pauses
    assert details_au_moment_de_la_pause == [1, 2]  # après le 1er et le 2e détail, jamais avant le 1er


@pytest.mark.parametrize("nombre", [0, 1])
def test_pprn_aucune_pause_avec_zero_ou_un_seul_detail(nombre):
    r = _routeur_pprn(nombre)
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert len(res.bloc["pprn"]) == nombre
    assert r.attentes == []


def test_pprn_commune_absente_du_detail_sous_bloc_none_et_erreur():
    detail = fx("georisques_pprn_detail_99DDT20000001.json")
    detail["communes"] = [c for c in detail["communes"] if c["codeInsee"] != INSEE]
    r = routeur_nominal()
    r.route(MOTIF_PPRN_DETAIL + "99DDT20000001", rep_json(detail))
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["pprn"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.pprn"]
    assert res.erreurs[0]["message"]


def test_pprn_total_elements_zero_est_une_liste_vide_valide():
    r = routeur_nominal()
    r.route(MOTIF_PPRN, rep_json(fx("georisques_pprn_vide.json")))
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["pprn"] == []
    assert not [e for e in res.erreurs if e["bloc"] == "risques.pprn"]
    assert r.appels_vers(MOTIF_PPRN_DETAIL + "*") == []


def test_pprn_erreur_http_sur_le_detail_sous_bloc_none_les_autres_restent():
    r = routeur_nominal()
    r.route(MOTIF_PPRN_DETAIL + "99DDT20000001", rep_statut(500))
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["pprn"] is None
    assert [e["bloc"] for e in res.erreurs] == ["risques.pprn"]
    assert res.bloc["commune"] == ATTENDU_RISQUES_COMMUNE and res.bloc["adresse"] is not None
    assert r.attentes == [1, 2]  # `sleep` injecté transmis jusqu'à l'appel de détail


def _sans(cle: str) -> Callable[[dict], dict]:
    def retirer(charge: dict) -> dict:
        del charge[cle]
        return charge
    return retirer


@pytest.mark.parametrize("sous_bloc, motif, fichier, transformation", [
    pytest.param("adresse", MOTIF_RAPPORT, "georisques_rapport_risque.json", _sans("risquesNaturels"),
                 id="rapport_sans_risquesNaturels"),
    pytest.param("pprn", MOTIF_PPRN_DETAIL + "99DDT20000001", "georisques_pprn_detail_99DDT20000001.json",
                 _sans("communes"), id="detail_pprn_sans_communes"),
    pytest.param("pprn", MOTIF_PPRN, "georisques_pprn_99001.json", _sans("content"), id="liste_pprn_sans_content"),
])
def test_georisques_forme_inattendue_sous_bloc_none_et_erreur_pas_keyerror(sous_bloc, motif, fichier,
                                                                         transformation):
    r = routeur_nominal()
    r.route(motif, rep_json(transformation(fx(fichier))))
    res = georisques.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc[sous_bloc] is None
    assert [e["bloc"] for e in res.erreurs] == [f"risques.{sous_bloc}"]
    assert all(res.bloc[autre] is not None for autre in ("commune", "adresse", "pprn") if autre != sous_bloc)


def test_georisques_sources_une_par_sous_bloc_obtenu():
    res = georisques.collecter(routeur_nominal().client(), GEO)
    assert sorted(s["bloc"] for s in res.sources) == ["risques.adresse", "risques.commune", "risques.pprn"]
    assert all(s["url"].startswith(georisques.BASE) and s["licence"] for s in res.sources)


# ===========================================================================
# 1. Fiscalité locale (REI DGFiP)
# ===========================================================================

def test_fiscalite_locale_forme_exercice_entier_et_aucun_montant_de_taxe():
    r = routeur_nominal()
    res = fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc == {"exercice": 2025, "taux_global_tfb": 41.27, "taux_plein_teom": 14.3,
                        "libelle_commune": "EXEMPLEVILLE", "note": fiscalite_locale.NOTE}
    assert type(res.bloc["exercice"]) is int  # « 2025 » (chaîne) dans l'API
    # La base cadastrale n'est pas publique : le bloc ne contient aucun montant de taxe.
    assert set(res.bloc) == {"exercice", "taux_global_tfb", "taux_plein_teom", "libelle_commune", "note"}
    assert "base cadastrale" in res.bloc["note"] and "aucun montant" in res.bloc["note"]
    assert res.erreurs == []


def test_fiscalite_locale_requete_where_order_by_limit_select():
    r = routeur_nominal()
    fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)
    assert len(r.appels) == 1
    assert r.appels[0].url == f"https://{MOTIF_FISCALITE}"
    assert r.appels[0].params == {
        "where": f'insee_com="{INSEE}"', "order_by": "exercice desc", "limit": "1",
        "select": "exercice,libcom,insee_com,taux_global_tfb,taux_plein_teom",
    }


def test_fiscalite_locale_source_millesime_est_l_exercice():
    res = fiscalite_locale.collecter(routeur_nominal().client(), GEO)
    assert len(res.sources) == 1
    source = res.sources[0]
    assert source["bloc"] == "fiscalite_locale" and source["millesime"] == "2025"
    assert source["url"].startswith(fiscalite_locale.URL) and source["licence"]


def test_fiscalite_locale_teom_absente_donne_none_sans_erreur():
    reponse = fx("fiscalite_locale_99001.json")
    del reponse["results"][0]["taux_plein_teom"]
    r = Routeur().route(MOTIF_FISCALITE, rep_json(reponse))
    res = fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["taux_plein_teom"] is None
    assert res.bloc["taux_global_tfb"] == 41.27


def test_fiscalite_locale_results_vide_leve_opendata_error():
    r = Routeur().route(MOTIF_FISCALITE, rep_json(fx("fiscalite_locale_vide.json")))
    with pytest.raises(oh.OpendataError):
        fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)


def test_fiscalite_locale_ligne_d_une_autre_commune_filtre_ignore_leve_opendata_error():
    """Si le where était ignoré, results[0] serait la commune la plus récente de n'importe où : les taux
    d'une autre commune présentés pour Exempleville. La garde compare insee_com à la commune demandée."""
    reponse = fx("fiscalite_locale_99001.json")
    reponse["results"][0]["insee_com"] = "99003"
    r = Routeur().route(MOTIF_FISCALITE, rep_json(reponse))
    with pytest.raises(oh.OpendataError, match="ignor") as erreur:
        fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)
    assert "99003" in str(erreur.value)


def test_fiscalite_locale_taux_global_tfb_absent_leve_opendata_error():
    reponse = fx("fiscalite_locale_99001.json")
    del reponse["results"][0]["taux_global_tfb"]
    r = Routeur().route(MOTIF_FISCALITE, rep_json(reponse))
    with pytest.raises(oh.OpendataError):
        fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)


def test_fiscalite_locale_http_500_persistant_leve_opendata_error():
    r = Routeur().route(MOTIF_FISCALITE, rep_statut(500))
    with pytest.raises(oh.OpendataError):
        fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)
    assert len(r.appels) == 3
    assert r.attentes == [1, 2]  # `sleep` injecté transmis à get_json


@pytest.mark.parametrize("modification", [
    pytest.param(lambda reponse: reponse.pop("results"), id="sans_results"),
    pytest.param(lambda reponse: reponse.update(results="x"), id="results_non_liste"),
    pytest.param(lambda reponse: reponse["results"][0].pop("exercice"), id="sans_exercice"),
])
def test_fiscalite_locale_forme_inattendue_leve_opendata_error_pas_keyerror(modification):
    reponse = fx("fiscalite_locale_99001.json")
    modification(reponse)
    r = Routeur().route(MOTIF_FISCALITE, rep_json(reponse))
    with pytest.raises(oh.OpendataError):
        fiscalite_locale.collecter(r.client(), GEO, sleep=r.sleep)


# ===========================================================================
# 19. Fiche : clés, sources, erreurs isolées
# ===========================================================================

def test_fiche_cles_de_premier_niveau_exactement_CLES_dans_l_ordre():
    assert tuple(fiche_mod.CLES) == CLES_FICHE
    fiche, _ = fiche_nominale()
    assert tuple(fiche) == CLES_FICHE


def test_fiche_nominale_tous_les_blocs_remplis_aucune_erreur_et_json_serialisable():
    fiche, r = fiche_nominale()
    assert fiche["adresse_demandee"] == ADRESSE
    assert fiche["genere_le"] == GENERE_LE
    assert fiche["geocodage"] == GEO
    assert fiche["commune"] == {"insee": INSEE, "nom": "Exempleville", "code_postal": "99100"}
    for bloc in BLOCS_COLLECTES:
        assert fiche[bloc] is not None, bloc
    assert fiche["erreurs"] == []
    assert fiche["loyers"]["appartement"]["valeur_m2"] == 12.2718
    assert fiche["dvf"]["compteurs"]["retenues"] == 6
    assert fiche["dpe"]["commune_total"] == 4614 and fiche["dpe"]["a_l_adresse"]["total"] == 4
    assert fiche["risques"]["commune"]["libelle_commune"] == "EXEMPLEVILLE"
    assert fiche["fiscalite_locale"]["exercice"] == 2025
    json.dumps(fiche, ensure_ascii=False)  # ne lève pas
    assert all(a.entetes["user-agent"] == "immo-locatif-opendata/1.0" for a in r.appels)


def test_fiche_genere_le_iso_avec_fuseau_precision_seconde_sans_conversion_utc():
    avec_micro = MAINTENANT.replace(microsecond=987654)
    fiche, _ = fiche_nominale(maintenant=avec_micro)
    assert fiche["genere_le"] == GENERE_LE  # microsecondes tronquées, fuseau conservé (+02:00)


def test_fiche_genere_le_par_defaut_porte_un_fuseau():
    r = routeur_nominal()
    fiche = fiche_mod.construire_fiche(ADRESSE, client=r.client(), sleep=r.sleep)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", fiche["genere_le"])


def test_fiche_sources_entrees_completes_date_extraction_debut_de_genere_le():
    fiche, _ = fiche_nominale()
    sources = fiche["sources"]
    attendu = Counter({"geocodage": 1, "cadastre": 1, "urbanisme": 1, "batiment": 1, "copropriete": 1, "loyers": 4,
                       "dvf": 2, "dpe.commune_total": 1, "dpe.a_l_adresse": 1, "risques.commune": 1,
                       "risques.adresse": 1, "risques.pprn": 1, "fiscalite_locale": 1})
    # ancien attendu : sans "urbanisme", "batiment", "copropriete" ni "cadastre"
    assert Counter(s["bloc"] for s in sources) == attendu
    for s in sources:
        assert set(s) == {"bloc", "url", "date_extraction", "licence", "millesime"}
        assert s["date_extraction"] == fiche["genere_le"][:10] == "2026-10-03"  # date locale, pas UTC
        assert s["url"].startswith("https://") and s["licence"]
    groupes = list(dict.fromkeys(s["bloc"].split(".")[0] for s in sources))
    assert groupes == ["geocodage", "cadastre", "urbanisme", "batiment", "copropriete", "loyers", "dvf", "dpe",
                       "risques", "fiscalite_locale"]  # ancien attendu : sans "urbanisme", "batiment", "copropriete"
    assert sorted(s["millesime"] for s in sources if s["bloc"] == "dvf") == ["2024", "2025"]
    assert {s["millesime"] for s in sources if s["bloc"] == "loyers"} == {"2025"}
    assert [s["millesime"] for s in sources if s["bloc"] == "fiscalite_locale"] == ["2025"]


def test_fiche_dvf_recoit_la_date_locale_de_maintenant_et_les_parametres_rayon_et_fenetre():
    fiche, _ = fiche_nominale()
    assert fiche["dvf"]["parametres"]["date_debut_fenetre"] == "2024-10-03"  # 24 mois avant le 03/10/2026
    assert fiche["dvf"]["parametres"]["rayon_m"] == 500 and fiche["dvf"]["parametres"]["fenetre_mois"] == 24
    fiche, _ = fiche_nominale(rayon_m=250, fenetre_mois=12)
    assert fiche["dvf"]["parametres"]["rayon_m"] == 250 and fiche["dvf"]["parametres"]["fenetre_mois"] == 12
    assert fiche["dvf"]["parametres"]["date_debut_fenetre"] == "2025-10-03"
    assert fiche["dvf"]["parametres"]["annees"] == [2025, 2026]


def test_fiche_fin_de_mois_31_mars_moins_1_mois_et_annee_courante_seule():
    maintenant = datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    csv_2026 = csv_dvf(
        mutation("2026-960001", [maison(100, 4)], date_mutation="2026-03-02"),
        mutation("2026-960002", [maison(100, 4)], date_mutation="2026-02-27"),
    )
    r = routeur_nominal()
    r.route(url_dvf(2026), rep_csv(csv_2026))
    fiche, _ = fiche_nominale(r, maintenant=maintenant, fenetre_mois=1)
    p, c = fiche["dvf"]["parametres"], fiche["dvf"]["compteurs"]
    assert p["date_debut_fenetre"] == "2026-02-28" and p["annees"] == [2026] and p["annees_absentes"] == []
    assert (c["retenues"], c["exclues_hors_fenetre"]) == (1, 1)
    assert not r.appels_vers(url_dvf(2025)) and not r.appels_vers(url_dvf(2024))


def test_fiche_drapeau_avant_reforme_present_sur_chaque_dpe_a_l_adresse_de_bout_en_bout():
    fiche, _ = fiche_nominale()
    dpe_adresse = fiche["dpe"]["a_l_adresse"]["dpe"]
    assert len(dpe_adresse) == 4
    assert all("avant_reforme_coef_elec" in d for d in dpe_adresse)
    assert [d["avant_reforme_coef_elec"] for d in dpe_adresse] == [True, False, False, None]


def test_fiche_geocodage_type_municipality_a_l_adresse_none_erreurs_dans_l_ordre_code_3():
    """Recette « Exempleville 99100 » : géocodage de type municipality, pas de numéro de rue."""
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_commune.json")))
    fiche, _ = fiche_nominale(r)
    assert fiche["geocodage"]["type"] == "municipality"
    assert fiche["commune"] == {"insee": INSEE, "nom": "Exempleville", "code_postal": "99100"}
    assert fiche["dpe"]["a_l_adresse"] is None and fiche["dpe"]["commune_total"] == 4614
    assert fiche["risques"]["adresse"] is None and fiche["risques"]["commune"] is not None
    assert blocs_erreurs(fiche) == ["dpe.a_l_adresse", "risques.adresse"]  # ordre d'apparition
    assert all(set(e) == {"bloc", "message"} and e["message"] for e in fiche["erreurs"])
    assert not any(a.params.get("qs", "").startswith("adresse_ban:") for a in r.appels)
    assert not r.appels_vers(MOTIF_RAPPORT)
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0 (fiche partielle signalée par le code 3)


def test_fiche_loyers_en_echec_http_500_aucun_zero_les_autres_blocs_restent():
    r = routeur_nominal()
    for rid in RESSOURCES_ATTENDUES.values():
        r.route(motif_loyers(rid), rep_statut(500))
    fiche, r = fiche_nominale(r)
    assert r.attentes == [1, 2] * 4  # `sleep` transmis aux quatre types : (1 s, 2 s) par type, aucune attente réelle
    loyers_fiche = fiche["loyers"]
    assert loyers_fiche is None or (isinstance(loyers_fiche, dict) and len(loyers_fiche) == 4
                                    and all(v is None for v in loyers_fiche.values()))
    erreurs_loyers = [e for e in fiche["erreurs"] if e["bloc"].split(".")[0] == "loyers"]
    assert erreurs_loyers and all(e["message"] for e in erreurs_loyers)
    assert not [s for s in fiche["sources"] if s["bloc"] == "loyers"]
    for bloc in ("dvf", "dpe", "risques", "fiscalite_locale"):
        assert fiche[bloc] is not None
    assert_aucun_faux_zero(fiche)
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0


@pytest.mark.parametrize("bloc, motif, reponse, attentes", [
    pytest.param("dvf", MOTIF_DVF + "*", rep_statut(404), [], id="dvf_toutes_annees_absentes"),
    pytest.param("fiscalite_locale", MOTIF_FISCALITE, rep_statut(500), [1, 2], id="fiscalite_http_500"),
    pytest.param("fiscalite_locale", MOTIF_FISCALITE, rep_json(fx("fiscalite_locale_vide.json")), [],
                 id="fiscalite_commune_absente"),
    # les trois nouveaux blocs échouent seuls, comme les autres
    pytest.param("urbanisme", MOTIF_GPU_SERVITUDES, rep_statut(500), [1, 2], id="urbanisme_http_500_dernier_appel"),
    pytest.param("batiment", MOTIF_BDNB_GROUPES, rep_statut(500), [1, 2], id="batiment_http_500"),
    pytest.param("copropriete", MOTIF_RNIC, rep_statut(500), [1, 2], id="copropriete_http_500"),
    pytest.param("copropriete", MOTIF_RNIC, rep_statut(403), [], id="copropriete_ressource_refusee_sans_repli"),
])
def test_fiche_bloc_en_echec_total_est_none_avec_une_seule_erreur_les_autres_restent_remplis(
        bloc, motif, reponse, attentes):
    r = routeur_nominal()
    r.route(motif, reponse)
    fiche, _ = fiche_nominale(r)
    assert r.attentes == attentes  # un 5xx est rejoué avec le `sleep` injecté ; un 404 ou une absence ne l'est pas
    assert fiche[bloc] is None
    assert blocs_erreurs(fiche) == [bloc]
    assert fiche["erreurs"][0]["message"]
    for autre in BLOCS_COLLECTES:
        if autre != bloc:
            assert fiche[autre] is not None, autre
    assert not [s for s in fiche["sources"] if s["bloc"].split(".")[0] == bloc]
    assert_aucun_faux_zero(fiche)
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0


def test_fiche_dvf_en_http_500_sur_chaque_annee_transmet_sleep_a_dvf():
    r = routeur_nominal()
    r.route(MOTIF_DVF + "*", rep_statut(500))
    fiche, _ = fiche_nominale(r)
    assert fiche["dvf"] is None and blocs_erreurs(fiche) == ["dvf"]
    assert r.attentes[:2] == [1, 2]  # première année lue : trois tentatives, deux attentes injectées
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0


def test_fiche_dpe_en_http_500_sur_les_deux_recherches_transmet_sleep_a_dpe():
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_statut(500))  # recherche commune ET recherche à l'adresse
    fiche, _ = fiche_nominale(r)
    assert r.attentes == [1, 2, 1, 2]
    assert {bloc.split(".")[0] for bloc in blocs_erreurs(fiche)} == {"dpe"}
    assert fiche["loyers"] is not None and fiche["fiscalite_locale"] is not None
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0


@pytest.mark.parametrize("cas", ["reponse_qui_leve_la_garde", "requete_sans_route"])
def test_fiche_ne_masque_pas_un_appel_reseau_imprevu_en_erreur_de_bloc(cas):
    """AppelInterdit (BaseException) remonte : `construire_fiche` ne capte que les `Exception`."""
    if cas == "reponse_qui_leve_la_garde":
        r = routeur_nominal()
        r.route(MOTIF_FISCALITE, AppelInterdit)
    else:
        r = Routeur().route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_housenumber.json")))  # aucune autre route
    with pytest.raises(AppelInterdit):
        fiche_nominale(r)


@pytest.mark.parametrize("bloc, motif", [
    pytest.param("fiscalite_locale", MOTIF_FISCALITE, id="fiscalite_locale"),
    pytest.param("dvf", MOTIF_DVF + "*", id="dvf"),
    pytest.param("urbanisme", MOTIF_GPU_ZONE, id="urbanisme"),  # les trois suivants : 
    pytest.param("batiment", MOTIF_BDNB_GROUPES, id="batiment"),
    pytest.param("copropriete", MOTIF_RNIC, id="copropriete"),
])
def test_fiche_exception_inattendue_dans_un_collecteur_bloc_none_et_type_dans_le_message(bloc, motif):
    """Une forme d'API qui change (KeyError...) ne doit pas faire planter la fiche."""
    r = routeur_nominal()
    r.route(motif, KeyError("boom"))
    fiche, _ = fiche_nominale(r)
    assert fiche[bloc] is None
    assert blocs_erreurs(fiche) == [bloc]
    assert fiche["erreurs"][0]["message"] == "KeyError: 'boom'"
    for autre in BLOCS_COLLECTES:
        if autre != bloc:
            assert fiche[autre] is not None, autre
    assert fiche_mod.code_sortie(fiche) == 3  # ancien attendu : 0


@pytest.mark.parametrize("score, code", [(0.5, 0), (0.4999, 2), (0.96, 0), (0.0, 2)])
def test_fiche_score_frontiere_0_5_accepte_en_dessous_code_2(score, code):
    payload = fx("geocodage_housenumber.json")
    payload["features"][0]["properties"]["score"] = score
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(payload))
    fiche, _ = fiche_nominale(r)
    assert fiche_mod.code_sortie(fiche) == code
    assert (fiche["loyers"] is not None) == (code == 0)


@pytest.mark.parametrize("fiche_geocodage, attendu", [
    ({"geocodage": None}, 2),
    ({"geocodage": {"score": 0.45}}, 2),
    ({"geocodage": {"score": 0.5}}, 0),
    # 4e cas (géocodage 0,96 + une erreur dvf -> 0) déplacé dans le test du code 3 ci-dessous : ancien attendu 0.
])
def test_code_sortie_2_si_geocodage_absent_ou_score_inferieur_a_0_5_sinon_0(fiche_geocodage, attendu):
    assert fiche_mod.code_sortie(fiche_geocodage) == attendu


ERREUR_DVF = {"bloc": "dvf", "message": "x"}


@pytest.mark.parametrize("fiche_partielle, attendu", [
    pytest.param({"geocodage": {"score": 0.96}, "erreurs": [ERREUR_DVF], "dvf": None}, 3, id="une_erreur_de_bloc"),
    pytest.param({"geocodage": {"score": 0.96}, "erreurs": [ERREUR_DVF, {"bloc": "dpe", "message": "y"}]}, 3,
                 id="deux_erreurs"),
    pytest.param({"geocodage": {"score": 0.96}, "erreurs": []}, 0, id="aucune_erreur"),
    pytest.param({"geocodage": {"score": 0.96}}, 0, id="cle_erreurs_absente"),
    pytest.param({"geocodage": {"score": 0.96}, "erreurs": [], "alertes": [{"bloc": "dvf", "message": "z"}]}, 0,
                 id="une_alerte_seule_ne_change_pas_le_code"),
    pytest.param({"geocodage": None, "erreurs": [{"bloc": "geocodage", "message": "x"}]}, 2,
                 id="geocodage_absent_prime_sur_3"),
    pytest.param({"geocodage": {"score": 0.45}, "erreurs": [ERREUR_DVF]}, 2, id="score_faible_prime_sur_3"),
    pytest.param({"geocodage": {"score": 0.5}, "erreurs": [ERREUR_DVF]}, 3, id="score_frontiere_0_5_et_erreur"),
])
def test_code_sortie_3_si_erreurs_non_vide_apres_le_geocodage_sinon_0(fiche_partielle, attendu):
    assert fiche_mod.code_sortie(fiche_partielle) == attendu


# --- 16. Géocodage en échec : code 2, aucun autre appel, JSON quand même écrit ---------------

CAS_GEOCODAGE_ECHEC = [
    pytest.param(rep_json(fx("geocodage_vide.json")), 1, False, id="features_vide"),
    pytest.param(rep_statut(500), 3, False, id="http_500_persistant"),
    pytest.param(rep_json(fx("geocodage_score_faible.json")), 1, True, id="score_0_45"),
]


@pytest.mark.parametrize("reponse, appels_geocodage, geocodage_garde", CAS_GEOCODAGE_ECHEC)
def test_fiche_geocodage_en_echec_code_2_tous_blocs_none_aucun_autre_appel(reponse, appels_geocodage,
                                                                           geocodage_garde):
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, reponse)
    fiche, _ = fiche_nominale(r)
    assert fiche_mod.code_sortie(fiche) == 2
    assert tuple(fiche) == CLES_FICHE
    assert fiche["commune"] is None
    for bloc in BLOCS_COLLECTES:
        assert fiche[bloc] is None, bloc
    assert blocs_erreurs(fiche) == ["geocodage"]
    if geocodage_garde:  # score trop faible : le géocodage est CONSERVÉ pour qu'on voie le score
        assert fiche["geocodage"]["score"] == 0.4520816883116883
        message = fiche["erreurs"][0]["message"]
        assert "score" in message and ("0,5" in message or "0.5" in message)
    else:
        assert fiche["geocodage"] is None
        assert fiche["sources"] == []
    assert {a.cle for a in r.appels} == {MOTIF_GEOCODAGE}  # AUCUN autre appel réseau émis
    assert len(r.appels) == appels_geocodage
    assert r.attentes == ([1, 2] if appels_geocodage == 3 else [])


@pytest.mark.parametrize("reponse, appels_geocodage, geocodage_garde", CAS_GEOCODAGE_ECHEC)
def test_main_geocodage_en_echec_ecrit_quand_meme_le_json_et_sort_en_code_2(script, tmp_path, capsys, reponse,
                                                                          appels_geocodage, geocodage_garde):
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, reponse)
    sortie = tmp_path / "fiche.json"
    sortie.write_text('{"fiche": "périmée"}', encoding="utf-8")  # un fichier périmé ne doit pas survivre
    code = script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=r.client(),
                       maintenant=MAINTENANT, sleep=r.sleep)
    assert code == 2
    ecrit = json.loads(sortie.read_text(encoding="utf-8"))
    assert tuple(ecrit) == CLES_FICHE
    assert ecrit["commune"] is None and all(ecrit[b] is None for b in BLOCS_COLLECTES)
    assert [e["bloc"] for e in ecrit["erreurs"]] == ["geocodage"]
    assert (ecrit["geocodage"] is not None) == geocodage_garde
    assert capsys.readouterr().out.strip()  # le résumé s'affiche aussi en cas d'échec


# --- resume -----------------------------------------------------------------------------

def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c)).lower()


def test_resume_entre_6_et_14_lignes_une_par_bloc_erreurs_et_chemin(tmp_path):
    fiche, _ = fiche_nominale()
    chemin = tmp_path / "fiche.json"
    texte = fiche_mod.resume(fiche, chemin)
    lignes = texte.splitlines()
    assert 6 <= len(lignes) <= 14  # ancienne borne : 11 (une évolution ajoute 3 lignes :
    # urbanisme, bâtiment, copropriété) ; avant : 10 (une évolution avait ajouté 2 lignes)
    assert all(ligne.strip() for ligne in lignes)  # pas de ligne vide
    assert str(chemin) in lignes[-1] and "fiche ecrite" in _sans_accents(lignes[-1])
    plat = _sans_accents(texte)
    for mot in ("geocodage", "loyers", "dvf", "dpe", "risques", "taxe", "erreur", "urbanisme", "batiment",
                "copropriete"):  # ancien attendu : sans les trois derniers mots
        assert mot in plat, mot


@pytest.mark.parametrize("cas", ["geocodage_en_echec", "bloc_en_echec", "municipality"])
def test_resume_reste_entre_6_et_14_lignes_quand_des_blocs_sont_none(tmp_path, cas):
    r = routeur_nominal()
    if cas == "geocodage_en_echec":
        r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    elif cas == "bloc_en_echec":
        r.route(MOTIF_FISCALITE, rep_statut(500))
    else:
        r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_commune.json")))
    fiche, _ = fiche_nominale(r)
    lignes = fiche_mod.resume(fiche, tmp_path / "fiche.json").splitlines()
    assert 6 <= len(lignes) <= 14  # ancienne borne : 11 (avant une évolution : 10)
    assert all(ligne.strip() for ligne in lignes)


# ===========================================================================
# 19 + 14. Script : arguments, écriture, code de sortie
# ===========================================================================

def test_main_ecrit_un_json_valide_cree_le_dossier_parent_affiche_le_resume_code_0(script, tmp_path, capsys):
    r = routeur_nominal()
    client = r.client()
    sortie = tmp_path / "dossier" / "sous_dossier" / "fiche.json"
    assert not sortie.parent.exists()
    code = script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=client, maintenant=MAINTENANT,
                       sleep=r.sleep)
    assert code == 0
    brut = sortie.read_text(encoding="utf-8")
    donnees = json.loads(brut)
    assert tuple(donnees) == CLES_FICHE
    assert donnees["adresse_demandee"] == ADRESSE and donnees["genere_le"] == GENERE_LE
    assert donnees["erreurs"] == []
    assert brut.startswith('{\n  "adresse_demandee"')  # indent=2
    assert brut.endswith("\n")
    assert "Électricité" in brut and "\\u00c9" not in brut  # ensure_ascii=False
    affiche = capsys.readouterr().out
    assert 6 <= len(affiche.strip().splitlines()) <= 14  # ancienne borne : 11 (auparavant : 10)
    assert str(sortie) in affiche
    assert not client.is_closed  # un client fourni par l'appelant n'est pas fermé


def test_main_affiche_les_trois_lignes_reglementaires_du_resume(script, tmp_path, capsys):
    r = routeur_nominal()
    code = script.main(["--adresse", ADRESSE, "--out", str(tmp_path / "fiche.json")], client=r.client(),
                       maintenant=MAINTENANT, sleep=r.sleep)
    assert code == 0
    sortie = capsys.readouterr().out.splitlines()
    assert [ligne.split(" :")[0] for ligne in sortie[2:5]] == ["Urbanisme", "Bâtiment", "Copropriété"]
    assert len(sortie) == 14


def test_main_sans_client_injecte_cree_un_client_http_avec_user_agent_et_le_ferme(script, tmp_path, monkeypatch):
    """client=None : le script fabrique son client (make_client) et le FERME en sortie ; ici ses requêtes
    sont détournées vers le routeur au niveau du transport par défaut, sans aucun appel réseau."""
    r = routeur_nominal()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, requete: r.repondre_a(requete))
    crees: list[httpx.Client] = []
    init_origine = httpx.Client.__init__

    def init_espion(self, *args, **kwargs):
        init_origine(self, *args, **kwargs)
        crees.append(self)

    monkeypatch.setattr(httpx.Client, "__init__", init_espion)
    code = script.main(["--adresse", ADRESSE, "--out", str(tmp_path / "fiche.json")], maintenant=MAINTENANT,
                       sleep=r.sleep)
    assert code == 0
    assert r.appels
    assert all(a.entetes["user-agent"] == "immo-locatif-opendata/1.0" for a in r.appels)
    assert len(crees) == 1 and crees[0].is_closed  # ni fuite de client, ni client créé en double


def test_main_rayon_et_fenetre_mois_sont_transmis_a_dvf(script, tmp_path):
    r = routeur_nominal()
    sortie = tmp_path / "fiche.json"
    code = script.main(["--adresse", ADRESSE, "--rayon", "250", "--fenetre-mois", "12", "--out", str(sortie)],
                       client=r.client(), maintenant=MAINTENANT, sleep=r.sleep)
    assert code == 0
    p = json.loads(sortie.read_text(encoding="utf-8"))["dvf"]["parametres"]
    assert (p["rayon_m"], p["fenetre_mois"], p["date_debut_fenetre"]) == (250, 12, "2025-10-03")


def test_main_valeurs_par_defaut_rayon_500_fenetre_24_mois(script, tmp_path):
    r = routeur_nominal()
    sortie = tmp_path / "fiche.json"
    script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=r.client(), maintenant=MAINTENANT,
                sleep=r.sleep)
    p = json.loads(sortie.read_text(encoding="utf-8"))["dvf"]["parametres"]
    assert (p["rayon_m"], p["fenetre_mois"]) == (500, 24)


@pytest.mark.parametrize("argv", [
    [],
    ["--adresse", ADRESSE],
    ["--out", "fiche.json"],
    ["--adresse", ADRESSE, "--out", "fiche.json", "--rayon", "abc"],
    ["--adresse", ADRESSE, "--out", "fiche.json", "--fenetre-mois", "x"],
], ids=["aucun", "sans_out", "sans_adresse", "rayon_non_entier", "fenetre_non_entiere"])
def test_main_arguments_obligatoires_ou_invalides_argparse_sort_en_code_2(script, argv):
    r = routeur_nominal()
    with pytest.raises(SystemExit) as exc:
        script.main(argv, client=r.client(), maintenant=MAINTENANT, sleep=r.sleep)
    assert exc.value.code == 2
    assert r.appels == []  # rien n'est appelé avant la validation des arguments


def test_main_georisques_adresse_trois_echecs_fiche_produite_code_3_json_ecrit(script, tmp_path):
    """trois échecs sur resultats_rapport_risque -> risques.adresse None, EXACTEMENT UNE entrée
    d'erreur de ce bloc, fiche produite par le script, code de sortie 3 (ancien attendu : 0), JSON écrit."""
    r = routeur_nominal()
    r.route(MOTIF_RAPPORT, httpx.ConnectError)
    sortie = tmp_path / "fiche.json"
    code = script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=r.client(), maintenant=MAINTENANT,
                       sleep=r.sleep)
    assert code == 3
    fiche = json.loads(sortie.read_text(encoding="utf-8"))
    assert fiche["risques"]["adresse"] is None
    assert [e["bloc"] for e in fiche["erreurs"]].count("risques.adresse") == 1
    assert len(fiche["erreurs"]) == 1
    assert fiche["risques"]["commune"] is not None and fiche["risques"]["pprn"] is not None
    for bloc in ("loyers", "dvf", "dpe", "fiscalite_locale"):
        assert fiche[bloc] is not None
    assert len(r.appels_vers(MOTIF_RAPPORT)) == 3
    assert r.attentes == [1, 2]


def test_main_georisques_adresse_deux_echecs_puis_succes_aucune_erreur(script, tmp_path):
    r = routeur_nominal()
    r.route(MOTIF_RAPPORT, [httpx.ConnectError("1"), httpx.ReadError("2"),
                            rep_json(fx("georisques_rapport_risque.json"))])
    sortie = tmp_path / "fiche.json"
    code = script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=r.client(), maintenant=MAINTENANT,
                       sleep=r.sleep)
    assert code == 0
    fiche = json.loads(sortie.read_text(encoding="utf-8"))
    assert fiche["risques"]["adresse"] is not None
    assert fiche["erreurs"] == []
    assert r.attentes == [1, 2]


# --- Code de sortie 3 : fiche partielle signalée, blocs en échec sur stderr ---------

def _lancer(script, tmp_path, r: Routeur) -> tuple[int, dict]:
    sortie = tmp_path / "fiche.json"
    code = script.main(["--adresse", ADRESSE, "--out", str(sortie)], client=r.client(), maintenant=MAINTENANT,
                       sleep=r.sleep)
    return code, json.loads(sortie.read_text(encoding="utf-8"))


def test_main_fiche_complete_code_0_et_stderr_vide(script, tmp_path, capsys):
    code, fiche = _lancer(script, tmp_path, routeur_nominal())
    assert code == 0 and fiche["erreurs"] == []
    sortie = capsys.readouterr()
    assert sortie.err == ""
    assert sortie.out.strip()


def test_main_risques_en_echec_code_3_json_ecrit_et_bloc_nomme_sur_stderr(script, tmp_path, capsys):
    r = routeur_nominal()
    r.route(MOTIF_RISQUES, rep_statut(500))
    r.route(MOTIF_RAPPORT, rep_statut(500))
    r.route(MOTIF_PPRN, rep_statut(500))
    code, fiche = _lancer(script, tmp_path, r)
    assert code == 3
    assert [e["bloc"] for e in fiche["erreurs"]] == ["risques.commune", "risques.adresse", "risques.pprn"]
    sortie = capsys.readouterr()
    lignes = sortie.err.splitlines()
    assert len(lignes) == 3  # une ligne par bloc en échec
    for ligne, erreur in zip(lignes, fiche["erreurs"]):
        assert ligne.startswith(erreur["bloc"]) and erreur["message"] in ligne
    assert "Erreurs : 3" in sortie.out  # le résumé reste sur stdout


def test_main_stderr_une_ligne_par_erreur_meme_si_le_message_en_contient_plusieurs(script, tmp_path, capsys,
                                                                                    monkeypatch):
    fiche_partielle = {c: None for c in CLES_FICHE}
    fiche_partielle.update(geocodage={"score": 0.96, "label": "x", "type": "housenumber", "citycode": INSEE},
                           sources=[], alertes=[],
                           erreurs=[{"bloc": "dvf", "message": "premiere\nseconde   ligne"},
                                    {"bloc": "dpe", "message": "autre"}])
    monkeypatch.setattr(script, "construire_fiche", lambda *a, **k: fiche_partielle)
    code = script.main(["--adresse", ADRESSE, "--out", str(tmp_path / "f.json")], client=Routeur().client())
    assert code == 3
    assert capsys.readouterr().err.splitlines() == ["dvf : premiere seconde ligne", "dpe : autre"]


def test_main_une_alerte_seule_garde_le_code_0_et_stderr_vide(script, tmp_path, capsys, monkeypatch):
    fiche_alerte = {c: None for c in CLES_FICHE}
    fiche_alerte.update(geocodage={"score": 0.96, "label": "x", "type": "housenumber", "citycode": INSEE},
                        sources=[], erreurs=[], alertes=[{"bloc": "dvf", "message": "fenêtre courte"}])
    monkeypatch.setattr(script, "construire_fiche", lambda *a, **k: fiche_alerte)
    code = script.main(["--adresse", ADRESSE, "--out", str(tmp_path / "f.json")], client=Routeur().client())
    assert code == 0
    assert capsys.readouterr().err == ""


def test_main_geocodage_en_echec_garde_le_code_2_pas_3(script, tmp_path):
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    code, fiche = _lancer(script, tmp_path, r)
    assert code == 2 and [e["bloc"] for e in fiche["erreurs"]] == ["geocodage"]


# ===========================================================================
# DVF : ventes d'immeubles (`dvf.immeubles`, )
# ===========================================================================

TYPE_ACTIVITE = "Local industriel. commercial ou assimilé"
CLES_BLOC_IMMEUBLES = {"parametres", "statistiques", "reference", "ventes", "compteurs"}  # `reference` : 


def immeuble(id_mutation: str, valeur: Any, logements: tuple = (50, 50), activite: tuple = (), **kw: Any):
    """Vente de plusieurs locaux : un appartement par surface de `logements` (lots distincts), un local
    commercial par surface de `activite`, tous sur la même parcelle."""
    locaux = [appart(s, 3, lot=str(rang)) for rang, s in enumerate(logements, start=1)]
    locaux += [commercial(s) for s in activite]
    return mutation(id_mutation, locaux, valeur=str(valeur), **kw)


def immeubles_de(csv_par_annee: dict[int, str | int], **kw: Any):
    kw.setdefault("fenetre_immeubles_mois", dvf.FENETRE_IMMEUBLES_MOIS)
    res, r = collecter_dvf(csv_par_annee, **kw)
    return res.bloc["immeubles"], res, r


def test_immeubles_constantes_du_contrat():
    assert dvf.FENETRE_IMMEUBLES_MOIS == 60
    assert dvf.N_MIN_MEDIANE_IMMEUBLES == 3
    assert dvf.NB_IMMEUBLES == 20


def test_immeubles_vente_de_3_locaux_2_apparts_et_1_commerce_presente_et_absente_des_comparables():
    csv = csv_dvf(immeuble("2025-970001", 300000, logements=(60, 70), activite=(40,), nord_m=150, numero="12"))
    bloc, res, _ = immeubles_de({2025: csv})
    assert set(bloc) == CLES_BLOC_IMMEUBLES
    assert bloc["ventes"] == [{
        "id_mutation": "2025-970001", "date": "2025-11-20", "valeur_fonciere": 300000.0,
        "nb_logements": 2, "nb_locaux_activite": 1, "surface_bati_m2": 170.0,
        "eur_m2_bati": 1764.71, "eur_par_logement": 150000.0, "distance_m": 150,
        "adresse": "12 RUE DE TEST", "types_locaux": {"Appartement": 2, TYPE_ACTIVITE: 1},
        # champs ajoutés par une évolution (2 logements : hors référence)
        "surface_habitation_m2": 130.0, "surface_activite_m2": 40.0, "parcelles": [f"{INSEE}000970001"],
        "atypique": [], "dans_reference": False,
    }]
    assert "2025-970001" not in ids_comparables(res)
    assert res.bloc["compteurs"]["exclues_multi_locaux"] == 1  # le compteur historique des comparables ne bouge pas
    assert res.bloc["compteurs"]["retenues"] == 0


def test_immeubles_maison_plus_local_commercial_un_seul_logement():
    csv = csv_dvf(mutation("2025-970002", [maison(110, 5), commercial(40)], valeur="260000", nord_m=120))
    vente = immeubles_de({2025: csv})[0]["ventes"][0]
    assert (vente["nb_logements"], vente["nb_locaux_activite"], vente["surface_bati_m2"]) == (1, 1, 150.0)
    assert vente["eur_par_logement"] == 260000.0 and vente["eur_m2_bati"] == 1733.33
    assert vente["types_locaux"] == {"Maison": 1, TYPE_ACTIVITE: 1}


def test_immeubles_quatre_appartements_identiques_sans_lot_sont_quatre_logements_surface_multipliee():
    """Cas réel de Exempleville (docstring de `_nb_locaux`) : même signature répétée = locaux distincts."""
    csv = csv_dvf(mutation("2025-970003", [appart(25, 1, lot="")] * 4, valeur="200000"))
    vente = immeubles_de({2025: csv})[0]["ventes"][0]
    assert (vente["nb_logements"], vente["surface_bati_m2"]) == (4, 100.0)
    assert vente["eur_m2_bati"] == 2000.0 and vente["eur_par_logement"] == 50000.0
    assert vente["valeur_fonciere"] == 200000.0  # le prix de la vente, une seule fois


def test_immeubles_une_maison_repetee_par_culture_et_une_dependance_ne_sont_pas_un_immeuble():
    csv = csv_dvf(
        mutation("2025-970004", [maison(100, 4, culture="sols"), maison(100, 4, culture="jardins")]),
        mutation("2025-970005", [maison(100, 4), dependance(12)]),
    )
    bloc = immeubles_de({2025: csv})[0]
    assert bloc["ventes"] == [] and bloc["compteurs"]["multi_locaux_vues"] == 0


def test_immeubles_n_inferieur_a_3_medianes_null_avec_la_raison():
    csv = csv_dvf(immeuble("2025-970101", 100000, nord_m=50), immeuble("2025-970102", 200000, nord_m=60))
    statistiques = immeubles_de({2025: csv})[0]["statistiques"]
    assert statistiques["n"] == 2 and statistiques["n_min"] == 3
    assert statistiques["mediane_eur_m2_bati"] is None and statistiques["mediane_eur_par_logement"] is None
    assert "n = 2 < 3" in statistiques["raison_mediane_absente"]


def test_immeubles_aucune_vente_n_0_medianes_null_et_liste_vide_pas_de_faux_zero():
    bloc = immeubles_de({2025: csv_dvf(mutation("2025-970103", [maison(100, 4)]))})[0]
    assert bloc["ventes"] == []
    assert bloc["statistiques"]["n"] == 0
    assert bloc["statistiques"]["mediane_eur_m2_bati"] is None
    assert "n = 0 < 3" in bloc["statistiques"]["raison_mediane_absente"]


def test_immeubles_n_egal_3_medianes_calculees_sur_les_trois_ventes_et_sans_raison():
    """A : 1 logement + 1 commerce, 100 m2, 100 000 -> 1 000 €/m2 et 100 000 €/logement.
    B : 3 logements, 100 m2, 300 000 -> 3 000 et 100 000. C : 2 logements, 100 m2, 150 000 -> 1 500 et 75 000.
    Médiane €/m2 = 1 500 (C) ; médiane €/logement = 100 000 (A ou B) : les deux médianes viennent de ventes
    différentes, jamais d'une même vente retenue."""
    csv = csv_dvf(
        immeuble("2025-970201", 100000, logements=(50,), activite=(50,), nord_m=10),
        immeuble("2025-970202", 300000, logements=(40, 30, 30), nord_m=20),
        immeuble("2025-970203", 150000, logements=(60, 40), nord_m=30),
    )
    statistiques = immeubles_de({2025: csv})[0]["statistiques"]
    assert statistiques["n"] == 3
    assert statistiques["mediane_eur_m2_bati"] == 1500.0
    assert statistiques["mediane_eur_par_logement"] == 100000.0
    assert statistiques["raison_mediane_absente"] is None


def test_immeubles_mediane_de_n_pair_est_la_moyenne_des_deux_valeurs_centrales():
    csv = csv_dvf(*(immeuble(f"2025-97030{k}", 100000 * k, nord_m=10 * k) for k in (1, 2, 3, 4)))  # 1000..4000 €/m2
    assert immeubles_de({2025: csv})[0]["statistiques"]["mediane_eur_m2_bati"] == 2500.0


def test_immeubles_ecartees_par_motif_chaque_vente_dans_un_seul_compteur_et_les_hors_perimetre_non_comptes():
    deux_commerces = [commercial(22), commercial(30)]
    csv_2025 = csv_dvf(
        immeuble("2025-971001", 200000, nord_m=10),                                          # retenue
        mutation("2025-971002", deux_commerces, valeur="150000"),                            # sans logement
        immeuble("2025-971003", "", nord_m=20),                                              # prix vide
        immeuble("2025-971004", 200000, logements=(40, 0), nord_m=20),                       # surface 0
        immeuble("2025-971005", 200000, nord_m=20, longitude="", latitude=""),               # sans coordonnées
        immeuble("2025-971006", 200000, nord_m=20, nature="Echange"),                        # hors périmètre : nature
        immeuble("2025-971012", 200000, nord_m=20, nature="Vente en l'état futur d'achèvement"),  # idem
        mutation("2025-971009", [maison(100, 4)], valeur="150000"),                          # un seul local
        mutation("2025-971010", [maison(100, 4), dependance(12)], valeur="150000"),          # un local + annexe
        mutation("2025-971011", [appart(25, 1, lot="")] * 4, valeur="200000", nord_m=40),    # retenue : 4 logements
        mutation("2025-971013", deux_commerces, valeur="", longitude="", latitude=""),       # sans logement d'abord
        immeuble("2025-971014", "", nord_m=20, longitude="", latitude=""),                   # prix d'abord
    )
    csv_2021 = csv_dvf(
        immeuble("2021-971007", 200000, nord_m=20, date_mutation="2021-10-02"),              # la veille du début
        immeuble("2021-971008", 200000, nord_m=20, date_mutation="2021-10-03"),              # le jour du début : retenue
    )
    bloc = immeubles_de({2025: csv_2025, 2021: csv_2021})[0]
    assert bloc["compteurs"] == {
        "multi_locaux_vues": 9, "retenues": 3,
        "ecartees": {"sans_logement": 2, "prix_ou_surface": 3, "sans_coordonnees": 1},
    }
    vues, retenues = bloc["compteurs"]["multi_locaux_vues"], bloc["compteurs"]["retenues"]
    assert vues == retenues + sum(bloc["compteurs"]["ecartees"].values())  # aucune vente ne disparaît sans trace
    assert sorted(v["id_mutation"] for v in bloc["ventes"]) == ["2021-971008", "2025-971001", "2025-971011"]
    assert bloc["statistiques"]["n"] == retenues == 3


def test_immeubles_tri_par_distance_plafond_de_20_et_statistiques_sur_toutes_les_ventes():
    """22 ventes à 10, 20... 220 m ; le prix monte avec la distance (1 000 à 3 100 €/m2). La médiane des 22 est
    2 050 ; celle des 20 premières (1 950) prouverait que les statistiques partent de la liste tronquée."""
    csv = csv_dvf(*(immeuble(f"2025-9720{k:02d}", 100000 + 10000 * k, nord_m=10 * (k + 1)) for k in range(22)))
    bloc = immeubles_de({2025: csv})[0]
    assert [v["id_mutation"] for v in bloc["ventes"]] == [f"2025-9720{k:02d}" for k in range(20)]
    assert [v["distance_m"] for v in bloc["ventes"]] == [10 * (k + 1) for k in range(20)]
    assert bloc["statistiques"]["n"] == bloc["compteurs"]["retenues"] == 22
    assert bloc["statistiques"]["mediane_eur_m2_bati"] == 2050.0
    assert bloc["parametres"]["plafond_ventes"] == 20


def test_immeubles_exactement_20_ventes_toutes_listees_et_21_en_ecarte_une():
    for nombre, listees in ((20, 20), (21, 20), (19, 19)):
        csv = csv_dvf(*(immeuble(f"2025-9730{k:02d}", 100000, nord_m=10 * (k + 1)) for k in range(nombre)))
        assert len(immeubles_de({2025: csv})[0]["ventes"]) == listees, nombre


def test_immeubles_a_distance_egale_l_id_de_mutation_departage_quel_que_soit_l_ordre_du_csv():
    csv = csv_dvf(immeuble("2025-974002", 100000, nord_m=50), immeuble("2025-974001", 100000, nord_m=50))
    assert [v["id_mutation"] for v in immeubles_de({2025: csv})[0]["ventes"]] == ["2025-974001", "2025-974002"]


def test_immeubles_parametres_dits_fenetre_annees_absentes_perimetre_commune():
    csv = csv_dvf(immeuble("2025-975001", 100000))
    bloc = immeubles_de({2025: csv})[0]
    assert bloc["parametres"] == {
        "fenetre_mois": 60, "date_debut_fenetre": "2021-10-03",
        "annees": [2021, 2022, 2023, 2024, 2025, 2026], "annees_absentes": [2021, 2022, 2023, 2024, 2026],
        "perimetre": f"commune {INSEE}", "natures": ["Vente", "Adjudication"], "plafond_ventes": 20,
    }


def test_immeubles_fenetre_parametrable_et_lue_dans_les_parametres():
    bloc = immeubles_de({2025: csv_dvf(immeuble("2025-975002", 100000))}, fenetre_immeubles_mois=36)[0]
    assert bloc["parametres"]["fenetre_mois"] == 36
    assert bloc["parametres"]["date_debut_fenetre"] == "2023-10-03"
    assert bloc["parametres"]["annees"] == [2023, 2024, 2025, 2026]


def test_immeubles_les_annees_hors_fenetre_des_comparables_ne_changent_pas_les_comparables():
    """Un fichier 2022 n'est lu que pour les immeubles : comparables, statistiques, compteurs et paramètres du
    bloc de premier niveau sont identiques avec ou sans lui."""
    csv_2025 = csv_dvf(mutation("2025-976001", [maison(100, 4)], valeur="200000"),
                       immeuble("2025-976002", 100000))
    csv_2022 = csv_dvf(mutation("2022-976003", [maison(100, 4)], date_mutation="2022-05-10"),
                       immeuble("2022-976004", 100000, date_mutation="2022-05-10"))
    sans = immeubles_de({2025: csv_2025})
    avec = immeubles_de({2022: csv_2022, 2025: csv_2025})
    for cle in ("parametres", "par_type", "atypiques", "comparables", "compteurs"):
        assert avec[1].bloc[cle] == sans[1].bloc[cle], cle
    assert [v["id_mutation"] for v in sans[0]["ventes"]] == ["2025-976002"]
    assert sorted(v["id_mutation"] for v in avec[0]["ventes"]) == ["2022-976004", "2025-976002"]
    assert avec[0]["parametres"]["annees_absentes"] == [2021, 2023, 2024, 2026]


def test_immeubles_sans_l_option_aucun_bloc_et_seules_les_annees_des_comparables_sont_demandees():
    res, r = collecter_dvf({2025: csv_dvf(immeuble("2025-977001", 100000))})
    assert "immeubles" not in res.bloc
    assert {a.cle for a in r.appels} == {url_dvf(2024), url_dvf(2025), url_dvf(2026)}


@pytest.mark.parametrize("fenetre", [None, 0])
def test_immeubles_option_absente_ou_nulle_desactive_le_bloc(fenetre):
    res, _ = collecter_dvf({2025: csv_dvf(immeuble("2025-977002", 100000))}, fenetre_immeubles_mois=fenetre)
    assert "immeubles" not in res.bloc


def test_immeubles_une_requete_par_annee_de_l_union_des_deux_fenetres_et_une_source_par_fichier_lu():
    csv = csv_dvf(immeuble("2025-977003", 100000))
    res, r = collecter_dvf({2022: csv_dvf(), 2025: csv}, fenetre_immeubles_mois=60)
    assert Counter(a.cle for a in r.appels) == Counter({url_dvf(a): 1 for a in range(2021, 2027)})
    assert sorted(s["millesime"] for s in res.sources) == ["2022", "2025"]
    assert res.erreurs == []


def test_immeubles_une_annee_ancienne_en_erreur_isole_le_bloc_les_comparables_restent():
    csv_2025 = csv_dvf(mutation("2025-978001", [maison(100, 4)], valeur="200000"), immeuble("2025-978002", 100000))
    r = routeur_dvf({2025: csv_2025, 2022: 500})
    res = dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep, fenetre_immeubles_mois=60)
    assert res.bloc["immeubles"] is None
    assert ids_comparables(res) == ["2025-978001"]
    assert [e["bloc"] for e in res.erreurs] == ["dvf.immeubles"]
    assert url_dvf(2022) in res.erreurs[0]["message"] and "500" in res.erreurs[0]["message"]
    assert r.attentes == [1, 2]
    assert sorted(s["millesime"] for s in res.sources) == ["2025"]
    assert res.bloc["parametres"]["annees_absentes"] == [2024, 2026]  # la panne de 2022 n'est pas une année absente


def test_immeubles_une_annee_des_comparables_en_erreur_leve_toujours_pas_de_couverture_partielle():
    r = routeur_dvf({2024: csv_dvf(), 2025: 500, 2022: csv_dvf()})
    with pytest.raises(oh.OpendataError) as exc:
        dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep, fenetre_immeubles_mois=60)
    assert not isinstance(exc.value, oh.NotFound)


def test_immeubles_toutes_les_annees_des_comparables_absentes_leve_meme_si_une_annee_ancienne_existe():
    r = routeur_dvf({2022: csv_dvf(immeuble("2022-978003", 100000, date_mutation="2022-05-10"))})
    with pytest.raises(oh.OpendataError, match="aucun fichier"):
        dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep, fenetre_immeubles_mois=60)


def test_immeubles_fixtures_synthetiques_deux_ventes_a_100_et_120_m_valeurs_calculees_a_la_main():
    """2025-900004 : 2 appartements 69 + 78 = 147 m2, 300 000 -> 2 040,82 €/m2, 150 000 €/logement, 100 m.
    2025-900005 : maison 110 + local 40 = 150 m2, 260 000 -> 1 733,33 €/m2, 260 000 €/logement, 120 m."""
    bloc = immeubles_de({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})[0]
    assert bloc["ventes"] == [
        {"id_mutation": "2025-900004", "date": "2025-01-27", "valeur_fonciere": 300000.0, "nb_logements": 2,
         "nb_locaux_activite": 0, "surface_bati_m2": 147.0, "eur_m2_bati": 2040.82, "eur_par_logement": 150000.0,
         "distance_m": 100, "adresse": "26 RUE DE TEST", "types_locaux": {"Appartement": 2},
         # champs ajoutés par une évolution
         "surface_habitation_m2": 147.0, "surface_activite_m2": 0.0, "parcelles": ["99001000AB0004"],
         "atypique": [], "dans_reference": False},
        {"id_mutation": "2025-900005", "date": "2025-05-05", "valeur_fonciere": 260000.0, "nb_logements": 1,
         "nb_locaux_activite": 1, "surface_bati_m2": 150.0, "eur_m2_bati": 1733.33, "eur_par_logement": 260000.0,
         "distance_m": 120, "adresse": "12 RUE DE TEST", "types_locaux": {"Maison": 1, TYPE_ACTIVITE: 1},
         "surface_habitation_m2": 110.0, "surface_activite_m2": 40.0, "parcelles": ["99001000AB0005"],
         "atypique": [], "dans_reference": False},
    ]
    assert bloc["compteurs"] == {"multi_locaux_vues": 2, "retenues": 2,
                                 "ecartees": {"sans_logement": 0, "prix_ou_surface": 0, "sans_coordonnees": 0}}
    assert bloc["statistiques"]["n"] == 2 and bloc["statistiques"]["mediane_eur_m2_bati"] is None


def test_immeubles_dans_la_fiche_avec_l_option_et_sans_changer_les_comparables():
    r = routeur_nominal()
    fiche, _ = fiche_nominale(r, fenetre_immeubles_mois=60)
    assert set(fiche["dvf"]["immeubles"]) == CLES_BLOC_IMMEUBLES
    assert [v["id_mutation"] for v in fiche["dvf"]["immeubles"]["ventes"]] == ["2025-900004", "2025-900005"]
    assert fiche["dvf"]["compteurs"]["retenues"] == 6 and fiche["erreurs"] == []
    json.dumps(fiche, ensure_ascii=False)  # sérialisable
    sans, _ = fiche_nominale()
    assert "immeubles" not in sans["dvf"]


def test_main_option_fenetre_immeubles_mois_par_defaut_60_valeur_donnee_et_0_pour_desactiver(script, tmp_path):
    def lancer(*option):
        r = routeur_nominal()
        sortie = tmp_path / f"fiche_{'_'.join(option) or 'defaut'}.json"
        script.main(["--adresse", ADRESSE, "--out", str(sortie), *option], client=r.client(),
                    maintenant=MAINTENANT, sleep=r.sleep)
        return json.loads(sortie.read_text(encoding="utf-8"))["dvf"]

    assert lancer()["immeubles"]["parametres"]["fenetre_mois"] == 60
    assert lancer("--fenetre-immeubles-mois", "36")["immeubles"]["parametres"]["fenetre_mois"] == 36
    assert "immeubles" not in lancer("--fenetre-immeubles-mois", "0")


def test_main_fenetre_immeubles_mois_non_entiere_argparse_code_2(script):
    r = routeur_nominal()
    with pytest.raises(SystemExit) as exc:
        script.main(["--adresse", ADRESSE, "--out", "f.json", "--fenetre-immeubles-mois", "x"], client=r.client())
    assert exc.value.code == 2 and r.appels == []


# ===========================================================================
# Fraîcheur de DVF : alerte de fenêtre effective, alertes de premier niveau, résumé
# ===========================================================================

def derniere_mutation_le(date_mutation: str, *, fichier: int | None = None, **kw: Any):
    """DVF dont la dernière (et seule) mutation date de `date_mutation` ; aujourd'hui = 2026-10-03, 24 mois."""
    annee = fichier or int(date_mutation[:4])
    csv = csv_dvf(mutation(f"{annee}-980001", [maison(100, 4)], date_mutation=date_mutation))
    return collecter_dvf({annee: csv}, **kw)[0]


def test_fraicheur_constante_18_mois():
    assert dvf.FENETRE_EFFECTIVE_MIN_MOIS == 18


def test_fraicheur_alerte_quand_la_derniere_mutation_laisse_14_mois_la_phrase_dit_tout():
    """Fixtures : début de fenêtre 2024-10-03, dernière mutation 2025-12-31 -> 14 mois, année 2026 absente."""
    res, _ = collecter_dvf({2024: fx_texte("dvf_synthetique_2024.csv"), 2025: fx_texte("dvf_synthetique_2025.csv")})
    assert res.alertes == [{"bloc": "dvf", "message": (
        "fenêtre effective de 14 mois sur 24 demandés (du 2024-10-03 à la dernière mutation 2025-12-31), "
        "sous le minimum de 18 mois ; années absentes : 2026")}]
    assert res.erreurs == []  # une alerte n'est pas une erreur


@pytest.mark.parametrize("derniere, mois, alerte", [
    ("2026-06-15", 20, False),    # récente
    ("2026-04-03", 18, False),    # frontière : exactement 18 mois, pas d'alerte
    ("2026-04-02", 17, True),     # un jour de moins : 17 mois entiers
    ("2025-12-31", 14, True),
    ("2024-10-03", 0, True),      # la dernière mutation est le jour du début de fenêtre
    ("2024-06-10", 0, True),      # antérieure au début : 0 mois, jamais négatif
])
def test_fraicheur_seuil_de_18_mois_entiers_alerte_sous_le_seuil_aucune_au_dessus(derniere, mois, alerte):
    res = derniere_mutation_le(derniere)
    if alerte:
        assert len(res.alertes) == 1 and res.alertes[0]["bloc"] == "dvf"
        assert f"fenêtre effective de {mois} mois" in res.alertes[0]["message"]
        assert f"dernière mutation {derniere}" in res.alertes[0]["message"]
    else:
        assert res.alertes == []


def test_fraicheur_les_annees_absentes_sont_dites_dans_l_alerte_et_aucune_quand_toutes_sont_la():
    res = derniere_mutation_le("2025-12-31")
    assert "années absentes : 2024, 2026" in res.alertes[0]["message"]
    csv_vide = csv_dvf()
    res, _ = collecter_dvf({2024: csv_vide, 2025: csv_dvf(mutation("2025-980002", [maison(100, 4)],
                                                                    date_mutation="2025-12-31")), 2026: csv_vide})
    assert "années absentes : aucune" in res.alertes[0]["message"]


def test_fraicheur_aucune_mutation_lue_alerte_fenetre_effective_non_disponible():
    res, _ = collecter_dvf({2025: csv_dvf()})
    assert res.bloc["parametres"]["derniere_mutation"] is None
    assert len(res.alertes) == 1
    assert "aucune mutation lue" in res.alertes[0]["message"] and "18 mois" in res.alertes[0]["message"]
    assert "24 demandés" in res.alertes[0]["message"]


def test_fraicheur_l_alerte_ne_depend_pas_de_la_fenetre_des_immeubles_et_vient_des_comparables():
    sans = derniere_mutation_le("2025-12-31").alertes
    avec = derniere_mutation_le("2025-12-31", fenetre_immeubles_mois=60).alertes
    assert sans == avec and len(sans) == 1


def test_fiche_alertes_de_premier_niveau_liste_avec_l_alerte_dvf_et_code_de_sortie_0():
    fiche, _ = fiche_nominale()
    assert fiche["erreurs"] == []
    assert [a["bloc"] for a in fiche["alertes"]] == ["dvf"]
    assert "fenêtre effective de 14 mois" in fiche["alertes"][0]["message"]
    assert fiche_mod.code_sortie(fiche) == 0  # une alerte ne change pas le code
    json.dumps(fiche, ensure_ascii=False)


def test_fiche_alertes_vide_quand_dvf_est_frais_ou_en_echec_jamais_none():
    r = routeur_nominal()
    r.route(url_dvf(2026), rep_csv(csv_dvf(mutation("2026-980003", [maison(100, 4)], date_mutation="2026-06-15"))))
    frais, _ = fiche_nominale(r)
    assert frais["alertes"] == []
    r = routeur_nominal()
    r.route(MOTIF_DVF + "*", rep_statut(404))
    en_echec, _ = fiche_nominale(r)
    assert en_echec["dvf"] is None and en_echec["alertes"] == []
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    sans_geocodage, _ = fiche_nominale(r)
    assert sans_geocodage["alertes"] == []


def _ligne(texte: str, debut: str) -> str:
    return next(ligne for ligne in texte.splitlines() if ligne.startswith(debut))


def test_resume_dit_derniere_mutation_et_annees_absentes_sur_la_ligne_dvf(tmp_path):
    fiche, _ = fiche_nominale()
    ligne = _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "DVF :")
    assert "dernière mutation 2025-12-31" in ligne
    assert "années absentes 2026" in ligne
    assert ligne.startswith("DVF : 6 comparables retenus sur 19 mutations (rayon 500 m, 24 mois)")  # début inchangé


def test_resume_annees_absentes_aucune_et_derniere_mutation_nd(tmp_path):
    r = routeur_nominal()
    r.route(url_dvf(2026), rep_csv(csv_dvf(mutation("2026-980004", [maison(100, 4)], date_mutation="2026-06-15"))))
    fiche, _ = fiche_nominale(r)
    ligne = _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "DVF :")
    assert "dernière mutation 2026-06-15" in ligne and "années absentes aucune" in ligne
    r = routeur_nominal()
    for annee in (2024, 2025):
        r.route(url_dvf(annee), rep_csv(csv_dvf()))
    fiche, _ = fiche_nominale(r)
    assert fiche["dvf"]["parametres"]["derniere_mutation"] is None
    assert "dernière mutation n/d" in _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "DVF :")


def test_resume_ligne_alertes_dit_le_message_et_aucune_quand_il_n_y_en_a_pas(tmp_path):
    fiche, _ = fiche_nominale()
    texte = fiche_mod.resume(fiche, tmp_path / "f.json")
    ligne = _ligne(texte, "Alertes :")
    assert ligne == f"Alertes : dvf : {fiche['alertes'][0]['message']}"
    assert len(texte.splitlines()) == 14  # ancien attendu : 11 (une ligne par bloc (6), cadastre, immeubles, erreurs,
    # alertes, chemin) ; une évolution y ajoute urbanisme, bâtiment, copropriété
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    sans, _ = fiche_nominale(r)
    assert _ligne(fiche_mod.resume(sans, tmp_path / "f.json"), "Alertes :") == "Alertes : aucune"
    assert "DVF : n/d" in fiche_mod.resume(sans, tmp_path / "f.json")


def test_resume_plusieurs_alertes_separees_par_un_point_virgule(tmp_path):
    fiche, _ = fiche_nominale()
    fiche["alertes"] = [{"bloc": "dvf", "message": "a"}, {"bloc": "dpe.a_l_adresse", "message": "b"}]
    assert _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "Alertes :") == \
        "Alertes : dvf : a ; dpe.a_l_adresse : b"


# ===========================================================================
# DPE à l'adresse : toutes les lignes jusqu'à 200, alerte au-delà
# ===========================================================================

def ligne_dpe(k: int) -> dict:
    """k-ième DPE de l'adresse ; `conso_5_usages_par_m2_ep` = k sert de repère d'ordre."""
    return {"etiquette_dpe": "D", "etiquette_ges": "B", "conso_5_usages_par_m2_ep": k,
            "date_etablissement_dpe": f"2025-{1 + k % 12:02d}-15", "surface_habitable_logement": 40 + k,
            "type_batiment": "appartement", "periode_construction": "1948-1974",
            "type_energie_principale_chauffage": "Gaz naturel", "adresse_ban": LABEL, "code_insee_ban": INSEE}


def serveur_dpe(total: int, *, respecte_size: bool = True) -> Callable[[httpx.Request], httpx.Response]:
    """API data-fair simulée : `total` DPE à l'adresse ; renvoie `size` lignes au plus (ou toutes si `size` est
    ignoré), dans l'ordre."""
    def repondre(requete: httpx.Request) -> httpx.Response:
        taille = int(requete.url.params["size"]) if respecte_size else total
        return httpx.Response(200, json={"total": total, "results": [ligne_dpe(k) for k in range(min(taille, total))]})
    return repondre


def dpe_a_l_adresse(total: int, **kw: Any):
    r = routeur_nominal()
    r.route(MOTIF_DPE, serveur_dpe(total, **kw), si=_est_recherche_a_l_adresse)
    return dpe.collecter(r.client(), GEO, sleep=r.sleep), r


def test_dpe_45_lignes_au_total_les_45_rendues_dans_l_ordre_en_un_seul_appel_sans_alerte():
    res, r = dpe_a_l_adresse(45)
    adresse = res.bloc["a_l_adresse"]
    assert adresse["total"] == 45
    assert [d["conso_5_usages_par_m2_ep"] for d in adresse["dpe"]] == list(range(45))
    assert res.alertes == [] and res.erreurs == []
    appels = [a for a in r.appels if a.params.get("qs", "").startswith("adresse_ban:")]
    assert len(appels) == 1 and appels[0].params["size"] == str(dpe.DPE_MAX_LIGNES)


def test_dpe_chaque_ligne_garde_la_date_et_la_surface_du_logement():
    res, _ = dpe_a_l_adresse(45)
    for ligne in res.bloc["a_l_adresse"]["dpe"]:
        assert ligne["date_etablissement_dpe"] and ligne["surface_habitable_logement"] is not None
        assert set(ligne) == set(CHAMPS_DPE_ATTENDUS) | {"avant_reforme_coef_elec"}


def test_dpe_250_lignes_au_total_200_rendues_le_vrai_total_et_une_alerte_qui_le_dit():
    res, _ = dpe_a_l_adresse(250)
    adresse = res.bloc["a_l_adresse"]
    assert adresse["total"] == 250 and len(adresse["dpe"]) == 200
    assert [d["conso_5_usages_par_m2_ep"] for d in adresse["dpe"]] == list(range(200))
    assert res.alertes == [{"bloc": "dpe.a_l_adresse", "message":
                            "250 DPE annoncés à l'adresse, 200 lus (plafond 200) : liste tronquée"}]
    assert res.erreurs == []  # une liste tronquée signalée n'est pas une erreur


@pytest.mark.parametrize("total, lues, alerte", [(199, 199, False), (200, 200, False), (201, 200, True)])
def test_dpe_frontiere_du_plafond_200_accepte_201_alerte(total, lues, alerte):
    res, _ = dpe_a_l_adresse(total)
    assert len(res.bloc["a_l_adresse"]["dpe"]) == lues
    assert bool(res.alertes) is alerte


def test_dpe_l_api_ignore_size_et_renvoie_250_lignes_le_plafond_de_200_tient_et_alerte():
    res, _ = dpe_a_l_adresse(250, respecte_size=False)
    assert len(res.bloc["a_l_adresse"]["dpe"]) == 200
    assert len(res.alertes) == 1 and "tronquée" in res.alertes[0]["message"]


def test_dpe_total_superieur_aux_lignes_rendues_sous_le_plafond_alerte_liste_incomplete():
    """L'API annonce 35 DPE mais n'en rend que 20 : ce n'est pas le plafond, c'est un écart à signaler."""
    lignes = [dict(fx("dpe_adresse.json")["results"][2]) for _ in range(20)]
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json({"total": 35, "results": lignes}), si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"]["total"] == 35 and len(res.bloc["a_l_adresse"]["dpe"]) == 20
    assert res.alertes == [{"bloc": "dpe.a_l_adresse", "message":
                            "35 DPE annoncés à l'adresse, 20 reçus : liste incomplète"}]


def test_dpe_pas_d_alerte_sur_la_fixture_nominale_ni_quand_la_recherche_a_l_adresse_echoue():
    res = dpe.collecter(routeur_nominal().client(), GEO)
    assert res.alertes == []
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_statut(500), si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None and res.alertes == []


def test_fiche_dpe_tronque_alerte_de_premier_niveau_sans_erreur_et_code_0():
    r = routeur_nominal()
    r.route(MOTIF_DPE, serveur_dpe(250), si=_est_recherche_a_l_adresse)
    fiche, _ = fiche_nominale(r)
    assert fiche["erreurs"] == []
    assert [a["bloc"] for a in fiche["alertes"]] == ["dvf", "dpe.a_l_adresse"]  # ordre des blocs de la fiche
    assert fiche_mod.code_sortie(fiche) == 0
    assert "DPE : 4614 dans la commune ; 250 à l'adresse" in fiche_mod.resume(fiche, "f.json")


# ===========================================================================
# : gardes révélées par la revue et le test de mutation
# ===========================================================================

@pytest.mark.parametrize("fenetre", [12, 18])
def test_fraicheur_fenetre_demandee_courte_l_alerte_part_toujours_et_dit_la_fenetre_demandee(fenetre):
    """Une fenêtre demandée <= 18 mois ne peut pas atteindre 18 mois effectifs : l'alerte part même si la dernière
    mutation date de 5 jours (règle de référence, littérale). Le message dit alors la fenêtre DEMANDÉE, pour qu'on ne
    lise pas un retard de DVF là où il n'y a qu'une fenêtre courte."""
    res = derniere_mutation_le("2026-09-28", fenetre_mois=fenetre)
    assert len(res.alertes) == 1
    message = res.alertes[0]["message"]
    assert f"sur {fenetre} demandés" in message and "sous le minimum de 18 mois" in message
    assert "dernière mutation 2026-09-28" in message


def test_fraicheur_fenetre_de_24_mois_et_mutation_recente_aucune_alerte_la_meme_derniere_mutation():
    assert derniere_mutation_le("2026-09-28", fenetre_mois=24).alertes == []  # pendant du test ci-dessus


@pytest.mark.parametrize("valeur", ["0", "-5"], ids=["valeur_zero", "valeur_negative"])
def test_immeubles_prix_nul_ou_negatif_est_ecarte_prix_ou_surface(valeur):
    csv = csv_dvf(immeuble("2025-979001", valeur, nord_m=10), immeuble("2025-979002", 200000, nord_m=20))
    bloc = immeubles_de({2025: csv})[0]
    assert bloc["compteurs"] == {"multi_locaux_vues": 2, "retenues": 1,
                                 "ecartees": {"sans_logement": 0, "prix_ou_surface": 1, "sans_coordonnees": 0}}
    assert [v["id_mutation"] for v in bloc["ventes"]] == ["2025-979002"]


def test_immeubles_surface_decimale_arrondie_a_2_decimales_sans_bruit_flottant():
    csv = csv_dvf(immeuble("2025-979010", 150000, logements=(33.3, 44.4), nord_m=10))
    vente = immeubles_de({2025: csv})[0]["ventes"][0]
    assert vente["surface_bati_m2"] == 77.7  # 33.3 + 44.4 vaut 77.69999999999999 en flottant
    assert vente["eur_m2_bati"] == round(150000 / 77.7, 2)


def test_immeubles_annees_absentes_limitees_a_la_fenetre_des_immeubles_quand_elle_est_plus_courte():
    bloc, res, _ = immeubles_de({2025: csv_dvf(immeuble("2025-979003", 100000))}, fenetre_immeubles_mois=12)
    assert bloc["parametres"]["annees"] == [2025, 2026]
    assert bloc["parametres"]["annees_absentes"] == [2026]  # 2024 manque aux comparables, pas à CE bloc
    assert res.bloc["parametres"]["annees_absentes"] == [2024, 2026]


def test_immeubles_deux_annees_anciennes_en_erreur_l_erreur_nommee_est_la_premiere():
    r = routeur_dvf({2025: csv_dvf(immeuble("2025-979004", 100000)), 2021: 500, 2022: 502})
    res = dvf.collecter(r.client(), GEO, aujourdhui=AUJOURDHUI, sleep=r.sleep, fenetre_immeubles_mois=60)
    assert res.bloc["immeubles"] is None and [e["bloc"] for e in res.erreurs] == ["dvf.immeubles"]
    assert url_dvf(2021) in res.erreurs[0]["message"] and url_dvf(2022) not in res.erreurs[0]["message"]


def test_immeubles_premier_local_sans_coordonnees_le_local_suivant_localise_la_vente():
    lignes = immeuble("2025-979005", 200000, nord_m=30)
    lignes[0]["longitude"] = lignes[0]["latitude"] = ""  # parcelle non géolocalisée, la suivante l'est
    bloc = immeubles_de({2025: csv_dvf(lignes)})[0]
    assert bloc["compteurs"]["ecartees"]["sans_coordonnees"] == 0 and bloc["compteurs"]["retenues"] == 1
    assert [v["distance_m"] for v in bloc["ventes"]] == [30]


def test_immeubles_distance_mesuree_au_premier_local_geolocalise():
    lignes = immeuble("2025-979006", 200000, nord_m=30)
    lignes[1]["latitude"] = f"{LAT + 90 / M_PAR_DEGRE:.6f}"  # le 2e local est 60 m plus loin
    bloc = immeubles_de({2025: csv_dvf(lignes)})[0]
    assert [v["distance_m"] for v in bloc["ventes"]] == [30]


def test_immeubles_deux_locaux_d_activite_pour_un_logement_les_deux_sont_comptes():
    bloc = immeubles_de({2025: csv_dvf(immeuble("2025-979007", 200000, logements=(60,), activite=(40, 30)))})[0]
    vente = bloc["ventes"][0]
    assert (vente["nb_logements"], vente["nb_locaux_activite"]) == (1, 2)
    assert vente["types_locaux"] == {"Appartement": 1, TYPE_ACTIVITE: 2}


def test_immeubles_l_adresse_est_celle_du_premier_local():
    lignes = immeuble("2025-979008", 200000, nord_m=30, numero="12")
    lignes[1]["adresse_numero"] = "14"
    assert immeubles_de({2025: csv_dvf(lignes)})[0]["ventes"][0]["adresse"] == "12 RUE DE TEST"


def test_dpe_total_egal_au_plafond_avec_199_lignes_rendues_est_incomplet_pas_tronque():
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json({"total": 200, "results": [ligne_dpe(k) for k in range(199)]}),
            si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.alertes == [{"bloc": "dpe.a_l_adresse", "message":
                            "200 DPE annoncés à l'adresse, 199 reçus : liste incomplète"}]


def test_dpe_une_ligne_etrangere_au_dela_du_plafond_leve_quand_meme_le_filtre_ignore():
    """La garde contrôle TOUTES les lignes rendues, pas seulement les 200 gardées (docstring du module)."""
    lignes = [ligne_dpe(k) for k in range(250)]
    lignes[230] = {**lignes[230], "adresse_ban": "2 Rue Autre 99100 Exempleville"}
    r = routeur_nominal()
    r.route(MOTIF_DPE, rep_json({"total": 250, "results": lignes}), si=_est_recherche_a_l_adresse)
    res = dpe.collecter(r.client(), GEO, sleep=r.sleep)
    assert res.bloc["a_l_adresse"] is None and res.alertes == []
    assert [e["bloc"] for e in res.erreurs] == ["dpe.a_l_adresse"]
    assert "filtre adresse_ban ignoré" in res.erreurs[0]["message"]


def test_get_429_retry_after_avec_espaces_est_lu_comme_entier():
    r = Routeur().route(MOTIF_TEST, [rep_429(" 7 "), rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [7]


@pytest.mark.parametrize("valeur", ["²", "７"], ids=["exposant", "chiffre_pleine_chasse"])
def test_get_429_retry_after_chiffres_non_ascii_retombe_sur_le_bareme(valeur):
    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers=[(b"retry-after", valeur.encode("utf-8"))], content=b"trop")
    r = Routeur().route(MOTIF_TEST, [repondre, rep_json({"v": 1})])
    assert oh.get_json(r.client(), URL_TEST, sleep=r.sleep) == {"v": 1}
    assert r.attentes == [1]  # ni plantage (« ² »), ni 7 s (« ７ ») : illisible = barème


def test_main_geocodage_en_echec_code_2_n_ecrit_rien_sur_stderr(script, tmp_path, capsys):
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    code, _ = _lancer(script, tmp_path, r)
    sortie = capsys.readouterr()
    assert code == 2 and sortie.err == "" and sortie.out.strip()  # stderr = code 3 seulement (fiche partielle)


@pytest.mark.parametrize("valeur", ["-1", "-60"])
def test_main_fenetre_immeubles_mois_negative_argparse_code_2_aucun_appel(script, valeur):
    r = routeur_nominal()
    with pytest.raises(SystemExit) as exc:
        script.main(["--adresse", ADRESSE, "--out", "f.json", "--fenetre-immeubles-mois", valeur], client=r.client())
    assert exc.value.code == 2 and r.appels == []


# ===========================================================================
# - étape 1 : médiane de RÉFÉRENCE des immeubles (`dvf.immeubles.reference`)
# ===========================================================================

CLES_REFERENCE = {"criteres", "n", "n_min", "mediane_eur_m2_bati", "mediane_eur_par_logement",
                  "raison_mediane_absente", "ecartees"}
ECARTEES_NULLES = {"moins_de_3_logements": 0, "atypique": 0, "revente_meme_parcelle": 0}


def parcelle(k: int) -> str:
    """Identifiant de parcelle de test, au format réel (commune + préfixe + section + numéro)."""
    return f"{INSEE}000AB{k:04d}"


def immeuble_p(id_mutation: str, valeur: Any, parcelle_vente: str, logements: tuple = (40, 40, 40),
               activite: tuple = (), **kw: Any):
    """Comme `immeuble`, mais sur la parcelle choisie : le regroupement par parcelle se joue là-dessus."""
    locaux = [appart(s, 3, lot=str(rang), parcelle=parcelle_vente) for rang, s in enumerate(logements, start=1)]
    locaux += [_local(TYPE_ACTIVITE, s, 0, culture="sols", parcelle=parcelle_vente) for s in activite]
    return mutation(id_mutation, locaux, valeur=str(valeur), **kw)


def reference_de(*mutations: list[dict[str, str]], **kw: Any):
    bloc = immeubles_de({2025: csv_dvf(*mutations)}, **kw)[0]
    return bloc["reference"], bloc


def vente_de(bloc: dict, id_mutation: str) -> dict:
    return next(v for v in bloc["ventes"] if v["id_mutation"] == id_mutation)


def test_reference_constantes_du_contrat():
    assert dvf.NB_LOGEMENTS_REFERENCE_MIN == 3
    assert dvf.NB_LOGEMENTS_BLOC == 20
    assert dvf.N_MIN_MEDIANE_IMMEUBLES == 3


def test_reference_cles_criteres_et_seuils_dits_dans_la_fiche():
    ref, bloc = reference_de(immeuble_p("2025-981001", 240000, parcelle(1)))
    assert set(ref) == CLES_REFERENCE
    assert ref["n_min"] == 3
    assert ref["criteres"]["nb_logements_min"] == 3
    assert ref["criteres"]["sans_atypique"] is True
    assert ref["criteres"]["une_vente_par_parcelle"] == "la plus récente"
    assert set(ref["criteres"]["atypique_si"]) == {"bloc", "activite_dominante"}
    assert "20" in ref["criteres"]["atypique_si"]["bloc"]  # le seuil de « résidence vendue en bloc » est dit
    assert set(ref["ecartees"]) == {"moins_de_3_logements", "atypique", "revente_meme_parcelle"}
    assert list(bloc)[:3] == ["parametres", "statistiques", "reference"]
    json.dumps(bloc, ensure_ascii=False)  # sérialisable


@pytest.mark.parametrize("logements, retenue", [
    pytest.param((50,), False, id="1_logement_plus_commerce"),
    pytest.param((50, 50), False, id="2_logements"),
    pytest.param((40, 40, 40), True, id="3_logements"),
    pytest.param((25, 25, 25, 25), True, id="4_logements"),
])
def test_reference_moins_de_3_logements_ecarte_trois_et_plus_retenu(logements, retenue):
    activite = (40,) if len(logements) == 1 else ()
    ref, bloc = reference_de(immeuble_p("2025-981101", 300000, parcelle(1), logements=logements, activite=activite))
    assert bloc["ventes"][0]["dans_reference"] is retenue
    assert ref["n"] == int(retenue)
    assert ref["ecartees"] == {**ECARTEES_NULLES, "moins_de_3_logements": int(not retenue)}


@pytest.mark.parametrize("nombre, motifs", [
    pytest.param(19, [], id="19_logements"),
    pytest.param(20, ["bloc"], id="20_logements"),
    pytest.param(21, ["bloc"], id="21_logements"),
])
def test_reference_motif_bloc_des_20_logements(nombre, motifs):
    ref, bloc = reference_de(immeuble_p("2025-981201", 1_000_000, parcelle(1), logements=(10,) * nombre))
    vente = bloc["ventes"][0]
    assert vente["nb_logements"] == nombre
    assert vente["atypique"] == motifs
    assert vente["dans_reference"] is (not motifs)
    assert ref["ecartees"] == {**ECARTEES_NULLES, "atypique": int(bool(motifs))}
    assert ref["n"] == int(not motifs)


@pytest.mark.parametrize("activite, motifs", [
    pytest.param(59, [], id="activite_inferieure"),
    pytest.param(60, [], id="egalite_n_est_pas_dominante"),
    pytest.param(61, ["activite_dominante"], id="activite_superieure"),
])
def test_reference_motif_activite_dominante_strictement_superieure_a_l_habitation(activite, motifs):
    ref, bloc = reference_de(
        immeuble_p("2025-981301", 400000, parcelle(1), logements=(20, 20, 20), activite=(activite,)))
    vente = bloc["ventes"][0]
    assert (vente["surface_habitation_m2"], vente["surface_activite_m2"]) == (60.0, float(activite))
    assert vente["atypique"] == motifs and vente["dans_reference"] is (not motifs)
    assert ref["ecartees"] == {**ECARTEES_NULLES, "atypique": int(bool(motifs))}


def test_reference_un_site_a_deux_motifs_les_porte_tous_dans_l_ordre_du_contrat():
    ref, bloc = reference_de(
        immeuble_p("2025-981401", 5_000_000, parcelle(1), logements=(5,) * 20, activite=(150,)))
    assert bloc["ventes"][0]["atypique"] == ["bloc", "activite_dominante"]
    assert ref["ecartees"]["atypique"] == 1  # une vente, comptée une fois


def test_reference_une_vente_a_un_logement_et_beaucoup_d_activite_compte_dans_moins_de_3_logements_pas_atypique():
    """Ordre des exclusions : « moins de 3 logements » AVANT « atypique ». La vente porte le motif d'atypie
    `activite_dominante` (200 m2 d'activité pour 60 m2 d'habitation) mais n'est comptée qu'au premier motif rencontré."""
    ref, bloc = reference_de(
        immeuble_p("2025-981451", 400000, parcelle(1), logements=(60,), activite=(200,)))
    assert bloc["ventes"][0]["atypique"] == ["activite_dominante"] and bloc["ventes"][0]["dans_reference"] is False
    assert ref["ecartees"] == {**ECARTEES_NULLES, "moins_de_3_logements": 1}


def test_reference_activite_dominante_se_juge_sur_les_surfaces_publiees_arrondies_a_2_decimales():
    """33,3 + 44,4 + 10 vaut 87.69999999999999 en flottant : 87,7 d'habitation contre 87,7 d'activité (égalité des
    valeurs publiées) n'est PAS une activité dominante ; 87,71 l'est."""
    ref, bloc = reference_de(
        immeuble_p("2025-981461", 400000, parcelle(1), logements=(33.3, 44.4, 10), activite=(87.7,), nord_m=10),
        immeuble_p("2025-981462", 400000, parcelle(2), logements=(33.3, 44.4, 10), activite=(87.71,), nord_m=20))
    egal, domine = vente_de(bloc, "2025-981461"), vente_de(bloc, "2025-981462")
    assert (egal["surface_habitation_m2"], egal["surface_activite_m2"]) == (87.7, 87.7)
    assert egal["atypique"] == [] and egal["dans_reference"] is True
    assert domine["surface_activite_m2"] == 87.71 and domine["atypique"] == ["activite_dominante"]
    assert ref["n"] == 1 and ref["ecartees"] == {**ECARTEES_NULLES, "atypique": 1}


def test_reference_revente_sur_la_meme_parcelle_garde_la_plus_recente_et_compte_l_autre():
    mutations = [
        immeuble_p("2025-981501", 240000, parcelle(1), date_mutation="2023-05-10", nord_m=10),
        immeuble_p("2025-981502", 360000, parcelle(1), date_mutation="2025-03-04", nord_m=20),
    ]
    for ordre in (mutations, mutations[::-1]):  # le résultat ne dépend pas de l'ordre du CSV
        ref, bloc = reference_de(*ordre)
        assert ref["n"] == 1
        assert ref["ecartees"] == {**ECARTEES_NULLES, "revente_meme_parcelle": 1}
        assert vente_de(bloc, "2025-981502")["dans_reference"] is True
        assert vente_de(bloc, "2025-981501")["dans_reference"] is False


def test_reference_deux_parcelles_differentes_deux_ventes_gardees():
    ref, bloc = reference_de(
        immeuble_p("2025-981511", 240000, parcelle(1), nord_m=10),
        immeuble_p("2025-981512", 360000, parcelle(2), nord_m=20),
    )
    assert ref["n"] == 2 and ref["ecartees"] == ECARTEES_NULLES
    assert all(v["dans_reference"] for v in bloc["ventes"])


def test_reference_regroupement_de_proche_en_proche_un_seul_groupe():
    """A et B partagent la parcelle 1, B et C la parcelle 2, A et C rien : un seul groupe, C (la plus récente) reste."""
    def vente_a_deux_parcelles(id_mutation, date_mutation, nord_m):
        locaux = [appart(40, 3, lot="1", parcelle=parcelle(1)), appart(40, 3, lot="2", parcelle=parcelle(1)),
                  appart(40, 3, lot="3", parcelle=parcelle(2))]
        return mutation(id_mutation, locaux, valeur="300000", date_mutation=date_mutation, nord_m=nord_m)

    mutations = [
        immeuble_p("2025-981601", 300000, parcelle(1), date_mutation="2022-02-01", nord_m=10),       # A : parcelle 1
        vente_a_deux_parcelles("2025-981602", "2023-02-01", 20),                                      # B : 1 et 2
        immeuble_p("2025-981603", 300000, parcelle(2), date_mutation="2025-02-01", nord_m=30),       # C : parcelle 2
    ]
    for ordre in (mutations, mutations[::-1]):
        ref, bloc = reference_de(*ordre)
        assert ref["n"] == 1
        assert ref["ecartees"] == {**ECARTEES_NULLES, "revente_meme_parcelle": 2}
        assert [v["id_mutation"] for v in bloc["ventes"] if v["dans_reference"]] == ["2025-981603"]


@pytest.mark.parametrize("anciennete, garde", [
    pytest.param((("2025-981701", "2025-03-04"), ("2025-981702", "2025-03-04")), "2025-981702",
                 id="meme_date_le_plus_grand_id"),
    pytest.param((("2025-9", "2025-03-04"), ("2025-10", "2025-03-04")), "2025-10",
                 id="meme_date_ordre_numerique_pas_alphabetique"),
    pytest.param((("2025-981712", "2023-01-01"), ("2025-981711", "2025-01-01")), "2025-981711",
                 id="la_date_prime_sur_l_id"),
])
def test_reference_egalite_de_date_departagee_par_id_mutation_la_date_prime(anciennete, garde):
    mutations = [immeuble_p(i, 300000, parcelle(1), date_mutation=d, nord_m=10 + k)
                 for k, (i, d) in enumerate(anciennete)]
    for ordre in (mutations, mutations[::-1]):
        ref, bloc = reference_de(*ordre)
        assert [v["id_mutation"] for v in bloc["ventes"] if v["dans_reference"]] == [garde]
        assert ref["ecartees"]["revente_meme_parcelle"] == 1


def test_reference_une_petite_vente_sur_la_meme_parcelle_ne_fait_pas_tomber_la_grande():
    """Ordre des exclusions : moins de 3 logements AVANT le regroupement par parcelle."""
    ref, bloc = reference_de(
        immeuble_p("2025-981801", 300000, parcelle(1), logements=(40, 40, 40), date_mutation="2022-06-01", nord_m=10),
        immeuble_p("2025-981802", 150000, parcelle(1), logements=(50, 50), date_mutation="2025-06-01", nord_m=20),
    )
    assert ref["n"] == 1
    assert ref["ecartees"] == {**ECARTEES_NULLES, "moins_de_3_logements": 1}
    assert vente_de(bloc, "2025-981801")["dans_reference"] is True


def test_reference_une_vente_atypique_sur_la_meme_parcelle_ne_fait_pas_tomber_la_vente_ordinaire():
    """Ordre des exclusions : atypique AVANT le regroupement par parcelle."""
    ref, bloc = reference_de(
        immeuble_p("2025-981811", 300000, parcelle(1), logements=(40, 40, 40), date_mutation="2022-06-01", nord_m=10),
        immeuble_p("2025-981812", 900000, parcelle(1), logements=(10,) * 20, date_mutation="2025-06-01", nord_m=20),
    )
    assert ref["n"] == 1
    assert ref["ecartees"] == {**ECARTEES_NULLES, "atypique": 1}
    assert vente_de(bloc, "2025-981811")["dans_reference"] is True


def test_reference_parcelle_sans_identifiant_jamais_regroupee():
    """Deux ventes dont `id_parcelle` est vide n'ont aucune parcelle en commun : on ne les prend pas pour une revente."""
    mutations = []
    for k, id_mutation in enumerate(("2025-981901", "2025-981902")):
        lignes = immeuble_p(id_mutation, 300000, parcelle(1), date_mutation=f"202{3 + k}-05-01", nord_m=10 + k)
        for ligne in lignes:
            ligne["id_parcelle"] = ""
        mutations.append(lignes)
    ref, bloc = reference_de(*mutations)
    assert ref["n"] == 2 and ref["ecartees"] == ECARTEES_NULLES
    assert [v["parcelles"] for v in bloc["ventes"]] == [[], []]


def test_reference_n_inferieur_a_3_medianes_null_avec_la_raison_et_les_statistiques_brutes_restent():
    mutations = [
        immeuble_p("2025-982001", 240000, parcelle(1), nord_m=10),                          # référence
        immeuble_p("2025-982002", 270000, parcelle(2), nord_m=20),                          # référence
        immeuble_p("2025-982003", 100000, parcelle(3), logements=(50, 50), nord_m=30),      # 2 logements
        immeuble_p("2025-982004", 110000, parcelle(4), logements=(50, 50), nord_m=40),      # 2 logements
    ]
    ref, bloc = reference_de(*mutations)
    assert ref["n"] == 2
    assert ref["mediane_eur_m2_bati"] is None and ref["mediane_eur_par_logement"] is None
    assert "n = 2 < 3" in ref["raison_mediane_absente"]
    assert bloc["statistiques"]["n"] == 4 and bloc["statistiques"]["mediane_eur_m2_bati"] is not None


def test_reference_aucune_vente_n_0_medianes_null_avec_la_raison_pas_de_faux_zero():
    ref, _ = reference_de(immeuble_p("2025-982011", 100000, parcelle(1), logements=(50, 50)))
    assert ref["n"] == 0 and ref["mediane_eur_m2_bati"] is None and ref["mediane_eur_par_logement"] is None
    assert "n = 0 < 3" in ref["raison_mediane_absente"]
    ref_vide, _ = reference_de(mutation("2025-982012", [maison(100, 4)]))  # aucune vente d'immeuble du tout
    assert ref_vide["n"] == 0 and ref_vide["ecartees"] == ECARTEES_NULLES


def test_reference_n_egal_3_medianes_calculees_a_la_main_sans_raison_et_differentes_de_la_brute():
    """R1 : 3 logements, 120 m2, 240 000 -> 2 000 €/m2 et 80 000 €/logement. R2 : 3 logements, 90 m2, 270 000 ->
    3 000 et 90 000. R3 : 4 logements, 100 m2, 150 000 -> 1 500 et 37 500. Médianes de référence : 2 000 et 80 000.
    R4 (2 logements, 100 m2, 50 000 : 500 et 25 000) entre dans la médiane brute et pas dans la référence : la brute
    vaut (1 500 + 2 000) / 2 = 1 750 et (37 500 + 80 000) / 2 = 58 750."""
    ref, bloc = reference_de(
        immeuble_p("2025-982101", 240000, parcelle(1), logements=(40, 40, 40), nord_m=10),
        immeuble_p("2025-982102", 270000, parcelle(2), logements=(30, 30, 30), nord_m=20),
        immeuble_p("2025-982103", 150000, parcelle(3), logements=(25, 25, 25, 25), nord_m=30),
        immeuble_p("2025-982104", 50000, parcelle(4), logements=(50, 50), nord_m=40),
    )
    assert ref["n"] == 3 and ref["raison_mediane_absente"] is None
    assert ref["mediane_eur_m2_bati"] == 2000.0 and ref["mediane_eur_par_logement"] == 80000.0
    assert bloc["statistiques"]["mediane_eur_m2_bati"] == 1750.0
    assert bloc["statistiques"]["mediane_eur_par_logement"] == 58750.0


MELANGE = (  # 7 ventes : 2 petites, 1 atypique, 1 revente, 3 ordinaires (voir le test qui l'utilise)
    lambda: immeuble_p("2025-982201", 150000, parcelle(1), logements=(50, 50), nord_m=10),                    # 2 log.
    lambda: immeuble_p("2025-982202", 240000, parcelle(2), date_mutation="2023-05-10", nord_m=20),            # revendue
    lambda: immeuble_p("2025-982203", 270000, parcelle(2), logements=(30, 30, 30), date_mutation="2025-03-04",
                       nord_m=30),                                                                              # ordinaire
    lambda: immeuble_p("2025-982204", 400000, parcelle(3), logements=(5,) * 20, nord_m=40),                   # bloc
    lambda: immeuble_p("2025-982205", 120000, parcelle(4), logements=(25, 25, 25, 25), nord_m=50),           # ordinaire
    lambda: immeuble_p("2025-982206", 100000, parcelle(5), logements=(60,), activite=(40,), nord_m=60),       # 1 log.
    lambda: immeuble_p("2025-982207", 144000, parcelle(6), nord_m=70),                                        # ordinaire
)


def test_reference_statistiques_brutes_inchangees_elles_gardent_toutes_les_ventes():
    """Les médianes de `statistiques` partent des 7 ventes, petites, atypique et revente comprises : €/m2 triés
    1 000 / 1 200 / 1 200 / 1 500 / 2 000 / 3 000 / 4 000 -> 1 500 ; €/logement 20 000 / 30 000 / 48 000 / 75 000 /
    80 000 / 90 000 / 100 000 -> 75 000. Ce test doit passer à l'identique sur le code d'avant ce changement."""
    bloc = immeubles_de({2025: csv_dvf(*(f() for f in MELANGE))})[0]
    assert bloc["statistiques"] == {
        "n": 7, "n_min": 3, "mediane_eur_m2_bati": 1500.0, "mediane_eur_par_logement": 75000.0,
        "raison_mediane_absente": None,
    }
    assert bloc["compteurs"]["retenues"] == 7


def test_reference_melange_exclusions_dans_l_ordre_et_medianes_a_la_main():
    """2 petites (R1, R6), 1 atypique (R4), 1 revente (R2 remplacée par R3), 3 retenues : R3 (3 000 €/m2, 90 000),
    R5 (1 200, 30 000), R7 (144 000 / 120 m2 = 1 200, 48 000). Médianes 1 200 et 48 000."""
    ref, bloc = reference_de(*(f() for f in MELANGE))
    assert ref["n"] == 3
    assert ref["ecartees"] == {"moins_de_3_logements": 2, "atypique": 1, "revente_meme_parcelle": 1}
    assert ref["mediane_eur_m2_bati"] == 1200.0 and ref["mediane_eur_par_logement"] == 48000.0
    assert ref["n"] + sum(ref["ecartees"].values()) == bloc["statistiques"]["n"] == 7  # aucune vente sans trace
    retenues = sorted(v["id_mutation"] for v in bloc["ventes"] if v["dans_reference"])
    assert retenues == ["2025-982203", "2025-982205", "2025-982207"]
    ordre_inverse = reference_de(*(f() for f in reversed(MELANGE)))[0]
    assert ordre_inverse == ref  # indépendant de l'ordre du CSV


def test_reference_calculee_sur_toutes_les_ventes_retenues_pas_sur_les_20_listees():
    """22 ventes de 3 logements à 1 000 ... 3 100 €/m2 (120 m2) : médiane des 22 = 2 050, des 20 premières = 1 950."""
    csv = csv_dvf(*(immeuble_p(f"2025-9830{k:02d}", 120000 + 12000 * k, parcelle(k), nord_m=10 * (k + 1))
                    for k in range(22)))
    bloc = immeubles_de({2025: csv})[0]
    assert len(bloc["ventes"]) == 20
    assert bloc["reference"]["n"] == 22 and bloc["reference"]["mediane_eur_m2_bati"] == 2050.0


def test_reference_la_revente_est_detectee_meme_si_la_vente_la_plus_recente_n_est_pas_dans_les_20_listees():
    """Le regroupement porte sur toutes les ventes retenues. La vente ancienne est proche (listée), la récente est
    loin (hors des 20 plus proches) : elle reste dans la référence, l'ancienne en est écartée."""
    proches = [immeuble_p(f"2025-9840{k:02d}", 300000, parcelle(10 + k), nord_m=10 * (k + 1)) for k in range(20)]
    ancienne = immeuble_p("2025-984100", 300000, parcelle(1), date_mutation="2022-01-01", nord_m=5)
    recente = immeuble_p("2025-984101", 300000, parcelle(1), date_mutation="2025-06-01", nord_m=400)
    ref, bloc = reference_de(*proches, ancienne, recente)
    assert vente_de(bloc, "2025-984100")["dans_reference"] is False
    assert all(v["id_mutation"] != "2025-984101" for v in bloc["ventes"])  # hors des 20 listées
    assert ref["n"] == 21 and ref["ecartees"]["revente_meme_parcelle"] == 1


def test_reference_chaque_vente_porte_parcelles_surfaces_par_usage_atypique_et_drapeau():
    """2 appartements (60 + 70 m2) sur les parcelles 2 et 1, un commerce (40 m2) sur la 1, plus une dépendance et un
    terrain : seuls les locaux bâtis donnent des parcelles (uniques, triées)."""
    locaux = [appart(60, 3, lot="1", parcelle=parcelle(2)), appart(70, 3, lot="2", parcelle=parcelle(1)),
              _local(TYPE_ACTIVITE, 40, 0, culture="sols", parcelle=parcelle(1)),
              _local("Dépendance", "", 0, parcelle=parcelle(7)), terrain(parcelle(8))]
    bloc = immeubles_de({2025: csv_dvf(mutation("2025-985001", locaux, valeur="300000"))})[0]
    vente = bloc["ventes"][0]
    assert vente["parcelles"] == [parcelle(1), parcelle(2)]
    assert (vente["surface_bati_m2"], vente["surface_habitation_m2"], vente["surface_activite_m2"]) == (170.0, 130.0, 40.0)
    assert vente["atypique"] == [] and vente["dans_reference"] is False  # 2 logements


def test_reference_surfaces_par_usage_somme_surface_fois_nombre_et_arrondies_a_2_decimales():
    quatre = mutation("2025-985011", [appart(25, 1, lot="")] * 4, valeur="200000")
    decimales = immeuble_p("2025-985012", 150000, parcelle(3), logements=(33.3, 44.4), activite=(10.1, 20.2))
    bloc = immeubles_de({2025: csv_dvf(quatre, decimales)})[0]
    assert (vente_de(bloc, "2025-985011")["surface_habitation_m2"], vente_de(bloc, "2025-985011")["surface_activite_m2"]) \
        == (100.0, 0.0)
    assert (vente_de(bloc, "2025-985012")["surface_habitation_m2"], vente_de(bloc, "2025-985012")["surface_activite_m2"]) \
        == (77.7, 30.3)  # 33.3 + 44.4 et 10.1 + 20.2 valent 77.69999999999999 et 30.299999999999997 en flottant


def test_reference_comparables_et_compteurs_historiques_ne_changent_pas():
    sans = collecter_dvf({2025: csv_dvf(*(f() for f in MELANGE))})[0].bloc
    avec = collecter_dvf({2025: csv_dvf(*(f() for f in MELANGE))}, fenetre_immeubles_mois=60)[0].bloc
    for cle in ("parametres", "par_type", "atypiques", "comparables", "compteurs"):
        assert avec[cle] == sans[cle], cle


# ===========================================================================
# - étape 2 : commune du géocodage contrôlée, identifiant BAN, rang du candidat
# ===========================================================================

def geocoder_liste(adresse: str, *features: dict):
    r = Routeur().route(MOTIF_GEOCODAGE, rep_json(reponse_ban(*features)))
    return geocodage.geocoder(r.client(), adresse, sleep=r.sleep), r


def test_geocodage_constantes_du_contrat_identite():
    assert geocodage.NB_CANDIDATS == 5
    assert geocodage.URL_REVERSE == "https://data.geopf.fr/geocodage/reverse"


def test_geocodage_code_postal_concordant_premier_candidat_rang_1_et_identifiant_ban():
    geo, r = geocoder_liste("1 rue de test 99100 Exempleville", feature_ban(LABEL, "99001_0001_00001"))
    assert geo["identifiant_ban"] == "99001_0001_00001"
    assert geo["controle_commune"] == "code postal 99100 concordant"
    assert geo["rang_candidat"] == 1
    assert r.appels[0].params["limit"] == "5"


def test_geocodage_retient_le_premier_candidat_du_code_postal_demande_pas_le_premier_de_la_liste():
    geo, _ = geocoder_liste(
        "14 allée des cerisiers 99200 Bourg-Exemple",
        feature_ban("14 Allée des Cerisiers 99100 Exempleville", "99001_0003_00014", postcode="99100"),
        feature_ban("14 Allée des Cerisiers 99200 Bourg-Exemple", "99002_0004_00014", postcode="99200",
                    citycode="99002", city="Bourg-Exemple", lon=1.7006, lat=47.3004),
        feature_ban("14 Rue de l'Exemple 99200 Bourg-Exemple", "99002_0005_00014", postcode="99200",
                    citycode="99002", city="Bourg-Exemple"),
    )
    assert geo["label"] == "14 Allée des Cerisiers 99200 Bourg-Exemple"
    assert geo["rang_candidat"] == 2 and geo["identifiant_ban"] == "99002_0004_00014"
    assert geo["controle_commune"] == "code postal 99200 concordant"
    assert (geo["citycode"], geo["lon"], geo["lat"]) == ("99002", 1.7006, 47.3004)  # tout vient du candidat retenu


def test_geocodage_aucun_candidat_dans_le_code_postal_leve_opendata_error():
    with pytest.raises(oh.OpendataError, match="aucun candidat dans le code postal 99999") as exc:
        geocoder_liste("1 rue de test 99999 Exempleville", feature_ban(LABEL, "99001_0001_00001"),
                       feature_ban(LABEL, "99001_0001_00002"))
    assert "data.geopf.fr/geocodage/search" in str(exc.value)  # le message dit la source


def test_geocodage_sans_code_postal_premier_candidat_controle_non_fait():
    geo, _ = geocoder_liste("1 rue de test Exempleville",
                            feature_ban(LABEL, "99001_0001_00001", postcode="99100"),
                            feature_ban(LABEL, "99001_0001_00002", postcode="99200"))
    assert geo["rang_candidat"] == 1 and geo["identifiant_ban"] == "99001_0001_00001"
    assert geo["controle_commune"] == "non fait : pas de code postal dans l'adresse"


def test_geocodage_le_code_postal_est_le_dernier_nombre_a_cinq_chiffres_de_l_adresse():
    geo, _ = geocoder_liste("BP 12345 1 rue de test 99100 Exempleville",
                            feature_ban(LABEL, "99001_0001_00001", postcode="99100"))
    assert geo["controle_commune"] == "code postal 99100 concordant"


@pytest.mark.parametrize("adresse", ["123456 rue de test Exempleville", "1 rue de test 99100Exempleville", "1 rue 7714 Exempleville"],
                         ids=["six_chiffres", "colle_a_du_texte", "quatre_chiffres"])
def test_geocodage_ce_qui_n_est_pas_un_code_postal_laisse_le_controle_non_fait(adresse):
    geo, _ = geocoder_liste(adresse, feature_ban(LABEL, "99001_0001_00001"))
    assert geo["controle_commune"].startswith("non fait")


def test_geocodage_un_candidat_sans_postcode_n_est_jamais_concordant():
    geo, _ = geocoder_liste("1 rue de test 99100 Exempleville",
                            feature_ban(LABEL, "99001_0001_00001", postcode=None),
                            feature_ban(LABEL, "99001_0001_00002", postcode="99100"))
    assert geo["rang_candidat"] == 2 and geo["identifiant_ban"] == "99001_0001_00002"


def test_geocodage_seuls_les_cinq_premiers_candidats_sont_examines():
    cinq_autres = [feature_ban(LABEL, f"99001_0001_0000{k}", postcode="99200") for k in range(5)]
    sixieme = feature_ban(LABEL, "99001_0001_00009", postcode="99100")
    with pytest.raises(oh.OpendataError, match="aucun candidat dans le code postal 99100"):
        geocoder_liste("1 rue de test 99100 Exempleville", *cinq_autres, sixieme)
    geo, _ = geocoder_liste("1 rue de test 99100 Exempleville", *cinq_autres[:4], sixieme)  # le 5e rang est examiné
    assert geo["rang_candidat"] == 5


@pytest.mark.parametrize("identifiant", [None, 99001, ""], ids=["absent", "non_chaine", "vide"])
def test_geocodage_identifiant_ban_absent_ou_invalide_leve_forme_inattendue(identifiant):
    feature = feature_ban(LABEL, "99001_0001_00001")
    if identifiant is None:
        del feature["properties"]["id"]
    else:
        feature["properties"]["id"] = identifiant
    with pytest.raises(oh.OpendataError, match="forme inattendue"):
        geocoder_liste("1 rue de test 99100 Exempleville", feature)


def test_geocodage_dict_rendu_les_onze_cles_du_contrat():
    geo, _ = geocoder_liste("1 rue de test 99100 Exempleville", feature_ban(LABEL, "99001_0001_00001"))
    assert set(geo) == {"label", "score", "type", "citycode", "postcode", "city", "lon", "lat", "identifiant_ban",
                        "controle_commune", "rang_candidat"}


def fiche_pour(adresse: str, r: Routeur | None = None, **kw: Any) -> tuple[dict, Routeur]:
    """Comme `fiche_nominale`, pour une adresse choisie (le routeur répond la même fixture quelle que soit la requête)."""
    r = r or routeur_nominal()
    kw.setdefault("maintenant", MAINTENANT)
    return fiche_mod.construire_fiche(adresse, client=r.client(), sleep=r.sleep, **kw), r


def alertes_de(fiche: dict, bloc: str) -> list[dict]:
    return [a for a in fiche["alertes"] if a["bloc"] == bloc]


def test_fiche_sans_code_postal_une_alerte_dit_que_le_controle_de_commune_n_est_pas_fait():
    fiche, _ = fiche_pour("1 rue de test Exempleville")
    alertes = alertes_de(fiche, "geocodage")
    assert len(alertes) == 1
    assert "contrôle de commune non fait" in alertes[0]["message"] and LABEL in alertes[0]["message"]
    assert [a["bloc"] for a in fiche["alertes"]] == ["geocodage", "dvf"]  # l'alerte du géocodage vient en premier
    assert fiche["erreurs"] == [] and fiche_mod.code_sortie(fiche) == 0  # une alerte ne change pas le code


def test_fiche_candidat_de_rang_2_une_alerte_dit_le_rang_retenu_et_le_code_postal():
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(reponse_ban(
        feature_ban("1 Rue de Test 99200 Bourg-Exemple", "99002_0001_00001", postcode="99200", citycode="99002"),
        feature_ban(LABEL, "99001_0001_00001"))))
    fiche, _ = fiche_pour("1 rue de test 99100 Exempleville", r)
    assert fiche["geocodage"]["rang_candidat"] == 2 and fiche["commune"]["insee"] == INSEE
    alertes = alertes_de(fiche, "geocodage")
    assert len(alertes) == 1 and "rang 2" in alertes[0]["message"] and "99100" in alertes[0]["message"]
    assert "parmi les 5 lus" in alertes[0]["message"]  # le nombre de candidats lus est dit


def test_fiche_code_postal_concordant_au_rang_1_aucune_alerte_de_geocodage():
    fiche, _ = fiche_nominale()
    assert fiche["geocodage"]["rang_candidat"] == 1
    assert alertes_de(fiche, "geocodage") == []


def test_fiche_score_trop_faible_l_erreur_suffit_pas_d_alerte_de_geocodage():
    payload = fx("geocodage_housenumber.json")
    payload["features"][0]["properties"]["score"] = 0.4
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(payload))
    fiche, _ = fiche_pour("1 rue de test Exempleville", r)  # sans code postal : le contrôle ne serait pas fait
    assert blocs_erreurs(fiche) == ["geocodage"] and fiche["alertes"] == []


# ===========================================================================
# - étape 3 : cadastre (API Carto) et géocodage inverse
# ===========================================================================

def geom_demandee(appel: Appel) -> Any:
    return json.loads(appel.params["geom"])


def collecter_cadastre(carto: Any, inverse: Any = None, *, geo: dict | None = None):
    r = Routeur().route(MOTIF_CADASTRE, carto if callable(carto) or isinstance(carto, (list, type)) else rep_json(carto))
    if inverse is not None:
        r.route(MOTIF_INVERSE, inverse if callable(inverse) or isinstance(inverse, list) else rep_json(inverse))
    return cadastre.collecter(r.client(), geo or GEO, sleep=r.sleep), r


# --- géocodage inverse (`geocodage.inverse`) -------------------------------------------------

def test_inverse_requete_lon_lat_index_limit_et_proprietes_dans_l_ordre_de_l_api():
    r = Routeur().route(MOTIF_INVERSE, rep_json(reponse_ban(
        feature_ban("3 Rue de l'Exemple 99200 Bourg-Exemple", "99002_0007_00003", distance=17),
        feature_ban("1 Rue de l'Exemple 99200 Bourg-Exemple", "99002_0007_00001", distance=26))))
    resultats = geocodage.inverse(r.client(), lon=1.700583, lat=47.300417, index="address", limit=5, sleep=r.sleep)
    assert r.appels[0].params == {"lon": "1.700583", "lat": "47.300417", "index": "address", "limit": "5"}
    assert [x["id"] for x in resultats] == ["99002_0007_00003", "99002_0007_00001"]
    assert resultats[0]["distance"] == 17 and resultats[0]["type"] == "housenumber"


def test_inverse_aucun_resultat_rend_une_liste_vide_pas_une_erreur():
    r = Routeur().route(MOTIF_INVERSE, rep_json(reponse_ban()))
    assert geocodage.inverse(r.client(), lon=LON, lat=LAT, index="parcel", limit=1, sleep=r.sleep) == []


@pytest.mark.parametrize("payload", [
    {}, {"features": "x"}, {"features": [{"geometry": {}}]}, {"features": [{"properties": "x"}]}, [],
], ids=["sans_features", "features_non_liste", "sans_proprietes", "proprietes_non_objet", "racine_liste"])
def test_inverse_forme_inattendue_leve_opendata_error_et_nomme_l_url(payload):
    r = Routeur().route(MOTIF_INVERSE, rep_json(payload))
    with pytest.raises(oh.OpendataError, match="forme inattendue") as exc:
        geocodage.inverse(r.client(), lon=LON, lat=LAT, index="address", limit=5, sleep=r.sleep)
    assert "data.geopf.fr/geocodage/reverse" in str(exc.value)


def test_inverse_erreur_400_levee_tout_de_suite_sans_nouvel_essai():
    r = Routeur().route(MOTIF_INVERSE, rep_statut(400))
    with pytest.raises(oh.OpendataError, match="HTTP 400"):
        geocodage.inverse(r.client(), lon=LON, lat=LAT, index="address", limit=51, sleep=r.sleep)
    assert len(r.appels) == 1 and r.attentes == []


# --- cadastre.collecter ----------------------------------------------------------------------

def test_cadastre_constantes_du_contrat():
    assert cadastre.URL == "https://apicarto.ign.fr/api/cadastre/parcelle"
    assert cadastre.LICENCE == "Licence Ouverte 2.0 (Etalab) - plan cadastral (DGFiP) via API Carto (IGN)"
    assert cadastre.SOURCE == {"bloc": "cadastre", "url": cadastre.URL, "licence": cadastre.LICENCE, "millesime": None}
    assert cadastre.METHODE_CONTENANT == "parcelle contenant le point"
    assert cadastre.METHODE_PLUS_PROCHE == "parcelle la plus proche du point (point hors parcelle), à confirmer"


def test_cadastre_parcelle_contenant_le_point_bloc_complet_une_seule_requete():
    res, r = collecter_cadastre(reponse_carto(parcelle_carto(contenance=106)))
    assert res.bloc == {
        "idu": IDU, "section": "AB", "numero": "0001", "contenance_m2": 106, "code_insee": INSEE,
        "commune": "Exempleville", "methode": "parcelle contenant le point",
    }
    assert res.erreurs == [] and res.alertes == []
    assert res.sources == [cadastre.SOURCE]
    assert [a.cle for a in r.appels] == [MOTIF_CADASTRE]  # pas de géocodage inverse quand la parcelle est trouvée


def test_cadastre_la_requete_n_envoie_que_geom_en_point_lon_puis_lat():
    """Longitude et latitude inversées donnent 200 et 0 résultat sans erreur ; un autre nom de paramètre donne des
    parcelles quelconques : le test fige le seul paramètre et l'ordre des coordonnées."""
    _, r = collecter_cadastre(reponse_carto(parcelle_carto()))
    assert set(r.appels[0].params) == {"geom"}
    assert geom_demandee(r.appels[0]) == {"type": "Point", "coordinates": [LON, LAT]}


def test_cadastre_plusieurs_parcelles_la_premiere_est_retenue_et_une_alerte_les_nomme():
    autre = f"{INSEE}000AB0002"
    res, _ = collecter_cadastre(reponse_carto(parcelle_carto(), parcelle_carto(idu=autre, numero="0002")))
    assert res.bloc["idu"] == IDU and res.bloc["methode"] == cadastre.METHODE_CONTENANT
    assert len(res.alertes) == 1 and res.alertes[0]["bloc"] == "cadastre"
    assert "2 parcelles" in res.alertes[0]["message"]
    assert IDU in res.alertes[0]["message"] and autre in res.alertes[0]["message"]


def test_cadastre_point_sur_la_voirie_repli_sur_la_parcelle_la_plus_proche_et_une_alerte():
    res, r = collecter_cadastre(
        reponse_carto(), reponse_ban(feature_parcelle_inverse("99002000AT0001", "AT", "0001", distance=9)),
        geo={**GEO, "citycode": "99002"})
    assert res.bloc["idu"] == "99002000AT0001" and res.bloc["section"] == "AT" and res.bloc["numero"] == "0001"
    assert res.bloc["contenance_m2"] is None  # la contenance n'existe pas dans cette source : null, jamais 0
    assert res.bloc["methode"] == cadastre.METHODE_PLUS_PROCHE
    assert len(res.alertes) == 1 and res.alertes[0]["bloc"] == "cadastre"
    assert "aucune parcelle ne contient le point" in res.alertes[0]["message"]
    assert "99002000AT0001" in res.alertes[0]["message"] and "9 m" in res.alertes[0]["message"]
    assert [a.cle for a in r.appels] == [MOTIF_CADASTRE, MOTIF_INVERSE]
    assert r.appels[1].params == {"lon": str(LON), "lat": str(LAT), "index": "parcel", "limit": "1"}
    assert [s["url"] for s in res.sources] == [cadastre.URL, geocodage.URL_REVERSE]


def test_cadastre_repli_sans_distance_dans_la_reponse_l_alerte_reste_lisible():
    res, _ = collecter_cadastre(
        reponse_carto(), reponse_ban(feature_parcelle_inverse("99002000AT0001", "AT", "0001", distance=None)))
    assert "99002000AT0001" in res.alertes[0]["message"] and "(à " not in res.alertes[0]["message"]  # pas de distance


def test_cadastre_repli_insee_lu_dans_departement_plus_commune_et_commune_dans_city_sinon_null():
    """La source n'a pas de `citycode` : le code INSEE est `departmentcode` + `municipalitycode` (77 + 458)."""
    res, _ = collecter_cadastre(
        reponse_carto(), reponse_ban(feature_parcelle_inverse("99002000AT0001", "AT", "0001", ville="Bourg-Exemple")),
        geo={**GEO, "citycode": "99002"})
    assert (res.bloc["code_insee"], res.bloc["commune"]) == ("99002", "Bourg-Exemple")
    assert len(res.alertes) == 1  # seule l'alerte « point hors parcelle » : la commune est celle du géocodage
    sans = feature_parcelle_inverse("99002000AT0001", "AT", "0001", ville=None)
    for cle in ("departmentcode", "municipalitycode"):
        del sans["properties"][cle]
    absent, _ = collecter_cadastre(reponse_carto(), reponse_ban(sans))
    assert (absent.bloc["code_insee"], absent.bloc["commune"]) == (None, None)  # absent de la source : null


@pytest.mark.parametrize("cle, valeur", [("departmentcode", ""), ("municipalitycode", ""), ("departmentcode", None),
                                         ("municipalitycode", 458)],
                         ids=["departement_vide", "commune_vide", "departement_null", "commune_non_textuelle"])
def test_cadastre_repli_un_code_departement_ou_commune_vide_ou_illisible_laisse_l_insee_inconnu_sans_fausse_alerte(
        cle, valeur):
    """Un `departmentcode` vide ne doit pas donner « 458 » (et une fausse alerte de commune différente)."""
    feature = feature_parcelle_inverse("99002000AT0001", "AT", "0001", ville="Bourg-Exemple")
    feature["properties"][cle] = valeur
    res, _ = collecter_cadastre(reponse_carto(), reponse_ban(feature), geo={**GEO, "citycode": "99002"})
    assert res.bloc["code_insee"] is None
    assert len(res.alertes) == 1 and "aucune parcelle ne contient le point" in res.alertes[0]["message"]


def test_cadastre_repli_parcelle_la_plus_proche_d_une_autre_commune_une_alerte_en_plus():
    """Le point est près d'une limite de commune : la parcelle la plus proche est de l'autre côté."""
    res, _ = collecter_cadastre(
        reponse_carto(), reponse_ban(feature_parcelle_inverse("99999000AT0001", "AT", "0001", ville="Ailleurs")))
    assert res.bloc["code_insee"] == "99999"
    assert [a["bloc"] for a in res.alertes] == ["cadastre", "cadastre"]
    assert "99999" in res.alertes[1]["message"] and INSEE in res.alertes[1]["message"]


def test_cadastre_aucune_parcelle_nulle_part_leve_opendata_error():
    with pytest.raises(oh.OpendataError, match="aucune parcelle"):
        collecter_cadastre(reponse_carto(), reponse_ban())


def test_cadastre_api_carto_en_erreur_leve_apres_trois_essais_sans_repli():
    r = Routeur().route(MOTIF_CADASTRE, rep_statut(500)).route(MOTIF_INVERSE, rep_json(reponse_ban()))
    with pytest.raises(oh.OpendataError, match="500"):
        cadastre.collecter(r.client(), GEO, sleep=r.sleep)
    assert len(r.appels_vers(MOTIF_CADASTRE)) == 3 and r.attentes == [1, 2]
    assert not r.appels_vers(MOTIF_INVERSE)  # une panne n'est pas « point hors parcelle » : pas de repli


def test_cadastre_repli_en_erreur_leve_opendata_error():
    r = Routeur().route(MOTIF_CADASTRE, rep_json(reponse_carto())).route(MOTIF_INVERSE, rep_statut(500))
    with pytest.raises(oh.OpendataError, match="500"):
        cadastre.collecter(r.client(), GEO, sleep=r.sleep)


@pytest.mark.parametrize("modifier", [
    pytest.param(lambda p: {}, id="sans_features"),
    pytest.param(lambda p: {"features": {"a": 1}}, id="features_non_liste"),
    pytest.param(lambda p: {"features": [{"geometry": {}}]}, id="sans_proprietes"),
    pytest.param(lambda p: {"features": [{"properties": {k: v for k, v in p["properties"].items() if k != "idu"}}]},
                 id="sans_idu"),
    pytest.param(lambda p: {"features": [{"properties": {**p["properties"], "idu": 99001}}]}, id="idu_non_chaine"),
    pytest.param(lambda p: {"features": [{"properties": {**p["properties"], "contenance": "106"}}]},
                 id="contenance_chaine"),
    pytest.param(lambda p: {"features": [{"properties": {**p["properties"], "contenance": True}}]},
                 id="contenance_booleen"),
    pytest.param(lambda p: {"features": [{"properties": {**p["properties"], "section": None}}]}, id="section_nulle"),
])
def test_cadastre_forme_inattendue_leve_opendata_error_nomme_l_url(modifier):
    with pytest.raises(oh.OpendataError, match="forme inattendue") as exc:
        collecter_cadastre(modifier(parcelle_carto()))
    assert "apicarto.ign.fr" in str(exc.value)


@pytest.mark.parametrize("contenance", [None, 0, -5, 0.0])
def test_cadastre_contenance_absente_nulle_ou_negative_donne_null_jamais_un_faux_zero(contenance):
    res, _ = collecter_cadastre(reponse_carto(parcelle_carto(contenance=contenance)))
    assert res.bloc["contenance_m2"] is None


@pytest.mark.parametrize("contenance", [1, 106, 104.7])
def test_cadastre_contenance_positive_lue_telle_quelle(contenance):
    res, _ = collecter_cadastre(reponse_carto(parcelle_carto(contenance=contenance)))
    assert res.bloc["contenance_m2"] == contenance


def test_cadastre_parcelle_d_une_autre_commune_que_le_geocodage_une_alerte():
    res, _ = collecter_cadastre(reponse_carto(parcelle_carto(idu="99999000ZZ0001", code_insee="99999", nom_com="Ailleurs")))
    assert res.bloc["idu"] == "99999000ZZ0001"
    assert len(res.alertes) == 1 and "99999" in res.alertes[0]["message"] and INSEE in res.alertes[0]["message"]
    meme, _ = collecter_cadastre(reponse_carto(parcelle_carto()))
    assert meme.alertes == []  # même commune : rien à dire


def test_cadastre_forme_inattendue_du_repli_leve_opendata_error():
    sans_id = feature_parcelle_inverse("99002000AT0001", "AT", "0001")
    del sans_id["properties"]["id"]
    with pytest.raises(oh.OpendataError, match="forme inattendue") as exc:
        collecter_cadastre(reponse_carto(), reponse_ban(sans_id))
    assert "data.geopf.fr/geocodage/reverse" in str(exc.value)


# ===========================================================================
# - étape 4 : cadastre et clé du bien dans la fiche, résumé à onze lignes
# ===========================================================================

def test_fiche_cadastre_et_cle_bien_nominaux():
    fiche, _ = fiche_nominale()
    assert fiche["cadastre"] == {
        "idu": IDU, "section": "AB", "numero": "0001", "contenance_m2": 500, "code_insee": INSEE,
        "commune": "Exempleville", "methode": "parcelle contenant le point",
    }
    assert fiche["cle_bien"] == {"parcelle": IDU, "identifiant_ban": "99001_0001_00001", "fiable": True}
    assert fiche["erreurs"] == [] and [a["bloc"] for a in fiche["alertes"]] == ["dvf"]
    json.dumps(fiche, ensure_ascii=False)


def test_fiche_le_cadastre_est_le_premier_collecteur_et_sa_source_suit_celle_du_geocodage():
    fiche, r = fiche_nominale()
    assert [a.cle for a in r.appels][:2] == [MOTIF_GEOCODAGE, MOTIF_CADASTRE]
    assert [s["bloc"] for s in fiche["sources"]][:2] == ["geocodage", "cadastre"]
    source = fiche["sources"][1]
    assert source == {"bloc": "cadastre", "url": cadastre.URL, "date_extraction": "2026-10-03",
                      "licence": cadastre.LICENCE, "millesime": None}


def _routeur_cas_cle_bien(cas: str) -> Routeur:
    r = routeur_nominal()
    if cas == "commune_sans_numero":  # géocodage de type municipality, parcelle qui contient le point
        r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_commune.json")))
        r.route(MOTIF_CADASTRE, rep_json(reponse_carto(parcelle_carto())))
    elif cas == "point_hors_parcelle":  # numéro de rue, mais aucune parcelle ne contient le point
        r.route(MOTIF_CADASTRE, rep_json(reponse_carto()))
        r.route(MOTIF_INVERSE, rep_json(reponse_ban(feature_parcelle_inverse(f"{INSEE}000AB0007", "AB", "0007"))))
    return r


@pytest.mark.parametrize("cas, parcelle_attendue, fiable", [
    pytest.param("nominal", IDU, True, id="numero_de_rue_et_parcelle_contenant_le_point"),
    pytest.param("commune_sans_numero", IDU, False, id="geocodage_commune_pas_fiable"),
    pytest.param("point_hors_parcelle", f"{INSEE}000AB0007", False, id="parcelle_la_plus_proche_pas_fiable"),
])
def test_fiche_cle_bien_fiable_seulement_si_numero_de_rue_et_parcelle_contenant_le_point(cas, parcelle_attendue,
                                                                                           fiable):
    fiche, _ = fiche_nominale(_routeur_cas_cle_bien(cas))
    assert fiche["cle_bien"]["parcelle"] == parcelle_attendue
    assert fiche["cle_bien"]["identifiant_ban"] == fiche["geocodage"]["identifiant_ban"]
    assert fiche["cle_bien"]["fiable"] is fiable
    assert set(fiche["cle_bien"]) == {"parcelle", "identifiant_ban", "fiable"}


def test_fiche_cadastre_en_panne_bloc_null_erreur_nommee_code_3_et_cle_bien_garde_l_identifiant_ban():
    r = routeur_nominal()
    r.route(MOTIF_CADASTRE, rep_statut(500))
    fiche, _ = fiche_nominale(r)
    assert fiche["cadastre"] is None and blocs_erreurs(fiche) == ["cadastre", "batiment"]
    # ancien attendu : ["cadastre"] seul ; le bâtiment lit la parcelle du cadastre
    assert fiche["erreurs"][1] == {"bloc": "batiment", "message": "parcelle inconnue (cadastre en échec)"}
    assert fiche["cle_bien"] == {"parcelle": None, "identifiant_ban": "99001_0001_00001", "fiable": False}
    assert fiche["batiment"] is None and not r.appels_vers(MOTIF_BDNB_RELATION)  # aucun appel BDNB sans parcelle
    # ancien attendu : tous les blocs de BLOCS_COLLECTES servis ; désormais tous sauf le bâtiment
    assert all(fiche[bloc] is not None for bloc in BLOCS_COLLECTES if bloc != "batiment")
    assert fiche["copropriete"]["correspondance"] == "parcelle inconnue"  # le RNIC est lu, sans parcelle à comparer
    assert r.attentes == [1, 2] and fiche_mod.code_sortie(fiche) == 3
    assert not [s for s in fiche["sources"] if s["bloc"] in ("cadastre", "batiment")]


@pytest.mark.parametrize("reponse", [rep_json(fx("geocodage_vide.json")), rep_statut(500),
                                     rep_json(fx("geocodage_score_faible.json"))],
                         ids=["features_vide", "http_500", "score_faible"])
def test_fiche_geocodage_en_echec_cle_bien_et_cadastre_null_aucun_appel_cadastre(reponse):
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, reponse)
    fiche, _ = fiche_nominale(r)
    assert fiche["cle_bien"] is None and fiche["cadastre"] is None
    assert not r.appels_vers(MOTIF_CADASTRE)
    assert fiche_mod.code_sortie(fiche) == 2


def test_fiche_alertes_du_cadastre_remontent_sans_changer_le_code_de_sortie():
    fiche, _ = fiche_nominale(_routeur_cas_cle_bien("point_hors_parcelle"))
    assert [a["bloc"] for a in fiche["alertes"]] == [
        "cadastre", "batiment", "batiment", "copropriete", "copropriete", "dvf"]  # le cadastre est collecté avant DVF
    # ancien attendu : ["cadastre", "dvf"] ; une évolution ajoute, pour une parcelle seulement la
    # plus proche, « à confirmer » en tête des alertes du bâtiment et de la copropriété, puis leurs propres alertes
    assert "aucune parcelle ne contient le point" in fiche["alertes"][0]["message"]
    assert [a["message"] for a in fiche["alertes"][1:5]] == [
        "bâtiment d'une parcelle à confirmer", "aucun bâtiment BDNB sur la parcelle",
        "copropriété d'une parcelle à confirmer",
        f"aucune copropriété immatriculée sur la parcelle {INSEE}000AB0007 : l'absence du RNIC ne prouve pas "
        f"l'absence de copropriété"]
    assert fiche["erreurs"] == [] and fiche_mod.code_sortie(fiche) == 0
    assert [s["bloc"] for s in fiche["sources"]][:3] == ["geocodage", "cadastre", "cadastre"]  # Carto puis le repli


def test_fiche_exception_inattendue_dans_le_cadastre_bloc_none_et_type_dans_le_message():
    r = routeur_nominal()
    r.route(MOTIF_CADASTRE, KeyError("boom"))
    fiche, _ = fiche_nominale(r)
    assert fiche["cadastre"] is None and fiche["erreurs"][0] == {"bloc": "cadastre", "message": "KeyError: 'boom'"}
    assert fiche["cle_bien"]["parcelle"] is None and fiche_mod.code_sortie(fiche) == 3


# ===========================================================================
# - urbanisme, bâtiment et copropriété dans la fiche
# ===========================================================================

def test_fiche_urbanisme_batiment_copropriete_nominaux_sans_erreur_ni_alerte_nouvelle():
    fiche, r = fiche_nominale()
    assert fiche_mod.CLES[5:9] == ("cadastre", "urbanisme", "batiment", "copropriete")  # juste après le cadastre
    urb, bat, cop = fiche["urbanisme"], fiche["batiment"], fiche["copropriete"]
    assert urb["commune"] == {"insee": INSEE, "nom": "EXEMPLEVILLE", "rnu": False, "supprimee": False}
    assert urb["zone"]["libelle"] == "Ua1" and urb["zone"]["date_approbation"] == "2025-04-10"
    assert [d["nom"] for d in urb["documents"]] == ["99001_PLU_20250410"]
    assert urb["abords_monument_historique"] is True and urb["plan_prevention_risques"] is True
    assert [p["libelle"] for p in urb["prescriptions"]] == ["Linéaire d'exemple protégé"]
    assert bat["parcelle"] == IDU and bat["n_groupes"] == 1
    assert bat["groupes"][0]["batiment_groupe_id"] == ID_GROUPE_BDNB
    assert bat["groupes"][0]["parcelle_principale"] is True
    assert cop["n_commune"] == 2 and cop["correspondance"] == "parcelle" and cop["parametres"]["parcelle"] == IDU
    assert [v["numero_immatriculation"] for v in cop["voisines"]] == ["AA0000002"]
    assert fiche["erreurs"] == [] and [a["bloc"] for a in fiche["alertes"]] == ["dvf"]  # aucune alerte de plus
    json.dumps(fiche, ensure_ascii=False)
    # le bâtiment lit la parcelle du CADASTRE, la copropriété aussi : mêmes IDU, même commune que le géocodage
    assert r.appels_vers(MOTIF_BDNB_RELATION)[0].params == {"parcelle_id": f"eq.{IDU}"}
    assert r.appels_vers(MOTIF_RNIC)[0].params["commune__exact"] == INSEE


def test_fiche_les_collecteurs_reglementaires_passent_apres_le_cadastre_et_avant_les_loyers():
    fiche, r = fiche_nominale()
    ordre = [a.cle for a in r.appels]
    assert ordre[:12] == [MOTIF_GEOCODAGE, MOTIF_CADASTRE, *MOTIFS_URBANISME, MOTIF_BDNB_RELATION,
                          MOTIF_BDNB_GROUPES, MOTIF_RNIC]
    assert ordre[12].startswith("tabular-api.data.gouv.fr/api/resources/")  # puis les loyers, autre ressource
    assert ordre[12] != MOTIF_RNIC
    assert [s["bloc"] for s in fiche["sources"]][:5] == [
        "geocodage", "cadastre", "urbanisme", "batiment", "copropriete"]
    assert fiche["sources"][2]["url"] == urbanisme.URL and fiche["sources"][3]["url"] == batiment.URL
    assert fiche["sources"][4]["url"] == copropriete.URL


def test_fiche_point_de_commune_saute_urbanisme_batiment_et_copropriete_avec_une_alerte():
    """Décision de référence : un point `municipality` est le centre de la commune, il ne dit rien du bien."""
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_commune.json")))
    fiche, _ = fiche_nominale(r)
    assert fiche["geocodage"]["type"] == "municipality"
    assert all(fiche[bloc] is None for bloc in BLOCS_REGLEMENTAIRES)
    assert {"bloc": "geocodage",
            "message": "point de commune : urbanisme, bâtiment et copropriété non lus"} in fiche["alertes"]
    assert not [e for e in fiche["erreurs"] if e["bloc"] in BLOCS_REGLEMENTAIRES]  # sautés : pas des échecs
    for motif in (*MOTIFS_URBANISME[1:], MOTIF_BDNB_RELATION, MOTIF_BDNB_GROUPES, MOTIF_RNIC):
        assert not r.appels_vers(motif), motif  # aucun appel (la commune de GPU n'est pas lue non plus)
    assert not r.appels_vers(MOTIF_GPU_COMMUNE)
    assert not [s for s in fiche["sources"] if s["bloc"] in BLOCS_REGLEMENTAIRES]


@pytest.mark.parametrize("type_point, message", [
    pytest.param("street", "point sur la rue", id="rue"),
    pytest.param("locality", "point sur un lieu-dit", id="lieu_dit"),
    pytest.param("autre", "point de type autre", id="type_inconnu"),
])
def test_fiche_point_sur_la_rue_lit_les_trois_blocs_avec_une_alerte(type_point, message):
    """`street` (décision de référence) : lus, avec « point sur la rue ». Lieu-dit et type inconnu : lus aussi,
    avec une alerte qui nomme le type (cas non prévu au départ)."""
    r = routeur_nominal()
    r.route(MOTIF_GEOCODAGE, rep_json(reponse_ban(
        feature_ban("Rue de Test 99100 Exempleville", "99001_0001", type_=type_point))))
    fiche, _ = fiche_nominale(r)
    assert fiche["geocodage"]["type"] == type_point
    assert all(fiche[bloc] is not None for bloc in BLOCS_REGLEMENTAIRES)
    assert {"bloc": "geocodage", "message": message} in fiche["alertes"]
    assert fiche["cle_bien"]["fiable"] is False  # pas un numéro de rue


def test_fiche_numero_de_rue_aucune_alerte_de_point():
    fiche, _ = fiche_nominale()
    assert not [a for a in fiche["alertes"] if a["bloc"] == "geocodage"]


def test_fiche_parcelle_la_plus_proche_les_appels_partent_avec_cet_idu_et_l_alerte_dit_a_confirmer():
    r = _routeur_cas_cle_bien("point_hors_parcelle")
    fiche, _ = fiche_nominale(r)
    idu_proche = f"{INSEE}000AB0007"
    assert r.appels_vers(MOTIF_BDNB_RELATION)[0].params == {"parcelle_id": f"eq.{idu_proche}"}
    assert fiche["batiment"]["parcelle"] == idu_proche and fiche["batiment"]["groupes"] == []
    assert fiche["copropriete"]["parametres"]["parcelle"] == idu_proche
    messages = [(a["bloc"], a["message"]) for a in fiche["alertes"]]
    assert ("batiment", "bâtiment d'une parcelle à confirmer") in messages
    assert ("copropriete", "copropriété d'une parcelle à confirmer") in messages
    # la parcelle qui contient le point n'appelle aucune alerte « à confirmer » (fiche nominale)
    assert not [a for a in fiche_nominale()[0]["alertes"] if "à confirmer" in a["message"]]


def test_fiche_cadastre_en_panne_copropriete_sans_parcelle_dit_parcelle_inconnue_et_batiment_en_erreur():
    r = routeur_nominal()
    r.route(MOTIF_CADASTRE, rep_statut(500))
    fiche, _ = fiche_nominale(r)
    assert fiche["batiment"] is None
    assert fiche["copropriete"]["correspondance"] == "parcelle inconnue"
    assert fiche["copropriete"]["parametres"]["parcelle"] is None
    assert any(a["bloc"] == "copropriete" and "parcelle inconnue" in a["message"] for a in fiche["alertes"])
    assert not [a for a in fiche["alertes"] if "à confirmer" in a["message"]]  # pas de parcelle, donc rien à confirmer


def _routeur_commune_de_la_parcelle(code_insee: str | None) -> Routeur:
    """Une parcelle qui CONTIENT le point mais que l'API Carto place dans une autre commune (ou sans commune)."""
    r = routeur_nominal()
    parcelle = parcelle_carto(idu="99999000ZZ9999", code_insee="99999", nom_com="Ailleurs")
    if code_insee is None:
        parcelle["properties"]["code_insee"] = None
    else:
        parcelle["properties"]["code_insee"] = code_insee
    r.route(MOTIF_CADASTRE, rep_json(reponse_carto(parcelle)), si=_point_du_bien)
    return r


def test_fiche_cle_bien_pas_fiable_quand_la_commune_de_la_parcelle_differe_du_geocodage():
    fiche, _ = fiche_nominale(_routeur_commune_de_la_parcelle("99999"))
    assert fiche["cadastre"]["methode"] == cadastre.METHODE_CONTENANT  # la parcelle contient bien le point
    assert fiche["geocodage"]["type"] == "housenumber"
    assert fiche["cle_bien"] == {"parcelle": "99999000ZZ9999", "identifiant_ban": "99001_0001_00001", "fiable": False}
    # ancien attendu : fiable True (numéro de rue et parcelle contenant le point) ; la commune est désormais contrôlée
    messages = [(a["bloc"], a["message"]) for a in fiche["alertes"]]
    assert ("cle_bien", "clé du bien non fiable : la parcelle 99999000ZZ9999 est dans la commune 99999, le géocodage "
                        "dit 99001") in messages
    assert any(bloc == "cadastre" and "à vérifier" in message for bloc, message in messages)  # celle du cadastre reste
    assert fiche["erreurs"] == [] and fiche_mod.code_sortie(fiche) == 0  # une alerte ne change pas le code


@pytest.mark.parametrize("code_insee, fiable, alerte", [
    pytest.param(INSEE, True, False, id="meme_commune"),
    pytest.param("99999", False, True, id="autre_commune"),
    pytest.param(None, True, False, id="commune_de_la_parcelle_inconnue_pas_d_ecart_prouve"),
])
def test_fiche_cle_bien_fiable_selon_la_commune_de_la_parcelle(code_insee, fiable, alerte):
    r = _routeur_commune_de_la_parcelle(code_insee)
    fiche, _ = fiche_nominale(r)
    assert fiche["cle_bien"]["fiable"] is fiable
    assert any(a["bloc"] == "cle_bien" for a in fiche["alertes"]) is alerte


# --- résumé : onze lignes, puis quatorze avec les blocs réglementaires -------------------------

def trois_immeubles_de_reference() -> list[list[dict[str, str]]]:
    """R1 : 120 m2, 240 000 (2 000 €/m2, 80 000/logement) ; R2 : 90 m2, 270 000 (3 000, 90 000) ; R3 : 100 m2,
    150 000 (1 500, 37 500). Médianes : 2 000 €/m2 et 80 000 €/logement."""
    return [
        immeuble_p("2025-986001", 240000, parcelle(1), logements=(40, 40, 40), nord_m=10),
        immeuble_p("2025-986002", 270000, parcelle(2), logements=(30, 30, 30), nord_m=20),
        immeuble_p("2025-986003", 150000, parcelle(3), logements=(25, 25, 25, 25), nord_m=30),
    ]


def test_resume_quatorze_lignes_cadastre_puis_lignes_reglementaires_apres_le_geocodage_immeubles_apres_dvf(tmp_path):
    r = routeur_nominal()
    r.route(url_dvf(2025), rep_csv(csv_dvf(*trois_immeubles_de_reference())))
    fiche, _ = fiche_nominale(r, fenetre_immeubles_mois=60)
    lignes = fiche_mod.resume(fiche, tmp_path / "f.json").splitlines()
    assert len(lignes) == 14  # ancien attendu : 11
    assert [ligne.split(" :")[0] for ligne in lignes] == [
        "Géocodage", "Cadastre", "Urbanisme", "Bâtiment", "Copropriété", "Loyers 2025 (EUR/m2/mois)", "DVF",
        "Immeubles", "DPE", "Risques", "Taxe foncière", "Erreurs", "Alertes", "Fiche écrite"]
    # ancien attendu : ["Géocodage", "Cadastre", "Loyers 2025 (EUR/m2/mois)", "DVF", "Immeubles", "DPE", "Risques",
    #                   "Taxe foncière", "Erreurs", "Alertes", "Fiche écrite"]
    assert lignes[1] == f"Cadastre : parcelle {IDU} (500 m², parcelle contenant le point)"
    assert lignes[7] == ("Immeubles : 3 ventes retenues ; référence (3 logements ou plus, une par parcelle, sans "
                         "atypique) n = 3, médiane 2000,00 €/m² bâti, 80000,00 €/logement")


def test_resume_lignes_urbanisme_batiment_copropriete_nominales_apres_le_cadastre(tmp_path):
    fiche, _ = fiche_nominale()
    texte = fiche_mod.resume(fiche, tmp_path / "f.json")
    assert texte.splitlines()[2:5] == [
        "Urbanisme : zone Ua1 (99001_PLU_20250410 PLU), abords MH oui, PPR oui, 1 prescription (carré ~38 × 56 m)",
        "Bâtiment : 1900 · PIERRE · 3 logements (BDNB, 1 groupe)",
        "Copropriété : immatriculée sur la parcelle, 1 voisine à moins de 50 m",
    ]


def _fiche_modifiee(fiche: dict, **blocs: Any) -> dict:
    copie = json.loads(json.dumps(fiche))
    copie.update(blocs)
    return copie


@pytest.mark.parametrize("modification, attendu", [
    pytest.param(lambda f: {"urbanisme": None}, "Urbanisme : n/d", id="urbanisme_absent"),
    pytest.param(lambda f: {"urbanisme": {**f["urbanisme"], "zone": None, "documents": []}},
                 "Urbanisme : zone n/d, abords MH oui, PPR oui, 1 prescription (carré ~38 × 56 m)",
                 id="sans_zone"),
    pytest.param(lambda f: {"urbanisme": {**f["urbanisme"], "zone": None, "documents": [],
                                          "commune": {**f["urbanisme"]["commune"], "rnu": True}}},
                 "Urbanisme : zone n/d (commune au RNU), abords MH oui, PPR oui, 1 prescription (carré ~38 × 56 m)",
                 id="commune_au_rnu"),
    pytest.param(lambda f: {"urbanisme": {**f["urbanisme"], "documents": [], "abords_monument_historique": False,
                                          "plan_prevention_risques": False, "prescriptions": []}},
                 "Urbanisme : zone Ua1, abords MH non, PPR non, 0 prescription (carré ~38 × 56 m)",
                 id="sans_document_ni_servitude_ni_prescription"),
    pytest.param(lambda f: {"urbanisme": {**f["urbanisme"], "portee": {**f["urbanisme"]["portee"],
                                                                      "prescriptions": "illisible"}}},
                 "Urbanisme : zone Ua1 (99001_PLU_20250410 PLU), abords MH oui, PPR oui, 1 prescription",
                 id="taille_du_carre_illisible_omise"),
    pytest.param(lambda f: {"batiment": None}, "Bâtiment : n/d", id="batiment_absent"),
    pytest.param(lambda f: {"batiment": {**f["batiment"], "groupes": [], "n_groupes": 0}},
                 "Bâtiment : aucun groupe BDNB sur la parcelle", id="aucun_groupe"),
    pytest.param(lambda f: {"batiment": {**f["batiment"], "groupes": [
        {**f["batiment"]["groupes"][0], "annee_construction": None, "mat_mur_txt": None, "nb_log": None}]}},
                 "Bâtiment : n/d · n/d · n/d logements (BDNB, 1 groupe)", id="valeurs_absentes_jamais_un_zero"),
    pytest.param(lambda f: {"batiment": {**f["batiment"], "n_groupes": 2, "groupes": [
        f["batiment"]["groupes"][0], {**f["batiment"]["groupes"][0], "batiment_groupe_id": "autre", "nb_log": 2,
                                      "annee_construction": 1960}]}},
                 "Bâtiment : 1900 · PIERRE · 5 logements (BDNB, 2 groupes)", id="deux_groupes_total_des_logements"),
    pytest.param(lambda f: {"copropriete": None}, "Copropriété : n/d", id="copropriete_absente"),
    pytest.param(lambda f: {"copropriete": {**f["copropriete"], "correspondance": "aucune", "sur_la_parcelle": []}},
                 "Copropriété : aucune sur la parcelle (l'absence ne prouve rien), 1 voisine à moins de 50 m",
                 id="aucune_sur_la_parcelle"),
    pytest.param(lambda f: {"copropriete": {**f["copropriete"], "correspondance": "parcelle inconnue"}},
                 "Copropriété : parcelle inconnue (correspondance impossible), 1 voisine à moins de 50 m",
                 id="parcelle_inconnue"),
    pytest.param(lambda f: {"copropriete": {**f["copropriete"], "parametres": {
        **f["copropriete"]["parametres"], "voisines_dans_le_rayon": 8}}},
                 "Copropriété : immatriculée sur la parcelle, 8 voisines à moins de 50 m",
                 id="plus_de_cinq_voisines_le_compte_du_rayon_pas_la_liste"),
    pytest.param(lambda f: {"copropriete": {**f["copropriete"], "parametres": {
        **f["copropriete"]["parametres"], "voisines_dans_le_rayon": 0}}},
                 "Copropriété : immatriculée sur la parcelle, 0 voisine à moins de 50 m", id="aucune_voisine"),
])
def test_resume_lignes_reglementaires_disent_les_absences_sans_faux_zero(tmp_path, modification, attendu):
    nominale, _ = fiche_nominale()
    fiche = _fiche_modifiee(nominale, **modification(nominale))
    texte = fiche_mod.resume(fiche, tmp_path / "f.json")
    assert attendu in texte.splitlines() and len(texte.splitlines()) == 14


def test_resume_immeubles_sans_mediane_de_reference_dit_la_raison(tmp_path):
    fiche, _ = fiche_nominale(fenetre_immeubles_mois=60)  # les fixtures n'ont que 2 ventes, à 1 ou 2 logements
    ligne = _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "Immeubles :")
    assert ligne == ("Immeubles : 2 ventes retenues ; référence (3 logements ou plus, une par parcelle, sans "
                     "atypique) : n = 0 < 3 ventes de référence : médianes non calculées")


@pytest.mark.parametrize("cas, attendu", [
    pytest.param("desactive", "Immeubles : désactivé (--fenetre-immeubles-mois 0)", id="option_a_zero"),
    pytest.param("en_echec", "Immeubles : n/d", id="annee_ancienne_en_erreur"),
    pytest.param("dvf_absent", "Immeubles : n/d", id="dvf_en_echec"),
])
def test_resume_immeubles_absents_jamais_un_faux_zero(tmp_path, cas, attendu):
    r = routeur_nominal()
    if cas == "en_echec":
        r.route(url_dvf(2022), rep_statut(500))
    elif cas == "dvf_absent":
        r.route(MOTIF_DVF + "*", rep_statut(404))
    fiche, _ = fiche_nominale(r, fenetre_immeubles_mois=0 if cas == "desactive" else 60)
    texte = fiche_mod.resume(fiche, tmp_path / "f.json")
    assert _ligne(texte, "Immeubles :") == attendu
    assert len(texte.splitlines()) == 14  # ancien attendu : 11


def test_resume_cadastre_parcelle_la_plus_proche_dit_la_methode_et_contenance_nd(tmp_path):
    fiche, _ = fiche_nominale(_routeur_cas_cle_bien("point_hors_parcelle"))
    ligne = _ligne(fiche_mod.resume(fiche, tmp_path / "f.json"), "Cadastre :")
    assert ligne == (f"Cadastre : parcelle {INSEE}000AB0007 (contenance n/d, parcelle la plus proche du point "
                     f"(point hors parcelle), à confirmer)")


@pytest.mark.parametrize("cas", ["cadastre_en_panne", "geocodage_en_echec"])
def test_resume_cadastre_absent_dit_nd(tmp_path, cas):
    r = routeur_nominal()
    if cas == "cadastre_en_panne":
        r.route(MOTIF_CADASTRE, rep_statut(500))
    else:
        r.route(MOTIF_GEOCODAGE, rep_json(fx("geocodage_vide.json")))
    fiche, _ = fiche_nominale(r)
    texte = fiche_mod.resume(fiche, tmp_path / "f.json")
    assert _ligne(texte, "Cadastre :") == "Cadastre : n/d"
    assert len(texte.splitlines()) == 14  # ancien attendu : 11


def test_main_cadastre_en_panne_code_3_json_ecrit_et_bloc_nomme_sur_stderr(script, tmp_path, capsys):
    r = routeur_nominal()
    r.route(MOTIF_CADASTRE, rep_statut(500))
    code, fiche = _lancer(script, tmp_path, r)
    assert code == 3 and fiche["cadastre"] is None and fiche["cle_bien"]["parcelle"] is None
    sortie = capsys.readouterr()
    assert [ligne.split(" : ")[0] for ligne in sortie.err.splitlines()] == ["cadastre", "batiment"]
    # ancien attendu : ["cadastre"] seul et « Erreurs : 1 (cadastre) » (le bâtiment lit la parcelle du cadastre)
    assert "Cadastre : n/d" in sortie.out and "Erreurs : 2 (cadastre, batiment)" in sortie.out


# ===========================================================================
# - étape 5 : mode `--point`, adresses candidates d'une annonce sans adresse
# ===========================================================================

POINT_LAT, POINT_LON = 47.300417, 1.700583
# Valeurs FICTIVES : premier candidat BAN du point, et DPE F de 130 m2 voisin.
LABEL_BOURGEX = "3 Rue de l'Exemple 99200 Bourg-Exemple"
ID_BAN_BOURGEX = "99002_0007_00003"
LABEL_DPE_BOURGEX = "14 Allée des Cerisiers 99200 Bourg-Exemple"
ID_DPE_BOURGEX = "99002_0004_00014"
INSEE_BOURGEX = "99002"
CLES_POINT = ("genere_le", "point", "parametres", "commune", "candidats_ban", "candidats_dpe", "sources", "erreurs",
              "alertes")
CHAMPS_CANDIDAT_BAN = {"label", "identifiant_ban", "type", "distance_m", "postcode", "citycode"}
CHAMPS_CANDIDAT_DPE = {"numero_dpe", "adresse_ban", "identifiant_ban", "date_etablissement_dpe", "etiquette_dpe",
                       "etiquette_ges", "surface_habitable_logement", "type_batiment", "periode_construction",
                       "distance_m", "doublons"}


def feature_bourgex(label: str, id_ban: str, distance: float | None, *, type_: str = "housenumber") -> dict:
    return feature_ban(label, id_ban, postcode="99200", citycode=INSEE_BOURGEX, city="Bourg-Exemple",
                       type_=type_, distance=distance)


def candidats_bourgex() -> dict:
    return reponse_ban(
        feature_bourgex(LABEL_BOURGEX, ID_BAN_BOURGEX, 17),
        feature_bourgex("Rue de l'Exemple 99200 Bourg-Exemple", "99002_0007", 23, type_="street"),
        feature_bourgex("1 Rue de l'Exemple 99200 Bourg-Exemple", "99002_0007_00001", 26),
        feature_bourgex("9 Rue des Essais 99200 Bourg-Exemple", "99002_0009_00009", 32),
        feature_bourgex("4 Rue des Essais 99200 Bourg-Exemple", "99002_0009_00004", 38),
    )


def decale(nord_m: float = 0.0, est_m: float = 0.0) -> str:
    """`_geopoint` ("lat,lon", WGS84) d'un point à `nord_m` mètres au nord et `est_m` à l'est du point de l'annonce."""
    lat = POINT_LAT + nord_m / M_PAR_DEGRE
    lon = POINT_LON + est_m / (M_PAR_DEGRE * math.cos(math.radians(POINT_LAT)))
    return f"{lat:.6f},{lon:.6f}"


def ligne_dpe_point(numero: str, id_ban: str | None, *, nord_m: float = 0.0, est_m: float = 0.0,
                    etiquette: str = "F", surface: Any = 130, date: str = "2023-05-12", insee: str = INSEE_BOURGEX,
                    adresse: str = LABEL_DPE_BOURGEX) -> dict:
    return {"numero_dpe": numero, "adresse_ban": adresse, "identifiant_ban": id_ban,
            "date_etablissement_dpe": date, "etiquette_dpe": etiquette, "etiquette_ges": "D",
            "surface_habitable_logement": surface, "type_batiment": "maison", "periode_construction": "avant 1948",
            "code_insee_ban": insee, "_geopoint": decale(nord_m, est_m), "_score": None}


def reponse_dpe_point(*lignes: dict, total: int | None = None) -> dict:
    return {"total": len(lignes) if total is None else total, "results": list(lignes)}


def dpe_bourgex() -> dict:
    return reponse_dpe_point(ligne_dpe_point("2377E3174556J", ID_DPE_BOURGEX, nord_m=61, date="2023-09-22"))


def routeur_point(inverse: Any = None, dpe_reponse: Any = None) -> Routeur:
    r = Routeur()
    r.route(MOTIF_INVERSE, rep_json(candidats_bourgex() if inverse is None else inverse))
    r.route(MOTIF_DPE, rep_json(dpe_bourgex() if dpe_reponse is None else dpe_reponse))
    return r


def chercher_point(r: Routeur, **kw: Any) -> dict:
    return adresse.rechercher(POINT_LAT, POINT_LON, client=r.client(), maintenant=MAINTENANT, sleep=r.sleep, **kw)


# --- candidats BAN (géocodage inverse) ----------------------------------------------------

def test_point_constantes_du_contrat():
    assert adresse.TOLERANCE_SURFACE == 0.10
    assert adresse.NB_CANDIDATS_DPE == 10
    assert adresse.NB_CANDIDATS_BAN == geocodage.NB_CANDIDATS == 5
    assert adresse.DPE_LIGNES_MAX == dpe.DPE_MAX_LIGNES == 200


def test_point_candidats_ban_requete_champs_et_commune_du_premier_candidat():
    r = routeur_point()
    res = chercher_point(r)
    assert tuple(res) == CLES_POINT
    assert res["genere_le"] == GENERE_LE and res["point"] == {"lat": POINT_LAT, "lon": POINT_LON}
    assert [a.cle for a in r.appels] == [MOTIF_INVERSE]  # sans surface : aucun appel DPE
    assert r.appels[0].params == {"lon": str(POINT_LON), "lat": str(POINT_LAT), "index": "address", "limit": "5"}
    assert [c["identifiant_ban"] for c in res["candidats_ban"]] == [
        ID_BAN_BOURGEX, "99002_0007", "99002_0007_00001", "99002_0009_00009", "99002_0009_00004"]
    assert all(set(c) == CHAMPS_CANDIDAT_BAN for c in res["candidats_ban"])
    assert res["candidats_ban"][0] == {"label": LABEL_BOURGEX, "identifiant_ban": ID_BAN_BOURGEX,
                                      "type": "housenumber", "distance_m": 17, "postcode": "99200",
                                      "citycode": INSEE_BOURGEX}
    assert res["candidats_ban"][1]["type"] == "street"
    assert res["commune"] == {"insee": INSEE_BOURGEX, "nom": "Bourg-Exemple", "code_postal": "99200"}
    assert res["candidats_dpe"] is None and res["erreurs"] == [] and res["alertes"] == []
    assert adresse.code_sortie(res) == 0
    json.dumps(res, ensure_ascii=False)


def test_point_distance_non_entiere_arrondie_et_absente_rendue_null_les_candidats_gardent_l_ordre_de_la_reponse():
    inverse = reponse_ban(feature_bourgex(LABEL_BOURGEX, ID_BAN_BOURGEX, 16.6),
                          feature_bourgex("1 Rue de l'Exemple 99200 Bourg-Exemple", "99002_0007_00001", None))
    res = chercher_point(routeur_point(inverse))
    assert [c["distance_m"] for c in res["candidats_ban"]] == [17, None]


def test_point_candidats_ban_dans_l_ordre_de_l_api_meme_si_les_distances_ne_croissent_pas():
    """L'API classe par distance : son ordre est gardé, la commune est celle du PREMIER candidat rendu."""
    inverse = reponse_ban(
        feature_ban("1 Rue de Test 99100 Exempleville", "99001_0001_00001", citycode=INSEE, city="Exempleville", distance=40),
        feature_bourgex(LABEL_BOURGEX, ID_BAN_BOURGEX, 17))
    res = chercher_point(routeur_point(inverse))
    assert [c["identifiant_ban"] for c in res["candidats_ban"]] == ["99001_0001_00001", ID_BAN_BOURGEX]
    assert res["commune"] == {"insee": INSEE, "nom": "Exempleville", "code_postal": "99100"}


def test_point_cinq_candidats_ban_au_plus_meme_si_l_api_ignore_limit():
    inverse = reponse_ban(*(feature_bourgex(f"{k} Rue de l'Exemple 99200 Bourg-Exemple", f"99002_0007_{k:05d}", k)
                            for k in range(1, 8)))
    res = chercher_point(routeur_point(inverse))
    assert [c["identifiant_ban"] for c in res["candidats_ban"]] == [f"99002_0007_{k:05d}" for k in range(1, 6)]


def test_point_geocodage_inverse_en_panne_code_2_json_complet_sans_candidats():
    r = routeur_point()
    r.route(MOTIF_INVERSE, rep_statut(500))
    res = chercher_point(r, surface=130)
    assert tuple(res) == CLES_POINT
    assert res["candidats_ban"] is None and res["commune"] is None and res["candidats_dpe"] is None
    assert [e["bloc"] for e in res["erreurs"]] == ["geocodage_inverse"] and "500" in res["erreurs"][0]["message"]
    assert adresse.code_sortie(res) == 2
    assert not r.appels_vers(MOTIF_DPE)  # sans commune connue, pas de recherche DPE (et pas d'erreur de plus)
    assert [a["bloc"] for a in res["alertes"]] == ["dpe"] and "recherche DPE non faite" in res["alertes"][0]["message"]
    assert r.attentes == [1, 2]


def test_point_aucune_adresse_proche_est_un_echec_du_geocodage_inverse_code_2():
    res = chercher_point(routeur_point(reponse_ban()))
    assert res["candidats_ban"] is None and adresse.code_sortie(res) == 2
    assert "aucune adresse" in res["erreurs"][0]["message"] and str(POINT_LAT) in res["erreurs"][0]["message"]


@pytest.mark.parametrize("modifier", [
    pytest.param(lambda p: p.pop("label"), id="sans_label"),
    pytest.param(lambda p: p.pop("id"), id="sans_identifiant"),
    pytest.param(lambda p: p.pop("citycode"), id="sans_citycode"),
    pytest.param(lambda p: p.update(distance="17"), id="distance_chaine"),
])
def test_point_forme_inattendue_d_un_candidat_est_un_echec_du_geocodage_inverse(modifier):
    feature = feature_bourgex(LABEL_BOURGEX, ID_BAN_BOURGEX, 17)
    modifier(feature["properties"])
    res = chercher_point(routeur_point(reponse_ban(feature)))
    assert res["candidats_ban"] is None and adresse.code_sortie(res) == 2
    assert "forme inattendue" in res["erreurs"][0]["message"]


def test_point_code_postal_different_du_premier_candidat_une_alerte_concordant_aucune():
    res = chercher_point(routeur_point(), code_postal="99100")
    assert len(res["alertes"]) == 1 and res["alertes"][0]["bloc"] == "geocodage_inverse"
    assert "99100" in res["alertes"][0]["message"] and "99200" in res["alertes"][0]["message"]
    assert chercher_point(routeur_point(), code_postal="99200")["alertes"] == []
    assert chercher_point(routeur_point())["alertes"] == []  # code postal non donné : rien à comparer


# --- candidats DPE (ADEME) ----------------------------------------------------------------

def test_point_dpe_requete_qs_commune_surface_etiquette_size_et_select():
    r = routeur_point()
    chercher_point(r, surface=130, etiquette="F", code_postal="99200")
    appel = r.appels_vers(MOTIF_DPE)[0]
    assert appel.params["qs"] == 'code_insee_ban:"99002" AND surface_habitable_logement:[117 TO 143] AND etiquette_dpe:"F"'
    assert appel.params["size"] == "200"
    assert set(appel.params["select"].split(",")) == {
        "numero_dpe", "adresse_ban", "identifiant_ban", "date_etablissement_dpe", "etiquette_dpe", "etiquette_ges",
        "surface_habitable_logement", "type_batiment", "periode_construction", "code_insee_ban", "_geopoint"}
    assert len(r.appels_vers(MOTIF_DPE)) == 1


@pytest.mark.parametrize("options, qs", [
    pytest.param({"surface": 130}, 'code_insee_ban:"99002" AND surface_habitable_logement:[117 TO 143]', id="surface"),
    pytest.param({"surface": 130, "etiquette": "F", "date_dpe": "2023-05-12"},
                 'code_insee_ban:"99002" AND surface_habitable_logement:[117 TO 143] AND etiquette_dpe:"F" '
                 'AND date_etablissement_dpe:"2023-05-12"', id="surface_etiquette_date"),
    pytest.param({"surface": 130, "date_dpe": "2023-05-12"},
                 'code_insee_ban:"99002" AND surface_habitable_logement:[117 TO 143] '
                 'AND date_etablissement_dpe:"2023-05-12"', id="surface_date"),
    pytest.param({"surface": 130, "insee": "99004"}, 'code_insee_ban:"99004" AND surface_habitable_logement:[117 TO 143]',
                 id="insee_force"),
])
def test_point_dpe_qs_selon_les_options_guillemets_autour_de_chaque_valeur(options, qs):
    r = routeur_point(dpe_reponse=reponse_dpe_point(
        ligne_dpe_point("2377E3174556J", ID_DPE_BOURGEX, insee=options.get("insee", INSEE_BOURGEX))))
    chercher_point(r, **options)
    assert r.appels_vers(MOTIF_DPE)[0].params["qs"] == qs


@pytest.mark.parametrize("surface, bas, haut", [
    pytest.param(130, 117, 143, id="entiere"),
    pytest.param(100, 90, 110, id="bruit_flottant_100_fois_1_1_ne_donne_pas_111"),  # nouveau cas
    pytest.param(40, 36, 44, id="bornes_exactes"),
    pytest.param(42, 37, 47, id="cas_valide_38_contre_42"),  # ancien attendu : 38, 46 (arrondi au plus proche)
    pytest.param(25, 22, 28, id="borne_basse_22_5_vers_le_bas_borne_haute_27_5_vers_le_haut"),
    # ancien attendu : 23, 28 ; ancien id : demi_vers_le_haut_22_5_et_27_5
    pytest.param(35, 31, 39, id="borne_basse_31_5_vers_le_bas_borne_haute_38_5_vers_le_haut"),
    # ancien attendu : 32, 39 ; ancien id : demi_vers_le_haut_31_5_et_38_5
    pytest.param(41.6, 37, 46, id="surface_decimale"),
    pytest.param(39.5, 35, 44, id="borne_basse_35_55_vers_le_bas"),  # nouveau cas : ancien attendu 36, 44
])
def test_point_bornes_de_surface_a_plus_ou_moins_10_pour_cent_arrondies_au_m2_incluses(surface, bas, haut):
    """Borne basse arrondie vers le bas, borne haute vers le haut : un DPE dans les
    10 % n'est plus écarté par l'arrondi. Ancien attendu : les deux bornes arrondies au plus proche."""
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "id1", surface=bas),
                                                    ligne_dpe_point("n2", "id2", surface=haut)))
    res = chercher_point(r, surface=surface)
    assert f"surface_habitable_logement:[{bas} TO {haut}]" in r.appels_vers(MOTIF_DPE)[0].params["qs"]
    assert res["parametres"]["dpe"]["bornes_surface_m2"] == [bas, haut]
    assert res["erreurs"] == [] and len(res["candidats_dpe"]) == 2  # les deux bornes sont incluses


def test_point_dpe_lignes_champs_distance_haversine_dans_l_ordre_lat_lon():
    """Un DPE à 250 m à l'EST : une latitude et une longitude inversées donneraient des milliers de kilomètres."""
    lignes = (ligne_dpe_point("n-est", "idE", est_m=250), ligne_dpe_point("n-nord", "idN", nord_m=100),
              ligne_dpe_point("n-sud", "idS", nord_m=-400))
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130)
    candidats = res["candidats_dpe"]
    assert [c["numero_dpe"] for c in candidats] == ["n-nord", "n-est", "n-sud"]  # triés par distance
    assert [c["distance_m"] for c in candidats] == [100, 250, 400]
    assert all(set(c) == CHAMPS_CANDIDAT_DPE for c in candidats)
    assert candidats[0] == {
        "numero_dpe": "n-nord", "adresse_ban": LABEL_DPE_BOURGEX, "identifiant_ban": "idN",
        "date_etablissement_dpe": "2023-05-12", "etiquette_dpe": "F", "etiquette_ges": "D",
        "surface_habitable_logement": 130, "type_batiment": "maison", "periode_construction": "avant 1948",
        "distance_m": 100, "doublons": 0}


def test_point_dpe_dedoublonne_par_identifiant_ban_garde_le_plus_recent_et_dit_les_doublons():
    lignes = (
        ligne_dpe_point("n1", "idA", nord_m=50, date="2020-01-01"),
        ligne_dpe_point("n2", "idA", nord_m=50, date="2023-05-12"),
        ligne_dpe_point("n3", "idA", nord_m=50, date="2023-05-12"),  # même date : le numéro le plus grand
        ligne_dpe_point("n4", "idB", nord_m=20),
    )
    for ordre in (lignes, lignes[::-1]):  # indépendant de l'ordre de la réponse
        res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*ordre)), surface=130)
        assert [(c["identifiant_ban"], c["numero_dpe"], c["doublons"]) for c in res["candidats_dpe"]] == [
            ("idB", "n4", 0), ("idA", "n3", 2)]
    assert res["parametres"]["dpe"]["lignes_lues"] == 4 and res["parametres"]["dpe"]["adresses_distinctes"] == 2


def test_point_dpe_deux_adresses_differentes_ne_sont_pas_dedoublonnees():
    lignes = (ligne_dpe_point("n1", "idA", nord_m=10), ligne_dpe_point("n2", "idB", nord_m=20))
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130)
    assert len(res["candidats_dpe"]) == 2 and [c["doublons"] for c in res["candidats_dpe"]] == [0, 0]


def test_point_dpe_sans_identifiant_ban_gardee_sans_dedoublonnage():
    lignes = (ligne_dpe_point("n1", None, nord_m=10), ligne_dpe_point("n2", None, nord_m=20))
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130)
    assert [c["numero_dpe"] for c in res["candidats_dpe"]] == ["n1", "n2"]
    assert all(c["identifiant_ban"] is None and c["doublons"] == 0 for c in res["candidats_dpe"])


@pytest.mark.parametrize("geopoint", [None, "", "abc", "47.30", "47.30,1.70,1", "91.0,2.7", "47.30,181.0"],
                         ids=["absent", "vide", "texte", "une_valeur", "trois_valeurs", "latitude_hors_plage",
                              "longitude_hors_plage"])
def test_point_dpe_sans_position_lisible_distance_null_classee_en_dernier_jamais_ecartee(geopoint):
    sans_position = ligne_dpe_point("n-sans", "idZ")
    if geopoint is None:
        del sans_position["_geopoint"]
    else:
        sans_position["_geopoint"] = geopoint
    lignes = (sans_position, ligne_dpe_point("n-loin", "idL", nord_m=900), ligne_dpe_point("n-pres", "idP", nord_m=5))
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130)
    assert [(c["numero_dpe"], c["distance_m"]) for c in res["candidats_dpe"]] == [
        ("n-pres", 5), ("n-loin", 900), ("n-sans", None)]


@pytest.mark.parametrize("nombre, alerte", [(10, False), (11, True), (3, False)])
def test_point_dpe_dix_adresses_au_plus_les_plus_proches_et_une_alerte_au_dela(nombre, alerte):
    lignes = [ligne_dpe_point(f"n{k:02d}", f"id{k:02d}", nord_m=10 * (k + 1)) for k in range(nombre)]
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*reversed(lignes))), surface=130)
    assert [c["numero_dpe"] for c in res["candidats_dpe"]] == [f"n{k:02d}" for k in range(min(nombre, 10))]
    alertes = [a for a in res["alertes"] if a["bloc"] == "dpe"]
    assert bool(alertes) is alerte
    if alerte:
        assert "11 adresses" in alertes[0]["message"] and "10 plus proches" in alertes[0]["message"]


@pytest.mark.parametrize("total, lues, fragment", [
    pytest.param(250, 200, "250 DPE", id="au_dela_du_plafond_de_200"),
    pytest.param(5, 3, "liste incomplète", id="moins_de_lignes_que_le_total"),
    pytest.param(3, 3, None, id="total_egal_aux_lignes"),
])
def test_point_dpe_total_superieur_aux_lignes_lues_alerte_la_liste_n_est_jamais_tronquee_en_silence(total, lues,
                                                                                                      fragment):
    lignes = [ligne_dpe_point(f"n{k:03d}", f"id{k:03d}", nord_m=k + 1) for k in range(lues)]
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes, total=total)), surface=130)
    alertes = [a for a in res["alertes"] if a["bloc"] == "dpe" and "adresses" not in a["message"]]
    if fragment is None:
        assert alertes == []
    else:
        assert len(alertes) == 1 and fragment in alertes[0]["message"]
        assert res["parametres"]["dpe"]["total"] == total and res["parametres"]["dpe"]["lignes_lues"] == lues
    assert adresse.code_sortie(res) == 0  # une alerte ne change pas le code


def test_point_dpe_l_api_ignore_size_et_renvoie_250_lignes_le_plafond_de_200_tient_et_alerte():
    lignes = [ligne_dpe_point(f"n{k:03d}", f"id{k:03d}", nord_m=k + 1) for k in range(250)]
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130)
    assert res["parametres"]["dpe"]["lignes_lues"] == 200 and res["parametres"]["dpe"]["total"] == 250
    assert res["parametres"]["dpe"]["adresses_distinctes"] == 200
    assert [c["numero_dpe"] for c in res["candidats_dpe"]] == [f"n{k:03d}" for k in range(10)]
    messages = [a["message"] for a in res["alertes"] if a["bloc"] == "dpe"]
    assert any("250 DPE" in m and "plafond 200" in m and "tronquée" in m for m in messages)
    assert any("les 10 plus proches parmi les 200 DPE lus" in m for m in messages)  # les plus proches PARMI les lus


def test_point_surface_demesuree_donne_une_erreur_dpe_pas_une_exception():
    """Les bornes ±10 % d'une surface de 1,7e308 débordent : l'erreur est rendue, le JSON reste complet."""
    res = chercher_point(routeur_point(), surface=1.7e308)
    assert res["candidats_dpe"] is None and res["parametres"]["dpe"] is None
    assert [e["bloc"] for e in res["erreurs"]] == ["dpe"] and "OverflowError" in res["erreurs"][0]["message"]
    assert len(res["candidats_ban"]) == 5 and adresse.code_sortie(res) == 3


@pytest.mark.parametrize("ligne_etrangere, options", [
    pytest.param({"insee": "99999"}, {}, id="autre_commune"),
    pytest.param({"surface": 200}, {}, id="surface_hors_bornes"),
    pytest.param({"surface": None}, {}, id="surface_absente"),
    pytest.param({"etiquette": "B"}, {"etiquette": "F"}, id="autre_etiquette"),
    pytest.param({"date": "2020-01-01"}, {"date_dpe": "2023-05-12"}, id="autre_date"),
])
def test_point_dpe_filtre_ignore_par_l_api_une_ligne_hors_filtre_est_une_erreur_code_3(ligne_etrangere, options):
    """Même garde que `dpe.py` : toutes les lignes sont recontrôlées contre les filtres demandés."""
    bonne = ligne_dpe_point("n-bonne", "idB", nord_m=10)
    mauvaise = ligne_dpe_point("n-mauvaise", "idM", nord_m=20, **ligne_etrangere)
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(bonne, mauvaise)), surface=130, **options)
    assert res["candidats_dpe"] is None
    assert [e["bloc"] for e in res["erreurs"]] == ["dpe"] and "filtre" in res["erreurs"][0]["message"]
    assert adresse.code_sortie(res) == 3 and res["candidats_ban"] is not None


def test_point_dpe_en_panne_code_3_les_candidats_ban_restent():
    r = routeur_point()
    r.route(MOTIF_DPE, rep_statut(500))
    res = chercher_point(r, surface=130)
    assert res["candidats_dpe"] is None and len(res["candidats_ban"]) == 5
    assert [e["bloc"] for e in res["erreurs"]] == ["dpe"] and adresse.code_sortie(res) == 3
    assert not [s for s in res["sources"] if s["bloc"] == "dpe"]


@pytest.mark.parametrize("payload", [{}, {"total": "5", "results": []}, {"total": 1, "results": "x"},
                                     {"total": 1, "results": ["x"]}, []],
                         ids=["sans_total", "total_chaine", "results_non_liste", "ligne_non_objet", "racine_liste"])
def test_point_dpe_forme_inattendue_erreur_nommee_code_3(payload):
    res = chercher_point(routeur_point(dpe_reponse=payload), surface=130)
    assert res["candidats_dpe"] is None and "forme inattendue" in res["erreurs"][0]["message"]
    assert adresse.code_sortie(res) == 3


def test_point_dpe_aucun_resultat_est_une_liste_vide_valide_pas_une_erreur():
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point()), surface=130)
    assert res["candidats_dpe"] == [] and res["erreurs"] == [] and adresse.code_sortie(res) == 0


def test_point_insee_force_la_commune_des_dpe_et_une_alerte_dit_l_ecart_avec_le_premier_candidat():
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", insee="99004")))
    res = chercher_point(r, surface=130, insee="99004")
    assert r.appels_vers(MOTIF_DPE)[0].params["qs"].startswith('code_insee_ban:"99004"')
    assert res["commune"]["insee"] == INSEE_BOURGEX  # `commune` reste celle du premier candidat BAN
    assert [a["bloc"] for a in res["alertes"]] == ["dpe"]
    assert "99004" in res["alertes"][0]["message"] and INSEE_BOURGEX in res["alertes"][0]["message"]
    meme = chercher_point(routeur_point(), surface=130, insee=INSEE_BOURGEX)
    assert meme["alertes"] == []  # même commune que le premier candidat : rien à dire


def test_point_geocodage_inverse_en_panne_mais_insee_donne_les_dpe_sont_cherches_le_code_reste_2():
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", nord_m=10)))
    r.route(MOTIF_INVERSE, rep_statut(500))
    res = chercher_point(r, surface=130, insee=INSEE_BOURGEX)
    assert res["candidats_ban"] is None and len(res["candidats_dpe"]) == 1
    assert adresse.code_sortie(res) == 2


def test_point_sources_datees_et_licences_du_geocodage_inverse_et_des_dpe():
    res = chercher_point(routeur_point(), surface=130)
    assert res["sources"] == [
        {"bloc": "geocodage_inverse", "url": geocodage.URL_REVERSE, "date_extraction": "2026-10-03",
         "licence": geocodage.LICENCE, "millesime": None},
        {"bloc": "dpe", "url": dpe.URL, "date_extraction": "2026-10-03", "licence": dpe.LICENCE, "millesime": None},
    ]


def test_point_parametres_disent_la_demande_les_seuils_de_methode_et_la_recherche_dpe():
    res = chercher_point(routeur_point(), surface=130, etiquette="F", date_dpe="2023-09-22", code_postal="99200")
    assert res["parametres"] == {
        "demande": {"surface_m2": 130, "etiquette": "F", "date_dpe": "2023-09-22", "code_postal": "99200",
                    "insee": None},
        "methode": {"candidats_ban": 5, "tolerance_surface": 0.1, "candidats_dpe": 10, "dpe_lignes_max": 200},
        "dpe": {"qs": 'code_insee_ban:"99002" AND surface_habitable_logement:[117 TO 143] AND etiquette_dpe:"F" '
                      'AND date_etablissement_dpe:"2023-09-22"',
                "bornes_surface_m2": [117, 143], "total": 1, "lignes_lues": 1, "adresses_distinctes": 1},
    }
    assert chercher_point(routeur_point())["parametres"]["dpe"] is None  # sans surface : pas de recherche DPE


def test_point_le_cas_valide_38_contre_42_m2_est_retrouve_a_plus_ou_moins_10_pour_cent():
    """La surface du DPE contredisait l'annonce (l'écart dépassait 5 %) : à ±5 % il était manqué."""
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", surface=38, etiquette="E")))
    res = chercher_point(r, surface=42, etiquette="E")
    assert [c["surface_habitable_logement"] for c in res["candidats_dpe"]] == [38]
    assert res["parametres"]["dpe"]["bornes_surface_m2"] == [37, 47]  # ancien attendu : [38, 46] (au plus proche)


def test_point_dpe_de_35_6_m2_dans_les_10_pour_cent_de_39_5_m2_devient_candidat():
    """39,5 x 0,9 = 35,55 : le DPE de 35,6 m2 est dans les 10 %. L'ancienne borne basse (arrondi au plus proche : 36) le
    manquait ; la borne basse arrondie vers le bas (35) le retient."""
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", surface=35.6, etiquette="E")))
    res = chercher_point(r, surface=39.5, etiquette="E")
    assert res["parametres"]["dpe"]["bornes_surface_m2"] == [35, 44]  # ancien attendu : [36, 44]
    assert "surface_habitable_logement:[35 TO 44]" in r.appels_vers(MOTIF_DPE)[0].params["qs"]
    assert [c["surface_habitable_logement"] for c in res["candidats_dpe"]] == [35.6] and res["erreurs"] == []


def test_point_dpe_de_34_9_m2_hors_des_bornes_reste_refuse_par_la_garde_filtre_ignore():
    """Le refus du pendant : 34,9 m2 est sous la borne basse élargie (35) ; une API qui le renverrait quand même ignore
    son filtre, et la garde le dit (aucun candidat fabriqué)."""
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", surface=34.9, etiquette="E")))
    res = chercher_point(r, surface=39.5, etiquette="E")
    assert res["candidats_dpe"] is None and "filtre" in res["erreurs"][0]["message"]


def test_point_le_cas_valide_38_contre_42_m2_est_manque_a_plus_ou_moins_5_pour_cent(monkeypatch):
    """Pendant du test précédent, par le code : à ±5 % la requête serait [39 TO 45] (ancien attendu : [40 TO 44], avant
    l'arrondi vers l'extérieur) ; ce DPE de 38 m2 est hors fourchette et la garde « filtre ignoré » le dit. C'est la
    tolérance de `adresse`, et elle seule, qui le retrouve."""
    monkeypatch.setattr(adresse, "TOLERANCE_SURFACE", 0.05)
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", surface=38, etiquette="E")))
    res = chercher_point(r, surface=42, etiquette="E")
    assert r.appels_vers(MOTIF_DPE)[0].params["qs"].count("[39 TO 45]") == 1  # ancien attendu : "[40 TO 44]"
    assert res["candidats_dpe"] is None and "filtre" in res["erreurs"][0]["message"]


# --- le résumé et le code de sortie ----------------------------------------------------------

def test_point_resume_une_ligne_par_candidat_ban_et_par_candidat_dpe(tmp_path):
    lignes = (ligne_dpe_point("n1", ID_DPE_BOURGEX, nord_m=61), ligne_dpe_point("n2", "idB", nord_m=120, surface=125.5))
    res = chercher_point(routeur_point(dpe_reponse=reponse_dpe_point(*lignes)), surface=130, etiquette="F")
    texte = adresse.resume(res, tmp_path / "point.json")
    assert texte.splitlines()[-1] == f"Fiche écrite : {tmp_path / 'point.json'}"
    ligne_ban = [ligne for ligne in texte.splitlines() if ID_BAN_BOURGEX in ligne and "housenumber" in ligne]
    assert len(ligne_ban) == 1 and LABEL_BOURGEX in ligne_ban[0] and "17 m" in ligne_ban[0]
    assert sum(ligne.startswith("BAN ") for ligne in texte.splitlines()) == 5
    assert sum(ligne.startswith("DPE ") and "m²" in ligne for ligne in texte.splitlines()) == 2
    assert f"DPE 1 : {LABEL_DPE_BOURGEX} : F, 130 m², 2023-05-12, 61 m ({ID_DPE_BOURGEX})" in texte
    assert "DPE 2 : " in texte and ": F, 125,5 m²," in texte  # la virgule décimale, comme le résumé de la fiche
    assert "surface 130 m² (117 à 143 m²), étiquette F : 2 DPE lus sur 2, 2 adresses, 2 listées" in texte
    assert "Erreurs : aucune" in texte and "Alertes : aucune" in texte
    assert all(ligne.strip() for ligne in texte.splitlines())


def test_point_resume_dit_les_absences_sans_faux_zero(tmp_path):
    r = routeur_point()
    r.route(MOTIF_INVERSE, rep_statut(500))
    texte = adresse.resume(chercher_point(r, surface=130), tmp_path / "p.json")
    assert "Erreurs : 1 (geocodage_inverse)" in texte and "BAN : n/d" in texte
    sans_surface = adresse.resume(chercher_point(routeur_point()), tmp_path / "p.json")
    assert "DPE : non demandé" in sans_surface


# --- le script : `--point` ----------------------------------------------------------------------

def lancer_point(script, tmp_path, r: Routeur, *options: str, nom: str = "point.json") -> tuple[int, dict]:
    sortie = tmp_path / nom
    code = script.main(["--point", f"{POINT_LAT},{POINT_LON}", *options, "--out", str(sortie)], client=r.client(),
                       maintenant=MAINTENANT, sleep=r.sleep)
    return code, json.loads(sortie.read_text(encoding="utf-8"))


def test_main_point_ecrit_le_json_imprime_une_ligne_par_candidat_code_0_stderr_vide(script, tmp_path, capsys):
    r = routeur_point()
    code, res = lancer_point(script, tmp_path, r, "--surface", "130", "--etiquette", "F", "--code-postal", "99200")
    assert code == 0 and tuple(res) == CLES_POINT
    assert any(c["identifiant_ban"] == ID_DPE_BOURGEX and c["etiquette_dpe"] == "F"
               and c["surface_habitable_logement"] == 130 for c in res["candidats_dpe"])
    assert res["candidats_ban"][0]["label"] == LABEL_BOURGEX and res["candidats_ban"][0]["distance_m"] == 17
    sortie = capsys.readouterr()
    assert sortie.err == ""
    assert sum(ligne.startswith("BAN ") for ligne in sortie.out.splitlines()) == 5
    assert str(tmp_path / "point.json") in sortie.out
    brut = (tmp_path / "point.json").read_text(encoding="utf-8")
    assert brut.startswith('{\n  "genere_le"') and brut.endswith("\n")  # indent=2, comme la fiche


def test_main_point_n_appelle_que_le_geocodage_inverse_et_l_ademe_ni_dvf_ni_cadastre_ni_la_recherche(script,
                                                                                                tmp_path):
    r = routeur_point()
    lancer_point(script, tmp_path, r, "--surface", "130")
    assert {a.cle for a in r.appels} == {MOTIF_INVERSE, MOTIF_DPE}
    assert all(a.entetes["user-agent"] == "immo-locatif-opendata/1.0" for a in r.appels)


def test_main_point_accepte_la_surface_a_virgule_et_l_etiquette_en_minuscule(script, tmp_path):
    r = routeur_point(dpe_reponse=reponse_dpe_point(ligne_dpe_point("n1", "idA", surface=41, etiquette="E")))
    code, res = lancer_point(script, tmp_path, r, "--surface", "41,6", "--etiquette", "e")
    assert code == 0
    assert res["parametres"]["demande"]["surface_m2"] == 41.6 and res["parametres"]["demande"]["etiquette"] == "E"
    assert r.appels_vers(MOTIF_DPE)[0].params["qs"].endswith('AND etiquette_dpe:"E"')


def test_main_point_geocodage_inverse_en_panne_code_2_json_ecrit_et_stderr_vide(script, tmp_path, capsys):
    r = routeur_point()
    r.route(MOTIF_INVERSE, rep_statut(500))
    code, res = lancer_point(script, tmp_path, r, "--surface", "130")
    assert code == 2 and res["candidats_ban"] is None and res["erreurs"][0]["bloc"] == "geocodage_inverse"
    sortie = capsys.readouterr()
    assert sortie.err == "" and "Erreurs : 1 (geocodage_inverse)" in sortie.out


def test_main_point_dpe_en_panne_code_3_une_ligne_par_erreur_sur_stderr(script, tmp_path, capsys):
    r = routeur_point()
    r.route(MOTIF_DPE, rep_statut(500))
    code, res = lancer_point(script, tmp_path, r, "--surface", "130")
    assert code == 3 and len(res["candidats_ban"]) == 5 and res["candidats_dpe"] is None
    lignes = capsys.readouterr().err.splitlines()
    assert len(lignes) == 1 and lignes[0].startswith("dpe : ") and "500" in lignes[0]


def test_main_point_une_alerte_seule_garde_le_code_0_et_stderr_vide(script, tmp_path, capsys):
    code, res = lancer_point(script, tmp_path, routeur_point(), "--code-postal", "99100")
    assert code == 0 and len(res["alertes"]) == 1
    sortie = capsys.readouterr()
    assert sortie.err == "" and "Alertes : geocodage_inverse" in sortie.out


def test_main_point_sans_client_injecte_cree_un_client_http_avec_user_agent_et_le_ferme(script, tmp_path,
                                                                                        monkeypatch):
    r = routeur_point()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, requete: r.repondre_a(requete))
    crees: list[httpx.Client] = []
    init_origine = httpx.Client.__init__

    def init_espion(self, *args, **kwargs):
        init_origine(self, *args, **kwargs)
        crees.append(self)

    monkeypatch.setattr(httpx.Client, "__init__", init_espion)
    code = script.main(["--point", f"{POINT_LAT},{POINT_LON}", "--out", str(tmp_path / "p.json")],
                       maintenant=MAINTENANT, sleep=r.sleep)
    assert code == 0 and r.appels
    assert all(a.entetes["user-agent"] == "immo-locatif-opendata/1.0" for a in r.appels)
    assert len(crees) == 1 and crees[0].is_closed


POINT_OK = ["--point", "47.30,1.70"]


@pytest.mark.parametrize("argv, fragment", [
    pytest.param(["--out", "p.json"], "--adresse --point", id="ni_adresse_ni_point"),
    pytest.param(["--adresse", ADRESSE, "--point", "47.30,1.70", "--out", "p.json"], "not allowed with",
                 id="adresse_et_point"),
    pytest.param(POINT_OK, "--out", id="sans_out"),
    pytest.param(["--point", "abc", "--out", "p.json"], "argument --point:", id="point_texte"),
    pytest.param(["--point", "47.30", "--out", "p.json"], "argument --point:", id="point_une_valeur"),
    pytest.param(["--point", "47.30,abc", "--out", "p.json"], "argument --point:", id="point_longitude_texte"),
    pytest.param(["--point", "47.30,1.70,1", "--out", "p.json"], "argument --point:", id="point_trois_valeurs"),
    pytest.param(["--point", "91,1.70", "--out", "p.json"], "argument --point:", id="latitude_hors_plage"),
    pytest.param(["--point", "47.30,181", "--out", "p.json"], "argument --point:", id="longitude_hors_plage"),
    pytest.param(["--point", "nan,1.70", "--out", "p.json"], "argument --point:", id="latitude_nan"),
    pytest.param(["--point", "47.30,inf", "--out", "p.json"], "argument --point:", id="longitude_infinie"),
    pytest.param([*POINT_OK, "--surface", "0", "--out", "p.json"], "argument --surface:", id="surface_nulle"),
    pytest.param([*POINT_OK, "--surface", "-5", "--out", "p.json"], "argument --surface:", id="surface_negative"),
    pytest.param([*POINT_OK, "--surface", "abc", "--out", "p.json"], "argument --surface:", id="surface_texte"),
    pytest.param([*POINT_OK, "--surface", "nan", "--out", "p.json"], "argument --surface:", id="surface_nan"),
    pytest.param([*POINT_OK, "--surface", "40", "--etiquette", "H", "--out", "p.json"], "argument --etiquette:",
                 id="etiquette_hors_a_g"),
    pytest.param([*POINT_OK, "--surface", "40", "--etiquette", "AB", "--out", "p.json"], "argument --etiquette:",
                 id="etiquette_deux_lettres"),
    pytest.param([*POINT_OK, "--surface", "40", "--date-dpe", "2026-13-01", "--out", "p.json"],
                 "argument --date-dpe:", id="date_mois_13"),
    pytest.param([*POINT_OK, "--surface", "40", "--date-dpe", "07/10/2026", "--out", "p.json"],
                 "argument --date-dpe:", id="date_francaise"),
    pytest.param([*POINT_OK, "--surface", "40", "--date-dpe", "20261007", "--out", "p.json"],
                 "argument --date-dpe:", id="date_compacte"),
    pytest.param([*POINT_OK, "--code-postal", "7746", "--out", "p.json"], "argument --code-postal:",
                 id="code_postal_court"),
    pytest.param([*POINT_OK, "--code-postal", "abcde", "--out", "p.json"], "argument --code-postal:",
                 id="code_postal_texte"),
    pytest.param([*POINT_OK, "--insee", "123", "--out", "p.json"], "argument --insee:", id="insee_court"),
    pytest.param([*POINT_OK, "--insee", "7745x", "--out", "p.json"], "argument --insee:", id="insee_lettre"),
    pytest.param(["--adresse", ADRESSE, "--surface", "130", "--out", "p.json"], "ne valent qu'avec --point",
                 id="surface_avec_adresse"),
    pytest.param(["--adresse", ADRESSE, "--insee", "99002", "--out", "p.json"], "ne valent qu'avec --point",
                 id="insee_avec_adresse"),
    pytest.param(["--adresse", ADRESSE, "--code-postal", "99200", "--out", "p.json"], "ne valent qu'avec --point",
                 id="code_postal_avec_adresse"),
    pytest.param([*POINT_OK, "--etiquette", "F", "--out", "p.json"], "requièrent --surface",
                 id="etiquette_sans_surface"),
    pytest.param([*POINT_OK, "--date-dpe", "2023-05-12", "--out", "p.json"], "requièrent --surface",
                 id="date_sans_surface"),
    pytest.param([*POINT_OK, "--insee", "99002", "--out", "p.json"], "requièrent --surface", id="insee_sans_surface"),
    pytest.param([*POINT_OK, "--surface", "1.7e308", "--out", "p.json"], "argument --surface:",
                 id="surface_demesuree"),
    pytest.param([*POINT_OK, "--code-postal", "７７４６０", "--out", "p.json"], "argument --code-postal:",
                 id="code_postal_chiffres_pleine_chasse"),
    pytest.param([*POINT_OK, "--insee", "７７４５８", "--out", "p.json"], "argument --insee:",
                 id="insee_chiffres_pleine_chasse"),
    pytest.param([*POINT_OK, "--surface", "40", "--date-dpe", "２０２３-０５-１２", "--out", "p.json"],
                 "argument --date-dpe:", id="date_chiffres_pleine_chasse"),
])
def test_main_point_arguments_invalides_ou_incoherents_argparse_code_2_aucun_appel(script, capsys, tmp_path, argv,
                                                                                   fragment):
    r = routeur_point()
    argv = [str(tmp_path / "p.json") if a == "p.json" else a for a in argv]  # jamais d'écriture dans le répertoire courant
    with pytest.raises(SystemExit) as exc:
        script.main(argv, client=r.client(), maintenant=MAINTENANT, sleep=r.sleep)
    assert exc.value.code == 2
    assert fragment in capsys.readouterr().err  # refusé pour la bonne raison, pas pour un argument inconnu
    assert r.appels == []  # rien n'est appelé avant la validation des arguments


@pytest.mark.parametrize("insee", ["99002", "2A004", "2B033", "97411"])
def test_main_point_insee_valides_metropole_corse_et_outre_mer(script, tmp_path, insee):
    r = routeur_point(dpe_reponse=reponse_dpe_point())
    code, res = lancer_point(script, tmp_path, r, "--surface", "130", "--insee", insee)
    assert code == 0 and res["parametres"]["demande"]["insee"] == insee
    assert r.appels_vers(MOTIF_DPE)[0].params["qs"].startswith(f'code_insee_ban:"{insee}"')


def test_main_point_latitude_negative_s_ecrit_avec_le_signe_egal(script, tmp_path):
    """L'aide du script le dit : `--point=-21.1,55.5` (la forme à espace n'est comprise que par les Python récents)."""
    sortie = tmp_path / "sud.json"
    r = routeur_point()
    code = script.main(["--point=-21.1,55.5", "--out", str(sortie)], client=r.client(), maintenant=MAINTENANT,
                       sleep=r.sleep)
    assert code == 0 and json.loads(sortie.read_text(encoding="utf-8"))["point"] == {"lat": -21.1, "lon": 55.5}
    assert r.appels[0].params["lat"] == "-21.1" and r.appels[0].params["lon"] == "55.5"


def test_main_adresse_inchange_une_adresse_sans_point_passe_toujours(script, tmp_path):
    """Pendant des refus ci-dessus : `--adresse` seul, comme avant le lot, fait la fiche."""
    code, fiche = _lancer(script, tmp_path, routeur_nominal())
    assert code == 0 and tuple(fiche) == CLES_FICHE
