"""Socle du moteur immo (`src/immo/`) : acquisition, financement, exploitation, indicateurs.

Tous les chiffres viennent du bien FICTIF
`tests/fixtures/immo/bien_fictif.json` : aucune valeur réelle ni de marché, aucun montant du foyer.

Les valeurs attendues (TABLEAU) sont indépendantes du moteur : calculées à part avec
les formes fermées de l'annuité et du capital restant dû (`_monthly_payment`, `_loan_balance_after_months` ci-dessous)
et une bissection simple, avant d'écrire le moteur.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import acquisition, analyser, exploitation, financement, indicateurs, modele  # noqa: E402


def _monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    """Mensualité de référence, forme fermée de l'annuité constante (indépendante du moteur)."""
    if principal <= 0 or term_months <= 0:
        return 0.0
    t = annual_rate / 12
    if t <= 0:
        return principal / term_months
    return principal * t / (1 - (1 + t) ** (-term_months))


def _loan_balance_after_months(outstanding: float, annual_rate: float, monthly_payment: float, months: int) -> float:
    """Capital restant dû de référence après `months` mensualités, forme fermée (indépendante du moteur)."""
    if outstanding <= 0:
        return 0.0
    if months <= 0:
        return round(outstanding, 2)
    t = annual_rate / 12
    if t <= 0:
        return round(max(0.0, outstanding - monthly_payment * months), 2)
    facteur = (1 + t) ** months
    return round(max(0.0, outstanding * facteur - monthly_payment * ((facteur - 1) / t)), 2)


FIXTURES = ROOT / "tests" / "fixtures" / "immo"
BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_INCOMPLET = biens_test.chemin("bien_fictif_incomplet.json")
PARAMS_JSON = ROOT / "src" / "immo" / "params.json"
SRC_IMMO = ROOT / "src" / "immo"


@pytest.fixture()
def bien():
    return modele.charger_bien(BIEN_FICTIF)


@pytest.fixture()
def params():
    return modele.charger_params()


@pytest.fixture()
def ctx(bien, params):
    return SimpleNamespace(bien=bien, params=params)


def _bien_modifie(chemin: str, valeur) -> dict:
    """Copie du bien fictif brut (non validé) dont le champ `chemin` (a.b.c) vaut `valeur`."""
    brut = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    cible = brut
    *debut, dernier = chemin.split(".")
    for cle in debut:
        cible = cible[cle]
    cible[dernier] = valeur
    return brut


def _bien_sans(chemin: str) -> dict:
    brut = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    cible = brut
    *debut, dernier = chemin.split(".")
    for cle in debut:
        cible = cible[cle]
    del cible[dernier]
    return brut


# --------------------------------------------------------------------------------------------
# 1. Tableau des valeurs attendues de référence : chaque ligne (n° 1 à 20), scénario `realiste`.
# --------------------------------------------------------------------------------------------

TABLEAU = [
    # (n° de ligne, nom, valeur calculée par le moteur, attendu, tolérance absolue)
    (1, "dmto", lambda c: acquisition.dmto(c.bien["prix_net_vendeur"], c.bien["departement"], c.params),
     12637.00, 0.01),
    (2, "taux_global_dmto",
     lambda c: acquisition.dmto(c.bien["prix_net_vendeur"], c.bien["departement"], c.params)
     / c.bien["prix_net_vendeur"], 0.063185, 1e-6),
    (3, "frais_acquisition", lambda c: acquisition.frais_acquisition(c.bien, c.params), 15637.00, 0.01),
    (4, "cout_total", lambda c: acquisition.cout_total(c.bien, c.params), 245637.00, 0.01),
    (5, "emprunt", lambda c: financement.emprunt(c.bien), 230000.00, 0.01),
    (5, "apport", lambda c: financement.apport(c.bien, c.params), 15637.00, 0.01),
    (6, "mensualite_hors_assurance", lambda c: financement.mensualite(230000, 0.037, 300), 1176.2516, 1e-4),
    (7, "assurance_mensuelle", lambda c: financement.assurance_mensuelle(c.bien), 57.50, 1e-4),
    (8, "rendement_brut", lambda c: indicateurs.rendement_brut(c.bien, "realiste", c.params), 0.063508, 1e-6),
    (9, "rendement_net", lambda c: indicateurs.rendement_net(c.bien, "realiste", c.params), 0.045970, 1e-6),
    (10, "cash_flow_mensuel_avant_impot",
     lambda c: indicateurs.cash_flow_mensuel_avant_impot(c.bien, "realiste"), -292.7516, 1e-3),
    (11, "cash_on_cash", lambda c: indicateurs.cash_on_cash(c.bien, "realiste", c.params), -0.224661, 1e-6),
    (12, "ratio_couverture",
     lambda c: indicateurs.ratio_couverture(c.bien, "realiste"), 0.873215, 1e-6),
    (13, "crd_apres_12_mois",
     lambda c: financement.crd_apres(financement.echeancier_bien(c.bien), 12), 224298.94, 0.01),
    (13, "enrichissement_an1", lambda c: indicateurs.enrichissement_an1(c.bien), 5701.06, 0.01),
    (14, "prix_equilibre", lambda c: indicateurs.prix_equilibre(c.bien, "realiste"), 145424.28, 0.01),
    (15, "taux_effort_hcsf",
     lambda c: indicateurs.taux_effort_hcsf(c.bien, "realiste", c.params), 0.377961, 1e-6),
    (16, "differe_partiel_interets_seuls",
     lambda c: financement.echeancier(230000, 0.037, 300, "partiel", 12)[0]["mensualite"], 709.1667, 1e-4),
    (16, "differe_partiel_pmt_288",
     lambda c: financement.echeancier(230000, 0.037, 300, "partiel", 12)[12]["mensualite"], 1206.1487, 1e-4),
    (17, "differe_total_capital_capitalise",
     lambda c: financement.echeancier(230000, 0.037, 300, "total", 12)[11]["crd"], 238655.8090, 1e-3),
    (17, "differe_total_pmt_288",
     lambda c: financement.echeancier(230000, 0.037, 300, "total", 12)[12]["mensualite"], 1251.5408, 1e-3),
    (18, "tri_100_10_10_110", lambda c: indicateurs.tri([-100, 10, 10, 110]), 0.10, 1e-9),
    (19, "tri_1000_300_400_500", lambda c: indicateurs.tri([-1000, 300, 400, 500]), 0.08896339, 1e-8),
    (20, "van_5pct_1000_300_400_500",
     lambda c: indicateurs.van(0.05, [-1000, 300, 400, 500]), 80.444876, 1e-6),
]


