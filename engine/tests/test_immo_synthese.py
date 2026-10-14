"""Synthèse de la sortie du moteur immo (`scripts/immo_synthese.py`).

Données FICTIVES uniquement : la fixture `bien_fictif.json` et un contexte de foyer fictif injecté par
monkeypatch. Aucun test ne lit les sources réelles du foyer.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import biens_test  # noqa: E402

from src.immo import analyser  # noqa: E402

BIEN_FICTIF = biens_test.chemin("bien_fictif.json")
BIEN_FICTIF_SCI_IS = biens_test.chemin("bien_fictif_sci_is.json")
SCRIPT = ROOT / "scripts" / "immo_synthese.py"

_spec = importlib.util.spec_from_file_location("immo_synthese", SCRIPT)
synthese = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthese)

# Contexte de foyer FICTIF, à la forme de `src.immo.foyer.contexte()`. Valeurs choisies pour ne
# ressembler à rien de réel.
CONTEXTE_FICTIF = {
    "annee": 2026,
    "tmi": 0.41,
    "revenus_fonciers_bruts_existants": 7777.0,
    "a_un_bien_ij": False,
    "foncier_existant": {"R": 7777.0, "I": 1234.0, "C": 2468.0, "report_disponible": 0.0},
    "mensualites": {"actuelle": 3141.59, "future": 4321.0, "nb_prets": 3},
    "revenus_activite_mensuels": 6543.0,
    "loyers_existants_mensuels": 555.0,
}


@pytest.fixture(scope="module")
def sortie_cli(tmp_path_factory) -> Path:
    """Sortie réelle de la CLI du moteur sur la fixture fictive, sans `--foyer`."""
    res = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(BIEN_FICTIF)],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    chemin = tmp_path_factory.mktemp("sortie") / "sortie.json"
    chemin.write_text(res.stdout, encoding="utf-8")
    return chemin


def _ecrire(tmp_path: Path, donnees: dict, nom: str = "sortie.json") -> Path:
    chemin = tmp_path / nom
    chemin.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    return chemin


def _lancer(capsys, *args: str) -> tuple[int, str, str]:
    rc = synthese.main(list(args))
    out, err = capsys.readouterr()
    return rc, out, err


# --------------------------------------------------------------------------------------------
# 1. Synthèse de la sortie de la fixture
# --------------------------------------------------------------------------------------------

def test_synthese_fixture(sortie_cli, capsys):
    rc, out, _ = _lancer(capsys, "--sortie", str(sortie_cli))
    assert rc == 0
    for titre in ("## Acquisition", "## Financement", "## Scénarios", "## Prix d'équilibre", "## HCSF",
                  "## Fiscalité", "## Hypothèses"):
        assert titre in out, titre
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    for nom in donnees["scenarios"]:
        assert f"| {nom} |" in out, nom
    # Autant de lignes de régime que la sortie en porte : comptées dans la sortie, pas en dur.
    attendues = [(s, r) for s, v in donnees["fiscalite"]["scenarios"].items() for r in v["regimes"]]
    assert len(attendues) >= 15
    for s, r in attendues:
        assert f"| {s} | {r} |" in out, (s, r)
    assert "foyer : absent" in out
    assert "blocs non lus : aucun" in out
    assert len(out.splitlines()) <= 80
    assert len(out.encode("utf-8")) * 5 < sortie_cli.stat().st_size


def test_montants_a_l_euro_et_ratios_en_pourcent(sortie_cli, capsys):
    _, out, _ = _lancer(capsys, "--sortie", str(sortie_cli))
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    cout = round(donnees["acquisition"]["cout_total"])
    assert f"{cout:,}".replace(",", " ") + " €" in out
    taux = donnees["financement"]["taux_nominal"] * 100
    assert f"{taux:.2f}".replace(".", ",") + " %" in out


def test_hypotheses_toutes_listees(sortie_cli, capsys):
    _, out, _ = _lancer(capsys, "--sortie", str(sortie_cli))
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    for h in donnees["fiscalite"]["hypotheses"]:
        assert f"- {h}" in out


def test_entrees_foyer_cles_seules(tmp_path, capsys):
    bien = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    bien.pop("foyer")
    sortie = analyser(bien, contexte_foyer=copy.deepcopy(CONTEXTE_FICTIF))
    entrees = sortie["hcsf"]["entrees_foyer"]
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, sortie)))
    assert rc == 0
    for cle in entrees:
        assert cle in out
    assert "foyer : absent" not in out
    for valeur in (entrees["revenus_nets_mensuels"], entrees["mensualites_existantes"]):
        assert f"{round(valeur):,}".replace(",", " ") not in out
        assert str(round(valeur)) not in out


def test_effet_foyer_marginal_seul_affiche(tmp_path, capsys):
    """Avec un foyer, l'impôt du foncier réel est celui du bien seul : l'effet marginal doit se lire."""
    bien = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    bien.pop("foyer")
    sortie = analyser(bien, contexte_foyer=copy.deepcopy(CONTEXTE_FICTIF))
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, sortie)))
    assert rc == 0
    ligne = next(l for l in out.splitlines() if l.startswith("- effet_foyer foncier_reel"))
    for s, sc in sortie["fiscalite"]["scenarios"].items():
        effet = sc["regimes"]["foncier_reel"]["effet_foyer"]
        assert f"{s} {synthese.euros(effet['effet_marginal'])}" in ligne
        for cle in ("impot_foyer_seul", "impot_foyer_avec_bien"):
            assert synthese.euros(effet[cle]) not in ligne
    del sortie["fiscalite"]["scenarios"]["realiste"]["regimes"]["foncier_reel"]["effet_foyer"]["effet_marginal"]
    rc, _, err = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, sortie, "sans_effet.json")))
    assert rc == 2
    assert "fiscalite.scenarios.realiste.regimes.foncier_reel.effet_foyer.effet_marginal" in err


# --------------------------------------------------------------------------------------------
# 2. Clé attendue absente : rc=2, la clé nommée ; jamais de valeur par défaut
# --------------------------------------------------------------------------------------------

CLES_RETIREES = [
    ("acquisition", "cout_total"),
    ("financement", "mensualite_totale"),
    ("scenarios", "realiste", "indicateurs", "cash_on_cash"),
    ("prix_equilibre", "optimiste"),
    ("hcsf", "taux_effort"),
    ("fiscalite", "tmi_source"),
    ("fiscalite", "scenarios", "realiste", "regimes", "lmnp_reel", "impot_total"),
]


@pytest.mark.parametrize("chemin", CLES_RETIREES, ids=".".join)
def test_cle_retiree_rc2(sortie_cli, tmp_path, capsys, chemin):
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    noeud = donnees
    for cle in chemin[:-1]:
        noeud = noeud[cle]
    del noeud[chemin[-1]]
    rc, out, err = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 2
    assert ".".join(chemin) in err
    assert out == ""


def test_bloc_premier_niveau_absent_rc2(sortie_cli, tmp_path, capsys):
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    del donnees["fiscalite"]
    rc, _, err = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 2 and "fiscalite" in err


# --------------------------------------------------------------------------------------------
# 3. Blocs inconnus et régimes futurs : lus sans être énumérés en dur
# --------------------------------------------------------------------------------------------

def test_cle_inconnue_listee(sortie_cli, tmp_path, capsys):
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    donnees["sortie_revente"] = {"tri": 0.05}
    donnees["tableur"] = {}
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 0
    assert "blocs non lus : sortie_revente, tableur" in out


def _regime_fictif(**extra) -> dict:
    return {"evaluable": True, "eligible": True, "raisons": [], "impot_total": 111.0,
            "cash_flow_mensuel_net_net": -22.0, "rendement_net_net": 0.031, **extra}


def test_regime_inconnu_et_distribution(sortie_cli, tmp_path, capsys):
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    for sc in donnees["fiscalite"]["scenarios"].values():
        sc["regimes"]["sci_ir"] = _regime_fictif()
        sc["regimes"]["sci_is"] = _regime_fictif(distribution={"cash_flow_mensuel_foyer": -987.0})
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 0
    for s in donnees["fiscalite"]["scenarios"]:
        assert f"| {s} | sci_ir |" in out
        assert f"| {s} | sci_is |" in out
    assert "| -987 |" in out
    assert len(out.splitlines()) <= 80


def test_distribution_sans_cash_flow_foyer_rc2(sortie_cli, tmp_path, capsys):
    # Une distribution non vide sans `cash_flow_mensuel_foyer` reste une clé absente ; `{}` (aucun
    # versement) est le cas normal, couvert par test_sci_is_qui_capitalise_sans_distribution.
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    donnees["fiscalite"]["scenarios"]["realiste"]["regimes"]["sci_is"] = _regime_fictif(
        distribution={"distribuable": True})
    rc, _, err = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 2
    assert "fiscalite.scenarios.realiste.regimes.sci_is.distribution.cash_flow_mensuel_foyer" in err


def _sortie_sci_is_qui_capitalise(tmp_path: Path) -> Path:
    """Sortie réelle du moteur, sans `--foyer`, pour une SCI à l'IS qui ne verse rien."""
    bien = json.loads(BIEN_FICTIF_SCI_IS.read_text(encoding="utf-8"))
    bien["sci"].update(distribution_annuelle=0, remboursement_cca_annuel=0)
    chemin_bien = _ecrire(tmp_path, bien, "bien.json")
    res = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(chemin_bien)],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    chemin = tmp_path / "sortie.json"
    chemin.write_text(res.stdout, encoding="utf-8")
    return chemin


