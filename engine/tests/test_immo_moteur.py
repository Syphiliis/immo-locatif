"""Lanceur `scripts/immo_moteur.py` : même sortie et mêmes codes que `python -m src.immo`, quel que soit le cwd.

Données FICTIVES : la fixture `bien_fictif.json` et un `foyer.json` inventé.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

LANCEUR = ROOT / "scripts" / "immo_moteur.py"
BIEN = ROOT / "tests" / "fixtures" / "immo" / "bien_fictif.json"


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "IMMO_DATA_DIR")}


def _lancer(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LANCEUR), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", env=_env(), timeout=120)


def _paquet_src_etranger(dossier: Path) -> None:
    """Un `src/` du projet de l'utilisateur, qui masquerait le moteur avec `python -m src.immo`."""
    (dossier / "src").mkdir()
    (dossier / "src" / "__init__.py").write_text("", encoding="utf-8")
    (dossier / "src" / "immo.py").write_text("raise SystemExit('mauvais paquet src')\n", encoding="utf-8")


def test_meme_sortie_que_python_m_src_immo(tmp_path):
    attendu = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(BIEN)], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", env=_env(), timeout=120)
    _paquet_src_etranger(tmp_path)
    r = _lancer("--bien", str(BIEN), cwd=tmp_path)
    assert r.returncode == attendu.returncode == 0, r.stderr
    assert json.loads(r.stdout) == json.loads(attendu.stdout)


def test_foyer_par_defaut_dans_immo_data_du_repertoire_courant(tmp_path):
    def f(v):
        return {"valeur": v, "source": "pièce fictive", "date": "2026-09-01"}
    foyer = {"annee": f(2026), "tmi": f(0.41), "revenus_activite_mensuels": f(5200), "loyers_existants_mensuels": f(0),
             "revenus_fonciers_bruts_existants": f(0), "a_un_bien_ij": f(False),
             "foncier_existant": {"R": f(0), "I": f(0), "C": f(0), "report_disponible": f(0)},
             "mensualites": {"actuelle": f(800), "future": f(800), "nb_prets": f(1)}}
    (tmp_path / "immo-data").mkdir()
    (tmp_path / "immo-data" / "foyer.json").write_text(json.dumps(foyer), encoding="utf-8")
    r = _lancer("--bien", str(BIEN), "--foyer", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["hcsf"]["entrees_foyer"]["mensualites_existantes"] == 800


def test_codes_de_sortie(tmp_path):
    assert _lancer(cwd=tmp_path).returncode == 2                                    # --bien manquant
    assert _lancer("--bien", str(tmp_path / "absent.json"), cwd=tmp_path).returncode == 2
    r = _lancer("--bien", str(BIEN), "--foyer", cwd=tmp_path)                       # foyer.json introuvable
    assert r.returncode == 2 and "foyer introuvable" in r.stderr


def test_avertit_quand_le_bien_porte_un_foyer_ecrit_a_la_main(tmp_path):
    complet = biens_test.chemin("bien_fictif.json")                                # fixture + bloc foyer de test
    r = _lancer("--bien", str(complet), cwd=tmp_path)
    assert r.returncode == 0 and "avertissement : foyer écrit(s) à la main" in r.stderr
    assert json.loads(r.stdout)["hcsf"]["calcule"] is True                          # calcul d'essai fait quand même
    sans = _lancer("--bien", str(BIEN), cwd=tmp_path)
    assert "avertissement" not in sans.stderr and json.loads(sans.stdout)["hcsf"]["calcule"] is False


def test_avec_foyer_les_blocs_foyer_et_fiscal_tmi_du_bien_sont_ignores(tmp_path):
    def f(v):
        return {"valeur": v, "source": "pièce fictive", "date": "2026-09-01"}
    foyer = {"annee": f(2026), "tmi": f(0.41), "revenus_activite_mensuels": f(5200), "loyers_existants_mensuels": f(0),
             "revenus_fonciers_bruts_existants": f(0), "a_un_bien_ij": f(False),
             "foncier_existant": {"R": f(0), "I": f(0), "C": f(0), "report_disponible": f(0)},
             "mensualites": {"actuelle": f(800), "future": f(800), "nb_prets": f(1)}}
    chemin_foyer = tmp_path / "foyer.json"
    chemin_foyer.write_text(json.dumps(foyer), encoding="utf-8")
    complet = biens_test.brut("bien_fictif_sci_is.json")
    complet["foyer"] = dict(biens_test.FOYER_DE_TEST)
    chemin_bien = tmp_path / "bien.json"
    chemin_bien.write_text(json.dumps(complet), encoding="utf-8")
    r = _lancer("--bien", str(chemin_bien), "--foyer", str(chemin_foyer), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "avertissement : foyer et fiscal.tmi écrit(s) dans le JSON du bien, ignoré(s)" in r.stderr
    sortie = json.loads(r.stdout)
    assert sortie["fiscalite"]["tmi"] == 0.41 and sortie["hcsf"]["entrees_foyer"]["source"] == "foyer.json"
    assert "foyer" not in sortie["bien"] and "tmi" not in sortie["bien"].get("fiscal", {})
