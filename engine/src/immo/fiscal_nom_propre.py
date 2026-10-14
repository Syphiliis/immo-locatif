"""Fiscalité en nom propre, année 1 : micro-foncier, foncier réel (déficit), LMNP micro-BIC et réel, bailleur privé.

Les régimes de la SCI (IR et IS) sont calculés par `fiscal_sci.py` et rangés avec eux.

Fonctions pures, sans arrondi interne ; les règles viennent de `params.json` (datées, sourcées, avec leur
nature : loi, doctrine ou pratique). `fiscalite()` assemble la section `fiscalite` du contrat de sortie ;
elle ne lit aucun fichier : le contexte du foyer lui est passé tout fait (`foyer.charger()`, depuis foyer.json).
"""
from __future__ import annotations

from datetime import date

from .acquisition import cout_total, frais_acquisition
from .exploitation import loyers_encaisses
from .financement import assurance_mensuelle, echeancier_bien
from .indicateurs import cash_flow_mensuel_avant_impot, rendement_net
from .modele import SCENARIOS, valeur

CHAMPS_BAILLEUR_PRIVE = ("surface_habitable", "code_insee", "immeuble_collectif", "date_acquisition",
                         "bailleur_prive")

HYPOTHESES = [
    "(a) assurance emprunteur et frais d'emprunt dans le bloc « intérêts » du foncier réel (ligne 250 de la 2044), non "
    "imputable sur le revenu global (fiscal.foncier.frais_emprunt_dans_bloc_interets, a_verifier).",
    "(b) LMNP : frais d'acquisition incorporés au prix et ventilés comme lui ; l'option « charge de l'année 1 » "
    "(CGI ann. III art. 38 quinquies) n'est pas codée (fiscal.lmnp.frais_acquisition, a_verifier).",
    "(c) LMNP : ventilation par composants et durées d'usage, pratique et non doctrine (fiscal.lmnp.composants, "
    "a_verifier).",
    "(d) LMNP : amortissement limité au résultat (CGI 39 C II), puis déficits antérieurs imputés sur le reste "
    "(fiscal.lmnp.ordre_imputation, a_verifier).",
    "(e) forfait de frais de gestion de 20 € par local (ligne 222 de la 2044) NON modélisé.",
    "Provision CAPEX : pas une charge déductible (ce n'est pas une dépense).",
    "Foncier : CFE et honoraires comptables exclus des charges déductibles ; LMNP : inclus.",
    "Cash-flow net-net = cash-flow avant impôt en année pleine d'amortissement - impôt de l'année 1 / 12 ; "
    "rendement net-net = rendement net - impôt de l'année 1 / coût total.",
    "LMNP : même loyer que la location nue ; micro-BIC en catégorie « meublé de longue durée ».",
    "Bailleur privé : mode « prudent » retenu (amortissement dans le bloc non imputable, comme les intérêts) ; "
    "mode « droit commun » (probable, précédent Robien BOI-RFPI-SPEC-20-20-40 §30) affiché en écart.",
    "IR au taux marginal fixe (tmi) : ni barème, ni décote, ni plafond du quotient familial, ni changement de tranche. "
    "En zone de décote, un euro imposable coûte environ tmi × 1,4525 (coefficient de décote de 45,25 %, barème 2025) ; "
    "un déficit qui fait changer de tranche est surestimé. Même réserve pour l'IR des dividendes au barème (SCI à "
    "l'IS). Contrôle croisé avec OpenFisca.",
]


# --------------------------------------------------------------------------------------------
# Règles (fonctions pures)
# --------------------------------------------------------------------------------------------

