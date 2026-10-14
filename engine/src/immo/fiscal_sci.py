"""Fiscalité de la SCI, année 1 : SCI à l'IR (foncier réel en quote-part) et SCI à l'IS (BIC, IS, distribution).

Fonctions pures, sans arrondi interne ; les règles viennent de `params.json` (valeurs datées et sourcées).
`regimes_sci()` assemble les deux régimes d'un scénario à partir de l'assiette déjà calculée par
`fiscal_nom_propre._scenario` ; il ne lit aucune source réelle. La revente (plus-value sur la valeur nette
comptable), la liquidation et le TRI des associés sont dans `sortie.py`.
"""
from __future__ import annotations

from .acquisition import frais_acquisition
from .fiscal_nom_propre import _charges_lmnp, _regime, amortissements_composants, foncier_reel
from .modele import valeur

RAISON_MICRO_FONCIER_ASSOCIE = (
    "micro-foncier non codé pour un associé : exclu sauf si le foyer est aussi propriétaire en direct d'un immeuble "
    "donné en location nue (CGI 32, 2-d ; BOI-RFPI-DECLA-10-20250306 §50 et §70)")

HYPOTHESES_SCI = [
    "SCI : résultat de l'année 1 (12 mois). Si le premier exercice ne dure pas 12 mois (sci.duree_premier_exercice_mois), "
    "seule la limite du taux réduit d'IS est proratisée (BOI-IS-LIQ-20-20-20230621 §50) ; le résultat n'est pas ramené "
    "à la durée de l'exercice.",
    "SCI : frais de constitution et de tenue (statuts, annonce légale, liasse) à fournir dans exploitation.comptable ; "
    "aucun n'est supposé.",
    "SCI à l'IR : foncier réel en quote-part (sci.quote_part_foyer), plafond de 10 700 € appliqué au foyer après la "
    "quote-part ; cash-flow et coût total du foyer pris en quote-part.",
    "SCI à l'IS : amortissement par composants sans limitation au loyer (CGI 39 C II ne vise pas les sociétés ayant "
    "opté pour l'IS, BOI-BIC-AMT-20-40-10-10 §30) ; composants et durées de fiscal.lmnp.composants (pratique, "
    "a_verifier).",
    "SCI à l'IS : taux réduit de 15 % (CGI 219 I-b) ; chiffre d'affaires ≤ 10 M€ et capital détenu à 75 % au moins par "
    "des personnes physiques supposés ; capital entièrement libéré lu dans sci.capital_libere.",
    "SCI à l'IS : premier exercice, aucun déficit antérieur ; le déficit reste dans la SCI (report en avant, CGI 209-I "
    "al. 3) et ne s'impute pas sur les revenus des associés ; report en arrière (CGI 220 quinquies) non codé.",
    "SCI à l'IS : intérêts de compte courant plafonnés au taux de référence des exercices de 12 mois (CGI 39-1-3°, "
    "BOI-BIC-CHG-50-50-30), clôture supposée au 31/12 de l'année de revenus ; non déduits si ce taux n'est pas publié. "
    "Côté associé : revenus de capitaux mobiliers, imposition non calculée.",
    "SCI à l'IS : cash-flow de la SCI = cash-flow avant impôt - intérêts de compte courant versés / 12 - IS / 12 ; "
    "rendement net-net = rendement net - IS / coût total.",
    "SCI à l'IS : dividende comparé au PFU et au barème sur cette seule distribution ; l'option pour le barème est "
    "globale (CGI 200 A, 2) et vaut pour tous les revenus de capitaux du foyer de l'année. Distribuable : montant ≤ "
    "résultat après IS de l'exercice, résultat fiscal pris pour le résultat comptable, réserves non modélisées.",
    "SCI à l'IS : option révocable jusqu'au 5e exercice suivant celui de l'option (avant la fin du mois précédant la "
    "date limite du premier acompte d'IS), puis irrévocable ; après une renonciation, plus de nouvelle option (CGI 239).",
    "SCI à l'IS : cfe reprise de l'entrée ; la location nue d'habitation n'est pas réputée professionnelle pour la CFE "
    "(CGI 1447 I) ; TVA non traitée.",
]


# --------------------------------------------------------------------------------------------
# Règles (fonctions pures)
# --------------------------------------------------------------------------------------------

def impot_societes(resultat: float, duree_exercice_mois: int, params: dict,
                   taux_reduit_applicable: bool = True) -> dict:
    """IS : taux réduit jusqu'à la limite proratisée sur la durée de l'exercice, taux normal au-delà ; 0 si ≤ 0."""
    limite = valeur(params, "fiscal.is.limite_taux_reduit_12_mois") * duree_exercice_mois / 12
    if resultat <= 0:
        reduit, normal = 0.0, 0.0
    elif taux_reduit_applicable:
        reduit = min(resultat, limite)
        normal = resultat - reduit
    else:
        reduit, normal = 0.0, resultat
    impot = valeur(params, "fiscal.is.taux_reduit") * reduit + valeur(params, "fiscal.is.taux_normal") * normal
    return {"base_taux_reduit": reduit, "base_taux_normal": normal, "limite_appliquee": limite,
            "duree_exercice_mois": duree_exercice_mois, "impot": impot}


