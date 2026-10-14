"""Tests hors ligne des collecteurs réglementaires de la fiche « données ouvertes » d'un bien : `src/opendata/{urbanisme,batiment,copropriete}.py`.

Aucun appel réseau : chaque client passe par `httpx.MockTransport` (classe `Reseau`, qui garde le journal des
requêtes) ; une fixture autouse fait échouer toute connexion réelle ; `sleep` est injecté (aucune attente réelle).
Les faux serveurs reproduisent les pièges constatés sur les API réelles le 07/10/2026 : longitude et latitude
inversées -> 200 vide (API Carto), plafond silencieux de 10 lignes (BDNB), filtre ignoré, etc. : un code qui tombe
dans le piège fait échouer le test, au lieu de passer sur une réponse complaisante.

Données FICTIVES : commune « Testville » (INSEE 99999), identifiants, noms de copropriété et de monument inventés.
Rien n'est importé de `tests/test_opendata.py` (ses tests seraient collectés deux fois).
"""

from __future__ import annotations

import json
import math
import socket
from collections.abc import Callable
from typing import Any, NamedTuple

import httpx
import pytest

from src.opendata import batiment, copropriete, urbanisme
from src.opendata.http import OpendataError, Resultat, make_client

INSEE = "99999"
LON, LAT = 2.5, 47.45
DEMI = 0.00025  # oracle du test, indépendant de la constante du module
GEO: dict[str, Any] = {
    "label": "1 Rue d'Essai 99999 Testville", "score": 0.97, "type": "housenumber", "citycode": INSEE,
    "postcode": "99999", "city": "Testville", "lon": LON, "lat": LAT,
}


# ---------------------------------------------------------------------------
# Infrastructure : réseau interdit, faux réseau (MockTransport) et journal des requêtes
# ---------------------------------------------------------------------------

class AppelInterdit(BaseException):
    """Connexion réelle, ou requête que le faux réseau n'a pas prévue.

    Dérive de BaseException et non d'Exception : un collecteur ou la fiche qui capterait `Exception` ne
    l'absorbe pas, et le test tombe au lieu de passer sur une erreur avalée.
    """


@pytest.fixture(autouse=True)
def _reseau_interdit(monkeypatch):
    """Toute tentative de connexion ou de résolution DNS réelle fait échouer le test."""
    def interdit(*_args, **_kwargs):
        raise AppelInterdit("appel réseau interdit en test")

    monkeypatch.setattr(socket.socket, "connect", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)


class Appel(NamedTuple):
    cle: str  # hôte + chemin, sans schéma ni query
    params: dict[str, str]
    url: str  # URL complète, query comprise


class Reseau:
    """Faux réseau : transport `httpx.MockTransport`, journal des requêtes, attentes simulées.

    `route(cle, reponse)` : `cle` = hôte + chemin exacts. `reponse` est un appelable `requete -> httpx.Response`,
    une exception (instance ou classe, levée à chaque appel) ou une liste de ces éléments, consommée dans l'ordre
    (une liste épuisée fait échouer le test). Les routes ajoutées en DERNIER l'emportent. Une requête sans route
    lève AppelInterdit.
    """

    def __init__(self) -> None:
        self.appels: list[Appel] = []
        self.attentes: list[float] = []
        self._routes: list[tuple[str, Any]] = []
        self.transport = httpx.MockTransport(self._repondre)

    def sleep(self, secondes: float) -> None:
        self.attentes.append(secondes)

    def client(self) -> httpx.Client:
        return make_client(self.transport)

    def route(self, cle: str, reponse: Any) -> Reseau:
        self._routes.append((cle, reponse))
        return self

    def appels_vers(self, cle: str) -> list[Appel]:
        return [a for a in self.appels if a.cle == cle]

    def panne_au_appel(self, cle: str, rang: int = 1, code: int = 500) -> Reseau:
        """Le `rang`-ième appel (1 = le premier) vers `cle` répond `code` ; tous les autres, comme avant."""
        courant = next(reponse for motif, reponse in reversed(self._routes) if motif == cle)
        compteur = [0]

        def repondre(requete: httpx.Request) -> httpx.Response:
            compteur[0] += 1
            if compteur[0] == rang:
                return httpx.Response(code, content=b"erreur simulee")
            return self._produire(courant)(requete)

        return self.route(cle, repondre)

    def _repondre(self, requete: httpx.Request) -> httpx.Response:
        cle = f"{requete.url.host}{requete.url.path}"
        self.appels.append(Appel(cle, dict(requete.url.params), str(requete.url)))
        for motif, reponse in reversed(self._routes):
            if motif == cle:
                return self._produire(reponse)(requete)
        raise AppelInterdit(f"requête non prévue par le faux réseau : {requete.method} {requete.url}")

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


def json_ok(donnees: Any, statut: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(statut, json=donnees)


def statut_http(code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(code, content=b"erreur simulee")


def test_garde_reseau_la_fixture_autouse_est_active():
    """Un httpx.Client SANS transport simulé qui tente un GET lève AppelInterdit : aucun appel réel possible."""
    with httpx.Client() as client:
        with pytest.raises(AppelInterdit, match="réseau interdit"):
            client.get("https://apicarto.ign.fr/api/gpu/municipality")
    with pytest.raises(AppelInterdit, match="réseau interdit"):
        socket.getaddrinfo("apicarto.ign.fr", 443)
    with pytest.raises(AppelInterdit, match="réseau interdit"):
        socket.socket().connect(("127.0.0.1", 9))


def test_faux_reseau_une_requete_sans_route_fait_echouer_le_test():
    with pytest.raises(AppelInterdit, match="non prévue"):
        Reseau().client().get("https://api.test/imprevu")


def test_faux_reseau_une_sequence_epuisee_fait_echouer_le_test():
    r = Reseau().route("api.test/x", [json_ok({})])
    r.client().get("https://api.test/x")
    with pytest.raises(AppelInterdit, match="épuisée"):
        r.client().get("https://api.test/x")


# ===========================================================================
# 1. urbanisme : API Carto, module GPU
# ===========================================================================

GPU = "apicarto.ign.fr/api/gpu/"
ENDPOINTS = ("municipality", "document", "zone-urba", "prescription-surf", "prescription-lin", "prescription-pct",
             "assiette-sup-s")

COMMUNE = {"insee": INSEE, "name": "Testville", "is_rnu": False, "is_deleted": False}
DOCUMENT = {"id": "doc-0001", "name": "99999_PLU_20200115", "du_type": "PLU", "gpu_status": "statut-test",
            "gpu_timestamp": "2020-02-03T10:00:00Z", "partition": "DU_99999"}
ZONE = {"libelle": "UA", "libelong": "Secteur du centre", "typezone": "U", "idurba": "99999_PLU_20200115",
        "datvalid": "20170627", "nomfic": "99999_reglement_20200115.pdf", "gpu_doc_id": "doc-0001",
        "datappro": "", "urlfic": ""}
PRESC_LIN = {"gid": 11, "libelle": "Linéaire d'exemple protégé", "txt": "commerce en rez-de-chaussée",
             "typepsc": "22", "stypepsc": "03"}
PRESC_SURF = {"gid": 21, "libelle": "Bande constructible", "txt": "30m", "typepsc": "15", "stypepsc": "01"}
AC1 = {"suptype": "ac1", "typeass": "Périmètre des abords", "nomass": "AC1_Essai_ass",
       "nomsuplitt": "Eglise Saint-ExemplÃ©", "modegeoass": "Zone tampon", "paramcalc": 500}
PM1 = {"suptype": "pm1", "typeass": "Enveloppe des zonages réglementaires",
       "nomass": "PM1_PPRI_Essai_20091122_ass", "nomsuplitt": None, "modegeoass": None, "paramcalc": None}

BLOC_ZONE = {
    "libelle": "UA", "libelong": "Secteur du centre", "typezone": "U", "idurba": "99999_PLU_20200115",
    "date_approbation": "2020-01-15",
    "reglement_url": "https://www.geoportail-urbanisme.gouv.fr/api/document/doc-0001/files/"
                     "99999_reglement_20200115.pdf",
}
BLOC_PORTEE = {
    "zone": "au point", "servitudes": "au point",
    "prescriptions": "carré d'environ 38 × 56 m autour du point : à confirmer sur le règlement",
    "prescriptions_demi_cote_deg": 0.00025,
    "limite": "une liste vide ne prouve pas l'absence de servitude",
}


def collection(*proprietes: dict | None) -> dict:
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None, "properties": p} for p in proprietes]}


def _geom(requete: httpx.Request) -> Any:
    brut = requete.url.params.get("geom")
    try:
        return json.loads(brut) if brut else None
    except ValueError:
        return None


def _est_le_point(geom: Any) -> bool:
    return geom == {"type": "Point", "coordinates": [LON, LAT]}


def _est_le_carre(geom: Any) -> bool:
    """Polygone d'un seul anneau fermé dont les 4 coins sont (LON ± DEMI, LAT ± DEMI), quel que soit le sens."""
    if not isinstance(geom, dict) or geom.get("type") != "Polygon":
        return False
    anneaux = geom.get("coordinates")
    if not (isinstance(anneaux, list) and len(anneaux) == 1 and len(anneaux[0]) == 5):
        return False
    anneau = anneaux[0]
    coins = {(round(x, 6), round(y, 6)) for x in (LON - DEMI, LON + DEMI) for y in (LAT - DEMI, LAT + DEMI)}
    return anneau[0] == anneau[-1] and {(round(x, 6), round(y, 6)) for x, y in anneau[:4]} == coins


def au_point(*proprietes: dict | None) -> Callable[[httpx.Request], httpx.Response]:
    """Réponse à une requête au point : vide si longitude et latitude sont inversées (piège réel, sans erreur)."""
    return lambda requete: httpx.Response(
        200, json=collection(*(proprietes if _est_le_point(_geom(requete)) else ())))


def dans_le_carre(*proprietes: dict | None) -> Callable[[httpx.Request], httpx.Response]:
    """Réponse à une requête par carré : vide si le carré n'est pas celui de ±0,00025° autour du point."""
    return lambda requete: httpx.Response(
        200, json=collection(*(proprietes if _est_le_carre(_geom(requete)) else ())))


def reseau_urbanisme(*, commune: dict | None = COMMUNE, documents: tuple = (DOCUMENT,), zones: tuple = (ZONE,),
                     surf: tuple = (), lin: tuple = (), pct: tuple = (), servitudes: tuple = ()) -> Reseau:
    r = Reseau()
    r.route(GPU + "municipality", lambda q: httpx.Response(
        200, json=collection(*([commune] if commune is not None and q.url.params.get("insee") == INSEE else []))))
    r.route(GPU + "document", au_point(*documents))
    r.route(GPU + "zone-urba", au_point(*zones))
    r.route(GPU + "prescription-surf", dans_le_carre(*surf))
    r.route(GPU + "prescription-lin", dans_le_carre(*lin))
    r.route(GPU + "prescription-pct", dans_le_carre(*pct))
    r.route(GPU + "assiette-sup-s", au_point(*servitudes))
    return r


