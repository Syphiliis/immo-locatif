"""Loyers d'annonce de la commune, carte des loyers 2025.

Source : « Carte des loyers - Indicateurs de loyers d'annonce par commune en 2025 » (ANIL / ministère de la
Transition écologique, d'après les annonces SeLoger et leboncoin), via `tabular-api.data.gouv.fr`.
Quatre ressources, une par type de bien : appartement, T1-T2, T3 et plus, maison.

Particularités :
- C'est un loyer d'ANNONCE (charges comprises, non meublé, en EUR/m2/mois), pas un loyer signé : chaque
  typologie le dit (`charges`) et donne la surface du bien type auquel il s'applique (`surface_type_m2`).
- Le millésime n'est pas dans la donnée : il vient du titre du jeu, d'où la constante `MILLESIME`. De même
  les surfaces types : elles viennent de la description du jeu sur data.gouv.fr (constante datée
  `SURFACES_TYPES_M2`, avec sa source), pas d'une lecture réseau à chaque fiche. Une surface absente de ce
  texte vaut `None`, avec sa source, jamais une valeur retenue de tête.
- `TYPPRED` dit la maille de l'estimation : `commune` si la commune a assez d'annonces, sinon une maille
  plus large. `n` suit la maille (annonces de la commune, ou de la maille) : un loyer estimé sur la maille
  ne doit pas passer pour communal.
- Les clés `lwr.IPm2` et `upr.IPm2` (intervalle de prédiction) contiennent un point : lecture directe par `ligne[...]`.
- Chaque type est isolé : un échec ou une commune absente donne `None` + une erreur `loyers.<type>`,
  les autres types restent servis.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata.http import OpendataError, Resultat, get_json

MILLESIME = "2025"
CHARGES = "comprises"  # description du jeu : « Les indicateurs de loyers sont calculés charges comprises »
# Surfaces des biens types, recopiées telles qu'écrites dans la description du jeu (« caractéristiques de
# référence » : « Pour un appartement (toutes typologies confondues) : surface de 52 m² », T1-T2 37 m²,
# T3 et plus 72 m², maison 92 m²). Les descriptions des 4 ressources sont vides : seul le jeu les porte.
SURFACES_TYPES_M2 = {"appartement": 52, "appartement_t1_t2": 37, "appartement_t3_plus": 72, "maison": 92}
SURFACES_TYPES_SOURCE = (
    "https://www.data.gouv.fr/datasets/carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025 "
    "(description du jeu, lue le 2026-10-04)"
)
RESSOURCES = {
    "appartement": "55b34088-0964-415f-9df7-d87dd98a09be",
    "appartement_t1_t2": "14a1fe11-b2d1-49b3-9f6b-83d12df9482c",
    "appartement_t3_plus": "5e3b28a4-cf56-43a3-ae79-43cceeb27f8c",
    "maison": "129f764d-b613-44e4-952c-5ff50a8c9b73",
}
URL = "https://tabular-api.data.gouv.fr/api/resources/{rid}/data/"
LICENCE = (
    "Licence Ouverte 2.0 - Estimations ANIL, à partir des données du Groupe SeLoger et de leboncoin ; "
    "loyer d'annonce charges comprises, non meublé, en EUR/m2/mois ; indicateurs expérimentaux"
)


def _champ(ligne: dict, cle: str, types: type | tuple[type, ...], url: str) -> Any:
    """Valeur de `ligne[cle]`, ou `OpendataError` si elle manque ou n'a pas le type attendu (un booléen n'est pas un nombre)."""
    valeur = ligne.get(cle)
    if not isinstance(valeur, types) or isinstance(valeur, bool):
        raise OpendataError(f"forme inattendue de la réponse sur {url} (champ « {cle} » absent ou de type inattendu)")
    return valeur


def _lire(donnees: Any, insee: str, url: str, type_local: str) -> dict:
    """Réponse d'une ressource -> bloc d'un type. `OpendataError` si la commune manque ou si la forme change."""
    if not isinstance(donnees, dict) or not isinstance(donnees.get("data"), list):
        raise OpendataError(f"forme inattendue de la réponse sur {url} (clé « data » absente ou non liste)")
    if not donnees["data"]:
        raise OpendataError(f"commune {insee} absente de la carte des loyers {MILLESIME} ({url})")
    ligne = donnees["data"][0]
    if not isinstance(ligne, dict):
        raise OpendataError(f"forme inattendue de la réponse sur {url} (ligne non objet)")
    if ligne.get("INSEE_C") != insee:  # filtre serveur ignoré : on tiendrait la ligne d'une autre commune
        raise OpendataError(f"filtre commune ignoré sur {url} : INSEE_C={ligne.get('INSEE_C')!r}, attendu {insee}")
    maille = _champ(ligne, "TYPPRED", str, url)
    n_commune = _champ(ligne, "nbobs_com", int, url)
    n_maille = _champ(ligne, "nbobs_mail", int, url)
    surface_type = SURFACES_TYPES_M2.get(type_local)
    return {
        "valeur_m2": _champ(ligne, "loypredm2", (int, float), url),
        "ip_bas": _champ(ligne, "lwr.IPm2", (int, float), url),
        "ip_haut": _champ(ligne, "upr.IPm2", (int, float), url),
        "n": n_commune if maille == "commune" else n_maille,
        "maille": maille,
        "millesime": MILLESIME,
        "n_commune": n_commune,
        "n_maille": n_maille,
        "charges": CHARGES,
        "surface_type_m2": surface_type,
        "surface_type_source": SURFACES_TYPES_SOURCE if surface_type is not None else None,
    }


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Loyers de la commune du point géocodé : un dict à 4 clés (`RESSOURCES`), chacune un bloc ou `None`."""
    insee = geo["citycode"]
    bloc: dict[str, dict | None] = {}
    erreurs: list[dict] = []
    sources: list[dict] = []
    for type_local, rid in RESSOURCES.items():
        url = URL.format(rid=rid)
        try:
            bloc[type_local] = _lire(get_json(client, url, {"INSEE_C__exact": insee}, sleep=sleep), insee, url,
                                     type_local)
        except OpendataError as exc:
            bloc[type_local] = None
            erreurs.append({"bloc": f"loyers.{type_local}", "message": str(exc)})
        else:
            sources.append({"bloc": "loyers", "url": url, "licence": LICENCE, "millesime": MILLESIME})
    return Resultat(bloc, erreurs, sources)
