"""Fiscalité de la SCI du moteur immo (`src/immo/fiscal_sci.py`) : SCI à l'IR, SCI à l'IS, distribution.

Biens et foyers FICTIFS uniquement : `bien_fictif.json` (bloc `sci`
ajouté en mémoire) et `bien_fictif_sci_is.json`. Aucune valeur ne vient du dépôt ; le test ne lit aucune
source réelle.

Les valeurs attendues (TABLEAU) sont celles de référence, calculées  le 04/10/2026 sur
main @ 5c48663 ; tolérance 0,01 €, 1e-6 pour les ratios.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import analyser, fiscal_sci as fsci, modele  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "immo"
BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_SCI_IS = biens_test.chemin("bien_fictif_sci_is.json")

# Bloc `sci` FICTIF ajouté à bien_fictif.json : aucun versement, frais incorporés, capital libéré.
SCI_FICTIF = {"regime": "is", "quote_part_foyer": 1.0, "duree_premier_exercice_mois": 12,
              "frais_acquisition": "incorpores", "capital_libere": True, "cca": {"montant": 0, "taux": 0},
              "distribution_annuelle": 0, "remboursement_cca_annuel": 0}
# Contexte d'adaptateur FICTIF, à la forme de `foyer.contexte()` : aucune de ses valeurs ne vient du dépôt.
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
H_O7 = ("IR au taux marginal fixe (tmi) : ni barème, ni décote, ni plafond du quotient familial, ni changement de "
        "tranche. En zone de décote, un euro imposable coûte environ tmi × 1,4525 (coefficient de décote de 45,25 %, "
        "barème 2025) ; un déficit qui fait changer de tranche est surestimé. Même réserve pour l'IR des dividendes "
        "au barème (SCI à l'IS). Contrôle croisé avec OpenFisca.")


@pytest.fixture(scope="module")
def params():
    return modele.charger_params()


def _bien(chemin=BIEN_FICTIF, sans_sci: bool = False, **sci) -> dict:
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    if sans_sci:
        brut.pop("sci", None)
    else:
        brut["sci"] = {**brut.get("sci", SCI_FICTIF), **sci}
    return modele.valider_bien(brut)


def _sortie(bien, params, contexte=None):
    return analyser(bien, params, contexte_foyer=contexte)


def _regimes(bien, params, scenario="realiste"):
    return _sortie(bien, params)["fiscalite"]["scenarios"][scenario]["regimes"]


@pytest.fixture(scope="module")
def ctx(params):
    inc = _sortie(_bien(), params)
    sci = _sortie(_bien(BIEN_SCI_IS), params)
    return SimpleNamespace(
        params=params,
        inc=inc,
        r_inc=inc["fiscalite"]["scenarios"]["realiste"]["regimes"],
        assiette=inc["fiscalite"]["scenarios"]["realiste"]["assiette"],
        r_chg=_regimes(_bien(frais_acquisition="charges"), params),
        r_q05=_regimes(_bien(regime="ir", quote_part_foyer=0.5), params),
        sci=sci,
        r_sci_chg=_regimes(_bien(BIEN_SCI_IS, frais_acquisition="charges"), params),
    )


def _f(c, s):
    """Régimes, assiette et indicateurs d'un scénario de bien_fictif_sci_is.json."""
    return (c.sci["fiscalite"]["scenarios"][s]["regimes"], c.sci["fiscalite"]["scenarios"][s]["assiette"],
            c.sci["scenarios"][s]["indicateurs"])


def _charges_exploitation(c, s):
    r, a, _ = _f(c, s)
    return r["sci_is"]["charges_deductibles"] - a["interets_an1"] - a["assurance_an1"]


def _is(resultat, duree, c):
    return fsci.impot_societes(resultat, duree, c.params)


def _dist(montant, tmi, c):
    return fsci.distribution(montant, 1e9, tmi, 0.0, 0.0, c.params)


# --------------------------------------------------------------------------------------------
# 1. Valeurs attendues de référence : 19 lignes (IS 5, distribution 3, bien_fictif 5, fixture SCI 6).
# --------------------------------------------------------------------------------------------