def lancer_urbanisme(r: Reseau, geo: dict | None = None) -> Resultat:
    return urbanisme.collecter(r.client(), geo or GEO, sleep=r.sleep)


def urbanisme_nominal() -> Reseau:
    return reseau_urbanisme(lin=(PRESC_LIN,), surf=(PRESC_SURF,), servitudes=(AC1, PM1))


def test_urbanisme_nominal_bloc_complet():
    resultat = lancer_urbanisme(urbanisme_nominal())
    assert resultat.bloc == {
        "commune": {"insee": INSEE, "nom": "Testville", "rnu": False, "supprimee": False},
        "documents": [{"id": "doc-0001", "nom": "99999_PLU_20200115", "type": "PLU", "statut": "statut-test",
                       "date_gpu": "2020-02-03T10:00:00Z"}],
        "zone": BLOC_ZONE,
        "prescriptions": [
            {"nature": "surf", "libelle": "Bande constructible", "typepsc": "15", "stypepsc": "01", "txt": "30m"},
            {"nature": "lin", "libelle": "Linéaire d'exemple protégé", "typepsc": "22", "stypepsc": "03",
             "txt": "commerce en rez-de-chaussée"},
        ],
        "servitudes": [
            {"categorie": "AC1", "nom": "Eglise Saint-Exemplé", "type_assiette": "Périmètre des abords",
             "mode": "Zone tampon", "parametre": 500, "nomass": "AC1_Essai_ass"},
            {"categorie": "PM1", "nom": None, "type_assiette": "Enveloppe des zonages réglementaires",
             "mode": None, "parametre": None, "nomass": "PM1_PPRI_Essai_20091122_ass"},
        ],
        "abords_monument_historique": True,
        "plan_prevention_risques": True,
        "portee": BLOC_PORTEE,
    }
    assert resultat.erreurs == []
    assert list(resultat.alertes) == []


def test_urbanisme_source_constantes_et_forme_du_resultat():
    resultat = lancer_urbanisme(urbanisme_nominal())
    assert resultat.sources == [urbanisme.SOURCE]
    assert urbanisme.SOURCE == {"bloc": "urbanisme", "url": urbanisme.URL, "licence": urbanisme.LICENCE,
                                "millesime": None}
    assert urbanisme.URL == "https://apicarto.ign.fr/api/gpu"
    assert "Licence Ouverte" in urbanisme.LICENCE
    assert urbanisme.DEMI_COTE_DEG == DEMI
    assert isinstance(resultat, Resultat)


def test_urbanisme_sept_appels_dans_l_ordre_avec_les_bons_parametres():
    r = urbanisme_nominal()
    lancer_urbanisme(r)
    assert [a.cle for a in r.appels] == [GPU + e for e in ENDPOINTS]
    par_endpoint = {a.cle.removeprefix(GPU): a.params for a in r.appels}
    assert par_endpoint["municipality"] == {"insee": INSEE}
    for endpoint in ("document", "zone-urba", "assiette-sup-s"):
        assert set(par_endpoint[endpoint]) == {"geom"}
        # GeoJSON : la LONGITUDE d'abord (inversée, l'API répond 200 vide, sans erreur)
        assert json.loads(par_endpoint[endpoint]["geom"]) == {"type": "Point", "coordinates": [LON, LAT]}
    for endpoint in ("prescription-surf", "prescription-lin", "prescription-pct"):
        assert set(par_endpoint[endpoint]) == {"geom"}
        assert _est_le_carre(json.loads(par_endpoint[endpoint]["geom"])), endpoint


# --- date d'approbation : le suffixe _AAAAMMJJ de idurba -------------------------------------------------

def zone_avec(**champs: Any) -> Reseau:
    return reseau_urbanisme(zones=({**ZONE, **champs},))


@pytest.mark.parametrize("idurba, attendu", [
    ("99999_PLU_20200115", "2020-01-15"),
    ("999999999_PLUI_20250101", "2025-01-01"),  # « PLUI » en majuscules : la casse n'entre pas en jeu
    ("99999_PLUi_20231231", "2023-12-31"),
])
def test_urbanisme_date_d_approbation_tiree_du_suffixe_de_idurba(idurba, attendu):
    zone = lancer_urbanisme(zone_avec(idurba=idurba)).bloc["zone"]
    assert zone["date_approbation"] == attendu
    assert zone["idurba"] == idurba


def test_urbanisme_datvalid_n_est_pas_une_date_d_approbation():
    """Piège réel : datvalid 20170627 pour une approbation du 20230413."""
    zone = lancer_urbanisme(zone_avec(idurba="99999_PLU_20230413", datvalid="20170627")).bloc["zone"]
    assert zone["date_approbation"] == "2023-04-13"


@pytest.mark.parametrize("idurba", [
    None, "", "99999_PLU", "99999_PLU_2023", "99999_PLU_202304131",  # pas de suffixe de 8 chiffres
    "99999_PLU_20231345", "99999_PLU_20230230",  # 8 chiffres qui ne sont pas une date
    "99999_PLU_20230413_M1",  # le suffixe n'est pas en fin d'identifiant
])
def test_urbanisme_date_d_approbation_absente_ou_illisible_vaut_null(idurba):
    zone = lancer_urbanisme(zone_avec(idurba=idurba, datvalid="20170627")).bloc["zone"]
    assert zone["date_approbation"] is None  # jamais datvalid à sa place


@pytest.mark.parametrize("champ", ["libelong", "typezone", "idurba"])
@pytest.mark.parametrize("vide", ["", "   ", None])
def test_urbanisme_champ_facultatif_vide_ou_absent_est_rendu_null(champ, vide):
    """L'API sert `""` pour un libellé long absent : une absence se rend en null, jamais en chaîne vide."""
    assert lancer_urbanisme(zone_avec(**{champ: vide})).bloc["zone"][champ] is None


@pytest.mark.parametrize("parametre", [0, 0.0, 500, "500"])
def test_urbanisme_parametre_de_la_servitude_zero_n_est_pas_une_absence(parametre):
    """La PM1 de Bourg-Exemple porte paramcalc 0 : un zéro est une valeur, il reste 0 (jamais null)."""
    servitude = lancer_urbanisme(reseau_urbanisme(servitudes=({**PM1, "paramcalc": parametre},))).bloc["servitudes"][0]
    assert servitude["parametre"] == parametre and servitude["parametre"] is not None


# --- règlement écrit ---------------------------------------------------------------------------------------

def test_urbanisme_reglement_url_construit_depuis_gpu_doc_id_et_nomfic():
    zone = lancer_urbanisme(zone_avec(gpu_doc_id="abc123", nomfic="Règlement 2023.pdf")).bloc["zone"]
    assert zone["reglement_url"] == ("https://www.geoportail-urbanisme.gouv.fr/api/document/abc123/files/"
                                     "R%C3%A8glement%202023.pdf")


@pytest.mark.parametrize("champs", [{"nomfic": None}, {"nomfic": ""}, {"gpu_doc_id": None}, {"gpu_doc_id": ""}])
def test_urbanisme_reglement_url_null_sans_nom_de_fichier_ou_sans_document(champs):
    assert lancer_urbanisme(zone_avec(**champs)).bloc["zone"]["reglement_url"] is None


# --- prescriptions : dédoublonnage sur (nature, libelle, typepsc, stypepsc, txt) -----------------------------

def test_urbanisme_prescriptions_dedoublonnees_malgre_des_gid_differents():
    doublons = ({**PRESC_LIN, "gid": 1}, {**PRESC_LIN, "gid": 2}, {**PRESC_LIN, "gid": 3})
    r = reseau_urbanisme(lin=doublons)
    assert lancer_urbanisme(r).bloc["prescriptions"] == [
        {"nature": "lin", "libelle": "Linéaire d'exemple protégé", "typepsc": "22", "stypepsc": "03",
         "txt": "commerce en rez-de-chaussée"}]


@pytest.mark.parametrize("difference", [
    {"txt": "autre texte"}, {"typepsc": "99"}, {"stypepsc": "04"}, {"libelle": "Autre libellé"}, {"txt": None},
])
def test_urbanisme_prescriptions_qui_different_sur_un_champ_sont_conservees(difference):
    r = reseau_urbanisme(lin=(PRESC_LIN, {**PRESC_LIN, "gid": 99, **difference}))
    assert len(lancer_urbanisme(r).bloc["prescriptions"]) == 2


def test_urbanisme_prescriptions_de_natures_differentes_ne_se_fusionnent_pas():
    r = reseau_urbanisme(surf=(PRESC_LIN,), lin=(PRESC_LIN,), pct=(PRESC_LIN,))
    natures = [p["nature"] for p in lancer_urbanisme(r).bloc["prescriptions"]]
    assert natures == ["surf", "lin", "pct"]


# --- texte mal encodé -------------------------------------------------------------------------------------

def test_urbanisme_texte_mal_encode_est_repare():
    r = reseau_urbanisme(
        zones=({**ZONE, "libelong": "Secteur de l'ExemplÃ©"},),
        lin=({**PRESC_LIN, "txt": "RÃ©sidence"},),
        servitudes=({**AC1, "nomsuplitt": "Eglise Saint-ExemplÃ©"},),
    )
    bloc = lancer_urbanisme(r).bloc
    assert bloc["servitudes"][0]["nom"] == "Eglise Saint-Exemplé"
    assert bloc["zone"]["libelong"] == "Secteur de l'Exemplé"
    assert bloc["prescriptions"][0]["txt"] == "Résidence"


@pytest.mark.parametrize("texte", [
    "Eglise Saint-Exemplé",  # déjà correct : sans « Ã », rien ne change
    "Cœur d'îlot « protégé »",  # caractères hors latin-1 : jamais touchés
    "Paroisse SÃO Paulo",  # contient « Ã » mais n'est pas du UTF-8 relu en latin-1 : le texte brut reste
    "RÃ©sidence Å“uvre",  # réparation impossible (« Å“ » est hors latin-1) : le texte brut reste
])
def test_urbanisme_texte_correct_ou_irreparable_reste_brut(texte):
    r = reseau_urbanisme(servitudes=({**AC1, "nomsuplitt": texte},))
    assert lancer_urbanisme(r).bloc["servitudes"][0]["nom"] == texte


# --- RNU et alertes ---------------------------------------------------------------------------------------

def test_urbanisme_commune_au_rnu_zone_nulle_et_alerte():
    r = reseau_urbanisme(commune={**COMMUNE, "is_rnu": True}, documents=(), zones=())
    resultat = lancer_urbanisme(r)
    assert resultat.bloc["commune"]["rnu"] is True
    assert resultat.bloc["documents"] == [] and resultat.bloc["zone"] is None
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1 and "RNU" in messages[0]
    assert all(a["bloc"].startswith("urbanisme") for a in resultat.alertes)


def test_urbanisme_hors_rnu_sans_document_alerte_document_peut_etre_non_publie():
    r = reseau_urbanisme(documents=(), zones=())
    resultat = lancer_urbanisme(r)
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1
    assert "document opposable peut-être non publié" in messages[0]
    assert [a["bloc"] for a in resultat.alertes] == ["urbanisme.documents"]  # pas l'alerte « commune au RNU »
    assert resultat.bloc["commune"]["rnu"] is False


