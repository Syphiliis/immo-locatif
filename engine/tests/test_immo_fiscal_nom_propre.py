"""Fiscalité en nom propre du moteur immo (`src/immo/fiscal_nom_propre.py`) et exception HCSF 27 ans.

Biens et foyers FICTIFS uniquement : `bien_fictif.json`,
`bien_fictif_bailleur_prive.json`, `bien_fictif_differe_27ans.json`, et un foyer fictif
(R_e 24 000, I_e 8 000, C_e 5 000). Foyer fictif de référence : aucune de ses valeurs ne vient du dépôt ; le test ne lit aucune source réelle.

Les valeurs attendues (TABLEAU) sont celles de référence, calculées  le 03/10/2026 :
scénario `realiste`, année 1, TMI 0,14 (fictive) fournie en entrée, ligne 250 de la 2044 = intérêts + assurance.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import analyser, fiscal_nom_propre as fnp, indicateurs, modele  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "immo"
BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_BAILLEUR_PRIVE = biens_test.chemin("bien_fictif_bailleur_prive.json")
BIEN_DIFFERE_27 = biens_test.chemin("bien_fictif_differe_27ans.json")

FISCAL_FICTIF = {"tmi": 0.14, "annee_revenus": 2026}
# Foyer FICTIF de référence : revenus fonciers existants, intérêts, autres charges.
FOYER_FICTIF = {"R": 24000.0, "I": 8000.0, "C": 5000.0}
# Contexte d'adaptateur FICTIF, à la forme de `foyer.contexte()`. Foyer fictif de référence : aucune de ses valeurs ne vient du dépôt ; le test ne lit aucune source réelle.
CONTEXTE_FICTIF = {
    "annee": 2026,
    "tmi": 0.41,
    "revenus_fonciers_bruts_existants": 24000.0,
    "a_un_bien_ij": False,
    "foncier_existant": {"R": 24000.0, "I": 8000.0, "C": 5000.0, "report_disponible": 0.0},
    "mensualites": {"actuelle": 1000.0, "future": 1500.0},
    "revenus_activite_mensuels": 4000.0,
    "loyers_existants_mensuels": 1000.0,
}


@pytest.fixture()
def params():
    """params.json, plus la zone locative de la commune FICTIVE 99001 (surcharge de test)."""
    return modele.charger_params(local=ROOT / "tests" / "fixtures" / "immo" / "params_local_zone_fictive.json")


def _bien(chemin=BIEN_FICTIF, **ajouts) -> dict:
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    brut.setdefault("fiscal", dict(FISCAL_FICTIF))
    brut.update(ajouts)
    return modele.valider_bien(brut)


def _regimes(bien, params, scenario="realiste", contexte=None):
    return analyser(bien, params, contexte_foyer=contexte)["fiscalite"]["scenarios"][scenario]["regimes"]


@pytest.fixture()
def ctx(params):
    return SimpleNamespace(params=params,
                           r=_regimes(_bien(), params),
                           r_sans_travaux=_regimes(_bien(travaux_deductibles_foncier=0), params),
                           r_bp=_regimes(_bien(BIEN_BAILLEUR_PRIVE), params),
                           assiette=analyser(_bien(), params)["fiscalite"]["scenarios"]["realiste"]["assiette"])


def _impot_de(resultat_foncier: dict) -> float:
    return fnp.impot(resultat_foncier["imposable"], resultat_foncier["deficit_impute_global"], 0.14, 0.172)["total"]


def _effet_fictif(params):
    bien = {"R": 14352.0, "I": 8413.96447492082 + 690.0, "C": 32280.0}
    return fnp.effet_foyer(FOYER_FICTIF, bien, 10700, 10700, 0.14, 0.172)


# --------------------------------------------------------------------------------------------
# 1. Tableau des valeurs attendues de référence (18 lignes).
# --------------------------------------------------------------------------------------------

TABLEAU = [
    # (n° de ligne, nom, valeur calculée, attendu, tolérance absolue)
    (1, "R_loyers_encaisses", lambda c: c.assiette["loyers_encaisses"], 14352.00, 0.01),
    (2, "interets_an1", lambda c: c.assiette["interets_an1"], 8413.96, 0.01),
    (2, "assurance_an1", lambda c: c.assiette["assurance_an1"], 690.00, 0.01),
    (3, "foncier_travaux_resultat", lambda c: c.r["foncier_reel"]["resultat"], -27031.96, 0.01),
    (4, "foncier_travaux_deficit_impute", lambda c: c.r["foncier_reel"]["deficit_impute_global"], 10700.00, 0.01),
    (4, "foncier_travaux_report", lambda c: c.r["foncier_reel"]["report_foncier"], 16331.96, 0.01),
    (5, "foncier_travaux_impot", lambda c: c.r["foncier_reel"]["impot_total"], -1498.00, 0.01),
    (6, "foncier_sans_travaux_resultat", lambda c: c.r_sans_travaux["foncier_reel"]["resultat"], 2968.04, 0.01),
    (6, "foncier_sans_travaux_ir", lambda c: c.r_sans_travaux["foncier_reel"]["ir"], 415.53, 0.01),
    (6, "foncier_sans_travaux_ps", lambda c: c.r_sans_travaux["foncier_reel"]["ps"], 510.50, 0.01),
    (7, "micro_foncier_imposable", lambda c: c.r["micro_foncier"]["imposable"], 10046.40, 0.01),
    (7, "micro_foncier_ir", lambda c: c.r["micro_foncier"]["ir"], 1406.50, 0.01),
    (7, "micro_foncier_ps", lambda c: c.r["micro_foncier"]["ps"], 1727.98, 0.01),
    (8, "micro_bic_imposable", lambda c: c.r["lmnp_micro_bic"]["imposable"], 7176.00, 0.01),
    (8, "micro_bic_ir", lambda c: c.r["lmnp_micro_bic"]["ir"], 1004.64, 0.01),
    (8, "micro_bic_ps_18_6", lambda c: c.r["lmnp_micro_bic"]["ps"], 1334.74, 0.01),
    (9, "lmnp_amortissement_bati", lambda c: c.r["lmnp_reel"]["amortissements"]["bati"], 6145.65, 0.01),
    (9, "lmnp_amortissement_travaux", lambda c: c.r["lmnp_reel"]["amortissements"]["travaux"], 2000.00, 0.01),
    (10, "lmnp_resultat_avant_amortissement",
     lambda c: c.r["lmnp_reel"]["resultat_avant_amortissement"], 2968.04, 0.01),
    (10, "lmnp_amortissement_deduit", lambda c: c.r["lmnp_reel"]["amortissement_deduit"], 2968.04, 0.01),
    (10, "lmnp_ard_reporte", lambda c: c.r["lmnp_reel"]["ard_reporte"], 5177.62, 0.01),
    (10, "lmnp_resultat_fiscal", lambda c: c.r["lmnp_reel"]["imposable"], 0.00, 0.01),
    (11, "bailleur_prive_base", lambda c: c.r_bp["bailleur_prive"]["base_amortissable"], 208000.00, 0.01),
    (11, "bailleur_prive_amortissement", lambda c: c.r_bp["bailleur_prive"]["amortissement"], 6240.00, 0.01),
    (12, "plafond_coefficient", lambda c: c.r_bp["bailleur_prive"]["coefficient_surface"], 1.02, 1e-4),
    (12, "plafond_m2", lambda c: c.r_bp["bailleur_prive"]["loyer_plafond_m2"], 12.0360, 1e-4),
    (12, "plafond_loyer_mensuel", lambda c: c.r_bp["bailleur_prive"]["loyer_plafond_mensuel"], 722.16, 1e-4),
    (14, "foyer_fictif_impot_seul", lambda c: _effet_fictif(c.params)["impot_foyer_seul"], 3432.00, 0.01),
    (14, "foyer_fictif_impot_avec_bien", lambda c: _effet_fictif(c.params)["impot_foyer_avec_bien"], -1498.00, 0.01),
    (15, "effet_marginal_du_bien", lambda c: _effet_fictif(c.params)["effet_marginal"], -4930.00, 0.01),
    (15, "effet_du_bien_seul",
     lambda c: _impot_de(fnp.foncier_reel(14352.0, 8413.96447492082 + 690.0, 32280.0, 10700)), -1498.00, 0.01),
    (16, "agrege_deficit_impute", lambda c: _effet_fictif(c.params)["deficit_impute_global"], 10700.00, 0.01),
    (16, "agrege_report_sortant", lambda c: _effet_fictif(c.params)["report_sortant"], 5331.96, 0.01),
    (17, "report_entrant_imposable",
     lambda c: fnp.foncier_reel(14352.0, 9103.96447492082, 2280.0, 10700, 20000.0)["imposable"], 0.00, 0.01),
    (17, "report_entrant_report_sortant",
     lambda c: fnp.foncier_reel(14352.0, 9103.96447492082, 2280.0, 10700, 20000.0)["report_sortant"],
     17031.96, 0.01),
    (17, "report_entrant_impot",
     lambda c: _impot_de(fnp.foncier_reel(14352.0, 9103.96447492082, 2280.0, 10700, 20000.0)), 0.00, 0.01),
]
LIGNES_TESTEES_HORS_TABLEAU = {13, 18}  # inéligibilité j (raison) et HCSF 27 ans (booléens) : tests dédiés


@pytest.mark.parametrize("attendu,tolerance,calcul",
                         [pytest.param(a, t, f, id=f"L{n:02d}_{nom}") for n, nom, f, a, t in TABLEAU])
def test_tableau_de_reference(ctx, calcul, attendu, tolerance):
    assert calcul(ctx) == pytest.approx(attendu, abs=tolerance)


def test_tableau_couvre_les_18_lignes():
    """Couverture comptée : les 18 lignes du tableau de référence ont chacune au moins un test."""
    assert {n for n, *_ in TABLEAU} | LIGNES_TESTEES_HORS_TABLEAU == set(range(1, 19))


def test_l13_bailleur_prive_j_inelegible_si_travaux_inferieurs_a_30_pct_du_prix(params):
    r = _regimes(_bien(BIEN_BAILLEUR_PRIVE, travaux=30000), params)["bailleur_prive"]
    assert r["eligible"] is False
    assert any("travaux < 30 % du prix" in raison for raison in r["raisons"])
    assert r["impot_total"] is None


def test_l18_hcsf_27_ans_conforme_avec_differe_et_travaux_10_pct(params):
    bien = modele.charger_bien(BIEN_DIFFERE_27)
    h = indicateurs.conformite_hcsf(bien, "realiste", params)
    assert bien["travaux"] / 245637 == pytest.approx(0.1221, abs=1e-4)
    assert h["duree_conforme"] is True
    assert h["exception_differe_27_ans"] is True


def test_l18_hcsf_324_mois_sans_differe_non_conforme(params):
    bien = modele.charger_bien(BIEN_DIFFERE_27)
    bien["financement"]["differe"] = {"type": "aucun", "mois": 0}
    h = indicateurs.conformite_hcsf(bien, "realiste", params)
    assert h["duree_conforme"] is False
    assert h["conforme"] is False


# --------------------------------------------------------------------------------------------
# 2. Gardes : chaque règle prouvée dans les deux sens.
# --------------------------------------------------------------------------------------------

def test_r1_le_revenu_brut_compense_d_abord_les_interets(params):
    """Ordre d'imputation du foncier réel, §110 : la part du déficit née des intérêts (4 000) se reporte ; les autres charges (500), que plus
    aucun revenu ne compense, s'imputent sur le revenu global."""
    r = fnp.foncier_reel(1000.0, 5000.0, 500.0, 10700)
    assert r["deficit_impute_global"] == pytest.approx(500.0)
    assert r["report_sortant"] == pytest.approx(4000.0)
    r = fnp.foncier_reel(1000.0, 5000.0, 0.0, 10700)  # déficit né des seuls intérêts : rien sur le revenu global
    assert r["deficit_impute_global"] == 0.0