def imputer_deficits(resultat: float, deficits_anterieurs: float, params: dict) -> dict:
    """Report en avant (CGI 209-I al. 3) : imputation ≤ 1 M€ + 50 % du bénéfice au-delà ; le reste se reporte."""
    if resultat <= 0:
        return {"imposable": 0.0, "deficit_impute": 0.0, "deficit_reporte": deficits_anterieurs - resultat}
    limite = valeur(params, "fiscal.sci_is.deficit_imputation_max")
    plafond = limite["franchise"] + limite["fraction_au_dela"] * max(0.0, resultat - limite["franchise"])
    impute = min(deficits_anterieurs, resultat, plafond)
    return {"imposable": resultat - impute, "deficit_impute": impute, "deficit_reporte": deficits_anterieurs - impute}


def interets_cca(cca: dict, capital_libere: bool, date_cloture: str | None, duree_exercice_mois: int,
                 params: dict) -> dict:
    """Intérêts de compte courant : versés = montant × taux ; déductibles au taux maximal publié (CGI 39-1-3°).

    Clôture postérieure au dernier taux publié → dernier taux publié, hypothèse « à vérifier » dite (convention
    du moteur). Clôture antérieure à la table, sans date, ou exercice qui ne
    dure pas 12 mois → non déduits, raison dite.
    """
    verses = cca["montant"] * cca["taux"]
    if verses == 0:
        return {"verses": 0.0, "deductibles": 0.0, "raisons": []}
    if not capital_libere:
        return {"verses": verses, "deductibles": 0.0,
                "raisons": ["intérêts de compte courant non déduits : capital non entièrement libéré (CGI 39-1-3°)"]}
    if duree_exercice_mois != 12:
        return {"verses": verses, "deductibles": 0.0,
                "raisons": [f"intérêts de compte courant non déduits : exercice de {duree_exercice_mois} mois, seuls les "
                            "taux des exercices de 12 mois sont paramétrés (fiscal.sci_is.taux_max_interets_cca)"]}
    table = valeur(params, "fiscal.sci_is.taux_max_interets_cca")
    publies = [t["taux"] for t in table
               if date_cloture is not None and t["cloture_du"] <= date_cloture <= t["cloture_au"]]
    anterieurs = [t for t in table if date_cloture is not None and t["cloture_au"] < date_cloture]
    if not publies and anterieurs:
        dernier = max(anterieurs, key=lambda t: t["cloture_au"])
        taux = str(round(dernier["taux"] * 100, 2)).replace(".", ",")
        return {"verses": verses, "deductibles": cca["montant"] * min(cca["taux"], dernier["taux"]),
                "raisons": [f"intérêts de compte courant déduits au dernier taux maximal publié ({taux} % "
                            f"pour les clôtures du {dernier['cloture_du']} au {dernier['cloture_au']}), hypothèse à "
                            f"vérifier : taux non publié pour une clôture au {date_cloture} "
                            "(fiscal.sci_is.taux_max_interets_cca, BOI-BIC-CHG-50-50-30)"]}
    if not publies:
        return {"verses": verses, "deductibles": 0.0,
                "raisons": [f"intérêts de compte courant non déduits : taux maximal non publié pour une clôture au "
                            f"{date_cloture} (fiscal.sci_is.taux_max_interets_cca, BOI-BIC-CHG-50-50-30)"]}
    return {"verses": verses, "deductibles": cca["montant"] * min(cca["taux"], publies[0]), "raisons": []}


def distribution(montant: float, resultat_apres_is: float, tmi: float | None, remboursement_cca: float,
                 cf_sci_mensuel: float, params: dict) -> dict:
    """Dividende brut au PFU et au barème (abattement 40 %), remboursement de compte courant non imposable."""
    raisons = []
    distribuable = montant <= resultat_apres_is
    if not distribuable:
        raisons.append(f"distribution {round(montant, 2)} > résultat après IS de l'exercice "
                       f"{round(resultat_apres_is, 2)} : non couverte par le bénéfice (réserves non modélisées)")
    ps = valeur(params, "fiscal.prelevements_sociaux.revenus_placement")
    impot_pfu = montant * (valeur(params, "fiscal.dividendes.pfu_ir") + ps)
    pfu = {"impot": impot_pfu, "net": montant - impot_pfu}
    bareme, option = None, None
    if tmi is None:
        raisons.append("barème non évalué : tmi absente ; cash-flow du foyer au PFU, régime par défaut (CGI 200 A)")
    else:
        ir = montant * (1 - valeur(params, "fiscal.dividendes.abattement_bareme")) * tmi
        bareme = {"ir": ir, "ps": montant * ps, "impot": ir + montant * ps, "net": montant - ir - montant * ps,
                  "csg_deductible_n1": montant * valeur(params, "fiscal.dividendes.csg_deductible") * tmi}
        option = "bareme" if bareme["impot"] < impot_pfu else "pfu"
    net = bareme["net"] if option == "bareme" else pfu["net"]
    return {"montant": montant, "distribuable": distribuable, "raisons": raisons, "pfu": pfu, "bareme": bareme,
            "option_la_plus_favorable": option, "remboursement_cca": remboursement_cca,
            "cash_flow_mensuel_foyer": (net + remboursement_cca) / 12,
            "cash_flow_mensuel_sci_apres_versements": cf_sci_mensuel - (montant + remboursement_cca) / 12}