def test_urbanisme_hors_rnu_avec_document_aucune_alerte():
    resultat = lancer_urbanisme(reseau_urbanisme())
    assert list(resultat.alertes) == []


def test_urbanisme_au_rnu_avec_un_document_publie_seule_l_alerte_rnu():
    r = reseau_urbanisme(commune={**COMMUNE, "is_rnu": True})
    messages = [a["message"] for a in lancer_urbanisme(r).alertes]
    assert len(messages) == 1 and "RNU" in messages[0]


def test_urbanisme_zones_multiples_premiere_retenue_et_alerte():
    autre = {**ZONE, "libelle": "N", "libelong": "Zone naturelle", "typezone": "N"}
    resultat = lancer_urbanisme(reseau_urbanisme(zones=(ZONE, autre)))
    assert resultat.bloc["zone"]["libelle"] == "UA"
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1
    assert "2 zones au point" in messages[0] and "UA (" in messages[0] and "N (" in messages[0]
    assert "première" in messages[0]


# --- servitudes : AC1 et PM1 ------------------------------------------------------------------------------

def test_urbanisme_servitudes_categorie_en_majuscules_et_indicateurs():
    bloc = lancer_urbanisme(reseau_urbanisme(servitudes=(AC1,))).bloc
    assert [s["categorie"] for s in bloc["servitudes"]] == ["AC1"]
    assert bloc["abords_monument_historique"] is True and bloc["plan_prevention_risques"] is False
    bloc = lancer_urbanisme(reseau_urbanisme(servitudes=(PM1,))).bloc
    assert bloc["abords_monument_historique"] is False and bloc["plan_prevention_risques"] is True


def test_urbanisme_autres_servitudes_ne_levent_aucun_des_deux_indicateurs():
    a4 = {**AC1, "suptype": "a4", "typeass": "Servitude de cours d'eau"}
    bloc = lancer_urbanisme(reseau_urbanisme(servitudes=(a4, {**PM1, "suptype": "pm2"}))).bloc
    assert [s["categorie"] for s in bloc["servitudes"]] == ["A4", "PM2"]
    assert bloc["abords_monument_historique"] is False and bloc["plan_prevention_risques"] is False


def test_urbanisme_servitudes_plusieurs_ac1_toutes_gardees_sans_dedoublonnage():
    """Comme les 6 AC1 de Exempleville : une ligne par entité de l'API, aucune fusion."""
    six = tuple({**AC1, "nomsuplitt": f"Monument {i}"} for i in range(6))
    bloc = lancer_urbanisme(reseau_urbanisme(servitudes=six + (PM1,))).bloc
    assert [s["categorie"] for s in bloc["servitudes"]] == ["AC1"] * 6 + ["PM1"]
    identiques = lancer_urbanisme(reseau_urbanisme(servitudes=(AC1, AC1))).bloc
    assert len(identiques["servitudes"]) == 2


def test_urbanisme_suptype_en_minuscules_ou_avec_espaces_est_normalise():
    bloc = lancer_urbanisme(reseau_urbanisme(servitudes=({**AC1, "suptype": " Ac1 "},))).bloc
    assert bloc["servitudes"][0]["categorie"] == "AC1" and bloc["abords_monument_historique"] is True


# --- vide, portée --------------------------------------------------------------------------------------

def test_urbanisme_tout_vide_ne_fabrique_aucun_faux_positif():
    bloc = lancer_urbanisme(reseau_urbanisme(documents=(), zones=())).bloc
    assert bloc["zone"] is None
    assert bloc["documents"] == [] and bloc["prescriptions"] == [] and bloc["servitudes"] == []
    assert bloc["abords_monument_historique"] is False and bloc["plan_prevention_risques"] is False


def test_urbanisme_portee_dit_ou_et_comment_chaque_liste_a_ete_lue():
    portee = lancer_urbanisme(urbanisme_nominal()).bloc["portee"]
    assert portee == BLOC_PORTEE
    assert "à confirmer sur le règlement" in portee["prescriptions"]
    assert "ne prouve pas l'absence de servitude" in portee["limite"]


def test_urbanisme_portee_le_carre_se_calcule_a_la_latitude_du_point():
    """37 x 56 m n'est vrai qu'à cette latitude : à 45 degrés, la largeur du carré de ±0,00025° est d'environ 39 m."""
    r = Reseau()
    for endpoint in ENDPOINTS:
        r.route(GPU + endpoint, json_ok(collection(COMMUNE) if endpoint == "municipality" else collection()))
    portee = lancer_urbanisme(r, {**GEO, "lat": 45.0}).bloc["portee"]
    assert portee["prescriptions"] == "carré d'environ 39 × 56 m autour du point : à confirmer sur le règlement"


# --- forme inattendue, erreurs HTTP ------------------------------------------------------------------------

def _casse(endpoint: str, reponse: Any, **kw: Any) -> Reseau:
    r = reseau_urbanisme(**kw)
    r.route(GPU + endpoint, json_ok(reponse))
    return r


FORMES_INATTENDUES = [
    pytest.param("municipality", [], id="municipality-liste"),
    pytest.param("municipality", {"type": "FeatureCollection"}, id="municipality-sans-features"),
    pytest.param("municipality", collection({"insee": INSEE, "name": "Testville", "is_deleted": False}),
                 id="municipality-sans-is_rnu"),
    pytest.param("municipality", collection({"insee": INSEE, "name": "Testville", "is_rnu": "non"}),
                 id="municipality-is_rnu-texte"),
    pytest.param("municipality", collection({"insee": INSEE, "is_rnu": False}), id="municipality-sans-nom"),
    pytest.param("document", {"features": "pas une liste"}, id="document-features-non-liste"),
    pytest.param("document", {"features": [{"type": "Feature"}]}, id="document-sans-properties"),
    pytest.param("document", {"features": [None]}, id="document-feature-nulle"),
    pytest.param("document", collection({"name": "x"}), id="document-sans-id"),
    pytest.param("zone-urba", collection({"libelong": "sans libelle"}), id="zone-sans-libelle"),
    pytest.param("zone-urba", "texte", id="zone-corps-texte"),
    pytest.param("prescription-lin", collection({"txt": "sans libelle"}), id="prescription-sans-libelle"),
    pytest.param("prescription-pct", {"features": {}}, id="prescription-features-objet"),
    pytest.param("assiette-sup-s", collection({"typeass": "sans suptype"}), id="servitude-sans-suptype"),
    pytest.param("assiette-sup-s", collection({"suptype": 7}), id="servitude-suptype-numerique"),
]


@pytest.mark.parametrize("endpoint, reponse", FORMES_INATTENDUES)
def test_urbanisme_forme_inattendue_leve_opendataerror_avec_l_url(endpoint, reponse):
    r = _casse(endpoint, reponse)
    with pytest.raises(OpendataError) as exc:
        lancer_urbanisme(r)
    assert "apicarto.ign.fr" in str(exc.value) and endpoint in str(exc.value)


def test_urbanisme_commune_absente_de_l_api_leve():
    with pytest.raises(OpendataError, match="99999"):
        lancer_urbanisme(reseau_urbanisme(commune=None))


def test_urbanisme_autre_commune_renvoyee_leve_filtre_ignore():
    with pytest.raises(OpendataError, match="filtre"):
        lancer_urbanisme(reseau_urbanisme(commune={**COMMUNE, "insee": "88888"}))


def test_urbanisme_une_panne_ne_laisse_pas_un_bloc_partiel_ni_un_faux_vide_de_servitudes():
    """assiette-sup-s en 500 : tout le bloc échoue (jamais `servitudes: []` qui dirait « aucune servitude »)."""
    r = urbanisme_nominal()
    r.route(GPU + "assiette-sup-s", statut_http(500))
    with pytest.raises(OpendataError, match="3 tentatives"):
        lancer_urbanisme(r)
    assert r.attentes == [1, 2]
    assert len(r.appels_vers(GPU + "assiette-sup-s")) == 3


@pytest.mark.parametrize("code", [400, 403, 404])
def test_urbanisme_une_erreur_du_demandeur_n_est_pas_rejouee(code):
    r = urbanisme_nominal()
    r.route(GPU + "zone-urba", statut_http(code))
    with pytest.raises(OpendataError, match=f"HTTP {code}"):
        lancer_urbanisme(r)
    assert len(r.appels_vers(GPU + "zone-urba")) == 1 and r.attentes == []


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("code", [500, 429])
def test_urbanisme_chaque_appel_est_rejoue_apres_une_panne_avec_le_sleep_injecte(endpoint, code):
    """Les sept appels passent par le socle HTTP ET lui transmettent `sleep` : zéro attente réelle en test."""
    r = urbanisme_nominal().panne_au_appel(GPU + endpoint, 1, code)
    assert lancer_urbanisme(r).bloc == lancer_urbanisme(urbanisme_nominal()).bloc
    assert r.attentes == [1] and len(r.appels_vers(GPU + endpoint)) == 2


def test_urbanisme_un_429_est_rejoue_puis_le_bloc_est_servi():
    r = urbanisme_nominal()
    ok = au_point(ZONE)
    r.route(GPU + "zone-urba", [statut_http(429), ok])
    assert lancer_urbanisme(r).bloc["zone"]["libelle"] == "UA"
    assert r.attentes == [1]


# ===========================================================================
# 2. batiment : BDNB (CSTB), API ouverte
# ===========================================================================

BDNB = "api.bdnb.io/v1/bdnb/donnees/"
RELATION = BDNB + "rel_batiment_groupe_parcelle"
TABLE = BDNB + "batiment_groupe_complet"
PARCELLE = "99999000AB0123"  # IDU fictif : INSEE 99999, préfixe 000, section AB, numéro 0123
CHAMPS_BDNB = (  # oracle du test : les onze champs de référence, dans l'ordre
    "batiment_groupe_id", "annee_construction", "mat_mur_txt", "materiaux_structure_mur_exterieur", "nb_log",
    "nb_niveau", "usage_niveau_1_txt", "usage_principal_bdnb_open", "numero_immat_principal", "nb_log_rnc",
    "nb_lot_tertiaire_rnc",
)
ID_A, ID_B = "bdnb-bg-AAAA-AAAA-AAAA", "bdnb-bg-BBBB-BBBB-BBBB"
LIMITES_BDNB = ["usage mixte non publié en accès ouvert",
                "valeurs brutes : la BDNB peut contredire le DPE ou l'annonce"]


def groupe(identifiant: str, **champs: Any) -> dict:
    return {**dict.fromkeys(CHAMPS_BDNB), "batiment_groupe_id": identifiant, **champs}


G_MAISON = groupe(ID_A, annee_construction=1850, mat_mur_txt="MEULIERE", materiaux_structure_mur_exterieur="pierre",
                  nb_log=1, nb_niveau=2, usage_niveau_1_txt="Résidentiel individuel",
                  usage_principal_bdnb_open="Résidentiel individuel")
G_ANNEXE = groupe(ID_B)  # « petit objet presque vide »