def test_r1_charges_hors_interets_imputees_au_dela_du_revenu_net_d_interets(params):
    r = fnp.foncier_reel(10000.0, 4000.0, 9000.0, 10700)
    assert r["deficit_impute_global"] == pytest.approx(3000.0)  # 9 000 - (10 000 - 4 000)
    assert r["report_sortant"] == pytest.approx(0.0)


def test_r1_plafond_10700_borne_l_imputation(params):
    r = fnp.foncier_reel(0.0, 0.0, 50000.0, 10700)
    assert r["deficit_impute_global"] == 10700
    assert r["report_sortant"] == pytest.approx(39300.0)


def test_effet_foyer_et_report_agreges_suivent_l_ordre_r1(params):
    """Discriminant 1 : imputer sur C - R (sans l'ordre d'imputation) change l'agrégé du foyer fictif."""
    e = _effet_fictif(params)
    assert e["deficit_impute_global"] == pytest.approx(10700.0, abs=0.01)
    assert e["report_sortant"] == pytest.approx(5331.96, abs=0.01)
    assert e["effet_marginal"] == pytest.approx(-4930.00, abs=0.01)


def test_provision_capex_n_est_pas_une_charge_deductible(params):
    bien = _bien()
    sans = _regimes(bien, params)["foncier_reel"]["resultat"]
    bien["exploitation"]["capex_taux"] = 0.0
    assert _regimes(bien, params)["foncier_reel"]["resultat"] == pytest.approx(sans)