def foncier_reel(R: float, I: float, C: float, plafond: float, report_in: float = 0.0) -> dict:
    """Résultat foncier réel avec l'ordre d'imputation du foncier réel : le revenu brut compense d'abord les intérêts (I).

    Seule la part du déficit née des autres charges (C) s'impute sur le revenu global, dans la limite
    `plafond` ; le reste s'ajoute au report (10 ans, revenus fonciers seulement). Un résultat positif
    absorbe d'abord le report entrant.
    """
    res = R - I - C
    if res >= 0:
        absorbe = min(report_in, res)
        return {"resultat": res, "imposable": res - absorbe, "deficit_impute_global": 0.0,
                "report_absorbe": absorbe, "report_sortant": report_in - absorbe}
    imp_glob = min(plafond, max(0.0, C - max(0.0, R - I)))
    return {"resultat": res, "imposable": 0.0, "deficit_impute_global": imp_glob, "report_absorbe": 0.0,
            "report_sortant": report_in + (-res - imp_glob)}


def plafond_deficit(renovation: dict | None, annee_revenus: int | None, params: dict) -> dict:
    """10 700 €, ou min(21 400 ; 10 700 + dépenses) si toutes les conditions de la rénovation énergétique."""
    base = valeur(params, "fiscal.deficit_foncier.plafond_revenu_global")
    if not renovation:
        return {"plafond": base, "majore": False, "raisons": ["pas de rénovation énergétique déclarée"]}
    raisons = []
    if renovation["classe_avant"] not in valeur(params, "fiscal.deficit_foncier.renovation_classes_avant"):
        raisons.append(f"classe avant {renovation['classe_avant']} : E, F ou G requise")
    if renovation["classe_apres"] not in valeur(params, "fiscal.deficit_foncier.renovation_classes_apres"):
        raisons.append(f"classe après {renovation['classe_apres']} : A, B, C ou D requise")
    debut, fin = valeur(params, "fiscal.deficit_foncier.renovation_annees_paiement")
    if annee_revenus is None or not debut <= annee_revenus <= fin:
        raisons.append(f"année de revenus {annee_revenus} hors de la période de paiement {debut}-{fin}")
    if raisons:
        return {"plafond": base, "majore": False, "raisons": raisons}
    plafond = min(valeur(params, "fiscal.deficit_foncier.plafond_majore_renovation"), base + renovation["depenses"])
    return {"plafond": plafond, "majore": plafond > base,
            "raisons": ["plafond majoré (option à exercer sur la 2044 ; nouveau classement à justifier au plus "
                        "tard le 31/12/2027)"]}


def micro_foncier(R_bien: float, R_foyer_existant: float, a_un_bien_ij: bool, params: dict) -> dict:
    """Éligible si les revenus fonciers bruts du FOYER (bien compris) ≤ 15 000 € et aucun bien en i/j."""
    seuil = valeur(params, "fiscal.micro_foncier.seuil_revenus_bruts_foyer")
    raisons = []
    if R_bien + R_foyer_existant > seuil:
        raisons.append(f"revenus fonciers bruts du foyer {round(R_bien + R_foyer_existant, 2)} > 15 000 € (CGI 32)")
    if a_un_bien_ij:
        raisons.append("le foyer détient un logement au statut du bailleur privé (CGI 32, 2-c)")
    if raisons:
        return {"eligible": False, "raisons": raisons, "imposable": None}
    abattement = valeur(params, "fiscal.micro_foncier.abattement")
    return {"eligible": True, "raisons": [], "imposable": R_bien * (1 - abattement)}


def micro_bic(recettes: float, categorie: str, annee: int | None, params: dict) -> dict:
    """Abattement max(305 ; taux × recettes), plafond de recettes selon l'année et la catégorie."""
    bareme = params["fiscal"]["micro_bic"].get(f"revenus_{annee}")
    if bareme is None:
        return {"evaluable": False, "eligible": False, "imposable": None, "abattement": None,
                "raisons": [f"non évaluable : barème micro-BIC des revenus {annee} non paramétré"]}
    regle = bareme["valeur"][categorie]
    if recettes > regle["plafond"]:
        return {"evaluable": True, "eligible": False, "imposable": None, "abattement": None,
                "raisons": [f"recettes {round(recettes, 2)} > plafond micro-BIC {regle['plafond']} € ({annee})"]}
    abattement = min(recettes, max(valeur(params, "fiscal.micro_bic.abattement_minimum"),
                                   regle["abattement"] * recettes))
    return {"evaluable": True, "eligible": True, "imposable": recettes - abattement, "abattement": abattement,
            "raisons": []}