def attendu_groupe(groupe_table: dict, principale: Any = True) -> dict:
    """Groupe tel que le bloc le rend (forme actuelle) : les champs de la table plus `parcelle_principale`, lu sur la
    relation. Ancien attendu : les onze champs de la table seuls."""
    return {**groupe_table, "parcelle_principale": principale}


def groupes_numerotes(n: int, **champs: Any) -> list[dict]:
    return [groupe(f"bdnb-bg-{i:04d}-TEST-0000", nb_log=i % 7, **champs) for i in range(n)]


def reseau_bdnb(groupes: tuple | list = (), *, relation: list[str] | None = None, parcelle: str = PARCELLE,
                plafond_table: int = 10, plafond_relation: int | None = None, statut_partiel: int = 206,
                principales: dict[str, Any] | None = None) -> Reseau:
    """Faux PostgREST de la BDNB. `relation` : identifiants liés à la parcelle (par défaut ceux de `groupes`).

    Plafond SILENCIEUX de `plafond_table` lignes par réponse sur la table complète, avec le statut 206 quand la page
    est partielle (piège réel : au-delà de 10 identifiants par appel, des groupes disparaissent sans erreur).
    `plafond_relation` (None : pas de plafond) fait de même sur la relation parcelle -> groupes. `statut_partiel` :
    206 comme au relevé du 07/10, ou 200 avec `Content-Range: 0-9/*` comme au rejeu du 08/10 : le code ne se fie pas
    au statut. `principales` : valeur de `parcelle_principale` de la relation par groupe (vrai par défaut, comme les
    deux groupes de la parcelle de Bourg-Exemple au contrôle réel du 08/10).
    """
    par_id = {g["batiment_groupe_id"]: g for g in groupes}
    ids_relation = [g["batiment_groupe_id"] for g in groupes] if relation is None else list(relation)

    def repondre_relation(requete: httpx.Request) -> httpx.Response:
        if requete.url.params.get("parcelle_id") != f"eq.{parcelle}":
            return httpx.Response(200, json=[])
        lignes = [{"batiment_groupe_id": i, "parcelle_id": parcelle,
                   "parcelle_principale": (principales or {}).get(i, True)} for i in ids_relation]
        if plafond_relation is not None and len(lignes) > plafond_relation:
            return httpx.Response(statut_partiel, json=lignes[:plafond_relation])
        return httpx.Response(200, json=lignes)

    def repondre_table(requete: httpx.Request) -> httpx.Response:
        filtre = requete.url.params.get("batiment_groupe_id", "")
        if not (filtre.startswith("in.(") and filtre.endswith(")")):
            return httpx.Response(400, json={"message": "filtre illisible"})
        champs = requete.url.params.get("select")
        trouves = [par_id[i] for i in filtre[4:-1].split(",") if i in par_id]
        lignes = [{c: g.get(c) for c in champs.split(",")} if champs else g for g in trouves]
        return httpx.Response(statut_partiel if len(lignes) > plafond_table else 200, json=lignes[:plafond_table])

    return Reseau().route(RELATION, repondre_relation).route(TABLE, repondre_table)


def lancer_batiment(r: Reseau, parcelle: Any = PARCELLE) -> Resultat:
    return batiment.collecter(r.client(), parcelle, sleep=r.sleep)


def test_batiment_nominal_bloc_complet():
    r = reseau_bdnb((G_ANNEXE, G_MAISON), relation=[ID_B, ID_A])  # la relation n'est pas dans l'ordre du tri
    resultat = lancer_batiment(r)
    assert resultat.bloc == {
        "parcelle": PARCELLE,
        "groupes": [attendu_groupe(G_MAISON), attendu_groupe(G_ANNEXE)],  # nb_log décroissant, null en dernier
        "n_groupes": 2,
        "immatriculations": [],
        "usage_mixte_indice": None,
        "limites": resultat.bloc["limites"],
        "parametres": {"max_identifiants_par_appel": 10},
    }
    assert resultat.bloc["limites"][:2] == LIMITES_BDNB
    assert resultat.erreurs == [] and list(resultat.alertes) == []
    assert resultat.sources == [batiment.SOURCE]


@pytest.mark.parametrize("principales", [
    pytest.param({ID_A: True, ID_B: False}, id="vrai_et_faux"),
    pytest.param({ID_A: False, ID_B: True}, id="faux_et_vrai"),
    pytest.param({ID_A: None, ID_B: None}, id="nuls"),
])
def test_batiment_parcelle_principale_de_la_relation_est_rendue_telle_quelle_dans_chaque_groupe(principales):
    """Champ brut de la relation, juste après l'identifiant du groupe (jamais interprété)."""
    groupes = lancer_batiment(reseau_bdnb((G_MAISON, G_ANNEXE), principales=principales)).bloc["groupes"]
    assert {g["batiment_groupe_id"]: g["parcelle_principale"] for g in groupes} == principales
    assert all(list(g)[:2] == ["batiment_groupe_id", "parcelle_principale"] for g in groupes)
    assert all(set(g) == set(CHAMPS_BDNB) | {"parcelle_principale"} for g in groupes)


def test_batiment_parcelle_principale_absente_de_la_ligne_de_relation_vaut_null():
    ligne = {"batiment_groupe_id": ID_A, "parcelle_id": PARCELLE}  # pas de parcelle_principale
    r = Reseau().route(RELATION, json_ok([ligne])).route(TABLE, json_ok([G_MAISON]))
    assert lancer_batiment(r).bloc["groupes"][0]["parcelle_principale"] is None


def test_batiment_limites_dites_dont_le_sens_du_null_de_usage_mixte_indice():
    limites = lancer_batiment(reseau_bdnb((G_MAISON,))).bloc["limites"]
    assert limites[:2] == LIMITES_BDNB
    assert len(limites) == 3 and "nb_lot_tertiaire_rnc" in limites[2] and "ne prouve pas" in limites[2]


def test_batiment_le_seuil_de_dix_identifiants_par_appel_est_dit_dans_le_bloc(monkeypatch):
    """Paramètre de méthode : nommé en constante, dit dans le bloc (et suit la constante)."""
    assert lancer_batiment(reseau_bdnb((G_MAISON,))).bloc["parametres"] == {"max_identifiants_par_appel": 10}
    monkeypatch.setattr(batiment, "BDNB_MAX_IDS", 4)
    assert lancer_batiment(reseau_bdnb((G_MAISON,))).bloc["parametres"] == {"max_identifiants_par_appel": 4}


def test_batiment_source_constantes_et_quota_dans_le_docstring():
    assert batiment.SOURCE == {"bloc": "batiment", "url": batiment.URL, "licence": batiment.LICENCE,
                               "millesime": None}
    assert batiment.URL == "https://api.bdnb.io/v1/bdnb/donnees"
    assert "Licence Ouverte 2.0" in batiment.LICENCE
    assert batiment.BDNB_MAX_IDS == 10
    assert tuple(batiment.CHAMPS) == CHAMPS_BDNB
    # le docstring dit le quota de l'API ouverte et le coût d'une fiche
    assert "10 000 requêtes par mois" in batiment.__doc__
    assert "120" in batiment.__doc__ and "2 requêtes par fiche" in batiment.__doc__


def test_batiment_deux_appels_relation_puis_table_avec_select_des_onze_champs():
    r = reseau_bdnb((G_MAISON, G_ANNEXE))
    lancer_batiment(r)
    assert [a.cle for a in r.appels] == [RELATION, TABLE]
    assert r.appels[0].params == {"parcelle_id": f"eq.{PARCELLE}"}
    assert r.appels[1].params == {"batiment_groupe_id": f"in.({ID_A},{ID_B})", "select": ",".join(CHAMPS_BDNB)}


def test_batiment_jamais_la_requete_interdite_ni_de_jointure():
    """`l_parcelle_id=cs.{...}` rend 500 après 10 s et les jointures intégrées rendent 400 : aucune des deux."""
    r = reseau_bdnb((G_MAISON,))
    lancer_batiment(r)
    for appel in r.appels:
        assert not (set(appel.params) & {"l_parcelle_id", "limit", "offset", "order"})
        assert all("cs." not in valeur and "(" not in valeur.replace("in.(", "") for valeur in appel.params.values())
        assert appel.params.get("select", "").count("(") == 0  # pas de jointure intégrée


# --- tri ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("entrees, attendu", [
    # (identifiant, nb_log) dans l'ordre de la relation -> ordre attendu : nb_log décroissant, null en dernier, id
    ([("C", 1), ("A", 3), ("B", None), ("D", 3), ("E", 0), ("F", None)], ["A", "D", "C", "E", "B", "F"]),
    ([("B", 2), ("A", 2)], ["A", "B"]),  # égalité : l'identifiant croissant départage
    ([("Z", None), ("Y", None)], ["Y", "Z"]),  # que des null : l'identifiant croissant
    ([("A", 0), ("B", None)], ["A", "B"]),  # 0 logement passe AVANT null (0 est une valeur, null une absence)
])
def test_batiment_tri_nb_log_decroissant_null_en_dernier_puis_identifiant(entrees, attendu):
    groupes = [groupe(f"bdnb-bg-{i}", nb_log=n) for i, n in entrees]
    resultat = lancer_batiment(reseau_bdnb(groupes))
    assert [g["batiment_groupe_id"] for g in resultat.bloc["groupes"]] == [f"bdnb-bg-{i}" for i in attendu]


# --- paquets de 10 identifiants -------------------------------------------------------------------------

@pytest.mark.parametrize("n, tailles", [
    (1, [1]), (9, [9]), (10, [10]), (11, [10, 1]), (20, [10, 10]), (21, [10, 10, 1]), (23, [10, 10, 3]),
])
def test_batiment_par_paquets_de_dix_identifiants_aucun_groupe_perdu(n, tailles):
    groupes = groupes_numerotes(n)
    r = reseau_bdnb(groupes)  # la table plafonne en silence à 10 lignes : un seul gros appel perdrait des groupes
    resultat = lancer_batiment(r)
    appels = r.appels_vers(TABLE)
    assert [len(a.params["batiment_groupe_id"][4:-1].split(",")) for a in appels] == tailles
    assert len(r.appels_vers(RELATION)) == 1
    assert resultat.bloc["n_groupes"] == n
    assert {g["batiment_groupe_id"] for g in resultat.bloc["groupes"]} == {g["batiment_groupe_id"] for g in groupes}


def test_batiment_un_seul_gros_appel_perdrait_des_groupes_le_faux_serveur_le_prouve():
    """Garde de la garde : le faux serveur plafonne bien à 10 lignes, statut 206, sans erreur."""
    groupes = groupes_numerotes(15)
    r = reseau_bdnb(groupes)
    ids = ",".join(g["batiment_groupe_id"] for g in groupes)
    reponse = r.client().get(f"https://{TABLE}", params={"batiment_groupe_id": f"in.({ids})"})
    assert reponse.status_code == 206 and len(reponse.json()) == 10


# --- 206 et erreurs HTTP --------------------------------------------------------------------------------

