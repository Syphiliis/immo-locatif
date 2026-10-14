"""Sortie d'une SCI à l'IS (`src/immo/sortie.py`) : bloc d'entrée `sortie`, projection année par année, revente,
liquidation et boni.

Sections 1 à 16.
Biens FICTIFS uniquement :
`bien_fictif_sci_is_sortie.json` et `bien_fictif.json` (blocs `sci` et `sortie` ajoutés en mémoire). Aucune valeur
ne vient du dépôt ; le test ne lit aucune source réelle.

Valeurs attendues : un cas de contrôle calculé à part, sans le moteur (07/10/2026), les résultats de l'année 1 de `analyser()` (`sci_is`), et des
identités comptables recalculées dans le test à partir des champs des lignes.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import analyser, fiscal_sci as fsci, modele, sortie as so  # noqa: E402
from src.immo.financement import apport, assurance_mensuelle, echeancier_bien, emprunt  # noqa: E402
from src.immo.fiscal_nom_propre import amortissements_composants  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "immo"
BIEN_SORTIE = biens_test.chemin("bien_fictif_sci_is_sortie.json")
BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_DIFFERE = biens_test.chemin("bien_fictif_differe_27ans.json")

# Blocs FICTIFS ajoutés à bien_fictif.json et bien_fictif_differe_27ans.json (sans bloc sci ni sortie).
SCI_FICTIF = {"regime": "is", "quote_part_foyer": 1.0, "duree_premier_exercice_mois": 12,
              "frais_acquisition": "incorpores", "capital_libere": True, "cca": {"montant": 0, "taux": 0},
              "distribution_annuelle": 0, "remboursement_cca_annuel": 0}
SORTIE_FICTIVE = json.loads(BIEN_SORTIE.read_text(encoding="utf-8"))["sortie"]
INDEXATIONS_NULLES = {"revalorisation_annuelle": {"pessimiste": 0.0, "realiste": 0.0, "optimiste": 0.0},
                      "indexation_loyers_annuelle": {"pessimiste": 0.0, "realiste": 0.0, "optimiste": 0.0},
                      "indexation_charges_annuelle": 0.0}
CHAMPS_LIGNE = {"annee", "loyers_theoriques", "loyers_encaisses", "charges", "interets", "assurance",
                "capital_rembourse", "crd_fin", "amortissements", "interets_cca", "resultat", "deficit_reporte",
                "imposable", "impot", "resultat_apres_is", "report_a_nouveau", "distribution", "remboursement_cca",
                "cca_restant", "tresorerie_fin"}
CENTIME = 0.005  # « au centime » : écart inférieur au demi-centime


@pytest.fixture(scope="module")
def params():
    return modele.charger_params()


def _brut(chemin: Path = BIEN_SORTIE) -> dict:
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    brut.setdefault("sci", copy.deepcopy(SCI_FICTIF))
    brut.setdefault("sortie", copy.deepcopy(SORTIE_FICTIVE))
    brut.setdefault("fiscal", {"tmi": 0.14, "annee_revenus": 2026})
    return brut


def _bien(chemin: Path = BIEN_SORTIE, *, sortie: dict | None = None, sci: dict | None = None,
          financement: dict | None = None, **racine) -> dict:
    """Bien fictif validé ; `sortie`, `sci` et `financement` complètent le bloc du même nom, `racine` le bien."""
    brut = _brut(chemin)
    brut.update(racine)
    brut["sci"].update(sci or {})
    brut["sortie"].update(sortie or {})
    brut["financement"].update(financement or {})
    return modele.valider_bien(brut)


def _projeter(bien, params, scenario="realiste", contexte=None):
    return so.projeter(bien, scenario, params, contexte)


def _raisons(p) -> str:
    return " | ".join(p["raisons"])


# --------------------------------------------------------------------------------------------
# 1. Bloc d'entrée `sortie` : un cas qui passe et un qui refuse par champ ; absent, chaque champ est nommé.
# --------------------------------------------------------------------------------------------

CHAMPS_SORTIE = ("horizon_ans", "revalorisation_annuelle", "indexation_loyers_annuelle",
                 "indexation_charges_annuelle", "classe_dpe_location", "frais_revente_taux",
                 "indemnites_remboursement_anticipe", "frais_liquidation", "politique_distribution", "option_bareme",
                 "taux_actualisation")

# (chemin sous `sortie`, valeur qui passe, valeur qui refuse)
CAS_CHAMPS = [
    ("horizon_ans", 1, 0),
    ("horizon_ans", 40, 41),
    ("horizon_ans", 12, 12.0),
    ("horizon_ans", 10, True),
    ("revalorisation_annuelle.pessimiste", -0.99, -1),
    ("revalorisation_annuelle.realiste", 0.99, 1),
    ("revalorisation_annuelle.optimiste", 0.0, "2 %"),
    ("indexation_loyers_annuelle.pessimiste", -0.01, -1.5),
    ("indexation_loyers_annuelle.realiste", 0.0115, 1.0),
    ("indexation_loyers_annuelle.optimiste", 0.035, None),
    ("indexation_charges_annuelle", -0.5, -1),
    ("indexation_charges_annuelle", 0.02, 1),
    ("classe_dpe_location", "A", "H"),
    ("classe_dpe_location", "G", "g"),
    ("frais_revente_taux", 0, 1),
    ("frais_revente_taux", 0.08, -0.01),
    ("indemnites_remboursement_anticipe", 0, -1),
    ("frais_liquidation", 264, -0.01),
    ("frais_liquidation", 0, "264 €"),
    ("politique_distribution", "annuelle", "trimestrielle"),
    ("politique_distribution", "liquidation", None),
    ("option_bareme", True, "oui"),
    ("option_bareme", False, 1),
    ("taux_actualisation", None, -1),
    ("taux_actualisation", 0.04, "4 %"),
    ("taux_actualisation", -0.5, 1),
]


def _poser(brut: dict, chemin: str, v) -> dict:
    noeud = brut["sortie"]
    *parents, feuille = chemin.split(".")
    for cle in parents:
        noeud = noeud[cle]
    noeud[feuille] = v
    return brut


@pytest.mark.parametrize("chemin,valide,invalide", CAS_CHAMPS,
                         ids=[f"{c}-{v!r}-{i!r}" for c, v, i in CAS_CHAMPS])
def test_validation_un_cas_qui_passe_et_un_qui_refuse_par_champ(chemin, valide, invalide):
    modele.valider_bien(_poser(_brut(), chemin, valide))
    with pytest.raises(ValueError, match=f"champ invalide : sortie.{chemin} = "):
        modele.valider_bien(_poser(_brut(), chemin, invalide))


def test_validation_chaque_champ_du_bloc_est_couvert():
    """Couverture comptée : les 11 champs de référence ont un cas qui passe et un cas qui refuse."""
    assert {c.split(".")[0] for c, *_ in CAS_CHAMPS} == set(CHAMPS_SORTIE)
    for nom in modele.SCENARIOS:
        for champ in ("revalorisation_annuelle", "indexation_loyers_annuelle"):
            assert f"{champ}.{nom}" in {c for c, *_ in CAS_CHAMPS}


@pytest.mark.parametrize("champ", CHAMPS_SORTIE)
def test_validation_champ_absent_nomme_sans_valeur_par_defaut(champ):
    brut = _brut()
    del brut["sortie"][champ]
    with pytest.raises(ValueError, match=f"champ requis absent : sortie.{champ}"):
        modele.valider_bien(brut)


@pytest.mark.parametrize("champ", ["revalorisation_annuelle", "indexation_loyers_annuelle"])
@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_validation_un_taux_par_scenario_absent_nomme(champ, scenario):
    brut = _brut()
    del brut["sortie"][champ][scenario]
    with pytest.raises(ValueError, match=f"champ requis absent : sortie.{champ}.{scenario}"):
        modele.valider_bien(brut)


@pytest.mark.parametrize("champ", ["revalorisation_annuelle", "indexation_loyers_annuelle"])
def test_validation_taux_par_scenario_un_nombre_seul_est_refuse(champ):
    with pytest.raises(ValueError, match=f"champ invalide : sortie.{champ} = 0.02 .*un taux par scénario"):
        modele.valider_bien(_poser(_brut(), champ, 0.02))


def test_validation_bloc_sortie_optionnel():
    brut = _brut()
    del brut["sortie"]
    modele.valider_bien(brut)


def test_validation_bloc_sortie_objet_attendu():
    brut = _brut()
    brut["sortie"] = [10]
    with pytest.raises(ValueError, match=r"champ invalide : sortie = \[10\] \(objet attendu\)"):
        modele.valider_bien(brut)


def test_validation_sortie_exige_une_sci_a_l_is():
    sans_sci = _brut()
    del sans_sci["sci"]
    with pytest.raises(ValueError, match="bloc sortie : exige un bloc sci de régime is .*sci absent"):
        modele.valider_bien(sans_sci)
    sci_ir = _brut()
    sci_ir["sci"]["regime"] = "ir"
    with pytest.raises(ValueError, match="bloc sortie : exige un bloc sci de régime is .*sci.regime = 'ir'"):
        modele.valider_bien(sci_ir)


def test_validation_analyser_valide_aussi_le_bloc_sortie(params):
    brut = _poser(_brut(), "horizon_ans", 0)
    with pytest.raises(ValueError, match="sortie.horizon_ans"):
        analyser(brut, params)


def test_fixture_du_lot_valide_et_fictive():
    bien = modele.charger_bien(BIEN_SORTIE)
    assert "FICTIF" in bien["_avertissement"]
    assert set(bien["sortie"]) == set(CHAMPS_SORTIE)
    sans_sortie = {k: v for k, v in bien.items() if k != "sortie"}
    assert sans_sortie == json.loads((biens_test.chemin("bien_fictif_sci_is.json")).read_text(encoding="utf-8")) | {
        "_avertissement": sans_sortie["_avertissement"]}


# --------------------------------------------------------------------------------------------
# 2. Amortissements : cas de contrôle de référence (base 100 000, travaux d'amélioration 20 000, 12 ans).
# --------------------------------------------------------------------------------------------

def test_cas_controle_amortissement_annee_1(params):
    a = so.amortissements_annee(100000, 20000, "amelioration", 0, 1, params)
    assert a["bati"] == pytest.approx(2850.00, abs=CENTIME)
    assert a["travaux"] == pytest.approx(1333.33, abs=CENTIME)
    assert a["total"] == pytest.approx(4183.33, abs=CENTIME)
    assert a == amortissements_composants(100000, 20000, "amelioration", 0, params)


def test_cas_controle_amortissement_annee_11_agencements_termines(params):
    """S4 : les agencements (10 ans) ne s'amortissent plus en année 11."""
    a = so.amortissements_annee(100000, 20000, "amelioration", 0, 11, params)
    assert a["bati"] == pytest.approx(2350.00, abs=CENTIME)
    assert a["total"] == pytest.approx(3683.33, abs=CENTIME)