@pytest.mark.parametrize(
    "attendu,tolerance,calcul",
    [pytest.param(a, t, f, id=f"L{n:02d}_{nom}") for n, nom, f, a, t in TABLEAU],
)
def test_tableau_de_reference(ctx, calcul, attendu, tolerance):
    assert calcul(ctx) == pytest.approx(attendu, abs=tolerance)


def test_tableau_couvre_les_20_lignes():
    """Couverture comptée : les 20 lignes du tableau de référence ont chacune au moins un test."""
    assert {n for n, *_ in TABLEAU} == set(range(1, 21))


def test_l15_conforme_hcsf_faux_sur_le_realiste(bien, params):
    h = indicateurs.conformite_hcsf(bien, "realiste", params)
    assert h["taux_effort"] == pytest.approx(0.377961, abs=1e-6)
    assert h["conforme"] is False


def test_hcsf_conforme_quand_taux_et_duree_respectent_les_plafonds(bien, params):
    bien["foyer"]["revenus_nets_mensuels"] = 9000
    h = indicateurs.conformite_hcsf(bien, "realiste", params)
    assert h["taux_effort"] < params["hcsf"]["taux_effort_max"]["valeur"]
    assert h["duree_mois"] == 300
    assert h["conforme"] is True


def test_hcsf_non_conforme_si_duree_depasse_le_plafond_meme_avec_taux_faible(bien, params):
    bien["foyer"]["revenus_nets_mensuels"] = 20000
    bien["financement"]["duree_mois"] = 301
    h = indicateurs.conformite_hcsf(bien, "realiste", params)
    assert h["taux_effort"] <= params["hcsf"]["taux_effort_max"]["valeur"]
    assert h["conforme"] is False


def test_hcsf_ponderation_du_foyer_prime_sur_le_defaut_de_params(bien, params):
    bien["foyer"]["ponderation_loyers"] = 1.0
    taux = indicateurs.taux_effort_hcsf(bien, "realiste", params)
    assert taux == pytest.approx((1000 + 1176.2516441974294 + 57.5) / (5000 + 1300), abs=1e-9)


def test_hcsf_ponderation_defaut_de_params_si_absente_du_foyer(bien, params):
    del bien["foyer"]["ponderation_loyers"]
    taux = indicateurs.taux_effort_hcsf(bien, "realiste", params)
    assert taux == pytest.approx(0.377961, abs=1e-6)


# --------------------------------------------------------------------------------------------
# 2. Financement : parité avec les formes fermées, identités de l'échéancier, différés.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("capital,taux,n", [(120000, 0.0, 120), (230000, 0.037, 300), (150000, 0.015, 120)])
def test_mensualite_parite_avec_la_forme_fermee(capital, taux, n):
    assert financement.mensualite(capital, taux, n) == pytest.approx(_monthly_payment(capital, taux, n), abs=1e-9)


def test_mensualite_taux_minuscule_ne_divise_pas_par_zero():
    """1 + t == 1.0 pour t ~ 1e-18 : la forme naïve de la PMT divisait par zéro."""
    assert financement.mensualite(100000, 1e-17, 300) == pytest.approx(100000 / 300, rel=1e-9)


def test_mensualite_taux_nul_est_capital_sur_n():
    assert financement.mensualite(120000, 0.0, 120) == pytest.approx(1000.0, abs=1e-12)


def test_crd_12_mois_parite_avec_loan_balance_after_months(bien):
    ech = financement.echeancier_bien(bien)
    m = _monthly_payment(230000, 0.037, 300)
    assert financement.crd_apres(ech, 12) == pytest.approx(_loan_balance_after_months(230000, 0.037, m, 12), abs=0.01)


@pytest.mark.parametrize("type_,k", [("aucun", 0), ("partiel", 12), ("total", 12)])
def test_identites_echeancier(type_, k):
    ech = financement.echeancier(230000, 0.037, 300, type_, k)
    assert len(ech) == 300
    assert [l["mois"] for l in ech] == list(range(1, 301))
    assert sum(l["capital"] for l in ech) == pytest.approx(230000, abs=0.01)
    assert ech[-1]["crd"] == pytest.approx(0, abs=0.01)
    for ligne in ech:
        assert ligne["mensualite"] == pytest.approx(ligne["interets"] + ligne["capital"], abs=1e-9)


def test_differe_partiel_crd_constant_pendant_le_differe():
    ech = financement.echeancier(230000, 0.037, 300, "partiel", 12)
    assert all(l["crd"] == pytest.approx(230000, abs=1e-9) for l in ech[:12])
    assert all(l["capital"] == 0 for l in ech[:12])
    assert ech[12]["crd"] < 230000


