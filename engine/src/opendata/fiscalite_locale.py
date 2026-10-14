"""Taux de fiscalité locale de la commune, REI de la DGFiP.

Source : jeu « Fiscalité locale des particuliers » (`fiscalite-locale-des-particuliers-geo`) sur
data.economie.gouv.fr, API Explore v2.1 d'Opendatasoft, sans clé. Un enregistrement par commune et par exercice.

Particularités :
- `exercice` est une CHAÎNE dans l'API (« 2025 ») : converti en entier ; c'est aussi le millésime de la source.
- Le paramètre `select` est indispensable : sans lui chaque enregistrement pèse environ 23 Ko à cause des
  contours géographiques.
- Le jeu donne des TAUX. La taxe foncière réelle d'un bien = taux x base cadastrale, et la base cadastrale
  n'est pas publique : ce module ne calcule AUCUN montant de taxe, et le dit dans `note`.
- `taux_plein_teom` (ordures ménagères) peut manquer : `None`, sans erreur. `taux_global_tfb` est
  indispensable : sans lui, `OpendataError`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata.http import OpendataError, Resultat, get_json

URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/fiscalite-locale-des-particuliers-geo/records"
NOTE = (
    "La taxe foncière réelle d'un bien = taux x base cadastrale ; la base cadastrale n'est pas publique : "
    "aucun montant de taxe n'est calculé."
)
LICENCE = "Licence Ouverte 2.0 (Etalab) - DGFiP, Fiscalité locale des particuliers"
CHAMPS = "exercice,libcom,insee_com,taux_global_tfb,taux_plein_teom"


def _est_nombre(valeur: Any) -> bool:
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def _forme_inattendue(detail: str) -> OpendataError:
    return OpendataError(f"forme inattendue de la réponse sur {URL} ({detail})")


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Taux de taxe foncière bâtie et de TEOM du dernier exercice publié pour la commune du point géocodé."""
    insee = geo["citycode"]
    params = {"where": f'insee_com="{insee}"', "order_by": "exercice desc", "limit": 1, "select": CHAMPS}
    donnees = get_json(client, URL, params, sleep=sleep)
    if not isinstance(donnees, dict) or not isinstance(donnees.get("results"), list):
        raise _forme_inattendue("clé « results » absente ou non liste")
    if not donnees["results"]:
        raise OpendataError(f"commune {insee} absente de la fiscalité locale des particuliers ({URL})")
    try:
        ligne = donnees["results"][0]
        exercice = int(ligne["exercice"])
        taux_tfb = ligne.get("taux_global_tfb")
        taux_teom = ligne.get("taux_plein_teom")
        libelle = ligne["libcom"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _forme_inattendue(f"{type(exc).__name__}: {exc}") from exc
    if ligne.get("insee_com") != insee:  # filtre where ignoré : on tiendrait les taux d'une autre commune
        raise OpendataError(f"filtre commune ignoré sur {URL} : insee_com={ligne.get('insee_com')!r}, attendu {insee}")
    if not _est_nombre(taux_tfb):
        raise OpendataError(f"taux_global_tfb absent ou non numérique pour la commune {insee} ({URL})")
    if taux_teom is not None and not _est_nombre(taux_teom):
        raise _forme_inattendue("taux_plein_teom non numérique")
    bloc = {
        "exercice": exercice,
        "taux_global_tfb": taux_tfb,
        "taux_plein_teom": taux_teom,
        "libelle_commune": libelle,
        "note": NOTE,
    }
    source = {"bloc": "fiscalite_locale", "url": URL, "licence": LICENCE, "millesime": str(exercice)}
    return Resultat(bloc, [], [source])
