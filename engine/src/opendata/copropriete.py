"""Copropriétés immatriculées sur la parcelle d'un bien et autour de lui.

Source : RNIC, registre national d'immatriculation des copropriétés (ANAH), diffusé sur data.gouv.fr (Licence
Ouverte 2.0, mis à jour chaque jour), ressource `3ea8e2c3-0038-464a-b17e-cd5c91f65ce2`. Le fichier national fait
409 Mo (07/10/2026) : il n'est JAMAIS téléchargé. Seule l'API tabulaire de data.gouv.fr est interrogée, sans clé,
filtrée par commune (`commune__exact`), 200 lignes par page, en suivant `links.next` jusqu'à `RNIC_MAX_PAGES` pages.
Si l'API tabulaire refuse la ressource (4xx autre que 429), `OpendataError` : aucun repli sur le fichier national.

Particularités constatées le 07/10/2026 et rejouées le 08/10/2026 :
- `code_officiel_commune` contient le CODE POSTAL : le filtre porte sur `commune`, qui est l'INSEE.
- `page_size` au-delà de 200 rend 400 (« Page size exceeds allowed maximum: 200 »). `columns=a,b,c` restreint
  les colonnes (syntaxe lue dans le swagger de la ressource, et honorée : 18 colonnes rendues le 08/10) : seules
  les colonnes de `COLONNES` sont demandées et recopiées.
- Aucune identité de syndic : `identification_representant_legal`, `raison_sociale_representant_legal` et
  `siret_representant_legal` ne sont jamais demandées ni recopiées (données de personnes). Une ligne qui les
  porterait quand même (colonnes ignorées par le serveur) est réduite aux colonnes utiles.
- `reference_cadastrale_1` à `_3` : au plus 3 références, alors que `nombre_parcelles` peut dépasser 3, et certaines
  lignes n'en ont aucune. Elles sont parfois en minuscules (« 99999000ak0001 ») : comparées en majuscules et sans
  espaces, aux deux bouts.
- `nombre_lots_habitation_bureaux_commerces` (nom lu dans le swagger de la ressource, 08/10/2026) est rendu tel
  quel avec les autres comptes de lots : c'est la seule piste ouverte d'un usage mixte de la copropriété (valeur brute,
  sa définition n'a pas été lue à la source).
- `periode_construction` est hétérogène : rendue telle quelle.
- L'ABSENCE d'une parcelle au RNIC ne prouve pas l'absence de copropriété. Cas observé (08/10/2026) : la
  parcelle du bien n'y figure pas, alors qu'une copropriété est immatriculée sur la parcelle voisine, à environ 42 m.

Distance : `dvf.haversine_m`, du point géocodé au point de la copropriété (coordonnées du RNIC), en mètres, arrondie
au dixième. Une voisine est à `distance <= RAYON_VOISINES_M` ; celle déjà `sur_la_parcelle` n'est pas comptée parmi
les voisines. Rayon, nombre de voisines, taille et nombre de pages sont des paramètres de méthode : ils sont dits
dans `parametres`.

Un échec (réseau, 4xx, forme inattendue, filtre ignoré) lève `OpendataError` pour tout le bloc.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.opendata.dvf import haversine_m
from src.opendata.http import OpendataError, Resultat, get_json

RESSOURCE = "3ea8e2c3-0038-464a-b17e-cd5c91f65ce2"
URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE}/data/"
LICENCE = (
    "Licence Ouverte 2.0 (Etalab) - Registre national d'immatriculation des copropriétés (RNIC), ANAH, via "
    "l'API tabulaire de data.gouv.fr ; mis à jour chaque jour"
)
SOURCE = {"bloc": "copropriete", "url": URL, "licence": LICENCE, "millesime": None}
RNIC_PAGE_SIZE = 200  # au-delà, l'API tabulaire répond 400
RNIC_MAX_PAGES = 20  # soit 4 000 lignes : au-delà, la liste de la commune est tronquée et l'alerte le dit
RAYON_VOISINES_M = 50
NB_VOISINES_MAX = 5
COLONNES = (
    "numero_immatriculation", "nom_usage_copropriete", "adresse_reference", "commune", "longitude", "latitude",
    "reference_cadastrale_1", "reference_cadastrale_2", "reference_cadastrale_3", "nombre_parcelles",
    "nombre_total_lots", "nombre_lots_habitation", "nombre_lots_habitation_bureaux_commerces",
    "nombre_lots_stationnement", "periode_construction", "date_immatriculation", "date_derniere_maj", "type_syndic",
    "mandat_en_cours",
)


def _forme(detail: str) -> OpendataError:
    return OpendataError(f"forme inattendue sur {URL} : {detail}")


def _normaliser(reference: Any) -> str:
    """Référence cadastrale comparable : sans aucun espace, en majuscules ; chaîne vide si ce n'est pas un texte."""
    return "".join(reference.split()).upper() if isinstance(reference, str) else ""