def test_cas_controle_amortissements_cumules_sur_12_ans(params):
    cumul = sum(so.amortissements_annee(100000, 20000, "amelioration", 0, t, params)["total"] for t in range(1, 13))
    assert cumul == pytest.approx(49200.00, abs=CENTIME)


def test_cas_controle_par_la_projection(params):
    """Base 100 000 (frais d'acquisition en charges, pas d'honoraires), travaux d'amélioration 20 000, 12 ans."""
    bien = _bien(prix_net_vendeur=100000, travaux=20000, sci={"frais_acquisition": "charges"},
                 sortie={"horizon_ans": 12})
    p = _projeter(bien, params)
    assert p["base_amortissable"] == 100000 and p["travaux_immobilises"] == 20000
    assert len(p["annees"]) == 12
    assert p["annees"][0]["amortissements"]["total"] == pytest.approx(4183.33, abs=CENTIME)
    assert p["annees"][10]["amortissements"]["total"] == pytest.approx(3683.33, abs=CENTIME)
    assert sum(l["amortissements"]["total"] for l in p["annees"]) == pytest.approx(49200.00, abs=CENTIME)


def test_travaux_d_amelioration_et_mobilier_s_arretent_a_leur_duree(params):
    """Travaux d'amélioration sur 15 ans, mobilier sur 7 ans, gros œuvre sur 50 ans (fiscal.lmnp.*)."""
    a = {t: so.amortissements_annee(100000, 15000, "amelioration", 7000, t, params) for t in (7, 8, 15, 16, 26, 40)}
    assert a[7]["mobilier"] == pytest.approx(1000.0) and a[8]["mobilier"] == 0.0
    assert a[15]["travaux"] == pytest.approx(1000.0) and a[16]["travaux"] == 0.0
    assert a[26]["bati"] == pytest.approx(1000.0)  # gros œuvre seul : 100 000 × 50 % / 50
    assert a[40]["bati"] == pytest.approx(1000.0)


def test_travaux_d_entretien_non_amortis_deduits_en_annee_1_seulement(params):
    bien = _bien(travaux=40000, travaux_nature="entretien")
    p = _projeter(bien, params)
    sans = _projeter(_bien(), params)
    assert p["travaux_immobilises"] == 0.0
    assert all(l["amortissements"]["travaux"] == 0.0 for l in p["annees"])
    assert p["annees"][0]["charges_deductibles"] == pytest.approx(sans["annees"][0]["charges_deductibles"] + 40000)
    assert p["annees"][1]["charges_deductibles"] == pytest.approx(sans["annees"][1]["charges_deductibles"])


def test_frais_d_acquisition_en_charges_deduits_en_annee_1_seulement(params):
    inc = _projeter(_bien(), params)
    chg = _projeter(_bien(sci={"frais_acquisition": "charges"}), params)
    frais = 300000 * 0.063185 + 4000  # DMTO 77 (6,3185 %) + autres frais de la fixture
    assert chg["base_amortissable"] == pytest.approx(inc["base_amortissable"] - frais)
    assert chg["annees"][0]["charges_deductibles"] == pytest.approx(inc["annees"][0]["charges_deductibles"] + frais)
    assert chg["annees"][1]["charges_deductibles"] == pytest.approx(inc["annees"][1]["charges_deductibles"])


# --------------------------------------------------------------------------------------------
# 3. Dette : échéancier sommé par année, rien après la fin du prêt.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chemin,financement,horizon", [
    (BIEN_SORTIE, None, 10),
    (BIEN_SORTIE, None, 25),
    (BIEN_DIFFERE, None, 7),
    (BIEN_FICTIF, {"differe": {"type": "total", "mois": 18}}, 6),
], ids=["fixe_10_ans", "au_dela_du_pret", "differe_partiel", "differe_total"])
def test_somme_du_capital_rembourse_egale_emprunt_moins_crd_fin(params, chemin, financement, horizon):
    bien = _bien(chemin, financement=financement, sortie={"horizon_ans": horizon})
    lignes = _projeter(bien, params)["annees"]
    assert sum(l["capital_rembourse"] for l in lignes) == pytest.approx(emprunt(bien) - lignes[-1]["crd_fin"],
                                                                          abs=1e-6)


def test_dette_nulle_apres_la_fin_du_pret(params):
    lignes = _projeter(_bien(sortie={"horizon_ans": 25}), params)["annees"]  # prêt de 240 mois
    assert lignes[19]["crd_fin"] == pytest.approx(0.0, abs=1e-6) and lignes[19]["interets"] > 0
    for l in lignes[20:]:
        assert (l["interets"], l["capital_rembourse"], l["assurance"], l["crd_fin"]) == (0.0, 0.0, 0.0, 0.0)


def test_dette_annee_2_mois_13_a_24(params):
    bien = _bien()
    mois = echeancier_bien(bien)[12:24]
    l2 = _projeter(bien, params)["annees"][1]
    assert l2["interets"] == pytest.approx(sum(m["interets"] for m in mois))
    assert l2["capital_rembourse"] == pytest.approx(sum(m["capital"] for m in mois))
    assert l2["assurance"] == pytest.approx(12 * assurance_mensuelle(bien))
    assert l2["crd_fin"] == pytest.approx(mois[-1]["crd"])


# --------------------------------------------------------------------------------------------
# 4. Année 1, indexations nulles = année 1 de `analyser()` pour `sci_is`.
# --------------------------------------------------------------------------------------------

VARIANTES_AN1 = {
    "fixture_du_lot": (BIEN_SORTIE, {}, {}),
    "deficit_bien_fictif": (BIEN_FICTIF, {}, {}),
    "frais_en_charges": (BIEN_SORTIE, {"frais_acquisition": "charges"}, {}),
    "travaux_entretien": (BIEN_SORTIE, {}, {"travaux": 40000, "travaux_nature": "entretien"}),
    "compte_courant_remunere": (BIEN_SORTIE, {"cca": {"montant": 20000, "taux": 0.05}}, {}),
    "premier_exercice_18_mois": (BIEN_SORTIE, {"duree_premier_exercice_mois": 18,
                                               "cca": {"montant": 20000, "taux": 0.03}}, {}),
    "capital_non_libere": (BIEN_SORTIE, {"capital_libere": False}, {}),
}


@pytest.mark.parametrize("scenario", modele.SCENARIOS)
@pytest.mark.parametrize("variante", VARIANTES_AN1)
def test_annee_1_indexations_nulles_egale_analyser_sci_is(params, variante, scenario):
    chemin, sci, racine = VARIANTES_AN1[variante]
    bien = _bien(chemin, sci=sci, sortie=INDEXATIONS_NULLES, **racine)
    attendu = analyser(bien, params)["fiscalite"]["scenarios"][scenario]["regimes"]["sci_is"]
    l1 = _projeter(bien, params, scenario)["annees"][0]
    assert l1["annee"] == 1
    for cle in ("bati", "travaux", "mobilier", "total"):
        assert l1["amortissements"][cle] == pytest.approx(attendu["amortissements"][cle], abs=1e-9), cle
    assert l1["charges_deductibles"] == pytest.approx(attendu["charges_deductibles"], abs=1e-9)
    assert l1["resultat"] == pytest.approx(attendu["resultat_fiscal"], abs=1e-9)
    assert l1["imposable"] == pytest.approx(attendu["imposable"], abs=1e-9)
    assert l1["impot"] == pytest.approx(attendu["impot_total"], abs=1e-9)
    assert l1["deficit_reporte"] == pytest.approx(attendu["deficit_reporte"], abs=1e-9)
    assert l1["resultat_apres_is"] == pytest.approx(attendu["resultat_apres_is"], abs=1e-9)
    assert l1["interets_cca"]["verses"] == pytest.approx(attendu["interets_cca_verses"], abs=1e-9)
    assert l1["interets_cca"]["deductibles"] == pytest.approx(attendu["interets_cca_deductibles"], abs=1e-9)