TABLEAU = [
    # (ligne, nom, valeur calculée, attendu, tolérance absolue)
    ("IS1", "base_15", lambda c: _is(50000, 12, c)["base_taux_reduit"], 42500.00, 0.01),
    ("IS1", "base_25", lambda c: _is(50000, 12, c)["base_taux_normal"], 7500.00, 0.01),
    ("IS1", "impot", lambda c: _is(50000, 12, c)["impot"], 8250.00, 0.01),
    ("IS2", "base_15_18_mois", lambda c: _is(50000, 18, c)["base_taux_reduit"], 50000.00, 0.01),
    ("IS2", "base_25_18_mois", lambda c: _is(50000, 18, c)["base_taux_normal"], 0.00, 0.01),
    ("IS2", "impot_18_mois", lambda c: _is(50000, 18, c)["impot"], 7500.00, 0.01),
    ("IS3", "base_15_6_mois", lambda c: _is(30000, 6, c)["base_taux_reduit"], 21250.00, 0.01),
    ("IS3", "base_25_6_mois", lambda c: _is(30000, 6, c)["base_taux_normal"], 8750.00, 0.01),
    ("IS3", "impot_6_mois", lambda c: _is(30000, 6, c)["impot"], 5375.00, 0.01),
    ("IS4", "base_15_limite", lambda c: _is(42500, 12, c)["base_taux_reduit"], 42500.00, 0.01),
    ("IS4", "base_25_limite", lambda c: _is(42500, 12, c)["base_taux_normal"], 0.00, 0.01),
    ("IS4", "impot_limite", lambda c: _is(42500, 12, c)["impot"], 6375.00, 0.01),
    ("IS5", "base_15_deficit", lambda c: _is(-5000, 12, c)["base_taux_reduit"], 0.00, 0.01),
    ("IS5", "base_25_deficit", lambda c: _is(-5000, 12, c)["base_taux_normal"], 0.00, 0.01),
    ("IS5", "impot_deficit", lambda c: _is(-5000, 12, c)["impot"], 0.00, 0.01),
    ("IS5", "deficit_reporte", lambda c: fsci.imputer_deficits(-5000, 0.0, c.params)["deficit_reporte"], 5000.00, 0.01),
    ("D1", "pfu_impot", lambda c: _dist(10000, 0.14, c)["pfu"]["impot"], 3140.00, 0.01),
    ("D1", "pfu_net", lambda c: _dist(10000, 0.14, c)["pfu"]["net"], 6860.00, 0.01),
    ("D2", "bareme_014_ir", lambda c: _dist(10000, 0.14, c)["bareme"]["ir"], 840.00, 0.01),
    ("D2", "bareme_014_ps", lambda c: _dist(10000, 0.14, c)["bareme"]["ps"], 1860.00, 0.01),
    ("D2", "bareme_014_impot", lambda c: _dist(10000, 0.14, c)["bareme"]["impot"], 2700.00, 0.01),
    ("D2", "bareme_014_net", lambda c: _dist(10000, 0.14, c)["bareme"]["net"], 7300.00, 0.01),
    ("D2", "bareme_014_csg_n1", lambda c: _dist(10000, 0.14, c)["bareme"]["csg_deductible_n1"], 95.20, 0.01),
    ("D3", "bareme_030_impot", lambda c: _dist(10000, 0.30, c)["bareme"]["impot"], 3660.00, 0.01),
    ("D3", "bareme_030_net", lambda c: _dist(10000, 0.30, c)["bareme"]["net"], 6340.00, 0.01),
    ("B1", "R", lambda c: c.assiette["loyers_encaisses"], 14352.00, 0.01),
    ("B1", "interets_an1", lambda c: c.assiette["interets_an1"], 8413.96, 0.01),
    ("B1", "assurance_an1", lambda c: c.assiette["assurance_an1"], 690.00, 0.01),
    ("B1", "charges_exploitation",
     lambda c: c.r_inc["sci_is"]["charges_deductibles"] - c.assiette["interets_an1"] - c.assiette["assurance_an1"],
     2280.00, 0.01),
    ("B1", "frais_acquisition", lambda c: c.inc["acquisition"]["frais_acquisition"], 15637.00, 0.01),
    ("B1", "cash_flow_avant_impot", lambda c: c.inc["scenarios"]["realiste"]["indicateurs"]["cash_flow_mensuel_avant_impot"],
     -292.75, 0.01),
    ("B2", "inc_base", lambda c: c.r_inc["sci_is"]["base_amortissable"], 215637.00, 0.01),
    ("B2", "inc_amort_bati", lambda c: c.r_inc["sci_is"]["amortissements"]["bati"], 6145.65, 0.01),
    ("B2", "inc_amort_travaux", lambda c: c.r_inc["sci_is"]["amortissements"]["travaux"], 2000.00, 0.01),
    ("B2", "inc_amort_total", lambda c: c.r_inc["sci_is"]["amortissements"]["total"], 8145.65, 0.01),
    ("B2", "inc_charges", lambda c: c.r_inc["sci_is"]["charges_deductibles"], 11383.96, 0.01),
    ("B2", "inc_resultat_fiscal", lambda c: c.r_inc["sci_is"]["resultat_fiscal"], -5177.62, 0.01),
    ("B2", "inc_is", lambda c: c.r_inc["sci_is"]["impot_total"], 0.00, 0.01),
    ("B2", "inc_deficit_reporte", lambda c: c.r_inc["sci_is"]["deficit_reporte"], 5177.62, 0.01),
    ("B2", "inc_cash_flow_sci", lambda c: c.r_inc["sci_is"]["cash_flow_mensuel_net_net"], -292.75, 0.01),
    ("B3", "chg_base", lambda c: c.r_chg["sci_is"]["base_amortissable"], 200000.00, 0.01),
    ("B3", "chg_amort_total", lambda c: c.r_chg["sci_is"]["amortissements"]["total"], 7700.00, 0.01),
    ("B3", "chg_charges", lambda c: c.r_chg["sci_is"]["charges_deductibles"], 27020.96, 0.01),
    ("B3", "chg_resultat_fiscal", lambda c: c.r_chg["sci_is"]["resultat_fiscal"], -20368.96, 0.01),
    ("B3", "chg_is", lambda c: c.r_chg["sci_is"]["impot_total"], 0.00, 0.01),
    ("B3", "chg_deficit_reporte", lambda c: c.r_chg["sci_is"]["deficit_reporte"], 20368.96, 0.01),
    ("B4", "ir_q1_resultat", lambda c: c.r_inc["sci_ir"]["resultat"], -27031.96, 0.01),
    ("B4", "ir_q1_imposable", lambda c: c.r_inc["sci_ir"]["imposable"], 0.00, 0.01),
    ("B4", "ir_q1_impute", lambda c: c.r_inc["sci_ir"]["deficit_impute_global"], 10700.00, 0.01),
    ("B4", "ir_q1_report", lambda c: c.r_inc["sci_ir"]["report_foncier"], 16331.96, 0.01),
    ("B5", "ir_q05_resultat", lambda c: c.r_q05["sci_ir"]["resultat"], -13515.98, 0.01),
    ("B5", "ir_q05_imposable", lambda c: c.r_q05["sci_ir"]["imposable"], 0.00, 0.01),
    ("B5", "ir_q05_impute", lambda c: c.r_q05["sci_ir"]["deficit_impute_global"], 10700.00, 0.01),
    ("B5", "ir_q05_report", lambda c: c.r_q05["sci_ir"]["report_foncier"], 2815.98, 0.01),
    ("F4", "assurance_an1", lambda c: _f(c, "realiste")[1]["assurance_an1"], 300.00, 0.01),
    ("F4", "frais_acquisition", lambda c: c.sci["acquisition"]["frais_acquisition"], 22955.50, 0.01),
    ("F4", "base_amortissable", lambda c: _f(c, "realiste")[0]["sci_is"]["base_amortissable"], 322955.50, 0.01),
    ("F4", "cout_total", lambda c: c.sci["acquisition"]["cout_total"], 322955.50, 0.01),
    ("F5", "distribuable", lambda c: _f(c, "realiste")[0]["sci_is"]["distribution"]["distribuable"], True, 0),
    ("F5", "pfu_impot", lambda c: _f(c, "realiste")[0]["sci_is"]["distribution"]["pfu"]["impot"], 3140.00, 0.01),
    ("F5", "bareme_impot", lambda c: _f(c, "realiste")[0]["sci_is"]["distribution"]["bareme"]["impot"], 2700.00, 0.01),
    ("F5", "cash_flow_mensuel_foyer",
     lambda c: _f(c, "realiste")[0]["sci_is"]["distribution"]["cash_flow_mensuel_foyer"], 608.33, 0.01),
    ("F5", "cash_flow_mensuel_sci_apres_versements",
     lambda c: _f(c, "realiste")[0]["sci_is"]["distribution"]["cash_flow_mensuel_sci_apres_versements"], 1470.23, 0.01),
    ("F6", "chg_resultat_fiscal", lambda c: c.r_sci_chg["sci_is"]["resultat_fiscal"], 6350.54, 0.01),
    ("F6", "chg_is", lambda c: c.r_sci_chg["sci_is"]["impot_total"], 952.58, 0.01),
]