def _parcelle(parcelle: Any) -> str | None:
    """IDU normalisé, ou None si la parcelle est inconnue (None, vide) ; OpendataError si ce n'est pas un texte."""
    if parcelle is None:
        return None
    if not isinstance(parcelle, str):
        raise OpendataError(f"parcelle illisible pour le RNIC : {parcelle!r} (IDU en texte, ou None, attendu)")
    return _normaliser(parcelle) or None


def _flottant(valeur: Any) -> float | None:
    """Nombre fini d'une cellule (nombre ou texte numérique) ; booléen, vide, non numérique ou non fini -> None."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        nombre = float(valeur)
    elif isinstance(valeur, str):
        try:
            nombre = float(valeur)
        except ValueError:
            return None
    else:
        return None
    return nombre if math.isfinite(nombre) else None


def _coordonnees(brute: dict) -> tuple[float, float] | None:
    """(latitude, longitude) si les deux sont lisibles et plausibles, sinon None (jamais 0 à la place)."""
    lon, lat = _flottant(brute.get("longitude")), _flottant(brute.get("latitude"))
    if lon is None or lat is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _ligne(brute: Any, insee: str) -> dict:
    """Une ligne du RNIC réduite aux colonnes utiles ; OpendataError si la forme change ou si le filtre est ignoré."""
    if not isinstance(brute, dict):
        raise _forme("ligne non objet")
    if str(brute.get("commune")).strip() != insee:  # filtre ignoré : on tiendrait les copropriétés d'une autre commune
        raise OpendataError(f"filtre commune ignoré sur {URL} : commune={brute.get('commune')!r}, attendu {insee}")
    coordonnees = _coordonnees(brute)
    references = [r for r in (_normaliser(brute.get(f"reference_cadastrale_{i}")) for i in (1, 2, 3)) if r]
    return {
        "numero_immatriculation": brute.get("numero_immatriculation"),
        "nom_usage_copropriete": brute.get("nom_usage_copropriete"),
        "adresse_reference": brute.get("adresse_reference"),
        "longitude": None if coordonnees is None else coordonnees[1],
        "latitude": None if coordonnees is None else coordonnees[0],
        "references_cadastrales": references,
        "nombre_parcelles": brute.get("nombre_parcelles"),
        "nombre_total_lots": brute.get("nombre_total_lots"),
        "nombre_lots_habitation": brute.get("nombre_lots_habitation"),
        "nombre_lots_habitation_bureaux_commerces": brute.get("nombre_lots_habitation_bureaux_commerces"),
        "nombre_lots_stationnement": brute.get("nombre_lots_stationnement"),
        "periode_construction": brute.get("periode_construction"),
        "date_immatriculation": brute.get("date_immatriculation"),
        "date_derniere_maj": brute.get("date_derniere_maj"),
        "type_syndic": brute.get("type_syndic"),
        "mandat_en_cours": brute.get("mandat_en_cours"),
    }


def _page(donnees: Any) -> tuple[list, int, str | None]:
    """(lignes brutes, meta.total, links.next) d'une page de l'API tabulaire."""
    if not isinstance(donnees, dict) or not isinstance(donnees.get("data"), list):
        raise _forme("clé « data » absente ou non liste")
    meta, liens = donnees.get("meta"), donnees.get("links")
    if not isinstance(meta, dict) or type(meta.get("total")) is not int:
        raise _forme("« meta.total » entier attendu")
    if not isinstance(liens, dict) or "next" not in liens:
        raise _forme("« links.next » absent")
    suivante = liens["next"]
    if suivante is not None and not (isinstance(suivante, str) and suivante.strip()):
        raise _forme("« links.next » doit être un lien ou null")
    return donnees["data"], meta["total"], suivante


def _lien_suivant(lien: str) -> str:
    """Lien de la page suivante, suivi seulement s'il reste sur l'hôte de l'API tabulaire (et toujours en https)."""
    base = httpx.URL(URL)
    try:
        cible = base.join(lien)
    except (httpx.InvalidURL, ValueError) as exc:
        raise OpendataError(f"lien de page suivante illisible : {lien!r} ({URL})") from exc
    if cible.scheme not in ("http", "https") or cible.host != base.host:
        raise OpendataError(f"lien de page suivante hors de l'API tabulaire, non suivi : {lien!r} ({URL})")
    return str(cible.copy_with(scheme="https"))