# --------------------------------------------------------------------------------------------
# Assemblage des régimes `sci_ir` et `sci_is`
# --------------------------------------------------------------------------------------------

def _sci_ir(bien: dict, R: float, I: float, C: float, plafond: dict, tmi, ps_foncier: float, cf: float, rn: float,
            cout: float) -> dict:
    """Foncier réel du foyer sur sa quote-part ; le plafond s'applique après la quote-part (au foyer)."""
    q = bien["sci"]["quote_part_foyer"]
    f = foncier_reel(q * R, q * I, q * C, plafond["plafond"])
    return _regime(True, [RAISON_MICRO_FONCIER_ASSOCIE], f["imposable"], f["deficit_impute_global"], tmi, ps_foncier,
                   q * cf, rn, q * cout, regime_demande=bien["sci"]["regime"] == "ir", resultat=f["resultat"],
                   deficit_impute_global=f["deficit_impute_global"], report_foncier=f["report_sortant"],
                   plafond_deficit=plafond)


def _sci_is(bien: dict, s: dict, R: float, interets: float, assurance: float, tmi, annee, cf: float, rn: float,
            cout: float, params: dict) -> dict:
    sci = bien["sci"]
    duree = sci["duree_premier_exercice_mois"]
    raisons = []
    nature = bien.get("travaux_nature", "amelioration")
    frais = frais_acquisition(bien, params)
    en_charges = sci["frais_acquisition"] == "charges"
    base = bien["prix_net_vendeur"] + bien["frais_agence_acquereur"] + (0.0 if en_charges else frais)
    amort = amortissements_composants(base, bien["travaux"], nature, bien["mobilier"], params)
    cca = interets_cca(sci["cca"], sci["capital_libere"], f"{annee}-12-31" if annee is not None else None, duree,
                       params)
    raisons += cca["raisons"]
    charges = (_charges_lmnp(bien, s) + interets + assurance + (bien["travaux"] if nature == "entretien" else 0.0)
               + cca["deductibles"] + (frais if en_charges else 0.0))
    resultat = R - charges - amort["total"]
    report = imputer_deficits(resultat, 0.0, params)  # premier exercice : aucun déficit antérieur
    if not sci["capital_libere"]:
        raisons.append("taux réduit de 15 % non appliqué : capital non entièrement libéré (CGI 219 I-b)")
    i = impot_societes(report["imposable"], duree, params, taux_reduit_applicable=sci["capital_libere"])
    if sci["remboursement_cca_annuel"] > sci["cca"]["montant"]:
        raisons.append("remboursement de compte courant > montant du compte courant (sci.cca.montant)")
    cf_sci = cf - cca["verses"] / 12 - i["impot"] / 12
    apres_is = resultat - i["impot"]
    versements = sci["distribution_annuelle"] or sci["remboursement_cca_annuel"]
    return {"evaluable": True, "eligible": True, "raisons": raisons, "imposable": report["imposable"], "ir": None,
            "ps": None, "impot_total": i["impot"], "cash_flow_mensuel_net_net": cf_sci,
            "rendement_net_net": rn - i["impot"] / cout, "regime_demande": sci["regime"] == "is",
            "resultat_fiscal": resultat, "charges_deductibles": charges, "base_amortissable": base,
            "amortissements": amort, "frais_acquisition_traitement": {"option": sci["frais_acquisition"], "montant": frais},
            "is_detail": {k: i[k] for k in ("base_taux_reduit", "base_taux_normal", "limite_appliquee",
                                            "duree_exercice_mois")},
            "deficit_reporte": report["deficit_reporte"], "interets_cca_deductibles": cca["deductibles"],
            "interets_cca_verses": cca["verses"], "resultat_apres_is": apres_is,
            "distribution": (distribution(sci["distribution_annuelle"], apres_is, tmi, sci["remboursement_cca_annuel"],
                                          cf_sci, params) if versements else {})}


def regimes_sci(bien: dict, s: dict, params: dict, *, R: float, I: float, C: float, interets: float, assurance: float,
                plafond: dict, tmi, annee, cf: float, rn: float, cout: float) -> dict:
    """`sci_ir` et `sci_is` d'un scénario ; sans bloc `sci`, tous deux non évaluables."""
    ps_foncier = valeur(params, "fiscal.prelevements_sociaux.revenus_fonciers")
    if "sci" not in bien:
        return {nom: _regime(False, ["non évaluable : bloc sci absent"], None, None, tmi, ps_foncier, cf, rn, cout,
                             evaluable=False) for nom in ("sci_ir", "sci_is")}
    return {"sci_ir": _sci_ir(bien, R, I, C, plafond, tmi, ps_foncier, cf, rn, cout),
            "sci_is": _sci_is(bien, s, R, interets, assurance, tmi, annee, cf, rn, cout, params)}
