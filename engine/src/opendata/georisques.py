"""Risques naturels et technologiques : commune, adresse, PPRN.

Source : API Géorisques v1 (georisques.gouv.fr), sans clé. Trois sous-blocs indépendants : un échec
(réseau, 4xx, forme inattendue) laisse le sous-bloc à None avec une erreur `risques.<sous-bloc>`, et les
autres sous-blocs sont servis quand même.

Particularités de l'API, toutes constatées sur des réponses réelles :
- `gaspar/risques` veut `code_insee` (snake_case) ; `codeInsee` y renvoie une erreur 500. À l'inverse
  `gaspar/pprn` veut `codeInsee` (camelCase) ; `code_insee` y est IGNORÉ sans erreur et l'API renvoie
  alors les 6 582 PPRN de France. D'où la garde `PPRN_MAX` : on ne livre jamais plus que ce qu'une
  commune peut porter, et le détail de chaque PPRN confirme que la commune y figure.
- dans `gaspar/risques`, `results` est un ENTIER (le nombre de communes) ; la liste est sous `data`.
- `resultats_rapport_risque` attend `latlon` = "<longitude>,<latitude>", longitude d'abord (l'ordre
  inverse donne un 404) ; les réinitialisations de connexion y sont fréquentes, le retry de `http`
  s'applique.
- les éléments de la liste des PPRN n'ont pas de champ commune : seul `gaspar/pprn/<id>` liste les
  communes concernées, avec leurs aléas.

Limites officielles : 1 appel par seconde pour le rapport, 5 par seconde pour les autres endpoints. Seuls les
appels de détail PPRN s'enchaînent (jusqu'à `PPRN_MAX`) : `PAUSE_PPRN_S` les espace ; les autres appels sont
uniques. Un 429 est rejoué par `http` (voir `Retry-After`) ; persistant, il donne un sous-bloc None et une
erreur visible.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from src.opendata.http import OpendataError, Resultat, get_json

BASE = "https://georisques.gouv.fr/api/v1"
PPRN_MAX = 50
PAUSE_PPRN_S = 0.2  # entre deux appels de détail PPRN : 1 / 5 appels par seconde (limite officielle)
LICENCE = "Licence Ouverte / Open Licence (mentions légales Géorisques ; version non précisée)"

URL_RISQUES = f"{BASE}/gaspar/risques"
URL_RAPPORT = f"{BASE}/resultats_rapport_risque"
URL_PPRN = f"{BASE}/gaspar/pprn"


def _forme(url: str, detail: str) -> OpendataError:
    return OpendataError(f"forme inattendue sur {url} : {detail}")


@contextmanager
def _forme_attendue(url: str) -> Iterator[None]:
    """Convertit une clé manquante ou un type inattendu en OpendataError (jamais de KeyError)."""
    try:
        yield
    except (KeyError, TypeError, AttributeError) as exc:
        raise _forme(url, f"{type(exc).__name__}: {exc}") from exc


def _commune(client: httpx.Client, insee: str, sleep: Callable[[float], Any]) -> dict:
    reponse = get_json(client, URL_RISQUES, {"code_insee": insee}, sleep=sleep)
    with _forme_attendue(URL_RISQUES):
        donnees = reponse["data"]
        if not donnees:
            raise OpendataError(f"commune {insee} absente de Géorisques (aucune donnée sur {URL_RISQUES})")
        entree = donnees[0]
        if entree["code_insee"] != insee:
            raise OpendataError(
                f"Géorisques renvoie la commune {entree['code_insee']} au lieu de {insee} ({URL_RISQUES})"
            )
        return {
            "code_insee": entree["code_insee"],
            "libelle_commune": entree["libelle_commune"],
            "risques": [
                {"num_risque": risque["num_risque"], "libelle": risque["libelle_risque_long"]}
                for risque in entree["risques_detail"]
            ],
        }


def _risques(entrees: dict) -> dict:
    """Toutes les entrées sont gardées : « non présent » est une information."""
    return {
        cle: {
            "present": risque["present"],
            "libelle": risque["libelle"],
            "statut_commune": risque.get("libelleStatutCommune"),
            "statut_adresse": risque.get("libelleStatutAdresse"),
        }
        for cle, risque in entrees.items()
    }


def _adresse(client: httpx.Client, geo: dict, sleep: Callable[[float], Any]) -> dict:
    if geo["type"] != "housenumber":
        raise OpendataError(
            f"géocodage de type {geo['type']} (pas de numéro de rue) : rapport de risques à l'adresse non applicable"
        )
    rapport = get_json(client, URL_RAPPORT, {"latlon": f"{geo['lon']},{geo['lat']}"}, sleep=sleep)
    with _forme_attendue(URL_RAPPORT):
        return {
            "adresse": rapport["adresse"]["libelle"],
            "commune": rapport["commune"]["libelle"],
            "url_rapport": rapport["url"],
            "risques_naturels": _risques(rapport["risquesNaturels"]),
            "risques_technologiques": _risques(rapport["risquesTechnologiques"]),
        }


def _pprn_de_la_commune(client: httpx.Client, element: dict, insee: str, sleep: Callable[[float], Any]) -> dict:
    with _forme_attendue(URL_PPRN):
        id_gaspar = element["idGaspar"]
    url = f"{URL_PPRN}/{id_gaspar}"
    detail = get_json(client, url, sleep=sleep)
    with _forme_attendue(url):
        commune = next((c for c in detail["communes"] if c["codeInsee"] == insee), None)
        if commune is None:
            raise OpendataError(f"PPRN {id_gaspar} : commune {insee} absente de ses communes concernées ({url})")
        return {
            "id_gaspar": id_gaspar,
            "libelle": element.get("libPpr"),
            "modele_procedure": element.get("modeleProcedure"),
            "bassin_risques": element.get("libBassinRisques"),
            "etat_revision": element.get("etatRevision"),
            "date_modification": element.get("dateModification"),
            "aleas": [
                {
                    "libelle": alea["libelle"],
                    "date_prescription": alea.get("datePrescription"),
                    "date_approbation": alea.get("dateApprobation"),
                    "date_abrogation": alea.get("dateAbrog"),
                }
                for alea in commune["aleas"]
            ],
        }


def _pprn(client: httpx.Client, insee: str, sleep: Callable[[float], Any]) -> list[dict]:
    liste = get_json(client, URL_PPRN, {"codeInsee": insee, "page_size": 100}, sleep=sleep)
    if not isinstance(liste, dict) or type(liste.get("totalElements")) is not int \
            or not isinstance(liste.get("content"), list):
        raise _forme(URL_PPRN, "« totalElements » entier et « content » liste attendus")
    total, contenu = liste["totalElements"], liste["content"]
    # Garde AVANT tout appel de détail : un filtre ignoré renverrait (et détaillerait) tout le pays.
    if total > PPRN_MAX:
        raise OpendataError(
            f"filtre ignoré : {total} PPRN renvoyés pour la commune {insee} (plafond {PPRN_MAX}), "
            f"rien n'est livré ({URL_PPRN})"
        )
    if len(contenu) != total:
        raise _forme(URL_PPRN, f"{len(contenu)} éléments pour totalElements = {total}")
    detail = []
    for rang, element in enumerate(contenu):
        if rang:
            sleep(PAUSE_PPRN_S)  # entre deux détails seulement : jusqu'à 50 appels de suite, limite de 5 par seconde
        detail.append(_pprn_de_la_commune(client, element, insee, sleep))
    return detail


def collecter(client: httpx.Client, geo: dict, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """`bloc` = {"commune", "adresse", "pprn"}, chacun rempli ou None : chaque sous-bloc échoue seul."""
    bloc: dict = {}
    erreurs: list[dict] = []
    sources: list[dict] = []
    sous_blocs = (
        ("commune", URL_RISQUES, lambda: _commune(client, geo["citycode"], sleep)),
        ("adresse", URL_RAPPORT, lambda: _adresse(client, geo, sleep)),
        ("pprn", URL_PPRN, lambda: _pprn(client, geo["citycode"], sleep)),
    )
    for nom, url, recherche in sous_blocs:
        try:
            bloc[nom] = recherche()
        except OpendataError as exc:
            bloc[nom] = None
            erreurs.append({"bloc": f"risques.{nom}", "message": str(exc)})
        else:
            sources.append({"bloc": f"risques.{nom}", "url": url, "licence": LICENCE, "millesime": None})
    return Resultat(bloc, erreurs, sources)
