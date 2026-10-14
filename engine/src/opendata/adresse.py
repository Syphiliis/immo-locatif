"""Adresses candidates d'une annonce sans adresse, depuis son point.

Une annonce dont l'adresse est masquée ne donne qu'un point. Ce module classe des adresses candidates, de deux façons
indépendantes :

1. Géocodage inverse de la Géoplateforme (BAN, `index=address`) : les `NB_CANDIDATS_BAN` adresses les plus proches du
   point, dans l'ordre de l'API qui les classe par distance (`label`, `identifiant_ban`, `type`, `distance_m`,
   `postcode`, `citycode`). La commune du premier candidat est la commune retenue ; un code postal donné et différent
   est signalé.
2. Avec une surface : les DPE de l'ADEME (`dpe03existant`) de la commune dont la surface habitable est à
   ± `TOLERANCE_SURFACE` de la surface annoncée (borne basse arrondie au m2 vers le bas, borne haute vers le haut,
   toutes deux incluses : un DPE dans les 10 % n'est pas manqué par l'arrondi), et, si elles sont données, de la
   même étiquette et de la même date. Une adresse n'apparaît qu'une fois (son DPE le plus récent), classée par distance
   du point au DPE, `NB_CANDIDATS_DPE` au plus. `doublons` compte les autres DPE de la même adresse BAN : le même
   logement refait, ou un autre logement du même immeuble.

Pourquoi ± 10 % et non ± 5 % : sur un cas validé, la surface du DPE contredisait l'annonce (l'écart dépassait 5 %).

Une distance ne prouve rien quand le point de l'annonce est le centre de la commune (localisation masquée) : tous les
candidats sont alors à la même distance approximative et seuls la surface, l'étiquette et la date départagent.

Particularités de l'API ADEME (voir `dpe.py`) : le `qs` DOIT mettre chaque valeur entre guillemets, sinon le filtre est
ignoré sans erreur ; toutes les lignes reçues sont donc recontrôlées contre les filtres demandés. Les doublons sont
fréquents (même adresse, même DPE). `_geopoint` vaut « lat,lon » en WGS84 ; une position illisible donne une distance
`null` et un classement en dernier, jamais une exclusion. `size` = `DPE_LIGNES_MAX` ; si `total` dépasse les lignes lues,
une alerte le dit.

La sortie (`rechercher`) est un dict JSON : `genere_le`, `point`, `parametres` (la demande, les seuils de méthode, la
requête DPE et ses comptes), `commune`, `candidats_ban`, `candidats_dpe` (`None` sans surface), `sources`, `erreurs`,
`alertes`. Code de sortie (`code_sortie`) : 2 si le géocodage inverse échoue, 3 si seuls les DPE échouent, 0 sinon.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.opendata import dpe, geocodage
from src.opendata.dvf import haversine_m
from src.opendata.http import OpendataError, get_json

TOLERANCE_SURFACE = 0.10  # surface du DPE à ±10 % de celle de l'annonce
NB_CANDIDATS_BAN = geocodage.NB_CANDIDATS
NB_CANDIDATS_DPE = 10  # adresses DPE listées (les plus proches du point)
DPE_LIGNES_MAX = dpe.DPE_MAX_LIGNES  # lignes DPE lues en une requête (`size`)
CHAMPS_DPE = (
    "numero_dpe", "adresse_ban", "identifiant_ban", "date_etablissement_dpe", "etiquette_dpe", "etiquette_ges",
    "surface_habitable_logement", "type_batiment", "periode_construction", "code_insee_ban", "_geopoint",
)
SOURCE_INVERSE = {"bloc": "geocodage_inverse", "url": geocodage.URL_REVERSE, "licence": geocodage.LICENCE,
                  "millesime": None}
SOURCE_DPE = {"bloc": "dpe", "url": dpe.URL, "licence": dpe.LICENCE, "millesime": None}


def _message(exc: Exception) -> str:
    return str(exc) if isinstance(exc, OpendataError) else f"{type(exc).__name__}: {exc}"


def _forme(detail: str, url: str) -> OpendataError:
    return OpendataError(f"forme inattendue de la réponse sur {url} ({detail})")


def _est_nombre(valeur: Any) -> bool:
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


# --- candidats BAN ------------------------------------------------------------------------------

def _lire_candidat_ban(proprietes: dict) -> tuple[dict, str | None]:
    """Un résultat du géocodage inverse -> (candidat, nom de la commune). `label`, `id`, `type` et `citycode` sont
    obligatoires (une forme qui change est une erreur, pas un candidat à moitié vide)."""
    url = geocodage.URL_REVERSE
    for cle in ("label", "id", "type", "citycode"):
        if not isinstance(proprietes.get(cle), str) or not proprietes[cle]:
            raise _forme(f"« {cle} » absent ou non textuel", url)
    distance = proprietes.get("distance")
    if distance is not None and not _est_nombre(distance):
        raise _forme("« distance » non numérique", url)
    candidat = {
        "label": proprietes["label"], "identifiant_ban": proprietes["id"], "type": proprietes["type"],
        "distance_m": None if distance is None else round(distance), "postcode": proprietes.get("postcode"),
        "citycode": proprietes["citycode"],
    }
    return candidat, proprietes.get("city")


def _geocodage_inverse(client: httpx.Client, lat: float, lon: float,
                       sleep: Callable[[float], Any]) -> tuple[list[dict], dict]:
    """(candidats BAN du plus proche au plus lointain, commune du premier). Une réponse vide est un échec."""
    proprietes = geocodage.inverse(client, lon=lon, lat=lat, index="address", limit=NB_CANDIDATS_BAN, sleep=sleep)
    if not proprietes:
        raise OpendataError(f"aucune adresse à proximité du point {lat}, {lon} ({geocodage.URL_REVERSE})")
    lus = [_lire_candidat_ban(p) for p in proprietes[:NB_CANDIDATS_BAN]]  # l'API classe par distance : son ordre est gardé
    premier, ville = lus[0]
    commune = {"insee": premier["citycode"], "nom": ville, "code_postal": premier["postcode"]}
    return [candidat for candidat, _ in lus], commune


# --- candidats DPE ------------------------------------------------------------------------------

def _borne_basse(valeur: float) -> int:
    """Borne basse arrondie au m2 vers le BAS (35,55 -> 35, 22,5 -> 22) : l'arrondi n'écarte jamais un DPE qui est dans
    la tolérance. `round(valeur, 9)` ôte le bruit flottant (100 x 1,1 = 110,00000000000001 ne doit pas faire 111)."""
    return math.floor(round(valeur, 9))


def _borne_haute(valeur: float) -> int:
    """Borne haute arrondie au m2 vers le HAUT (43,45 -> 44, 27,5 -> 28), même garde contre le bruit flottant."""
    return math.ceil(round(valeur, 9))


def _bornes_surface(surface: float) -> tuple[int, int]:
    return _borne_basse(surface * (1 - TOLERANCE_SURFACE)), _borne_haute(surface * (1 + TOLERANCE_SURFACE))


def _qs(insee: str, bas: int, haut: int, etiquette: str | None, date_dpe: str | None) -> str:
    filtres = [dpe._qs("code_insee_ban", insee), f"surface_habitable_logement:[{bas} TO {haut}]"]
    if etiquette:
        filtres.append(dpe._qs("etiquette_dpe", etiquette))
    if date_dpe:
        filtres.append(dpe._qs("date_etablissement_dpe", date_dpe))
    return " AND ".join(filtres)


def _verifier_filtres(ligne: dict, qs: str, insee: str, bas: int, haut: int, etiquette: str | None,
                      date_dpe: str | None) -> None:
    """`OpendataError` si une ligne ne correspond pas aux filtres demandés : l'API les a ignorés."""
    surface = ligne.get("surface_habitable_logement")
    conforme = (
        ligne.get("code_insee_ban") == insee
        and _est_nombre(surface) and bas <= surface <= haut
        and (not etiquette or ligne.get("etiquette_dpe") == etiquette)
        and (not date_dpe or ligne.get("date_etablissement_dpe") == date_dpe)
    )
    if not conforme:
        raise OpendataError(f"filtre ignoré par l'API : la ligne {ligne.get('numero_dpe')} ne correspond pas à "
                            f"{qs} ({dpe.URL})")


