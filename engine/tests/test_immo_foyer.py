"""Foyer de l'investisseur (`src/immo/foyer.py`) : lecture et validation de `foyer.json`, option `--foyer` de la CLI.

Données FICTIVES uniquement : un `foyer.json` construit par le test (valeurs inventées) et le gabarit
`templates/foyer.json` du plugin. Aucun test ne lit un foyer réel.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import analyser, foyer, modele  # noqa: E402
from src.immo.financement import assurance_mensuelle, mensualite_amortissement  # noqa: E402

BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
GABARIT = ROOT.parent / "templates" / "foyer.json"


def _f(valeur, source: str = "pièce fictive", quand: str = "2026-09-01") -> dict:
    return {"valeur": valeur, "source": source, "date": quand}


FOYER_FICTIF = {
    "_lisez_moi": "foyer FICTIF de test",
    "annee": _f(2026),
    "tmi": _f(0.41),
    "revenus_activite_mensuels": _f(6543.0),
    "loyers_existants_mensuels": _f(555.0),
    "revenus_fonciers_bruts_existants": _f(6660.0),
    "a_un_bien_ij": _f(False),
    "foncier_existant": {"R": _f(6660.0), "I": _f(1234.0), "C": _f(2468.0), "report_disponible": _f(0.0)},
    "mensualites": {"actuelle": _f(3141.59), "future": _f(4321.0, quand="2026-01-15"), "nb_prets": _f(3)},
}


def _ecrire(tmp_path: Path, brut: dict, nom: str = "foyer.json") -> Path:
    chemin = tmp_path / nom
    chemin.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    return chemin


def _sans(brut: dict, chemin: str) -> dict:
    copie = copy.deepcopy(brut)
    *parents, feuille = chemin.split(".")
    noeud = copie
    for p in parents:
        noeud = noeud[p]
    del noeud[feuille]
    return copie


def _avec(brut: dict, chemin: str, valeur) -> dict:
    copie = copy.deepcopy(brut)
    noeud = copie
    for p in chemin.split("."):
        noeud = noeud[p]
    noeud["valeur"] = valeur
    return copie


# --------------------------------------------------------------------------------------------
# Lecture : la forme du contexte consommé par le moteur.
# --------------------------------------------------------------------------------------------

def test_contexte_a_la_forme_attendue_par_le_moteur(tmp_path):
    ctx = foyer.charger(_ecrire(tmp_path, FOYER_FICTIF))
    assert ctx == {
        "annee": 2026, "tmi": 0.41, "revenus_fonciers_bruts_existants": 6660.0, "a_un_bien_ij": False,
        "foncier_existant": {"R": 6660.0, "I": 1234.0, "C": 2468.0, "report_disponible": 0.0},
        "mensualites": {"actuelle": 3141.59, "future": 4321.0, "nb_prets": 3},
        "revenus_activite_mensuels": 6543.0, "loyers_existants_mensuels": 555.0,
    }
    assert foyer.contexte(_ecrire(tmp_path, FOYER_FICTIF)) == ctx


def test_ponderation_optionnelle_lue_si_presente(tmp_path):
    brut = {**FOYER_FICTIF, "ponderation_loyers": _f(0.8)}
    assert foyer.charger(_ecrire(tmp_path, brut))["ponderation_loyers"] == 0.8


def test_chemin_par_defaut_immo_data_du_repertoire_courant(tmp_path, monkeypatch):
    monkeypatch.delenv("IMMO_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "immo-data").mkdir()
    _ecrire(tmp_path / "immo-data", FOYER_FICTIF)
    assert foyer.charger()["tmi"] == 0.41


def test_variable_immo_data_dir_prime(tmp_path, monkeypatch):
    autre = tmp_path / "ailleurs"
    autre.mkdir()
    _ecrire(autre, _avec(FOYER_FICTIF, "tmi", 0.3))
    monkeypatch.setenv("IMMO_DATA_DIR", str(autre))
    monkeypatch.chdir(tmp_path)
    assert foyer.chemin_par_defaut() == autre / "foyer.json"
    assert foyer.charger()["tmi"] == 0.3


def test_gabarit_du_plugin_refuse_tant_qu_il_n_est_pas_rempli():
    with pytest.raises(ValueError, match="à remplir"):
        foyer.charger(GABARIT)


def test_gabarit_rempli_se_charge(tmp_path):
    brut = json.loads(GABARIT.read_text(encoding="utf-8"))

    def remplir(noeud):
        for v in noeud.values():
            if isinstance(v, dict) and "valeur" in v:
                v.update(source="pièce fictive", date="2026-09-01")
            elif isinstance(v, dict):
                remplir(v)
    remplir(brut)
    ctx = foyer.charger(_ecrire(tmp_path, brut))
    assert set(ctx) >= {"annee", "tmi", "foncier_existant", "mensualites"}


@pytest.mark.parametrize("champ, valeur, morceau", [
    ("source", "À remplir (avis d'imposition)", "à remplir"),
    ("date", "à remplir", "à remplir"),
    ("date", "09/2026", "AAAA-MM-JJ"),
    ("date", "2026-13-01", "AAAA-MM-JJ"),
])
def test_source_ou_date_non_renseignee_refusee(tmp_path, champ, valeur, morceau):
    brut = copy.deepcopy(FOYER_FICTIF)
    brut["tmi"][champ] = valeur
    with pytest.raises(ValueError, match=r"tmi") as exc:
        foyer.charger(_ecrire(tmp_path, brut))
    assert morceau in str(exc.value)


def test_date_la_plus_ancienne(tmp_path):
    assert foyer.date_la_plus_ancienne(_ecrire(tmp_path, FOYER_FICTIF)) == ("mensualites.future", date(2026, 1, 15))


# --------------------------------------------------------------------------------------------
# Validation : une absence ou une valeur invalide arrête, en nommant la clé.
# --------------------------------------------------------------------------------------------

def test_fichier_absent_message_qui_dit_quoi_faire(tmp_path):
    with pytest.raises(ValueError, match=r"foyer introuvable.*templates/foyer.json.*--foyer"):
        foyer.charger(tmp_path / "absent.json")


def test_json_invalide(tmp_path):
    chemin = tmp_path / "foyer.json"
    chemin.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON invalide"):
        foyer.charger(chemin)


@pytest.mark.parametrize("cle", ["annee", "tmi", "revenus_activite_mensuels", "loyers_existants_mensuels",
                                 "revenus_fonciers_bruts_existants", "a_un_bien_ij", "foncier_existant.R",
                                 "foncier_existant.I", "foncier_existant.C", "foncier_existant.report_disponible",
                                 "mensualites.actuelle", "mensualites.future", "mensualites.nb_prets"])
def test_cle_absente_nommee(tmp_path, cle):
    with pytest.raises(ValueError, match=rf"clé requise absente : {cle.replace('.', '[.]')}"):
        foyer.charger(_ecrire(tmp_path, _sans(FOYER_FICTIF, cle)))


@pytest.mark.parametrize("cle, valeur, morceau", [
    ("tmi", 0.6, "entre 0 et 0.45"),
    ("tmi", "30 %", "nombre fini"),
    ("revenus_activite_mensuels", -1, "supérieur ou égal à 0"),
    ("mensualites.future", None, "nombre fini"),
    ("mensualites.nb_prets", 2.5, "entier"),
    ("annee", 26, "entre 2000 et 2100"),
    ("a_un_bien_ij", "non", "true ou false"),
    ("revenus_fonciers_bruts_existants", True, "nombre fini"),
])
def test_valeur_invalide_nommee(tmp_path, cle, valeur, morceau):
    with pytest.raises(ValueError, match=cle.replace(".", "[.]")) as exc:
        foyer.charger(_ecrire(tmp_path, _avec(FOYER_FICTIF, cle, valeur)))
    assert morceau in str(exc.value)


@pytest.mark.parametrize("champ", ["source", "date"])
def test_valeur_sans_source_ou_date_refusee(tmp_path, champ):
    brut = copy.deepcopy(FOYER_FICTIF)
    del brut["tmi"][champ]
    with pytest.raises(ValueError, match=rf"tmi sans {champ}"):
        foyer.charger(_ecrire(tmp_path, brut))


def test_valeur_nue_refusee(tmp_path):
    brut = {**FOYER_FICTIF, "tmi": 0.41}
    with pytest.raises(ValueError, match="tmi doit être un objet"):
        foyer.charger(_ecrire(tmp_path, brut))


def test_aucun_pret_mais_mensualite_non_nulle_refusee(tmp_path):
    with pytest.raises(ValueError, match="nb_prets vaut 0"):
        foyer.charger(_ecrire(tmp_path, _avec(FOYER_FICTIF, "mensualites.nb_prets", 0)))


def test_contexte_foyer_vide_n_est_pas_pris_pour_pas_de_contexte():
    """`{}` est un contexte incomplet : sa clé manquante lève KeyError au lieu d'un calcul « sans contexte »."""
    from src.immo import fiscal_nom_propre
    bien, params = modele.charger_bien(BIEN_FICTIF), modele.charger_params()
    with pytest.raises(KeyError):
        fiscal_nom_propre.fiscalite(bien, params, {})
    with pytest.raises(KeyError):
        analyser(bien, params, contexte_foyer={})