def test_batiment_reponse_206_acceptee_sur_la_relation_et_sur_la_table():
    lignes = [{"batiment_groupe_id": ID_A, "parcelle_id": PARCELLE, "parcelle_principale": True}]
    r = Reseau().route(RELATION, json_ok(lignes, 206)).route(TABLE, json_ok([G_MAISON], 206))
    resultat = lancer_batiment(r)
    assert resultat.bloc["groupes"] == [attendu_groupe(G_MAISON)] and resultat.bloc["n_groupes"] == 1


@pytest.mark.parametrize("cle", [RELATION, TABLE])
@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_batiment_une_erreur_du_demandeur_leve_sans_etre_rejouee(cle, code):
    """Les erreurs comptent dans le quota de l'API : une erreur du demandeur ne se rejoue pas."""
    r = reseau_bdnb((G_MAISON,))
    r.route(cle, statut_http(code))
    with pytest.raises(OpendataError, match=f"HTTP {code}"):
        lancer_batiment(r)
    assert len(r.appels_vers(cle)) == 1 and r.attentes == []


def test_batiment_une_panne_serveur_est_rejouee_trois_fois_puis_leve():
    r = reseau_bdnb((G_MAISON,))
    r.route(TABLE, statut_http(500))
    with pytest.raises(OpendataError, match="3 tentatives"):
        lancer_batiment(r)
    assert len(r.appels_vers(TABLE)) == 3 and r.attentes == [1, 2]


@pytest.mark.parametrize("cle, rang, n_groupes", [(RELATION, 1, 2), (TABLE, 1, 2), (TABLE, 1, 15), (TABLE, 2, 15)])
def test_batiment_chaque_appel_est_rejoue_apres_une_panne_avec_le_sleep_injecte(cle, rang, n_groupes):
    """Relation, premier et second paquet de la table : tous passent par le socle HTTP avec `sleep` injecté."""
    groupes = groupes_numerotes(n_groupes)
    r = reseau_bdnb(groupes).panne_au_appel(cle, rang)
    resultat = lancer_batiment(r)
    assert resultat.bloc["n_groupes"] == n_groupes
    appels_sans_panne = 1 if cle == RELATION else (n_groupes + 9) // 10
    assert len(r.appels_vers(cle)) == appels_sans_panne + 1  # un seul appel de plus : celui qui a échoué
    assert r.attentes == [1]


# --- aucune relation, plafond de la relation ------------------------------------------------------------

def test_batiment_aucune_ligne_de_relation_groupes_vides_et_alerte():
    r = reseau_bdnb(())
    resultat = lancer_batiment(r)
    assert resultat.bloc == {
        "parcelle": PARCELLE, "groupes": [], "n_groupes": 0, "immatriculations": [], "usage_mixte_indice": None,
        "limites": resultat.bloc["limites"], "parametres": {"max_identifiants_par_appel": 10},
    }
    assert resultat.bloc["limites"][:2] == LIMITES_BDNB
    assert list(resultat.alertes) == [{"bloc": "batiment", "message": "aucun bâtiment BDNB sur la parcelle"}]
    assert [a.cle for a in r.appels] == [RELATION]  # rien à demander à la table
    assert resultat.erreurs == []


@pytest.mark.parametrize("statut_partiel", [206, 200])
def test_batiment_relation_au_plafond_de_dix_lignes_alerte_liste_peut_etre_tronquee(statut_partiel):
    """12 groupes, mais la relation n'en rend que 10 (plafond silencieux, 206 ou 200) : le dire, ne rien taire."""
    groupes = groupes_numerotes(12)
    r = reseau_bdnb(groupes, plafond_relation=10, statut_partiel=statut_partiel)
    resultat = lancer_batiment(r)
    assert resultat.bloc["n_groupes"] == 10
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1 and "10" in messages[0] and "tronquée" in messages[0]


def test_batiment_relation_sous_le_plafond_aucune_alerte():
    resultat = lancer_batiment(reseau_bdnb(groupes_numerotes(9), plafond_relation=10))
    assert resultat.bloc["n_groupes"] == 9 and list(resultat.alertes) == []


# --- usage mixte, immatriculations ----------------------------------------------------------------------

@pytest.mark.parametrize("tertiaires, attendu", [
    ([None, None], None),  # rien de renseigné : on ne sait pas
    ([None], None),
    ([0, None], False),
    ([0, 0], False),
    ([0, 2], True),
    ([3], True),
    ([None, 1], True),
])
def test_batiment_usage_mixte_indice(tertiaires, attendu):
    groupes = [groupe(f"bdnb-bg-{i}", nb_lot_tertiaire_rnc=t) for i, t in enumerate(tertiaires)]
    assert lancer_batiment(reseau_bdnb(groupes)).bloc["usage_mixte_indice"] is attendu


def test_batiment_immatriculations_non_nulles_sans_doublon_dans_l_ordre_des_groupes():
    groupes = [
        groupe("bdnb-bg-1", nb_log=2, numero_immat_principal="AA0000002"),
        groupe("bdnb-bg-2", nb_log=9, numero_immat_principal="AA0000001"),
        groupe("bdnb-bg-3", nb_log=5, numero_immat_principal="AA0000002"),  # même copropriété que bdnb-bg-1
        groupe("bdnb-bg-4", nb_log=7, numero_immat_principal=None),
        groupe("bdnb-bg-5", nb_log=1, numero_immat_principal=""),
    ]
    assert lancer_batiment(reseau_bdnb(groupes)).bloc["immatriculations"] == ["AA0000001", "AA0000002"]


def test_batiment_sans_aucune_immatriculation_liste_vide():
    assert lancer_batiment(reseau_bdnb((G_MAISON,))).bloc["immatriculations"] == []


# --- groupe de la relation absent de la table ------------------------------------------------------------

def test_batiment_groupe_de_la_relation_sans_ligne_dans_la_table_alerte():
    r = reseau_bdnb((G_MAISON,), relation=[ID_A, ID_B])  # ID_B n'a pas de ligne dans batiment_groupe_complet
    resultat = lancer_batiment(r)
    assert resultat.bloc["n_groupes"] == 1 and resultat.bloc["groupes"] == [attendu_groupe(G_MAISON)]
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1 and ID_B in messages[0] and "batiment_groupe_complet" in messages[0]


def test_batiment_doublons_dans_la_relation_un_seul_identifiant_demande():
    r = reseau_bdnb((G_MAISON,), relation=[ID_A, ID_A])
    resultat = lancer_batiment(r)
    assert r.appels_vers(TABLE)[0].params["batiment_groupe_id"] == f"in.({ID_A})"
    assert resultat.bloc["n_groupes"] == 1 and list(resultat.alertes) == []


# --- forme inattendue ------------------------------------------------------------------------------------

LIGNE_RELATION = {"batiment_groupe_id": ID_A, "parcelle_id": PARCELLE, "parcelle_principale": True}
FORMES_RELATION = [
    pytest.param({"message": "erreur"}, id="relation-objet"),
    pytest.param(["texte"], id="relation-ligne-texte"),
    pytest.param([{"parcelle_id": PARCELLE}], id="relation-sans-id"),
    pytest.param([{**LIGNE_RELATION, "batiment_groupe_id": 12}], id="relation-id-numerique"),
    pytest.param([{**LIGNE_RELATION, "batiment_groupe_id": "a,b"}], id="relation-id-avec-virgule"),
    pytest.param([{**LIGNE_RELATION, "batiment_groupe_id": "x)"}], id="relation-id-avec-parenthese"),
    pytest.param([{**LIGNE_RELATION, "parcelle_id": "99999000ZZ9999"}], id="relation-filtre-ignore-autre-parcelle"),
    pytest.param([{"batiment_groupe_id": ID_A}], id="relation-sans-parcelle_id"),
    pytest.param([{**LIGNE_RELATION, "parcelle_principale": "oui"}], id="relation-parcelle_principale-texte"),
    pytest.param([{**LIGNE_RELATION, "parcelle_principale": 1}], id="relation-parcelle_principale-entier"),
]


@pytest.mark.parametrize("corps", FORMES_RELATION)
def test_batiment_relation_de_forme_inattendue_leve_avec_l_url(corps):
    r = Reseau().route(RELATION, json_ok(corps))
    with pytest.raises(OpendataError) as exc:
        lancer_batiment(r)
    assert "api.bdnb.io" in str(exc.value) and "rel_batiment_groupe_parcelle" in str(exc.value)
    assert r.appels_vers(TABLE) == []  # aucun appel à la table sur une relation douteuse


FORMES_TABLE = [
    pytest.param({"message": "erreur"}, id="table-objet"),
    pytest.param(["texte"], id="table-ligne-texte"),
    pytest.param([groupe(ID_A, batiment_groupe_id=None)], id="table-sans-id"),
    pytest.param([groupe("bdnb-bg-ETRANGER-0000-0000")], id="table-filtre-ignore-groupe-non-demande"),
    pytest.param([groupe(ID_A, nb_log="3")], id="table-nb_log-texte"),
    pytest.param([groupe(ID_A, nb_log=True)], id="table-nb_log-booleen"),
    pytest.param([groupe(ID_A, nb_lot_tertiaire_rnc="x")], id="table-tertiaire-texte"),
    pytest.param([groupe(ID_A, numero_immat_principal=5)], id="table-immat-numerique"),
]


@pytest.mark.parametrize("corps", FORMES_TABLE)
def test_batiment_table_de_forme_inattendue_leve_avec_l_url(corps):
    r = reseau_bdnb((G_MAISON,))
    r.route(TABLE, json_ok(corps))
    with pytest.raises(OpendataError) as exc:
        lancer_batiment(r)
    assert "api.bdnb.io" in str(exc.value) and "batiment_groupe_complet" in str(exc.value)


# --- la parcelle -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("parcelle", [
    None, "", "   ", "123", "99999000AB012", "99999000AB01234", "99999000AB012&", "99999000AB0 123",
    "99999000AB012é", "99999000AB012.", "99999000AB0123;", 12345678901234,
])
def test_batiment_parcelle_invalide_leve_sans_aucun_appel(parcelle):
    """Un identifiant douteux ne part jamais dans un filtre : les erreurs comptent dans le quota de l'API."""
    r = reseau_bdnb((G_MAISON,))
    with pytest.raises(OpendataError, match="parcelle"):
        lancer_batiment(r, parcelle)
    assert r.appels == []


@pytest.mark.parametrize("saisie", ["99999000AB0123", "99999000ab0123", " 99999000Ab0123 "])
def test_batiment_parcelle_normalisee_en_majuscules_sans_espaces(saisie):
    r = reseau_bdnb((G_MAISON,))
    resultat = lancer_batiment(r, saisie)
    assert r.appels[0].params == {"parcelle_id": f"eq.{PARCELLE}"}
    assert resultat.bloc["parcelle"] == PARCELLE and resultat.bloc["n_groupes"] == 1


# ===========================================================================
# 3. copropriete : RNIC (ANAH) par l'API tabulaire de data.gouv.fr
# ===========================================================================

