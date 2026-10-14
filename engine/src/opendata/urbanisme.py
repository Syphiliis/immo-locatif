"""Urbanisme d'un point : document, zone, prescriptions, servitudes.

Source : API Carto de l'IGN, module GPU (Géoportail de l'urbanisme), sans clé ni quota publié. Documentation :
https://apicarto.ign.fr/api/doc/gpu.yml (lue le 2026-10-08 : elle n'indique ni quota ni licence). Sept appels GET
par fiche sur `https://apicarto.ign.fr/api/gpu/<endpoint>`, dans cet ordre :
`municipality` (par INSEE), `document` et `zone-urba` (au point), `prescription-surf`, `prescription-lin` et
`prescription-pct` (sur un carré autour du point), `assiette-sup-s` (au point).

Particularités de l'API, constatées sur des réponses réelles le 07/10/2026 et rejouées le 08/10/2026 (quatre
communes de Département-Exemple) :
- `geom` est un GeoJSON passé en paramètre, LONGITUDE d'abord. Longitude et latitude inversées : HTTP 200 et
  `features: []`, sans erreur (un vide ne prouve donc pas que la requête était juste) ; `geom` mal formé : 400.
  `_limit` et `_start` sont ignorés : aucune pagination.
- les prescriptions se cherchent sur un carré de ±`DEMI_COTE_DEG` degrés autour du point, car au point seul l'API
  n'a rien rendu sur une commune testée (07/10/2026) : ce carré est une convention de méthode de ce module, pas
  une règle de l'API. Il ramène aussi des prescriptions voisines, et la même prescription revient plusieurs fois
  avec des `gid` différents : dédoublonnage sur (nature, libelle, typepsc, stypepsc, txt). `typepsc` est peu
  fiable (99 sur « Linéaires d'exemple à protéger ») : le libellé et `txt` font foi.
- la date d'approbation du document est le suffixe `_AAAAMMJJ` de `idurba` ; `datappro` est vide et `datvalid`
  n'est pas une date d'approbation. `idurba` écrit parfois « PLUI » là où `document.name` écrit « PLUi » :
  toute comparaison entre les deux doit se faire sans la casse (ce module n'en fait aucune).
- le texte de certaines servitudes est mal encodé (UTF-8 relu en latin-1 : « Eglise Saint-ExemplÃ© ») : il est
  réparé si « Ã » y figure et que la réparation réussit, laissé brut sinon (un texte passé par cp1252, comme
  « Ã‰ », reste donc brut).
- `assiette-sup-s` : `suptype` arrive en minuscules (`ac1`, `pm1`), rendu en majuscules. PM1 est l'ENVELOPPE du
  plan de prévention des risques : elle ne dit pas la zone (rouge, bleue), qui se lit au règlement du plan.
  `paramcalc` (rendu `parametre`) est le paramètre de calcul de l'assiette (500 pour une AC1 en « Zone tampon »
  ; l'API n'en donne pas l'unité). `assiette-sup-l` et `assiette-sup-p` (servitudes linéaires et ponctuelles)
  ne sont pas lues.
- une commune inconnue de `municipality` rend HTTP 400 (« Invalid INSEE code »), pas un 200 vide.
- le texte de certains champs est déjà dégradé à la source (« d?inondation » dans le nom d'un PPRI
  observé) : aucune réparation n'est possible, il est rendu tel quel.
- les réponses PM1 pèsent environ 270 Ko (1 à 3 s).

Portée : zone et servitudes sont lues AU POINT géocodé, les prescriptions sur le carré ; le bloc le dit dans
`portee`, avec la taille du carré à la latitude du point. Une liste vide ne prouve pas l'absence de servitude.

Un échec (réseau, 4xx, forme inattendue) lève `OpendataError` pour tout le bloc : jamais de bloc partiel, qui
laisserait lire « aucune servitude » alors que l'appel a échoué.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from src.opendata.dvf import haversine_m
from src.opendata.http import OpendataError, Resultat, get_json

URL = "https://apicarto.ign.fr/api/gpu"
LICENCE = (
    "Licence Ouverte / Open Licence 2.0 (jeu « Documents d'urbanisme - GPU » sur data.gouv.fr, lu le 2026-10-08) - "
    "API Carto (IGN), module Géoportail de l'urbanisme ; l'API conserve la licence des sources"
)
SOURCE = {"bloc": "urbanisme", "url": URL, "licence": LICENCE, "millesime": None}
DEMI_COTE_DEG = 0.00025  # demi-côté du carré des prescriptions : environ 37 x 56 m à 48 degrés de latitude
REGLEMENT_URL = "https://www.geoportail-urbanisme.gouv.fr/api/document/{gpu_doc_id}/files/{nomfic}"
NATURES_PRESCRIPTION = (("surf", "prescription-surf"), ("lin", "prescription-lin"), ("pct", "prescription-pct"))
_SUFFIXE_DATE = re.compile(r"_(\d{8})$")


def _forme(url: str, detail: str) -> OpendataError:
    return OpendataError(f"forme inattendue sur {url} : {detail}")


def _reparer(texte: str) -> str:
    """UTF-8 relu en latin-1 (« ExemplÃ© ») -> « Exemplé » ; le texte brut si « Ã » est absent ou si la
    réparation échoue (caractère hors latin-1, octets qui ne forment pas de l'UTF-8)."""
    if "Ã" not in texte:
        return texte
    try:
        return texte.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texte


def _proprietes(donnees: Any, url: str) -> list[dict]:
    """`properties` de chaque entité d'une FeatureCollection ; OpendataError si la forme n'est pas celle-là."""
    if not isinstance(donnees, dict) or not isinstance(donnees.get("features"), list):
        raise _forme(url, "clé « features » absente ou non liste")
    liste = []
    for entite in donnees["features"]:
        proprietes = entite.get("properties") if isinstance(entite, dict) else None
        if not isinstance(proprietes, dict):
            raise _forme(url, "entité sans « properties »")
        liste.append(proprietes)
    return liste


def _obligatoire(proprietes: dict, cle: str, url: str) -> str:
    """Texte indispensable, réparé ; OpendataError s'il manque, est vide ou n'est pas une chaîne."""
    valeur = proprietes.get(cle)
    if not isinstance(valeur, str) or not valeur.strip():
        raise _forme(url, f"champ « {cle} » absent ou non textuel")
    return _reparer(valeur)


def _facultatif(proprietes: dict, cle: str) -> Any:
    """Valeur facultative : texte réparé, autre type conservé tel quel, absent ou vide -> None (une absence)."""
    valeur = proprietes.get(cle)
    if isinstance(valeur, str):
        return _reparer(valeur) if valeur.strip() else None
    return valeur


def _date_approbation(idurba: Any) -> str | None:
    """Date d'approbation (ISO) tirée du suffixe `_AAAAMMJJ` de `idurba` ; None si absent ou illisible."""
    suffixe = _SUFFIXE_DATE.search(idurba.strip()) if isinstance(idurba, str) else None
    if suffixe is None:
        return None
    brut = suffixe.group(1)
    try:
        return date(int(brut[:4]), int(brut[4:6]), int(brut[6:])).isoformat()
    except ValueError:
        return None


def _reglement_url(gpu_doc_id: Any, nomfic: Any) -> str | None:
    """Lien du règlement écrit au Géoportail de l'urbanisme ; None s'il manque l'un des deux éléments."""
    if not (isinstance(gpu_doc_id, str) and gpu_doc_id.strip() and isinstance(nomfic, str) and nomfic.strip()):
        return None
    return REGLEMENT_URL.format(gpu_doc_id=quote(gpu_doc_id.strip(), safe=""), nomfic=quote(nomfic.strip(), safe=""))


def _point(geo: dict) -> str:
    return json.dumps({"type": "Point", "coordinates": [geo["lon"], geo["lat"]]}, separators=(",", ":"))


def _carre(geo: dict) -> str:
    """Carré de ±DEMI_COTE_DEG autour du point : un anneau fermé, dans le sens inverse des aiguilles d'une montre."""
    lon, lat = geo["lon"], geo["lat"]
    ouest, est = round(lon - DEMI_COTE_DEG, 7), round(lon + DEMI_COTE_DEG, 7)
    sud, nord = round(lat - DEMI_COTE_DEG, 7), round(lat + DEMI_COTE_DEG, 7)
    anneau = [[ouest, sud], [est, sud], [est, nord], [ouest, nord], [ouest, sud]]
    return json.dumps({"type": "Polygon", "coordinates": [anneau]}, separators=(",", ":"))


def _commune(client: httpx.Client, insee: str, sleep: Callable[[float], Any]) -> dict:
    url = f"{URL}/municipality"
    entites = _proprietes(get_json(client, url, {"insee": insee}, sleep=sleep), url)
    if not entites:
        raise OpendataError(f"commune {insee} absente de l'API Carto GPU ({url})")
    commune = entites[0]
    if commune.get("insee") != insee:  # filtre ignoré : on tiendrait le statut RNU d'une autre commune
        raise OpendataError(f"filtre commune ignoré sur {url} : insee={commune.get('insee')!r}, attendu {insee}")
    rnu, supprimee = commune.get("is_rnu"), commune.get("is_deleted")
    if not isinstance(rnu, bool):
        raise _forme(url, "champ « is_rnu » absent ou non booléen")
    if supprimee is not None and not isinstance(supprimee, bool):
        raise _forme(url, "champ « is_deleted » non booléen")
    return {"insee": insee, "nom": _obligatoire(commune, "name", url), "rnu": rnu, "supprimee": supprimee}


def _documents(client: httpx.Client, point: str, sleep: Callable[[float], Any]) -> list[dict]:
    url = f"{URL}/document"
    documents = []
    for proprietes in _proprietes(get_json(client, url, {"geom": point}, sleep=sleep), url):
        identifiant = proprietes.get("id")
        if identifiant is None or identifiant == "" or isinstance(identifiant, bool):
            raise _forme(url, "champ « id » absent")
        documents.append({
            "id": identifiant,
            "nom": _obligatoire(proprietes, "name", url),
            "type": _facultatif(proprietes, "du_type"),
            "statut": _facultatif(proprietes, "gpu_status"),
            "date_gpu": _facultatif(proprietes, "gpu_timestamp"),
        })
    return documents


def _zones(client: httpx.Client, point: str, sleep: Callable[[float], Any]) -> list[dict]:
    url = f"{URL}/zone-urba"
    zones = []
    for proprietes in _proprietes(get_json(client, url, {"geom": point}, sleep=sleep), url):
        zones.append({
            "libelle": _obligatoire(proprietes, "libelle", url),
            "libelong": _facultatif(proprietes, "libelong"),
            "typezone": _facultatif(proprietes, "typezone"),
            "idurba": _facultatif(proprietes, "idurba"),
            "date_approbation": _date_approbation(proprietes.get("idurba")),
            "reglement_url": _reglement_url(proprietes.get("gpu_doc_id"), proprietes.get("nomfic")),
        })
    return zones


def _prescriptions(client: httpx.Client, carre: str, sleep: Callable[[float], Any]) -> list[dict]:
    """Les trois natures (surf, lin, pct), dédoublonnées sur (nature, libelle, typepsc, stypepsc, txt)."""
    vues: set[str] = set()
    prescriptions = []
    for nature, endpoint in NATURES_PRESCRIPTION:
        url = f"{URL}/{endpoint}"
        for proprietes in _proprietes(get_json(client, url, {"geom": carre}, sleep=sleep), url):
            prescription = {
                "nature": nature,
                "libelle": _obligatoire(proprietes, "libelle", url),
                "typepsc": _facultatif(proprietes, "typepsc"),
                "stypepsc": _facultatif(proprietes, "stypepsc"),
                "txt": _facultatif(proprietes, "txt"),
            }
            cle = json.dumps(prescription, sort_keys=True, ensure_ascii=False, default=str)
            if cle not in vues:
                vues.add(cle)
                prescriptions.append(prescription)
    return prescriptions


def _servitudes(client: httpx.Client, point: str, sleep: Callable[[float], Any]) -> list[dict]:
    """Une ligne par entité de l'API, sans dédoublonnage (une commune testée porte 6 AC1 distinctes)."""
    url = f"{URL}/assiette-sup-s"
    servitudes = []
    for proprietes in _proprietes(get_json(client, url, {"geom": point}, sleep=sleep), url):
        suptype = proprietes.get("suptype")
        if not isinstance(suptype, str) or not suptype.strip():
            raise _forme(url, "champ « suptype » absent ou non textuel")
        servitudes.append({
            "categorie": suptype.strip().upper(),
            "nom": _facultatif(proprietes, "nomsuplitt"),
            "type_assiette": _facultatif(proprietes, "typeass"),
            "mode": _facultatif(proprietes, "modegeoass"),
            "parametre": _facultatif(proprietes, "paramcalc"),
            "nomass": _facultatif(proprietes, "nomass"),
        })
    return servitudes


def _portee(geo: dict) -> dict:
    """Où chaque liste a été lue. La taille du carré se calcule à la latitude du point (la largeur varie avec elle)."""
    lon, lat = geo["lon"], geo["lat"]
    largeur = haversine_m(lat, lon - DEMI_COTE_DEG, lat, lon + DEMI_COTE_DEG)
    hauteur = haversine_m(lat - DEMI_COTE_DEG, lon, lat + DEMI_COTE_DEG, lon)
    return {
        "zone": "au point",
        "servitudes": "au point",
        "prescriptions": f"carré d'environ {largeur:.0f} × {hauteur:.0f} m autour du point : "
                         "à confirmer sur le règlement",
        "prescriptions_demi_cote_deg": DEMI_COTE_DEG,
        "limite": "une liste vide ne prouve pas l'absence de servitude",
    }


def _alertes(commune: dict, documents: list[dict], zones: list[dict]) -> list[dict]:
    alertes = []
    if commune["rnu"]:
        alertes.append({"bloc": "urbanisme.commune", "message": (
            "commune au règlement national d'urbanisme (RNU) selon le GPU : pas de zone ni de prescription de "
            "PLU dans la fiche, les servitudes (AC1, PM1...) restent à lire")})
    elif not documents:
        alertes.append({"bloc": "urbanisme.documents", "message": (
            "aucun document d'urbanisme publié au Géoportail de l'urbanisme pour ce point alors que la commune "
            "n'est pas au RNU : document opposable peut-être non publié")})
    if len(zones) > 1:
        detail = ", ".join(f"{zone['libelle']} ({zone['idurba'] or 'idurba absent'})" for zone in zones)
        alertes.append({"bloc": "urbanisme.zone", "message": (
            f"{len(zones)} zones au point : {detail} ; la première est retenue, à confirmer sur le plan de zonage")})
    return alertes


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Cadre d'urbanisme du point géocodé `geo` (`citycode`, `lon`, `lat`) ; `OpendataError` au moindre échec.

    `bloc` : `commune` {insee, nom, rnu, supprimee} ; `documents` [{id, nom, type, statut, date_gpu}] ;
    `zone` {libelle, libelong, typezone, idurba, date_approbation, reglement_url} ou None (RNU, ou pas de zone) ;
    `prescriptions` [{nature, libelle, typepsc, stypepsc, txt}] ; `servitudes` [{categorie, nom, type_assiette,
    mode, parametre, nomass}] ; `abords_monument_historique` (une AC1) et `plan_prevention_risques` (une PM1) ;
    `portee`. S'il y a plusieurs zones au point, la première est retenue et une alerte les nomme.
    """
    point, carre = _point(geo), _carre(geo)
    commune = _commune(client, geo["citycode"], sleep)
    documents = _documents(client, point, sleep)
    zones = _zones(client, point, sleep)
    prescriptions = _prescriptions(client, carre, sleep)
    servitudes = _servitudes(client, point, sleep)
    categories = {servitude["categorie"] for servitude in servitudes}
    bloc = {
        "commune": commune,
        "documents": documents,
        "zone": zones[0] if zones else None,
        "prescriptions": prescriptions,
        "servitudes": servitudes,
        "abords_monument_historique": "AC1" in categories,
        "plan_prevention_risques": "PM1" in categories,
        "portee": _portee(geo),
    }
    return Resultat(bloc, [], [dict(SOURCE)], _alertes(commune, documents, zones))