def _distance_m(geopoint: Any, lat: float, lon: float) -> int | None:
    """Distance du point au `_geopoint` « lat,lon » du DPE ; None si la position est absente ou illisible."""
    if not isinstance(geopoint, str):
        return None
    morceaux = geopoint.split(",")
    if len(morceaux) != 2:
        return None
    try:
        lat_dpe, lon_dpe = float(morceaux[0]), float(morceaux[1])
    except ValueError:
        return None
    if not (math.isfinite(lat_dpe) and math.isfinite(lon_dpe) and -90 <= lat_dpe <= 90 and -180 <= lon_dpe <= 180):
        return None
    return round(haversine_m(lat, lon, lat_dpe, lon_dpe))


def _candidat_dpe(ligne: dict, doublons: int, lat: float, lon: float) -> dict:
    return {
        "numero_dpe": ligne.get("numero_dpe"), "adresse_ban": ligne.get("adresse_ban"),
        "identifiant_ban": ligne.get("identifiant_ban"), "date_etablissement_dpe": ligne.get("date_etablissement_dpe"),
        "etiquette_dpe": ligne.get("etiquette_dpe"), "etiquette_ges": ligne.get("etiquette_ges"),
        "surface_habitable_logement": ligne.get("surface_habitable_logement"),
        "type_batiment": ligne.get("type_batiment"), "periode_construction": ligne.get("periode_construction"),
        "distance_m": _distance_m(ligne.get("_geopoint"), lat, lon), "doublons": doublons,
    }