def test_impot_le_deficit_impute_ne_reduit_que_l_ir():
    i = fnp.impot(0.0, 10700.0, 0.14, 0.172)
    assert i["ir"] == pytest.approx(-1498.0)
    assert i["ps"] == 0.0


def test_plafond_deficit_10700_par_defaut(params):
    p = fnp.plafond_deficit(None, 2026, params)
    assert p["plafond"] == 10700
    assert p["majore"] is False


def test_plafond_deficit_majore_renovation_energetique_e_vers_c(params):
    p = fnp.plafond_deficit({"classe_avant": "F", "classe_apres": "C", "depenses": 8000}, 2026, params)
    assert p["majore"] is True
    assert p["plafond"] == 18700
    p = fnp.plafond_deficit({"classe_avant": "G", "classe_apres": "D", "depenses": 30000}, 2027, params)
    assert p["plafond"] == 21400


@pytest.mark.parametrize("renov,annee,raison", [
    ({"classe_avant": "D", "classe_apres": "B", "depenses": 8000}, 2026, "classe avant"),
    ({"classe_avant": "F", "classe_apres": "E", "depenses": 8000}, 2026, "classe après"),
    ({"classe_avant": "F", "classe_apres": "C", "depenses": 8000}, 2028, "2027"),
])
def test_plafond_deficit_reste_10700_si_une_condition_manque(params, renov, annee, raison):
    p = fnp.plafond_deficit(renov, annee, params)
    assert p["plafond"] == 10700 and p["majore"] is False
    assert any(raison in r for r in p["raisons"])


