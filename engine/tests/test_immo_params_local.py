"""Surcharge locale des paramètres (`immo-data/params_local.json`) et arrêts quand la zone n'est pas paramétrée.

Valeurs FICTIVES : département « 99 », commune « 99999 », taux inventés pour le test. Aucun taux réel n'est ajouté.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import acquisition, analyser, modele  # noqa: E402
from src.immo.fiscal_nom_propre import bailleur_prive  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "immo"
BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_BAILLEUR_PRIVE = biens_test.chemin("bien_fictif_bailleur_prive.json")
GABARIT = ROOT.parent / "templates" / "params_local.json"


def _feuille(valeur, source: str = "source fictive de test", verifie_le: str = "2026-10-01") -> dict:
    return {"valeur": valeur, "source": source, "verifie_le": verifie_le}


LOCAL_99 = {"_lisez_moi": "ignoré",
            "dmto": {"departements": {"99": {"taux_departemental": _feuille(0.0123)}}}}


def _ecrire(dossier: Path, contenu: dict) -> Path:
    chemin = dossier / "params_local.json"
    chemin.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
    return chemin


# --------------------------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------------------------

def test_un_departement_s_ajoute_a_cote_du_77(tmp_path):
    p = modele.charger_params(local=_ecrire(tmp_path, LOCAL_99))
    assert set(p["dmto"]["departements"]) == {"77", "99"}
    feuille = p["dmto"]["departements"]["99"]["taux_departemental"]
    assert feuille["valeur"] == 0.0123 and feuille["origine"] == "params_local.json"
    assert p["dmto"]["taux_communal"] == modele.charger_params(local=False)["dmto"]["taux_communal"]
    assert "_lisez_moi" not in p


def test_la_fusion_ne_modifie_pas_la_base():
    base = modele.charger_params(local=False)
    copie = copy.deepcopy(base)
    modele.fusionner_params(base, LOCAL_99)
    assert base == copie


def test_une_feuille_locale_remplace_la_feuille_entiere(tmp_path):
    local = {"fiscal": {"bailleur_prive": {"zones": _feuille({"99999": "B2"})}}}
    p = modele.charger_params(local=_ecrire(tmp_path, local))
    assert p["fiscal"]["bailleur_prive"]["zones"]["valeur"] == {"99999": "B2"}   # la feuille locale remplace la feuille entière
    assert p["fiscal"]["bailleur_prive"]["taux"] == modele.charger_params(local=False)["fiscal"]["bailleur_prive"]["taux"]


def test_surcharge_cherchee_dans_le_dossier_de_donnees(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMO_DATA_DIR", str(tmp_path))
    _ecrire(tmp_path, LOCAL_99)
    assert "99" in modele.charger_params()["dmto"]["departements"]
    assert "99" not in modele.charger_params(local=False)["dmto"]["departements"]


def test_sans_fichier_local_params_inchanges(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMO_DATA_DIR", str(tmp_path))
    assert modele.charger_params() == modele.charger_params(local=False)


def test_gabarit_du_plugin_ne_change_rien():
    """Le gabarit ne porte que `_lisez_moi` et `_exemple` : copié tel quel, il n'ajoute aucun chiffre."""
    assert modele.charger_params(local=GABARIT) == modele.charger_params(local=False)


@pytest.mark.parametrize("local, morceau", [
    ({"dmto": {"departements": {"99": {"taux_departemental": {"valeur": 0.01, "source": "s"}}}}}, "verifie_le"),
    ({"dmto": {"departements": {"99": {"taux_departemental": {"valeur": 0.01, "verifie_le": "2026-10-01"}}}}},
     "source"),
    ({"dmto": {"departements": {"99": {"taux_departemental": _feuille("À RENSEIGNER")}}}}, "À RENSEIGNER"),
    ({"fiscal": {"bailleur_prive": {"zones": _feuille({"99999": "à renseigner"})}}}, "À RENSEIGNER"),
    ({"dmto": {"departements": {"99": {"taux_departemental": _feuille(0.01, verifie_le="hier")}}}}, "AAAA-MM-JJ"),
    ({"dmto": {"taux_communal": 0.02}}, "valeur nue"),
    ({"dmto": {"taux_communal": {"autre": _feuille(1)}}}, "est une feuille"),
])
def test_feuille_locale_invalide_refusee(tmp_path, local, morceau):
    with pytest.raises(ValueError, match="params_local.json") as exc:
        modele.charger_params(local=_ecrire(tmp_path, local))
    assert morceau in str(exc.value)


def test_fichier_local_illisible(tmp_path):
    chemin = tmp_path / "params_local.json"
    chemin.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON invalide"):
        modele.charger_params(local=chemin)


# --------------------------------------------------------------------------------------------
# Arrêts : département DMTO et zone locative absents
# --------------------------------------------------------------------------------------------

def test_departement_absent_message_qui_dit_quoi_ajouter():
    with pytest.raises(ValueError) as exc:
        acquisition.dmto(200000, "99", modele.charger_params(local=False))
    message = str(exc.value)
    for morceau in ("'99'", "params_local.json", "dmto", "departements", "taux_departemental", "source",
                    "verifie_le", "DGFiP", "Aucun taux n'est deviné"):
        assert morceau in message, morceau


def test_departement_ajoute_en_local_est_utilise(tmp_path):
    params = modele.charger_params(local=_ecrire(tmp_path, LOCAL_99))
    d = acquisition.dmto_detail(100000, "99", params)
    assert d["droit_departemental"] == pytest.approx(100000 * 0.0123)
    bien = {**modele.charger_bien(BIEN_FICTIF), "departement": "99"}
    sortie = analyser(bien, params)
    assert sortie["params_utilises"]["dmto.departements.99.taux_departemental"]["origine"] == "params_local.json"


def test_zone_locative_absente_message_qui_dit_quoi_ajouter():
    bien = {**modele.charger_bien(BIEN_BAILLEUR_PRIVE), "code_insee": "99999"}
    with pytest.raises(ValueError) as exc:
        bailleur_prive(bien, 500.0, modele.charger_params(local=False))
    message = str(exc.value)
    for morceau in ("99999", "params_local.json", "fiscal.bailleur_prive.zones", "zonage A/B/C", "verifie_le",
                    "Aucune zone n'est devinée"):
        assert morceau in message, morceau


def test_zone_ajoutee_en_local_est_utilisee(tmp_path):
    local = {"fiscal": {"bailleur_prive": {"zones": _feuille({"99999": "B2"})}}}
    bien = {**modele.charger_bien(BIEN_BAILLEUR_PRIVE), "code_insee": "99999"}
    r = bailleur_prive(bien, 500.0, modele.charger_params(local=_ecrire(tmp_path, local)))
    assert r["evaluable"] is True and r["zone"] == "B2"


def test_cli_departement_absent_code_2_sans_traceback(tmp_path):
    bien = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    bien["departement"] = "99"
    chemin = tmp_path / "bien.json"
    chemin.write_text(json.dumps(bien), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "IMMO_DATA_DIR": str(tmp_path / "vide")}
    r = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(chemin)], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 2 and "params_local.json" in r.stderr and "Traceback" not in r.stderr
    (tmp_path / "vide").mkdir()
    _ecrire(tmp_path / "vide", LOCAL_99)
    r = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(chemin)], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 0, r.stderr