def test_annee_1_ne_depend_pas_des_indexations(params):
    a = _projeter(_bien(sortie=INDEXATIONS_NULLES), params, "optimiste")["annees"][0]
    b = _projeter(_bien(), params, "optimiste")["annees"][0]
    assert a == b


# --------------------------------------------------------------------------------------------
# 5. Indexation des loyers et des charges ; aucune révision pour un logement F ou G (S13).
# --------------------------------------------------------------------------------------------

def test_classe_d_loyers_indexes(params):
    bien = _bien(sortie={"classe_dpe_location": "D"})
    p = _projeter(bien, params, "optimiste")  # indexation des loyers 1,5 % dans la fixture
    l1 = p["annees"][0]
    for l in p["annees"]:
        k = 1.015 ** (l["annee"] - 1)
        assert l["loyers_theoriques"] == pytest.approx(4400 * 12 * k)
        assert l["loyers_encaisses"] == pytest.approx(l1["loyers_encaisses"] * k)
    assert "17-1" not in _raisons(p)


@pytest.mark.parametrize("classe", ["F", "G"])
def test_classe_f_ou_g_indexation_forcee_a_zero_avec_la_raison(params, classe):
    p = _projeter(_bien(sortie={"classe_dpe_location": classe}), params, "optimiste")
    assert {l["loyers_theoriques"] for l in p["annees"]} == {4400 * 12}
    raison = next(r for r in p["raisons"] if "17-1" in r)
    assert f"classe DPE {classe}" in raison and "indexation des loyers forcée à 0" in raison
    assert "1,5 %" in raison  # le taux d'entrée écarté est dit


def test_charges_fixes_indexees_gestion_gli_capex_sur_les_loyers_de_l_annee(params):
    bien = _bien(exploitation={"taxe_fonciere": 2500, "pno": 300, "copro_non_recuperable": 400, "cfe": 100,
                               "comptable": 1200, "gestion_taux": 0.07, "gli_taux": 0.03, "capex_taux": 0.05})
    p = _projeter(bien, params, "realiste")  # charges à 2 %, loyers à 1 %
    for l in p["annees"]:
        fixes = (2500 + 300 + 400 + 100 + 1200) * 1.02 ** (l["annee"] - 1)
        assert l["charges"] == pytest.approx(fixes + 0.10 * l["loyers_encaisses"] + 0.05 * l["loyers_theoriques"])


# --------------------------------------------------------------------------------------------
# 6. IS année par année : report des déficits.
# --------------------------------------------------------------------------------------------

def test_deficit_de_l_annee_1_impute_sur_l_annee_2(params):
    bien = _bien(travaux=40000, travaux_nature="entretien", sortie=INDEXATIONS_NULLES)
    l1, l2 = _projeter(bien, params)["annees"][:2]
    assert l1["resultat"] < 0
    assert (l1["imposable"], l1["impot"]) == (0.0, 0.0)
    assert l1["deficit_reporte"] == pytest.approx(-l1["resultat"])
    assert l2["resultat"] > l1["deficit_reporte"]
    assert l2["imposable"] == pytest.approx(l2["resultat"] - l1["deficit_reporte"])
    assert l2["deficit_reporte"] == 0.0
    assert l2["impot"] == pytest.approx(0.15 * l2["imposable"])  # sous la limite de 42 500 €


def test_deficits_reportes_d_annee_en_annee_tant_que_le_resultat_est_negatif(params):
    """bien_fictif.json en SCI à l'IS : résultat négatif plusieurs années, le déficit s'accumule."""
    lignes = _projeter(_bien(BIEN_FICTIF, sortie={"horizon_ans": 3}), params)["annees"]
    assert all(l["resultat"] < 0 and l["impot"] == 0.0 for l in lignes)
    assert lignes[2]["deficit_reporte"] == pytest.approx(-sum(l["resultat"] for l in lignes))


def test_is_annee_2_sur_12_mois_apres_un_premier_exercice_de_18_mois(params):
    p = _projeter(_bien(sci={"duree_premier_exercice_mois": 18}), params)
    l1, l2 = p["annees"][:2]
    assert l1["impot"] == pytest.approx(0.15 * l1["imposable"])  # limite proratisée à 63 750 €
    assert l2["imposable"] > 0
    assert any("18 mois" in r for r in p["raisons"])


# --------------------------------------------------------------------------------------------
# 7. Distributions : plafonnées par le report à nouveau, puis par la trésorerie (S7 : pas de réserve légale).
# --------------------------------------------------------------------------------------------

def _tresorerie_avant_versements(lignes, i) -> float:
    l = lignes[i]
    avant = lignes[i - 1]["tresorerie_fin"] if i else 0.0
    return (avant + l["loyers_encaisses"] - l["charges"] - l["interets"] - l["capital_rembourse"] - l["assurance"]
            - l["interets_cca"]["verses"] - l["impot"])


def test_distribution_plafonnee_par_le_report_a_nouveau_avec_la_raison(params):
    p = _projeter(_bien(sci={"distribution_annuelle": 50000}), params)
    l1 = p["annees"][0]
    assert l1["distribution"] == pytest.approx(24354.04, abs=CENTIME)  # résultat après IS, TABLEAU_FIXTURE F2
    assert l1["distribution"] == pytest.approx(l1["resultat_apres_is"])
    assert _tresorerie_avant_versements(p["annees"], 0) > l1["distribution"]  # la trésorerie ne joue pas
    assert l1["report_a_nouveau"] == pytest.approx(0.0, abs=1e-9)
    raison = next(r for r in p["raisons"] if "report à nouveau" in r)
    assert "année 1" in raison or "années 1" in raison
    assert "L. 232-10" in raison  # S7 : pas de réserve légale pour une SCI
    assert not any("trésorerie disponible" in r for r in p["raisons"])


def test_distribution_plafonnee_par_le_report_a_nouveau_puis_par_la_tresorerie(params):
    """Prêt sur 5 ans : capital remboursé > amortissements, la trésorerie passe sous le report à nouveau."""
    p = _projeter(_bien(sci={"distribution_annuelle": 50000}, financement={"duree_mois": 60}), params)
    l1 = p["annees"][0]
    treso = _tresorerie_avant_versements(p["annees"], 0)
    assert 0 < treso < l1["resultat_apres_is"] < 50000
    assert l1["distribution"] == pytest.approx(treso)
    assert l1["tresorerie_fin"] == pytest.approx(0.0, abs=1e-6)
    assert any("report à nouveau" in r for r in p["raisons"])
    assert any("trésorerie disponible" in r for r in p["raisons"])


def test_distribution_plafonnee_par_la_tresorerie_seule(params):
    p = _projeter(_bien(sci={"distribution_annuelle": 15000}, financement={"duree_mois": 60}), params)
    l1 = p["annees"][0]
    treso = _tresorerie_avant_versements(p["annees"], 0)
    assert treso < 15000 < l1["resultat_apres_is"]
    assert l1["distribution"] == pytest.approx(treso)
    assert any("trésorerie disponible" in r for r in p["raisons"])
    assert not any("report à nouveau" in r for r in p["raisons"])


def test_distribution_annuelle_non_plafonnee_sans_raison(params):
    p = _projeter(_bien(), params)  # 10 000 €/an, sous le résultat après IS et la trésorerie
    assert all(l["distribution"] == 10000 for l in p["annees"])
    assert not any("plafonné" in r for r in p["raisons"])


def test_politique_liquidation_aucune_distribution_en_cours_de_detention(params):
    p = _projeter(_bien(sortie={"politique_distribution": "liquidation"}), params)
    assert all(l["distribution"] == 0.0 for l in p["annees"])
    assert p["annees"][-1]["report_a_nouveau"] == pytest.approx(sum(l["resultat_apres_is"] for l in p["annees"]))


def test_report_a_nouveau_cumule_resultats_apres_is_moins_distributions(params):
    lignes = _projeter(_bien(sci={"distribution_annuelle": 30000}), params)["annees"]
    ran = 0.0
    for l in lignes:
        ran += l["resultat_apres_is"] - l["distribution"]
        assert l["report_a_nouveau"] == pytest.approx(ran)


# --------------------------------------------------------------------------------------------
# 8. Comptes courants, apports en capital, trésorerie.
# --------------------------------------------------------------------------------------------