# Tableau par scénario de bien_fictif_sci_is.json (lignes F1 à F3, 10 colonnes chacune).
TABLEAU_FIXTURE = {
    #             R          intérêts  charges  bâti     résultat   IS        après IS   CF av.   CF SCI   rend. nn
    "pessimiste": (39744.00, 3443.96, 4000.00, 9204.23, 22795.81, 3419.37, 19376.44, 2193.71, 1908.76, 0.093402),
    "realiste":   (45600.00, 3443.96, 4000.00, 9204.23, 28651.81, 4297.77, 24354.04, 2661.71, 2303.56, 0.108071),
    "optimiste":  (51216.00, 3443.96, 4000.00, 9204.23, 34267.81, 5140.17, 29127.64, 3109.71, 2681.36, 0.122109),
}
COLONNES_FIXTURE = [
    ("R", lambda c, s: _f(c, s)[1]["loyers_encaisses"], 0.01),
    ("interets", lambda c, s: _f(c, s)[1]["interets_an1"], 0.01),
    ("charges", _charges_exploitation, 0.01),
    ("amort_bati", lambda c, s: _f(c, s)[0]["sci_is"]["amortissements"]["bati"], 0.01),
    ("resultat_fiscal", lambda c, s: _f(c, s)[0]["sci_is"]["resultat_fiscal"], 0.01),
    ("is", lambda c, s: _f(c, s)[0]["sci_is"]["impot_total"], 0.01),
    ("apres_is", lambda c, s: _f(c, s)[0]["sci_is"]["resultat_apres_is"], 0.01),
    ("cf_avant_impot", lambda c, s: _f(c, s)[2]["cash_flow_mensuel_avant_impot"], 0.01),
    ("cf_sci_apres_is", lambda c, s: _f(c, s)[0]["sci_is"]["cash_flow_mensuel_net_net"], 0.01),
    ("rendement_net_net", lambda c, s: _f(c, s)[0]["sci_is"]["rendement_net_net"], 1e-6),
]
LIGNES_FIXTURE = {"pessimiste": "F1", "realiste": "F2", "optimiste": "F3"}
LIGNES_DE_REFERENCE = {"IS1", "IS2", "IS3", "IS4", "IS5", "D1", "D2", "D3", "B1", "B2", "B3", "B4", "B5",
                    "F1", "F2", "F3", "F4", "F5", "F6"}