def test_differe_total_capitalise_les_interets_sans_paiement():
    ech = financement.echeancier(230000, 0.037, 300, "total", 12)
    assert all(l["mensualite"] == 0 for l in ech[:12])
    assert all(l["capital"] < 0 for l in ech[:12])
    crds = [l["crd"] for l in ech[:12]]
    assert crds == sorted(crds) and crds[0] > 230000
    assert ech[11]["crd"] == pytest.approx(230000 * (1 + 0.037 / 12) ** 12, abs=1e-6)


def test_echeancier_taux_nul():
    ech = financement.echeancier(120000, 0.0, 120)
    assert len(ech) == 120
    assert all(l["interets"] == 0 and l["mensualite"] == pytest.approx(1000) for l in ech)
    assert ech[-1]["crd"] == pytest.approx(0, abs=0.01)


def test_assurance_sur_capital_initial_aussi_pendant_un_differe(bien):
    base = financement.assurance_mensuelle(bien)
    bien["financement"]["differe"] = {"type": "total", "mois": 12}
    assert financement.assurance_mensuelle(bien) == pytest.approx(base, abs=1e-12) == pytest.approx(57.5)
    assert financement.emprunt(bien) == 230000


def test_mensualite_amortissement_apres_differe(bien):
    bien["financement"]["differe"] = {"type": "partiel", "mois": 12}
    assert financement.mensualite_amortissement(bien) == pytest.approx(1206.1487, abs=1e-4)
    bien["financement"]["differe"] = {"type": "total", "mois": 12}
    assert financement.mensualite_amortissement(bien) == pytest.approx(1251.5408, abs=1e-3)


def test_cash_flow_en_regime_d_amortissement_apres_differe_total(bien, params):
    bien["financement"]["differe"] = {"type": "total", "mois": 12}
    pmt = 1251.5408311550436
    attendu = (11292.0 - 12 * (pmt + 57.5)) / 12
    assert indicateurs.cash_flow_mensuel_avant_impot(bien, "realiste") == pytest.approx(attendu, abs=1e-6)
    assert indicateurs.enrichissement_an1(bien) == pytest.approx(230000 - 238655.80899938595, abs=1e-6)


def test_emprunt_mode_fixe(bien):
    bien["financement"]["emprunt_mode"] = "fixe"
    bien["financement"]["emprunt"] = 180000
    assert financement.emprunt(bien) == 180000


# --------------------------------------------------------------------------------------------
# 3. Exploitation, monotonie des scénarios, indicateurs bornés.
# --------------------------------------------------------------------------------------------

def test_cout_total_inclut_mobilier_et_frais_d_agence_sans_les_taxer_au_dmto(bien, params):
    """Mobilier et frais d'agence sont nuls dans la fixture : sans ce test, les omettre passerait."""
    bien["mobilier"] = 4000
    bien["frais_agence_acquereur"] = 7000
    assert acquisition.cout_total(bien, params) == pytest.approx(245637 + 4000 + 7000, abs=0.01)
    assert acquisition.dmto(bien["prix_net_vendeur"], "77", params) == pytest.approx(12637, abs=0.01)
    assert acquisition.frais_acquisition(bien, params) == pytest.approx(15637, abs=0.01)
    assert financement.apport(bien, params) == pytest.approx(15637 + 11000, abs=0.01)


def test_exploitation_realiste(bien):
    s = exploitation.resoudre_scenario(bien, "realiste")
    assert exploitation.loyer_annuel_theorique(s) == pytest.approx(15600.0)
    assert exploitation.loyers_encaisses(s) == pytest.approx(14352.0)
    assert exploitation.charges(bien, s) == pytest.approx(1500 + 180 + 600 + 0 + 0 + 0.05 * 15600)


def test_charges_proportionnelles_gestion_et_gli_sur_loyers_encaisses_capex_sur_theorique(bien):
    bien["exploitation"].update({"gestion_taux": 0.07, "gli_taux": 0.03, "capex_taux": 0.04,
                                 "cfe": 100, "comptable": 400})
    s = exploitation.resoudre_scenario(bien, "realiste")
    attendu = 1500 + 180 + 600 + 100 + 400 + 0.07 * 14352 + 0.03 * 14352 + 0.04 * 15600
    assert exploitation.charges(bien, s) == pytest.approx(attendu, abs=1e-9)


def test_resoudre_scenario_accepte_un_nom_ou_un_dict(bien):
    assert exploitation.resoudre_scenario(bien, "realiste") is bien["scenarios"]["realiste"]
    d = {"loyer_mensuel_hc": 1, "vacance": 0.0}
    assert exploitation.resoudre_scenario(bien, d) is d


def test_monotonie_du_cash_flow_selon_le_scenario(bien, params):
    cf = [indicateurs.cash_flow_mensuel_avant_impot(bien, n) for n in ("pessimiste", "realiste", "optimiste")]
    assert cf[0] < cf[1] < cf[2]


# --------------------------------------------------------------------------------------------
# 4. Prix d'équilibre.
# --------------------------------------------------------------------------------------------

def test_prix_equilibre_annule_le_cash_flow_avec_dmto_et_emprunt_qui_suivent_le_prix(bien, params):
    pe = indicateurs.prix_equilibre(bien, "realiste")
    autre = copy.deepcopy(bien)
    autre["prix_net_vendeur"] = pe
    assert indicateurs.cash_flow_mensuel_avant_impot(autre, "realiste") == pytest.approx(0, abs=1e-6)
    assert financement.emprunt(autre) == pytest.approx(pe + 30000)
    assert autre["autres_frais_acquisition"] == 3000
    # Les DMTO suivent le prix : à l'équilibre, l'apport = DMTO(pe) + autres frais. Ils sont payés sur
    # l'apport et non empruntés : c'est pourquoi le prix d'équilibre lui-même n'en dépend pas.
    assert financement.apport(autre, params) == pytest.approx(pe * 0.063185 + 3000, abs=0.01)


