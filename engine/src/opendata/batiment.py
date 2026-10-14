"""Bâtiments d'une parcelle : année, murs, logements, niveaux, usage.

Source : BDNB, Base de données nationale des bâtiments du CSTB, API ouverte `https://api.bdnb.io/v1/bdnb/donnees`
(PostgREST), sans clé ni compte, Licence Ouverte 2.0. Documentation : https://bdnb.io/services/services_api/.

Quota de l'API ouverte (relevé du 07/10/2026) : 10 000 requêtes par mois et 120 par minute et par IP, et les
erreurs comptent aussi.
Coût d'une fiche : 2 requêtes par fiche (la relation parcelle -> groupes, puis la table complète) tant que la
parcelle compte au plus 10 groupes de bâtiments, plus 1 requête par paquet de 10 groupes en plus. Chaque nouvelle
tentative de `http` sur un 5xx ou un 429 compte aussi : aucune requête ne part si l'identifiant de parcelle est
douteux, et une erreur du demandeur (4xx) n'est jamais rejouée.

Deux appels GET, jamais de jointure intégrée :
1. `rel_batiment_groupe_parcelle?parcelle_id=eq.<idu>` : les `batiment_groupe_id` posés sur la parcelle ;
2. `batiment_groupe_complet?batiment_groupe_id=in.(<id1>,<id2>...)&select=<CHAMPS>` : leur description, par paquets
   de `BDNB_MAX_IDS`.

Particularités de l'API, constatées sur des réponses réelles le 07/10/2026 et rejouées le 08/10/2026 :
- la table complète a 138 colonnes et un polygone : `select=` est donc TOUJOURS donné.
- l'API plafonne `limit` à 10 SANS LE DIRE : une réponse ne dépasse pas 10 lignes. D'où `BDNB_MAX_IDS = 10`
  identifiants par appel. Une page partielle rend HTTP 206 (07/10) ou 200 avec `Content-Range: 0-9/*` (rejeu du
  08/10 : `limit=50` rend 10 lignes) : les deux sont acceptés (`get_json` ne rejette que les statuts de 400 et
  plus), le statut ne dit donc pas si la liste est complète. Ce plafond n'a pas été observé sur la relation
  (aucune parcelle de plus de 10 groupes lue) : 10 lignes reçues déclenchent une alerte « liste peut-être
  tronquée », jamais une liste tronquée en silence.
- `batiment_groupe_complet?l_parcelle_id=cs.{...}` rend 500 après 10 s, les jointures intégrées rendent 400 :
  ni l'une ni les autres ne sont utilisées.
- chaque ligne de la relation porte `parcelle_principale` (vrai pour les deux groupes d'une parcelle
  observée le 08/10/2026) : le champ est rendu tel quel dans chaque groupe, sa définition n'ayant pas été lue
  à la source (ne pas l'interpréter au-delà de la valeur brute). Absent ou nul : `null`.
- « usage mixte » n'existe pas en accès ouvert. `usage_mixte_indice` n'en est qu'un indice : vrai si un groupe a
  `nb_lot_tertiaire_rnc` > 0, null si aucun groupe n'a ce champ renseigné (une absence, pas un « non »).
- les valeurs sont brutes : la BDNB peut contredire le DPE ou l'annonce (`limites` le dit).

Un échec (réseau, 4xx, forme inattendue) lève `OpendataError` pour tout le bloc.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata.http import OpendataError, Resultat, get_json

URL = "https://api.bdnb.io/v1/bdnb/donnees"
URL_RELATION = f"{URL}/rel_batiment_groupe_parcelle"
URL_GROUPES = f"{URL}/batiment_groupe_complet"
LICENCE = (
    "Licence Ouverte 2.0 (Etalab) - Base de données nationale des bâtiments (BDNB), CSTB, API ouverte ; "
    "valeurs brutes"
)
SOURCE = {"bloc": "batiment", "url": URL, "licence": LICENCE, "millesime": None}
BDNB_MAX_IDS = 10  # plafond silencieux de l'API : 10 lignes par réponse, donc 10 identifiants par appel
CHAMPS = (
    "batiment_groupe_id", "annee_construction", "mat_mur_txt", "materiaux_structure_mur_exterieur", "nb_log",
    "nb_niveau", "usage_niveau_1_txt", "usage_principal_bdnb_open", "numero_immat_principal", "nb_log_rnc",
    "nb_lot_tertiaire_rnc",
)
LIMITES = (
    "usage mixte non publié en accès ouvert",
    "valeurs brutes : la BDNB peut contredire le DPE ou l'annonce",
    "usage_mixte_indice : vrai si un groupe a nb_lot_tertiaire_rnc > 0 ; null = champ non renseigné, ce qui ne "
    "prouve pas l'absence d'usage mixte",
)
_IDU = re.compile(r"[0-9A-Z]{14}")
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_-]+")  # ni virgule ni parenthèse : l'identifiant va dans un filtre in.(...)


def _forme(url: str, detail: str) -> OpendataError:
    return OpendataError(f"forme inattendue sur {url} : {detail}")


def _idu(parcelle: Any) -> str:
    """IDU de 14 caractères, en majuscules et sans espaces autour ; OpendataError sinon (rien ne part au réseau)."""
    idu = parcelle.strip().upper() if isinstance(parcelle, str) else ""
    if _IDU.fullmatch(idu) is None:
        raise OpendataError(f"parcelle invalide pour la BDNB : {parcelle!r} (IDU de 14 caractères attendu)")
    return idu


def _identifiants(lignes: Any, idu: str) -> tuple[list[str], dict[str, bool | None]]:
    """Identifiants (sans doublon, dans l'ordre reçu) des groupes posés sur la parcelle `idu`, et le champ brut
    `parcelle_principale` de leur ligne de relation (booléen, ou `None` s'il est absent ou nul)."""
    if not isinstance(lignes, list):
        raise _forme(URL_RELATION, "liste de lignes attendue")
    identifiants: list[str] = []
    principales: dict[str, bool | None] = {}
    for ligne in lignes:
        if not isinstance(ligne, dict):
            raise _forme(URL_RELATION, "ligne non objet")
        identifiant = ligne.get("batiment_groupe_id")
        if not isinstance(identifiant, str) or _IDENTIFIANT.fullmatch(identifiant) is None:
            raise _forme(URL_RELATION, "champ « batiment_groupe_id » absent ou illisible")
        if ligne.get("parcelle_id") != idu:  # filtre ignoré : on décrirait les bâtiments d'une autre parcelle
            raise OpendataError(
                f"filtre parcelle ignoré sur {URL_RELATION} : parcelle_id={ligne.get('parcelle_id')!r}, attendu {idu}")
        principale = ligne.get("parcelle_principale")
        if principale is not None and not isinstance(principale, bool):
            raise _forme(URL_RELATION, "champ « parcelle_principale » non booléen")
        if identifiant not in identifiants:
            identifiants.append(identifiant)
            principales[identifiant] = principale
    return identifiants, principales


def _groupe(ligne: Any, demandes: set[str], principales: dict[str, bool | None]) -> dict:
    if not isinstance(ligne, dict):
        raise _forme(URL_GROUPES, "ligne non objet")
    identifiant = ligne.get("batiment_groupe_id")
    if not isinstance(identifiant, str):
        raise _forme(URL_GROUPES, "champ « batiment_groupe_id » absent")
    if identifiant not in demandes:  # filtre ignoré : un groupe qu'on n'a pas demandé
        raise OpendataError(f"filtre batiment_groupe_id ignoré sur {URL_GROUPES} : {identifiant!r} non demandé")
    for cle in ("nb_log", "nb_lot_tertiaire_rnc"):  # ceux sur lesquels le bloc calcule : un nombre ou rien
        valeur = ligne.get(cle)
        if valeur is not None and (isinstance(valeur, bool) or not isinstance(valeur, (int, float))):
            raise _forme(URL_GROUPES, f"champ « {cle} » non numérique")
    immatriculation = ligne.get("numero_immat_principal")
    if immatriculation is not None and not isinstance(immatriculation, str):
        raise _forme(URL_GROUPES, "champ « numero_immat_principal » non textuel")
    return {
        "batiment_groupe_id": identifiant,
        "parcelle_principale": principales.get(identifiant),
        **{champ: ligne.get(champ) for champ in CHAMPS if champ != "batiment_groupe_id"},
    }


def _lire_paquet(client: httpx.Client, paquet: list[str], principales: dict[str, bool | None],
                 sleep: Callable[[float], Any]) -> list[dict]:
    params = {"batiment_groupe_id": f"in.({','.join(paquet)})", "select": ",".join(CHAMPS)}
    lignes = get_json(client, URL_GROUPES, params, sleep=sleep)
    if not isinstance(lignes, list):
        raise _forme(URL_GROUPES, "liste de lignes attendue")
    demandes = set(paquet)
    groupes: dict[str, dict] = {}
    for ligne in lignes:
        groupe = _groupe(ligne, demandes, principales)
        groupes.setdefault(groupe["batiment_groupe_id"], groupe)
    return list(groupes.values())


def _cle_tri(groupe: dict) -> tuple:
    """nb_log décroissant, null en dernier (0 logement passe avant null : une valeur avant une absence), puis id."""
    nb_log = groupe["nb_log"]
    return nb_log is None, -(nb_log or 0), groupe["batiment_groupe_id"]


def collecter(client: httpx.Client, parcelle: str, *, sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Bâtiments de la parcelle `parcelle` (IDU de 14 caractères) ; `OpendataError` au moindre échec.

    `bloc` : `parcelle` (IDU normalisé) ; `groupes` (`batiment_groupe_id`, `parcelle_principale` de la relation,
    puis les dix autres champs de `CHAMPS` ; triés par nb_log décroissant, null en dernier, puis identifiant) ;
    `n_groupes` ; `immatriculations` (les `numero_immat_principal` non nuls, sans doublon) ; `usage_mixte_indice` ;
    `limites` ; `parametres` (le paquet d'identifiants par appel). Aucune ligne de relation : `groupes` vide et une
    alerte.
    """
    idu = _idu(parcelle)
    lignes = get_json(client, URL_RELATION, {"parcelle_id": f"eq.{idu}"}, sleep=sleep)
    identifiants, principales = _identifiants(lignes, idu)
    alertes: list[dict] = []
    groupes: list[dict] = []
    if not identifiants:
        alertes.append({"bloc": "batiment", "message": "aucun bâtiment BDNB sur la parcelle"})
    else:
        if len(lignes) >= BDNB_MAX_IDS:
            alertes.append({"bloc": "batiment", "message": (
                f"{len(lignes)} groupes de bâtiments reçus pour la parcelle : c'est le plafond silencieux de la "
                f"BDNB ({BDNB_MAX_IDS} lignes par réponse), la liste est peut-être tronquée")})
        for debut in range(0, len(identifiants), BDNB_MAX_IDS):
            groupes.extend(_lire_paquet(client, identifiants[debut:debut + BDNB_MAX_IDS], principales, sleep))
        recus = {groupe["batiment_groupe_id"] for groupe in groupes}
        manquants = [identifiant for identifiant in identifiants if identifiant not in recus]
        if manquants:
            alertes.append({"bloc": "batiment", "message": (
                f"{len(manquants)} groupe(s) de la relation parcelle sans ligne dans batiment_groupe_complet : "
                f"{', '.join(manquants)}")})
    groupes.sort(key=_cle_tri)
    tertiaires = [g["nb_lot_tertiaire_rnc"] for g in groupes if g["nb_lot_tertiaire_rnc"] is not None]
    bloc = {
        "parcelle": idu,
        "groupes": groupes,
        "n_groupes": len(groupes),
        "immatriculations": list(dict.fromkeys(g["numero_immat_principal"] for g in groupes
                                               if g["numero_immat_principal"])),
        "usage_mixte_indice": any(t > 0 for t in tertiaires) if tertiaires else None,
        "limites": list(LIMITES),
        "parametres": {"max_identifiants_par_appel": BDNB_MAX_IDS},
    }
    return Resultat(bloc, [], [dict(SOURCE)], alertes)