@pytest.mark.parametrize("attendu,tolerance,calcul",
                         [pytest.param(a, t, f, id=f"{n}_{nom}") for n, nom, f, a, t in TABLEAU])
def test_tableau_de_reference(ctx, calcul, attendu, tolerance):
    assert calcul(ctx) == pytest.approx(attendu, abs=tolerance)


@pytest.mark.parametrize("scenario,colonne", [pytest.param(s, i, id=f"{LIGNES_FIXTURE[s]}_{s}_{nom}")
                                               for s in TABLEAU_FIXTURE for i, (nom, *_) in enumerate(COLONNES_FIXTURE)])
def test_tableau_fixture_sci_is(ctx, scenario, colonne):
    nom, calcul, tolerance = COLONNES_FIXTURE[colonne]
    assert calcul(ctx, scenario) == pytest.approx(TABLEAU_FIXTURE[scenario][colonne], abs=tolerance), nom


def test_tableau_couvre_les_19_lignes_de_reference():
    """Couverture comptée : chaque ligne des tableaux de référence a au moins un test."""
    couvertes = {n for n, *_ in TABLEAU} | set(LIGNES_FIXTURE.values())
    assert couvertes == LIGNES_DE_REFERENCE and len(LIGNES_DE_REFERENCE) == 19


def test_b4_sci_ir_quote_part_1_egale_au_foncier_reel_du_nom_propre(ctx):
    ir, nom_propre = ctx.r_inc["sci_ir"], ctx.r_inc["foncier_reel"]
    for cle in ("resultat", "imposable", "deficit_impute_global", "report_foncier"):
        assert ir[cle] == pytest.approx(nom_propre[cle]), cle


def test_d_option_la_plus_favorable(ctx):
    assert _dist(10000, 0.14, ctx)["option_la_plus_favorable"] == "bareme"
    assert _dist(10000, 0.30, ctx)["option_la_plus_favorable"] == "pfu"
    r, _, _ = _f(ctx, "realiste")
    assert r["sci_is"]["distribution"]["option_la_plus_favorable"] == "bareme"


def test_cli_fixture_sci_is_sept_regimes_is_et_cash_flow_foyer():
    """Critère de référence : les 7 régimes, IS 4297.77, cash-flow du foyer 608.33 (sortie arrondie de la CLI)."""
    r = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(BIEN_SCI_IS)], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    reg = json.loads(r.stdout)["fiscalite"]["scenarios"]["realiste"]["regimes"]
    assert sorted(reg) == ["bailleur_prive", "foncier_reel", "lmnp_micro_bic", "lmnp_reel", "micro_foncier", "sci_ir",
                           "sci_is"]
    assert reg["sci_is"]["impot_total"] == 4297.77
    assert reg["sci_is"]["distribution"]["cash_flow_mensuel_foyer"] == 608.33


# --------------------------------------------------------------------------------------------
# 2. Gardes : chaque règle prouvée dans les deux sens.
# --------------------------------------------------------------------------------------------

def test_is_limite_proratisee_sur_la_duree_de_l_exercice(params):
    """Discriminant 1 (BOI-IS-LIQ-20-20-20230621 §50) : 18 mois → 63 750 ; 6 mois → 21 250."""
    assert fsci.impot_societes(50000, 18, params)["limite_appliquee"] == pytest.approx(63750.0)
    assert fsci.impot_societes(30000, 6, params)["limite_appliquee"] == pytest.approx(21250.0)
    assert fsci.impot_societes(30000, 6, params)["duree_exercice_mois"] == 6