def test_prix_equilibre_ne_modifie_pas_le_bien_passe_en_entree(bien, params):
    avant = copy.deepcopy(bien)
    indicateurs.prix_equilibre(bien, "realiste")
    assert bien == avant


def test_prix_equilibre_par_scenario_est_croissant(bien, params):
    pe = [indicateurs.prix_equilibre(bien, n) for n in ("pessimiste", "realiste", "optimiste")]
    assert pe[0] < pe[1] < pe[2]


def test_prix_equilibre_entre_1_5_et_2_fois_le_prix_est_trouve(bien):
    bien["scenarios"]["realiste"] = {"loyer_mensuel_hc": 2400, "vacance": 0.0}
    pe = indicateurs.prix_equilibre(bien, "realiste")
    assert 300000 < pe < 400000
    assert indicateurs.cash_flow_mensuel_avant_impot({**bien, "prix_net_vendeur": pe}, "realiste") == pytest.approx(0, abs=1e-6)


def test_prix_equilibre_absent_si_le_loyer_ne_couvre_pas_les_charges_meme_a_1_euro(bien, params):
    bien["scenarios"]["realiste"] = {"loyer_mensuel_hc": 100, "vacance": 0.0}
    assert indicateurs.prix_equilibre(bien, "realiste") is None


def test_prix_equilibre_absent_s_il_depasse_deux_fois_le_prix(bien, params):
    bien["scenarios"]["realiste"] = {"loyer_mensuel_hc": 100000, "vacance": 0.0}
    assert indicateurs.prix_equilibre(bien, "realiste") is None


def test_prix_equilibre_absent_en_mode_emprunt_fixe_car_le_cash_flow_ne_depend_plus_du_prix(bien, params):
    bien["financement"]["emprunt_mode"] = "fixe"
    bien["financement"]["emprunt"] = 180000
    assert indicateurs.prix_equilibre(bien, "realiste") is None


# --------------------------------------------------------------------------------------------
# 5. Divisions par zéro : l'absence se rend comme une absence (None), pas comme un crash ni un 0.
# --------------------------------------------------------------------------------------------

def test_cash_on_cash_absent_sans_apport(bien, params):
    bien["financement"]["emprunt_mode"] = "fixe"
    bien["financement"]["emprunt"] = 245637
    assert financement.apport(bien, params) == pytest.approx(0, abs=1e-9)
    assert indicateurs.cash_on_cash(bien, "realiste", params) is None


def test_cash_on_cash_absent_si_l_apport_est_negatif(bien, params):
    """Emprunter plus que le coût total : 12 × CF / apport donnerait un signe trompeur, on rend None."""
    bien["financement"]["emprunt_mode"] = "fixe"
    bien["financement"]["emprunt"] = 260000
    assert financement.apport(bien, params) == pytest.approx(-14363, abs=0.01)
    assert indicateurs.cash_on_cash(bien, "realiste", params) is None


def test_ratio_couverture_absent_sans_dette_ni_charges(bien, params):
    bien["financement"]["emprunt_mode"] = "fixe"
    bien["financement"]["emprunt"] = 0
    for cle in ("taxe_fonciere", "pno", "copro_non_recuperable", "cfe", "comptable", "capex_taux"):
        bien["exploitation"][cle] = 0
    assert indicateurs.ratio_couverture(bien, "realiste") is None


# --------------------------------------------------------------------------------------------
# 6. TRI et VAN : gardes.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("flux", [[10, 20, 30], [-10, -20, -30], [], [0, 0, 0]])
def test_tri_sans_changement_de_signe_leve_value_error(flux):
    with pytest.raises(ValueError, match="changement de signe"):
        indicateurs.tri(flux)


@pytest.mark.parametrize("flux", [[-100, 250], [-100, 0.5]])
def test_tri_hors_de_l_intervalle_de_recherche_leve_value_error(flux):
    with pytest.raises(ValueError, match="hors de"):
        indicateurs.tri(flux)


def test_tri_aux_bornes_de_l_intervalle_de_recherche():
    assert indicateurs.tri([-100, 10]) == pytest.approx(-0.9, abs=1e-9)  # proche de la borne basse -0,99
    assert indicateurs.tri([-100, 200]) == pytest.approx(1.0, abs=1e-9)  # borne haute 1,0 incluse


def test_tri_sur_des_flux_mensuels_de_25_ans_ne_deborde_pas():
    """van divise par (1 + r)^i, qui sous-déborde près de -0,99 dès 162 flux : le TRI doit passer quand même."""
    flux = [-1000.0] + [10.0] * 300
    r = indicateurs.tri(flux)
    assert r == pytest.approx(0.009395170016, abs=1e-9)
    assert indicateurs.van(r, flux) == pytest.approx(0, abs=1e-6)
    assert 0 < indicateurs.tri([-1000.0] + [10.0] * 1199) < 0.01


@pytest.mark.parametrize("flux", [[-100, float("nan"), 110], [-100, float("inf"), 110]])
def test_tri_flux_non_finis_leve_value_error(flux):
    with pytest.raises(ValueError, match="nombres finis"):
        indicateurs.tri(flux)


def test_van_est_la_somme_actualisee_des_flux_depuis_i_egal_0():
    assert indicateurs.van(0.0, [-10, 4, 6]) == pytest.approx(0.0)
    assert indicateurs.van(0.10, [100]) == pytest.approx(100.0)


# --------------------------------------------------------------------------------------------
# 7. Gardes d'entrée : chaque ValueError a son test.
# --------------------------------------------------------------------------------------------

def test_departement_absent_de_params_leve_value_error_qui_le_nomme(params):
    with pytest.raises(ValueError, match="75"):
        acquisition.dmto(200000, "75", params)