# Foyer FICTIF déjà au plafond de 10 700 € sans le bien : déficit imputable 30 000 - (10 000 - 2 000) = 22 000.
FOYER_AU_PLAFOND = {"R": 10000.0, "I": 2000.0, "C": 30000.0, "report_disponible": 0.0}
RENOVATION_F_VERS_D = {"classe_avant": "F", "classe_apres": "D", "depenses": 15000}


def test_effet_foyer_le_foyer_seul_garde_son_propre_plafond():
    """Discriminant : la majoration (CGI 156 I-3°, à concurrence des dépenses de rénovation énergétique du foyer) naît
    des travaux du bien ; le foyer seul, sans ces travaux, reste à 10 700 €. Avec un plafond commun, l'effet serait 0."""
    bien = {"R": 5000.0, "I": 1000.0, "C": 25000.0}
    e = fnp.effet_foyer(FOYER_AU_PLAFOND, bien, 10700, 21400, 0.14, 0.172)
    assert e["plafond_foyer_seul"] == 10700 and e["plafond_foyer_avec_bien"] == 21400
    assert e["deficit_impute_global"] == 21400
    assert e["effet_marginal"] == pytest.approx(-(21400 - 10700) * 0.14)  # -1 498
    commun = fnp.effet_foyer(FOYER_AU_PLAFOND, bien, 21400, 21400, 0.14, 0.172)
    assert commun["effet_marginal"] == pytest.approx(0.0)


def test_contexte_foyer_renovation_du_bien_majore_le_seul_foyer_avec_bien(params):
    """Bout en bout : foyer existant au plafond, bien en rénovation F vers D ; hypothèse du foyer seul affichée."""
    contexte = {**CONTEXTE_FICTIF, "foncier_existant": FOYER_AU_PLAFOND}
    f = analyser(_bien(renovation_energetique=RENOVATION_F_VERS_D), params, contexte_foyer=contexte)["fiscalite"]
    e = f["scenarios"]["realiste"]["regimes"]["foncier_reel"]["effet_foyer"]
    assert e["plafond_foyer_seul"] == 10700 and e["plafond_foyer_avec_bien"] == 21400
    assert e["effet_marginal"] == pytest.approx(-(21400 - 10700) * CONTEXTE_FICTIF["tmi"], abs=0.01)  # -4 387 à 41 %
    assert any("foyer seul" in h and "10 700" in h for h in f["hypotheses"])


def test_sans_contexte_foyer_pas_d_hypothese_du_foyer_seul(params):
    """Discriminant : l'hypothèse du plafond du foyer seul n'existe que si un contexte foyer est fourni."""
    assert not any("foyer seul" in h for h in analyser(_bien(), params)["fiscalite"]["hypotheses"])


def test_micro_foncier_eligible_pour_le_bien_seul(params):
    m = fnp.micro_foncier(14352.0, 0.0, False, params)
    assert m["eligible"] is True
    assert m["imposable"] == pytest.approx(10046.40, abs=0.01)


def test_micro_foncier_ineligible_si_le_foyer_depasse_15000(params):
    """Discriminant 2 : le foyer fictif a déjà 24 000 € de revenus fonciers bruts."""
    m = fnp.micro_foncier(14352.0, 24000.0, False, params)
    assert m["eligible"] is False
    assert any("15 000" in r for r in m["raisons"])
    assert m["imposable"] is None


def test_micro_foncier_ineligible_en_contexte_foyer_qui_depasse_15000(params):
    r = _regimes(_bien(), params, contexte=CONTEXTE_FICTIF)["micro_foncier"]
    assert r["eligible"] is False
    assert r["impot_total"] is None


def test_micro_foncier_ineligible_si_le_foyer_a_un_bien_bailleur_prive(params):
    m = fnp.micro_foncier(1000.0, 0.0, True, params)
    assert m["eligible"] is False
    assert any("bailleur privé" in r for r in m["raisons"])


def test_micro_bic_plafond_2025_77700_et_2026_83600(params):
    assert fnp.micro_bic(80000.0, "meuble_longue_duree", 2025, params)["eligible"] is False
    assert fnp.micro_bic(80000.0, "meuble_longue_duree", 2026, params)["eligible"] is True
    assert fnp.micro_bic(83601.0, "meuble_longue_duree", 2026, params)["eligible"] is False


def test_micro_bic_tourisme_non_classe_30_pct_et_minimum_305(params):
    m = fnp.micro_bic(10000.0, "tourisme_non_classe", 2026, params)
    assert m["imposable"] == pytest.approx(7000.0)
    m = fnp.micro_bic(500.0, "meuble_longue_duree", 2026, params)
    assert m["abattement"] == 305
    assert m["imposable"] == pytest.approx(195.0)


def test_micro_bic_annee_non_parametree_est_une_absence(params):
    m = fnp.micro_bic(10000.0, "meuble_longue_duree", 2031, params)
    assert m["eligible"] is False and m["evaluable"] is False


def test_lmnp_reel_deficit_reporte_et_tout_l_amortissement_reporte():
    r = fnp.lmnp_reel(5000.0, 7000.0, 3000.0, 0.0)
    assert r["deficit_sortant"] == pytest.approx(2000.0)
    assert r["amortissement_deduit"] == 0.0
    assert r["ard_reporte"] == pytest.approx(3000.0)
    assert r["imposable"] == 0.0


