"""Parcelle cadastrale du bien, API Carto de l'IGN.

Source : `GET /api/cadastre/parcelle` de l'API Carto (module cadastre, plan cadastral DGFiP), sans clé, avec le seul
paramètre `geom` : le JSON d'un point GeoJSON, `{"type":"Point","coordinates":[lon,lat]}`, la longitude d'abord. Elle
rend la parcelle (ou les parcelles) qui CONTIENT le point.

Particularités constatées sur l'API (07/10/2026) :
- Longitude et latitude inversées : HTTP 200 et zéro parcelle, sans erreur. Un paramètre mal nommé : des parcelles
  quelconques (94 millions annoncées). D'où le seul paramètre `geom`, et le contrôle de la commune de la parcelle
  contre celle du géocodage (alerte si elles diffèrent).
- Un point sur la voirie ou hors parcelle : HTTP 200 et `features` vide. Le module se replie alors sur le géocodage
  inverse de la Géoplateforme, `index=parcel`, `limit` 1 : la parcelle la plus proche, rendue même pour un point sur la
  voirie, avec une alerte et une méthode qui le dit (`METHODE_PLUS_PROCHE`, « à confirmer »). Cette source ne donne pas
  la contenance (`contenance_m2` vaut `null`, jamais 0) ni de `citycode` : le code INSEE se lit dans `departmentcode` +
  `municipalitycode` (comme `code_dep` + `code_com` de l'API Carto), la commune dans `city`.
- `contenance` est un entier dont l'unité n'est pas documentée : lue comme des m2 (elle colle à l'aire du polygone,
  106 pour 104,7 m2 sur un cas observé), à ne pas citer comme surface cadastrale légale. Absente, nulle ou négative,
  elle vaut `null` : 0 m2 n'est pas une surface, ce serait un faux zéro.
- Plusieurs parcelles peuvent contenir le point (point sur une limite) : la première est retenue, une alerte les nomme.

Une panne (réseau, 5xx, forme inattendue) lève `OpendataError` : la fiche laisse alors le bloc à `None` et le dit dans
`erreurs`. Une panne n'est JAMAIS prise pour « point hors parcelle » : pas de repli.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata import geocodage
from src.opendata.http import OpendataError, Resultat, get_json

URL = "https://apicarto.ign.fr/api/cadastre/parcelle"
LICENCE = "Licence Ouverte 2.0 (Etalab) - plan cadastral (DGFiP) via API Carto (IGN)"
SOURCE = {"bloc": "cadastre", "url": URL, "licence": LICENCE, "millesime": None}
LICENCE_REPLI = "Géoplateforme (IGN), géocodage inverse sur l'index des parcelles : licence non vérifiée"
SOURCE_REPLI = {"bloc": "cadastre", "url": geocodage.URL_REVERSE, "licence": LICENCE_REPLI, "millesime": None}
METHODE_CONTENANT = "parcelle contenant le point"
METHODE_PLUS_PROCHE = "parcelle la plus proche du point (point hors parcelle), à confirmer"


def _forme_inattendue(detail: str, url: str = URL) -> OpendataError:
    return OpendataError(f"forme inattendue de la réponse sur {url} ({detail})")


def _chaine(valeur: Any, nom: str, url: str) -> str:
    if not isinstance(valeur, str) or not valeur:
        raise _forme_inattendue(f"« {nom} » absent ou non textuel", url)
    return valeur


def _chaine_ou_none(valeur: Any, nom: str, url: str) -> str | None:
    return None if valeur is None else _chaine(valeur, nom, url)


def _lire_parcelle(feature: Any) -> dict:
    """Une parcelle de l'API Carto -> bloc sans `methode`. `contenance` absente ou nulle : `None`."""
    proprietes = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(proprietes, dict):
        raise _forme_inattendue("parcelle sans « properties »")
    contenance = proprietes.get("contenance")
    if contenance is not None and (not isinstance(contenance, (int, float)) or isinstance(contenance, bool)):
        raise _forme_inattendue("« contenance » non numérique")
    if contenance is not None and not 0 < contenance < math.inf:  # 0, négative ou non finie : pas une surface
        contenance = None
    return {
        "idu": _chaine(proprietes.get("idu"), "idu", URL),
        "section": _chaine(proprietes.get("section"), "section", URL),
        "numero": _chaine(proprietes.get("numero"), "numero", URL),
        "contenance_m2": contenance,
        "code_insee": _chaine_ou_none(proprietes.get("code_insee"), "code_insee", URL),
        "commune": _chaine_ou_none(proprietes.get("nom_com"), "nom_com", URL),
    }