HOTE_RNIC = "tabular-api.data.gouv.fr"
RNIC_RID = "3ea8e2c3-0038-464a-b17e-cd5c91f65ce2"
RNIC = f"{HOTE_RNIC}/api/resources/{RNIC_RID}/data/"
M_PAR_DEGRE = 6_371_000 * math.pi / 180  # mètres par degré de latitude (R = 6 371 000 m, comme dvf.haversine_m)
COLONNES_RNIC = (  # oracle du test : la liste utile de référence
    "numero_immatriculation", "nom_usage_copropriete", "adresse_reference", "commune", "longitude", "latitude",
    "reference_cadastrale_1", "reference_cadastrale_2", "reference_cadastrale_3", "nombre_parcelles",
    "nombre_total_lots", "nombre_lots_habitation", "nombre_lots_habitation_bureaux_commerces",
    "nombre_lots_stationnement", "periode_construction", "date_immatriculation", "date_derniere_maj", "type_syndic",
    "mandat_en_cours",  # ancien attendu : 18 colonnes, sans nombre_lots_habitation_bureaux_commerces
)
COLONNES_SYNDIC = ("identification_representant_legal", "raison_sociale_representant_legal",
                   "siret_representant_legal")
VALEURS_SYNDIC = ("SYNDIC-FICTIF-A-NE-PAS-RECOPIER", "RAISON-FICTIVE-A-NE-PAS-RECOPIER", "00000000000000")
PARCELLE_COPRO = "99999000AK0001"
ALERTE_AUCUNE = ("aucune copropriété immatriculée sur la parcelle 99999000AK0001 : "
                 "l'absence du RNIC ne prouve pas l'absence de copropriété")


def au_nord(metres: float) -> float:
    """Latitude située à `metres` mètres au nord du point géocodé (même longitude)."""
    return LAT + metres / M_PAR_DEGRE


def ligne_rnic(numero: str, *, nord_m: float | None = None, refs: tuple = (), commune: str = INSEE,
               **champs: Any) -> dict:
    """Ligne brute du RNIC : colonnes utiles FICTIVES, plus les colonnes d'identité du syndic (valeurs fictives
    qui ne doivent jamais ressortir). `nord_m` : distance au point, vers le nord ; None : pas de coordonnées."""
    references = [*refs, None, None, None][:3]
    ligne = {
        "numero_immatriculation": numero,
        "nom_usage_copropriete": f"Résidence des Essais {numero}",
        "adresse_reference": "3 Rue d'Essai 99999 Testville",
        "commune": commune,
        "longitude": None if nord_m is None else LON,
        "latitude": None if nord_m is None else au_nord(nord_m),
        "reference_cadastrale_1": references[0],
        "reference_cadastrale_2": references[1],
        "reference_cadastrale_3": references[2],
        "nombre_parcelles": 1, "nombre_total_lots": 6, "nombre_lots_habitation": 4,
        "nombre_lots_habitation_bureaux_commerces": 5, "nombre_lots_stationnement": 2,
        "periode_construction": "avant 1949", "date_immatriculation": "2017-01-15",
        "date_derniere_maj": "2026-09-30", "type_syndic": "professionnel", "mandat_en_cours": "Oui",
        **dict(zip(COLONNES_SYNDIC, VALEURS_SYNDIC)),
    }
    ligne.update(champs)
    return ligne


def sortie_attendue(ligne: dict, **extra: Any) -> dict:
    """Ligne telle que le bloc doit la rendre : colonnes utiles, références en liste, jamais le syndic."""
    references = [ligne[f"reference_cadastrale_{i}"].upper() for i in (1, 2, 3) if ligne[f"reference_cadastrale_{i}"]]
    return {
        **{c: ligne[c] for c in COLONNES_RNIC if not c.startswith("reference_cadastrale_") and c != "commune"},
        "references_cadastrales": references,
        **extra,
    }


def reseau_rnic(lignes: list[dict], *, taille_page: int = 200, filtre_ignore: bool = False,
                colonnes_ignorees: bool = False) -> Reseau:
    """Faux serveur de l'API tabulaire : filtre `commune__exact`, pages de `taille_page` lignes, `links.next`
    complet (même requête, `page` incrémentée), `meta.total`. `colonnes_ignorees` : renvoie toutes les colonnes
    (syndic compris) même si `columns` est demandé ; `filtre_ignore` : renvoie les lignes de toutes les communes."""
    def repondre(requete: httpx.Request) -> httpx.Response:
        params = dict(requete.url.params)
        insee = params.get("commune__exact")
        retenues = [ligne for ligne in lignes if filtre_ignore or insee is None or str(ligne["commune"]) == insee]
        page = int(params.get("page", "1"))
        morceau = retenues[(page - 1) * taille_page: page * taille_page]
        if params.get("columns") and not colonnes_ignorees:
            morceau = [{c: ligne.get(c) for c in params["columns"].split(",")} for ligne in morceau]
        a_une_suite = page * taille_page < len(retenues)
        suivante = str(requete.url.copy_set_param("page", str(page + 1))) if a_une_suite else None
        return httpx.Response(200, json={
            "data": morceau,
            "links": {"profile": f"https://{HOTE_RNIC}/api/resources/{RNIC_RID}/profile/", "next": suivante,
                      "prev": None},
            "meta": {"page": page, "page_size": taille_page, "total": len(retenues)},
        })

    return Reseau().route(RNIC, repondre)


def page_json(lignes: list[dict], *, suivante: Any = None, total: Any = ..., links: Any = ...) -> dict:
    return {
        "data": lignes,
        "links": {"next": suivante} if links is ... else links,
        "meta": {"total": len(lignes) if total is ... else total},
    }


def lancer_copropriete(r: Reseau, parcelle: Any = PARCELLE_COPRO, geo: dict | None = None) -> Resultat:
    return copropriete.collecter(r.client(), geo or GEO, parcelle, sleep=r.sleep)


def parametres_attendus(**changements: Any) -> dict:
    base = {"insee": INSEE, "parcelle": PARCELLE_COPRO, "rayon_voisines_m": 50, "max_voisines": 5, "page_size": 200,
            "max_pages": 20, "pages_lues": 1, "lignes_lues": 0, "sans_coordonnees": 0, "voisines_dans_le_rayon": 0}
    return {**base, **changements}


def test_copropriete_nominal_bloc_complet():
    sur = ligne_rnic("AA0000001", nord_m=20, refs=("99999000ak0001",))  # en minuscules dans le RNIC
    proche = ligne_rnic("AA0000002", nord_m=42, refs=("99999000AT0507",))
    plus_proche = ligne_rnic("AA0000003", nord_m=30, refs=("99999000AK0002",))
    loin = ligne_rnic("AA0000004", nord_m=500, refs=("99999000ZZ0001",))
    sans_coordonnees = ligne_rnic("AA0000005")
    r = reseau_rnic([loin, proche, sans_coordonnees, sur, plus_proche])
    resultat = lancer_copropriete(r)
    assert resultat.bloc == {
        "n_commune": 5,
        "sur_la_parcelle": [sortie_attendue(sur)],
        "voisines": [sortie_attendue(plus_proche, distance_m=30.0), sortie_attendue(proche, distance_m=42.0)],
        "correspondance": "parcelle",
        "parametres": parametres_attendus(lignes_lues=5, sans_coordonnees=1, voisines_dans_le_rayon=2),
    }
    assert resultat.erreurs == [] and list(resultat.alertes) == []
    assert resultat.sources == [copropriete.SOURCE]


def test_copropriete_nombre_lots_habitation_bureaux_commerces_est_demande_et_rendu():
    """La colonne est demandée (`columns`) et rendue telle quelle ; absente d'une ligne : null."""
    sur = ligne_rnic("AA0000001", nord_m=10, refs=(PARCELLE_COPRO,), nombre_lots_habitation_bureaux_commerces=7)
    voisine = ligne_rnic("AA0000002", nord_m=20)
    sans_colonne = ligne_rnic("AA0000003", nord_m=30)
    del sans_colonne["nombre_lots_habitation_bureaux_commerces"]
    r = reseau_rnic([sur, voisine, sans_colonne])
    bloc = lancer_copropriete(r).bloc
    assert "nombre_lots_habitation_bureaux_commerces" in r.appels[0].params["columns"].split(",")
    assert bloc["sur_la_parcelle"][0]["nombre_lots_habitation_bureaux_commerces"] == 7
    voisines = {v["numero_immatriculation"]: v for v in bloc["voisines"]}
    assert voisines["AA0000002"]["nombre_lots_habitation_bureaux_commerces"] == 5
    assert voisines["AA0000003"]["nombre_lots_habitation_bureaux_commerces"] is None


def test_copropriete_source_et_constantes():
    assert copropriete.RESSOURCE == RNIC_RID
    assert copropriete.URL == f"https://{RNIC}"
    assert copropriete.SOURCE == {"bloc": "copropriete", "url": copropriete.URL, "licence": copropriete.LICENCE,
                                  "millesime": None}
    assert "Licence Ouverte 2.0" in copropriete.LICENCE
    assert (copropriete.RNIC_PAGE_SIZE, copropriete.RNIC_MAX_PAGES) == (200, 20)
    assert (copropriete.RAYON_VOISINES_M, copropriete.NB_VOISINES_MAX) == (50, 5)
    assert tuple(copropriete.COLONNES) == COLONNES_RNIC


# --- la requête : l'API tabulaire, filtrée par commune, colonnes restreintes, jamais le fichier national -------

def test_copropriete_requete_filtree_par_commune_colonnes_utiles_et_page_de_200():
    r = reseau_rnic([ligne_rnic("AA0000001", nord_m=10)])
    lancer_copropriete(r)
    assert [a.cle for a in r.appels] == [RNIC]
    assert r.appels[0].params == {"commune__exact": INSEE, "page_size": "200", "columns": ",".join(COLONNES_RNIC)}
    assert r.appels[0].url.startswith(f"https://{RNIC}?")


def test_copropriete_colonnes_demandees_sans_aucune_identite_de_syndic():
    r = reseau_rnic([ligne_rnic("AA0000001", nord_m=10)])
    lancer_copropriete(r)
    demandees = set(r.appels[0].params["columns"].split(","))
    assert demandees == set(COLONNES_RNIC)
    assert not demandees & set(COLONNES_SYNDIC)
    assert not set(copropriete.COLONNES) & set(COLONNES_SYNDIC)


@pytest.mark.parametrize("colonnes_ignorees", [False, True])
def test_copropriete_aucune_identite_de_syndic_dans_le_bloc_meme_si_l_api_les_renvoie(colonnes_ignorees):
    """`columns` ignoré par le serveur : le bloc ne recopie QUE les colonnes utiles."""
    sur = ligne_rnic("AA0000001", nord_m=10, refs=(PARCELLE_COPRO,))
    r = reseau_rnic([sur, ligne_rnic("AA0000002", nord_m=20)], colonnes_ignorees=colonnes_ignorees)
    texte = json.dumps(lancer_copropriete(r).bloc, ensure_ascii=False)
    for valeur in VALEURS_SYNDIC:
        assert valeur not in texte
    for colonne in COLONNES_SYNDIC:
        assert colonne not in texte


# --- correspondance à la parcelle : la casse ---------------------------------------------------------------