def test_lmnp_reel_deficits_anterieurs_imputes_apres_l_amortissement():
    r = fnp.lmnp_reel(10000.0, 4000.0, 4000.0, 5000.0)  # pre 6 000, amort 4 000, reste 2 000
    assert r["amortissement_deduit"] == pytest.approx(4000.0)
    assert r["deficit_impute"] == pytest.approx(2000.0)
    assert r["deficit_sortant"] == pytest.approx(3000.0)
    assert r["imposable"] == 0.0


def test_lmnp_reel_ps_a_18_6_pct(params):
    bien = _bien()
    bien["mobilier"] = 0
    bien["scenarios"]["realiste"]["loyer_mensuel_hc"] = 3000
    r = _regimes(bien, params)["lmnp_reel"]
    assert r["imposable"] > 0
    assert r["ps"] == pytest.approx(r["imposable"] * 0.186)


def test_lmnp_travaux_d_entretien_sont_une_charge_pas_un_amortissement(params):
    r = _regimes(_bien(travaux_nature="entretien"), params)["lmnp_reel"]
    assert r["amortissements"]["travaux"] == 0.0
    assert r["resultat_avant_amortissement"] == pytest.approx(2968.04 - 30000, abs=0.01)


def test_amortissements_composants_mobilier_sur_7_ans(params):
    a = fnp.amortissements_composants(100000.0, 0.0, "amelioration", 7000.0, params)
    assert a["mobilier"] == pytest.approx(1000.0)
    assert a["bati"] == pytest.approx(2850.0)


def test_bailleur_prive_loyer_retenu_plafonne(ctx):
    """Discriminant 3 : le loyer du scénario (1 300) dépasse le plafond B1 (722,16)."""
    r = ctx.r_bp["bailleur_prive"]
    assert r["eligible"] is True
    assert r["loyer_retenu"] == pytest.approx(722.16, abs=1e-4)


def test_bailleur_prive_recalcule_sur_le_loyer_retenu(ctx, params):
    r = ctx.r_bp["bailleur_prive"]
    R = 722.16 * 12 * 0.92
    assert r["loyers_encaisses"] == pytest.approx(R, abs=0.01)
    bien = _bien(BIEN_BAILLEUR_PRIVE)
    plein = analyser(bien, params)["scenarios"]["realiste"]["indicateurs"]["cash_flow_mensuel_avant_impot"]
    assert r["cash_flow_mensuel_net_net"] < plein


def test_bailleur_prive_loyer_sous_le_plafond_inchange(params):
    bien = _bien(BIEN_BAILLEUR_PRIVE)
    bien["scenarios"]["realiste"]["loyer_mensuel_hc"] = 700
    assert _regimes(bien, params)["bailleur_prive"]["loyer_retenu"] == 700


def test_bailleur_prive_amortissement_plafonne_a_8000(params):
    bien = _bien(BIEN_BAILLEUR_PRIVE, prix_net_vendeur=400000, travaux=150000)
    assert _regimes(bien, params)["bailleur_prive"]["amortissement"] == 8000


def test_bailleur_prive_mode_prudent_retenu_et_ecart_droit_commun_affiche(ctx):
    r = ctx.r_bp["bailleur_prive"]
    assert r["mode_deficit"] == "prudent"
    assert set(r["droit_commun"]) >= {"impot_total", "deficit_impute_global", "report_foncier"}
    assert r["ecart_droit_commun_vs_prudent"] == pytest.approx(
        r["droit_commun"]["impot_total"] - r["impot_total"])
    assert r["ecart_droit_commun_vs_prudent"] <= 0


@pytest.mark.parametrize("modif,raison", [
    ({"immeuble_collectif": False}, "collectif"),
    ({"date_acquisition": "2026-02-20"}, "fenêtre"),
    ({"date_acquisition": "2029-01-01"}, "fenêtre"),
])
def test_bailleur_prive_conditions_d_eligibilite(params, modif, raison):
    r = _regimes(_bien(BIEN_BAILLEUR_PRIVE, **modif), params)["bailleur_prive"]
    assert r["eligible"] is False
    assert any(raison in x for x in r["raisons"]), r["raisons"]


@pytest.mark.parametrize("champ", ["surface_habitable", "code_insee", "immeuble_collectif", "date_acquisition",
                                   "bailleur_prive"])
def test_bailleur_prive_non_evaluable_sans_ses_entrees(params, champ):
    brut = json.loads(BIEN_BAILLEUR_PRIVE.read_text(encoding="utf-8"))
    del brut[champ]
    r = _regimes(modele.valider_bien(brut), params)["bailleur_prive"]
    assert r["evaluable"] is False and r["eligible"] is False
    assert any(champ in x for x in r["raisons"])


def test_bailleur_prive_social_non_evaluable_faute_de_plafond_de_loyer_parametre(params):
    r = _regimes(_bien(BIEN_BAILLEUR_PRIVE, bailleur_prive={"regime": "j", "location": "social"}),
                 params)["bailleur_prive"]
    assert r["evaluable"] is False