# --------------------------------------------------------------------------------------------
# Taux d'effort : mensualité FUTURE, une seule pondération (bien, sinon foyer, sinon défaut).
# --------------------------------------------------------------------------------------------

def _taux_effort_attendu(bien: dict, ponderation: float) -> float:
    """Recalcul indépendant depuis FOYER_FICTIF : mensualité future ; revenus d'activité + pondération × loyers
    existants ; la MÊME pondération sur le loyer du bien étudié."""
    revenus = 6543.0 + ponderation * 555.0
    return ((4321.0 + mensualite_amortissement(bien) + assurance_mensuelle(bien))
            / (revenus + ponderation * bien["scenarios"]["realiste"]["loyer_mensuel_hc"]))


def test_bloc_hcsf_mensualite_future_et_loyers_ponderes(tmp_path):
    ctx = foyer.charger(_ecrire(tmp_path, FOYER_FICTIF))
    assert foyer.bloc_hcsf(ctx, 0.7) == {"revenus_nets_mensuels": pytest.approx(6543.0 + 0.7 * 555.0),
                                         "mensualites_existantes": 4321.0, "ponderation_loyers": 0.7}


def test_avec_foyer_json_la_ponderation_du_bien_est_ignoree(tmp_path):
    bien = modele.charger_bien(BIEN_FICTIF)
    assert bien["foyer"]["ponderation_loyers"] == 0.7
    ctx = foyer.charger(_ecrire(tmp_path, {**FOYER_FICTIF, "ponderation_loyers": _f(0.5)}))
    h = analyser(bien, contexte_foyer=ctx)["hcsf"]
    assert h["entrees_foyer"]["ponderation_loyers"] == 0.5
    assert h["taux_effort"] == pytest.approx(_taux_effort_attendu(bien, 0.5))


