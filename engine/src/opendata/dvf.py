"""Comparables de vente autour d'un point, depuis DVF géolocalisé.

Source : fichiers CSV communaux « Demandes de valeurs foncières géolocalisées » (DGFiP, publiés sur
files.data.gouv.fr), un fichier par année et par commune. Une année absente répond 404 (parfois
après une redirection 302) : elle est comptée, pas signalée comme une erreur.

Particularités qui font le cœur du module :
- Une ligne du CSV n'est PAS une vente ni un bien : une mutation (`id_mutation`) s'étale sur
  plusieurs lignes, et une même maison est répétée une fois par nature de culture du terrain, avec
  la valeur de toute la mutation. On regroupe donc par mutation, puis par LOCAL (clé `CLE_LOCAL`).
- Une mutation à plusieurs locaux bâtis est exclue des COMPARABLES : son prix global n'est pas attribuable à un
  bien. Elle alimente un bloc distinct, `immeubles` (option `fenetre_immeubles_mois`) : ventes de la commune du bien
  à 2 locaux bâtis ou plus dont un logement, avec leur prix global, leur surface bâtie totale et leurs €/m2 et
  €/logement ; médianes seulement à partir de `N_MIN_MEDIANE_IMMEUBLES` ventes. Deux médianes : la BRUTE
  (`statistiques`, toutes les ventes retenues, jamais citable comme référence d'immeuble de rapport : elle mêle
  maisons, sites industriels, résidences vendues en bloc et reventes) et la médiane de RÉFÉRENCE (`reference`, convention
  du moteur) : ventes à `NB_LOGEMENTS_REFERENCE_MIN` logements ou plus, sans vente atypique (`bloc` :
  `NB_LOGEMENTS_BLOC` logements ou plus ; `activite_dominante` : plus de surface d'activité que d'habitation), une
  seule vente par groupe de parcelles (la plus récente). Chaque vente porte ses parcelles, ses surfaces par usage, ses
  motifs d'atypie et `dans_reference`.
- `derniere_mutation` et `annees_absentes` disent la fraîcheur réelle de DVF : sous `FENETRE_EFFECTIVE_MIN_MOIS`
  mois entre le début de fenêtre et la dernière mutation, une alerte (`Resultat.alertes`) le dit.
- `type_local` vide = terrain, « Dépendance » = annexe : ni l'un ni l'autre n'est un local bâti.
- Chaque mutation tombe dans UN compteur (`compteurs`), dans l'ordre des exclusions de `_evaluer` ;
  `mutations` = somme des exclusions + `retenues`, de sorte qu'aucune vente ne disparaisse sans trace.
- Une donnée illisible (prix, surface, coordonnées) est une exclusion comptée, jamais un 0.
- Un comparable au prix_m2 atypique est SIGNALÉ (`atypique`, `motif_atypie`), jamais retiré : il reste dans
  `par_type`, et figure dans `comparables`, avec son drapeau, seulement s'il est parmi les 15 plus récents ;
  `atypiques` en donne le compte par type, sur tous les retenus. Barrières de Tukey par type, sur tous les
  retenus du type ; sous `N_MIN_ATYPIE` retenus, `null` (pas de drapeau plutôt qu'un drapeau sans base) et
  `atypiques` vaut `null`, non 0.
"""

from __future__ import annotations

import calendar
import csv
import io
import math
import statistics
import time
from collections import Counter
from collections.abc import Callable
from datetime import date

import httpx

from src.opendata.http import NotFound, OpendataError, Resultat, get_text

URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/communes/{dep}/{insee}.csv"
LICENCE = (
    "Licence Ouverte 2.0 (Etalab) - DGFiP, Demandes de valeurs foncières géolocalisées ; réutilisation "
    "soumise aux CGU DGFiP : ni réidentification des personnes, ni indexation par les moteurs de recherche"
)
R_TERRE_M = 6_371_000
NATURES_RETENUES = ("Vente", "Adjudication")
TYPES_HABITATION = ("Maison", "Appartement")
TYPES_NON_BATIS = ("", "Dépendance")  # terrain (type vide) et annexe : jamais un local bâti
NB_COMPARABLES = 15
COEFFICIENT_TUKEY = 1.5  # convention de Tukey : barrières à 1,5 x l'écart interquartile (EIQ) des quartiles
N_MIN_ATYPIE = 5  # en dessous, pas de drapeau : des barrières sur moins de 5 prix n'ont pas de base
_COEF_FR = f"{COEFFICIENT_TUKEY:g}".replace(".", ",")
LOTS = ("lot1_numero", "lot2_numero", "lot3_numero", "lot4_numero", "lot5_numero")
CLE_LOCAL = ("numero_disposition", "id_parcelle", "type_local", "surface_reelle_bati",
             "nombre_pieces_principales", *LOTS)  # une disposition = une opération de vente distincte