def test_bailleur_prive_signale_les_conditions_non_modelisees(ctx):
    r = ctx.r_bp["bailleur_prive"]
    assert any("réhabilitation lourde" in x for x in r["raisons"])


# --------------------------------------------------------------------------------------------
# 3. HCSF 27 ans : chaque condition de l'exception.
# --------------------------------------------------------------------------------------------

def test_hcsf_324_mois_avec_differe_mais_amortissement_superieur_a_300_non_conforme(params):
    bien = modele.charger_bien(BIEN_DIFFERE_27)
    bien["financement"]["differe"] = {"type": "partiel", "mois": 12}
    assert indicateurs.conformite_hcsf(bien, "realiste", params)["duree_conforme"] is False


def test_hcsf_324_mois_travaux_sous_10_pct_non_conforme_sauf_vefa(params):
    bien = modele.charger_bien(BIEN_DIFFERE_27)
    bien["travaux"] = 20000  # 20 000 / 235 637 < 10 %
    assert indicateurs.conformite_hcsf(bien, "realiste", params)["duree_conforme"] is False
    bien["vefa"] = True
    assert indicateurs.conformite_hcsf(bien, "realiste", params)["duree_conforme"] is True


def test_hcsf_au_dela_de_324_mois_jamais_conforme(params):
    bien = modele.charger_bien(BIEN_DIFFERE_27)
    bien["financement"]["duree_mois"] = 325
    bien["financement"]["differe"] = {"type": "partiel", "mois": 25}
    assert indicateurs.conformite_hcsf(bien, "realiste", params)["duree_conforme"] is False


def test_hcsf_exception_signale_la_condition_de_differe_analogue_au_decalage(params):
    h = indicateurs.conformite_hcsf(modele.charger_bien(BIEN_DIFFERE_27), "realiste", params)
    assert "décalage" in h["exception_note"]


# --------------------------------------------------------------------------------------------
# 4. Contrat de sortie `fiscalite`.
# --------------------------------------------------------------------------------------------

REGIMES = {"micro_foncier", "foncier_reel", "lmnp_micro_bic", "lmnp_reel", "bailleur_prive", "sci_ir", "sci_is"}
CLES_REGIME = {"eligible", "raisons", "imposable", "ir", "ps", "impot_total", "cash_flow_mensuel_net_net",
               "rendement_net_net"}


def test_contrat_fiscalite_trois_scenarios_cinq_regimes(params):
    f = analyser(_bien(), params)["fiscalite"]
    assert {"annee_revenus", "tmi", "tmi_source", "hypotheses", "scenarios"} <= set(f)
    assert f["tmi"] == 0.14 and f["tmi_source"] == "entree:fiscal.tmi"
    assert set(f["scenarios"]) == {"pessimiste", "realiste", "optimiste"}
    for s in f["scenarios"].values():
        assert set(s["regimes"]) == REGIMES
        for nom, r in s["regimes"].items():
            assert CLES_REGIME <= set(r), nom


def test_contrat_details_propres_a_chaque_regime(ctx):
    assert {"resultat", "deficit_impute_global", "report_foncier"} <= set(ctx.r["foncier_reel"])
    assert {"amortissement_dispo", "amortissement_deduit", "ard_reporte"} <= set(ctx.r["lmnp_reel"])
    assert {"loyer_plafond_mensuel", "loyer_retenu", "amortissement",
            "ecart_droit_commun_vs_prudent"} <= set(ctx.r_bp["bailleur_prive"])
    assert "effet_foyer" not in ctx.r["foncier_reel"]


def test_cash_flow_net_net_et_rendement_net_net(params):
    bien = _bien()
    sortie = analyser(bien, params)
    r = sortie["fiscalite"]["scenarios"]["realiste"]["regimes"]["foncier_reel"]
    cf = sortie["scenarios"]["realiste"]["indicateurs"]["cash_flow_mensuel_avant_impot"]
    assert r["cash_flow_mensuel_net_net"] == pytest.approx(cf - r["impot_total"] / 12)
    rn = sortie["scenarios"]["realiste"]["indicateurs"]["rendement_net"]
    assert r["rendement_net_net"] == pytest.approx(rn - r["impot_total"] / sortie["acquisition"]["cout_total"])


def test_hypotheses_listent_les_points_a_a_e(params):
    h = " ".join(analyser(_bien(), params)["fiscalite"]["hypotheses"])
    for marque in ("(a)", "(b)", "(c)", "(d)", "(e)"):
        assert marque in h
    assert "20 €" in h  # (e) forfait de gestion non modélisé
    assert "travaux_deductibles_foncier" in h


H_MICRO_FONCIER_BIEN_SEUL = ("Micro-foncier évalué pour le bien seul : revenus fonciers existants du foyer et "
                             "statut i/j non fournis (option --foyer).")
H_FOYER_JSON = ("Foyer lu dans foyer.json : revenus fonciers existants, statut du bailleur privé (a_un_bien_ij) et foncier "
                "existant (R, I, C) tels que déclarés par l'investisseur, pour l'année 2026.")
