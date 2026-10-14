"""Journal des négociations (`engine/scripts/negoc_journal.py`).

Toutes les écritures ont lieu sous `tmp_path` (dossier de données fictif, `--donnees`). Fixtures FICTIVES :
aucun nom, montant ou libellé d'une négociation réelle.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # engine/
SCRIPT = ROOT / "scripts" / "negoc_journal.py"
sys.path.insert(0, str(ROOT / "scripts"))

import negoc_journal as nj  # noqa: E402

AUJOURDHUI = date(2026, 10, 11)


@pytest.fixture(autouse=True)
def _jour_fixe(monkeypatch):
    monkeypatch.setattr(nj, "aujourdhui", lambda: AUJOURDHUI)


# --------------------------------------------------------------------------------------------------- aides

def cli(capsys, *args, donnees):
    capsys.readouterr()
    code = nj.main([*args, "--donnees", str(donnees)])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def dernier(out: str) -> str:
    return out.rstrip("\n").splitlines()[-1]


def coup(n, d, de, type_, montant, tactiques=()):
    return {"n": n, "date": d, "de": de, "canal": "ecrit", "type": type_, "montant": montant, "conditions": [],
            "leviers": [], "tactiques": list(tactiques), "resume": "Coup fictif de test.", "source": None}


def issue(statut="en_cours", d=None, montant=None, lecons=(), retex=False):
    return {"statut": statut, "date": d, "montant_final": montant, "conditions_finales": [],
            "lecons": list(lecons), "retex_integre": retex}


def journal(slug="essai-fictif", terrain="immo_achat", role="acheteur", reperes=(200000, 160000, 175000, 185000),
            coups=(), iss=None):
    prix, ouverture, cible, limite = reperes
    return {
        "schema": "negoc-journal/1", "slug": slug, "terrain": terrain, "objet": "Bien fictif de test",
        "notre_role": role, "contrepartie": {"type": "particulier", "intermediaire": None, "signaux": []},
        "devise": "EUR",
        "reperes": {"prix_affiche": prix, "ouverture": ouverture, "cible": cible, "limite": limite,
                    "unite": "eur", "source": None},
        "batna": None, "coups": list(coups), "issue": iss or issue(),
    }


def ecrire(donnees: Path, j: dict, nom: str | None = None) -> Path:
    chemin = donnees / "negociations" / f"{nom or j['slug']}.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(j, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return chemin


def fixture_conclue():
    return journal("fixture-conclue", coups=[
        coup(1, "2026-01-05", "nous", "offre", 160000, ["justification_pieces"]),
        coup(2, "2026-01-08", "eux", "contre_offre", 190000),
        coup(3, "2026-01-15", "nous", "offre", 170000, ["concession_contre_contrepartie"]),
        coup(4, "2026-01-20", "eux", "acceptation", 170000)], iss=issue("conclu", "2026-01-20", 170000))


def fixture_devis_rompu():
    return journal("fixture-devis", terrain="artisan", role="client", reperes=(10000, 7400, 8100, 8800), coups=[
        coup(1, "2026-03-01", "nous", "offre", 7400, ["justification_pieces"]),
        coup(2, "2026-03-02", "eux", "refus", None)], iss=issue("rompu_par_eux", "2026-03-10"))


def nouveau(capsys, donnees, *extra, slug="essai-fictif", terrain="immo_achat", role="acheteur"):
    return cli(capsys, "nouveau", "--slug", slug, "--terrain", terrain, "--role", role,
               "--objet", "Bien fictif de test", *extra, donnees=donnees)


# ------------------------------------------------------------------------------------------------- contrat

def test_deux_terrains_seulement():
    assert nj.TERRAINS == ("immo_achat", "artisan")
    assert set(nj.ROLES) == {"acheteur", "client"}
    assert not hasattr(nj, "DOSSIERS")


def test_script_n_importe_que_la_bibliotheque_standard():
    arbre = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules = {a.name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}


def test_dossier_par_defaut_cwd_puis_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("IMMO_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert nj.donnees_par_defaut() == tmp_path / "immo-data"
    monkeypatch.setenv("IMMO_DATA_DIR", str(tmp_path / "ailleurs"))
    assert nj.donnees_par_defaut() == tmp_path / "ailleurs"


def test_nouveau_sans_option_ecrit_sous_immo_data_du_repertoire_courant(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IMMO_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    code = nj.main(["nouveau", "--slug", "essai-fictif", "--terrain", "artisan", "--role", "client",
                    "--objet", "Devis fictif"])
    assert code == 0
    assert dernier(capsys.readouterr().out) == "RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/essai-fictif.json"


# ------------------------------------------------------------------------------------------ écriture

def test_nouveau_squelette_valide(tmp_path, capsys):
    code, out, _ = nouveau(capsys, tmp_path, "--prix-affiche", "200000", "--ouverture", "160000",
                           "--cible", "175000", "--limite", "185000")
    assert code == 0 and "RESULT=NEGOC_JOURNAL_ECRIT" in out
    j = json.loads((tmp_path / "negociations" / "essai-fictif.json").read_text(encoding="utf-8"))
    assert j["terrain"] == "immo_achat" and "workstream" not in j
    assert j["reperes"]["limite"] == 185000 and j["issue"]["statut"] == "en_cours"


@pytest.mark.parametrize("terrain", ["credit", "contrat", "cession", "autre"])
def test_nouveau_refuse_un_terrain_retire(tmp_path, capsys, terrain):
    code, out, _ = nouveau(capsys, tmp_path, terrain=terrain)
    assert code == 1 and "terrain : valeur hors enum" in out
    assert not (tmp_path / "negociations").exists()


def test_nouveau_refuse_fichier_existant(tmp_path, capsys):
    ecrire(tmp_path, journal())
    code, out, _ = nouveau(capsys, tmp_path)
    assert code == 1 and dernier(out) == "RESULT=NEGOC_JOURNAL_REFUS(fichier existant)"


def test_cycle_complet_nouveau_coup_clore_check(tmp_path, capsys):
    nouveau(capsys, tmp_path, "--limite", "185000")
    f = str(tmp_path / "negociations" / "essai-fictif.json")
    assert cli(capsys, "coup", "--fichier", f, "--de", "nous", "--type", "offre", "--canal", "ecrit",
               "--resume", "Offre fictive.", "--montant", "160000", "--date", "2026-01-05", donnees=tmp_path)[0] == 0
    code, out, _ = cli(capsys, "coup", "--fichier", f, "--de", "nous", "--type", "offre", "--canal", "ecrit",
                       "--resume", "Offre fictive haute.", "--montant", "190000", donnees=tmp_path)
    assert code == 0 and "coup 2 au-delà de la limite : décision à tracer" in out
    assert cli(capsys, "clore", "--fichier", f, "--statut", "conclu", "--montant-final", "180000",
               donnees=tmp_path)[0] == 0
    j = json.loads(Path(f).read_text(encoding="utf-8"))
    assert [c["n"] for c in j["coups"]] == [1, 2] and j["coups"][1]["date"] == AUJOURDHUI.isoformat()
    code, out, _ = cli(capsys, "coup", "--fichier", f, "--de", "nous", "--type", "relance", "--canal", "ecrit",
                       "--resume", "Relance.", donnees=tmp_path)
    assert code == 1 and dernier(out) == "RESULT=NEGOC_JOURNAL_REFUS(journal clos)"


def test_coup_refuse_date_anterieure(tmp_path, capsys):
    f = ecrire(tmp_path, journal(coups=[coup(1, "2026-02-01", "nous", "offre", 160000)]))
    code, out, _ = cli(capsys, "coup", "--fichier", str(f), "--de", "eux", "--type", "refus", "--canal", "ecrit",
                       "--resume", "Refus.", "--date", "2026-01-01", donnees=tmp_path)
    assert code == 1 and "date antérieure au dernier coup" in out


def test_fichier_hors_du_dossier_des_journaux_code_2(tmp_path, capsys):
    autre = tmp_path / "ailleurs" / "essai-fictif.json"
    autre.parent.mkdir()
    autre.write_text(json.dumps(journal()), encoding="utf-8")
    code, out, _ = cli(capsys, "coup", "--fichier", str(autre), "--de", "nous", "--type", "offre",
                       "--canal", "ecrit", "--resume", "x", donnees=tmp_path)
    assert code == 2 and "hors du dossier des journaux" in out
    assert cli(capsys, "check", "--fichier", str(autre), donnees=tmp_path)[0] == 2


def test_clore_conclu_sans_montant_refuse(tmp_path, capsys):
    f = ecrire(tmp_path, journal())
    code, out, _ = cli(capsys, "clore", "--fichier", str(f), "--statut", "conclu", donnees=tmp_path)
    assert code == 1 and dernier(out) == "RESULT=NEGOC_JOURNAL_REFUS(conclu sans --montant-final)"


# ------------------------------------------------------------------------------------------------- check

def test_check_aucun_journal(tmp_path, capsys):
    code, out, _ = cli(capsys, "check", donnees=tmp_path)
    assert code == 0 and "aucun journal trouvé" in out and dernier(out) == "RESULT=NEGOC_JOURNAL_OK"


def test_check_fixtures_ok(tmp_path, capsys):
    ecrire(tmp_path, fixture_conclue())
    ecrire(tmp_path, fixture_devis_rompu())
    code, out, _ = cli(capsys, "check", donnees=tmp_path)
    assert code == 0 and out.count("OK ") == 2


@pytest.mark.parametrize("modif, motif", [
    (lambda j: j.update(workstream="finance"), "clé inconnue : workstream"),
    (lambda j: j["reperes"].update(unite="taux_pct"), "reperes.unite : valeur hors enum"),
    (lambda j: j.update(notre_role="emprunteur"), "notre_role : valeur hors enum"),
    (lambda j: j["contrepartie"].update(type="banque"), "contrepartie.type : valeur hors enum"),
    (lambda j: j["reperes"].update(cible=190000), "reperes.cible : 190000 au-delà de reperes.limite"),
    (lambda j: j.update(slug="autre-nom"), "différent du nom du fichier"),
    (lambda j: j["issue"].update(retex_integre=True), "doit être faux tant que le statut est en_cours"),
])
def test_check_echecs(tmp_path, capsys, modif, motif):
    j = journal()
    modif(j)
    ecrire(tmp_path, j, nom="essai-fictif")
    code, out, _ = cli(capsys, "check", donnees=tmp_path)
    assert code == 1 and motif in out


@pytest.mark.parametrize("texte, type_", [
    ("Contact : contact@exemple.fr", "courriel"),
    ("Rappeler au 06 00 00 00 00", "téléphone"),
    ("Virement sur FR76 0000 0000 0000 0000 0000 000", "IBAN"),
    ("Réponse de Madame Fictive", "civilité et nom"),
])
def test_check_donnees_personnelles(tmp_path, capsys, texte, type_):
    j = journal(coups=[coup(1, "2026-01-05", "eux", "information", None)])
    j["coups"][0]["resume"] = texte
    ecrire(tmp_path, j)
    code, out, _ = cli(capsys, "check", donnees=tmp_path)
    assert code == 1 and f"donnée personnelle probable ({type_})" in out


# ------------------------------------------------------------------------------------------------- bilan

def test_bilan_json_par_terrain(tmp_path, capsys):
    ecrire(tmp_path, fixture_conclue())
    ecrire(tmp_path, fixture_devis_rompu())
    code, out, err = cli(capsys, "bilan", "--json", donnees=tmp_path)
    assert code == 0 and err.strip() == "RESULT=NEGOC_BILAN_OK"
    b = json.loads(out)
    groupes = {(g["terrain"], g["sens"]): g for g in b["groupes"]}
    assert set(groupes) == {("immo_achat", "baisse"), ("artisan", "baisse")}
    immo = groupes[("immo_achat", "baisse")]
    assert immo["premiere_offre_vs_affiche"]["mediane"] == pytest.approx(-0.2)
    assert immo["final_vs_affiche"]["mediane"] == pytest.approx(-0.15)
    assert immo["dans_cible"] == {"oui": 1, "n": 1}
    assert immo["coups_jusqu_accord"]["mediane"] == 4 and immo["jours_jusqu_accord"]["mediane"] == 15
    assert immo["avertissement"] == nj.AVERTISSEMENT
    artisan = groupes[("artisan", "baisse")]
    assert artisan["statuts"] == {"rompu_par_eux": 1}
    assert artisan["tactiques"] == {"justification_pieces": {"conclu": 0, "clos_sans_accord": 1}}


def test_bilan_texte_et_filtre(tmp_path, capsys):
    ecrire(tmp_path, fixture_conclue())
    ecrire(tmp_path, fixture_devis_rompu())
    code, out, _ = cli(capsys, "bilan", "--terrain", "artisan", donnees=tmp_path)
    assert code == 0 and "== artisan / baisse : 1 journal ==" in out and "immo_achat" not in out
    assert dernier(out) == "RESULT=NEGOC_BILAN_OK"


@pytest.mark.parametrize("valeur, attendu", [(-0.2, "-20,0 %"), (0.075, "+7,5 %"), (0.0, "+0,0 %"), (None, "n.d.")])
def test_format_pourcentage(valeur, attendu):
    assert nj.pct(valeur) == attendu


def test_script_en_ligne_de_commande(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "check", "--donnees", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.rstrip().endswith("RESULT=NEGOC_JOURNAL_OK")
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 2