def lmnp_reel(R: float, charges: float, amortissement_dispo: float, deficits_anterieurs: float = 0.0) -> dict:
    """BIC réel : l'amortissement ne crée pas de déficit (39 C II), puis les déficits antérieurs s'imputent."""
    pre = R - charges
    if pre < 0:
        return {"resultat_avant_amortissement": pre, "amortissement_deduit": 0.0, "ard_reporte": amortissement_dispo,
                "deficit_impute": 0.0, "deficit_sortant": deficits_anterieurs - pre, "imposable": 0.0}
    deduit = min(amortissement_dispo, pre)
    reste = pre - deduit
    impute = min(deficits_anterieurs, reste)
    return {"resultat_avant_amortissement": pre, "amortissement_deduit": deduit,
            "ard_reporte": amortissement_dispo - deduit, "deficit_impute": impute,
            "deficit_sortant": deficits_anterieurs - impute, "imposable": reste - impute}


def amortissements_composants(base: float, travaux: float, nature_travaux: str, mobilier: float,
                              params: dict) -> dict:
    """Amortissement annuel : composants du bâti (terrain exclu), travaux d'amélioration, mobilier."""
    composants = valeur(params, "fiscal.lmnp.composants")
    bati = base * sum(c[0] / c[1] for nom, c in composants.items() if nom != "terrain")  # c = [part, durée]
    trav = travaux / valeur(params, "fiscal.lmnp.duree_travaux_amelioration") if nature_travaux == "amelioration" else 0.0
    mob = mobilier / valeur(params, "fiscal.lmnp.duree_mobilier")
    return {"bati": bati, "travaux": trav, "mobilier": mob, "total": bati + trav + mob}


