"""Indicateurs de rentabilité avant impôt : rendements, cash-flow, couverture, TRI, VAN, HCSF.

Fonctions pures, sans arrondi interne (l'arrondi est réservé à la sortie CLI). `scenario` se donne par
son nom ("realiste") ou par son dict. Les ratios dont le dénominateur est nul retournent None : une
absence se rend comme une absence.
"""
from __future__ import annotations

import math

from .acquisition import cout_total
from .exploitation import charges, loyer_annuel_theorique, loyers_encaisses, resoudre_scenario
from .financement import (apport, assurance_mensuelle, crd_apres, echeancier_bien, emprunt,
                          mensualite_amortissement)
from .modele import charger_params, valeur


def rendement_brut(bien: dict, scenario: str | dict, params: dict | None = None) -> float:
    s = resoudre_scenario(bien, scenario)
    return loyer_annuel_theorique(s) / cout_total(bien, params)


def rendement_net(bien: dict, scenario: str | dict, params: dict | None = None) -> float:
    """Avant impôt : (loyers encaissés - charges) / coût total."""
    s = resoudre_scenario(bien, scenario)
    return (loyers_encaisses(s) - charges(bien, s)) / cout_total(bien, params)


def cash_flow_mensuel_avant_impot(bien: dict, scenario: str | dict) -> float:
    """En année pleine d'amortissement : mensualité de la phase d'amortissement, assurance comprise."""
    s = resoudre_scenario(bien, scenario)
    service_dette = 12 * (mensualite_amortissement(bien) + assurance_mensuelle(bien))
    return (loyers_encaisses(s) - charges(bien, s) - service_dette) / 12


def cash_on_cash(bien: dict, scenario: str | dict, params: dict | None = None) -> float | None:
    """12 × cash-flow mensuel avant impôt / apport ; None sans apport (pas de division par zéro)."""
    mise = apport(bien, params)
    if mise <= 0:
        return None
    return 12 * cash_flow_mensuel_avant_impot(bien, scenario) / mise


def ratio_couverture(bien: dict, scenario: str | dict) -> float | None:
    """Loyer mensuel HC / (mensualité + assurance + charges mensuelles) ; None si dénominateur nul."""
    s = resoudre_scenario(bien, scenario)
    sorties = mensualite_amortissement(bien) + assurance_mensuelle(bien) + charges(bien, s) / 12
    if sorties <= 0:
        return None
    return s["loyer_mensuel_hc"] / sorties


def enrichissement_an1(bien: dict) -> float:
    """Capital amorti en 12 mensualités (emprunt - CRD). Distinct du cash-flow : ne jamais les additionner."""
    return emprunt(bien) - crd_apres(echeancier_bien(bien), 12)


def van(taux: float, flux: list[float]) -> float:
    """Σ flux_i / (1 + taux)^i, i partant de 0."""
    return sum(f / (1 + taux) ** i for i, f in enumerate(flux))


def _van_ponderee(taux: float, flux: list[float]) -> float:
    """van × (1 + taux)^(n-1), par Horner : même signe que `van` pour taux > -1, sans division.

    `van` divise par (1 + taux)^i, qui sous-déborde à 0 près de -0,99 dès 162 flux : le TRI de flux
    mensuels sur 25 ans ne passerait pas.
    """
    cumul = 0.0
    for f in flux:
        cumul = cumul * (1 + taux) + f
    return cumul


def tri(flux: list[float]) -> float:
    """TRI par bissection sur van = 0, r dans ]-0,99 ; 1,0] (300 itérations ou largeur < 1e-12)."""
    if not all(math.isfinite(f) for f in flux):
        raise ValueError("TRI indéfini : les flux doivent être des nombres finis")
    if not (any(f > 0 for f in flux) and any(f < 0 for f in flux)):
        raise ValueError("TRI indéfini : les flux n'ont pas de changement de signe")
    bas, haut = -0.99, 1.0
    v_bas, v_haut = _van_ponderee(bas, flux), _van_ponderee(haut, flux)
    if v_bas * v_haut > 0:
        raise ValueError("TRI hors de ]-0,99 ; 1,0] : pas de racine dans l'intervalle de recherche")
    for _ in range(300):
        milieu = (bas + haut) / 2
        v = _van_ponderee(milieu, flux)
        if v == 0 or haut - bas < 1e-12:
            return milieu
        if (v > 0) == (v_bas > 0):
            bas, v_bas = milieu, v
        else:
            haut = milieu
    return (bas + haut) / 2