SIGNATURE_CULTURE = ("nature_culture", "nature_culture_speciale", "surface_terrain")
COLONNES = (
    "id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere", *CLE_LOCAL, *SIGNATURE_CULTURE,
    "longitude", "latitude", "adresse_numero", "adresse_suffixe", "adresse_nom_voie",
)
COMPTEURS = (
    "lignes_lues", "mutations", "exclues_nature", "exclues_hors_fenetre", "exclues_multi_locaux",
    "exclues_sans_local_habitation", "exclues_prix_ou_surface", "exclues_sans_coordonnees", "hors_rayon",
    "retenues", "annees_absentes",
)
FENETRE_IMMEUBLES_MOIS = 60  # fenêtre PROPRE aux ventes d'immeubles, distincte de celle des comparables
N_MIN_MEDIANE_IMMEUBLES = 3  # sous 3 ventes retenues : médianes null, avec la raison (brute comme de référence)
NB_IMMEUBLES = 20  # ventes listées (les plus proches) ; les statistiques portent sur toutes les retenues
NB_LOGEMENTS_REFERENCE_MIN = 3  # médiane de RÉFÉRENCE : ventes à 3 logements ou plus (convention du moteur)
NB_LOGEMENTS_BLOC = 20  # à partir de 20 logements : résidence vendue en bloc, vente atypique (motif `bloc`)
MOTIFS_IMMEUBLES = ("sans_logement", "prix_ou_surface", "sans_coordonnees")  # ordre du contrat, comme `_evaluer`
FENETRE_EFFECTIVE_MIN_MOIS = 18  # sous ce nombre de mois entre le début de fenêtre et la dernière mutation : alerte


def departement(insee: str) -> str:
    """Outre-mer : 3 caractères (974) ; ailleurs 2, Corse comprise (2A, 2B)."""
    return insee[:3] if insee.startswith("97") else insee[:2]


def date_debut_fenetre(aujourdhui: date, fenetre_mois: int) -> date:
    """`aujourdhui` moins `fenetre_mois` mois calendaires, le jour ramené à la fin du mois si besoin."""
    annee, mois = divmod(aujourdhui.year * 12 + aujourdhui.month - 1 - fenetre_mois, 12)
    mois += 1
    return date(annee, mois, min(aujourdhui.day, calendar.monthrange(annee, mois)[1]))


def annees_couvrantes(aujourdhui: date, fenetre_mois: int) -> list[int]:
    return list(range(date_debut_fenetre(aujourdhui, fenetre_mois).year, aujourdhui.year + 1))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlon / 2) ** 2
    return 2 * R_TERRE_M * math.asin(math.sqrt(min(1.0, a)))  # min : l'arrondi flottant peut dépasser 1


def _nombre(texte: str) -> float | None:
    """Nombre d'une cellule CSV ; vide, non numérique ou non fini -> None (jamais 0)."""
    try:
        valeur = float(texte)
    except ValueError:
        return None
    return valeur if math.isfinite(valeur) else None


def _coordonnees(ligne: dict[str, str]) -> tuple[float, float] | None:
    """(latitude, longitude) si les deux sont lisibles et plausibles, sinon None."""
    lon, lat = _nombre(ligne["longitude"]), _nombre(ligne["latitude"])
    if lon is None or lat is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _date_mutation(ligne: dict[str, str]) -> date:
    try:
        return date.fromisoformat(ligne["date_mutation"])
    except ValueError as exc:
        raise OpendataError(
            f"DVF : date_mutation illisible ({ligne['date_mutation']!r}) pour la mutation {ligne['id_mutation']}"
        ) from exc