def test_sci_is_qui_capitalise_sans_distribution(tmp_path, capsys):
    sortie = _sortie_sci_is_qui_capitalise(tmp_path)
    assert json.loads(sortie.read_text(encoding="utf-8"))["fiscalite"]["scenarios"]["realiste"]["regimes"][
        "sci_is"]["distribution"] == {}
    rc, out, err = _lancer(capsys, "--sortie", str(sortie))
    assert rc == 0, err
    for s in synthese.SCENARIOS:
        assert f"| {s} | sci_is |" in out
    assert "CF foyer (distribution)" not in out


def test_sci_is_qui_capitalise_verifier(foyer_fictif, tmp_path, capsys):
    sortie = _sortie_sci_is_qui_capitalise(tmp_path)
    analyse = tmp_path / "analyse.md"
    analyse.write_text("# Analyse\nAucune valeur du foyer ici.\n", encoding="utf-8")
    rc, out, err = _lancer(capsys, "--sortie", str(sortie), "--verifier", str(analyse))
    assert rc == 0, err
    assert "aucune valeur du foyer" in out


def test_hcsf_non_calcule(sortie_cli, tmp_path, capsys):
    donnees = json.loads(sortie_cli.read_text(encoding="utf-8"))
    donnees["hcsf"] = {"calcule": False, "raison": "bloc foyer absent de l'entrée"}
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 0
    assert "bloc foyer absent de l'entrée" in out