def _chercher_dpe(client: httpx.Client, insee: str, lat: float, lon: float, etiquette: str | None,
                  date_dpe: str | None, info: dict, sleep: Callable[[float], Any], alertes: list[dict]) -> list[dict]:
    """Candidats DPE (dédoublonnés par adresse BAN, triés par distance, `NB_CANDIDATS_DPE` au plus). `info` porte la
    requête (`qs`, bornes) et reçoit les comptes (`total`, `lignes_lues`, `adresses_distinctes`)."""
    bas, haut = info["bornes_surface_m2"]
    qs = info["qs"]
    reponse = get_json(client, dpe.URL, {"qs": qs, "size": DPE_LIGNES_MAX, "select": ",".join(CHAMPS_DPE)}, sleep=sleep)
    total = dpe._total(reponse)
    lignes = reponse.get("results")
    if not isinstance(lignes, list) or not all(isinstance(ligne, dict) for ligne in lignes):
        raise _forme("« results » doit être une liste de lignes", dpe.URL)
    lignes = lignes[:DPE_LIGNES_MAX]  # plafond tenu même si l'API ignorait `size`
    for ligne in lignes:
        _verifier_filtres(ligne, qs, insee, bas, haut, etiquette, date_dpe)

    par_adresse: dict[str, list[dict]] = {}
    sans_adresse: list[dict] = []
    for ligne in lignes:
        identifiant = ligne.get("identifiant_ban")
        if isinstance(identifiant, str) and identifiant:
            par_adresse.setdefault(identifiant, []).append(ligne)
        else:  # pas d'identifiant BAN : impossible à dédoublonner, chaque ligne reste un candidat
            sans_adresse.append(ligne)
    candidats = [
        _candidat_dpe(max(groupe, key=lambda ligne: (str(ligne.get("date_etablissement_dpe") or ""),
                                                      str(ligne.get("numero_dpe") or ""))),
                      len(groupe) - 1, lat, lon)
        for groupe in par_adresse.values()
    ]
    candidats += [_candidat_dpe(ligne, 0, lat, lon) for ligne in sans_adresse]
    candidats.sort(key=lambda c: (c["distance_m"] is None, c["distance_m"] or 0, c["identifiant_ban"] or "",
                                  c["numero_dpe"] or ""))

    info.update(total=total, lignes_lues=len(lignes), adresses_distinctes=len(candidats))
    if total > len(lignes):
        suite = (f"{len(lignes)} lus (plafond {DPE_LIGNES_MAX}) : liste tronquée" if total > DPE_LIGNES_MAX
                 else f"{len(lignes)} reçus : liste incomplète")
        alertes.append({"bloc": "dpe", "message": f"{total} DPE correspondent à la recherche, {suite}"})
    if len(candidats) > NB_CANDIDATS_DPE:
        alertes.append({"bloc": "dpe", "message": (
            f"{len(candidats)} adresses distinctes ont un DPE dans la fourchette, les {NB_CANDIDATS_DPE} plus proches "
            f"parmi les {len(lignes)} DPE lus sont listées")})
    return candidats[:NB_CANDIDATS_DPE]