def _lire_csv(texte: str, url: str) -> list[dict[str, str]]:
    lecteur = csv.DictReader(io.StringIO(texte, newline=""), restval="")
    manquantes = [c for c in COLONNES if c not in (lecteur.fieldnames or [])]
    if manquantes:
        raise OpendataError(f"DVF : forme inattendue sur {url}, colonnes absentes : {', '.join(manquantes)}")
    return list(lecteur)


def _nb_locaux(lignes: list[dict[str, str]]) -> int:
    """Nombre de locaux derrière les lignes d'une même clé. Un lot renseigné identifie le local : un seul.
    Sans lot, un local n'apparaît qu'UNE fois par signature de culture du terrain (une maison sur deux
    cultures = deux lignes, un local) : la même signature répétée désigne des locaux distincts, comme les
    4 appartements identiques de 25 m2 sans lot d'une même vente (cas observé)."""
    if any(lignes[0][c] for c in LOTS):
        return 1
    return max(Counter(tuple(ligne[c] for c in SIGNATURE_CULTURE) for ligne in lignes).values())


def _locaux_batis(lignes: list[dict[str, str]]) -> dict[tuple[str, ...], list[dict[str, str]]]:
    """Lignes d'une mutation regroupées par local bâti (clé `CLE_LOCAL`) ; terrains et dépendances écartés."""
    locaux: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for ligne in lignes:
        if ligne["type_local"] not in TYPES_NON_BATIS:
            locaux.setdefault(tuple(ligne[c] for c in CLE_LOCAL), []).append(ligne)
    return locaux


def _evaluer(lignes: list[dict[str, str]], date_mutation: date, debut: date, lat: float, lon: float,
             rayon_m: float) -> tuple[str, dict | None]:
    """Classe une mutation : (nom du compteur, comparable ou None). L'ordre des tests est celui du contrat."""
    premiere = lignes[0]
    if premiere["nature_mutation"] not in NATURES_RETENUES:
        return "exclues_nature", None
    if date_mutation < debut:
        return "exclues_hors_fenetre", None

    locaux = _locaux_batis(lignes)
    if sum(_nb_locaux(lignes_cle) for lignes_cle in locaux.values()) >= 2:
        return "exclues_multi_locaux", None
    if not locaux:
        return "exclues_sans_local_habitation", None
    lignes_local = next(iter(locaux.values()))
    type_local = lignes_local[0]["type_local"]
    if type_local not in TYPES_HABITATION:
        return "exclues_sans_local_habitation", None

    valeur = _nombre(premiere["valeur_fonciere"])
    surface = _nombre(lignes_local[0]["surface_reelle_bati"])
    if valeur is None or surface is None or valeur <= 0 or surface <= 0:
        return "exclues_prix_ou_surface", None

    point = next((c for c in map(_coordonnees, lignes_local) if c is not None), None)
    if point is None:
        return "exclues_sans_coordonnees", None
    distance = haversine_m(lat, lon, *point)
    if distance > rayon_m:
        return "hors_rayon", None

    ligne = lignes_local[0]
    pieces = _nombre(ligne["nombre_pieces_principales"])
    morceaux = (ligne[c].strip() for c in ("adresse_numero", "adresse_suffixe", "adresse_nom_voie"))
    return "retenues", {
        "date": date_mutation.isoformat(), "type": type_local, "surface": surface,
        "pieces": int(pieces) if pieces is not None and pieces.is_integer() else None,
        "prix": valeur, "prix_m2": valeur / surface,  # non arrondi : les statistiques partent de là
        "distance_m": round(distance), "adresse": " ".join(m for m in morceaux if m), "id_mutation": premiere["id_mutation"],
    }


def _quartiles(prix_m2: list[float]) -> list[float]:
    """Les trois quartiles, méthode « inclusive » de `statistics.quantiles` : ils restent dans [min ; max] des
    prix observés (l'exclusive en sort dès n = 2 : 750 / 2 250 pour 1 000 / 2 000, et un p25 sous le prix
    minimal est trompeur). Au moins 2 valeurs."""
    return statistics.quantiles(prix_m2, n=4, method="inclusive")