def test_remboursement_de_compte_courant_plafonne_au_solde(params):
    bien = _bien(sci={"cca": {"montant": 5000, "taux": 0.02}, "remboursement_cca_annuel": 2000},
                 sortie={"politique_distribution": "liquidation"})
    p = _projeter(bien, params)
    lignes = p["annees"]
    assert [l["remboursement_cca"] for l in lignes[:4]] == [2000, 2000, 1000, 0.0]
    assert [l["cca_restant"] for l in lignes[:4]] == [3000, 1000, 0, 0]
    # intérêts sur le solde d'ouverture de l'année : 5 000, puis 3 000, puis 1 000, puis 0
    assert [l["interets_cca"]["verses"] for l in lignes[:4]] == pytest.approx([100.0, 60.0, 20.0, 0.0])
    assert any("solde du compte courant" in r and "année 3" in r for r in p["raisons"])


def test_remboursement_de_compte_courant_plafonne_a_la_tresorerie(params):
    bien = _bien(sci={"distribution_annuelle": 50000, "cca": {"montant": 5000, "taux": 0.0},
                      "remboursement_cca_annuel": 2000}, financement={"duree_mois": 60})
    p = _projeter(bien, params)
    l1 = p["annees"][0]
    assert l1["remboursement_cca"] == 0.0 and l1["cca_restant"] == 5000
    assert any("remboursement de compte courant" in r and "plafonné à la trésorerie" in r for r in p["raisons"])


def test_apports_en_capital_apport_moins_compte_courant_convention_dite(params):
    bien = _bien(sci={"cca": {"montant": 20000, "taux": 0.0}})
    p = _projeter(bien, params)
    assert p["apports_capital"] == pytest.approx(apport(bien, params) - 20000)
    assert any("apports en capital" in r and "sci.cca.montant" in r for r in p["raisons"])


def test_apports_en_capital_negatifs_refuses(params):
    bien = _bien(sci={"cca": {"montant": 400000, "taux": 0.0}})
    with pytest.raises(ValueError, match="apports en capital négatifs"):
        _projeter(bien, params)


def test_tresorerie_de_la_sci_identite_annee_par_annee(params):
    bien = _bien(sci={"distribution_annuelle": 20000, "cca": {"montant": 30000, "taux": 0.03},
                      "remboursement_cca_annuel": 4000})
    lignes = _projeter(bien, params)["annees"]
    for i, l in enumerate(lignes):
        assert l["tresorerie_fin"] == pytest.approx(_tresorerie_avant_versements(lignes, i) - l["distribution"]
                                                    - l["remboursement_cca"] + l["apport_cca"])


def test_manque_de_tresorerie_apporte_en_compte_courant(params):
    """Convention du moteur : bien_fictif.json a un cash-flow avant impôt négatif ; le manque de
    fin d'année est apporté par les associés en compte courant, la trésorerie revient à 0 et l'avance rejoint le solde
    du compte courant ; une raison dit le total apporté sur la durée."""
    p = _projeter(_bien(BIEN_FICTIF, sortie={"horizon_ans": 3}), params)
    lignes, cumul = p["annees"], 0.0
    for i, l in enumerate(lignes):
        assert l["tresorerie_fin"] == 0.0 and l["distribution"] == 0.0 and l["remboursement_cca"] == 0.0
        assert l["apport_cca"] == pytest.approx(-_tresorerie_avant_versements(lignes, i)) and l["apport_cca"] > 0
        cumul += l["apport_cca"]
        assert l["cca_restant"] == pytest.approx(cumul)
    raison = next(r for r in p["raisons"] if "apportent le manque en compte courant" in r)
    assert so._euros(cumul) in raison and "années 1 à 3" in raison
    assert not any("négative" in r for r in p["raisons"])


def test_apport_en_compte_courant_porte_interet_au_taux_du_compte_courant(params):
    """Même taux et même traitement que le compte courant d'entrée : intérêts sur le solde d'ouverture."""
    p = _projeter(_bien(BIEN_FICTIF, sci={"cca": {"montant": 0, "taux": 0.02}}, sortie={"horizon_ans": 3}), params)
    l1, l2, l3 = p["annees"]
    assert l1["interets_cca"]["verses"] == 0.0 and l1["apport_cca"] > 0
    assert l2["interets_cca"]["verses"] == pytest.approx(0.02 * l1["cca_restant"])
    assert l3["interets_cca"]["verses"] == pytest.approx(0.02 * l2["cca_restant"])


def test_aucun_apport_en_compte_courant_si_la_tresorerie_suffit(params):
    p = _projeter(modele.charger_bien(BIEN_SORTIE), params)
    assert all(l["apport_cca"] == 0.0 for l in p["annees"])
    assert not any("apportent le manque" in r for r in p["raisons"])


# --------------------------------------------------------------------------------------------
# 9. Forme de la projection.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_projection_une_ligne_par_annee_et_champs_de_reference(params, scenario):
    p = _projeter(modele.charger_bien(BIEN_SORTIE), params, scenario)
    assert [l["annee"] for l in p["annees"]] == list(range(1, 11))
    for l in p["annees"]:
        assert CHAMPS_LIGNE <= set(l)
        assert set(l["amortissements"]) == {"bati", "travaux", "mobilier", "total"}
        assert set(l["interets_cca"]) == {"verses", "deductibles"}
    assert isinstance(p["raisons"], list) and all(isinstance(r, str) for r in p["raisons"])


def test_projection_ne_modifie_pas_le_bien(params):
    bien = modele.charger_bien(BIEN_SORTIE)
    avant = copy.deepcopy(bien)
    _projeter(bien, params)
    assert bien == avant


def test_projection_exige_le_bloc_sortie_et_un_scenario_connu(params):
    brut = _brut()
    del brut["sortie"]
    with pytest.raises(ValueError, match="champ requis absent : sortie"):
        so.projeter(brut, "realiste", params)
    with pytest.raises(ValueError, match="scénario inconnu"):
        so.projeter(_bien(), "median", params)


def test_projection_annee_du_contexte_pour_la_cloture_du_compte_courant(params):
    """Clôture au 31/12/2025 couverte par la table (4,55 %) : aucune hypothèse à vérifier en année 1."""
    bien = _bien(sci={"cca": {"montant": 10000, "taux": 0.04}})
    p = _projeter(bien, params, contexte={"annee": 2025, "tmi": 0.14})
    assert p["annees"][0]["interets_cca"]["deductibles"] == pytest.approx(400.0)
    raison = next(r for r in p["raisons"] if "dernier taux maximal publié" in r)
    assert "année 1" not in raison and "années 2" in raison


# --------------------------------------------------------------------------------------------
# 10. Revente et liquidation : cas de contrôle de référence, au centime (base 100 000, travaux 20 000, revente fin d'année 12).
# --------------------------------------------------------------------------------------------

def _cas_liquidation(params):
    return so.liquider(63825.0, 15000.0, 1000.0, 0.0, params)


def test_cas_controle_valeur_nette_comptable(params):
    """S2, S4 : le terrain reste dans la base, jamais amorti ; amortissements cumulés de la projection."""
    cumul = sum(so.amortissements_annee(100000, 20000, "amelioration", 0, t, params)["total"] for t in range(1, 13))
    assert so.valeur_nette_comptable(100000, 20000, 0, cumul) == pytest.approx(70800.00, abs=CENTIME)


def test_cas_controle_plus_value(params):
    assert so.plus_value_cession(130000, 130000 * 0.05, 70800) == pytest.approx(52700.00, abs=CENTIME)


def test_cas_controle_is_de_l_annee_de_cession(params):
    """S1, S3 : résultat courant 3 000 + plus-value 52 700 = 55 700 ; 15 % × 42 500 + 25 % × 13 200."""
    i = so.is_annee_cession(3000.0, 52700.0, 0.0, 12, params)
    assert i["resultat"] == pytest.approx(55700.00, abs=CENTIME)
    assert (i["base_taux_reduit"], i["base_taux_normal"]) == (pytest.approx(42500.0), pytest.approx(13200.0))
    assert i["impot"] == pytest.approx(9675.00, abs=CENTIME)


def test_cas_controle_actif_apres_cession():
    assert so.actif_apres_cession(10000.0, 130000.0, 6500.0, 60000.0, 0.0, 9675.0) == pytest.approx(63825.00,
                                                                                                    abs=CENTIME)


def test_cas_controle_liquidation_au_centime(params):
    """S8, S9, S10 : comptes courants déduits, droit de partage 2,5 % sur la masse, boni = masse - droit - apports."""
    liq = _cas_liquidation(params)
    assert liq["actif_net_partage"] == pytest.approx(48825.00, abs=1e-9)
    assert liq["droit_partage"] == pytest.approx(1220.625, abs=1e-9)
    assert liq["boni"] == pytest.approx(46604.375, abs=1e-9)
    assert (liq["cca_rembourses"], liq["apports_rembourses"]) == (15000.0, 1000.0)


def test_cas_controle_pfu_et_recu_par_les_associes(params):
    liq = _cas_liquidation(params)
    imp = so.imposer_boni(liq["boni"], 0.14, False, params)
    assert imp["regime"] == "pfu"
    assert imp["impot"] == pytest.approx(14633.77375, abs=1e-6)
    assert imp["net"] == pytest.approx(46604.375 - 14633.77375, abs=1e-6)
    assert so.recu_associes(liq, imp) == pytest.approx(47970.60125, abs=1e-6)