def test_fixture_incomplete_nomme_le_champ_absent():
    with pytest.raises(ValueError, match=r"champ requis absent : autres_frais_acquisition"):
        modele.charger_bien(BIEN_INCOMPLET)


CHAMPS_REQUIS = [
    "departement", "prix_net_vendeur", "autres_frais_acquisition", "travaux", "mobilier",
    "frais_agence_acquereur",
    "financement", "financement.emprunt_mode", "financement.taux_nominal", "financement.duree_mois",
    "financement.taux_assurance_annuel", "financement.differe.type", "financement.differe.mois",
    "exploitation", "exploitation.taxe_fonciere", "exploitation.pno", "exploitation.copro_non_recuperable",
    "exploitation.cfe", "exploitation.comptable", "exploitation.gestion_taux", "exploitation.gli_taux",
    "exploitation.capex_taux",
    "scenarios", "scenarios.pessimiste", "scenarios.realiste", "scenarios.optimiste",
    "scenarios.realiste.loyer_mensuel_hc", "scenarios.realiste.vacance",
    "foyer.revenus_nets_mensuels", "foyer.mensualites_existantes",
]


@pytest.mark.parametrize("chemin", CHAMPS_REQUIS)
def test_champ_requis_absent_nomme_le_chemin_exact(chemin):
    with pytest.raises(ValueError) as exc:
        modele.valider_bien(_bien_sans(chemin))
    assert str(exc.value) == f"champ requis absent : {chemin}"


def test_emprunt_fixe_exige_financement_emprunt():
    brut = _bien_modifie("financement.emprunt_mode", "fixe")
    with pytest.raises(ValueError, match=r"champ requis absent : financement\.emprunt"):
        modele.valider_bien(brut)


ENTREES_INVALIDES = [
    ("prix_net_vendeur", -1),
    ("prix_net_vendeur", 0),
    ("prix_net_vendeur", "200000"),
    ("prix_net_vendeur", True),
    ("travaux", -5),
    ("prix_net_vendeur", float("nan")),
    ("prix_net_vendeur", float("inf")),
    ("departement", 77),
    ("departement", "  "),
    ("scenarios.realiste.vacance", 1.0),
    ("scenarios.realiste.vacance", -0.1),
    ("scenarios.realiste.loyer_mensuel_hc", -1),
    ("exploitation.gestion_taux", 1.5),
    ("financement.duree_mois", 0),
    ("financement.duree_mois", 300.5),
    ("financement.taux_nominal", -0.01),
    ("financement.taux_nominal", 1.0),
    ("financement.taux_assurance_annuel", 1.0),
    ("financement.taux_assurance_annuel", -0.1),
    ("prix_net_vendeur", 10 ** 400),
    ("financement.emprunt_mode", "autre"),
    ("foyer.revenus_nets_mensuels", 0),
    ("foyer.ponderation_loyers", 1.5),
]


@pytest.mark.parametrize("chemin,valeur", ENTREES_INVALIDES)
def test_entree_invalide_nomme_le_champ(chemin, valeur):
    with pytest.raises(ValueError, match=re.escape(f"champ invalide : {chemin}")):
        modele.valider_bien(_bien_modifie(chemin, valeur))


@pytest.mark.parametrize("emprunt", [-5, "180000", None])
def test_emprunt_fixe_negatif_ou_non_numerique_leve_value_error(emprunt):
    brut = _bien_modifie("financement.emprunt_mode", "fixe")
    brut["financement"]["emprunt"] = emprunt
    with pytest.raises(ValueError, match=re.escape("champ invalide : financement.emprunt")):
        modele.valider_bien(brut)


def test_message_d_erreur_borne_l_apercu_d_un_entier_geant():
    with pytest.raises(ValueError) as exc:
        modele.valider_bien(_bien_modifie("prix_net_vendeur", 10 ** 400))
    assert len(str(exc.value)) < 200


@pytest.mark.parametrize("contenu,fragment", [
    ("{pas du json", "JSON invalide dans"),
    (BIEN_FICTIF.read_text(encoding="utf-8").replace('"mobilier": 0', '"mobilier": NaN'), "NaN"),
    (BIEN_FICTIF.read_text(encoding="utf-8").replace('"mobilier": 0', '"mobilier": Infinity'), "Infinity"),
    ("[" * 200000 + "]" * 200000, "imbrication"),
], ids=["syntaxe", "constante_NaN", "constante_Infinity", "imbrication"])
def test_charger_bien_json_illisible_leve_value_error(tmp_path, contenu, fragment):
    chemin = tmp_path / "illisible.json"
    chemin.write_text(contenu, encoding="utf-8")
    with pytest.raises(ValueError, match=fragment):
        modele.charger_bien(chemin)


def test_bien_qui_n_est_pas_un_objet_json_leve_value_error():
    with pytest.raises(ValueError, match="objet JSON"):
        modele.valider_bien([1, 2, 3])


def test_differe_type_inconnu():
    with pytest.raises(ValueError, match="type inconnu"):
        financement.echeancier(230000, 0.037, 300, "semi", 12)


def test_differe_aucun_incompatible_avec_des_mois():
    with pytest.raises(ValueError, match="incompatible"):
        financement.echeancier(230000, 0.037, 300, "aucun", 3)


@pytest.mark.parametrize("mois", [-1, 1.5, True])
def test_differe_mois_invalide(mois):
    with pytest.raises(ValueError, match="mois invalide"):
        financement.echeancier(230000, 0.037, 300, "partiel", mois)


def test_differe_mois_au_moins_egal_a_la_duree():
    with pytest.raises(ValueError, match="strictement inférieur"):
        financement.echeancier(230000, 0.037, 300, "partiel", 300)