def _stats(prix_m2: list[float]) -> dict:
    """Médiane et quartiles (`_quartiles`) ; None si n < 2."""
    n = len(prix_m2)
    if n < 2:
        return {"n": n, "mediane": None, "p25": None, "p75": None}
    quartiles = _quartiles(prix_m2)
    return {"n": n, "mediane": round(statistics.median(prix_m2), 2),
            "p25": round(quartiles[0], 2), "p75": round(quartiles[2], 2)}


def _barrieres_tukey(prix_m2: list[float]) -> tuple[float, float] | None:
    """[p25 - 1,5 x EIQ ; p75 + 1,5 x EIQ] sur les quartiles NON arrondis ; None sous `N_MIN_ATYPIE` prix."""
    if len(prix_m2) < N_MIN_ATYPIE:
        return None
    p25, _, p75 = _quartiles(prix_m2)
    eiq = p75 - p25
    return p25 - COEFFICIENT_TUKEY * eiq, p75 + COEFFICIENT_TUKEY * eiq


def _atypie(prix_m2: float, barrieres: tuple[float, float] | None, type_local: str, n: int) -> dict:
    """Drapeau et motif d'un comparable (prix_m2 non arrondi). `null` sans barrières ; hors barrières : `true`."""
    if barrieres is None:
        return {"atypique": None, "motif_atypie": None}
    bas, haut = barrieres
    if prix_m2 < bas:
        return {"atypique": True, "motif_atypie": f"prix_m2 < p25 − {_COEF_FR} × EIQ ({type_local}, n = {n})"}
    if prix_m2 > haut:
        return {"atypique": True, "motif_atypie": f"prix_m2 > p75 + {_COEF_FR} × EIQ ({type_local}, n = {n})"}
    return {"atypique": False, "motif_atypie": None}


def _evaluer_immeuble(lignes: list[dict[str, str]], date_mutation: date, debut: date, lat: float,
                      lon: float) -> tuple[str, tuple[dict, float, float] | None]:
    """Classe une mutation pour le bloc `immeubles` : (nom du compteur, (vente, €/m2, €/logement) ou None).

    `hors_perimetre` (non comptée) : nature non retenue, avant la fenêtre, ou moins de 2 locaux bâtis (le cas des
    comparables). Une mutation à 2 locaux bâtis ou plus est « vue » ; elle est ensuite `retenues` ou écartée, pour
    un seul motif, dans l'ordre de `MOTIFS_IMMEUBLES`. Surface = somme des surfaces des locaux distincts : un local
    répété sur plusieurs lignes (cultures du terrain) compte une fois, des locaux identiques sans lot (`_nb_locaux`)
    comptent chacun."""
    premiere = lignes[0]
    if premiere["nature_mutation"] not in NATURES_RETENUES or date_mutation < debut:
        return "hors_perimetre", None
    locaux = _locaux_batis(lignes)
    nombres = {cle: _nb_locaux(lignes_cle) for cle, lignes_cle in locaux.items()}
    if sum(nombres.values()) < 2:
        return "hors_perimetre", None

    types: Counter[str] = Counter()
    for cle, lignes_cle in locaux.items():
        types[lignes_cle[0]["type_local"]] += nombres[cle]
    nb_logements = sum(n for type_local, n in types.items() if type_local in TYPES_HABITATION)
    if nb_logements == 0:
        return "sans_logement", None

    valeur = _nombre(premiere["valeur_fonciere"])
    surfaces = {cle: _nombre(lignes_cle[0]["surface_reelle_bati"]) for cle, lignes_cle in locaux.items()}
    if valeur is None or valeur <= 0 or any(s is None or s <= 0 for s in surfaces.values()):
        return "prix_ou_surface", None
    surface = sum(surfaces[cle] * nombres[cle] for cle in locaux)
    habitation = sum(surfaces[cle] * nombres[cle] for cle, lignes_cle in locaux.items()
                     if lignes_cle[0]["type_local"] in TYPES_HABITATION)
    activite = sum(surfaces[cle] * nombres[cle] for cle, lignes_cle in locaux.items()
                   if lignes_cle[0]["type_local"] not in TYPES_HABITATION)

    point = next((c for lignes_cle in locaux.values() for c in map(_coordonnees, lignes_cle) if c is not None), None)
    if point is None:
        return "sans_coordonnees", None

    ligne = next(iter(locaux.values()))[0]
    morceaux = (ligne[c].strip() for c in ("adresse_numero", "adresse_suffixe", "adresse_nom_voie"))
    eur_m2, eur_logement = valeur / surface, valeur / nb_logements  # non arrondis : les médianes partent de là
    # Parcelles des seuls locaux bâtis ; un `id_parcelle` vide n'identifie rien (jamais une parcelle commune).
    parcelles = sorted({lignes_cle[0]["id_parcelle"].strip() for lignes_cle in locaux.values()} - {""})
    return "retenues", ({
        "id_mutation": premiere["id_mutation"], "date": date_mutation.isoformat(), "valeur_fonciere": valeur,
        "nb_logements": nb_logements, "nb_locaux_activite": sum(types.values()) - nb_logements,
        "surface_bati_m2": round(surface, 2), "surface_habitation_m2": round(habitation, 2),
        "surface_activite_m2": round(activite, 2),
        "eur_m2_bati": round(eur_m2, 2), "eur_par_logement": round(eur_logement, 2),
        "distance_m": round(haversine_m(lat, lon, *point)), "adresse": " ".join(m for m in morceaux if m),
        "parcelles": parcelles, "types_locaux": dict(sorted(types.items())),
        "atypique": _motifs_atypie(nb_logements, habitation, activite),
        "dans_reference": False,  # fixé par `_reference`, une fois toutes les ventes connues
    }, eur_m2, eur_logement)