# --------------------------------------------------------------------------------------------
# 4. --verifier : aucune valeur du foyer dans l'analyse (contexte FICTIF monkeypatché)
# --------------------------------------------------------------------------------------------

@pytest.fixture()
def foyer_fictif(monkeypatch):
    from src.immo import foyer
    monkeypatch.setattr(foyer, "contexte", lambda chemin=None: copy.deepcopy(CONTEXTE_FICTIF))


ANALYSE_PROPRE = """# Analyse fictive
## Rentabilité
Loyer réaliste : 1 300 € HC (carte ANIL 2025). Coût total : 245 637 €.
TMI du foyer : voir foyer.json. Année 2026, 3 prêts.
Mensualité 13 141 € et 43 210 € : d'autres nombres, sans rapport.
"""

FORMES = {
    "nue": "Mensualités existantes : 4321 €/mois.",
    "espace": "Mensualités existantes : 4 321 €/mois.",
    "espace_fine": "Mensualités existantes : 4 321 €/mois.",
    "insecable": "Mensualités existantes : 4 321 €/mois.",
    "decimales": "Mensualités existantes : 4 321,00 €/mois.",
    "decimales_exactes": "Mensualité actuelle : 3 141,59 €/mois.",
}


def _verifier(capsys, sortie: Path, analyse: Path) -> tuple[int, str, str]:
    return _lancer(capsys, "--sortie", str(sortie), "--verifier", str(analyse))


@pytest.mark.parametrize("forme", FORMES)
def test_verifier_trouve_une_valeur_du_foyer(foyer_fictif, sortie_cli, tmp_path, capsys, forme):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + FORMES[forme] + "\n", encoding="utf-8")
    avant = sorted(p.name for p in tmp_path.iterdir())
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 1
    texte = out + err
    assert "ligne 6" in texte
    assert "mensualites." in texte
    for interdit in ("4321", "4 321", "3141", "3 141"):
        assert interdit not in texte  # la valeur ne se réimprime pas
    assert sorted(p.name for p in tmp_path.iterdir()) == avant  # n'écrit rien