def prix_equilibre(bien: dict, scenario: str | dict) -> float | None:
    """Prix net vendeur, dans [1 ; 2 × prix], qui annule le cash-flow mensuel avant impôt.

    Seuls le prix et, en mode "prix_plus_travaux", l'emprunt qui le suit varient : loyers, charges et
    `autres_frais_acquisition` restent ceux du bien. Les DMTO suivent le prix mais n'entrent pas dans
    le cash-flow (ils sont payés sur l'apport) : ce prix n'en dépend pas. None si le cash-flow ne
    change pas de signe sur l'intervalle (par exemple en mode "fixe", où il ne dépend pas du prix).
    """
    s = resoudre_scenario(bien, scenario)

    def cash_flow(prix: float) -> float:
        return cash_flow_mensuel_avant_impot({**bien, "prix_net_vendeur": prix}, s)

    bas, haut = 1.0, 2 * bien["prix_net_vendeur"]
    if cash_flow(bas) < 0 or cash_flow(haut) > 0:
        return None
    for _ in range(300):
        milieu = (bas + haut) / 2
        if haut - bas < 1e-9:
            break
        if cash_flow(milieu) > 0:
            bas = milieu
        else:
            haut = milieu
    return (bas + haut) / 2


def _foyer(bien: dict) -> dict:
    if "foyer" not in bien:
        raise ValueError("champ requis absent : foyer (nécessaire au taux d'effort HCSF)")
    return bien["foyer"]


def ponderation_loyers(bien: dict, params: dict | None = None) -> float:
    """Pondération du foyer si fournie, sinon le défaut de params.json (pratique bancaire, à vérifier)."""
    foyer = _foyer(bien)
    if "ponderation_loyers" in foyer:
        return foyer["ponderation_loyers"]
    params = charger_params() if params is None else params
    return valeur(params, "hcsf.ponderation_loyers_defaut")


def taux_effort_hcsf(bien: dict, scenario: str | dict, params: dict | None = None) -> float:
    """(mensualités existantes + mensualité + assurance) / (revenus nets + pondération × loyer HC)."""
    foyer = _foyer(bien)
    s = resoudre_scenario(bien, scenario)
    charges_dette = foyer["mensualites_existantes"] + mensualite_amortissement(bien) + assurance_mensuelle(bien)
    revenus = foyer["revenus_nets_mensuels"] + ponderation_loyers(bien, params) * s["loyer_mensuel_hc"]
    return charges_dette / revenus


def duree_conforme_hcsf(bien: dict, params: dict | None = None) -> dict:
    """Maturité ≤ 25 ans, ou ≤ 27 ans avec un différé (≥ 1 mois) qui laisse ≤ 25 ans d'amortissement,
    pour une VEFA ou un ancien dont les travaux font au moins 10 % du coût total (D-HCSF-2021-7, art. 1er).
    """
    params = charger_params() if params is None else params
    f = bien["financement"]
    duree, differe = f["duree_mois"], f.get("differe", {"mois": 0})["mois"]
    duree_max = valeur(params, "hcsf.duree_max_mois")
    if duree <= duree_max:
        return {"duree_conforme": True, "exception_differe_27_ans": False, "exception_note": None}
    exception = (duree <= valeur(params, "hcsf.duree_max_differe_mois") and differe >= 1
                 and duree - differe <= duree_max
                 and (bien.get("vefa", False)
                      or bien["travaux"] / cout_total(bien, params) >= valeur(params, "hcsf.part_travaux_min_differe")))
    note = ("exception 27 ans : différé supposé d'une durée analogue au décalage de l'entrée en jouissance, et "
            "travaux d'un objet éligible (création de surfaces, modernisation, assainissement, aménagement, "
            "rénovation énergétique) : non contrôlés") if exception else None
    return {"duree_conforme": exception, "exception_differe_27_ans": exception, "exception_note": note}


def conformite_hcsf(bien: dict, scenario: str | dict, params: dict | None = None) -> dict:
    """Taux d'effort et durée comparés aux plafonds HCSF de params.json (exception 27 ans comprise)."""
    params = charger_params() if params is None else params
    taux = taux_effort_hcsf(bien, scenario, params)
    taux_max = valeur(params, "hcsf.taux_effort_max")
    duree = duree_conforme_hcsf(bien, params)
    return {
        "taux_effort": taux,
        "taux_effort_max": taux_max,
        "duree_mois": bien["financement"]["duree_mois"],
        "duree_max_mois": valeur(params, "hcsf.duree_max_mois"),
        **duree,
        "ponderation_loyers": ponderation_loyers(bien, params),
        "conforme": taux <= taux_max and duree["duree_conforme"],
    }