def test_cas_controle_enchaine_de_bout_en_bout(params):
    """Toutes les étapes à la suite, des amortissements de la projection au reçu (47 970,60 au centime)."""
    bien = _bien(prix_net_vendeur=100000, travaux=20000, sci={"frais_acquisition": "charges"},
                 sortie={"horizon_ans": 12})
    cumul = sum(l["amortissements"]["total"] for l in _projeter(bien, params)["annees"])
    vnc = so.valeur_nette_comptable(100000, 20000, 0, cumul)
    pv = so.plus_value_cession(130000, 130000 * 0.05, vnc)
    impot = so.is_annee_cession(3000.0, pv, 0.0, 12, params)["impot"]
    liq = so.liquider(so.actif_apres_cession(10000.0, 130000.0, 6500.0, 60000.0, 0.0, impot), 15000.0, 1000.0, 0.0,
                      params)
    assert so.recu_associes(liq, so.imposer_boni(liq["boni"], 0.14, False, params)) == pytest.approx(47970.60,
                                                                                                    abs=CENTIME)


# --------------------------------------------------------------------------------------------
# 11. Revente : prix revalorisé, plus-value sur la valeur nette comptable, année N refaite, prêt soldé.
# --------------------------------------------------------------------------------------------

def _revendre(bien, params, scenario="realiste"):
    return so.revendre(bien, scenario, params, None, so.projeter(bien, scenario, params))


@pytest.mark.parametrize("scenario,reval", [("pessimiste", -0.01), ("realiste", 0.01), ("optimiste", 0.02)])
def test_revente_fixture_du_lot(params, scenario, reval):
    bien = modele.charger_bien(BIEN_SORTIE)
    p = so.projeter(bien, scenario, params)
    r = so.revendre(bien, scenario, params, None, p)
    l10 = p["annees"][9]
    assert r["annee"] == 10
    assert r["prix_revente"] == pytest.approx(300000 * (1 + reval) ** 10)
    assert r["frais_revente"] == pytest.approx(r["prix_revente"] * 0.05)
    assert r["amortissements_cumules"] == pytest.approx(sum(l["amortissements"]["total"] for l in p["annees"]))
    assert r["valeur_nette_comptable"] == pytest.approx(322955.50 - r["amortissements_cumules"])  # base, frais inclus
    assert r["plus_value"] == pytest.approx(r["prix_revente"] - r["frais_revente"] - r["valeur_nette_comptable"])
    assert r["is_sans_cession"] == l10["impot"]
    attendu = fsci.impot_societes(l10["resultat"] + r["plus_value"], 12, params)["impot"]  # aucun déficit reporté
    assert r["is_avec_cession"] == pytest.approx(attendu)
    assert r["crd_rembourse"] == l10["crd_fin"] and r["indemnites_remboursement_anticipe"] == 1500
    assert r["tresorerie_avant_is"] == pytest.approx(l10["tresorerie_fin"] + l10["impot"])
    assert r["actif_apres_cession"] == pytest.approx(r["tresorerie_avant_is"] + r["prix_revente"] - r["frais_revente"]
                                                     - l10["crd_fin"] - 1500 - r["is_avec_cession"])


def test_revente_dit_l_is_sans_et_avec_la_cession(params):
    r = _revendre(modele.charger_bien(BIEN_SORTIE), params)
    assert r["plus_value"] > 0 and r["is_avec_cession"] > r["is_sans_cession"] > 0
    assert any("219 I-a quater" in x and "abattement" in x for x in r["raisons"])


def test_moins_value_deduite_du_resultat_de_l_annee_n_is_qui_baisse(params):
    """S2 : une moins-value est négative et se déduit du résultat de l'année N."""
    assert so.plus_value_cession(100000, 5000, 120000) == pytest.approx(-25000.0)
    sans = so.is_annee_cession(30000.0, 0.0, 0.0, 12, params)["impot"]
    avec = so.is_annee_cession(30000.0, -10000.0, 0.0, 12, params)
    assert avec["resultat"] == pytest.approx(20000.0)
    assert sans == pytest.approx(4500.0) and avec["impot"] == pytest.approx(3000.0)
    bien = _bien(sortie={"revalorisation_annuelle": {"pessimiste": -0.2, "realiste": 0.01, "optimiste": 0.02}})
    r = _revendre(bien, params, "pessimiste")
    assert r["plus_value"] < 0 and r["is_avec_cession"] < r["is_sans_cession"]
    assert any("moins-value" in x for x in r["raisons"])


def test_revente_impute_le_deficit_reporte_de_l_annee_n_moins_1(params):
    reval = {"pessimiste": 0.10, "realiste": 0.10, "optimiste": 0.10}
    bien = _bien(BIEN_FICTIF, sortie={"horizon_ans": 3, "revalorisation_annuelle": reval})
    p = so.projeter(bien, "realiste", params)
    r = so.revendre(bien, "realiste", params, None, p)
    d2 = p["annees"][1]["deficit_reporte"]
    assert d2 > 0 and r["plus_value"] > 0
    assert r["is_detail"]["deficit_anterieur"] == pytest.approx(d2)
    assert r["is_detail"]["imposable"] == pytest.approx(p["annees"][2]["resultat"] + r["plus_value"] - d2)
    assert r["is_avec_cession"] == pytest.approx(0.15 * r["is_detail"]["imposable"])


def test_deficit_non_impute_perdu_a_la_liquidation_dit(params):
    bien = _bien(BIEN_FICTIF, sortie={"horizon_ans": 3})  # revalorisation 1 % : moins-value, déficits restants
    r = _revendre(bien, params)
    assert r["is_detail"]["deficit_reporte"] > 0
    assert any("déficit" in x and "perdu" in x for x in r["raisons"])


def test_indemnites_de_remboursement_anticipe_seulement_si_le_pret_court(params):
    r = _revendre(_bien(sortie={"horizon_ans": 25}), params)  # prêt de 240 mois soldé en année 20
    assert (r["crd_rembourse"], r["indemnites_remboursement_anticipe"]) == (0.0, 0.0)
    assert any("indemnités de remboursement anticipé" in x and "soldé" in x for x in r["raisons"])


def test_ira_non_dues_quand_l_horizon_egale_la_duree_du_pret(params):
    """Défaut corrigé (A) : 150 000 € à 3,25 % sur 240 mois, revente en fin d'année 20 ; le dernier capital
    restant dû de l'échéancier est un résidu flottant (7e-11) : prêt soldé, aucune IRA."""
    bien = _bien(financement={"emprunt": 150000, "taux_nominal": 0.0325}, sortie={"horizon_ans": 20})
    r = _revendre(bien, params)
    assert (r["crd_rembourse"], r["indemnites_remboursement_anticipe"]) == (0.0, 0.0)
    assert any("non dues" in x and "soldé" in x for x in r["raisons"])
    assert not any(x.startswith("indemnités de remboursement anticipé (") for x in r["raisons"])
    avant = _revendre(_bien(financement={"emprunt": 150000, "taux_nominal": 0.0325}, sortie={"horizon_ans": 19}),
                      params)
    assert avant["crd_rembourse"] > 0 and avant["indemnites_remboursement_anticipe"] == 1500


def test_revente_annee_1_duree_du_premier_exercice(params):
    bien = _bien(sci={"duree_premier_exercice_mois": 18}, sortie={"horizon_ans": 1})
    r = _revendre(bien, params)
    assert r["is_detail"]["duree_exercice_mois"] == 18 and r["is_detail"]["deficit_anterieur"] == 0.0


def test_revente_refuse_une_projection_d_un_autre_horizon(params):
    bien = _bien()
    with pytest.raises(ValueError, match="projection"):
        so.revendre(bien, "realiste", params, None, so.projeter(_bien(sortie={"horizon_ans": 5}), "realiste", params))


def test_identite_de_bilan_a_la_sortie(params):
    """Actif après cession - comptes courants = apports + Σ résultats + plus-value - Σ IS (année N avec cession)
    - Σ distributions - Σ capex - Σ intérêts de compte courant non déduits - indemnités de remboursement anticipé."""
    bien = _bien(sci={"cca": {"montant": 30000, "taux": 0.06}, "remboursement_cca_annuel": 2000,
                      "distribution_annuelle": 15000, "frais_acquisition": "charges"},
                 travaux=25000, mobilier=6000)
    p = so.projeter(bien, "optimiste", params)
    r = so.revendre(bien, "optimiste", params, None, p)
    lignes = p["annees"]
    capex = sum(0.05 * l["loyers_theoriques"] for l in lignes)
    non_deduits = sum(l["interets_cca"]["verses"] - l["interets_cca"]["deductibles"] for l in lignes)
    assert non_deduits > 0
    impots = sum(l["impot"] for l in lignes) - r["is_sans_cession"] + r["is_avec_cession"]
    attendu = (p["apports_capital"] + sum(l["resultat"] for l in lignes) + r["plus_value"] - impots
               - sum(l["distribution"] for l in lignes) - capex - non_deduits - 1500)
    assert r["actif_apres_cession"] - lignes[-1]["cca_restant"] == pytest.approx(attendu, abs=1e-6)


