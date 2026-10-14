"""CLI : python3 engine/scripts/immo_moteur.py --bien <chemin.json> [--foyer [<foyer.json>]]
(équivalent à `python -m src.immo` lancé depuis engine/).

Imprime sur stdout un JSON (indent 2, ensure_ascii=False) ; code de sortie 0, ou 2 si l'entrée est
invalide (message sur stderr). L'arrondi est réservé à cette sortie : 2 décimales pour les montants,
6 pour les ratios (TRI compris), listes comprises. `bien` et `params_utilises` sont des entrées : ils ne sont pas
arrondis. `--foyer` lit le foyer de l'investisseur (`foyer.py`) : seul, dans `immo-data/foyer.json` (ou `$IMMO_DATA_DIR/foyer.json`) ;
suivi d'un chemin, dans ce fichier. Sans `--foyer`, rien n'est lu hors du bien et des paramètres
(`params.json`, surchargé par `immo-data/params_local.json` s'il existe).
Avec un bloc `sortie`, une ligne de résumé (TRI et VAN des trois scénarios) s'écrit sur stderr ; stdout reste du JSON.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import analyser
from .modele import SCENARIOS, charger_bien
from .sortie import _pct

RATIOS = {"taux_dmto_global", "taux_nominal", "taux_assurance_annuel", "vacance", "rendement_brut",
          "rendement_net", "cash_on_cash", "ratio_couverture", "taux_effort", "taux_effort_max",
          "ponderation_loyers", "tmi", "rendement_net_net", "taux_amortissement", "coefficient_surface",
          "loyer_plafond_m2", "tri"}
SECTIONS_NON_ARRONDIES = {"bien", "params_utilises"}


def arrondir(noeud, cle: str = ""):
    if isinstance(noeud, dict):
        return {k: arrondir(v, k) for k, v in noeud.items()}
    if isinstance(noeud, list):  # lignes d'années, flux des associés
        return [arrondir(v, cle) for v in noeud]
    if isinstance(noeud, float):
        return round(noeud, 6 if cle in RATIOS else 2) + 0.0  # + 0.0 : pas de -0.0 en sortie
    return noeud


LIBELLES = {"pessimiste": "pessimiste", "realiste": "réaliste", "optimiste": "optimiste"}


def _tri(taux: float | None) -> str:
    return "indéfini" if taux is None else format(taux * 100, ".2f").replace(".", ",") + " %"


def _euros(montant: float) -> str:
    return format(round(montant), ",d").replace(",", " ") + " €"


def resume_sortie(contrat: dict) -> str:
    """« Sortie à N ans (SCI à l'IS) : TRI pessimiste … %, réaliste … %, optimiste … % ; VAN … »."""
    entree, s = contrat["bien"]["sortie"], contrat["sortie"]
    tri = ", ".join(f"{LIBELLES[nom]} {_tri(s[nom]['tri'])}" for nom in SCENARIOS)
    if entree["taux_actualisation"] is None:
        van = "VAN non calculée (sortie.taux_actualisation null)"
    else:
        van = (f"VAN à {_pct(entree['taux_actualisation'])} : "
               + ", ".join(f"{LIBELLES[nom]} {_euros(s[nom]['van'])}" for nom in SCENARIOS))
    n = entree["horizon_ans"]
    return f"Sortie à {n} {'an' if n == 1 else 'ans'} (SCI à l'IS) : TRI {tri} ; {van}"


def blocs_foyer_ecrits(bien: dict) -> list[str]:
    """Blocs du foyer écrits à la main dans le JSON du bien : `foyer` (pondération comprise) et `fiscal.tmi`."""
    blocs = ["foyer"] if "foyer" in bien else []
    if "tmi" in (bien.get("fiscal") or {}):
        blocs.append("fiscal.tmi")
    return blocs


def avertir_blocs_foyer(bien: dict, avec_foyer_json: bool) -> dict:
    """Avertit sur stderr quand le bien porte un foyer écrit à la main ; avec --foyer, ces blocs sont retirés.

    Le foyer vient de foyer.json (--foyer), jamais du JSON du bien. Sans --foyer, les blocs restent utilisés (calcul
    d'essai) mais l'avertissement dit qu'ils ne valent pas foyer de l'investisseur. Le code de sortie ne change pas.
    """
    blocs = blocs_foyer_ecrits(bien)
    if not blocs:
        return bien
    noms = " et ".join(blocs)
    if avec_foyer_json:
        print(f"avertissement : {noms} écrit(s) dans le JSON du bien, ignoré(s) : le foyer vient de foyer.json "
              "(--foyer) ; retirer ce(s) bloc(s) de l'entrée", file=sys.stderr)
        epure = {k: v for k, v in bien.items() if k != "foyer"}
        if "fiscal" in epure:
            epure["fiscal"] = {k: v for k, v in epure["fiscal"].items() if k != "tmi"}
        return epure
    print(f"avertissement : {noms} écrit(s) à la main dans le JSON du bien : calcul d'essai seulement ; le foyer de "
          "l'investisseur se lit dans foyer.json (--foyer) et ne s'écrit pas dans le bien", file=sys.stderr)
    return bien


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="immo_moteur.py",
                                     description="Analyse de rentabilité locative avant impôt d'un bien (JSON).")
    parser.add_argument("--bien", required=True, help="chemin du JSON du bien")
    parser.add_argument("--foyer", nargs="?", const="", default=None, metavar="CHEMIN",
                        help="lit le foyer (TMI, revenus, loyers, prêts, foncier existant) dans foyer.json ; "
                             "sans chemin : immo-data/foyer.json ou $IMMO_DATA_DIR/foyer.json")
    args = parser.parse_args(argv)

    try:
        bien = charger_bien(args.bien)
        contexte = None
        if args.foyer is not None:
            from .foyer import charger
            contexte = charger(args.foyer or None)
        bien = avertir_blocs_foyer(bien, contexte is not None)
        sortie = analyser(bien, contexte_foyer=contexte)
        rendu = {cle: val if cle in SECTIONS_NON_ARRONDIES else arrondir(val, cle) for cle, val in sortie.items()}
        texte = json.dumps(rendu, indent=2, ensure_ascii=False, allow_nan=False)  # jamais Infinity ni NaN
    except (ValueError, OSError, ImportError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    except ArithmeticError as exc:  # débordement ou division par zéro sur une entrée extrême
        print(f"erreur : calcul impossible ({type(exc).__name__} : {exc})", file=sys.stderr)
        return 2

    for nom, prix in sortie["prix_equilibre"].items():
        if prix is None:
            print(f"note : prix d'équilibre introuvable dans [1 ; 2 × prix] pour le scénario {nom}",
                  file=sys.stderr)
    if "sortie" in sortie:
        print(resume_sortie(sortie), file=sys.stderr)
    print(texte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