def test_is_sans_taux_reduit_tout_au_taux_normal(params):
    i = fsci.impot_societes(50000, 12, params, taux_reduit_applicable=False)
    assert (i["base_taux_reduit"], i["base_taux_normal"], i["impot"]) == (0.0, 50000, pytest.approx(12500.0))


def test_sci_is_capital_non_libere_pas_de_taux_reduit(params):
    """CGI 219 I-b : le taux réduit suppose un capital entièrement libéré."""
    r = _regimes(_bien(BIEN_SCI_IS, capital_libere=False), params)["sci_is"]
    assert r["is_detail"]["base_taux_reduit"] == 0.0
    assert r["impot_total"] == pytest.approx(28651.81 * 0.25, abs=0.01)
    assert any("219 I-b" in x for x in r["raisons"])


def test_amortissement_non_limite_au_resultat_a_l_is(ctx):
    """Discriminant 2 : 39 C II ne vise pas la société à l'IS ; l'amortissement crée le déficit (-5 177,62)."""
    r = ctx.r_inc["sci_is"]
    assert r["resultat_fiscal"] < 0
    assert r["resultat_fiscal"] == pytest.approx(ctx.r_inc["lmnp_reel"]["resultat_avant_amortissement"]
                                                 - r["amortissements"]["total"])


def test_frais_d_acquisition_en_charges_ou_incorpores(ctx):
    """Discriminant 3 : l'option change la base amortissable et les charges."""
    inc, chg = ctx.r_inc["sci_is"], ctx.r_chg["sci_is"]
    assert inc["frais_acquisition_traitement"]["option"] == "incorpores"
    assert chg["frais_acquisition_traitement"]["option"] == "charges"
    assert chg["base_amortissable"] == pytest.approx(inc["base_amortissable"] - 15637.0)
    assert chg["charges_deductibles"] == pytest.approx(inc["charges_deductibles"] + 15637.0)


def test_sci_ir_quote_part_avant_plafond(ctx):
    """Discriminant 4 : le plafond de 10 700 € s'applique au foyer APRÈS la quote-part (pas 0,5 × 10 700)."""
    assert ctx.r_q05["sci_ir"]["deficit_impute_global"] == pytest.approx(10700.0)


def test_deficit_imputation_plafonnee_a_un_million_plus_50_pct(params):
    """CGI 209-I al. 3 : bénéfice 3 M€, déficits 5 M€ → imputation 1 M€ + 50 % × 2 M€ = 2 M€."""
    d = fsci.imputer_deficits(3_000_000.0, 5_000_000.0, params)
    assert d["deficit_impute"] == pytest.approx(2_000_000.0)
    assert d["imposable"] == pytest.approx(1_000_000.0)
    assert d["deficit_reporte"] == pytest.approx(3_000_000.0)
    petit = fsci.imputer_deficits(30_000.0, 5_000.0, params)
    assert (petit["imposable"], petit["deficit_reporte"]) == (pytest.approx(25_000.0), 0.0)


def test_deficit_reste_dans_la_sci(ctx):
    """Le déficit de la SCI à l'IS ne s'impute pas sur les revenus des associés."""
    r = ctx.r_inc["sci_is"]
    assert r["imposable"] == 0.0 and r["impot_total"] == 0.0
    assert r["ir"] is None and r["ps"] is None


def test_distribution_ps_au_taux_des_placements(params):
    """Discriminant 5 : PS des dividendes à 18,6 % (LFSS 2026), pas 17,2 %."""
    assert modele.valeur(params, "fiscal.prelevements_sociaux.revenus_placement") == 0.186
    assert fsci.distribution(10000, 1e9, 0.14, 0.0, 0.0, params)["bareme"]["ps"] == pytest.approx(1860.0)


def test_distribution_bareme_avec_abattement_de_40_pct(params):
    """Discriminant 6 : IR au barème sur 60 % du dividende (CGI 158-3-2°)."""
    assert fsci.distribution(10000, 1e9, 0.14, 0.0, 0.0, params)["bareme"]["ir"] == pytest.approx(840.0)


def test_distribution_non_distribuable_sans_erreur(params):
    r = _regimes(_bien(distribution_annuelle=5000), params)["sci_is"]
    d = r["distribution"]
    assert d["distribuable"] is False
    assert any("résultat après IS" in x for x in d["raisons"])
    assert d["pfu"]["impot"] == pytest.approx(5000 * 0.314)


def test_distribution_vide_si_aucun_versement(ctx):
    assert ctx.r_inc["sci_is"]["distribution"] == {}