def _motifs_atypie(nb_logements: int, habitation: float, activite: float) -> list[str]:
    """Motifs pour lesquels une vente d'immeuble ne peut pas servir de référence ; liste vide si elle est ordinaire.
    `bloc` : résidence vendue en bloc (`NB_LOGEMENTS_BLOC` logements ou plus). `activite_dominante` : site industriel
    ou commerce dominant (surface d'activité STRICTEMENT supérieure à la surface d'habitation, comparées comme elles
    sont publiées, arrondies à 2 décimales : 33,3 + 44,4 et 77,7 sont égales)."""
    motifs = []
    if nb_logements >= NB_LOGEMENTS_BLOC:
        motifs.append("bloc")
    if round(activite, 2) > round(habitation, 2):
        motifs.append("activite_dominante")
    return motifs


def _cle_mutation(id_mutation: str) -> tuple[int, int, str]:
    """Clé d'ordre d'un identifiant de mutation : « 2025-10 » vient après « 2025-9 » (ordre numérique, non alphabétique).
    Un identifiant qui n'a pas la forme « année-rang » se classe avant tous les autres, par son texte."""
    annee, _, rang = id_mutation.partition("-")
    if annee.isdecimal() and rang.isdecimal():
        return int(annee), int(rang), id_mutation
    return -1, -1, id_mutation


def _groupes_par_parcelle(ventes: list[tuple[dict, float, float]]) -> list[list[tuple[dict, float, float]]]:
    """Regroupe les ventes qui partagent une parcelle, de proche en proche : A et B partagent une parcelle, B et C une
    autre, A et C aucune -> un seul groupe {A, B, C}. Une vente sans parcelle est son propre groupe."""
    racine = list(range(len(ventes)))

    def trouver(i: int) -> int:
        while racine[i] != i:
            racine[i] = racine[racine[i]]
            i = racine[i]
        return i

    vue: dict[str, int] = {}
    for i, (vente, _, _) in enumerate(ventes):
        for parcelle in vente["parcelles"]:
            if parcelle in vue:
                racine[trouver(i)] = trouver(vue[parcelle])
            else:
                vue[parcelle] = i
    groupes: dict[int, list[tuple[dict, float, float]]] = {}
    for i, vente in enumerate(ventes):
        groupes.setdefault(trouver(i), []).append(vente)
    return list(groupes.values())