def bailleur_prive(bien: dict, loyer_mensuel_hc: float, params: dict) -> dict:
    """Éligibilité, amortissement plafonné et loyer retenu = min(loyer du scénario ; plafond intermédiaire)."""
    manquants = [c for c in CHAMPS_BAILLEUR_PRIVE if c not in bien]
    if manquants:
        return {"evaluable": False, "eligible": False,
                "raisons": [f"non évaluable : champ absent : {c}" for c in manquants]}
    regime, location = bien["bailleur_prive"]["regime"], bien["bailleur_prive"]["location"]
    raisons, evaluable = [], True
    if not bien["immeuble_collectif"]:
        raisons.append("logement hors immeuble collectif (CGI 31-I-1° i et j)")
    fenetre = valeur(params, "fiscal.bailleur_prive.fenetre_acquisition")
    if not fenetre["debut"] <= date.fromisoformat(bien["date_acquisition"]).isoformat() <= fenetre["fin"]:
        raisons.append(f"acquisition hors fenêtre du {fenetre['debut']} au {fenetre['fin']}")
    prix, travaux = bien["prix_net_vendeur"], bien["travaux"]
    if regime == "j" and travaux < valeur(params, "fiscal.bailleur_prive.travaux_min_j") * prix:
        raisons.append("travaux < 30 % du prix (j)")
    zones = valeur(params, "fiscal.bailleur_prive.zones")
    zone = zones.get(bien["code_insee"])
    if zone is None:
        raise ValueError(
            f"zone locative inconnue pour la commune de code INSEE {bien['code_insee']} "
            f"(communes paramétrées : {', '.join(sorted(zones)) or 'aucune'}). Ajouter dans immo-data/params_local.json "
            "la feuille fiscal.bailleur_prive.zones : {\"valeur\": {\"<code INSEE>\": \"<A bis, A, B1, B2 ou C>\", ...}, "
            "\"source\": \"arrêté du 1er août 2014 modifié (zonage A/B/C), version en vigueur sur Légifrance, avec "
            "l'article et la ligne lus\", \"verifie_le\": \"AAAA-MM-JJ\"}. La feuille locale remplace celle de "
            "params.json : y lister toutes les communes utiles. Aucune zone n'est devinée.")
    if location != "intermediaire":
        evaluable = False
        raisons.append(f"non évaluable : plafond de loyer de la location {location} non paramétré")
    if regime == "j":
        raisons.append("condition non modélisée : réhabilitation lourde (CGI 150 U, II, 7°, b), à vérifier")
    raisons.append("conditions non modélisées : plafonds de ressources du locataire, location nue en résidence "
                   "principale 9 ans, bail dans les 12 mois, option irrévocable")
    eligible = evaluable and not any(not r.startswith("condition") for r in raisons)
    if not evaluable:
        return {"evaluable": False, "eligible": False, "raisons": raisons}

    part_foncier = valeur(params, "fiscal.bailleur_prive.part_foncier")
    base = (prix + (travaux if regime == "j" else 0.0)) * (1 - part_foncier)
    taux = valeur(params, "fiscal.bailleur_prive.taux")[regime][location]
    plafond_annuel = valeur(params, "fiscal.bailleur_prive.plafond_annuel_foyer")[location]
    coef = valeur(params, "fiscal.bailleur_prive.coefficient_surface")
    surface = bien["surface_habitable"]
    coefficient = min(coef["maximum"], round(coef["constante"] + coef["numerateur"] / surface, 2))
    loyer_m2 = valeur(params, "fiscal.bailleur_prive.loyer_plafond_intermediaire_2026")[zone] * coefficient
    loyer_plafond = loyer_m2 * surface
    return {"evaluable": True, "eligible": eligible, "raisons": raisons, "zone": zone,
            "base_amortissable": base, "taux_amortissement": taux,
            "amortissement": min(plafond_annuel, base * taux), "coefficient_surface": coefficient,
            "loyer_plafond_m2": loyer_m2, "loyer_plafond_mensuel": loyer_plafond,
            "loyer_retenu": min(loyer_mensuel_hc, loyer_plafond)}


def impot(imposable: float, imp_glob: float, tmi: float, ps: float) -> dict:
    """IR à la TMI + PS sur l'imposable ; le déficit imputé sur le revenu global ne réduit que l'IR."""
    ir = imposable * tmi - imp_glob * tmi
    prelevements = imposable * ps
    return {"ir": ir, "ps": prelevements, "total": ir + prelevements}


def effet_foyer(existant: dict, bien: dict, plafond_seul: float, plafond_avec: float, tmi: float, ps: float,
                report_in: float = 0.0) -> dict:
    """Effet marginal du bien : impôt foncier du foyer avec le bien - impôt du foyer seul (même année).

    Le plafond d'imputation est celui du foyer (CGI 156 I-3°) : la majoration pour rénovation énergétique suit les
    dépenses de l'année, donc le foyer seul ne reçoit pas celle qui naît des travaux du bien.
    """
    seul = foncier_reel(existant["R"], existant["I"], existant["C"], plafond_seul, report_in)
    avec = foncier_reel(existant["R"] + bien["R"], existant["I"] + bien["I"], existant["C"] + bien["C"],
                        plafond_avec, report_in)
    impot_seul = impot(seul["imposable"], seul["deficit_impute_global"], tmi, ps)["total"]
    impot_avec = impot(avec["imposable"], avec["deficit_impute_global"], tmi, ps)["total"]
    return {"impot_foyer_seul": impot_seul, "impot_foyer_avec_bien": impot_avec,
            "effet_marginal": impot_avec - impot_seul, "deficit_impute_global": avec["deficit_impute_global"],
            "plafond_foyer_seul": plafond_seul, "plafond_foyer_avec_bien": plafond_avec,
            "report_sortant": avec["report_sortant"], "report_entrant": report_in}