def test_copropriete_reference_cadastrale_en_minuscules_correspond_a_la_parcelle():
    """Le RNIC écrit parfois une référence en minuscules : comparaison en majuscules, des deux côtés."""
    sur = ligne_rnic("AA0000001", nord_m=10, refs=("99999000ak0001",))
    resultat = lancer_copropriete(reseau_rnic([sur]), "99999000AK0001")
    assert [c["numero_immatriculation"] for c in resultat.bloc["sur_la_parcelle"]] == ["AA0000001"]
    assert resultat.bloc["correspondance"] == "parcelle"
    assert sortie_attendue(sur)["references_cadastrales"] == ["99999000AK0001"]
    assert resultat.bloc["sur_la_parcelle"][0]["references_cadastrales"] == ["99999000AK0001"]


def test_copropriete_parcelle_donnee_en_minuscules_correspond_a_une_reference_en_majuscules():
    sur = ligne_rnic("AA0000001", nord_m=10, refs=("99999000AK0001",))
    resultat = lancer_copropriete(reseau_rnic([sur]), "99999000ak0001")
    assert resultat.bloc["correspondance"] == "parcelle"
    assert resultat.bloc["parametres"]["parcelle"] == "99999000AK0001"


@pytest.mark.parametrize("reference", ["99999 000 ak 0001", " 99999000AK0001 ", "99999000Ak0001\t"])
def test_copropriete_references_avec_espaces_ou_casse_mixte_correspondent(reference):
    sur = ligne_rnic("AA0000001", nord_m=10, refs=(reference,))
    assert lancer_copropriete(reseau_rnic([sur])).bloc["correspondance"] == "parcelle"


@pytest.mark.parametrize("rang", [0, 1, 2])
def test_copropriete_la_parcelle_peut_etre_la_premiere_la_deuxieme_ou_la_troisieme_reference(rang):
    refs = ["99999000ZZ0001", "99999000ZZ0002", "99999000ZZ0003"]
    refs[rang] = "99999000ak0001"
    sur = ligne_rnic("AA0000001", nord_m=10, refs=tuple(refs))
    resultat = lancer_copropriete(reseau_rnic([sur]))
    assert resultat.bloc["correspondance"] == "parcelle"
    assert len(resultat.bloc["sur_la_parcelle"][0]["references_cadastrales"]) == 3


@pytest.mark.parametrize("reference", [
    "99999000AK0002",  # parcelle voisine, un chiffre de plus
    "99999000AL0530",  # autre section
    "99999000AK000",  # numéro tronqué
    "99999000AK00010",  # référence plus longue qui contient la parcelle
    "", None, "   ",
])
def test_copropriete_reference_differente_ou_vide_ne_correspond_pas(reference):
    ligne = ligne_rnic("AA0000001", nord_m=10, refs=(reference,))
    resultat = lancer_copropriete(reseau_rnic([ligne]))
    assert resultat.bloc["sur_la_parcelle"] == [] and resultat.bloc["correspondance"] == "aucune"


# --- correspondance : parcelle, aucune, parcelle inconnue --------------------------------------------------

def test_copropriete_correspondance_parcelle_sans_alerte():
    sur = ligne_rnic("AA0000001", nord_m=10, refs=(PARCELLE_COPRO,))
    resultat = lancer_copropriete(reseau_rnic([sur]))
    assert resultat.bloc["correspondance"] == "parcelle" and list(resultat.alertes) == []


def test_copropriete_correspondance_aucune_alerte_l_absence_du_rnic_ne_prouve_rien():
    autre = ligne_rnic("AA0000002", nord_m=42, refs=("99999000AT0507",))
    resultat = lancer_copropriete(reseau_rnic([autre]))
    assert resultat.bloc["correspondance"] == "aucune" and resultat.bloc["sur_la_parcelle"] == []
    assert [a["message"] for a in resultat.alertes] == [ALERTE_AUCUNE]
    assert [a["bloc"] for a in resultat.alertes] == ["copropriete"]
    # la voisine reste listée : l'absence sur la parcelle n'efface pas ce qui est à côté
    assert [v["numero_immatriculation"] for v in resultat.bloc["voisines"]] == ["AA0000002"]


@pytest.mark.parametrize("parcelle", [None, "", "   "])
def test_copropriete_parcelle_inconnue_pas_de_correspondance_possible(parcelle):
    voisine = ligne_rnic("AA0000002", nord_m=42, refs=(PARCELLE_COPRO,))  # même sans parcelle, pas de faux « sur »
    resultat = lancer_copropriete(reseau_rnic([voisine]), parcelle)
    assert resultat.bloc["correspondance"] == "parcelle inconnue"
    assert resultat.bloc["sur_la_parcelle"] == []
    assert resultat.bloc["parametres"]["parcelle"] is None
    assert [v["numero_immatriculation"] for v in resultat.bloc["voisines"]] == ["AA0000002"]
    messages = [a["message"] for a in resultat.alertes]
    assert len(messages) == 1 and "parcelle inconnue" in messages[0]
    assert "ne prouve pas l'absence de copropriété" in messages[0]


def test_copropriete_parcelle_non_textuelle_leve():
    with pytest.raises(OpendataError, match="parcelle"):
        lancer_copropriete(reseau_rnic([]), 12345678901234)


# --- voisines : rayon, tri, plafond de 5, lignes sans coordonnées ---------------------------------------------

@pytest.mark.parametrize("metres, dedans", [(1, True), (30, True), (49, True), (51, False), (60, False), (500, False)])
def test_copropriete_voisine_dans_le_rayon_de_50_m_ou_dehors(metres, dedans):
    ligne = ligne_rnic("AA0000002", nord_m=metres, refs=("99999000AT0507",))
    voisines = lancer_copropriete(reseau_rnic([ligne])).bloc["voisines"]
    assert [v["numero_immatriculation"] for v in voisines] == (["AA0000002"] if dedans else [])
    if dedans:
        assert voisines[0]["distance_m"] == pytest.approx(metres, abs=0.06)


def a_l_est(metres: float) -> float:
    """Longitude située à `metres` mètres à l'est du point géocodé (même latitude)."""
    return LON + math.degrees(metres / (6_371_000 * math.cos(math.radians(LAT))))


@pytest.mark.parametrize("est_m, nord_m, attendu_m", [
    (40, 0, 40.0), (0, 40, 40.0), (-40, 0, 40.0), (24, 32, 40.0), (-24, -32, 40.0), (36, 48, 60.0), (60, 0, 60.0),
])
def test_copropriete_distance_juste_vers_l_est_l_ouest_et_en_diagonale(est_m, nord_m, attendu_m):
    """Une longitude et une latitude permutées dans la distance ne se voient pas vers le nord ; vers l'est, si."""
    ligne = ligne_rnic("AA0000001", longitude=a_l_est(est_m), latitude=au_nord(nord_m))
    resultat = lancer_copropriete(reseau_rnic([ligne]))
    if attendu_m <= 50:
        assert [v["distance_m"] for v in resultat.bloc["voisines"]] == [pytest.approx(attendu_m, abs=0.1)]
    else:
        assert resultat.bloc["voisines"] == [] and resultat.bloc["parametres"]["voisines_dans_le_rayon"] == 0


def test_copropriete_voisines_triees_par_distance_puis_numero():
    lignes = [ligne_rnic("AA0000009", nord_m=40), ligne_rnic("AA0000002", nord_m=10),
              ligne_rnic("AA0000008", nord_m=40), ligne_rnic("AA0000005", nord_m=25)]
    voisines = lancer_copropriete(reseau_rnic(lignes)).bloc["voisines"]
    assert [v["numero_immatriculation"] for v in voisines] == ["AA0000002", "AA0000005", "AA0000008", "AA0000009"]
    assert [v["distance_m"] for v in voisines] == [10.0, 25.0, 40.0, 40.0]


def test_copropriete_cinq_voisines_au_plus_et_une_alerte_si_plus():
    lignes = [ligne_rnic(f"AA000000{i}", nord_m=5 * i) for i in range(1, 9)]  # 8 copropriétés de 5 à 40 m
    resultat = lancer_copropriete(reseau_rnic(lignes))
    assert [v["distance_m"] for v in resultat.bloc["voisines"]] == [5.0, 10.0, 15.0, 20.0, 25.0]
    assert resultat.bloc["parametres"]["voisines_dans_le_rayon"] == 8
    messages = [a["message"] for a in resultat.alertes if "voisin" in a["message"] or "à moins de" in a["message"]]
    assert any("8" in m and "5 plus proches" in m for m in messages)


def test_copropriete_cinq_voisines_exactement_pas_d_alerte_de_plafond():
    lignes = [ligne_rnic(f"AA000000{i}", nord_m=5 * i, refs=(PARCELLE_COPRO,) if i == 1 else ())
              for i in range(1, 7)]  # 6 dans le rayon, dont 1 sur la parcelle (exclue des voisines) -> 5 voisines
    resultat = lancer_copropriete(reseau_rnic(lignes))
    assert len(resultat.bloc["voisines"]) == 5 and list(resultat.alertes) == []


def test_copropriete_la_copropriete_de_la_parcelle_n_est_pas_comptee_parmi_les_voisines():
    sur = ligne_rnic("AA0000001", nord_m=10, refs=(PARCELLE_COPRO,))
    autre = ligne_rnic("AA0000002", nord_m=20, refs=("99999000AT0507",))
    bloc = lancer_copropriete(reseau_rnic([sur, autre])).bloc
    assert [c["numero_immatriculation"] for c in bloc["sur_la_parcelle"]] == ["AA0000001"]
    assert [v["numero_immatriculation"] for v in bloc["voisines"]] == ["AA0000002"]


@pytest.mark.parametrize("coordonnees", [
    {"longitude": None, "latitude": None}, {"longitude": LON, "latitude": None}, {"longitude": None, "latitude": LAT},
    {"longitude": LON, "latitude": ""}, {"longitude": LON, "latitude": "abc"}, {"longitude": "", "latitude": ""},
    {"longitude": LON, "latitude": 95.0}, {"longitude": 200.0, "latitude": LAT}, {"longitude": True, "latitude": LAT},
])
def test_copropriete_ligne_sans_coordonnees_utilisables_comptee_et_exclue_des_voisines(coordonnees):
    sans = ligne_rnic("AA0000001", nord_m=10, **coordonnees)
    avec = ligne_rnic("AA0000002", nord_m=10)
    resultat = lancer_copropriete(reseau_rnic([sans, avec]))
    assert [v["numero_immatriculation"] for v in resultat.bloc["voisines"]] == ["AA0000002"]
    assert resultat.bloc["parametres"]["sans_coordonnees"] == 1
    assert resultat.bloc["parametres"]["lignes_lues"] == 2


def test_copropriete_coordonnees_en_texte_numerique_acceptees():
    ligne = ligne_rnic("AA0000001", nord_m=10, longitude=str(LON), latitude=str(au_nord(10)))
    voisines = lancer_copropriete(reseau_rnic([ligne])).bloc["voisines"]
    assert len(voisines) == 1 and voisines[0]["distance_m"] == pytest.approx(10, abs=0.06)
    assert isinstance(voisines[0]["latitude"], float)


