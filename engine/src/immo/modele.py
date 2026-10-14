"""Chargement et validation du bien, accès aux paramètres datés et sourcés (`params.json`).

Une absence se rend comme une absence : un champ requis manquant lève
`ValueError("champ requis absent : <chemin.du.champ>")`, jamais un 0 implicite.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

PARAMS_PAR_DEFAUT = Path(__file__).with_name("params.json")

SCENARIOS = ("pessimiste", "realiste", "optimiste")
EMPRUNT_MODES = ("prix_plus_travaux", "fixe")
DIFFERE_TYPES = ("aucun", "partiel", "total")

MONETAIRES_ACQUISITION = ("prix_net_vendeur", "autres_frais_acquisition", "travaux", "mobilier",
                          "frais_agence_acquereur")
MONETAIRES_EXPLOITATION = ("taxe_fonciere", "pno", "copro_non_recuperable", "cfe", "comptable")
TAUX_EXPLOITATION = ("gestion_taux", "gli_taux", "capex_taux")
TRAVAUX_NATURES = ("entretien", "amelioration")
CLASSES_DPE = ("A", "B", "C", "D", "E", "F", "G")
BAILLEUR_PRIVE_REGIMES = ("i", "j")
BAILLEUR_PRIVE_LOCATIONS = ("intermediaire", "social", "tres_social")
SCI_REGIMES = ("is", "ir")
SCI_FRAIS_ACQUISITION = ("incorpores", "charges")
POLITIQUES_DISTRIBUTION = ("annuelle", "liquidation")


# --------------------------------------------------------------------------------------------
# Paramètres
# --------------------------------------------------------------------------------------------

PARAMS_LOCAL = "params_local.json"
CHAMPS_FEUILLE_LOCALE = ("valeur", "source", "verifie_le")
A_RENSEIGNER = "À RENSEIGNER"


def charger_params(chemin: str | Path | None = None, local: str | Path | bool | None = None) -> dict:
    """Lit `params.json` (celui du paquet par défaut), puis lui superpose `params_local.json`.

    Chaque feuille a valeur, source, verifie_le. `local` : None cherche `<dossier de données>/params_local.json`
    (sans erreur s'il n'existe pas) ; un chemin l'impose (il doit exister) ; False n'applique aucune surcharge.
    Règles de fusion : voir `fusionner_params`.
    """
    cible = Path(chemin) if chemin is not None else PARAMS_PAR_DEFAUT
    params = json.loads(cible.read_text(encoding="utf-8"))
    if local is False:
        return params
    if local is None or local is True:
        from .donnees import fichier
        chemin_local = fichier(PARAMS_LOCAL)
        if not chemin_local.is_file():
            return params
    else:
        chemin_local = Path(local)
    try:
        surcharge = json.loads(chemin_local.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{chemin_local} : illisible ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{chemin_local} : JSON invalide ({exc})") from exc
    if not isinstance(surcharge, dict):
        raise ValueError(f"{chemin_local} : objet JSON attendu à la racine")
    return fusionner_params(params, surcharge, origine=chemin_local.name)


def _est_feuille(noeud) -> bool:
    return isinstance(noeud, dict) and "valeur" in noeud


def fusionner_params(base: dict, surcharge: dict, origine: str = PARAMS_LOCAL, _chemin: tuple = ()) -> dict:
    """Fusion récursive de `surcharge` sur `base`, sans modifier ni l'un ni l'autre.

    - une clé commençant par `_` (notice, exemple) est ignorée ;
    - deux objets sans `valeur` se fusionnent clé par clé (un nouveau département s'ajoute à côté du 77) ;
    - une feuille (objet portant `valeur`) remplace la feuille de même chemin EN ENTIER : pour une table comme
      `fiscal.bailleur_prive.zones`, la feuille locale doit lister toutes les communes utiles ;
    - toute feuille locale porte `valeur`, `source` et `verifie_le` (AAAA-MM-JJ), et une valeur encore égale à
      « À RENSEIGNER » est refusée : aucun chiffre n'est deviné.
    La feuille fusionnée reçoit `origine` (nom du fichier local), recopiée dans `params_utilises`.
    """
    sortie = dict(base)
    for cle, val in surcharge.items():
        if cle.startswith("_"):
            continue
        chemin = _chemin + (cle,)
        nom = ".".join(chemin)
        if _est_feuille(val):
            manquants = [c for c in CHAMPS_FEUILLE_LOCALE if c not in val or val[c] in (None, "")]
            if manquants:
                raise ValueError(f"{origine} : la feuille {nom} doit porter {', '.join(CHAMPS_FEUILLE_LOCALE)} "
                                 f"(absent : {', '.join(manquants)})")
            if _contient_a_renseigner(val):
                raise ValueError(f"{origine} : la feuille {nom} contient encore « {A_RENSEIGNER} » : la remplir depuis "
                                 "sa source officielle, ou la retirer")
            try:
                date.fromisoformat(str(val["verifie_le"]))
            except ValueError as exc:
                raise ValueError(f"{origine} : {nom}.verifie_le doit être une date AAAA-MM-JJ "
                                 f"(reçu {val['verifie_le']!r})") from exc
            sortie[cle] = {**val, "origine": origine}
        elif isinstance(val, dict):
            existant = base.get(cle, {})
            if _est_feuille(existant):
                raise ValueError(f"{origine} : {nom} est une feuille dans params.json : la remplacer par un objet "
                                 f"{{{', '.join(CHAMPS_FEUILLE_LOCALE)}}}")
            if not isinstance(existant, dict):
                existant = {}
            sortie[cle] = fusionner_params(existant, val, origine, chemin)
        else:
            raise ValueError(f"{origine} : {nom} doit être un objet (une feuille {{{', '.join(CHAMPS_FEUILLE_LOCALE)}}} "
                             "ou un groupe de feuilles), pas une valeur nue")
    return sortie


def _contient_a_renseigner(noeud) -> bool:
    if isinstance(noeud, str):
        return A_RENSEIGNER.casefold() in noeud.casefold()
    if isinstance(noeud, dict):
        return any(_contient_a_renseigner(v) for v in noeud.values())
    if isinstance(noeud, list):
        return any(_contient_a_renseigner(v) for v in noeud)
    return False


def parametre(params: dict, chemin: str) -> dict:
    """Feuille complète (valeur, source, verifie_le, a_verifier éventuel) du chemin pointé `a.b.c`."""
    noeud = params
    for cle in chemin.split("."):
        if not isinstance(noeud, dict) or cle not in noeud:
            raise ValueError(f"paramètre absent de params.json : {chemin}")
        noeud = noeud[cle]
    if not isinstance(noeud, dict) or "valeur" not in noeud:
        raise ValueError(f"paramètre absent de params.json : {chemin} (feuille sans valeur)")
    return noeud


def valeur(params: dict, chemin: str):
    return parametre(params, chemin)["valeur"]


# --------------------------------------------------------------------------------------------
# Validation du bien
# --------------------------------------------------------------------------------------------

def _lire(brut: dict, chemin: str):
    noeud = brut
    for cle in chemin.split("."):
        if not isinstance(noeud, dict) or cle not in noeud:
            raise ValueError(f"champ requis absent : {chemin}")
        noeud = noeud[cle]
    return noeud


def _apercu(v) -> str:
    """repr borné, pour qu'un entier de 400 chiffres ne noie pas le message d'erreur."""
    texte = repr(v)
    return texte if len(texte) <= 60 else texte[:57] + "..."


def _nombre(brut: dict, chemin: str, *, mini: float | None = None, mini_exclu: bool = False,
            maxi: float | None = None, maxi_exclu: bool = False, entier: bool = False):
    v = _lire(brut, chemin)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (nombre attendu)")
    try:
        fini = math.isfinite(v)
    except OverflowError:  # entier JSON plus grand que le plus grand float
        fini = False
    if not fini:
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (nombre fini attendu)")
    if entier and not isinstance(v, int):
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (entier attendu)")
    if mini is not None and (v <= mini if mini_exclu else v < mini):
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (doit être {'>' if mini_exclu else '>='} {mini})")
    if maxi is not None and (v >= maxi if maxi_exclu else v > maxi):
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (doit être {'<' if maxi_exclu else '<='} {maxi})")
    return v


def valider_differe(differe_type, differe_mois, n_mois) -> None:
    """Règles du différé : type connu, mois entier >= 0, 'aucun' sans mois, mois < durée."""
    if differe_type not in DIFFERE_TYPES:
        raise ValueError(f"différé : type inconnu : {differe_type!r} (attendu : {', '.join(DIFFERE_TYPES)})")
    if isinstance(differe_mois, bool) or not isinstance(differe_mois, int) or differe_mois < 0:
        raise ValueError(f"différé : mois invalide : {differe_mois!r} (entier >= 0 attendu)")
    if differe_type == "aucun" and differe_mois != 0:
        raise ValueError(f"différé : type 'aucun' incompatible avec mois = {differe_mois}")
    if differe_mois >= n_mois:
        raise ValueError(f"différé : mois ({differe_mois}) doit être strictement inférieur à la durée ({n_mois})")


def valider_bien(bien: dict) -> dict:
    """Valide la forme du bien et retourne le même objet. Aucun montant n'est défaulté."""
    if not isinstance(bien, dict):
        raise ValueError("bien : un objet JSON est attendu")

    dep = _lire(bien, "departement")
    if not isinstance(dep, str) or not dep.strip():
        raise ValueError(f"champ invalide : departement = {dep!r} (texte non vide attendu, ex. \"77\")")

    _nombre(bien, "prix_net_vendeur", mini=0, mini_exclu=True)
    for champ in MONETAIRES_ACQUISITION[1:]:
        _nombre(bien, champ, mini=0)

    _lire(bien, "financement")
    mode = _lire(bien, "financement.emprunt_mode")
    if mode not in EMPRUNT_MODES:
        raise ValueError(f"champ invalide : financement.emprunt_mode = {mode!r} "
                         f"(attendu : {', '.join(EMPRUNT_MODES)})")
    if mode == "fixe":
        _nombre(bien, "financement.emprunt", mini=0)
    _nombre(bien, "financement.taux_nominal", mini=0, maxi=1, maxi_exclu=True)
    duree = _nombre(bien, "financement.duree_mois", mini=0, mini_exclu=True, entier=True)
    _nombre(bien, "financement.taux_assurance_annuel", mini=0, maxi=1, maxi_exclu=True)
    if "differe" in bien["financement"]:
        valider_differe(_lire(bien, "financement.differe.type"), _lire(bien, "financement.differe.mois"), duree)

    _lire(bien, "exploitation")
    for champ in MONETAIRES_EXPLOITATION:
        _nombre(bien, f"exploitation.{champ}", mini=0)
    for champ in TAUX_EXPLOITATION:
        _nombre(bien, f"exploitation.{champ}", mini=0, maxi=1, maxi_exclu=True)

    _lire(bien, "scenarios")
    for nom in SCENARIOS:
        _lire(bien, f"scenarios.{nom}")
        _nombre(bien, f"scenarios.{nom}.loyer_mensuel_hc", mini=0)
        _nombre(bien, f"scenarios.{nom}.vacance", mini=0, maxi=1, maxi_exclu=True)

    if "foyer" in bien:
        _nombre(bien, "foyer.revenus_nets_mensuels", mini=0, mini_exclu=True)
        _nombre(bien, "foyer.mensualites_existantes", mini=0)
        if "ponderation_loyers" in bien["foyer"]:
            _nombre(bien, "foyer.ponderation_loyers", mini=0, maxi=1)
    valider_optionnels(bien)
    return bien


def _choix(v, chemin: str, permis) -> None:
    if v not in permis:
        raise ValueError(f"champ invalide : {chemin} = {_apercu(v)} (attendu : {', '.join(permis)})")


def valider_optionnels(bien: dict) -> None:
    """Entrées optionnelles de la fiscalité : contrôlées seulement si présentes."""
    if "surface_habitable" in bien:
        _nombre(bien, "surface_habitable", mini=0, mini_exclu=True)
    if "code_insee" in bien and not (isinstance(bien["code_insee"], str) and bien["code_insee"].strip()):
        raise ValueError(f"champ invalide : code_insee = {_apercu(bien['code_insee'])} (texte attendu : code INSEE à 5 caractères)")
    for champ in ("immeuble_collectif", "vefa"):
        if champ in bien and not isinstance(bien[champ], bool):
            raise ValueError(f"champ invalide : {champ} = {_apercu(bien[champ])} (booléen attendu)")
    if "date_acquisition" in bien:
        try:
            date.fromisoformat(bien["date_acquisition"])
        except (TypeError, ValueError):
            raise ValueError(f"champ invalide : date_acquisition = {_apercu(bien['date_acquisition'])} "
                             "(date ISO AAAA-MM-JJ attendue)") from None
    if "travaux_deductibles_foncier" in bien:
        _nombre(bien, "travaux_deductibles_foncier", mini=0)
    if "travaux_nature" in bien:
        _choix(bien["travaux_nature"], "travaux_nature", TRAVAUX_NATURES)
    if "renovation_energetique" in bien:
        for cle in ("classe_avant", "classe_apres"):
            _choix(_lire(bien, f"renovation_energetique.{cle}"), f"renovation_energetique.{cle}", CLASSES_DPE)
        _nombre(bien, "renovation_energetique.depenses", mini=0)
    if "bailleur_prive" in bien:
        _choix(_lire(bien, "bailleur_prive.regime"), "bailleur_prive.regime", BAILLEUR_PRIVE_REGIMES)
        _choix(_lire(bien, "bailleur_prive.location"), "bailleur_prive.location", BAILLEUR_PRIVE_LOCATIONS)
    if "fiscal" in bien:
        if not isinstance(bien["fiscal"], dict):
            raise ValueError(f"champ invalide : fiscal = {_apercu(bien['fiscal'])} (objet attendu)")
        if "tmi" in bien["fiscal"]:
            _nombre(bien, "fiscal.tmi", mini=0, maxi=1, maxi_exclu=True)
        if "annee_revenus" in bien["fiscal"]:
            _nombre(bien, "fiscal.annee_revenus", mini=2000, maxi=2100, entier=True)
    if "sci" in bien:
        valider_sci(bien)
    if "sortie" in bien:
        valider_sortie(bien)


def valider_sci(bien: dict) -> None:
    """Bloc optionnel `sci` : présent, il est complet ; aucun montant n'est défaulté."""
    if not isinstance(bien["sci"], dict):
        raise ValueError(f"champ invalide : sci = {_apercu(bien['sci'])} (objet attendu)")
    _choix(_lire(bien, "sci.regime"), "sci.regime", SCI_REGIMES)
    _nombre(bien, "sci.quote_part_foyer", mini=0, mini_exclu=True, maxi=1)
    # premier exercice : clos au plus tard le 31/12 de l'année suivant la création (BOI-IS-LIQ-20-10-20230621 §80)
    _nombre(bien, "sci.duree_premier_exercice_mois", mini=1, maxi=24, entier=True)
    _choix(_lire(bien, "sci.frais_acquisition"), "sci.frais_acquisition", SCI_FRAIS_ACQUISITION)
    if not isinstance(_lire(bien, "sci.capital_libere"), bool):
        raise ValueError(f"champ invalide : sci.capital_libere = {_apercu(bien['sci']['capital_libere'])} "
                         "(booléen attendu)")
    _nombre(bien, "sci.cca.montant", mini=0)
    _nombre(bien, "sci.cca.taux", mini=0, maxi=1, maxi_exclu=True)
    _nombre(bien, "sci.distribution_annuelle", mini=0)
    _nombre(bien, "sci.remboursement_cca_annuel", mini=0)


def _taux(bien: dict, chemin: str):
    """Taux annuel dans ]-1 ; 1[."""
    return _nombre(bien, chemin, mini=-1, mini_exclu=True, maxi=1, maxi_exclu=True)


def valider_sortie(bien: dict) -> None:
    """Bloc optionnel `sortie` : présent, il est complet et aucune hypothèse n'est
    défaultée. La sortie n'est modélisée que pour une SCI à l'IS : il exige un bloc `sci` de régime `is`."""
    if not isinstance(bien["sortie"], dict):
        raise ValueError(f"champ invalide : sortie = {_apercu(bien['sortie'])} (objet attendu)")
    if "sci" not in bien:
        raise ValueError("bloc sortie : exige un bloc sci de régime is (sci absent)")
    if bien["sci"]["regime"] != "is":
        raise ValueError(f"bloc sortie : exige un bloc sci de régime is (sci.regime = {bien['sci']['regime']!r})")
    _nombre(bien, "sortie.horizon_ans", mini=1, maxi=40, entier=True)
    for champ in ("revalorisation_annuelle", "indexation_loyers_annuelle"):
        par_scenario = _lire(bien, f"sortie.{champ}")
        if not isinstance(par_scenario, dict):
            raise ValueError(f"champ invalide : sortie.{champ} = {_apercu(par_scenario)} (objet attendu : un taux par "
                             f"scénario, {', '.join(SCENARIOS)})")
        for nom in SCENARIOS:
            _taux(bien, f"sortie.{champ}.{nom}")
    _taux(bien, "sortie.indexation_charges_annuelle")
    _choix(_lire(bien, "sortie.classe_dpe_location"), "sortie.classe_dpe_location", CLASSES_DPE)
    _nombre(bien, "sortie.frais_revente_taux", mini=0, maxi=1, maxi_exclu=True)
    _nombre(bien, "sortie.indemnites_remboursement_anticipe", mini=0)
    _nombre(bien, "sortie.frais_liquidation", mini=0)
    _choix(_lire(bien, "sortie.politique_distribution"), "sortie.politique_distribution", POLITIQUES_DISTRIBUTION)
    if not isinstance(_lire(bien, "sortie.option_bareme"), bool):
        raise ValueError(f"champ invalide : sortie.option_bareme = {_apercu(bien['sortie']['option_bareme'])} "
                         "(booléen attendu)")
    if _lire(bien, "sortie.taux_actualisation") is not None:  # null : pas de VAN
        _taux(bien, "sortie.taux_actualisation")


def _constante_json_refusee(nom: str):
    raise ValueError(f"JSON invalide : la constante non standard {nom} est refusée")


def charger_bien(chemin: str | Path) -> dict:
    """Lit et valide un bien JSON. JSON illisible et champ absent lèvent ValueError."""
    texte = Path(chemin).read_text(encoding="utf-8")
    try:
        brut = json.loads(texte, parse_constant=_constante_json_refusee)  # NaN, Infinity : pas du JSON
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide dans {chemin} : {exc}") from exc
    except RecursionError as exc:
        raise ValueError(f"JSON invalide dans {chemin} : imbrication trop profonde") from exc
    return valider_bien(brut)
