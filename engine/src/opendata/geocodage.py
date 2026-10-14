"""Géocodage d'une adresse libre vers un point et un code INSEE.

Source : Géoplateforme de l'IGN (Base Adresse Nationale), `GET /geocodage/search`, sans clé.
Tous les autres modules de la fiche partent du dict rendu par `geocoder` : `citycode` pour les
sources communales, `lon`/`lat` pour DVF et Géorisques, `label` et `type` pour le DPE.

Particularités :
- `geometry.coordinates` est `[lon, lat]` : la longitude d'abord.
- `citycode` reste une chaîne : un code INSEE peut commencer par 0 (« 01001 ») ou contenir une lettre (« 2A004 »).
- `type` vient de `properties.type` (`housenumber`, `street`, `municipality`...) ; `_type` vaut toujours
  « address » et n'apprend rien. Seul `housenumber` désigne un numéro de rue : le DPE et le rapport de
  risques à l'adresse n'ont de sens que pour lui.
- `score` (0 à 1) dit la confiance du géocodeur ; en dessous de `SCORE_MIN` la fiche ne va pas plus loin.
- La COMMUNE est contrôlée : `NB_CANDIDATS` candidats sont lus. Si l'adresse porte
  un code postal (le dernier nombre de 5 chiffres), le premier candidat de même `postcode` est retenu, et aucun
  candidat de ce code postal est une erreur ; sans code postal, le premier candidat est pris et le contrôle est dit
  « non fait ». `rang_candidat` (1 à `NB_CANDIDATS`) dit quel candidat a été retenu ; `identifiant_ban`
  (`properties.id`, ex. `99999_0001_00001`) identifie l'adresse dans la BAN et sert, avec la parcelle, de clé du bien.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata.http import OpendataError, get_json

URL = "https://data.geopf.fr/geocodage/search"
URL_REVERSE = "https://data.geopf.fr/geocodage/reverse"
SCORE_MIN = 0.5
NB_CANDIDATS = 5  # candidats lus à la recherche (`limit`) ; le contrôle de commune cherche parmi eux
CODE_POSTAL = re.compile(r"\b\d{5}\b")
CONTROLE_NON_FAIT = "non fait : pas de code postal dans l'adresse"
LICENCE = "Licence Ouverte 2.0 (Etalab) - Base Adresse Nationale via la Géoplateforme (IGN)"
SOURCE = {"bloc": "geocodage", "url": URL, "licence": LICENCE, "millesime": None}


def _forme_inattendue(detail: str, url: str = URL) -> OpendataError:
    return OpendataError(f"forme inattendue de la réponse sur {url} ({detail})")


def geocoder(client: httpx.Client, adresse: str, *, sleep: Callable[[float], Any] = time.sleep) -> dict:
    """Géocode `adresse` : candidat retenu (voir le docstring du module pour le contrôle de commune), ou
    `OpendataError` s'il n'y en a aucun, si aucun n'est dans le code postal de l'adresse ou si la forme change."""
    donnees = get_json(client, URL, {"q": adresse, "limit": NB_CANDIDATS}, sleep=sleep)
    if not isinstance(donnees, dict) or "features" not in donnees:
        raise _forme_inattendue("clé « features » absente")
    if not donnees["features"]:
        raise OpendataError(f"aucun résultat de géocodage pour « {adresse} » ({URL})")
    codes = CODE_POSTAL.findall(adresse)
    code_postal = codes[-1] if codes else None  # le code postal ferme l'adresse : « BP 12345 ... 99999 Exempleville »
    try:
        candidats = donnees["features"][:NB_CANDIDATS]
        if code_postal is None:
            rang = 1
        else:
            rang = next((i for i, c in enumerate(candidats, start=1)
                         if c["properties"].get("postcode") == code_postal), None)
            if rang is None:
                pluriel = "s" if len(candidats) > 1 else ""
                raise OpendataError(f"aucun candidat dans le code postal {code_postal} (parmi {len(candidats)} "
                                    f"résultat{pluriel} pour « {adresse} », {URL})")
        feature = candidats[rang - 1]
        coordonnees = feature["geometry"]["coordinates"]
        proprietes = feature["properties"]
        citycode = proprietes["citycode"]
        if not isinstance(citycode, str):
            raise _forme_inattendue("citycode n'est pas une chaîne")
        identifiant = proprietes["id"]
        if not isinstance(identifiant, str) or not identifiant:
            raise _forme_inattendue("id n'est pas une chaîne non vide")
        return {
            "label": proprietes["label"],
            "score": float(proprietes["score"]),
            "type": proprietes["type"],
            "citycode": citycode,
            "postcode": proprietes.get("postcode"),
            "city": proprietes.get("city"),
            "lon": float(coordonnees[0]),
            "lat": float(coordonnees[1]),
            "identifiant_ban": identifiant,
            "controle_commune": CONTROLE_NON_FAIT if code_postal is None else f"code postal {code_postal} concordant",
            "rang_candidat": rang,
        }
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise _forme_inattendue(f"{type(exc).__name__}: {exc}") from exc


def inverse(client: httpx.Client, *, lon: float, lat: float, index: str, limit: int,
            sleep: Callable[[float], Any] = time.sleep) -> list[dict]:
    """Géocodage inverse : `properties` des résultats, du plus proche au plus lointain, liste vide s'il n'y en a pas.
    `index` : `address` (numéros et rues de la BAN : `label`, `id`, `type`, `distance`...) ou `parcel` (parcelles
    cadastrales : `id` = identifiant IDU, `section`, `number`). La longitude passe d'abord ; `limit` va de 1 à 50
    (51 donne un HTTP 400, jamais rejoué)."""
    donnees = get_json(client, URL_REVERSE, {"lon": lon, "lat": lat, "index": index, "limit": limit}, sleep=sleep)
    if not isinstance(donnees, dict) or not isinstance(donnees.get("features"), list):
        raise _forme_inattendue("clé « features » absente ou non liste", URL_REVERSE)
    resultats = []
    for feature in donnees["features"]:
        proprietes = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(proprietes, dict):
            raise _forme_inattendue("résultat sans « properties »", URL_REVERSE)
        resultats.append(proprietes)
    return resultats
