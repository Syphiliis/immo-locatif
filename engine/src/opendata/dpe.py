"""DPE de la commune et de l'adresse.

Source : ADEME, jeu « dpe03existant » (DPE des logements existants), API data-fair, sans clé.
Deux recherches indépendantes : le nombre de DPE de la commune (`size=0`) et les DPE rattachés à
l'adresse BAN exacte du géocodage. L'une peut échouer sans entraîner l'autre.

Particularités de l'API :
- le `qs` DOIT mettre sa valeur entre guillemets : `adresse_ban:1 Rue de Test` sans guillemets ne filtre
  rien et renvoie sans erreur les 9,5 millions de lignes du jeu. Par prudence, TOUTES les lignes
  renvoyées sont recontrôlées contre le label cherché (garde « filtre ignoré »).
- les lignes portent un champ technique `_score` : seuls les champs de `CHAMPS` sont conservés.
- les libellés sont accentués (« Électricité ») : la comparaison se fait sans accent ni casse.
- la donnée est brute (saisie des diagnostiqueurs), ni exhaustive ni représentative : un total de zéro
  est un résultat valide.
- toutes les lignes de l'adresse sont lues en UNE requête (`size=DPE_MAX_LIGNES`, 200 ; le maximum documenté de
  `size` est 10 000, OpenAPI du jeu consultée le 2026-10-07) : aucune pagination à suivre. Le `total` de la
  réponse est exact pour un filtre `qs` sans `q`. Si `total` dépasse les lignes rendues (plafond de 200, ou une API
  qui en rend moins qu'annoncé), une alerte `dpe.a_l_adresse` le dit : la liste n'est jamais tronquée en silence.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from src.opendata.http import OpendataError, Resultat, get_json

URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
CHAMPS = (
    "etiquette_dpe",
    "etiquette_ges",
    "conso_5_usages_par_m2_ep",
    "date_etablissement_dpe",
    "surface_habitable_logement",
    "type_batiment",
    "periode_construction",
    "type_energie_principale_chauffage",
    "adresse_ban",
    "code_insee_ban",
)
DATE_REFORME = date(2026, 1, 1)
DPE_MAX_LIGNES = 200  # DPE lus à l'adresse, en UNE requête (size) ; au-delà, la liste est tronquée et dite
LICENCE = (
    "Licence Ouverte 2.0 (Etalab) - ADEME, DPE Logements existants "
    "(données brutes saisies par les diagnostiqueurs, base ni exhaustive ni représentative)"
)
NOTE = (
    f"avant_reforme_coef_elec vaut True si le DPE est établi avant le {DATE_REFORME:%d/%m/%Y} avec un "
    f"chauffage principal électrique : le coefficient d'énergie primaire de l'électricité baisse au "
    f"{DATE_REFORME:%d/%m/%Y}. C'est un fait daté, pas une interprétation de l'étiquette ; "
    "None si la date ou le chauffage est absent."
)


def _sans_accent(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold().strip()


def avant_reforme_coef_elec(date_etablissement: str | None, chauffage: str | None) -> bool | None:
    """True si DPE avant la réforme ET chauffage électrique ; None si l'un des deux est absent ou illisible."""
    if not isinstance(date_etablissement, str) or not isinstance(chauffage, str) or not chauffage.strip():
        return None
    try:
        jour = date.fromisoformat(date_etablissement)
    except ValueError:
        return None
    return jour < DATE_REFORME and _sans_accent(chauffage) == "electricite"


def _qs(champ: str, valeur: str) -> str:
    """Filtre `champ:"valeur"` : guillemets obligatoires, `\\` et `"` échappés dans la valeur."""
    echappee = valeur.replace("\\", "\\\\").replace('"', '\\"')
    return f'{champ}:"{echappee}"'


def _total(reponse: Any) -> int:
    if not isinstance(reponse, dict) or type(reponse.get("total")) is not int:
        raise OpendataError(f"forme inattendue : « total » entier absent dans la réponse de {URL}")
    return reponse["total"]


def _commune_total(client: httpx.Client, insee: str, sleep: Callable[[float], Any]) -> int:
    reponse = get_json(client, URL, {"qs": _qs("code_insee_ban", insee), "size": 0}, sleep=sleep)
    return _total(reponse)


def _a_l_adresse(client: httpx.Client, geo: dict, sleep: Callable[[float], Any], alertes: list[dict]) -> dict:
    if geo["type"] != "housenumber":
        raise OpendataError(
            f"géocodage de type {geo['type']} (pas de numéro de rue) : recherche DPE à l'adresse non applicable"
        )
    label = geo["label"]
    params = {"qs": _qs("adresse_ban", label), "size": DPE_MAX_LIGNES, "select": ",".join(CHAMPS)}
    reponse = get_json(client, URL, params, sleep=sleep)
    total = _total(reponse)
    lignes = reponse.get("results")
    if not isinstance(lignes, list) or not all(isinstance(ligne, dict) for ligne in lignes):
        raise OpendataError(f"forme inattendue : « results » doit être une liste de lignes ({URL})")
    if any(ligne.get("adresse_ban") != label for ligne in lignes):
        raise OpendataError(f"filtre adresse_ban ignoré : des lignes d'autres adresses sont renvoyées ({URL})")
    dpe = []
    for ligne in lignes[:DPE_MAX_LIGNES]:  # plafond tenu même si l'API ignorait `size`
        entree = {champ: ligne.get(champ) for champ in CHAMPS}
        entree["avant_reforme_coef_elec"] = avant_reforme_coef_elec(
            entree["date_etablissement_dpe"], entree["type_energie_principale_chauffage"]
        )
        dpe.append(entree)
    if total > len(dpe):
        suite = (f"{len(dpe)} lus (plafond {DPE_MAX_LIGNES}) : liste tronquée" if total > DPE_MAX_LIGNES
                 else f"{len(dpe)} reçus : liste incomplète")
        alertes.append({"bloc": "dpe.a_l_adresse", "message": f"{total} DPE annoncés à l'adresse, {suite}"})
    return {"adresse_ban": label, "total": total, "dpe": dpe, "note": NOTE}


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """`bloc` = {"commune_total": int | None, "a_l_adresse": dict | None} ; chaque recherche échoue seule."""
    bloc: dict = {}
    erreurs: list[dict] = []
    sources: list[dict] = []
    alertes: list[dict] = []
    recherches = (
        ("commune_total", lambda: _commune_total(client, geo["citycode"], sleep)),
        ("a_l_adresse", lambda: _a_l_adresse(client, geo, sleep, alertes)),
    )
    for nom, recherche in recherches:
        try:
            bloc[nom] = recherche()
        except OpendataError as exc:
            bloc[nom] = None
            erreurs.append({"bloc": f"dpe.{nom}", "message": str(exc)})
        else:
            sources.append({"bloc": f"dpe.{nom}", "url": URL, "licence": LICENCE, "millesime": None})
    return Resultat(bloc, erreurs, sources, alertes)