# --------------------------------------------------------------------------------------------
# Assemblage de la section `fiscalite`
# --------------------------------------------------------------------------------------------

def interets_assurance_an1(bien: dict) -> tuple[float, float]:
    """Intérêts des 12 premières mensualités et assurance des mêmes mois."""
    lignes = echeancier_bien(bien)[:12]
    return sum(l["interets"] for l in lignes), assurance_mensuelle(bien) * len(lignes)


def _charges_foncier(bien: dict, s: dict) -> float:
    e, enc = bien["exploitation"], loyers_encaisses(s)
    return e["taxe_fonciere"] + e["pno"] + e["copro_non_recuperable"] + (e["gestion_taux"] + e["gli_taux"]) * enc


def _charges_lmnp(bien: dict, s: dict) -> float:
    e = bien["exploitation"]
    return _charges_foncier(bien, s) + e["cfe"] + e["comptable"]


def _regime(eligible: bool, raisons: list, imposable, imp_glob, tmi, ps_taux, cf_avant, rend_net, cout,
            evaluable: bool = True, **details) -> dict:
    """Bloc commun d'un régime ; montants None si inéligible, non évaluable, ou sans TMI."""
    sortie = {"evaluable": evaluable, "eligible": eligible, "raisons": list(raisons), "imposable": None, "ir": None,
              "ps": None, "impot_total": None, "cash_flow_mensuel_net_net": None, "rendement_net_net": None}
    if eligible and evaluable:
        sortie["imposable"] = imposable
        sortie["ps"] = imposable * ps_taux
        if tmi is None:
            sortie["evaluable"] = False
            sortie["raisons"].append("non évaluable : tmi absente (fiscal.tmi dans le bien, ou --foyer)")
        else:
            i = impot(imposable, imp_glob, tmi, ps_taux)
            sortie.update(ir=i["ir"], impot_total=i["total"], cash_flow_mensuel_net_net=cf_avant - i["total"] / 12,
                          rendement_net_net=rend_net - i["total"] / cout)
    sortie.update(details)
    return sortie