def test_ponderation_du_foyer_puis_defaut_de_params(tmp_path):
    bien = modele.charger_bien(BIEN_FICTIF)
    del bien["foyer"]["ponderation_loyers"]
    ctx = foyer.charger(_ecrire(tmp_path, {**FOYER_FICTIF, "ponderation_loyers": _f(0.5)}))
    sortie = analyser(bien, contexte_foyer=ctx)
    assert sortie["hcsf"]["taux_effort"] == pytest.approx(_taux_effort_attendu(bien, 0.5))
    assert "hcsf.ponderation_loyers_defaut" not in sortie["params_utilises"]
    sans = analyser(bien, contexte_foyer=foyer.charger(_ecrire(tmp_path, FOYER_FICTIF)))
    defaut = modele.valeur(modele.charger_params(), "hcsf.ponderation_loyers_defaut")
    assert sans["hcsf"]["entrees_foyer"]["ponderation_loyers"] == defaut
    assert "hcsf.ponderation_loyers_defaut" in sans["params_utilises"]


# --------------------------------------------------------------------------------------------
# CLI --foyer
# --------------------------------------------------------------------------------------------

def _cli(*args, cwd: Path = ROOT, env: dict | None = None):
    environnement = {k: v for k, v in os.environ.items() if k != "IMMO_DATA_DIR"}
    environnement.update({"PYTHONPATH": str(ROOT), **(env or {})})
    return subprocess.run([sys.executable, "-m", "src.immo", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", timeout=120, env=environnement)


def test_cli_foyer_avec_chemin(tmp_path):
    r = _cli("--bien", str(BIEN_FICTIF), "--foyer", str(_ecrire(tmp_path, FOYER_FICTIF)))
    assert r.returncode == 0, r.stderr
    sortie = json.loads(r.stdout)
    e = sortie["hcsf"]["entrees_foyer"]
    assert set(e) == {"revenus_nets_mensuels", "mensualites_existantes", "ponderation_loyers", "source"}
    assert e["source"] == "foyer.json" and e["mensualites_existantes"] == 4321.0
    assert sortie["hcsf"]["taux_effort"] == pytest.approx(
        _taux_effort_attendu(modele.charger_bien(BIEN_FICTIF), 0.7), abs=1e-6)
    f = sortie["fiscalite"]
    assert f["tmi"] == 0.41 and f["tmi_source"] == "foyer.json:tmi" and f["annee_revenus"] == 2026
    assert "effet_foyer" in f["scenarios"]["realiste"]["regimes"]["foncier_reel"]
    h = " ".join(f["hypotheses"])
    assert "mensualites.future" in h and "mensualites.actuelle" in h and "foyer.json" in h


def test_cli_foyer_sans_chemin_lit_immo_data_du_repertoire_courant(tmp_path):
    (tmp_path / "immo-data").mkdir()
    _ecrire(tmp_path / "immo-data", FOYER_FICTIF)
    r = _cli("--bien", str(BIEN_FICTIF), "--foyer", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["hcsf"]["entrees_foyer"]["mensualites_existantes"] == 4321.0


def test_cli_foyer_absent_code_2_message_clair(tmp_path):
    r = _cli("--bien", str(BIEN_FICTIF), "--foyer", cwd=tmp_path)
    assert r.returncode == 2
    assert "foyer introuvable" in r.stderr and "Traceback" not in r.stderr


def test_cli_foyer_incomplet_code_2_cle_nommee(tmp_path):
    r = _cli("--bien", str(BIEN_FICTIF), "--foyer", str(_ecrire(tmp_path, _sans(FOYER_FICTIF, "mensualites.future"))))
    assert r.returncode == 2 and "mensualites.future" in r.stderr


def test_cli_sans_foyer_pas_d_entrees_foyer_ni_lecture(tmp_path):
    """Sans --foyer, un foyer.json présent dans immo-data/ n'est pas lu."""
    (tmp_path / "immo-data").mkdir()
    _ecrire(tmp_path / "immo-data", FOYER_FICTIF)
    r = _cli("--bien", str(BIEN_FICTIF), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    sortie = json.loads(r.stdout)
    assert "entrees_foyer" not in sortie["hcsf"]
    assert sortie["fiscalite"]["tmi_source"] != "foyer.json:tmi"


def test_main_ne_masque_pas_un_keyerror_en_erreur_d_usage(monkeypatch):
    """Une erreur de données nomme sa cause : un KeyError ne passe pas pour une erreur d'usage (code 2)."""
    from src.immo import __main__ as cli

    def casse(*args, **kwargs):
        raise KeyError("cle_de_donnees_manquante")

    monkeypatch.setattr(cli, "analyser", casse)
    with pytest.raises(KeyError, match="cle_de_donnees_manquante"):
        cli.main(["--bien", str(BIEN_FICTIF)])
