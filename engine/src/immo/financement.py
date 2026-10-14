"""Financement : emprunt, mensualité, assurance, échéancier (différé partiel ou total), apport.

Fonctions pures, sans arrondi interne. Hypothèse de contrat : le bien passé en argument a été validé
(`modele.valider_bien`), sauf pour `echeancier` et `mensualite`, qui contrôlent leurs propres entrées.
"""
from __future__ import annotations

import math

from .acquisition import cout_total
from .modele import valider_differe

DIFFERE_AUCUN = {"type": "aucun", "mois": 0}


def emprunt(bien: dict) -> float:
    f = bien["financement"]
    if f["emprunt_mode"] == "fixe":
        return f["emprunt"]
    return bien["prix_net_vendeur"] + bien["travaux"]  # "prix_plus_travaux"


def _verifier_pret(capital: float, n_mois: int) -> None:
    if n_mois <= 0:
        raise ValueError(f"durée invalide : {n_mois!r} mois (doit être > 0)")
    if capital < 0:
        raise ValueError(f"capital invalide : {capital!r} (doit être >= 0)")


def mensualite(capital: float, taux_nominal: float, n_mois: int) -> float:
    """PMT standard hors assurance ; capital / n si le taux est nul (et 0 pour un capital nul)."""
    _verifier_pret(capital, n_mois)
    t = taux_nominal / 12
    if t == 0:
        return capital / n_mois
    # Même PMT que capital × t / (1 - (1 + t)^-n), écrite avec expm1/log1p : stable pour un taux minuscule
    # (1 + t == 1.0 ferait diviser par zéro).
    return capital * t / -math.expm1(-n_mois * math.log1p(t))


def assurance_mensuelle(bien: dict) -> float:
    """Sur le capital initial, payée aussi pendant un différé."""
    return emprunt(bien) * bien["financement"]["taux_assurance_annuel"] / 12


def _capital_a_amortir(capital: float, taux_nominal: float, differe_type: str, differe_mois: int) -> float:
    """Capital sur lequel porte la PMT d'amortissement : capitalisé après un différé total."""
    if differe_type == "total":
        return capital * (1 + taux_nominal / 12) ** differe_mois
    return capital


def echeancier(capital: float, taux_nominal: float, n_mois: int,
               differe_type: str = "aucun", differe_mois: int = 0) -> list[dict]:
    """Liste mensuelle de `n_mois` lignes {mois, interets, capital, crd, mensualite} (hors assurance).

    - "aucun"   : PMT sur n mois.
    - "partiel" : k mois d'intérêts seuls (CRD inchangé), puis PMT sur n - k mois.
    - "total"   : k mois sans paiement, intérêts capitalisés (lignes de capital négatives, CRD qui
                  monte), puis PMT du capital capitalisé sur n - k mois.
    Σ capital = capital emprunté et CRD final = 0, quel que soit le différé.
    """
    _verifier_pret(capital, n_mois)
    valider_differe(differe_type, differe_mois, n_mois)
    t = taux_nominal / 12
    lignes: list[dict] = []
    crd = capital

    for mois in range(1, differe_mois + 1):
        interets = crd * t
        if differe_type == "partiel":
            lignes.append({"mois": mois, "interets": interets, "capital": 0.0, "crd": crd,
                           "mensualite": interets})
        else:  # "total" : intérêts capitalisés, forme fermée capital × (1 + t)^mois
            crd_apres = capital * (1 + t) ** mois
            lignes.append({"mois": mois, "interets": interets, "capital": crd - crd_apres,
                           "crd": crd_apres, "mensualite": 0.0})
            crd = crd_apres

    pmt = mensualite(_capital_a_amortir(capital, taux_nominal, differe_type, differe_mois),
                     taux_nominal, n_mois - differe_mois)
    for mois in range(differe_mois + 1, n_mois + 1):
        interets = crd * t
        amorti = pmt - interets
        crd -= amorti
        lignes.append({"mois": mois, "interets": interets, "capital": amorti, "crd": crd, "mensualite": pmt})
    return lignes


def _differe(bien: dict) -> dict:
    return bien["financement"].get("differe", DIFFERE_AUCUN)


def echeancier_bien(bien: dict) -> list[dict]:
    f, d = bien["financement"], _differe(bien)
    return echeancier(emprunt(bien), f["taux_nominal"], f["duree_mois"], d["type"], d["mois"])


def mensualite_amortissement(bien: dict) -> float:
    """Mensualité hors assurance en année pleine d'amortissement (après un éventuel différé)."""
    f, d = bien["financement"], _differe(bien)
    capital = _capital_a_amortir(emprunt(bien), f["taux_nominal"], d["type"], d["mois"])
    return mensualite(capital, f["taux_nominal"], f["duree_mois"] - d["mois"])


def crd_apres(lignes: list[dict], mois: int) -> float:
    """Capital restant dû après `mois` mensualités (mois >= 1). Au-delà de la durée : 0, prêt soldé."""
    if mois < 1:
        raise ValueError(f"mois invalide : {mois!r} (doit être >= 1)")
    if mois > len(lignes):
        return 0.0
    return lignes[mois - 1]["crd"]


def apport(bien: dict, params: dict | None = None) -> float:
    return cout_total(bien, params) - emprunt(bien)