def test_distribution_sans_tmi_pas_de_bareme_et_pfu_par_defaut(params):
    d = fsci.distribution(10000, 1e9, None, 0.0, 0.0, params)
    assert d["bareme"] is None and d["option_la_plus_favorable"] is None
    assert d["cash_flow_mensuel_foyer"] == pytest.approx(6860.0 / 12)
    assert any("tmi" in x for x in d["raisons"])


def test_remboursement_de_compte_courant_non_impose(params):
    d = fsci.distribution(0.0, 1e9, 0.14, 6000.0, 1000.0, params)
    assert d["cash_flow_mensuel_foyer"] == pytest.approx(500.0)
    assert d["cash_flow_mensuel_sci_apres_versements"] == pytest.approx(500.0)


CCA = {"montant": 10000, "taux": 0.04}


def test_interets_cca_deductibles_si_capital_libere_et_taux_publie(params):
    """Taux publié pour un exercice de 12 mois clos le 31/12/2025 (4,55 %, BOI-BIC-CHG-50-50-30-20260128)."""
    i = fsci.interets_cca(CCA, True, "2025-12-31", 12, params)
    assert i["verses"] == pytest.approx(400.0) and i["deductibles"] == pytest.approx(400.0)
    plafonne = fsci.interets_cca({"montant": 10000, "taux": 0.06}, True, "2025-12-31", 12, params)
    assert plafonne["deductibles"] == pytest.approx(455.0) and plafonne["verses"] == pytest.approx(600.0)


def test_interets_cca_non_deductibles_sans_capital_libere(params):
    """Discriminant 7 : CGI 39-1-3°, déduction subordonnée à la libération entière du capital."""
    i = fsci.interets_cca(CCA, False, "2025-12-31", 12, params)
    assert i["deductibles"] == 0.0 and i["verses"] == pytest.approx(400.0)
    assert any("libéré" in x for x in i["raisons"])


def test_interets_cca_dernier_taux_publie_si_cloture_posterieure(params):
    """Convention du moteur : taux non publié pour une clôture au 31/12/2026
    → dernier taux publié (4,33 %, clôtures du 31/08 au 29/09/2026), hypothèse « à vérifier » dite dans la raison."""
    i = fsci.interets_cca(CCA, True, "2026-12-31", 12, params)
    assert i["deductibles"] == pytest.approx(400.0)
    plafonne = fsci.interets_cca({"montant": 10000, "taux": 0.06}, True, "2026-12-31", 12, params)
    assert plafonne["deductibles"] == pytest.approx(433.0)
    assert any("non publié" in x and "à vérifier" in x and "2026-09-29" in x for x in plafonne["raisons"])
    r = _regimes(_bien(BIEN_SCI_IS, cca=CCA), params)["sci_is"]
    assert r["evaluable"] is True and r["interets_cca_deductibles"] == pytest.approx(400.0)
    assert any("à vérifier" in x for x in r["raisons"])


def test_interets_cca_non_deduits_si_cloture_anterieure_a_la_table(params):
    """Clôture avant la première ligne de la table (versions antérieures du BOI non lues) : aucun « dernier taux »
    à cette date, rien de deviné, intérêt non déduit ; de même sans date de clôture."""
    for date in ("2025-06-30", None):
        i = fsci.interets_cca(CCA, True, date, 12, params)
        assert i["deductibles"] == 0.0
        assert any("non publié" in x for x in i["raisons"]) and not any("à vérifier" in x for x in i["raisons"])


def test_interets_cca_taux_publie_sans_raison_a_verifier(params):
    """Clôture couverte par la table : taux publié, aucune hypothèse à dire."""
    i = fsci.interets_cca(CCA, True, "2026-09-29", 12, params)
    assert i["deductibles"] == pytest.approx(400.0) and i["raisons"] == []


def test_interets_cca_exercice_hors_12_mois_non_deduits(params):
    i = fsci.interets_cca(CCA, True, "2025-12-31", 18, params)
    assert i["deductibles"] == 0.0
    assert any("12 mois" in x for x in i["raisons"])


def test_interets_cca_verses_sortent_de_la_tresorerie_de_la_sci(params):
    sans = _regimes(_bien(BIEN_SCI_IS), params)["sci_is"]
    avec = _regimes(_bien(BIEN_SCI_IS, cca=CCA), params)["sci_is"]
    assert avec["interets_cca_verses"] == pytest.approx(400.0)
    # Depuis 6b du , la clôture au 31/12/2026 prend le dernier taux publié : les intérêts
    # déduits baissent l'IS ; la trésorerie perd les versés et regagne l'IS économisé.
    economie_is = sans["impot_total"] - avec["impot_total"]
    assert economie_is > 0
    assert avec["cash_flow_mensuel_net_net"] == pytest.approx(
        sans["cash_flow_mensuel_net_net"] - 400.0 / 12 + economie_is / 12)