H_CONDITION_LOCATION = ("Imputation du déficit foncier sur le revenu global sous condition de louer le bien jusqu'au "
                        "31/12 de la 3e année suivant l'imputation (BOI-RFPI-BASE-30-20 §340).")


def test_hypotheses_sans_contexte_foyer_micro_foncier_pour_le_bien_seul(params):
    h = analyser(_bien(), params)["fiscalite"]["hypotheses"]
    assert H_MICRO_FONCIER_BIEN_SEUL in h
    assert H_CONDITION_LOCATION in h
    assert H_FOYER_JSON not in h


def test_hypotheses_avec_contexte_foyer_lu_dans_foyer_json(params):
    h = analyser(_bien(), params, contexte_foyer=CONTEXTE_FICTIF)["fiscalite"]["hypotheses"]
    assert H_FOYER_JSON in h
    assert H_CONDITION_LOCATION in h
    assert H_MICRO_FONCIER_BIEN_SEUL not in h


def test_sans_tmi_les_regimes_sont_non_evaluables_mais_presents(params):
    brut = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    f = analyser(modele.valider_bien(brut), params)["fiscalite"]
    assert f["tmi"] is None and f["tmi_source"] is None
    r = f["scenarios"]["realiste"]["regimes"]["foncier_reel"]
    assert r["impot_total"] is None and r["ir"] is None
    assert any("tmi" in x for x in r["raisons"])
    assert r["resultat"] == pytest.approx(-27031.96, abs=0.01)


def test_contexte_foyer_donne_l_effet_foyer_et_la_tmi(params):
    f = analyser(_bien(), params, contexte_foyer=CONTEXTE_FICTIF)["fiscalite"]
    assert f["tmi_source"] == "foyer.json:tmi"
    e = f["scenarios"]["realiste"]["regimes"]["foncier_reel"]["effet_foyer"]
    # même calcul que la ligne 15 du tableau (TMI 14 % : -4 930), ici à la TMI 41 % du contexte fictif
    assert e["effet_marginal"] == pytest.approx(-10789.00, abs=0.01)
    assert e["report_sortant"] == pytest.approx(5331.96, abs=0.01)


def test_contexte_foyer_taux_d_effort_sur_la_mensualite_future(params):
    """Discriminant 5 (forme pure) : mensualité future 1 500, pas l'actuelle 1 000 ; loyers existants pondérés."""
    bien = _bien()
    del bien["foyer"]
    sortie = analyser(bien, params, contexte_foyer=CONTEXTE_FICTIF)
    from src.immo.financement import assurance_mensuelle, mensualite_amortissement
    loyer = bien["scenarios"]["realiste"]["loyer_mensuel_hc"]
    attendu = (1500 + mensualite_amortissement(bien) + assurance_mensuelle(bien)) / (4000 + 0.7 * 1000 + 0.7 * loyer)
    assert sortie["hcsf"]["taux_effort"] == pytest.approx(attendu, abs=1e-12)
    assert any("mensualites.actuelle" in h for h in sortie["fiscalite"]["hypotheses"])
    assert "hcsf.ponderation_loyers_defaut" in sortie["params_utilises"]


def test_contexte_foyer_meme_ponderation_pour_loyers_existants_et_nouveau_loyer(params):
    """Pondération 0,5 de foyer.json → 0,5 sur les loyers existants ET sur le loyer du bien étudié ; celle écrite
    dans le bien (0,7) est ignorée."""
    bien = _bien()
    assert bien["foyer"]["ponderation_loyers"] == 0.7
    sortie = analyser(bien, params, contexte_foyer={**CONTEXTE_FICTIF, "ponderation_loyers": 0.5})
    from src.immo.financement import assurance_mensuelle, mensualite_amortissement
    loyer = bien["scenarios"]["realiste"]["loyer_mensuel_hc"]
    attendu = (1500 + mensualite_amortissement(bien) + assurance_mensuelle(bien)) / (4000 + 0.5 * 1000 + 0.5 * loyer)
    assert sortie["hcsf"]["taux_effort"] == pytest.approx(attendu, abs=1e-12)
    assert sortie["hcsf"]["entrees_foyer"]["revenus_nets_mensuels"] == pytest.approx(4000 + 0.5 * 1000)
    assert "hcsf.ponderation_loyers_defaut" not in sortie["params_utilises"]  # la pondération de foyer.json prime


def test_contexte_foyer_expose_les_entrees_du_taux_d_effort(params):
    """C7 : bloc `entrees_foyer` auditable ; absent sans contexte du foyer réel."""
    h = analyser(_bien(), params, contexte_foyer=CONTEXTE_FICTIF)["hcsf"]
    e = h["entrees_foyer"]
    assert set(e) == {"revenus_nets_mensuels", "mensualites_existantes", "ponderation_loyers", "source"}
    assert e["source"] == "foyer.json"
    assert e["mensualites_existantes"] == 1500.0
    assert e["ponderation_loyers"] == 0.7
    assert e["revenus_nets_mensuels"] == pytest.approx(4000 + 0.7 * 1000)
    assert "entrees_foyer" not in analyser(_bien(), params)["hcsf"]


