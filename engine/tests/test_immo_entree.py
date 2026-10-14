"""Contrôle de l'entrée du moteur contre le profil de l'investisseur, et loyer du tri rapide corrigé de la surface.

Biens FICTIFS (`tests/fixtures/immo/bien_fictif*.json`, modifiés en mémoire) ; profil du gabarit
`templates/profil.json` (décisions FICTIVES, aucun chiffre du foyer) ; fiche de loyers FICTIVE
(`tests/fixtures/immo/fiche_loyers_fictive.json`) pour `loyer-3r`.
"""
from __future__ import annotations

import copy
import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import loyer  # noqa: E402

SCRIPT = ROOT / "scripts" / "immo_entree.py"
GABARIT_PROFIL = ROOT.parent / "templates" / "profil.json"
PROFIL = ROOT / "tests" / "fixtures" / "immo" / "profil_controle_fictif.json"  # dérivé du gabarit, valeurs de test
BIEN_SCI_IS = biens_test.chemin("bien_fictif_sci_is.json")
FICHE = ROOT / "tests" / "fixtures" / "immo" / "fiche_loyers_fictive.json"
CLES_MINIMALES = {"cible", "budget_fai", "premier_achat_prix_max", "apport", "montage_reference",
                  "comptabilite_sci_dans_cash_flow", "seuil_confort_cf_mensuel", "division", "vacance_realiste",
                  "meuble_logements_2_pieces_ou_moins", "zone", "offre_sans_condition_suspensive_pret"}