def test_verifier_analyse_propre_rc0(foyer_fictif, sortie_cli, tmp_path, capsys):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE, encoding="utf-8")
    rc, _, _ = _verifier(capsys, sortie_cli, analyse)
    assert rc == 0


def test_verifier_ignore_tmi_annee_et_petites_valeurs(foyer_fictif, sortie_cli, tmp_path, capsys):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + "TMI 0,41 ; année 2026 ; 3 prêts ; report 0 €.\n", encoding="utf-8")
    rc, _, _ = _verifier(capsys, sortie_cli, analyse)
    assert rc == 0


# Nombres qui ne sont pas des montants : 1234 est la valeur fictive `foncier_existant.I`.
REFERENCES = {
    "cgi": "Charges déductibles : CGI 1234 I-3°.",
    "art_point": "Raccordement : art. 1234 du code civil.",
    "art_majuscule": "Raccordement : Art. 1234 du code civil.",
    "article": "Voir l'article 1234 du code civil.",
    "code_r": "Contrôle : art. R. 1234-23 CSP.",
    "code_l": "Voir L. 1234 du code de l'urbanisme.",
    "code_d": "Voir D. 1234 du code de la construction.",
    "code_sans_espace": "Voir R.1234 et L.1234.",
    "dpe_ademe": "DPE ADEME 2577E1234E.",
    "lettre_collee": "Référence CGI1234 ; lot B1234.",
    "mutation_dvf": "Mutation DVF 1234-991729 du 12/03/2025.",
    "parcelle": "Parcelle AS 01234.",
}


@pytest.mark.parametrize("forme", REFERENCES)
def test_verifier_ignore_articles_et_identifiants(foyer_fictif, sortie_cli, tmp_path, capsys, forme):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + REFERENCES[forme] + "\n", encoding="utf-8")
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 0, out + err


MONTANTS = {
    "espace": "Intérêts : 1 234 €.",
    "nu": "Intérêts : 1234 €.",
    "decimales": "Intérêts : 1234,5 €.",
    "tableau": "| intérêts | 1 234 |",
    "apres_un_article": "Selon l'art. 31, intérêts de 1 234 €.",
    "fin_de_phrase": "Intérêts déductibles. 1234 € par an.",
    "tiret_sans_chiffre": "Intérêts : 1234 - à confirmer.",
}


@pytest.mark.parametrize("forme", MONTANTS)
def test_verifier_garde_les_vrais_montants(foyer_fictif, sortie_cli, tmp_path, capsys, forme):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + MONTANTS[forme] + "\n", encoding="utf-8")
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 1
    assert "foncier_existant.I → ligne 6" in out + err


def test_verifier_controle_aussi_les_entrees_foyer_de_la_sortie(foyer_fictif, tmp_path, capsys):
    bien = json.loads(BIEN_FICTIF.read_text(encoding="utf-8"))
    bien.pop("foyer")
    sortie = analyser(bien, contexte_foyer=copy.deepcopy(CONTEXTE_FICTIF))
    revenus = round(sortie["hcsf"]["entrees_foyer"]["revenus_nets_mensuels"])
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + f"Revenus retenus : {revenus:,} €.\n".replace(",", " "), encoding="utf-8")
    rc, out, err = _verifier(capsys, _ecrire(tmp_path, sortie), analyse)
    assert rc == 1
    assert "hcsf.entrees_foyer.revenus_nets_mensuels → ligne 6" in out + err


def test_verifier_sans_sortie_lit_le_seul_contexte(foyer_fictif, tmp_path, capsys):
    """Étude arrêtée avant le moteur (sans prix) : le contrôle tourne quand même, sur contexte() seul."""
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE, encoding="utf-8")
    assert _lancer(capsys, "--verifier", str(analyse))[0] == 0
    analyse.write_text(ANALYSE_PROPRE + FORMES["espace"] + "\n", encoding="utf-8")
    rc, out, _ = _lancer(capsys, "--verifier", str(analyse))
    assert rc == 1 and "mensualites.future → ligne 6" in out


def test_ni_sortie_ni_verifier_rc2(capsys):
    rc, _, err = _lancer(capsys)
    assert rc == 2 and "--sortie" in err


# --------------------------------------------------------------------------------------------
# 5. --verifier renforcé : ×12 d'un montant mensuel, source HTML, longueur de l'étude
# --------------------------------------------------------------------------------------------