def _scenario(bien: dict, nom: str, params: dict, tmi, annee, ctx: dict | None) -> dict:
    s = bien["scenarios"][nom]
    cout = cout_total(bien, params)
    cf, rn = cash_flow_mensuel_avant_impot(bien, s), rendement_net(bien, s, params)
    R = loyers_encaisses(s)
    interets, assurance = interets_assurance_an1(bien)
    bloc_interets = valeur(params, "fiscal.foncier.frais_emprunt_dans_bloc_interets")
    I = interets + (assurance if bloc_interets else 0.0)
    autres_frais_emprunt = 0.0 if bloc_interets else assurance
    trav_ded = bien.get("travaux_deductibles_foncier", bien["travaux"])
    C = _charges_foncier(bien, s) + trav_ded + autres_frais_emprunt
    ps_foncier = valeur(params, "fiscal.prelevements_sociaux.revenus_fonciers")
    plafond = plafond_deficit(bien.get("renovation_energetique"), annee, params)
    regimes = {}

    # Micro-foncier
    R_existant = ctx["revenus_fonciers_bruts_existants"] if ctx else 0.0
    m = micro_foncier(R, R_existant, ctx["a_un_bien_ij"] if ctx else False, params)
    regimes["micro_foncier"] = _regime(m["eligible"], m["raisons"], m["imposable"], 0.0, tmi, ps_foncier, cf, rn, cout)

    # Foncier réel
    f = foncier_reel(R, I, C, plafond["plafond"])
    details = {"resultat": f["resultat"], "deficit_impute_global": f["deficit_impute_global"],
               "report_foncier": f["report_sortant"], "plafond_deficit": plafond}
    if ctx and tmi is not None:
        # foyer seul : aucune dépense de rénovation énergétique hors du bien (hypothèse affichée dans `fiscalite`)
        plafond_seul = valeur(params, "fiscal.deficit_foncier.plafond_revenu_global")
        details["effet_foyer"] = effet_foyer(ctx["foncier_existant"], {"R": R, "I": I, "C": C}, plafond_seul,
                                             plafond["plafond"], tmi, ps_foncier)
    regimes["foncier_reel"] = _regime(True, [], f["imposable"], f["deficit_impute_global"], tmi, ps_foncier, cf, rn,
                                      cout, **details)

    # LMNP : PS des BIC, seuil LMP
    ps_bic = params["fiscal"]["prelevements_sociaux"]["bic_lmnp"]
    raisons_lmnp = []
    bic_evaluable = annee is not None and annee >= ps_bic["annee_min"]
    if not bic_evaluable:
        raisons_lmnp.append(f"non évaluable : prélèvements sociaux BIC des revenus {annee} non paramétrés")
    if R > valeur(params, "fiscal.lmnp.seuil_lmp_recettes"):
        raisons_lmnp.append("recettes > 23 000 € : LMP si elles dépassent aussi les autres revenus d'activité du "
                            "foyer (CGI 155 IV 2), à vérifier")
    mb = micro_bic(R, "meuble_longue_duree", annee, params)
    regimes["lmnp_micro_bic"] = _regime(mb["eligible"], raisons_lmnp + mb["raisons"], mb["imposable"], 0.0, tmi,
                                        ps_bic["valeur"], cf, rn, cout, evaluable=mb["evaluable"] and bic_evaluable,
                                        abattement=mb["abattement"])

    if valeur(params, "fiscal.lmnp.frais_acquisition") != "incorpores":
        raise ValueError("fiscal.lmnp.frais_acquisition : seule l'incorporation au prix est codée")
    nature = bien.get("travaux_nature", "amelioration")
    base = bien["prix_net_vendeur"] + frais_acquisition(bien, params) + bien["frais_agence_acquereur"]
    amort = amortissements_composants(base, bien["travaux"], nature, bien["mobilier"], params)
    charges_lmnp = (_charges_lmnp(bien, s) + interets + assurance
                    + (bien["travaux"] if nature == "entretien" else 0.0))
    lr = lmnp_reel(R, charges_lmnp, amort["total"])
    regimes["lmnp_reel"] = _regime(True, raisons_lmnp, lr["imposable"], 0.0, tmi, ps_bic["valeur"], cf, rn, cout,
                                   evaluable=bic_evaluable, base_amortissable=base, amortissements=amort,
                                   amortissement_dispo=amort["total"],
                                   **{k: lr[k] for k in ("resultat_avant_amortissement", "amortissement_deduit",
                                                         "ard_reporte", "deficit_sortant")})

    # Bailleur privé : tout se recalcule sur le loyer retenu
    bp = bailleur_prive(bien, s["loyer_mensuel_hc"], params)
    if not (bp["evaluable"] and bp["eligible"]):
        regimes["bailleur_prive"] = _regime(False, bp["raisons"], None, None, tmi, ps_foncier, cf, rn, cout,
                                            evaluable=bp["evaluable"],
                                            **{k: v for k, v in bp.items() if k not in ("evaluable", "eligible",
                                                                                         "raisons")})
    else:
        s_bp = {**s, "loyer_mensuel_hc": bp["loyer_retenu"]}
        R_bp = loyers_encaisses(s_bp)
        trav_bp = 0.0 if bien["bailleur_prive"]["regime"] == "j" else trav_ded  # j : travaux dans la base amortie
        C_bp = _charges_foncier(bien, s_bp) + trav_bp + autres_frais_emprunt
        prudent = foncier_reel(R_bp, I + bp["amortissement"], C_bp, plafond["plafond"])
        commun = foncier_reel(R_bp, I, C_bp + bp["amortissement"], plafond["plafond"])
        cf_bp, rn_bp = cash_flow_mensuel_avant_impot(bien, s_bp), rendement_net(bien, s_bp, params)
        dc = _regime(True, [], commun["imposable"], commun["deficit_impute_global"], tmi, ps_foncier, cf_bp, rn_bp,
                     cout)
        sortie = _regime(True, bp["raisons"], prudent["imposable"], prudent["deficit_impute_global"], tmi, ps_foncier,
                         cf_bp, rn_bp, cout, mode_deficit="prudent", loyers_encaisses=R_bp,
                         resultat=prudent["resultat"], deficit_impute_global=prudent["deficit_impute_global"],
                         report_foncier=prudent["report_sortant"],
                         **{k: v for k, v in bp.items() if k not in ("evaluable", "eligible", "raisons")})
        sortie["droit_commun"] = {"resultat": commun["resultat"], "deficit_impute_global": commun["deficit_impute_global"],
                                  "report_foncier": commun["report_sortant"], "impot_total": dc["impot_total"]}
        sortie["ecart_droit_commun_vs_prudent"] = (None if dc["impot_total"] is None
                                                   else dc["impot_total"] - sortie["impot_total"])
        regimes["bailleur_prive"] = sortie

    # SCI à l'IR et à l'IS ; import différé : fiscal_sci importe les règles de ce module
    from .fiscal_sci import regimes_sci
    regimes.update(regimes_sci(bien, s, params, R=R, I=I, C=C, interets=interets, assurance=assurance,
                               plafond=plafond, tmi=tmi, annee=annee, cf=cf, rn=rn, cout=cout))

    return {"assiette": {"loyers_encaisses": R, "interets_an1": interets, "assurance_an1": assurance,
                         "charges_deductibles_foncier": C, "travaux_deductibles_foncier": trav_ded},
            "regimes": regimes}