def _reference(retenues: list[tuple[dict, float, float]]) -> dict:
    """Médiane de RÉFÉRENCE des ventes d'immeubles, seule citable (convention du moteur) : ventes à
    `NB_LOGEMENTS_REFERENCE_MIN` logements ou plus, sans vente atypique, une seule vente par groupe de parcelles
    (la plus récente : `date`, puis `id_mutation` le plus grand). Les exclusions s'appliquent dans CET ordre ; chaque
    vente retenue est dans la référence ou comptée dans UN seul motif d'exclusion (`n` + `ecartees` = ventes
    retenues). Pose `dans_reference` sur chaque vente."""
    ecartees = {"moins_de_3_logements": 0, "atypique": 0, "revente_meme_parcelle": 0}
    candidates: list[tuple[dict, float, float]] = []
    for vente, eur_m2, eur_logement in retenues:
        vente["dans_reference"] = False
        if vente["nb_logements"] < NB_LOGEMENTS_REFERENCE_MIN:
            ecartees["moins_de_3_logements"] += 1
        elif vente["atypique"]:
            ecartees["atypique"] += 1
        else:
            candidates.append((vente, eur_m2, eur_logement))

    gardees: list[tuple[dict, float, float]] = []
    for groupe in _groupes_par_parcelle(candidates):
        gardee = max(groupe, key=lambda t: (t[0]["date"], _cle_mutation(t[0]["id_mutation"])))
        gardee[0]["dans_reference"] = True
        gardees.append(gardee)
        ecartees["revente_meme_parcelle"] += len(groupe) - 1

    n = len(gardees)
    reference: dict = {
        "criteres": {
            "nb_logements_min": NB_LOGEMENTS_REFERENCE_MIN, "sans_atypique": True,
            "une_vente_par_parcelle": "la plus récente",
            "atypique_si": {
                "bloc": f"{NB_LOGEMENTS_BLOC} logements ou plus (résidence vendue en bloc)",
                "activite_dominante": "surface d'activité supérieure à la surface d'habitation",
            },
        },
        "n": n, "n_min": N_MIN_MEDIANE_IMMEUBLES, "mediane_eur_m2_bati": None, "mediane_eur_par_logement": None,
        "raison_mediane_absente": None, "ecartees": ecartees,
    }
    if n >= N_MIN_MEDIANE_IMMEUBLES:
        reference["mediane_eur_m2_bati"] = round(statistics.median(m2 for _, m2, _ in gardees), 2)
        reference["mediane_eur_par_logement"] = round(statistics.median(lg for _, _, lg in gardees), 2)
    else:
        reference["raison_mediane_absente"] = (
            f"n = {n} < {N_MIN_MEDIANE_IMMEUBLES} ventes de référence : médianes non calculées")
    return reference


def _bloc_immeubles(mutations: dict[str, list[dict[str, str]]], geo: dict, aujourdhui: date, fenetre_mois: int,
                    absentes: list[int]) -> dict:
    """Ventes d'immeubles de la commune du bien sur `fenetre_mois` : liste des `NB_IMMEUBLES` plus proches
    (distance croissante, `id_mutation` à égalité), statistiques brutes et médiane de référence (`_reference`) sur
    TOUTES les ventes retenues."""
    debut = date_debut_fenetre(aujourdhui, fenetre_mois)
    annees = annees_couvrantes(aujourdhui, fenetre_mois)
    compteurs = {"multi_locaux_vues": 0, "retenues": 0, "ecartees": dict.fromkeys(MOTIFS_IMMEUBLES, 0)}
    retenues: list[tuple[dict, float, float]] = []
    for lignes in mutations.values():
        compteur, vente = _evaluer_immeuble(lignes, _date_mutation(lignes[0]), debut, geo["lat"], geo["lon"])
        if compteur == "hors_perimetre":
            continue
        compteurs["multi_locaux_vues"] += 1
        if vente is None:
            compteurs["ecartees"][compteur] += 1
        else:
            compteurs["retenues"] += 1
            retenues.append(vente)

    n = len(retenues)
    statistiques: dict = {"n": n, "n_min": N_MIN_MEDIANE_IMMEUBLES, "mediane_eur_m2_bati": None,
                          "mediane_eur_par_logement": None, "raison_mediane_absente": None}
    if n >= N_MIN_MEDIANE_IMMEUBLES:
        statistiques["mediane_eur_m2_bati"] = round(statistics.median(m2 for _, m2, _ in retenues), 2)
        statistiques["mediane_eur_par_logement"] = round(statistics.median(lg for _, _, lg in retenues), 2)
    else:
        statistiques["raison_mediane_absente"] = (
            f"n = {n} < {N_MIN_MEDIANE_IMMEUBLES} ventes : médianes non calculées")
    reference = _reference(retenues)  # sur TOUTES les retenues, avant la troncature à `NB_IMMEUBLES`
    # Deux tris stables : id_mutation, puis distance croissante (indépendant de l'ordre du CSV).
    retenues.sort(key=lambda t: t[0]["id_mutation"])
    retenues.sort(key=lambda t: t[0]["distance_m"])
    return {
        "parametres": {
            "fenetre_mois": fenetre_mois, "date_debut_fenetre": debut.isoformat(), "annees": annees,
            "annees_absentes": [a for a in absentes if a in annees], "perimetre": f"commune {geo['citycode']}",
            "natures": list(NATURES_RETENUES), "plafond_ventes": NB_IMMEUBLES,
        },
        "statistiques": statistiques,
        "reference": reference,
        "ventes": [vente for vente, _, _ in retenues[:NB_IMMEUBLES]],
        "compteurs": compteurs,
    }