def _lire_commune(client: httpx.Client, insee: str, sleep: Callable[[float], Any]) -> tuple[list[dict], int, int, bool]:
    """(lignes, total annoncé par la première page, pages lues, liste tronquée au plafond de pages)."""
    params = {"commune__exact": insee, "page_size": RNIC_PAGE_SIZE, "columns": ",".join(COLONNES)}
    donnees = get_json(client, URL, params, sleep=sleep)
    lignes: list[dict] = []
    total = 0
    pages = 0
    while True:
        pages += 1
        brutes, total_page, suivante = _page(donnees)
        if pages == 1:
            total = total_page
        lignes.extend(_ligne(brute, insee) for brute in brutes)
        if suivante is None:
            return lignes, total, pages, False
        if pages >= RNIC_MAX_PAGES:
            return lignes, total, pages, True
        donnees = get_json(client, _lien_suivant(suivante), sleep=sleep)


def collecter(client: httpx.Client, geo: dict, parcelle: str | None, *,
              sleep: Callable[[float], Any] = time.sleep) -> Resultat:
    """Copropriétés du RNIC sur `parcelle` (IDU, ou None) et à moins de `RAYON_VOISINES_M` m du point `geo`.

    `bloc` : `n_commune` (total annoncé par l'API pour la commune) ; `sur_la_parcelle` (lignes dont une référence
    cadastrale égale la parcelle) ; `voisines` (à `distance_m` du point, les `NB_VOISINES_MAX` plus proches, hors
    parcelle) ; `correspondance` (`parcelle`, `aucune` ou `parcelle inconnue`) ; `parametres`. Les lignes sans
    coordonnées utilisables sont comptées (`parametres.sans_coordonnees`) et exclues des voisines.
    """
    insee = geo["citycode"]
    idu = _parcelle(parcelle)
    lignes, total, pages, tronquee = _lire_commune(client, insee, sleep)

    sur_la_parcelle: list[dict] = []
    proches: list[tuple[float, str, dict]] = []
    sans_coordonnees = 0
    for ligne in lignes:
        a_des_coordonnees = ligne["latitude"] is not None and ligne["longitude"] is not None
        if not a_des_coordonnees:
            sans_coordonnees += 1
        if idu is not None and idu in ligne["references_cadastrales"]:
            sur_la_parcelle.append(ligne)
        elif a_des_coordonnees:
            distance = haversine_m(geo["lat"], geo["lon"], ligne["latitude"], ligne["longitude"])
            if distance <= RAYON_VOISINES_M:
                proches.append((distance, str(ligne["numero_immatriculation"]), ligne))
    sur_la_parcelle.sort(key=lambda ligne: str(ligne["numero_immatriculation"]))
    proches.sort(key=lambda proche: proche[:2])
    voisines = [{**ligne, "distance_m": round(distance, 1)} for distance, _, ligne in proches[:NB_VOISINES_MAX]]

    alertes: list[dict] = []
    if tronquee:
        alertes.append({"bloc": "copropriete", "message": (
            f"plafond de {RNIC_MAX_PAGES} pages atteint ({RNIC_PAGE_SIZE} lignes par page) : {len(lignes)} lignes "
            f"lues sur {total} annoncées, la liste de la commune est incomplète")})
    elif len(lignes) != total:
        alertes.append({"bloc": "copropriete", "message": (
            f"{total} copropriétés annoncées pour la commune, {len(lignes)} lues : liste incomplète")})
    if len(proches) > NB_VOISINES_MAX:
        alertes.append({"bloc": "copropriete", "message": (
            f"{len(proches)} copropriétés à moins de {RAYON_VOISINES_M} m du point : les {NB_VOISINES_MAX} plus "
            "proches sont listées")})
    if idu is None:
        correspondance = "parcelle inconnue"
        alertes.append({"bloc": "copropriete", "message": (
            "parcelle inconnue : correspondance avec le RNIC impossible, seules les copropriétés voisines sont "
            "listées ; l'absence du RNIC ne prouve pas l'absence de copropriété")})
    elif sur_la_parcelle:
        correspondance = "parcelle"
    else:
        correspondance = "aucune"
        alertes.append({"bloc": "copropriete", "message": (
            f"aucune copropriété immatriculée sur la parcelle {idu} : l'absence du RNIC ne prouve pas "
            "l'absence de copropriété")})

    bloc = {
        "n_commune": total,
        "sur_la_parcelle": sur_la_parcelle,
        "voisines": voisines,
        "correspondance": correspondance,
        "parametres": {
            "insee": insee, "parcelle": idu,
            "rayon_voisines_m": RAYON_VOISINES_M, "max_voisines": NB_VOISINES_MAX,
            "page_size": RNIC_PAGE_SIZE, "max_pages": RNIC_MAX_PAGES,
            "pages_lues": pages, "lignes_lues": len(lignes),
            "sans_coordonnees": sans_coordonnees, "voisines_dans_le_rayon": len(proches),
        },
    }
    return Resultat(bloc, [], [dict(SOURCE)], alertes)