def test_differe_incoherent_est_aussi_refuse_a_la_validation_du_bien():
    with pytest.raises(ValueError, match="strictement inférieur"):
        modele.valider_bien(_bien_modifie("financement.differe", {"type": "total", "mois": 300}))


def test_scenario_inconnu_leve_value_error(bien):
    with pytest.raises(ValueError, match="scénario inconnu"):
        exploitation.resoudre_scenario(bien, "catastrophe")


def test_echeancier_refuse_une_duree_non_positive_ou_un_capital_negatif():
    with pytest.raises(ValueError, match="durée"):
        financement.echeancier(230000, 0.037, 0)
    with pytest.raises(ValueError, match="capital"):
        financement.echeancier(-1, 0.037, 300)
    with pytest.raises(ValueError, match="durée"):
        financement.mensualite(230000, 0.037, 0)


def test_capital_nul_donne_une_mensualite_nulle_et_un_echeancier_de_zeros():
    assert financement.mensualite(0, 0.037, 300) == 0.0
    ech = financement.echeancier(0, 0.037, 12)
    assert len(ech) == 12 and all(l["mensualite"] == 0 and l["crd"] == 0 for l in ech)


def test_crd_apres_mois_invalide_leve_value_error_et_pret_solde_donne_zero(bien):
    ech = financement.echeancier_bien(bien)
    with pytest.raises(ValueError, match="mois invalide"):
        financement.crd_apres(ech, 0)
    assert financement.crd_apres(ech, 301) == 0.0
    assert financement.crd_apres(ech, 300) == pytest.approx(0, abs=0.01)


def test_pret_de_moins_de_12_mois_est_solde_a_12_mois_sans_faire_tomber_l_analyse(bien, params):
    bien["financement"]["duree_mois"] = 6
    assert indicateurs.enrichissement_an1(bien) == pytest.approx(230000, abs=0.01)
    assert analyser(bien, params)["financement"]["crd_12_mois"] == 0.0


@pytest.mark.parametrize("chemin", ["dmto.taux_inexistant", "dmto.departements.77", "hcsf.nimporte.quoi"])
def test_parametre_absent_leve_value_error_qui_le_nomme(params, chemin):
    with pytest.raises(ValueError, match=re.escape(f"paramètre absent de params.json : {chemin}")):
        modele.parametre(params, chemin)


def test_taux_effort_hcsf_sans_bloc_foyer_leve_value_error_qui_le_nomme(bien, params):
    del bien["foyer"]
    with pytest.raises(ValueError, match="champ requis absent : foyer"):
        indicateurs.taux_effort_hcsf(bien, "realiste", params)


def test_hcsf_absent_si_pas_de_bloc_foyer_est_rendu_comme_une_absence(bien, params):
    del bien["foyer"]
    sortie = analyser(bien, params)
    assert sortie["hcsf"]["calcule"] is False
    assert "foyer" in sortie["hcsf"]["raison"]
    assert "conforme" not in sortie["hcsf"]


def test_params_utilises_inclut_la_ponderation_par_defaut_quand_le_foyer_ne_la_donne_pas(bien, params):
    del bien["foyer"]["ponderation_loyers"]
    pu = analyser(bien, params)["params_utilises"]
    assert pu["hcsf.ponderation_loyers_defaut"]["valeur"] == 0.7
    assert pu["hcsf.ponderation_loyers_defaut"]["a_verifier"] is True


def test_params_utilises_sans_foyer_ne_liste_aucun_parametre_hcsf(bien, params):
    del bien["foyer"]
    assert not [c for c in analyser(bien, params)["params_utilises"] if c.startswith("hcsf")]


# --------------------------------------------------------------------------------------------
# 8. params.json : chaque paramètre est sourcé et daté, ou signalé a_verifier.
# --------------------------------------------------------------------------------------------

def _feuilles(noeud, chemin=""):
    if isinstance(noeud, dict):
        if "valeur" in noeud:
            yield chemin, noeud
        else:
            for cle, sous in noeud.items():
                if not cle.startswith("_"):
                    yield from _feuilles(sous, f"{chemin}.{cle}" if chemin else cle)


def test_params_chaque_parametre_a_sa_source_et_sa_date():
    brut = json.loads(PARAMS_JSON.read_text(encoding="utf-8"))
    feuilles = dict(_feuilles(brut))
    assert len(feuilles) >= 6
    for chemin, f in feuilles.items():
        assert isinstance(f["source"], str) and f["source"].strip(), chemin
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["verifie_le"]), chemin
        assert f.get("a_verifier", False) in (True, False), chemin


def test_params_contient_les_parametres_de_reference():
    p = modele.charger_params(local=False)
    assert p["dmto"]["departements"]["77"]["taux_departemental"]["valeur"] == 0.05
    assert p["dmto"]["taux_communal"]["valeur"] == 0.012
    assert p["dmto"]["frais_assiette"]["valeur"] == 0.0237
    assert p["hcsf"]["taux_effort_max"]["valeur"] == 0.35
    assert p["hcsf"]["duree_max_mois"]["valeur"] == 300
    assert p["hcsf"]["ponderation_loyers_defaut"]["valeur"] == 0.70


def test_params_la_ponderation_des_loyers_est_signalee_a_verifier_car_non_reglementaire():
    p = modele.charger_params()["hcsf"]["ponderation_loyers_defaut"]
    assert p["a_verifier"] is True
    assert "non réglementaire" in p["source"]


def test_params_seul_le_departement_77_est_parametre():
    assert list(modele.charger_params(local=False)["dmto"]["departements"]) == ["77"]


def test_params_0_012_apparait_une_seule_fois_pour_que_le_controle_discriminant_soit_net():
    assert PARAMS_JSON.read_text(encoding="utf-8").count("0.012") == 1


# --------------------------------------------------------------------------------------------
# 9. CLI : python -m src.immo --bien <chemin.json>
# --------------------------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, "-m", "src.immo", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