def _mois_entre(debut: date, fin: date) -> int:
    """Mois civils ENTIERS de `debut` à `fin` (2024-10-03 -> 2026-04-02 : 17) ; 0 si `fin` précède `debut`."""
    mois = (fin.year - debut.year) * 12 + fin.month - debut.month - (fin.day < debut.day)
    return max(mois, 0)


def _alerte_fraicheur(debut: date, derniere: date | None, absentes: list[int], fenetre_mois: int) -> dict | None:
    """Alerte si la fenêtre EFFECTIVE (du début de fenêtre à la dernière mutation lue) tient en moins de
    `FENETRE_EFFECTIVE_MIN_MOIS` mois : les ventes récentes ne sont pas (encore) dans les fichiers. Le seuil, la
    fenêtre demandée et les années absentes sont dits dans le message : une fenêtre demandée de 18 mois ou moins
    ne peut jamais atteindre le seuil, l'alerte part alors toujours, et le message le laisse voir."""
    liste = ", ".join(str(a) for a in absentes) or "aucune"
    if derniere is None:
        message = (f"aucune mutation lue : fenêtre effective non disponible sur {fenetre_mois} demandés, sous le "
                   f"minimum de {FENETRE_EFFECTIVE_MIN_MOIS} mois ; années absentes : {liste}")
    else:
        mois = _mois_entre(debut, derniere)
        if mois >= FENETRE_EFFECTIVE_MIN_MOIS:
            return None
        message = (f"fenêtre effective de {mois} mois sur {fenetre_mois} demandés (du {debut.isoformat()} à la "
                   f"dernière mutation {derniere.isoformat()}), sous le minimum de {FENETRE_EFFECTIVE_MIN_MOIS} "
                   f"mois ; années absentes : {liste}")
    return {"bloc": "dvf", "message": message}