# --- assemblage ---------------------------------------------------------------------------------

def rechercher(lat: float, lon: float, *, client: httpx.Client, surface: float | None = None,
               etiquette: str | None = None, date_dpe: str | None = None, code_postal: str | None = None,
               insee: str | None = None, maintenant: datetime | None = None,
               sleep: Callable[[float], Any] = time.sleep) -> dict:
    """Adresses candidates du point (`lat`, `lon`). Ne lève jamais pour une panne de source : elle va dans `erreurs`.
    `insee` force la commune de la recherche DPE ; `code_postal` ne sert qu'à contrôler la commune du premier candidat."""
    if maintenant is None:
        maintenant = datetime.now().astimezone()
    genere_le = maintenant.isoformat(timespec="seconds")
    date_extraction = genere_le[:10]
    erreurs: list[dict] = []
    alertes: list[dict] = []
    sources: list[dict] = []

    candidats_ban: list[dict] | None = None
    commune: dict | None = None
    try:
        candidats_ban, commune = _geocodage_inverse(client, lat, lon, sleep)
    except Exception as exc:
        erreurs.append({"bloc": "geocodage_inverse", "message": _message(exc)})
    else:
        sources.append(SOURCE_INVERSE)
        if code_postal and commune["code_postal"] != code_postal:
            alertes.append({"bloc": "geocodage_inverse", "message": (
                f"le code postal demandé ({code_postal}) n'est pas celui du premier candidat "
                f"({commune['code_postal'] or 'n/d'}, {commune['nom'] or 'n/d'} {commune['insee']}) : le point est "
                f"peut-être hors de la commune de l'annonce ou n'en est que le centre")})

    candidats_dpe: list[dict] | None = None
    info_dpe: dict | None = None
    if surface is not None:
        insee_dpe = insee or (commune["insee"] if commune else None)
        if insee_dpe is None:
            alertes.append({"bloc": "dpe", "message": (
                "recherche DPE non faite : commune inconnue (géocodage inverse en échec et pas de --insee)")})
        else:
            if insee and commune and insee != commune["insee"]:
                alertes.append({"bloc": "dpe", "message": (
                    f"commune des DPE forcée à {insee} (--insee) ; le premier candidat BAN est dans la commune "
                    f"{commune['insee']}")})
            try:
                bas, haut = _bornes_surface(surface)
                info_dpe = {"qs": _qs(insee_dpe, bas, haut, etiquette, date_dpe), "bornes_surface_m2": [bas, haut],
                            "total": None, "lignes_lues": None, "adresses_distinctes": None}
                candidats_dpe = _chercher_dpe(client, insee_dpe, lat, lon, etiquette, date_dpe, info_dpe, sleep,
                                              alertes)
            except Exception as exc:
                erreurs.append({"bloc": "dpe", "message": _message(exc)})
            else:
                sources.append(SOURCE_DPE)

    return {
        "genere_le": genere_le,
        "point": {"lat": lat, "lon": lon},
        "parametres": {
            "demande": {"surface_m2": surface, "etiquette": etiquette, "date_dpe": date_dpe,
                        "code_postal": code_postal, "insee": insee},
            "methode": {"candidats_ban": NB_CANDIDATS_BAN, "tolerance_surface": TOLERANCE_SURFACE,
                        "candidats_dpe": NB_CANDIDATS_DPE, "dpe_lignes_max": DPE_LIGNES_MAX},
            "dpe": info_dpe,
        },
        "commune": commune,
        "candidats_ban": candidats_ban,
        "candidats_dpe": candidats_dpe,
        "sources": [{"bloc": s["bloc"], "url": s["url"], "date_extraction": date_extraction,
                     "licence": s["licence"], "millesime": s["millesime"]} for s in sources],
        "erreurs": erreurs,
        "alertes": alertes,
    }


