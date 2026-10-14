"""Fraîcheur des repères de l'étude immo (`scripts/immo_fraicheur.py`).

Les repères sont lus dans une racine de plugin FICTIVE et un dossier de données FICTIF construits par le test (dates
choisies par le test) ; un seul test lit la racine réelle du plugin, sans affirmer de date.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "immo_fraicheur.py"
sys.path.insert(0, str(ROOT / "scripts"))

import immo_fraicheur as fr  # noqa: E402

AUJOURDHUI = date(2026, 10, 7)


def _racine(tmp_path: Path, age: int, cloture_au: str = "2026-12-30", grille_age: int | None = None) -> Path:
    """Racine fictive dont tous les repères datés ont `age` jours (la grille, au mois près : premier du mois)."""
    j = (AUJOURDHUI - timedelta(days=age)).isoformat()
    g = AUJOURDHUI - timedelta(days=age if grille_age is None else grille_age)
    fichiers = {
        "immo-data/MARCHE.md": f"# Marché\n\n**Date de référence** : {j}\n",
        "skills/renovation-estimator/references/grille-couts-2026-05.md":
            f"# Grille\n\n> Grille indicative (rédigée {g.month:02d}/{g.year}, marché fictif)\n",
        "engine/src/opendata/loyers.py": f'MILLESIME = "{AUJOURDHUI.year}"\n',
        "engine/src/immo/params.json": json.dumps({"a": {"valeur": 1, "verifie_le": j},
                                            "b": {"valeur": 2, "verifie_le": AUJOURDHUI.isoformat(), "a_verifier": True},
                                            "t": {"valeur": [{"cloture_du": "2026-01-01", "cloture_au": cloture_au,
                                                              "taux": 0.01}], "verifie_le": j}}),
    }
    for rel, texte in fichiers.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(texte, encoding="utf-8")
    return tmp_path


def _code(racine: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--racine", str(racine), "--donnees", str(racine / "immo-data"),
                           "--aujourdhui",
                           AUJOURDHUI.isoformat(), *extra], capture_output=True, text=True)


def test_seuil():
    assert fr.SEUIL_JOURS == 180


@pytest.mark.parametrize("age, code", [(179, 0), (180, 0), (181, 1)])
def test_repere_de_181_jours_perime(tmp_path, age, code):
    r = _code(_racine(tmp_path, age, grille_age=0))
    assert r.returncode == code, r.stdout + r.stderr
    assert "| repère | date | âge (j) | seuil (j) | état |" in r.stdout


def test_grille_datee_au_premier_du_mois(tmp_path):
    reperes = fr.reperes(_racine(tmp_path, 10, grille_age=200), AUJOURDHUI, donnees=tmp_path / "immo-data")
    grille = next(r for r in reperes if r["repere"].startswith("grille"))
    assert grille["date"].day == 1 and grille["etat"] == "PÉRIMÉ"


def test_carte_des_loyers_datee_a_la_fin_du_millesime(tmp_path):
    reperes = fr.reperes(_racine(tmp_path, 10), AUJOURDHUI, donnees=tmp_path / "immo-data")
    carte = next(r for r in reperes if r["repere"].startswith("carte"))
    assert carte["date"] == date(AUJOURDHUI.year, 12, 31) and carte["etat"] == "OK"


def test_params_plus_ancienne_verification_et_compte(tmp_path):
    reperes = fr.reperes(_racine(tmp_path, 100), AUJOURDHUI, donnees=tmp_path / "immo-data")
    p = next(r for r in reperes if r["repere"].startswith("params.json : plus ancienne"))
    assert p["age"] == 100 and "3 verifie_le" in p["note"] and "1 a_verifier" in p["note"]


def test_table_datee_qui_ne_couvre_plus_aujourdhui_code_1(tmp_path):
    r = _code(_racine(tmp_path, 10, cloture_au="2026-10-06", grille_age=0))
    assert r.returncode == 1
    assert "t" in r.stdout and "NON COUVERT" in r.stdout
    assert _code(_racine(tmp_path, 10, cloture_au="2026-10-07", grille_age=0)).returncode == 0


def test_fiche_ajoute_dvf_rei_et_millesime(tmp_path):
    fiche = tmp_path / "fiche.json"
    fiche.write_text(json.dumps({"dvf": {"parametres": {"derniere_mutation": "2026-01-01"}},
                                 "fiscalite_locale": {"exercice": 2025},
                                 "loyers": {"maison": {"millesime": "2025"}, "appartement": None}}), encoding="utf-8")
    reperes = fr.reperes(_racine(tmp_path, 10, grille_age=0), AUJOURDHUI, json.loads(fiche.read_text()),
                         donnees=tmp_path / "immo-data")
    noms = {r["repere"]: r for r in reperes}
    assert noms["fiche : dernière mutation DVF"]["date"] == date(2026, 1, 1)
    assert noms["fiche : exercice REI (fiscalité locale)"]["date"] == date(2025, 12, 31)
    assert noms["fiche : millésime de la carte des loyers"]["date"] == date(2025, 12, 31)
    assert _code(_racine(tmp_path, 10, grille_age=0), "--fiche", str(fiche)).returncode == 1  # DVF : 279 jours


def test_repere_illisible_code_2(tmp_path):
    racine = _racine(tmp_path, 10)
    (racine / "immo-data/MARCHE.md").write_text("pas de date\n", encoding="utf-8")
    r = _code(racine)
    assert r.returncode == 2 and "MARCHE.md" in r.stderr


def test_racine_reelle_rend_un_tableau(tmp_path):
    """Racine réelle du plugin (grille, carte des loyers, params.json) ; dossier de données fictif (MARCHE.md)."""
    (tmp_path / "MARCHE.md").write_text(f"**Date de référence** : {date.today().isoformat()}\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path,
                       env={**os.environ, "IMMO_DATA_DIR": str(tmp_path)})
    assert r.returncode in (0, 1), r.stderr
    assert r.stdout.count("\n| ") >= 6


def _ecrire(chemin: Path, contenu: dict) -> None:
    chemin.write_text(json.dumps(contenu), encoding="utf-8")


def test_params_local_et_foyer_dates_quand_ils_existent(tmp_path):
    racine = _racine(tmp_path, 10, grille_age=0)
    donnees = racine / "immo-data"
    _ecrire(donnees / "params_local.json", {"_lisez_moi": "ignoré",
                                              "dmto": {"departements": {"99": {"taux_departemental": {
                                                  "valeur": 0.05, "source": "fictive", "verifie_le": "2026-01-01"}}}}})
    _ecrire(donnees / "foyer.json", {"tmi": {"valeur": 0.3, "source": "fictive", "date": "2026-09-01"},
                                       "annee": {"valeur": 2026, "source": "fictive", "date": "à remplir"}})
    noms = {r["repere"]: r for r in fr.reperes(racine, AUJOURDHUI, donnees=donnees)}
    assert noms["params_local.json : plus ancienne vérification"]["date"] == date(2026, 1, 1)
    assert noms["params_local.json : plus ancienne vérification"]["etat"] == "PÉRIMÉ"  # 279 jours
    assert noms["foyer.json : plus ancienne date"]["date"] == date(2026, 9, 1)


def test_sans_params_local_ni_foyer_aucun_repere(tmp_path):
    noms = [r["repere"] for r in fr.reperes(_racine(tmp_path, 10), AUJOURDHUI, donnees=tmp_path / "immo-data")]
    assert not any(n.startswith(("params_local", "foyer")) for n in noms)


def test_marche_gabarit_non_rempli_dit_de_lancer_market_context(tmp_path):
    racine = _racine(tmp_path, 10)
    gabarit = ROOT.parent / "templates" / "MARCHE.md"
    (racine / "immo-data/MARCHE.md").write_bytes(gabarit.read_bytes())
    r = _code(racine)
    assert r.returncode == 2 and "MARCHE.md pas encore rempli" in r.stderr and "market-context" in r.stderr


def test_marche_gabarit_rempli_est_lu_malgre_la_consigne_qui_cite_le_format(tmp_path):
    racine = _racine(tmp_path, 10, grille_age=0)
    gabarit = (ROOT.parent / "templates" / "MARCHE.md").read_text(encoding="utf-8")
    rempli = gabarit.replace("\n**Date de référence** : AAAA-MM-JJ", f"\n**Date de référence** : {AUJOURDHUI.isoformat()}")
    (racine / "immo-data/MARCHE.md").write_text(rempli, encoding="utf-8")
    assert _code(racine).returncode == 0


def test_fiche_incomplete_message_clair_code_2(tmp_path):
    racine = _racine(tmp_path, 10, grille_age=0)
    fiche = tmp_path / "fiche.json"
    fiche.write_text(json.dumps({"loyers": {}}), encoding="utf-8")
    r = _code(racine, "--fiche", str(fiche))
    assert r.returncode == 2 and "fiche incomplète : clé « dvf » absente" in r.stderr and "KeyError" not in r.stderr
