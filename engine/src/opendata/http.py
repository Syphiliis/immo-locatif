"""Socle HTTP des sources open data de la fiche d'un bien.

Un client `httpx.Client` (timeout 30 s, redirections suivies, User-Agent explicite) dont le transport est
injectable (tests : `httpx.MockTransport`), et deux lectures, `get_json` et `get_text`, qui rejouent
jusqu'à 3 tentatives sur une erreur de transport, un HTTP 5xx ou un HTTP 429, avec 1 s puis 2 s d'attente.

- Un 429 attend la valeur de `Retry-After` (secondes entières) si elle est présente, plafonnée à
  `RETRY_AFTER_MAX_S` (30 s), sinon le barème ci-dessus ; le 429 persistant lève `OpendataError` (« HTTP 429 »).
- Un 404 lève `NotFound` tout de suite (DVF : une année absente) ; tout autre 4xx lève `OpendataError`
  tout de suite : une erreur du demandeur ne se rejoue pas.
- L'attente est injectable (`sleep`) : en test, zéro attente réelle.
- `Resultat` est le retour commun des collecteurs : la valeur du bloc, ses erreurs, ses sources.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

import httpx

USER_AGENT = "immo-locatif-opendata/1.0"
TIMEOUT_S = 30.0
TENTATIVES = 3
ATTENTES_S = (1, 2)  # avant la 2e puis la 3e tentative
RETRY_AFTER_MAX_S = 30  # plafond de l'attente demandée par un 429 (Retry-After) : une fiche ne se bloque pas plus


class OpendataError(Exception):
    """Échec définitif d'un appel, ou forme de réponse inattendue. Le message contient l'URL."""


class NotFound(OpendataError):
    """HTTP 404, jamais rejoué (pour DVF : l'année n'existe pas encore)."""


class Resultat(NamedTuple):
    """Retour de tout collecteur : `bloc` (None si absent), `erreurs` {bloc, message}, `sources`, et `alertes`
    {bloc, message} : ce que la fiche signale sans que rien n'ait échoué (fenêtre courte, liste tronquée)."""

    bloc: Any
    erreurs: list[dict]
    sources: list[dict]
    alertes: Sequence[dict] = ()


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    )


def _retry_after(reponse: httpx.Response) -> int | None:
    """`Retry-After` d'un 429 en secondes entières, plafonné à `RETRY_AFTER_MAX_S` ; None si absent ou illisible
    (date HTTP, décimal, négatif) : l'appelant retombe alors sur le barème `ATTENTES_S`."""
    valeur = reponse.headers.get("retry-after", "").strip()
    return min(int(valeur), RETRY_AFTER_MAX_S) if valeur.isascii() and valeur.isdigit() else None


def _get(client: httpx.Client, url: str, params: dict | None, sleep: Callable[[float], Any]) -> httpx.Response:
    cause = ""
    attente_429: int | None = None  # Retry-After de la réponse précédente, valable pour la seule attente qui suit
    for essai in range(TENTATIVES):
        if essai:
            sleep(ATTENTES_S[essai - 1] if attente_429 is None else attente_429)
            attente_429 = None
        try:
            reponse = client.get(url, params=params)
        except httpx.TransportError as exc:
            cause = f"{type(exc).__name__}: {exc}"
            continue
        statut = reponse.status_code
        if statut >= 500:
            cause = f"HTTP {statut}"
            continue
        if statut == 429:
            cause = "HTTP 429"
            attente_429 = _retry_after(reponse)
            continue
        if statut == 404:
            raise NotFound(f"HTTP 404 sur {url}")
        if statut >= 400:
            raise OpendataError(f"HTTP {statut} sur {url}")
        return reponse
    raise OpendataError(f"échec après {TENTATIVES} tentatives sur {url} ({cause})")


def get_json(client: httpx.Client, url: str, params: dict | None = None, *, sleep: Callable[[float], Any] = time.sleep) -> Any:
    reponse = _get(client, url, params, sleep)
    try:
        return reponse.json()
    except ValueError as exc:
        raise OpendataError(f"réponse non JSON sur {url} ({exc})") from exc


def get_text(client: httpx.Client, url: str, params: dict | None = None, *, sleep: Callable[[float], Any] = time.sleep) -> str:
    return _get(client, url, params, sleep).text