# Dérivé ×12 seul des valeurs FICTIVES mensuelles : mensualites.future 4321
# → 51 852 ; revenus_activite_mensuels 6543 → 78 516. Aucun ÷12.
DERIVES = {
    "annuel_espace": ("Mensualités sur l'année : 51 852 €.", "mensualites.future ×12"),
    "annuel_nu": ("Revenus annuels : 78516 €.", "revenus_activite_mensuels ×12"),
}


@pytest.mark.parametrize("forme", DERIVES)
def test_verifier_trouve_les_montants_x12(foyer_fictif, sortie_cli, tmp_path, capsys, forme):
    texte, cle = DERIVES[forme]
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + texte + "\n", encoding="utf-8")
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 1, out + err
    assert f"{cle} → ligne 6" in out
    for interdit in ("51852", "51 852", "78516", "78 516"):
        assert interdit not in out + err


# Plus de ÷12 : annuel ÷12 (revenus_fonciers_bruts_existants 7777 → 648 ; foncier_existant.R 7777 → 648 ;
# foncier_existant.C 2468 → 206), mensuel ÷12 (mensualites.future → 360), annuel ×12 (foncier_existant.I 1234
# → 14 808) : non refusés.
@pytest.mark.parametrize("texte", ["Foncier existant : 648 €/mois.", "Charges : 206 € par mois.",
                                   "Charges : 360 € par mois.", "Travaux : 14 808 €."])
def test_verifier_ne_cherche_plus_le_div12(foyer_fictif, sortie_cli, tmp_path, capsys, texte):
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + texte + "\n", encoding="utf-8")
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 0, out + err


def test_verifier_derive_sous_100_ignore(foyer_fictif, sortie_cli, tmp_path, capsys):
    """loyers_existants_mensuels 555 : ×12 = 6 660 cherché ; 46 (÷12) jamais."""
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + "Vacance : 46 € par mois.\n", encoding="utf-8")
    assert _verifier(capsys, sortie_cli, analyse)[0] == 0


def test_verifier_x12_en_k_euros_accepte_d4(foyer_fictif, sortie_cli, tmp_path, capsys):
    """L'écriture en k€ reste l'échappatoire d'un montant du bien égal à un montant du foyer."""
    analyse = tmp_path / "analyse.md"
    analyse.write_text(ANALYSE_PROPRE + "Mensualités sur l'année : ≈ 51,9 k€.\n", encoding="utf-8")
    assert _verifier(capsys, sortie_cli, analyse)[0] == 0


HTML = {
    "balise": "<p>Mensualités : 4<span class=\"x\">321</span> €</p>",
    "nbsp": "<p>Mensualités : 4&nbsp;321 €</p>",
    "fine": "<p>Mensualités : 4&#8239;321 €</p>",
    "balise_et_nbsp": "<td>51&nbsp;<b>852</b></td>",
}


@pytest.mark.parametrize("forme", HTML)
def test_verifier_source_html_refusee(foyer_fictif, sortie_cli, tmp_path, capsys, forme):
    analyse = tmp_path / "presentation.html"
    analyse.write_text("<html><body>\n<h1>Analyse fictive</h1>\n" + HTML[forme] + "\n</body></html>\n",
                       encoding="utf-8")
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 1, out + err
    assert "ligne 3" in out


def test_verifier_source_html_propre_acceptee(foyer_fictif, sortie_cli, tmp_path, capsys):
    analyse = tmp_path / "presentation.html"
    analyse.write_text("<html><body><p>Loyer : 1&nbsp;300 €, <b>245 637</b> €</p></body></html>\n", encoding="utf-8")
    assert _verifier(capsys, sortie_cli, analyse)[0] == 0


@pytest.mark.parametrize("lignes, nom, averti", [(301, "etude.md", True), (300, "etude.md", False),
                                                 (301, "etude-annexes.md", False)])
def test_verifier_avertit_une_etude_longue_sans_changer_le_code(foyer_fictif, sortie_cli, tmp_path, capsys,
                                                                lignes, nom, averti):
    analyse = tmp_path / nom
    analyse.write_text(ANALYSE_PROPRE + "ligne\n" * (lignes - ANALYSE_PROPRE.count("\n")), encoding="utf-8")
    assert len(analyse.read_text(encoding="utf-8").splitlines()) == lignes
    rc, out, err = _verifier(capsys, sortie_cli, analyse)
    assert rc == 0
    assert ("300 lignes" in err) is averti
    analyse.write_text(analyse.read_text(encoding="utf-8") + FORMES["espace"] + "\n", encoding="utf-8")
    assert _verifier(capsys, sortie_cli, analyse)[0] == 1