@pytest.fixture(scope="module")
def sortie_cli():
    r = _cli("--bien", str(BIEN_FICTIF))
    assert r.returncode == 0, r.stderr
    return r, json.loads(r.stdout)


CLES_CONTRAT = {"bien", "params_utilises", "acquisition", "financement", "scenarios", "prix_equilibre", "hcsf", "fiscalite"}


def test_cli_cles_de_premier_niveau_exactes(sortie_cli):
    assert set(sortie_cli[1]) == CLES_CONTRAT


def test_cli_stdout_est_du_json_pur_non_ascii_echappe_et_indente(sortie_cli):
    r, _ = sortie_cli
    assert "réelle" in r.stdout  # ensure_ascii=False
    assert r.stdout.startswith("{\n  \"")  # indent=2


def test_cli_porte_l_avertissement_de_fixture(sortie_cli):
    assert "FICTIF" in sortie_cli[1]["bien"]["_avertissement"]


def test_cli_valeurs_du_realiste_a_l_arrondi_pres(sortie_cli):
    s = sortie_cli[1]
    a, f = s["acquisition"], s["financement"]
    ind = s["scenarios"]["realiste"]["indicateurs"]
    assert a["dmto"] == pytest.approx(12637.00, abs=0.01)
    assert a["taux_dmto_global"] == pytest.approx(0.063185, abs=1e-6)
    assert a["frais_acquisition"] == pytest.approx(15637.00, abs=0.01)
    assert a["cout_total"] == pytest.approx(245637.00, abs=0.01)
    assert f["emprunt"] == pytest.approx(230000.00, abs=0.01)
    assert f["apport"] == pytest.approx(15637.00, abs=0.01)
    assert f["mensualite_hors_assurance"] == pytest.approx(1176.2516, abs=0.01)
    assert f["assurance_mensuelle"] == pytest.approx(57.50, abs=0.01)
    assert f["crd_12_mois"] == pytest.approx(224298.94, abs=0.01)
    assert ind["rendement_brut"] == pytest.approx(0.063508, abs=1e-6)
    assert ind["rendement_net"] == pytest.approx(0.045970, abs=1e-6)
    assert ind["cash_flow_mensuel_avant_impot"] == pytest.approx(-292.7516, abs=0.01)
    assert ind["cash_on_cash"] == pytest.approx(-0.224661, abs=1e-6)
    assert ind["ratio_couverture"] == pytest.approx(0.873215, abs=1e-6)
    assert ind["enrichissement_an1"] == pytest.approx(5701.06, abs=0.01)
    assert s["prix_equilibre"]["realiste"] == pytest.approx(145424.28, abs=0.01)
    assert s["hcsf"]["taux_effort"] == pytest.approx(0.377961, abs=1e-6)
    assert s["hcsf"]["conforme"] is False


def test_cli_trois_scenarios_et_trois_prix_d_equilibre(sortie_cli):
    s = sortie_cli[1]
    assert list(s["scenarios"]) == ["pessimiste", "realiste", "optimiste"]
    assert list(s["prix_equilibre"]) == ["pessimiste", "realiste", "optimiste"]
    for bloc in s["scenarios"].values():
        assert set(bloc) == {"exploitation", "indicateurs"}


def test_cli_hcsf_detaille_les_trois_scenarios(sortie_cli):
    par = sortie_cli[1]["hcsf"]["par_scenario"]
    assert list(par) == ["pessimiste", "realiste", "optimiste"]
    assert par["pessimiste"]["taux_effort"] > par["realiste"]["taux_effort"] > par["optimiste"]["taux_effort"]


def test_cli_arrondi_2_decimales_pour_les_montants_6_pour_les_ratios(sortie_cli):
    s = sortie_cli[1]
    for montant in (s["acquisition"]["cout_total"], s["financement"]["mensualite_hors_assurance"],
                    s["scenarios"]["realiste"]["indicateurs"]["cash_flow_mensuel_avant_impot"],
                    s["prix_equilibre"]["realiste"]):
        assert montant == round(montant, 2)
    for ratio in (s["scenarios"]["realiste"]["indicateurs"]["ratio_couverture"], s["hcsf"]["taux_effort"],
                  s["acquisition"]["taux_dmto_global"], s["financement"]["taux_nominal"]):
        assert ratio == round(ratio, 6)
    # le taux nominal 0,037 et l'assurance 0,003 ne doivent pas être écrasés à 2 décimales
    assert s["financement"]["taux_nominal"] == 0.037
    assert s["financement"]["taux_assurance_annuel"] == 0.003


def test_cli_params_utilises_portent_valeur_source_et_date(sortie_cli):
    pu = sortie_cli[1]["params_utilises"]
    assert pu["dmto.taux_communal"]["valeur"] == 0.012
    assert pu["dmto.departements.77.taux_departemental"]["valeur"] == 0.05
    assert pu["dmto.frais_assiette"]["valeur"] == 0.0237
    assert pu["hcsf.taux_effort_max"]["valeur"] == 0.35
    assert pu["hcsf.duree_max_mois"]["valeur"] == 300
    for chemin, p in pu.items():
        assert p["source"] and p["verifie_le"], chemin
    # la pondération du foyer (0,70) est une entrée de la fixture : le défaut de params n'est pas utilisé
    assert "hcsf.ponderation_loyers_defaut" not in pu


def test_cli_incomplet_message_sur_stderr_et_code_2():
    r = _cli("--bien", str(BIEN_INCOMPLET))
    assert r.returncode == 2
    assert "autres_frais_acquisition" in r.stderr
    assert r.stdout == ""