def test_identite_de_bilan_avec_apports_en_compte_courant(params):
    """bien_fictif.json, compte courant rémunéré à 5 % (déduit au plus au taux maximal) : les apports du manque de
    trésorerie entrent en trésorerie et au passif ; l'identité de bilan ne bouge pas."""
    reval = {"pessimiste": 0.03, "realiste": 0.03, "optimiste": 0.03}
    bien = _bien(BIEN_FICTIF, sci={"cca": {"montant": 0, "taux": 0.05}}, sortie={"revalorisation_annuelle": reval})
    p = so.projeter(bien, "realiste", params)
    r = so.revendre(bien, "realiste", params, None, p)
    lignes = p["annees"]
    assert sum(l["apport_cca"] for l in lignes) > 0
    capex = sum(0.05 * l["loyers_theoriques"] for l in lignes)
    non_deduits = sum(l["interets_cca"]["verses"] - l["interets_cca"]["deductibles"] for l in lignes)
    assert non_deduits > 0
    impots = sum(l["impot"] for l in lignes) - r["is_sans_cession"] + r["is_avec_cession"]
    attendu = (p["apports_capital"] + sum(l["resultat"] for l in lignes) + r["plus_value"] - impots
               - sum(l["distribution"] for l in lignes) - capex - non_deduits - 1500)
    assert r["actif_apres_cession"] - lignes[-1]["cca_restant"] == pytest.approx(attendu, abs=1e-6)


# --------------------------------------------------------------------------------------------
# 12. Liquidation et boni : comptes courants déduits avant le droit (S10), mali, droit de partage paramétré.
# --------------------------------------------------------------------------------------------

def test_comptes_courants_deduits_avant_le_droit_de_partage(params):
    """S10 : retirer la déduction des comptes courants change le droit (+ 2,5 % × 15 000 = 375)."""
    avec = _cas_liquidation(params)
    sans = so.liquider(63825.0, 0.0, 1000.0, 0.0, params)  # même actif, aucun compte courant au passif
    assert avec["droit_partage"] == pytest.approx(0.025 * 48825)
    assert sans["droit_partage"] == pytest.approx(0.025 * 63825)
    assert sans["droit_partage"] - avec["droit_partage"] == pytest.approx(375.0)


def test_frais_de_liquidation_deduits_de_l_actif_partage(params):
    liq = so.liquider(63825.0, 15000.0, 1000.0, 400.0, params)
    assert liq["actif_net_partage"] == pytest.approx(48425.0)
    assert liq["droit_partage"] == pytest.approx(0.025 * 48425)


def test_mali_aucun_impot_raison_dite(params):
    liq = so.liquider(5000.0, 0.0, 10000.0, 0.0, params)
    assert liq["boni"] == pytest.approx(5000 - 125 - 10000) and liq["mali"] is True
    assert liq["apports_rembourses"] == pytest.approx(4875.0)
    imp = so.imposer_boni(liq["boni"], 0.14, False, params)
    assert (imp["impot"], imp["net"]) == (0.0, 0.0)
    assert any("mali" in x and "aucun impôt" in x for x in imp["raisons"])
    assert so.recu_associes(liq, imp) == pytest.approx(4875.0)


def test_actif_insuffisant_pour_les_comptes_courants(params):
    """Défaut corrigé (B) : la créance de compte courant perdue (5 500) ne se mêle pas au mali, qui ne
    porte que sur les apports (1 000) ; rien à partager, aucun droit."""
    liq = so.liquider(10000.0, 15000.0, 1000.0, 500.0, params)
    assert liq["cca_rembourses"] == pytest.approx(9500.0) and liq["cca_non_rembourses"] == pytest.approx(5500.0)
    assert (liq["actif_net_partage"], liq["droit_partage"], liq["apports_rembourses"]) == (0.0, 0.0, 0.0)
    assert liq["boni"] == pytest.approx(-1000.0) and liq["mali"] is True
    assert any("comptes courants remboursés à hauteur de" in x and "5 500,00 € non remboursés" in x
               for x in liq["raisons"])
    assert so.recu_associes(liq, so.imposer_boni(liq["boni"], 0.14, False, params)) == pytest.approx(9500.0)


def test_actif_insuffisant_pour_les_frais_de_liquidation(params):
    """Suites de la relecture : le manque (200 €) est une dette de la SCI supportée par les associés."""
    liq = so.liquider(300.0, 0.0, 1000.0, 500.0, params)
    assert (liq["cca_rembourses"], liq["actif_net_partage"], liq["apports_rembourses"]) == (0.0, 0.0, 0.0)
    assert liq["boni"] == pytest.approx(-1000.0) and liq["dette_associes"] == pytest.approx(200.0)
    raison = next(x for x in liq["raisons"] if "dette de la SCI à la sortie, supportée par les associés" in x)
    assert "200,00 €" in raison and "1857" in raison
    assert not any("non modélisé" in x for x in liq["raisons"])
    assert so.recu_associes(liq, so.imposer_boni(liq["boni"], 0.14, False, params)) == pytest.approx(-200.0)


def test_liquidation_raisons_du_socle(params):
    raisons = " | ".join(_cas_liquidation(params)["raisons"])
    for marque in ("CGI 746", "CGI 747", "112-1°", "109-1-1°", "à vérifier", "sans texte explicite"):
        assert marque in raisons, marque


def test_params_liquidation_sources_et_natures(params):
    d = modele.parametre(params, "fiscal.liquidation.droit_partage")
    assert (d["valeur"], d["nature"], d["verifie_le"]) == (0.025, "loi", "2026-10-07")
    for marque in ("CGI art. 746", "divorce", "PACS", "CGI art. 747", "BOI-ENR-AVS-30-20-10"):
        assert marque in d["source"], marque
    m = modele.parametre(params, "fiscal.liquidation.droit_partage_sur_masse")
    assert (m["valeur"], m["nature"], m["a_verifier"], m["verifie_le"]) == (True, "pratique", True, "2026-10-07")


def test_droit_de_partage_hors_masse_non_code(params):
    autre = copy.deepcopy(params)
    autre["fiscal"]["liquidation"]["droit_partage_sur_masse"]["valeur"] = False
    with pytest.raises(ValueError, match="fiscal.liquidation.droit_partage_sur_masse"):
        so.liquider(63825.0, 15000.0, 1000.0, 0.0, autre)


# --------------------------------------------------------------------------------------------
# 13. Imposition du boni (S8) et enchaînement par scénario.
# --------------------------------------------------------------------------------------------

def test_bareme_demande_sans_tmi_pfu_et_raison(params):
    imp = so.imposer_boni(46604.375, None, True, params)
    assert imp["regime"] == "pfu" and imp["impot"] == pytest.approx(46604.375 * 0.314)
    assert any("barème demandé" in x and "TMI" in x for x in imp["raisons"])


def test_bareme_avec_tmi_abattement_de_40_pct(params):
    imp = so.imposer_boni(46604.375, 0.14, True, params)
    assert imp["regime"] == "bareme"
    assert imp["ir"] == pytest.approx(46604.375 * 0.6 * 0.14)
    assert imp["ps"] == pytest.approx(46604.375 * 0.186)
    assert imp["impot"] == pytest.approx(46604.375 * (0.6 * 0.14 + 0.186))
    assert imp["csg_deductible_n1"] == pytest.approx(46604.375 * 0.068 * 0.14)
    assert imp["option_la_plus_favorable"] == "bareme"


def test_pfu_choisi_alors_que_le_bareme_serait_plus_favorable_dit(params):
    imp = so.imposer_boni(46604.375, 0.14, False, params)
    assert imp["regime"] == "pfu" and imp["option_la_plus_favorable"] == "bareme"
    raison = next(x for x in imp["raisons"] if "plus favorable" in x)
    assert "200 A" in raison
    # Suites de la relecture : la comparaison est faite à TMI fixe.
    assert "à TMI fixe : un boni ou un dividende qui change de tranche est mal évalué" in raison


@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_sortir_enchaine_projection_revente_liquidation_imposition(params, scenario):
    bien = modele.charger_bien(BIEN_SORTIE)
    s = so.sortir(bien, scenario, params)
    p = so.projeter(bien, scenario, params)
    r = so.revendre(bien, scenario, params, None, p)
    assert s["annees"] == p["annees"] and {k: v for k, v in s["revente"].items()} == {
        k: v for k, v in r.items() if k != "raisons"}
    liq = s["liquidation"]
    assert liq["actif_apres_cession"] == r["actif_apres_cession"]
    assert liq["cca_rembourses"] == 0.0 and liq["frais_liquidation"] == 1000
    assert liq["apports_rembourses"] == pytest.approx(p["apports_capital"])
    assert liq["actif_net_partage"] == pytest.approx(r["actif_apres_cession"] - 1000)
    assert liq["imposition"]["regime"] == "pfu"  # option_bareme faux dans la fixture
    assert liq["recu_associes"] == pytest.approx(liq["apports_rembourses"] + liq["imposition"]["net"])
    assert all(x in s["raisons"] for x in r["raisons"])
    assert "raisons" not in s["revente"] and "raisons" not in liq


def test_sortir_tmi_du_contexte_pour_le_bareme(params):
    bien = _bien(sortie={"option_bareme": True})
    s = so.sortir(bien, "realiste", params, contexte={"annee": 2026, "tmi": 0.30})
    imp = s["liquidation"]["imposition"]
    assert imp["regime"] == "bareme" and imp["ir"] == pytest.approx(s["liquidation"]["boni"] * 0.6 * 0.30)