def _repli(client: httpx.Client, geo: dict, sleep: Callable[[float], Any], alertes: list[dict]) -> dict:
    """Parcelle la plus proche du point (géocodage inverse `index=parcel`), quand aucune ne le contient."""
    resultats = geocodage.inverse(client, lon=geo["lon"], lat=geo["lat"], index="parcel", limit=1, sleep=sleep)
    if not resultats:
        raise OpendataError(
            f"aucune parcelle pour le point {geo['lat']}, {geo['lon']} : ni contenant le point ({URL}), "
            f"ni la plus proche ({geocodage.URL_REVERSE})")
    proprietes = resultats[0]
    url = geocodage.URL_REVERSE
    idu = _chaine(proprietes.get("id"), "id", url)
    distance = proprietes.get("distance")
    a_distance = isinstance(distance, (int, float)) and not isinstance(distance, bool)
    ecart = f" (à {round(distance)} m)" if a_distance else ""
    alertes.append({"bloc": "cadastre", "message": (
        f"aucune parcelle ne contient le point (voirie ?) : parcelle {idu} la plus proche{ecart}, à confirmer")})
    departement, commune = proprietes.get("departmentcode"), proprietes.get("municipalitycode")
    texte = isinstance(departement, str) and isinstance(commune, str) and departement and commune
    code_insee = departement + commune if texte else None  # un des deux vide ou absent : INSEE inconnu, pas « 458 »
    return {
        "idu": idu,
        "section": _chaine(proprietes.get("section"), "section", url),
        "numero": _chaine(proprietes.get("number"), "number", url),
        "contenance_m2": None,
        "code_insee": code_insee,
        "commune": _chaine_ou_none(proprietes.get("city"), "city", url),
        "methode": METHODE_PLUS_PROCHE,
    }


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Parcelle du point géocodé. Bloc : `idu`, `section`, `numero`, `contenance_m2`, `code_insee`, `commune`,
    `methode` (`METHODE_CONTENANT` ou `METHODE_PLUS_PROCHE`). `OpendataError` si l'API est en panne, si sa forme
    change, ou si aucune parcelle n'est trouvée nulle part."""
    geom = json.dumps({"type": "Point", "coordinates": [geo["lon"], geo["lat"]]}, separators=(",", ":"))
    donnees = get_json(client, URL, {"geom": geom}, sleep=sleep)
    if not isinstance(donnees, dict) or not isinstance(donnees.get("features"), list):
        raise _forme_inattendue("clé « features » absente ou non liste")
    alertes: list[dict] = []
    if donnees["features"]:
        parcelles = [_lire_parcelle(feature) for feature in donnees["features"]]
        bloc = {**parcelles[0], "methode": METHODE_CONTENANT}
        sources = [SOURCE]
        if len(parcelles) > 1:
            idus = ", ".join(p["idu"] for p in parcelles)
            alertes.append({"bloc": "cadastre", "message": (
                f"{len(parcelles)} parcelles contiennent le point ({idus}) : la première, {bloc['idu']}, est retenue")})
    else:
        bloc = _repli(client, geo, sleep, alertes)
        sources = [SOURCE, SOURCE_REPLI]
    if bloc["code_insee"] is not None and bloc["code_insee"] != geo["citycode"]:
        alertes.append({"bloc": "cadastre", "message": (
            f"la parcelle {bloc['idu']} est dans la commune {bloc['code_insee']}, le géocodage dit {geo['citycode']} : "
            f"à vérifier")})
    return Resultat(bloc, [], sources, alertes)