def test_sci_ir_micro_foncier_non_code_raison_affichee(ctx):
    raisons = " ".join(ctx.r_inc["sci_ir"]["raisons"])
    assert "micro-foncier" in raisons and "32, 2-d" in raisons


def test_sci_ir_cash_flow_et_cout_en_quote_part(params):
    """Bien sans travaux (résultat foncier positif) et TMI fictive : impôt, cash-flow et coût du foyer en quote-part."""
    bien = _bien(regime="ir", quote_part_foyer=0.5)
    bien.update(travaux=0, fiscal={"tmi": 0.14, "annee_revenus": 2026})
    sortie = _sortie(bien, params)
    r = sortie["fiscalite"]["scenarios"]["realiste"]["regimes"]["sci_ir"]
    ind = sortie["scenarios"]["realiste"]["indicateurs"]
    cout = sortie["acquisition"]["cout_total"]
    assert r["imposable"] > 0
    assert r["cash_flow_mensuel_net_net"] == pytest.approx(0.5 * ind["cash_flow_mensuel_avant_impot"] - r["impot_total"] / 12)
    assert r["rendement_net_net"] == pytest.approx(ind["rendement_net"] - r["impot_total"] / (0.5 * cout))


def test_regime_demande_et_regime_absent_calcule_aussi(ctx, params):
    assert ctx.r_inc["sci_is"]["regime_demande"] is True and ctx.r_inc["sci_ir"]["regime_demande"] is False
    assert ctx.r_q05["sci_ir"]["regime_demande"] is True and ctx.r_q05["sci_is"]["regime_demande"] is False
    assert ctx.r_q05["sci_is"]["impot_total"] is not None


# --------------------------------------------------------------------------------------------
# 3. Contrat, entrées, hypothèses, paramètres.
# --------------------------------------------------------------------------------------------

def test_sans_bloc_sci_les_regimes_sci_ne_sont_pas_evaluables(params):
    for s in _sortie(_bien(sans_sci=True), params)["fiscalite"]["scenarios"].values():
        for nom in ("sci_ir", "sci_is"):
            r = s["regimes"][nom]
            assert r["evaluable"] is False and r["impot_total"] is None, nom
            assert "bloc sci absent" in " ".join(r["raisons"]), nom


def test_sans_bloc_sci_aucun_parametre_sci_utilise(params):
    pu = _sortie(_bien(sans_sci=True), params)["params_utilises"]
    assert not [c for c in pu if c.startswith(("fiscal.is.", "fiscal.sci_is.", "fiscal.dividendes."))]
    assert "fiscal.prelevements_sociaux.revenus_placement" not in pu


def test_params_utilises_avec_bloc_sci(ctx):
    pu = ctx.sci["params_utilises"]
    for chemin in ("fiscal.is.taux_reduit", "fiscal.is.taux_normal", "fiscal.is.limite_taux_reduit_12_mois",
                   "fiscal.sci_is.taux_max_interets_cca", "fiscal.sci_is.deficit_imputation_max",
                   "fiscal.prelevements_sociaux.revenus_placement", "fiscal.dividendes.pfu_ir",
                   "fiscal.dividendes.abattement_bareme", "fiscal.dividendes.csg_deductible"):
        assert chemin in pu, chemin
        assert pu[chemin]["source"] and pu[chemin]["verifie_le"], chemin


def test_contrat_sci_is_details(ctx):
    r = ctx.r_inc["sci_is"]
    assert {"evaluable", "eligible", "raisons", "imposable", "ir", "ps", "impot_total", "cash_flow_mensuel_net_net",
            "rendement_net_net", "resultat_fiscal", "charges_deductibles", "amortissements",
            "frais_acquisition_traitement", "is_detail", "deficit_reporte", "interets_cca_deductibles",
            "resultat_apres_is", "distribution"} <= set(r)
    assert set(r["amortissements"]) == {"bati", "travaux", "mobilier", "total"}
    assert set(r["is_detail"]) == {"base_taux_reduit", "base_taux_normal", "limite_appliquee", "duree_exercice_mois"}
    d = _f(ctx, "realiste")[0]["sci_is"]["distribution"]
    assert {"montant", "distribuable", "pfu", "bareme", "option_la_plus_favorable", "remboursement_cca",
            "cash_flow_mensuel_foyer", "cash_flow_mensuel_sci_apres_versements"} <= set(d)
    assert set(d["pfu"]) >= {"impot", "net"} and set(d["bareme"]) >= {"ir", "ps", "net", "csg_deductible_n1"}


def test_sci_is_evaluable_sans_tmi(ctx):
    """L'IS ne dépend pas de la TMI du foyer : bien_fictif.json (sans TMI) a un IS évalué."""
    assert ctx.inc["fiscalite"]["tmi"] is None
    assert ctx.r_inc["sci_is"]["evaluable"] is True and ctx.r_inc["sci_is"]["impot_total"] == 0.0