def code_sortie(resultat: dict) -> int:
    """2 si le géocodage inverse a échoué (aucun candidat d'adresse) ; 3 si les DPE ont échoué alors que le géocodage
    inverse tient ; 0 sinon. Une alerte ne change pas le code."""
    if resultat["candidats_ban"] is None:
        return 2
    return 3 if resultat["erreurs"] else 0


def _distance_texte(distance_m: int | None) -> str:
    return "distance n/d" if distance_m is None else f"{distance_m} m"


def _surface_texte(surface: Any) -> str:
    """Surface en m2 à la française : 131.3 -> « 131,3 », 130 -> « 130 » ; une donnée absente -> « n/d »."""
    return f"{surface:g}".replace(".", ",") if _est_nombre(surface) else "n/d"


def resume(resultat: dict, chemin: str | Path) -> str:
    """Une ligne de tête, une ligne par candidat BAN, une ligne de recherche DPE puis une par candidat DPE, les
    erreurs, les alertes, le chemin du fichier. `n/d` = donnée absente."""
    point, commune = resultat["point"], resultat["commune"]
    if commune is None:
        lignes = [f"Point {point['lat']}, {point['lon']} : commune n/d"]
    else:
        lignes = [f"Point {point['lat']}, {point['lon']} : commune {commune['nom'] or 'n/d'} "
                  f"({commune['insee']}, code postal {commune['code_postal'] or 'n/d'})"]

    if resultat["candidats_ban"] is None:
        lignes.append("BAN : n/d")
    else:
        lignes += [f"BAN {rang} : {c['label']} ({c['type']}, {_distance_texte(c['distance_m'])}, "
                   f"{c['identifiant_ban']})" for rang, c in enumerate(resultat["candidats_ban"], start=1)]

    demande, info = resultat["parametres"]["demande"], resultat["parametres"]["dpe"]
    if demande["surface_m2"] is None:
        lignes.append("DPE : non demandé (pas de --surface)")
    elif resultat["candidats_dpe"] is None:
        lignes.append("DPE : n/d")
    else:
        bas, haut = info["bornes_surface_m2"]
        filtres = "".join(f", {nom} {valeur}" for nom, valeur in (("étiquette", demande["etiquette"]),
                                                                  ("date", demande["date_dpe"])) if valeur)
        lignes.append(f"Recherche DPE : surface {_surface_texte(demande['surface_m2'])} m² ({bas} à {haut} m²){filtres} : "
                      f"{info['lignes_lues']} DPE lus sur {info['total']}, {info['adresses_distinctes']} adresses, "
                      f"{len(resultat['candidats_dpe'])} listées")
        lignes += [
            f"DPE {rang} : {c['adresse_ban'] or 'adresse n/d'} : {c['etiquette_dpe'] or 'n/d'}, "
            f"{_surface_texte(c['surface_habitable_logement'])} m², {c['date_etablissement_dpe'] or 'date n/d'}, "
            f"{_distance_texte(c['distance_m'])} ({c['identifiant_ban'] or 'identifiant BAN n/d'})"
            for rang, c in enumerate(resultat["candidats_dpe"], start=1)]

    erreurs, alertes = resultat["erreurs"], resultat["alertes"]
    lignes.append("Erreurs : aucune" if not erreurs else
                  f"Erreurs : {len(erreurs)} ({', '.join(e['bloc'] for e in erreurs)})")
    lignes.append("Alertes : aucune" if not alertes else
                  "Alertes : " + " ; ".join(f"{a['bloc']} : {a['message']}" for a in alertes))
    lignes.append(f"Fiche écrite : {chemin}")
    return "\n".join(lignes)
