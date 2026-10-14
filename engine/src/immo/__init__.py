"""Moteur de rentabilité locative : acquisition, financement, exploitation, indicateurs, fiscalité, sortie.

Point d'entrée : `analyser(bien, params, contexte_foyer)` assemble le contrat de sortie, que la CLI
(`python -m src.immo --bien <chemin.json> [--foyer [<foyer.json>]]`) arrondit et imprime. Stdlib uniquement,
Python >= 3.11. Sans `contexte_foyer`, rien n'est lu hors du bien et des paramètres.
"""
from __future__ import annotations

import copy

from .acquisition import cout_total, dmto_detail, frais_acquisition
from .exploitation import charges, loyer_annuel_theorique, loyers_encaisses
from .fiscal_nom_propre import fiscalite, params_fiscaux_utilises
from .financement import (DIFFERE_AUCUN, apport, assurance_mensuelle, crd_apres, echeancier_bien, emprunt,
                          mensualite_amortissement)
from .indicateurs import (cash_flow_mensuel_avant_impot, cash_on_cash, conformite_hcsf, enrichissement_an1,
                          prix_equilibre, ratio_couverture, rendement_brut, rendement_net)
from .modele import SCENARIOS, charger_params, parametre, valeur, valider_bien
from .sortie import sortir

PARAMS_SORTIE = ["fiscal.liquidation.droit_partage", "fiscal.liquidation.droit_partage_sur_masse"]


def analyser(bien: dict, params: dict | None = None, contexte_foyer: dict | None = None) -> dict:
    """Contrat de sortie : bien, params_utilises, acquisition, financement, scenarios, prix_equilibre, hcsf,
    fiscalite ; plus `sortie` (revente, liquidation, flux des associés, TRI et VAN par scénario, `sortie.sortir`)
    seulement si le bien porte un bloc `sortie`.

    Valide le bien, ne le modifie pas, et ne fait aucun arrondi. `contexte_foyer` (forme de
    `foyer.charger()`, lu dans foyer.json) remplace le bloc `foyer` du taux d'effort (pondération comprise) et apporte
    TMI, année et foncier existant ; les blocs `foyer` et `fiscal.tmi` du bien sont alors ignorés.
    """
    params = charger_params() if params is None else params
    valider_bien(bien)
    prix, dep, f = bien["prix_net_vendeur"], bien["departement"], bien["financement"]

    detail = dmto_detail(prix, dep, params)
    acquisition = {
        "prix_net_vendeur": prix,
        "departement": dep,
        "dmto": detail["total"],
        "dmto_detail": {cle: detail[cle] for cle in ("droit_departemental", "taxe_communale", "frais_assiette")},
        "taux_dmto_global": detail["total"] / prix,
        "autres_frais_acquisition": bien["autres_frais_acquisition"],
        "frais_acquisition": frais_acquisition(bien, params),
        "travaux": bien["travaux"],
        "mobilier": bien["mobilier"],
        "frais_agence_acquereur": bien["frais_agence_acquereur"],
        "cout_total": cout_total(bien, params),
    }

    echeances = echeancier_bien(bien)
    mensualite = mensualite_amortissement(bien)
    assurance = assurance_mensuelle(bien)
    financement = {
        "emprunt_mode": f["emprunt_mode"],
        "emprunt": emprunt(bien),
        "apport": apport(bien, params),
        "taux_nominal": f["taux_nominal"],
        "duree_mois": f["duree_mois"],
        "taux_assurance_annuel": f["taux_assurance_annuel"],
        "differe": dict(f.get("differe", DIFFERE_AUCUN)),
        "mensualite_hors_assurance": mensualite,
        "assurance_mensuelle": assurance,
        "mensualite_totale": mensualite + assurance,
        "crd_12_mois": crd_apres(echeances, 12),
        "nb_echeances": len(echeances),
    }

    scenarios = {}
    for nom in SCENARIOS:
        s = bien["scenarios"][nom]
        scenarios[nom] = {
            "exploitation": {
                "loyer_mensuel_hc": s["loyer_mensuel_hc"],
                "vacance": s["vacance"],
                "loyer_annuel_theorique": loyer_annuel_theorique(s),
                "loyers_encaisses": loyers_encaisses(s),
                "charges": charges(bien, s),
            },
            "indicateurs": {
                "rendement_brut": rendement_brut(bien, s, params),
                "rendement_net": rendement_net(bien, s, params),
                "cash_flow_mensuel_avant_impot": cash_flow_mensuel_avant_impot(bien, s),
                "cash_on_cash": cash_on_cash(bien, s, params),
                "ratio_couverture": ratio_couverture(bien, s),
                "enrichissement_an1": enrichissement_an1(bien),
            },
        }

    utilises = [f"dmto.departements.{dep}.taux_departemental", "dmto.taux_communal", "dmto.frais_assiette"]
    ponderation_fournie = "ponderation_loyers" in bien.get("foyer", {})
    bien_hcsf, entrees_foyer = bien, None
    if contexte_foyer is not None:
        from .foyer import bloc_hcsf  # pur : ne lit rien, le contexte est déjà construit
        # Avec foyer.json, le bloc `foyer` éventuel du bien est ignoré : une seule pondération, celle de foyer.json,
        # sinon le défaut de params.json, pour les loyers existants ET pour le loyer du bien étudié.
        ponderation_fournie = "ponderation_loyers" in contexte_foyer
        ponderation = (contexte_foyer["ponderation_loyers"] if ponderation_fournie
                       else valeur(params, "hcsf.ponderation_loyers_defaut"))
        bloc = bloc_hcsf(contexte_foyer, ponderation)
        entrees_foyer = {**bloc, "source": "foyer.json"}
        bien_hcsf = {**bien, "foyer": bloc}
    if "foyer" in bien_hcsf:
        reference = conformite_hcsf(bien_hcsf, "realiste", params)
        hcsf = {
            "calcule": True,
            "scenario_de_reference": "realiste",
            **reference,
            "par_scenario": {nom: {"taux_effort": c["taux_effort"], "conforme": c["conforme"]}
                             for nom, c in ((n, conformite_hcsf(bien_hcsf, n, params)) for n in SCENARIOS)},
        }
        if entrees_foyer:
            hcsf["entrees_foyer"] = entrees_foyer
        utilises += ["hcsf.taux_effort_max", "hcsf.duree_max_mois", "hcsf.duree_max_differe_mois",
                     "hcsf.part_travaux_min_differe"]
        if not ponderation_fournie:
            utilises.append("hcsf.ponderation_loyers_defaut")
    else:
        hcsf = {"calcule": False,
                "raison": "bloc foyer absent de l'entrée : revenus_nets_mensuels et mensualites_existantes "
                          "sont requis pour le taux d'effort HCSF"}

    fiscal = fiscalite(bien, params, contexte_foyer)
    utilises += params_fiscaux_utilises(bien, fiscal["annee_revenus"], params)
    if "sortie" in bien:
        utilises += PARAMS_SORTIE

    contrat = {
        "bien": copy.deepcopy(bien),
        "params_utilises": {chemin: dict(parametre(params, chemin)) for chemin in utilises},
        "acquisition": acquisition,
        "financement": financement,
        "scenarios": scenarios,
        "prix_equilibre": {nom: prix_equilibre(bien, nom) for nom in SCENARIOS},
        "hcsf": hcsf,
        "fiscalite": fiscal,
    }
    if "sortie" in bien:
        contrat["sortie"] = {nom: sortir(bien, nom, params, contexte_foyer) for nom in SCENARIOS}
    return contrat