def test_copropriete_ligne_sans_coordonnees_mais_sur_la_parcelle_reste_sur_la_parcelle():
    sur = ligne_rnic("AA0000001", refs=(PARCELLE_COPRO,))  # aucune coordonnée
    resultat = lancer_copropriete(reseau_rnic([sur]))
    assert resultat.bloc["correspondance"] == "parcelle"
    assert resultat.bloc["parametres"]["sans_coordonnees"] == 1
    assert resultat.bloc["sur_la_parcelle"][0]["longitude"] is None


# --- pagination par links.next, plafond de pages ---------------------------------------------------------------

def test_copropriete_pagination_suit_links_next_jusqu_a_la_derniere_page():
    lignes = [ligne_rnic(f"AA000000{i}", nord_m=100 * i) for i in range(1, 5)]
    lignes.append(ligne_rnic("AA0000009", nord_m=10, refs=(PARCELLE_COPRO,)))  # sur la 3e page
    r = reseau_rnic(lignes, taille_page=2)
    resultat = lancer_copropriete(r)
    assert [a.cle for a in r.appels] == [RNIC] * 3
    assert "page" not in r.appels[0].params
    assert [a.params["page"] for a in r.appels[1:]] == ["2", "3"]
    assert all(a.params["commune__exact"] == INSEE and a.params["columns"] == ",".join(COLONNES_RNIC)
               for a in r.appels)
    assert resultat.bloc["n_commune"] == 5 and resultat.bloc["correspondance"] == "parcelle"
    assert resultat.bloc["parametres"]["pages_lues"] == 3 and resultat.bloc["parametres"]["lignes_lues"] == 5
    assert list(resultat.alertes) == []


@pytest.mark.parametrize("rang", [1, 2])
def test_copropriete_chaque_page_est_rejouee_apres_une_panne_avec_le_sleep_injecte(rang):
    lignes = [ligne_rnic(f"AA000000{i}", nord_m=100 * i) for i in range(1, 4)]
    reference = lancer_copropriete(reseau_rnic(lignes, taille_page=2)).bloc
    r = reseau_rnic(lignes, taille_page=2).panne_au_appel(RNIC, rang)
    assert lancer_copropriete(r).bloc == reference
    assert len(r.appels) == 3 and r.attentes == [1]  # 2 pages + l'appel qui a échoué


def test_copropriete_lien_page_suivante_vers_un_autre_hote_refuse_et_non_suivi():
    premiere = page_json([ligne_rnic("AA0000001", nord_m=10)], suivante="https://autre-hote.example/data/?page=2")
    r = Reseau().route(RNIC, json_ok(premiere))
    with pytest.raises(OpendataError, match="autre-hote.example"):
        lancer_copropriete(r)
    assert len(r.appels) == 1  # aucune requête vers l'hôte étranger


def test_copropriete_lien_page_suivante_meme_hote_en_http_est_suivi():
    deuxieme = page_json([ligne_rnic("AA0000002", nord_m=10)])
    premiere = page_json([ligne_rnic("AA0000001", nord_m=10)], suivante=f"http://{RNIC}?page=2", total=2)
    r = Reseau().route(RNIC, [json_ok(premiere), json_ok(deuxieme)])
    resultat = lancer_copropriete(r)
    assert resultat.bloc["parametres"]["pages_lues"] == 2 and len(r.appels) == 2
    assert r.appels[1].url.startswith("https://")  # le lien en http est repassé en https avant d'être suivi


@pytest.mark.parametrize("lien", ["ftp://tabular-api.data.gouv.fr/api/x?page=2", "https://[::1/x",
                                  "//autre-hote.example/x"])
def test_copropriete_lien_page_suivante_illisible_ou_d_un_autre_protocole_refuse(lien):
    premiere = page_json([ligne_rnic("AA0000001", nord_m=10)], suivante=lien)
    r = Reseau().route(RNIC, json_ok(premiere))
    with pytest.raises(OpendataError, match="lien de page suivante"):
        lancer_copropriete(r)
    assert len(r.appels) == 1


def test_copropriete_lien_page_suivante_relatif_reste_sur_l_hote_de_l_api():
    deuxieme = page_json([ligne_rnic("AA0000002", nord_m=10)])
    premiere = page_json([ligne_rnic("AA0000001", nord_m=10)], suivante=f"/api/resources/{RNIC_RID}/data/?page=2",
                         total=2)
    r = Reseau().route(RNIC, [json_ok(premiere), json_ok(deuxieme)])
    assert lancer_copropriete(r).bloc["parametres"]["pages_lues"] == 2
    assert r.appels[1].url == f"https://{RNIC}?page=2"


def test_copropriete_plafond_de_pages_alerte_et_arret(monkeypatch):
    monkeypatch.setattr(copropriete, "RNIC_MAX_PAGES", 3)
    lignes = [ligne_rnic(f"AA00000{i:02d}", nord_m=200 + i) for i in range(10)]
    lignes[8] = ligne_rnic("AA0000099", nord_m=10, refs=(PARCELLE_COPRO,))  # page 5 : jamais lue
    r = reseau_rnic(lignes, taille_page=2)
    resultat = lancer_copropriete(r)
    assert len(r.appels) == 3
    assert resultat.bloc["parametres"]["pages_lues"] == 3 and resultat.bloc["parametres"]["lignes_lues"] == 6
    assert resultat.bloc["parametres"]["max_pages"] == 3
    assert resultat.bloc["n_commune"] == 10
    messages = [a["message"] for a in resultat.alertes]
    assert any("plafond de 3 pages" in m and "6 lignes lues sur 10" in m for m in messages)


def test_copropriete_exactement_au_plafond_de_pages_sans_page_suivante_aucune_alerte(monkeypatch):
    monkeypatch.setattr(copropriete, "RNIC_MAX_PAGES", 3)
    lignes = [ligne_rnic(f"AA00000{i:02d}", nord_m=200 + i) for i in range(6)]  # 3 pages pleines, la 3e sans suite
    r = reseau_rnic(lignes, taille_page=2)
    resultat = lancer_copropriete(r)
    assert len(r.appels) == 3
    assert [a for a in resultat.alertes if "plafond" in a["message"]] == []


def test_copropriete_plafond_reel_de_vingt_pages():
    lignes = [ligne_rnic(f"AA{i:07d}", nord_m=300) for i in range(25)]
    r = reseau_rnic(lignes, taille_page=1)  # 25 pages de 1 ligne : le code s'arrête à la 20e
    resultat = lancer_copropriete(r)
    assert len(r.appels) == 20
    assert resultat.bloc["parametres"]["pages_lues"] == 20 and resultat.bloc["parametres"]["lignes_lues"] == 20
    assert any("plafond de 20 pages" in a["message"] for a in resultat.alertes)


def test_copropriete_total_annonce_different_des_lignes_lues_alerte():
    r = Reseau().route(RNIC, json_ok(page_json([ligne_rnic("AA0000001", nord_m=10)] * 5, total=7)))
    resultat = lancer_copropriete(r)
    assert resultat.bloc["n_commune"] == 7
    messages = [a["message"] for a in resultat.alertes if "annoncées" in a["message"]]
    assert len(messages) == 1 and "7" in messages[0] and "5 lues" in messages[0]


# --- vide, refus de l'API, filtre ignoré --------------------------------------------------------------------

def test_copropriete_commune_sans_aucune_copropriete_immatriculee():
    resultat = lancer_copropriete(reseau_rnic([]))
    assert resultat.bloc == {
        "n_commune": 0, "sur_la_parcelle": [], "voisines": [], "correspondance": "aucune",
        "parametres": parametres_attendus(),
    }
    assert [a["message"] for a in resultat.alertes] == [ALERTE_AUCUNE]


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
def test_copropriete_api_qui_refuse_la_ressource_leve_sans_repli_sur_le_fichier_national(code):
    r = Reseau().route(RNIC, statut_http(code))
    with pytest.raises(OpendataError, match=f"HTTP {code}"):
        lancer_copropriete(r)
    assert [a.cle for a in r.appels] == [RNIC]  # un seul appel, uniquement l'API tabulaire
    assert r.attentes == []


def test_copropriete_429_est_rejoue_ce_n_est_pas_un_refus_puis_leve_s_il_persiste():
    r = Reseau().route(RNIC, statut_http(429))
    with pytest.raises(OpendataError, match="429"):
        lancer_copropriete(r)
    assert len(r.appels) == 3 and r.attentes == [1, 2]
    ok = reseau_rnic([ligne_rnic("AA0000001", nord_m=10)])
    ok.route(RNIC, [statut_http(429), json_ok(page_json([ligne_rnic("AA0000001", nord_m=10)]))])
    assert lancer_copropriete(ok).bloc["n_commune"] == 1


def test_copropriete_filtre_commune_ignore_leve():
    autre_commune = ligne_rnic("AA0000002", nord_m=10, commune="88888")
    r = reseau_rnic([ligne_rnic("AA0000001", nord_m=10), autre_commune], filtre_ignore=True)
    with pytest.raises(OpendataError, match="filtre commune ignoré"):
        lancer_copropriete(r)


def test_copropriete_commune_numerique_dans_la_ligne_est_comparee_comme_texte():
    r = Reseau().route(RNIC, json_ok(page_json([ligne_rnic("AA0000001", nord_m=10, commune=int(INSEE))])))
    assert lancer_copropriete(r).bloc["n_commune"] == 1


# --- forme inattendue ------------------------------------------------------------------------------------------

LIGNE_OK = ligne_rnic("AA0000001", nord_m=10)
FORMES_RNIC = [
    pytest.param(["pas", "un", "objet"], id="corps-liste"),
    pytest.param({"links": {"next": None}, "meta": {"total": 0}}, id="sans-data"),
    pytest.param({**page_json([]), "data": {"a": 1}}, id="data-objet"),
    pytest.param(page_json(["texte"]), id="ligne-texte"),
    pytest.param(page_json([LIGNE_OK], links=None), id="links-nul"),
    pytest.param(page_json([LIGNE_OK], links={}), id="links-sans-next"),
    pytest.param(page_json([LIGNE_OK], suivante=5), id="next-numerique"),
    pytest.param(page_json([LIGNE_OK], suivante=""), id="next-vide"),
    pytest.param({"data": [LIGNE_OK], "links": {"next": None}}, id="sans-meta"),
    pytest.param({"data": [LIGNE_OK], "links": {"next": None}, "meta": {}}, id="meta-sans-total"),
    pytest.param(page_json([LIGNE_OK], total="1"), id="total-texte"),
    pytest.param(page_json([LIGNE_OK], total=True), id="total-booleen"),
]


@pytest.mark.parametrize("corps", FORMES_RNIC)
def test_copropriete_forme_inattendue_leve_avec_l_url(corps):
    r = Reseau().route(RNIC, json_ok(corps))
    with pytest.raises(OpendataError) as exc:
        lancer_copropriete(r)
    assert HOTE_RNIC in str(exc.value)


def test_la_distance_est_importee_de_dvf_pas_reecrite():
    """`dvf.haversine_m` existe déjà : urbanisme et copropriete l'importent."""
    from src.opendata import dvf

    assert copropriete.haversine_m is dvf.haversine_m
    assert urbanisme.haversine_m is dvf.haversine_m