def collecter(client: httpx.Client, geo: dict, *, rayon_m: float = 500, fenetre_mois: int = 24,
              aujourdhui: date | None = None, sleep: Callable[[float], object] = time.sleep,
              fenetre_immeubles_mois: int | None = None) -> Resultat:
    """`fenetre_immeubles_mois` (None ou 0 : désactivé) ajoute `bloc["immeubles"]` : ses années propres sont lues
    EN PLUS de celles des comparables, qui restent seuls à alimenter compteurs, paramètres et comparables. Une année
    plus ancienne que la fenêtre des comparables qui échoue isole le bloc (`immeubles` None, erreur `dvf.immeubles`)
    sans perdre les comparables ; une année des comparables qui échoue lève, comme toujours."""
    if aujourdhui is None:
        aujourdhui = date.today()
    debut = date_debut_fenetre(aujourdhui, fenetre_mois)
    annees = annees_couvrantes(aujourdhui, fenetre_mois)
    annees_immeubles = annees_couvrantes(aujourdhui, fenetre_immeubles_mois) if fenetre_immeubles_mois else []
    insee = geo["citycode"]

    mutations: dict[str, list[dict[str, str]]] = {}
    mutations_immeubles: dict[str, list[dict[str, str]]] = {}
    lignes_lues = 0
    absentes_toutes: list[int] = []
    echec_immeubles: OpendataError | None = None
    lues_comparables = 0
    sources: list[dict] = []
    for annee in sorted(set(annees) | set(annees_immeubles)):
        url = URL.format(annee=annee, dep=departement(insee), insee=insee)
        try:
            lignes = _lire_csv(get_text(client, url, sleep=sleep), url)
        except NotFound:  # toute autre OpendataError remonte : pas de couverture partielle silencieuse
            absentes_toutes.append(annee)
            continue
        except OpendataError as exc:
            if annee in annees:
                raise
            echec_immeubles = echec_immeubles or exc
            continue
        sources.append({"bloc": "dvf", "url": url, "licence": LICENCE, "millesime": str(annee)})
        for ligne in lignes:
            if fenetre_immeubles_mois:
                mutations_immeubles.setdefault(ligne["id_mutation"], []).append(ligne)
            if annee in annees:
                mutations.setdefault(ligne["id_mutation"], []).append(ligne)
        if annee in annees:
            lues_comparables += 1
            lignes_lues += len(lignes)
    absentes = [a for a in absentes_toutes if a in annees]
    if not lues_comparables:
        raise OpendataError(f"DVF : aucun fichier disponible pour la commune {insee} (années {annees}, 404)")

    compteurs = dict.fromkeys(COMPTEURS, 0)
    compteurs["lignes_lues"] = lignes_lues
    compteurs["mutations"] = len(mutations)
    compteurs["annees_absentes"] = len(absentes)
    retenues: list[dict] = []
    derniere: date | None = None
    for lignes in mutations.values():
        date_mutation = _date_mutation(lignes[0])
        derniere = date_mutation if derniere is None else max(derniere, date_mutation)
        compteur, comparable = _evaluer(lignes, date_mutation, debut, geo["lat"], geo["lon"], rayon_m)
        compteurs[compteur] += 1
        if comparable is not None:
            retenues.append(comparable)

    prix_par_type = {t: [c["prix_m2"] for c in retenues if c["type"] == t] for t in TYPES_HABITATION}
    par_type = {t: _stats(prix) for t, prix in prix_par_type.items()}
    barrieres = {t: _barrieres_tukey(prix) for t, prix in prix_par_type.items()}
    # Compte sur TOUS les retenus du type, avant la troncature à 15 ; `None` sans barrières (n < N_MIN_ATYPIE).
    atypiques = {
        t: None if barrieres[t] is None else sum(1 for p in prix if _atypie(p, barrieres[t], t, len(prix))["atypique"])
        for t, prix in prix_par_type.items()
    }
    # Deux tris stables : date décroissante, puis id_mutation croissant à date égale (indépendant du CSV).
    retenues.sort(key=lambda c: c["id_mutation"])
    retenues.sort(key=lambda c: c["date"], reverse=True)
    # Barrières sur TOUS les retenus du type (population de `par_type`), pas sur les 15 affichés : un atypique hors
    # affichage pèse sur les quartiles et compte dans `atypiques`, sans figurer dans `comparables`.
    comparables = [
        {**c, "prix_m2": round(c["prix_m2"], 2),
         **_atypie(c["prix_m2"], barrieres[c["type"]], c["type"], par_type[c["type"]]["n"])}
        for c in retenues[:NB_COMPARABLES]
    ]

    bloc = {
        "parametres": {
            "rayon_m": rayon_m, "fenetre_mois": fenetre_mois, "date_debut_fenetre": debut.isoformat(),
            "annees": annees, "annees_absentes": absentes,
            "derniere_mutation": derniere.isoformat() if derniere else None,
            "atypie": {"regle": f"Tukey, {_COEF_FR} × EIQ, par type", "coefficient": COEFFICIENT_TUKEY,
                       "n_min": N_MIN_ATYPIE, "methode_quartiles": "inclusive"},
        },
        "par_type": par_type,
        "atypiques": atypiques,
        "comparables": comparables,
        "compteurs": compteurs,
    }
    erreurs: list[dict] = []
    if fenetre_immeubles_mois:
        bloc["immeubles"] = None
        try:
            if echec_immeubles is not None:
                raise echec_immeubles
            bloc["immeubles"] = _bloc_immeubles(mutations_immeubles, geo, aujourdhui, fenetre_immeubles_mois,
                                                absentes_toutes)
        except OpendataError as exc:  # le bloc échoue seul : les comparables restent servis
            erreurs.append({"bloc": "dvf.immeubles", "message": str(exc)})
    alerte = _alerte_fraicheur(debut, derniere, absentes, fenetre_mois)
    return Resultat(bloc, erreurs, sources, [alerte] if alerte else [])
