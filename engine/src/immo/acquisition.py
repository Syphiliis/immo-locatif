"""Frais et coût d'acquisition : DMTO, frais d'acquisition, coût total.

Fonctions pures, sans arrondi interne. Les taux viennent de `params.json` (datés et sourcés).
"""
from __future__ import annotations

from .modele import charger_params, valeur


def dmto_detail(prix: float, departement: str, params: dict | None = None) -> dict:
    """DMTO d'un bien ancien, en trois composantes.

    L'assiette est le prix net vendeur hors mobilier. Les frais d'assiette et de recouvrement
    s'appliquent au droit départemental, pas au prix.
    """
    params = charger_params() if params is None else params
    connus = params["dmto"]["departements"]
    if departement not in connus:
        raise ValueError(
            f"département absent des paramètres DMTO : {departement!r} (paramétrés : {', '.join(sorted(connus))}). "
            f"Ajouter dans immo-data/params_local.json : {{\"dmto\": {{\"departements\": {{\"{departement}\": "
            "{\"taux_departemental\": {\"valeur\": <taux en décimal : 5 % s'écrit 0.05>, \"source\": \"table DGFiP des "
            "taux DMTO applicables (impots.gouv.fr, espace partenaires, notaires), date de la table et ligne du "
            "département\", \"verifie_le\": \"AAAA-MM-JJ\"}}}}}. Taux du droit commun (hors primo-accédant) pour un "
            "investissement locatif. Aucun taux n'est deviné.")
    taux_dep = valeur(params, f"dmto.departements.{departement}.taux_departemental")
    taux_com = valeur(params, "dmto.taux_communal")
    taux_assiette = valeur(params, "dmto.frais_assiette")

    droit_departemental = prix * taux_dep
    taxe_communale = prix * taux_com
    frais_assiette = droit_departemental * taux_assiette
    return {
        "droit_departemental": droit_departemental,
        "taxe_communale": taxe_communale,
        "frais_assiette": frais_assiette,
        "total": droit_departemental + taxe_communale + frais_assiette,
    }


def dmto(prix: float, departement: str, params: dict | None = None) -> float:
    return dmto_detail(prix, departement, params)["total"]


def frais_acquisition(bien: dict, params: dict | None = None) -> float:
    """DMTO + autres frais (émoluments, débours, CSI : entrée issue d'une simulation notariale datée)."""
    return dmto(bien["prix_net_vendeur"], bien["departement"], params) + bien["autres_frais_acquisition"]


def cout_total(bien: dict, params: dict | None = None) -> float:
    return (bien["prix_net_vendeur"] + frais_acquisition(bien, params) + bien["travaux"]
            + bien["mobilier"] + bien["frais_agence_acquereur"])