def _lancer(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def _conforme() -> dict:
    """Bien fictif SCI à l'IS, vacance 0,06 partout (celle du profil de test), comptabilité 0, prix sous le plafond du premier achat."""
    bien = json.loads(BIEN_SCI_IS.read_text(encoding="utf-8"))
    for sc in bien["scenarios"].values():
        sc["vacance"] = 0.06
    bien["exploitation"]["comptable"] = 0
    bien["prix_net_vendeur"], bien["frais_agence_acquereur"] = 120000, 5000
    return bien


@pytest.fixture
def ecrire(tmp_path):
    def _ecrire(bien: dict) -> Path:
        chemin = tmp_path / "entree.json"
        chemin.write_text(json.dumps(bien), encoding="utf-8")
        return chemin
    return _ecrire


# ---------------------------------------------------------------------------------------------- profil

@pytest.mark.parametrize("profil", ["gabarit", "fixture"])
def test_profil_porte_les_cles_minimales_datees_et_sourcees(profil):
    chemin = GABARIT_PROFIL if profil == "gabarit" else PROFIL
    decisions = json.loads(chemin.read_text(encoding="utf-8"))["decisions"]
    assert {d["cle"] for d in decisions} == CLES_MINIMALES
    assert len(decisions) == len(CLES_MINIMALES)
    for d in decisions:
        assert set(d) == {"cle", "valeur", "unite", "date", "source", "exceptions"}
        assert d["source"].strip() and len(d["date"]) == 10
        for e in d["exceptions"]:
            assert set(e) == {"annonce", "portee", "date"}


def test_profil_sans_tmi():
    assert "tmi" not in GABARIT_PROFIL.read_text(encoding="utf-8").lower().replace("la tmi n'y entre pas", "")


# ---------------------------------------------------------------------------------------------- controle

def test_controle_entree_conforme_code_0(ecrire):
    r = _lancer("controle", "--bien", str(ecrire(_conforme())), "--profil", str(PROFIL))
    assert r.returncode == 0, r.stderr
    assert "conforme" in r.stdout


def test_controle_vacance_010_refusee_puis_acceptee_justifiee(ecrire):
    bien = _conforme()
    bien["scenarios"]["pessimiste"]["vacance"] = 0.10
    chemin = ecrire(bien)
    r = _lancer("controle", "--bien", str(chemin), "--profil", str(PROFIL))
    assert r.returncode == 1
    assert "vacance" in r.stderr and "pessimiste" in r.stderr
    r = _lancer("controle", "--bien", str(chemin), "--profil", str(PROFIL), "--justification-vacance", "colocation")
    assert r.returncode == 0, r.stderr
    assert "colocation" in r.stdout


def test_controle_justification_vide_ne_vaut_pas_justification(ecrire):
    bien = _conforme()
    bien["scenarios"]["realiste"]["vacance"] = 0.10
    r = _lancer("controle", "--bien", str(ecrire(bien)), "--profil", str(PROFIL), "--justification-vacance", "  ")
    assert r.returncode == 1


def test_controle_comptabilite_dans_le_cash_flow_de_la_sci_refusee(ecrire):
    bien = _conforme()
    bien["exploitation"]["comptable"] = 600
    r = _lancer("controle", "--bien", str(ecrire(bien)), "--profil", str(PROFIL))
    assert r.returncode == 1
    assert "exploitation.comptable" in r.stderr


def test_controle_comptabilite_sans_bloc_sci_acceptee(ecrire):
    """LMNP réel étudié pour lui-même, exécution à part : la comptabilité est permise (entree_moteur.md)."""
    bien = _conforme()
    bien.pop("sci")
    bien["exploitation"]["comptable"] = 600
    assert _lancer("controle", "--bien", str(ecrire(bien)), "--profil", str(PROFIL)).returncode == 0


def test_controle_deux_violations_nommees_ensemble(ecrire):
    bien = _conforme()
    bien["scenarios"]["optimiste"]["vacance"] = 0.05
    bien["exploitation"]["comptable"] = 600
    r = _lancer("controle", "--bien", str(ecrire(bien)), "--profil", str(PROFIL))
    assert r.returncode == 1
    assert "optimiste" in r.stderr and "exploitation.comptable" in r.stderr


def test_controle_premier_achat_au_dela_avertit_sans_refuser(ecrire):
    bien = _conforme()
    bien["prix_net_vendeur"], bien["frais_agence_acquereur"] = 130000, 5000  # 135 000 : pas « inférieur à »
    chemin = ecrire(bien)
    r = _lancer("controle", "--bien", str(chemin), "--profil", str(PROFIL))
    assert r.returncode == 0
    assert "avertissement" in r.stderr and "premier_achat_prix_max" in r.stderr
    r = _lancer("controle", "--bien", str(chemin), "--profil", str(PROFIL), "--annonce", "9000000001")
    assert r.returncode == 0 and "premier_achat_prix_max" not in r.stderr
    assert "exception" in r.stdout


def test_controle_ne_modifie_pas_l_entree(ecrire):
    bien = _conforme()
    bien["exploitation"]["comptable"] = 600
    chemin = ecrire(bien)
    avant = chemin.read_bytes()
    _lancer("controle", "--bien", str(chemin), "--profil", str(PROFIL))
    assert chemin.read_bytes() == avant


def test_controle_entree_illisible_code_2(tmp_path, ecrire):
    casse = tmp_path / "casse.json"
    casse.write_text("{pas du json", encoding="utf-8")
    assert _lancer("controle", "--bien", str(casse), "--profil", str(PROFIL)).returncode == 2
    assert _lancer("controle", "--bien", str(tmp_path / "absent.json"), "--profil", str(PROFIL)).returncode == 2
    sans_scenarios = _conforme()
    sans_scenarios.pop("scenarios")
    assert _lancer("controle", "--bien", str(ecrire(sans_scenarios)), "--profil", str(PROFIL)).returncode == 2


# ---------------------------------------------------------------------------------------------- loyer-3r

FICHE_FICTIVE = {
    "commune": {"nom": "Fictive"},
    "loyers": {
        "appartement_t1_t2": {"valeur_m2": 20.0, "ip_haut": 24.0, "surface_type_m2": 37, "n": 100,
                              "maille": "commune", "millesime": "2025"},
        "appartement_t3_plus": {"valeur_m2": 16.0, "ip_haut": 19.0, "surface_type_m2": 72, "n": 50,
                                "maille": "commune", "millesime": "2025"},
        "maison": {"valeur_m2": 12.0, "ip_haut": 15.0, "surface_type_m2": 92, "n": 30,
                   "maille": "commune", "millesime": "2025"},
    },
}


def test_signature_figee():
    """`from __future__ import annotations` est exigé dans src/immo (test_immo_socle) : annotations évaluées ici."""
    assert str(inspect.signature(loyer.loyer_3r, eval_str=True)) == (
        "(fiche: dict, serie: str, surface_m2: float, charges_mensuelles: float | None = None) -> dict")


def test_elasticite_negative_derivee_de_la_fiche():
    r = loyer.loyer_3r(FICHE_FICTIVE, "appartement_t1_t2", 37)
    assert r["elasticite"] == pytest.approx(math.log(16 / 20) / math.log(72 / 37))
    assert r["elasticite"] < 0


def test_loyer_a_la_surface_type_vaut_la_carte():
    r = loyer.loyer_3r(FICHE_FICTIVE, "appartement_t1_t2", 37)
    assert r["scenarios"]["realiste"]["loyer_cc"] == pytest.approx(20.0 * 37)
    assert r["scenarios"]["optimiste"]["loyer_cc"] == pytest.approx(24.0 * 37)
    assert r["scenarios"]["pessimiste"]["loyer_cc"] == pytest.approx(0.9 * 20.0 * 37)
    assert r["extrapolation"] is False


def test_loyer_corrige_de_la_surface_et_hors_charges():
    r = loyer.loyer_3r(FICHE_FICTIVE, "appartement_t3_plus", 50, charges_mensuelles=40)
    e = math.log(16 / 20) / math.log(72 / 37)
    m2 = 16.0 * (50 / 72) ** e
    assert m2 > 16.0  # plus petit que le bien type : loyer au m² plus haut
    rea = r["scenarios"]["realiste"]
    assert rea["loyer_m2_cc"] == pytest.approx(m2)
    assert rea["loyer_cc"] == pytest.approx(m2 * 50) and rea["loyer_hc"] == pytest.approx(m2 * 50 - 40)
    assert r["scenarios"]["optimiste"]["loyer_hc"] == pytest.approx(19.0 * (50 / 72) ** e * 50 - 40)
    assert r["scenarios"]["pessimiste"]["loyer_hc"] == pytest.approx(0.9 * (m2 * 50 - 40))


def test_sans_charges_pas_de_hc():
    r = loyer.loyer_3r(FICHE_FICTIVE, "appartement_t1_t2", 40)
    assert all(sc["loyer_hc"] is None for sc in r["scenarios"].values())


@pytest.mark.parametrize("serie, surface, attendu", [
    ("appartement_t1_t2", 37, False), ("appartement_t3_plus", 92, False), ("appartement_t1_t2", 36.9, True),
    ("appartement_t3_plus", 92.1, True), ("maison", 92, True), ("maison", 60, True),
])
def test_drapeau_extrapolation(serie, surface, attendu):
    r = loyer.loyer_3r(FICHE_FICTIVE, serie, surface)
    assert r["extrapolation"] is attendu
    assert bool(r["raison_extrapolation"]) is attendu


@pytest.mark.parametrize("fiche, serie, surface", [
    (FICHE_FICTIVE, "studio", 30),
    (FICHE_FICTIVE, "appartement_t1_t2", 0),
    ({"loyers": {"appartement_t1_t2": FICHE_FICTIVE["loyers"]["appartement_t1_t2"]}}, "appartement_t1_t2", 40),
    ({"loyers": {**FICHE_FICTIVE["loyers"], "maison": None}}, "maison", 100),
])
def test_entree_invalide_refusee(fiche, serie, surface):
    with pytest.raises(ValueError):
        loyer.loyer_3r(fiche, serie, surface)


def test_loyer_3r_cli_fiche_fictive_t1t2_40m2():
    r = _lancer("loyer-3r", "--fiche", str(FICHE), "--serie", "appartement_t1_t2", "--surface", "40", "--json")
    assert r.returncode == 0, r.stderr
    sortie = json.loads(r.stdout)
    l = json.loads(FICHE.read_text(encoding="utf-8"))["loyers"]
    e = math.log(l["appartement_t3_plus"]["valeur_m2"] / l["appartement_t1_t2"]["valeur_m2"]) / math.log(72 / 37)
    assert sortie["elasticite"] == pytest.approx(e)
    assert sortie["scenarios"]["realiste"]["loyer_cc"] == pytest.approx(
        l["appartement_t1_t2"]["valeur_m2"] * (40 / 37) ** e * 40)
    assert sortie["extrapolation"] is False


@pytest.mark.parametrize("surface, facteur", [(333, 0.7377), (84.5, 1.0203)])
def test_controle_signe_et_facteurs_fiche_fictive(surface, facteur):
    """Valeurs de contrôle : e ≈ −0,2365 sur la fiche fictive ; série maison, S_type 92.
    Inverser le rapport des séries donne e > 0 et un facteur < 1 à 84,5 m² : ce test échoue."""
    r = loyer.loyer_3r(json.loads(FICHE.read_text(encoding="utf-8")), "maison", surface)
    assert r["elasticite"] == pytest.approx(-0.2365, abs=2e-4)  # valeurs de la fiche fictive
    assert r["facteur"] == pytest.approx(facteur, abs=5e-4)


def test_signe_fige_valeurs_fictives():
    """Critère loyer-3r : 15,10 (T1-T2) et 12,90 (T3 et plus), FICTIVES →
    e arrondi à −0,2365 ; série maison (S_type 92) : facteur 0,738 à 333 m², 1,0203 à 84,5 m².
    Inverser le rapport (v_t1t2 / v_t3plus) donne +0,2365 : ce test échoue."""
    fiche = {"loyers": {"appartement_t1_t2": {"valeur_m2": 15.1, "surface_type_m2": 37},
                        "appartement_t3_plus": {"valeur_m2": 12.9, "surface_type_m2": 72},
                        "maison": {"valeur_m2": 10.0, "surface_type_m2": 92}}}
    assert round(loyer.loyer_3r(fiche, "maison", 333)["elasticite"], 4) == -0.2365
    assert round(loyer.loyer_3r(fiche, "maison", 333)["facteur"], 3) == 0.738
    assert round(loyer.loyer_3r(fiche, "maison", 84.5)["facteur"], 4) == 1.0203


def test_loyer_3r_cli_maison_150m2_extrapolation():
    r = _lancer("loyer-3r", "--fiche", str(FICHE), "--serie", "maison", "--surface", "150")
    assert r.returncode == 0, r.stderr
    assert "extrapolation" in r.stdout.lower()


def test_loyer_3r_cli_serie_inconnue_code_2():
    assert _lancer("loyer-3r", "--fiche", str(FICHE), "--serie", "studio", "--surface", "30").returncode == 2


@pytest.mark.parametrize("cle, valeur, morceau", [
    ("premier_achat_prix_max", None, "premier_achat_prix_max"),
    ("premier_achat_prix_max", "150 k€", "premier_achat_prix_max"),
    ("vacance_realiste", "8 %", "vacance_realiste"),
    ("vacance_realiste", 1.5, "vacance_realiste"),
    ("comptabilite_sci_dans_cash_flow", "non", "comptabilite_sci_dans_cash_flow"),
])
def test_controle_profil_invalide_code_2_message_clair(tmp_path, ecrire, cle, valeur, morceau):
    profil = json.loads(PROFIL.read_text(encoding="utf-8"))
    next(d for d in profil["decisions"] if d["cle"] == cle)["valeur"] = valeur
    chemin = tmp_path / "profil.json"
    chemin.write_text(json.dumps(profil), encoding="utf-8")
    r = _lancer("controle", "--bien", str(ecrire(_conforme())), "--profil", str(chemin))
    assert r.returncode == 2, r.stderr
    assert morceau in r.stderr and "Traceback" not in r.stderr


def test_controle_profil_du_gabarit_non_rempli_code_2(ecrire):
    r = _lancer("controle", "--bien", str(ecrire(_conforme())), "--profil", str(GABARIT_PROFIL))
    assert r.returncode == 2 and "profil non rempli" in r.stderr and "Traceback" not in r.stderr