def fiscalite(bien: dict, params: dict, contexte_foyer: dict | None = None) -> dict:
    """Section `fiscalite` : TMI et année (entrée, ou foyer.json), hypothèses, 3 scénarios × 7 régimes."""
    fiscal = bien.get("fiscal", {})
    if contexte_foyer is not None:
        tmi, tmi_source = contexte_foyer["tmi"], "foyer.json:tmi"
        annee = contexte_foyer["annee"]
    else:
        tmi = fiscal.get("tmi")
        tmi_source = "entree:fiscal.tmi" if tmi is not None else None
        annee = fiscal.get("annee_revenus")

    hypotheses = list(HYPOTHESES)
    if "travaux_deductibles_foncier" in bien:
        hypotheses.append("travaux_deductibles_foncier fourni par l'entrée.")
    else:
        hypotheses.append("travaux_deductibles_foncier absent : tous les travaux supposés déductibles en foncier "
                          "réel (entretien, réparation, amélioration), hypothèse à confirmer sur devis.")
    if "travaux_nature" not in bien:
        hypotheses.append("travaux_nature absent : travaux supposés d'amélioration (amortis sur 15 ans en LMNP).")
    hypotheses.append("Imputation du déficit foncier sur le revenu global sous condition de louer le bien jusqu'au "
                      "31/12 de la 3e année suivant l'imputation (BOI-RFPI-BASE-30-20 §340).")
    if contexte_foyer is not None:
        base = format(valeur(params, "fiscal.deficit_foncier.plafond_revenu_global"), ",").replace(",", " ")
        hypotheses += [
            "Foyer lu dans foyer.json : revenus fonciers existants, statut du bailleur privé (a_un_bien_ij) et foncier "
            f"existant (R, I, C) tels que déclarés par l'investisseur, pour l'année {annee}.",
            f"Effet foyer : plafond d'imputation du foyer seul = {base} € (fiscal.deficit_foncier."
            "plafond_revenu_global), aucune dépense de rénovation énergétique supposée sur les biens existants l'année "
            "étudiée ; la majoration née des travaux du bien ne vaut que pour le foyer avec le bien (CGI 156 I-3°, "
            "limite du foyer à concurrence des dépenses). Si le foyer en engage aussi, l'effet du bien est faussé, "
            "dans un sens ou l'autre, d'au plus (plafond majoré fiscal.deficit_foncier.plafond_majore_renovation - "
            f"{base}) × tmi.",
            "Report de déficit du foyer (foncier_existant.report_disponible) non réinjecté dans l'effet foyer : "
            "s'il naît de la même année de référence, il serait compté deux fois.",
            "Taux d'effort HCSF : mensualites_existantes = mensualites.future de foyer.json (prêts en différé ou en "
            "anticipation pris à leur mensualité d'amortissement) ; borne basse : mensualites.actuelle.",
            "Revenus du taux d'effort : revenus d'activité nets après impôt (foyer.json) + pondération × loyers HC "
            "existants (foyer.json), tous les baux supposés en cours.",
        ]
    else:
        hypotheses.append("Micro-foncier évalué pour le bien seul : revenus fonciers existants du foyer et statut i/j "
                          "non fournis (option --foyer).")
    if "sci" in bien:
        from .fiscal_sci import HYPOTHESES_SCI  # import différé, comme dans _scenario
        hypotheses += HYPOTHESES_SCI
    return {
        "annee_revenus": annee,
        "tmi": tmi,
        "tmi_source": tmi_source,
        "hypotheses": hypotheses,
        "scenarios": {nom: _scenario(bien, nom, params, tmi, annee, contexte_foyer) for nom in SCENARIOS},
    }