# --------------------------------------------------------------------------------------------
# 14. Flux des associés, TRI et VAN.
# --------------------------------------------------------------------------------------------

def test_flux_de_fin_du_cas_de_controle(params):
    """t = N : comptes courants 15 000 + apports 1 000 + boni net 31 970,60125 = 47 970,60125 (aucun versement)."""
    liq = _cas_liquidation(params)
    imp = so.imposer_boni(liq["boni"], 0.14, False, params)
    flux = so.flux_associes(16000.0, [0.0] * 12, liq, imp)
    assert len(flux) == 13 and flux[0] == -16000.0
    assert flux[-1] == pytest.approx(47970.60125, abs=1e-6)
    assert flux[-1] == pytest.approx(so.recu_associes(liq, imp), abs=1e-9)


def test_tri_d_une_suite_simple_verifiee_a_la_main():
    """-100 puis +110 : 110 / (1 + r) = 100, r = 10 %."""
    r = so.rentabilite([-100.0, 110.0], None)
    assert r["tri"] == pytest.approx(0.10, abs=1e-9)
    assert r["van"] is None and any("taux_actualisation" in x for x in r["raisons"])


def test_tri_absent_et_raison_sans_changement_de_signe():
    r = so.rentabilite([-100.0, -10.0, -5.0], 0.04)
    assert r["tri"] is None
    assert any("TRI non calculé" in x and "changement de signe" in x for x in r["raisons"])
    assert r["van"] == pytest.approx(-100 - 10 / 1.04 - 5 / 1.04 ** 2)


@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_van_nulle_au_taux_du_tri(params, scenario):
    s = so.sortir(modele.charger_bien(BIEN_SORTIE), scenario, params)
    assert s["tri"] is not None
    assert so.rentabilite(s["flux_associes"], s["tri"])["van"] == pytest.approx(0.0, abs=1e-3)
    assert s["van"] == pytest.approx(sum(f / 1.04 ** i for i, f in enumerate(s["flux_associes"])))


def test_flux_des_associes_annee_par_annee(params):
    """t = 0 : - apport (capital et compte courant) ; t = 1 à N : distribution au PFU + remboursement de compte
    courant + intérêts de compte courant nets du PFU (S12) ; t = N : + liquidation."""
    bien = _bien(sci={"cca": {"montant": 30000, "taux": 0.03}, "remboursement_cca_annuel": 4000})
    s = so.sortir(bien, "realiste", params)
    flux, lignes, liq = s["flux_associes"], s["annees"], s["liquidation"]
    assert len(flux) == 11 and flux[0] == pytest.approx(-apport(bien, params))
    for t, l in enumerate(lignes, start=1):
        attendu = ((l["distribution"] + l["interets_cca"]["verses"]) * (1 - 0.314)  # PFU 12,8 % + 18,6 %
                   + l["remboursement_cca"] - l["apport_cca"])
        if t == 10:
            attendu += liq["cca_rembourses"] + liq["apports_rembourses"] + liq["boni_net"]
        assert flux[t] == pytest.approx(attendu), t
    assert any("F32966" in x for x in s["raisons"])


def test_flux_au_bareme_csg_deductible_comptee_l_annee_meme(params):
    bien = _bien(sortie={"option_bareme": True})
    s = so.sortir(bien, "realiste", params)
    l1 = s["annees"][0]
    d = 10000 * (1 - 0.6 * 0.14 - 0.186) + 10000 * 0.068 * 0.14  # distribution de 10 000, TMI 14 % de la fixture
    assert s["flux_associes"][1] == pytest.approx(d + l1["remboursement_cca"])
    imp = s["liquidation"]["imposition"]
    assert imp["regime"] == "bareme"
    fin = s["annees"][-1]["distribution"] * (1 - 0.6 * 0.14 - 0.186 + 0.068 * 0.14)
    assert s["flux_associes"][-1] == pytest.approx(fin + s["liquidation"]["apports_rembourses"] + imp["net"]
                                                   + imp["csg_deductible_n1"])
    assert any("CSG déductible" in x and "l'année même" in x for x in s["raisons"])


# TRI de ce bien dans une version antérieure du moteur, quand le manque de trésorerie restait un découvert sans frais, soldé à la liquidation.
TRI_VERSION_DECOUVERT = {"pessimiste": 0.05410685477923606, "realiste": 0.09412548704412757,
                         "optimiste": 0.12317520822462713}


@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_flux_manque_de_tresorerie_apporte_par_les_associes(params, scenario):
    """Convention du moteur : flux négatifs les années de besoin, comptes courants remboursés à la
    liquidation, TRI plus bas qu'avec le découvert. Taux du compte courant nul : reporter les apports à t = N redonne
    exactement les flux d'avant."""
    reval = {"pessimiste": 0.03, "realiste": 0.03, "optimiste": 0.03}
    s = so.sortir(_bien(BIEN_FICTIF, sortie={"revalorisation_annuelle": reval}), scenario, params)
    lignes, flux, liq = s["annees"], s["flux_associes"], s["liquidation"]
    apports = [l["apport_cca"] for l in lignes]
    assert len(flux) == 11 and all(a > 0 for a in apports[:9])  # optimiste : année 10 sans manque (loyer indexé)
    for t in range(1, 10):  # ni distribution, ni remboursement, ni intérêt (taux nul) : l'apport seul
        assert flux[t] == pytest.approx(-apports[t - 1]) and flux[t] < 0
    assert liq["cca_rembourses"] == pytest.approx(sum(apports))
    assert flux[-1] == pytest.approx(-apports[-1] + liq["recu_associes"])
    assert s["tri"] < TRI_VERSION_DECOUVERT[scenario]
    avant = [flux[0]] + [f + a for f, a in zip(flux[1:], apports)]
    avant[-1] -= sum(apports)
    assert so.rentabilite(avant, None)["tri"] == pytest.approx(TRI_VERSION_DECOUVERT[scenario], abs=1e-9)
    assert any("apportent le manque en compte courant" in x for x in s["raisons"])
    assert not any("TRI surestimé" in x for x in s["raisons"])


def test_sortir_cles_du_contrat_par_scenario(params):
    s = so.sortir(modele.charger_bien(BIEN_SORTIE), "realiste", params)
    assert set(s) == {"annees", "revente", "liquidation", "flux_associes", "tri", "van", "raisons"}


# --------------------------------------------------------------------------------------------
# 15. Contrat de sortie et CLI.
# --------------------------------------------------------------------------------------------

CLES_CONTRAT = {"bien", "params_utilises", "acquisition", "financement", "scenarios", "prix_equilibre", "hcsf",
                "fiscalite"}
CLES_SORTIE = {"annees", "revente", "liquidation", "flux_associes", "tri", "van", "raisons"}


def test_cle_sortie_absente_sans_bloc_sortie_et_cles_contrat_inchangees(params):
    for chemin in (BIEN_FICTIF, biens_test.chemin("bien_fictif_sci_is.json")):
        assert set(analyser(modele.charger_bien(chemin), params)) == CLES_CONTRAT
    sortie = analyser(modele.charger_bien(BIEN_SORTIE), params)
    assert set(sortie) == CLES_CONTRAT | {"sortie"}
    assert set(sortie["sortie"]) == set(modele.SCENARIOS)
    for nom in modele.SCENARIOS:
        assert set(sortie["sortie"][nom]) == CLES_SORTIE
        assert sortie["sortie"][nom] == so.sortir(modele.charger_bien(BIEN_SORTIE), nom, params)


def test_contrat_params_utilises_de_la_liquidation(params):
    pu = analyser(modele.charger_bien(BIEN_SORTIE), params)["params_utilises"]
    assert pu["fiscal.liquidation.droit_partage"]["valeur"] == 0.025
    assert pu["fiscal.liquidation.droit_partage_sur_masse"]["a_verifier"] is True
    sans = analyser(modele.charger_bien(BIEN_FICTIF), params)["params_utilises"]
    assert not any(c.startswith("fiscal.liquidation.") for c in sans)


def test_contrat_tmi_du_contexte_foyer(params):
    bien = _bien(sortie={"option_bareme": True})
    contexte = {"annee": 2026, "tmi": 0.30, "revenus_fonciers_bruts_existants": 0.0, "a_un_bien_ij": False,
                "foncier_existant": {"R": 0.0, "I": 0.0, "C": 0.0, "report_disponible": 0.0},
                "mensualites": {"actuelle": 0.0, "future": 0.0}, "revenus_activite_mensuels": 4000.0,
                "loyers_existants_mensuels": 0.0}
    s = analyser(bien, params, contexte_foyer=contexte)["sortie"]["realiste"]
    imp = s["liquidation"]["imposition"]
    assert imp["ir"] == pytest.approx(s["liquidation"]["boni"] * 0.6 * 0.30)


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "src.immo", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def test_cli_ligne_de_resume_de_la_sortie_et_arrondi():
    r = _cli("--bien", str(BIEN_SORTIE))
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)  # stdout reste du JSON pur
    s = d["sortie"]["realiste"]
    assert s["tri"] == round(s["tri"], 6) and 0 < s["tri"] < 1
    assert all(f == round(f, 2) for f in s["flux_associes"])
    assert all(v == round(v, 2) for l in s["annees"] for v in (l["resultat"], l["tresorerie_fin"]))
    lignes = [l for l in r.stderr.splitlines() if l.startswith("Sortie à ")]
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne.startswith("Sortie à 10 ans (SCI à l'IS) : TRI pessimiste ")
    assert ", réaliste " in ligne and ", optimiste " in ligne and " ; VAN à 4 % : " in ligne
    tri = format(d["sortie"]["realiste"]["tri"] * 100, ".2f").replace(".", ",")
    assert f"réaliste {tri} %" in ligne