def test_rendement_net_net_sci_is(ctx):
    r, _, ind = _f(ctx, "realiste")
    cout = ctx.sci["acquisition"]["cout_total"]
    assert r["sci_is"]["rendement_net_net"] == pytest.approx(ind["rendement_net"] - r["sci_is"]["impot_total"] / cout)


@pytest.mark.parametrize("champ,valeur", [
    ("regime", "sas"), ("quote_part_foyer", 0), ("quote_part_foyer", 1.5), ("duree_premier_exercice_mois", 0),
    ("duree_premier_exercice_mois", 25), ("duree_premier_exercice_mois", 12.5), ("frais_acquisition", "amortis"),
    ("capital_libere", "oui"), ("cca", {"montant": -1, "taux": 0}), ("cca", {"montant": 0, "taux": 1.2}),
    ("distribution_annuelle", -1), ("remboursement_cca_annuel", "1000"),
])
def test_bloc_sci_invalide_leve_value_error(champ, valeur):
    brut = json.loads(BIEN_SCI_IS.read_text(encoding="utf-8"))
    brut["sci"][champ] = valeur
    with pytest.raises(ValueError, match=f"sci.{champ}"):
        modele.valider_bien(brut)


@pytest.mark.parametrize("champ", list(SCI_FICTIF))
def test_bloc_sci_champ_absent_leve_value_error(champ):
    brut = json.loads(BIEN_SCI_IS.read_text(encoding="utf-8"))
    del brut["sci"][champ]
    with pytest.raises(ValueError, match=f"champ requis absent : sci.{champ}"):
        modele.valider_bien(brut)


def test_bloc_sci_absent_aucun_champ_requis_ajoute():
    brut = json.loads(BIEN_SCI_IS.read_text(encoding="utf-8"))
    del brut["sci"]
    assert modele.valider_bien(brut) is brut


def test_analyser_ne_modifie_pas_le_bien_sci(params):
    bien = _bien(BIEN_SCI_IS, cca=CCA, remboursement_cca_annuel=1000)
    avant = copy.deepcopy(bien)
    analyser(bien, params, contexte_foyer=CONTEXTE_FICTIF)
    assert bien == avant


def test_o7_hypothese_ir_au_taux_marginal_fixe_dans_les_deux_modes(params):
    assert H_O7 in _sortie(_bien(sans_sci=True), params)["fiscalite"]["hypotheses"]
    assert H_O7 in _sortie(_bien(sans_sci=True), params, CONTEXTE_FICTIF)["fiscalite"]["hypotheses"]


def test_hypotheses_sci_seulement_avec_bloc_sci(params):
    avec = " ".join(_sortie(_bien(), params)["fiscalite"]["hypotheses"])
    sans = " ".join(_sortie(_bien(sans_sci=True), params)["fiscalite"]["hypotheses"])
    for marque in ("BOI-BIC-AMT-20-40-10-10", "209-I al. 3", "CGI 239", "1447 I", "200 A, 2"):
        assert marque in avec and marque not in sans, marque
    assert avec.count("taux marginal fixe") == 1


NOUVEAUX_PARAMS = {
    "fiscal.is.taux_reduit": 0.15, "fiscal.is.taux_normal": 0.25, "fiscal.is.limite_taux_reduit_12_mois": 42500,
    "fiscal.prelevements_sociaux.revenus_placement": 0.186, "fiscal.dividendes.pfu_ir": 0.128,
    "fiscal.dividendes.abattement_bareme": 0.40, "fiscal.dividendes.csg_deductible": 0.068,
    "fiscal.sci_is.deficit_imputation_max": {"franchise": 1000000, "fraction_au_dela": 0.5},
}


@pytest.mark.parametrize("chemin,attendu", list(NOUVEAUX_PARAMS.items()))
def test_params_sci_valeurs_sources_nature(params, chemin, attendu):
    p = modele.parametre(params, chemin)
    assert p["valeur"] == attendu
    assert p["nature"] == "loi" and p["source"].strip() and p["verifie_le"] in ("2026-10-03", "2026-10-04")


def test_params_taux_max_cca_seulement_publies_et_a_verifier(params):
    p = modele.parametre(params, "fiscal.sci_is.taux_max_interets_cca")
    assert p["a_verifier"] is True and p["nature"] == "doctrine"
    assert "BOI-BIC-CHG-50-50-30-20260128" in p["source"]
    clotures = [t["cloture_au"] for t in p["valeur"]]
    assert max(clotures) == "2026-09-29"  # dernière clôture publiée au 04/10/2026
    for t in p["valeur"]:
        assert t["cloture_du"] <= t["cloture_au"] and 0 < t["taux"] < 0.1