PARAMS_FISCAUX = [
    "fiscal.deficit_foncier.plafond_revenu_global", "fiscal.foncier.frais_emprunt_dans_bloc_interets",
    "fiscal.micro_foncier.seuil_revenus_bruts_foyer", "fiscal.micro_foncier.abattement",
    "fiscal.micro_bic.abattement_minimum", "fiscal.prelevements_sociaux.revenus_fonciers",
    "fiscal.prelevements_sociaux.bic_lmnp", "fiscal.lmnp.seuil_lmp_recettes", "fiscal.lmnp.composants",
    "fiscal.lmnp.duree_travaux_amelioration", "fiscal.lmnp.duree_mobilier", "fiscal.lmnp.frais_acquisition",
    "fiscal.lmnp.ordre_imputation",
]
PARAMS_SCI = [
    "fiscal.is.taux_reduit", "fiscal.is.taux_normal", "fiscal.is.limite_taux_reduit_12_mois",
    "fiscal.sci_is.taux_max_interets_cca", "fiscal.sci_is.deficit_imputation_max",
    "fiscal.prelevements_sociaux.revenus_placement", "fiscal.dividendes.pfu_ir", "fiscal.dividendes.abattement_bareme",
    "fiscal.dividendes.csg_deductible",
]


def params_fiscaux_utilises(bien: dict, annee: int | None, params: dict) -> list[str]:
    chemins = list(PARAMS_FISCAUX)
    if f"revenus_{annee}" in params["fiscal"]["micro_bic"]:
        chemins.append(f"fiscal.micro_bic.revenus_{annee}")
    if "renovation_energetique" in bien:
        chemins += ["fiscal.deficit_foncier.plafond_majore_renovation", "fiscal.deficit_foncier.renovation_classes_avant",
                    "fiscal.deficit_foncier.renovation_classes_apres",
                    "fiscal.deficit_foncier.renovation_annees_paiement"]
    if "bailleur_prive" in bien:
        chemins += [f"fiscal.bailleur_prive.{c}" for c in
                    ("taux", "plafond_annuel_foyer", "part_foncier", "travaux_min_j", "fenetre_acquisition",
                     "loyer_plafond_intermediaire_2026", "coefficient_surface", "zones")]
    if "sci" in bien:
        chemins += PARAMS_SCI
    return chemins