def test_cli_sans_bloc_sortie_aucune_ligne_de_resume():
    r = _cli("--bien", str(biens_test.chemin("bien_fictif_sci_is.json")))
    assert r.returncode == 0 and "Sortie à" not in r.stderr and "sortie" not in json.loads(r.stdout)


# --------------------------------------------------------------------------------------------
# 16. Suites de la relecture du 08/10/2026 : détails et cas de test ajoutés.
# --------------------------------------------------------------------------------------------

def _bien_relecture():
    """Scénario de la relecture : emprunt 290 000, revalorisation -10 %/an aux 3 scénarios, distribution 30 000."""
    reval = {"pessimiste": -0.10, "realiste": -0.10, "optimiste": -0.10}
    return _bien(financement={"emprunt": 290000}, sci={"distribution_annuelle": 30000},
                 sortie={"revalorisation_annuelle": reval})


@pytest.mark.parametrize("scenario", modele.SCENARIOS)
def test_r1_dette_de_la_sci_a_la_sortie_supportee_par_les_associes(params, scenario):
    """C. civ. art. 1857 (lu le 08/10/2026 ) : l'actif après cession ne couvre ni le prêt ni les
    frais de liquidation ; le manque est un flux négatif des associés à l'année N. Avant ce correctif, le TRI
    réaliste valait 29,99 % (relevé sur une version antérieure du moteur)."""
    s = so.sortir(_bien_relecture(), scenario, params)
    liq, flux = s["liquidation"], s["flux_associes"]
    manque = -(liq["actif_apres_cession"] - liq["frais_liquidation"])
    assert manque > 60000 and liq["dette_associes"] == pytest.approx(manque)
    assert liq["recu_associes"] == pytest.approx(-manque)  # ni compte courant, ni apport, ni boni
    versement_n = flux[-1] - liq["recu_associes"] - liq["imposition"]["csg_deductible_n1"]
    assert flux[-1] < 0 and versement_n > 0
    assert any("dette de la SCI à la sortie, supportée par les associés" in r for r in s["raisons"])
    assert s["tri"] is None or s["tri"] < 0.05


def test_r1_tri_du_scenario_de_la_relecture_n_est_plus_de_30_pct(params):
    """Version antérieure du moteur : TRI réaliste 29,99 % et VAN à 4 % de 55 662,19 €, la dette de la SCI à la sortie ignorée.
    Le seul flux qui change est celui de l'année N (- dette) ; les flux ont alors deux changements de signe et deux
    racines (vers -2,5 % et 22 %), aucune trouvée seule dans ]-0,99 ; 1,0] : TRI absent, raison dite, VAN qui fait
    foi."""
    s = so.sortir(_bien_relecture(), "realiste", params)
    assert s["tri"] is None
    assert any("2 changements de signe" in r and "préférer la VAN" in r for r in s["raisons"])
    assert s["van"] == pytest.approx(55662.19 - s["liquidation"]["dette_associes"] / 1.04 ** 10, abs=0.01)


def test_flux_conventionnels_sans_raison_de_signe(params):
    s = so.sortir(modele.charger_bien(BIEN_SORTIE), "realiste", params)
    assert s["tri"] is not None and not any("changements de signe" in r for r in s["raisons"])


def test_r2_raison_seul_le_prix_d_achat_est_revalorise(params):
    r = _revendre(_bien(travaux=20000), params)
    assert any("seul le prix d'achat est revalorisé ; les travaux n'ajoutent aucune valeur de revente (hypothèse "
               "prudente, à reprendre dans À vérifier)" in x for x in r["raisons"])
    assert r["prix_revente"] == pytest.approx(300000 * 1.01 ** 10)  # pas de changement de modèle


def test_r3_bareme_plus_favorable_a_tmi_fixe_dit_pour_les_distributions(params):
    s = so.sortir(modele.charger_bien(BIEN_SORTIE), "realiste", params)  # PFU, TMI 14 % : barème plus favorable
    raisons = [x for x in s["raisons"] if "serait plus favorable" in x]
    assert len(raisons) == 2  # le boni, puis les distributions annuelles
    assert all("à TMI fixe : un boni ou un dividende qui change de tranche est mal évalué" in x for x in raisons)


def test_ira_non_dues_sans_emprunt(params):
    bien = _bien(financement={"emprunt": 0})
    r = _revendre(bien, params)
    assert (r["crd_rembourse"], r["indemnites_remboursement_anticipe"]) == (0.0, 0.0)
    assert any("non dues" in x and "aucun emprunt" in x for x in r["raisons"])
    assert not any(x.startswith("indemnités de remboursement anticipé (") for x in r["raisons"])


def test_t1_premier_exercice_de_18_mois_puis_limite_de_12_mois(params):
    """Année 1 (18 mois) : limite du taux réduit proratisée à 63 750 € ; année 2 (12 mois) : 42 500 €."""
    scenarios = {"pessimiste": {"loyer_mensuel_hc": 5600, "vacance": 0.05},
                 "realiste": {"loyer_mensuel_hc": 6000, "vacance": 0.05},
                 "optimiste": {"loyer_mensuel_hc": 6400, "vacance": 0.05}}
    p = _projeter(_bien(scenarios=scenarios, sci={"duree_premier_exercice_mois": 18}), params)
    l1, l2 = p["annees"][:2]
    assert 42500 < l1["imposable"] < 63750 and l1["impot"] == pytest.approx(0.15 * l1["imposable"])
    assert l2["imposable"] > 42500
    assert l2["impot"] == pytest.approx(0.15 * 42500 + 0.25 * (l2["imposable"] - 42500))


def test_t2_aucune_distribution_tant_que_le_report_a_nouveau_est_negatif(params):
    bien = _bien(travaux=100000, travaux_nature="entretien", sci={"distribution_annuelle": 10000})
    lignes = _projeter(bien, params)["annees"]
    ran, bloquees = 0.0, 0
    for l in lignes:
        if ran + l["resultat_apres_is"] <= 0:
            assert l["distribution"] == 0.0, l["annee"]
            bloquees += 1
        ran = l["report_a_nouveau"]
    assert bloquees >= 2 and lignes[-1]["distribution"] == 10000


def test_t3_revente_capital_non_libere_is_au_taux_normal(params):
    r = _revendre(_bien(sci={"capital_libere": False}), params)
    detail = r["is_detail"]
    assert detail["base_taux_reduit"] == 0.0 and detail["imposable"] > 0
    assert r["is_avec_cession"] == pytest.approx(0.25 * detail["imposable"])


@pytest.mark.parametrize("horizon", [1, 25])
def test_sortir_a_l_horizon_1_et_au_dela_du_pret(params, horizon):
    bien = _bien(sortie={"horizon_ans": horizon})  # prêt de 240 mois
    s = so.sortir(bien, "realiste", params)
    flux, liq = s["flux_associes"], s["liquidation"]
    assert len(flux) == horizon + 1 and flux[0] == pytest.approx(-apport(bien, params))
    l_n = s["annees"][-1]
    versement_n = (l_n["distribution"] + l_n["interets_cca"]["verses"]) * (1 - 0.314) + l_n["remboursement_cca"]
    assert flux[-1] == pytest.approx(versement_n + liq["recu_associes"] + liq["imposition"]["csg_deductible_n1"])
    assert s["tri"] is not None
    if horizon == 1:
        assert s["revente"]["is_detail"]["duree_exercice_mois"] == 12
        assert s["revente"]["crd_rembourse"] > 0 and s["revente"]["indemnites_remboursement_anticipe"] == 1500
    else:
        assert (s["revente"]["crd_rembourse"], s["revente"]["indemnites_remboursement_anticipe"]) == (0.0, 0.0)


def test_cli_et_synthese_au_singulier_pour_un_an(tmp_path):
    brut = json.loads(BIEN_SORTIE.read_text(encoding="utf-8"))
    brut["sortie"]["horizon_ans"] = 1
    chemin = tmp_path / "bien.json"
    chemin.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    r = _cli("--bien", str(chemin))
    assert r.returncode == 0, r.stderr
    assert "Sortie à 1 an (SCI à l'IS)" in r.stderr and "1 ans" not in r.stderr
    sortie = tmp_path / "sortie.json"
    sortie.write_text(r.stdout, encoding="utf-8")
    syn = subprocess.run([sys.executable, str(ROOT / "scripts" / "immo_synthese.py"), "--sortie", str(sortie)],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert syn.returncode == 0, syn.stderr
    assert "## Sortie à 1 an (SCI à l'IS)" in syn.stdout and "1 ans" not in syn.stdout