# --------------------------------------------------------------------------------------------
# Section « Sortie » : seulement si la sortie du moteur
# porte la clé `sortie` ; sinon la synthèse ne change pas (tests ci-dessus inchangés).
# --------------------------------------------------------------------------------------------

BIEN_FICTIF_SORTIE = biens_test.chemin("bien_fictif_sci_is_sortie.json")


@pytest.fixture(scope="module")
def sortie_cli_avec_sortie(tmp_path_factory) -> Path:
    """Sortie réelle de la CLI du moteur sur la fixture fictive à bloc `sortie`, sans `--foyer`."""
    res = subprocess.run([sys.executable, "-m", "src.immo", "--bien", str(BIEN_FICTIF_SORTIE)],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    chemin = tmp_path_factory.mktemp("sortie_revente") / "sortie.json"
    chemin.write_text(res.stdout, encoding="utf-8")
    return chemin


def _euros_texte(v: float) -> str:
    return f"{round(v):,}".replace(",", " ") + " €"


def test_section_sortie_par_scenario(sortie_cli_avec_sortie, capsys):
    rc, out, err = _lancer(capsys, "--sortie", str(sortie_cli_avec_sortie))
    assert rc == 0, err
    donnees = json.loads(sortie_cli_avec_sortie.read_text(encoding="utf-8"))
    lignes = out.splitlines()
    titre = next(l for l in lignes if l.startswith("## Sortie"))
    assert titre.startswith("## Sortie à 10 ans (SCI à l'IS)") and "VAN à 4,00 %" in titre
    for s in synthese.SCENARIOS:
        v = donnees["sortie"][s]
        ligne = next(l for l in lignes if l.startswith(f"- {s} : TRI "))
        is_cession = v["revente"]["is_avec_cession"] - v["revente"]["is_sans_cession"]
        for attendu in (f"TRI {v['tri'] * 100:.2f}".replace(".", ",") + " %", f"VAN {_euros_texte(v['van'])}",
                        f"plus-value {_euros_texte(v['revente']['plus_value'])}",
                        f"IS de la cession {_euros_texte(is_cession)}",
                        f"boni net {_euros_texte(v['liquidation']['boni_net'])}",
                        f"reçu à la sortie {_euros_texte(v['liquidation']['recu_associes'])}"):
            assert attendu in ligne, (s, attendu)
    assert "blocs non lus : aucun" in out
    assert lignes.index(titre) < next(i for i, l in enumerate(lignes) if l.startswith("## Hypothèses"))
    assert len(lignes) <= 80


def test_section_sortie_absente_sans_cle_sortie(sortie_cli, capsys):
    _, out, _ = _lancer(capsys, "--sortie", str(sortie_cli))
    assert "## Sortie" not in out and "reçu à la sortie" not in out


def test_section_sortie_tri_et_van_absents(sortie_cli_avec_sortie, tmp_path, capsys):
    donnees = json.loads(sortie_cli_avec_sortie.read_text(encoding="utf-8"))
    donnees["bien"]["sortie"]["taux_actualisation"] = None
    for v in donnees["sortie"].values():
        v["tri"], v["van"] = None, None
    rc, out, _ = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 0
    assert "VAN non calculée" in out
    assert "- realiste : TRI n/a · VAN n/a ·" in out


@pytest.mark.parametrize("chemin", [("sortie", "realiste", "liquidation", "recu_associes"),
                                    ("sortie", "optimiste", "revente", "is_avec_cession"),
                                    ("bien", "sortie", "horizon_ans")], ids=".".join)
def test_section_sortie_cle_absente_rc2(sortie_cli_avec_sortie, tmp_path, capsys, chemin):
    donnees = json.loads(sortie_cli_avec_sortie.read_text(encoding="utf-8"))
    noeud = donnees
    for cle in chemin[:-1]:
        noeud = noeud[cle]
    del noeud[chemin[-1]]
    rc, out, err = _lancer(capsys, "--sortie", str(_ecrire(tmp_path, donnees)))
    assert rc == 2 and ".".join(chemin) in err and out == ""