def test_cli_fichier_introuvable_code_2():
    r = _cli("--bien", str(FIXTURES / "n_existe_pas.json"))
    assert r.returncode == 2
    assert "n_existe_pas.json" in r.stderr


def test_cli_json_invalide_code_2(tmp_path):
    mauvais = tmp_path / "mauvais.json"
    mauvais.write_text("{pas du json", encoding="utf-8")
    r = _cli("--bien", str(mauvais))
    assert r.returncode == 2
    assert "JSON" in r.stderr


def _ecrire_bien(tmp_path, nom, modifs):
    brut = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    for chemin, valeur in modifs.items():
        cible = brut
        *debut, dernier = chemin.split(".")
        for cle in debut:
            cible = cible[cle]
        cible[dernier] = valeur
    chemin_fichier = tmp_path / f"{nom}.json"
    chemin_fichier.write_text(json.dumps(brut), encoding="utf-8")
    return chemin_fichier


ENTREES_PATHOLOGIQUES = [
    ("entier_geant", {"prix_net_vendeur": 10 ** 400}, "nombre fini"),
    ("prix_hors_limites_float", {"prix_net_vendeur": 1e308}, "JSON compliant"),
    ("differe_qui_deborde", {"financement.duree_mois": 2_000_000,
                             "financement.differe": {"type": "total", "mois": 1_000_000}}, "calcul impossible"),
]


@pytest.mark.parametrize("nom,modifs,fragment", ENTREES_PATHOLOGIQUES, ids=[e[0] for e in ENTREES_PATHOLOGIQUES])
def test_cli_entree_pathologique_code_2_sans_traceback_ni_json_invalide(tmp_path, nom, modifs, fragment):
    r = _cli("--bien", str(_ecrire_bien(tmp_path, nom, modifs)))
    assert r.returncode == 2
    assert fragment in r.stderr
    assert "Traceback" not in r.stderr
    assert r.stdout == ""


@pytest.mark.parametrize("contenu,fragment", [
    ("[" * 200000 + "]" * 200000, "imbrication"),
    (BIEN_FICTIF.read_text(encoding="utf-8").replace('"mobilier": 0', '"mobilier": NaN'), "NaN"),
    ("[1, 2, 3]", "objet JSON"),
], ids=["json_tres_imbrique", "constante_NaN", "tableau_au_lieu_d_un_objet"])
def test_cli_json_pathologique_code_2(tmp_path, contenu, fragment):
    chemin = tmp_path / "bizarre.json"
    chemin.write_text(contenu, encoding="utf-8")
    r = _cli("--bien", str(chemin))
    assert r.returncode == 2
    assert fragment in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_taux_minuscule_donne_un_resultat_valide(tmp_path):
    r = _cli("--bien", str(_ecrire_bien(tmp_path, "taux_minuscule", {"financement.taux_nominal": 1e-17})))
    assert r.returncode == 0
    assert json.loads(r.stdout)["financement"]["mensualite_hors_assurance"] == pytest.approx(230000 / 300, abs=0.01)


def test_cli_prix_equilibre_absent_signale_sur_stderr_et_json_reste_valide(tmp_path):
    brut = _bien_modifie("scenarios.pessimiste", {"loyer_mensuel_hc": 100, "vacance": 0.0})
    chemin = tmp_path / "pauvre.json"
    chemin.write_text(json.dumps(brut), encoding="utf-8")
    r = _cli("--bien", str(chemin))
    assert r.returncode == 0
    sortie = json.loads(r.stdout)
    assert sortie["prix_equilibre"]["pessimiste"] is None
    assert sortie["prix_equilibre"]["realiste"] is not None
    assert "pessimiste" in r.stderr


def test_analyser_est_serialisable_en_json_et_ne_modifie_pas_le_bien(bien, params):
    avant = copy.deepcopy(bien)
    sortie = analyser(bien, params)
    json.dumps(sortie)
    assert bien == avant


# --------------------------------------------------------------------------------------------
# 10. Compatibilité Python 3.11 (Dockerfile : python:3.11-slim ; pyproject : >=3.11).
# --------------------------------------------------------------------------------------------

MODULES = sorted(SRC_IMMO.glob("*.py"))


def test_les_modules_attendus_existent():
    assert {m.name for m in MODULES} >= {"__init__.py", "__main__.py", "modele.py", "acquisition.py",
                                         "financement.py", "exploitation.py", "indicateurs.py"}


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_python_311_pas_de_syntaxe_pep_695(module):
    source = module.read_text(encoding="utf-8")
    assert not re.search(r"^\s*type\s+\w+\s*=|def \w+\[", source, flags=re.MULTILINE)
    ast.parse(source, feature_version=(3, 11))  # rejette `type X = …` et les paramètres de type


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_python_311_pas_de_fstring_imbrique_a_guillemets_identiques(module):
    source = module.read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if not isinstance(noeud, ast.JoinedStr):
            continue
        texte = ast.get_source_segment(source, noeud)
        guillemet = re.match(r"[rRbBfF]*(\"\"\"|'''|\"|')", texte).group(1)[0]
        for sous in ast.walk(noeud):
            if isinstance(sous, ast.FormattedValue):
                assert guillemet not in ast.get_source_segment(source, sous.value), (module.name, texte)


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_from_future_annotations_en_tete_de_chaque_module(module):
    corps = ast.parse(module.read_text(encoding="utf-8")).body
    imports = [n for n in corps if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    assert imports and any(a.name == "annotations" for a in imports[0].names), module.name


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_aucune_dependance_hors_stdlib(module):
    autorises = set(sys.stdlib_module_names) | {"src"}
    for n in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        racines = []
        if isinstance(n, ast.Import):
            racines = [a.name.split(".")[0] for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            racines = [(n.module or "").split(".")[0]]
        for racine in racines:
            assert racine in autorises, (module.name, racine)