def test_analyser_ne_modifie_pas_le_bien(params):
    bien = _bien(BIEN_BAILLEUR_PRIVE)
    avant = copy.deepcopy(bien)
    analyser(bien, params, contexte_foyer=CONTEXTE_FICTIF)
    assert bien == avant


def test_params_utilises_inclut_les_parametres_fiscaux(params):
    pu = analyser(_bien(), params)["params_utilises"]
    assert "fiscal.deficit_foncier.plafond_revenu_global" in pu
    assert "fiscal.prelevements_sociaux.revenus_fonciers" in pu


# --------------------------------------------------------------------------------------------
# 5. Entrées optionnelles nouvelles et params.json.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("champ,valeur", [
    ("surface_habitable", 0), ("code_insee", 99001), ("immeuble_collectif", "oui"),
    ("date_acquisition", "01/06/2026"), ("travaux_deductibles_foncier", -1), ("travaux_nature", "luxe"),
    ("renovation_energetique", {"classe_avant": "H", "classe_apres": "C", "depenses": 1}),
    ("bailleur_prive", {"regime": "k", "location": "intermediaire"}),
    ("bailleur_prive", {"regime": "j", "location": "libre"}),
    ("vefa", 1), ("fiscal", {"tmi": 1.5}), ("fiscal", {"annee_revenus": "2026"}),
])
def test_entrees_optionnelles_invalides_levent_value_error(champ, valeur):
    brut = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    brut[champ] = valeur
    with pytest.raises(ValueError, match=champ):
        modele.valider_bien(brut)


def _feuilles(noeud, chemin=""):
    if isinstance(noeud, dict):
        if "valeur" in noeud:
            yield chemin, noeud
        else:
            for cle, sous in noeud.items():
                if not cle.startswith("_"):
                    yield from _feuilles(sous, f"{chemin}.{cle}" if chemin else cle)


def test_params_fiscaux_portent_source_date_et_nature():
    brut = json.loads((ROOT / "src" / "immo" / "params.json").read_text(encoding="utf-8"))
    nouveaux = {c: f for c, f in _feuilles(brut)
                if c.startswith("fiscal.") or c in ("hcsf.duree_max_differe_mois", "hcsf.part_travaux_min_differe")}
    assert len(nouveaux) >= 15
    for chemin, f in nouveaux.items():
        assert f["nature"] in ("loi", "doctrine", "pratique"), chemin
        assert f["source"].strip() and f["verifie_le"], chemin
        if f["nature"] == "pratique":
            assert f.get("a_verifier") is True, chemin


def test_params_points_non_verifies_signales_a_verifier(params):
    for chemin in ("fiscal.lmnp.composants", "fiscal.lmnp.duree_travaux_amelioration", "fiscal.lmnp.duree_mobilier",
                   "fiscal.lmnp.frais_acquisition", "fiscal.lmnp.ordre_imputation",
                   "fiscal.foncier.frais_emprunt_dans_bloc_interets"):
        assert modele.parametre(params, chemin).get("a_verifier") is True, chemin


def test_params_hcsf_duree_max_mois_ne_contredit_pas_l_exception_modelisee(params):
    """C1 : la source ne dit plus « exception NON modélisée » (elle l'est : sortie de chaque CLI)."""
    source = modele.parametre(params, "hcsf.duree_max_mois")["source"]
    assert "NON modélisée" not in source
    assert "hcsf.duree_max_differe_mois" in source and "hcsf.part_travaux_min_differe" in source
    assert modele.valeur(params, "hcsf.duree_max_mois") == 300


def test_params_aucune_source_ne_se_dit_non_relue():
    brut = json.loads((ROOT / "src" / "immo" / "params.json").read_text(encoding="utf-8"))
    for chemin, f in _feuilles(brut):
        assert "non relu" not in f.get("source", "").lower(), chemin


@pytest.mark.parametrize("chemin,marques", [
    ("fiscal.micro_foncier.seuil_revenus_bruts_foyer", ("LEGIARTI000048847610", "n'excède pas 15 000 €", "art. 32, 2-c")),
    ("fiscal.micro_foncier.abattement", ("même lecture du 04/10/2026", "abattement de 30 %")),
    ("fiscal.prelevements_sociaux.revenus_fonciers", ("LFSS 2026", "service-public.gouv.fr F2329", "= 17,2 %")),
    ("fiscal.prelevements_sociaux.bic_lmnp", ("LFSS 2026", "service-public.gouv.fr F2329", "10,6 %", "18,6 %")),
    ("fiscal.lmnp.seuil_lmp_recettes", ("LEGIARTI000041468265", "BOI-BIC-CHAMP-40-10-20200205", "23 000 €")),
])
def test_params_sources_loi_relues_le_04_10_2026(params, chemin, marques):
    source = modele.parametre(params, chemin)["source"]
    assert "04/10/2026" in source, chemin
    for marque in marques:
        assert marque in source, (chemin, marque)
