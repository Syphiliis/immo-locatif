"""Shortlist dérivée des études /immo.

`scripts/immo_shortlist.py` régénère `shortlist.md` §1 et §1 bis depuis le bloc `<!-- immo:ligne {...} -->` de chaque
étude et contrôle la cohérence bloc / étude. Les études de la fixture portent déjà leur bloc.

Données FICTIVES uniquement (`tests/fixtures/immo_shortlist/dossier/`) : communes et identifiants inventés, aucun nom de
personne. Les dossiers de travail sont des copies jetables sous `tmp_path` : aucun test n'écrit dans `immo-data/`.
"""
from __future__ import annotations

import shutil
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import immo_shortlist as sl  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "immo_shortlist"
ETUDES = {  # slug -> (section, verdict)
    "orme-180k-2026-09-01": ("complet", "🟨"),
    "orme-90k-2026-09-02": ("complet", "🟥"),
    "moulin-104k-2026-09-03": ("complet", "🟥"),
    "verger-97k-2026-09-04": ("complet", "🟨"),
    "tilleul-143k-2026-09-11": ("rapide", "⬛"),
    "quai-268k-2026-09-12": ("rapide", "🟥"),
    "ormes-140k-2026-09-13": ("rapide", "🟩"),
    "plaine-200k-2026-09-14": ("rapide", "⬜"),
}
ENTETE_13 = ("| # | Quartier | Type | Surface | Prix FAI | €/m² FAI | DPE | Rdt brut réal. | CF réal. (montage) | Verdict "
             "| Prix cible | ID LBC | Analyse |")
LIGNE_VERGER = (
    "| - | Chemin du Verger (5, adresse probable), Le Verger | Maison de bourg R+1 : atelier d'artisan + "
    "logement à rafraîchir | 118,6 m² (84 habitables + 34,6) | 97 000 € | 818 (118,6 m²) | E, GES D (02/06/2023) | 8,40 % deux "
    "baux ; 9,95 % un bail | **-94 €/mois** (deux baux ; un seul bail -215) | 🟨 **À creuser**, deux baux seulement ; "
    "un seul bail 🟥 | cible 88 120 € / 61 340 € ; plafond 96 500 / 74 980 € | "
    "[9000000004](https://www.leboncoin.fr/ad/ventes_immobilieres/9000000004) | "
    "[verger-97k](analyses/verger-97k-2026-09-04.md) · pas de tableur |")


# --------------------------------------------------------------------------------------------
# Aides
# --------------------------------------------------------------------------------------------

@pytest.fixture
def dossier(tmp_path) -> Path:
    """Copie jetable du dossier fictif : `analyses/` (8 études et 4 fichiers liés) et `shortlist.md`."""
    cible = tmp_path / "immo-data"
    shutil.copytree(FIXTURES / "dossier", cible)
    return cible


def poser_marqueurs(texte: str) -> str:
    """Ce que fera la relecture : DEBUT après le titre de §1, FIN après le dernier tableau de §1 bis."""
    lignes = texte.split("\n")
    i = next(k for k, ligne in enumerate(lignes) if ligne.startswith("## 1."))
    lignes.insert(i + 2, sl.DEBUT)
    bis = next(k for k, ligne in enumerate(lignes) if ligne.startswith("### 1 bis"))
    sep = next(k for k in range(bis, len(lignes)) if lignes[k] == "---")
    k = sep - 1
    while not lignes[k].startswith("|"):
        k -= 1
    lignes.insert(k + 1, sl.FIN)
    return "\n".join(lignes)


@pytest.fixture
def pret(dossier, capsys) -> Path:
    """Dossier dont les 8 études portent leur bloc (posé dans la fixture) et dont `shortlist.md` porte les marqueurs."""
    p = dossier / "shortlist.md"
    p.write_text(poser_marqueurs(p.read_text(encoding="utf-8")), encoding="utf-8")
    return dossier


def lancer(capsys, module, *args) -> tuple[int, str, str]:
    rc = module.main([str(a) for a in args])
    out, err = capsys.readouterr()
    return rc, out, err


def lire(chemin: Path) -> str:
    return chemin.read_bytes().decode("utf-8")


def lignes_du_tableau(texte: str, depuis: str) -> list[str]:
    """Lignes de données du tableau qui suit la première ligne commençant par `depuis`."""
    lignes = texte.split("\n")
    i = next(k for k, ligne in enumerate(lignes) if ligne.startswith(depuis))
    j = next(k for k in range(i, len(lignes)) if lignes[k].startswith("| # |"))
    out = []
    for ligne in lignes[j + 2:]:
        if not ligne.startswith("|"):
            break
        out.append(ligne)
    return out


def sans_score(ligne: str) -> str:
    """Attendu de l'aller-retour, écrit indépendamment du code : les 14 cellules d'origine moins Score ; `#` reste tel quel."""
    cellules = ligne.strip()[2:-2].split(" | ")
    assert len(cellules) == 14, ligne
    return "| " + " | ".join(cellules[:9] + cellules[10:]) + " |"


def bloc_type(slug: str = "demo-100k-2026-09-20", **sur) -> dict:
    ligne = {"quartier": "Centre", "type": "Maison de ville", "surface": "80 m²", "prix": "100 000 €", "eur_m2": "1 250",
             "dpe": "D", "rendement": "6,0 %", "cf": "**-50 €/mois** (SCI à l'IS)", "verdict": "🟨 **À creuser**",
             "prix_cible": "cible 90 000 €",
             "annonces": "[9000000099](https://www.leboncoin.fr/ad/ventes_immobilieres/9000000099)",
             "liens": f"[demo](analyses/{slug}.md)"}
    bloc = {"slug": slug, "date": slug[-10:], "mode": "complet", "verdict": "🟨", "quartier": "Centre",
            "type": "Maison de ville", "surface_m2": 80, "prix_fai": 100000, "prix_net_vendeur": 100000,
            "eur_m2_fai": 1250, "dpe": "D", "rendement_brut_realiste": 0.06, "cf_realiste_mensuel": -50,
            "montage": "sci_is", "plafond": 95000, "cible": 90000, "ancrage": 85000, "ids_annonces": ["9000000099"],
            "etapes_faites": ["1", "2"], "ligne_shortlist": ligne}
    bloc.update(sur)
    return bloc


STEM = "demo-100k-2026-09-20"


def retirer_le_bloc(chemin: Path) -> None:
    lignes = lire(chemin).rstrip("\n").split("\n")
    assert lignes[-1].startswith(sl.PREFIXE_BLOC)
    chemin.write_text("\n".join(lignes[:-1]).rstrip("\n") + "\n", encoding="utf-8")


def modifier_le_corps(chemin: Path, modif) -> None:
    """Applique `modif(texte)` au texte de l'étude, sans sa dernière ligne (le bloc, qui garde ses cellules)."""
    lignes = lire(chemin).rstrip("\n").split("\n")
    assert lignes[-1].startswith(sl.PREFIXE_BLOC)
    chemin.write_text(modif("\n".join(lignes[:-1])).rstrip("\n") + "\n" + lignes[-1] + "\n", encoding="utf-8")


def reecrire_le_bloc(chemin: Path, modif) -> None:
    """Relit le bloc de la dernière ligne, le modifie par `modif(bloc)`, le réécrit (sans le valider)."""
    lignes = lire(chemin).rstrip("\n").split("\n")
    bloc, erreurs = sl.extraire_bloc("\n".join(lignes))
    assert erreurs == []
    modif(bloc)
    chemin.write_text("\n".join(lignes[:-1]) + "\n" + sl.serialiser_bloc(bloc) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------
# 1. Le bloc : lecture, validation, sérialisation
# --------------------------------------------------------------------------------------------

def test_bloc_complet_valide():
    assert sl.valider_bloc(bloc_type(), STEM) == []
    assert tuple(bloc_type()) == sl.CLES_BLOC  # l'ordre canonique est celui du contrat


def test_bloc_cle_inconnue_refusee():
    b = bloc_type()
    b["score"] = 70
    erreurs = sl.valider_bloc(b, STEM)
    assert any("clé inconnue" in e and "score" in e for e in erreurs), erreurs
    b = bloc_type()
    b["ligne_shortlist"]["score"] = "70/100"  # la colonne Score est retirée : pas de cellule non plus
    erreurs = sl.valider_bloc(b, STEM)
    assert any("clé inconnue" in e and "score" in e for e in erreurs), erreurs


def test_bloc_cle_manquante_refusee():
    b = bloc_type()
    del b["ancrage"]
    assert any("clé manquante" in e and "ancrage" in e for e in sl.valider_bloc(b, STEM))
    b = bloc_type()
    del b["ligne_shortlist"]["liens"]
    assert any("clé manquante" in e and "liens" in e for e in sl.valider_bloc(b, STEM))


@pytest.mark.parametrize("champ,valeur", [
    ("mode", "partiel"), ("verdict", "🔥"), ("montage", "nom_propre"), ("date", "2026-13-40"), ("date", "08/10/2026"),
    ("prix_fai", "100000"), ("prix_fai", True), ("cf_realiste_mensuel", float("nan")), ("dpe", "H"),
    ("ids_annonces", "9000000099"), ("etapes_faites", [1, 2]), ("quartier", 12), ("slug", "autre-100k-2026-09-20"),
])
def test_bloc_valeur_hors_contrat_refusee(champ, valeur):
    erreurs = sl.valider_bloc(bloc_type(**{champ: valeur}), STEM)
    assert erreurs and any(champ in e for e in erreurs), erreurs


def test_bloc_valeurs_absentes_admises():
    """`null` pour une valeur absente, sur toute clé sauf slug, date, mode, verdict, ligne_shortlist."""
    b = bloc_type(**{c: None for c in sl.CLES_BLOC if c not in ("slug", "date", "mode", "verdict", "ligne_shortlist")})
    assert sl.valider_bloc(b, STEM) == []
    for obligatoire in ("slug", "date", "mode", "verdict"):
        b = bloc_type()
        b[obligatoire] = None
        assert sl.valider_bloc(b, STEM), obligatoire


@pytest.mark.parametrize("cellule,valeur,morceau", [
    ("prix", "100 000 € | 90 000 €", "pipe"),
    ("cf", "première ligne\nsuivante", "ligne"),
    ("cf", "première ligne\rsuivante", "ligne"),
    ("cf", "séparateur\u2028Unicode", "ligne"),  # `str.splitlines()`, y coupe la ligne
    ("liens", "[autre](analyses/autre-100k-2026-09-20.md)", f"analyses/{STEM}.md"),
    ("liens", f"[tableur](analyses/{STEM}.xlsx)", f"analyses/{STEM}.md"),
    ("verdict", "🟥 **À écarter**", "verdict"),
    ("quartier", 12, "texte"),
    ("rang", 7, "texte"),                 # le rang est une cellule comme les autres : texte, une ligne, pas de barre nue
    ("rang", "T1 | T2", "pipe"),
    ("rang", "T1\nT2", "ligne"),
])
def test_cellule_hors_contrat_refusee(cellule, valeur, morceau):
    b = bloc_type()
    b["ligne_shortlist"][cellule] = valeur
    erreurs = sl.valider_bloc(b, STEM)
    assert any(morceau in e for e in erreurs), erreurs


def test_cellule_avec_pipe_echappe_admise():
    b = bloc_type()
    b["ligne_shortlist"]["prix"] = r"100 000 € \| FAI"
    assert sl.valider_bloc(b, STEM) == []


def test_bloc_json_invalide_et_cle_en_double():
    bloc, erreurs = sl.extraire_bloc('# t\n\n<!-- immo:ligne {"slug": "a", } -->\n')
    assert bloc is None and "JSON invalide" in erreurs[0]
    bloc, erreurs = sl.extraire_bloc('# t\n\n<!-- immo:ligne {"slug": "a", "slug": "b"} -->\n')
    assert bloc is None and "en double" in erreurs[0]
    bloc, erreurs = sl.extraire_bloc("# t\n\n<!-- immo:ligne [1, 2] -->\n")
    assert bloc is None and "objet" in erreurs[0]


def test_bloc_lu_en_derniere_ligne_non_vide_seulement():
    ligne = sl.serialiser_bloc(bloc_type())
    bloc, erreurs = sl.extraire_bloc("# t\n\ncorps\n\n" + ligne + "\n\n  \n")  # lignes vides après : admises
    assert erreurs == [] and bloc["slug"] == STEM
    bloc, erreurs = sl.extraire_bloc("# t\n" + ligne + "\nfin de l'étude\n")
    assert bloc is None and "pas en dernière ligne" in erreurs[0]
    assert sl.extraire_bloc("# t\ncorps\n") == (None, ["bloc absent"])
    assert sl.extraire_bloc("") == (None, ["bloc absent"])


def test_deux_blocs_refuses_et_prose_qui_cite_le_nom_du_bloc_sans_gene():
    """Un ancien bloc resté dans le texte compterait comme texte de l'étude : il est refusé."""
    ligne = sl.serialiser_bloc(bloc_type())
    bloc, erreurs = sl.extraire_bloc("# t\n" + ligne + "\ncorps\n" + ligne + "\n")
    assert bloc is None and "plusieurs blocs" in erreurs[0]
    # une phrase qui parle du bloc n'est pas un bloc
    assert sl.extraire_bloc("# t\nclose par le bloc `<!-- immo:ligne … -->` de fin\n") == (None, ["bloc absent"])
    bloc, erreurs = sl.extraire_bloc("# t\nclose par le bloc `<!-- immo:ligne … -->` de fin\n" + ligne + "\n")
    assert erreurs == [] and bloc["slug"] == STEM


def test_serialisation_une_ligne_et_aller_retour_meme_avec_une_fermeture_de_commentaire():
    b = bloc_type()
    b["ligne_shortlist"]["cf"] = "**-50 €/mois** --> piège \"entre guillemets\", émoji 🟨 et accents é à ç"
    ligne = sl.serialiser_bloc(b)
    assert "\n" not in ligne and ligne.startswith("<!-- immo:ligne {") and ligne.endswith("} -->")
    assert ligne.count("-->") == 1, "un `-->` dans une cellule fermerait le commentaire HTML"
    bloc, erreurs = sl.extraire_bloc("# t\n\n" + ligne + "\n")
    assert erreurs == [] and bloc == b
    assert list(bloc) == list(sl.CLES_BLOC)


# --------------------------------------------------------------------------------------------
# 2. Les études lues
# --------------------------------------------------------------------------------------------

def test_etudes_sans_annexes_visite_projet_ni_one_pager(dossier):
    noms = [p.name for p in sl.lister_etudes(dossier / "analyses")]
    assert noms == sorted(f"{s}.md" for s in ETUDES)
    assert len(list((dossier / "analyses").glob("*.md"))) == len(ETUDES) + 4  # les 4 fichiers liés sont bien présents


# --------------------------------------------------------------------------------------------
# 3. Génération : tableaux, classement, marqueurs
# --------------------------------------------------------------------------------------------

def test_classement_verdict_puis_cash_flow_decroissant_puis_slug():
    def mini(slug, verdict, cf):
        return {"slug": slug, "verdict": verdict, "cf_realiste_mensuel": cf}

    blocs = [mini("e-2026-09-05", "⬛", 500), mini("a-2026-09-01", "🟥", -10), mini("b-2026-09-02", "🟥", None),
             mini("c-2026-09-03", "🟥", 20), mini("d-2026-09-04", "🟥", 20), mini("f-2026-09-06", "⬜", None),
             mini("g-2026-09-07", "🟨", -300), mini("h-2026-09-08", "🟩", -900), mini("i-2026-09-09", "🟨", 0)]
    ordre = [b["slug"][0] for b in sl.trier(blocs)]
    # 🟩 ; 🟨 par cash-flow décroissant (0 avant -300) ; ⬜ ; 🟥 (20 et 20 par slug, puis -10, puis null en dernier) ; ⬛
    assert ordre == ["h", "i", "g", "f", "c", "d", "a", "b", "e"]


def test_tableau_a_treize_colonnes_sans_score():
    assert sl.COLONNES == ("#", "Quartier", "Type", "Surface", "Prix FAI", "€/m² FAI", "DPE", "Rdt brut réal.",
                           "CF réal. (montage)", "Verdict", "Prix cible", "ID LBC", "Analyse")
    tableau = sl.tableau([bloc_type()])
    assert tableau[0] == ENTETE_13
    assert tableau[1] == "|" + "---|" * 13
    ligne = tableau[2]
    assert ligne.startswith("| - | Centre | Maison de ville | 80 m² | 100 000 € |")
    assert ligne.endswith(f"| [demo](analyses/{STEM}.md) |")
    assert len(ligne.strip()[2:-2].split(" | ")) == 13
    assert "Score" not in "".join(tableau)


def test_generation_ecrit_le_rang_dans_la_colonne_diese_et_tiret_si_absent():
    b = bloc_type()
    assert "rang" not in b["ligne_shortlist"] and sl.ligne_tableau(b).startswith("| - | Centre | ")
    for rang in ("T7", "**1**", "12"):
        b["ligne_shortlist"] = {"rang": rang, **{k: v for k, v in b["ligne_shortlist"].items() if k != "rang"}}
        assert sl.valider_bloc(b, STEM) == []
        ligne = sl.ligne_tableau(b)
        assert ligne.startswith(f"| {rang} | Centre | ") and len(ligne.strip()[2:-2].split(" | ")) == 13
    # le rang n'entre dans aucun classement : T7 ou « - », le verdict et le cash-flow décident
    avec, sans = bloc_type("a-100k-2026-09-20"), bloc_type("b-100k-2026-09-20")
    avec["ligne_shortlist"]["rang"] = "T9"
    assert [x["slug"] for x in sl.trier([sans, avec])] == ["a-100k-2026-09-20", "b-100k-2026-09-20"]


def test_marqueurs_absents_ou_mal_poses_code_2_et_rien_d_ecrit(pret, capsys):
    p = pret / "shortlist.md"
    sain = lire(p)
    cas = {
        "aucun": sain.replace(sl.DEBUT + "\n", "").replace(sl.FIN + "\n", ""),
        "sans fin": sain.replace(sl.FIN + "\n", ""),
        "sans debut": sain.replace(sl.DEBUT + "\n", ""),
        "dans le désordre": sain.replace(sl.DEBUT, "@@").replace(sl.FIN, sl.DEBUT).replace("@@", sl.FIN),
        "en double": sain.replace(sl.DEBUT, sl.DEBUT + "\n" + sl.DEBUT),
    }
    for nom, texte in cas.items():
        p.write_text(texte, encoding="utf-8")
        avant = p.read_bytes()
        rc, _, err = lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")
        assert rc == 2 and "marqueurs" in err, nom
        assert p.read_bytes() == avant, f"{nom} : le fichier a été modifié"
        rc, _, err = lancer(capsys, sl, "--check", "--dossier", pret)
        assert rc == 2, nom
        assert p.read_bytes() == avant


def test_zone_qui_ne_contient_pas_deux_tableaux_code_2(pret, capsys):
    p = pret / "shortlist.md"
    # FIN juste après le dernier tableau de §1 : la zone n'en contient qu'un
    lignes = lire(p).split("\n")
    lignes.remove(sl.FIN)
    i = next(k for k, ligne in enumerate(lignes) if ligne.startswith("| - | Chemin du Verger"))
    lignes.insert(i + 1, sl.FIN)
    p.write_text("\n".join(lignes), encoding="utf-8")
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 2 and "tableaux" in err
    assert p.read_bytes() == avant


def test_ligne_de_derniere_mise_a_jour_absente_code_2(pret, capsys):
    p = pret / "shortlist.md"
    p.write_text(lire(p).replace("Dernière mise à jour : **2026-09-30**.", "Mise à jour le 30 septembre."), encoding="utf-8")
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 2 and "Dernière mise à jour" in err and p.read_bytes() == avant


def test_le_reste_du_fichier_est_recopie_octet_pour_octet(pret, capsys):
    p = pret / "shortlist.md"
    avant = lire(p)
    rc, _, _ = lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")
    assert rc == 0
    apres = lire(p)
    a, b = avant.split("\n"), apres.split("\n")
    debut_a, fin_a = a.index(sl.DEBUT), a.index(sl.FIN)
    debut_b, fin_b = b.index(sl.DEBUT), b.index(sl.FIN)
    assert a[:debut_a + 1] != b[:debut_b + 1]  # seule la date change avant la zone...
    assert [x for x in a[:debut_a + 1] if "Dernière mise à jour" not in x] == \
           [x for x in b[:debut_b + 1] if "Dernière mise à jour" not in x]
    assert [x for x in b if "Dernière mise à jour" in x] == ["Dernière mise à jour : **2026-10-08**."]
    assert a[fin_a:] == b[fin_b:]  # ...et rien après
    # dans la zone : titres, paragraphes et lignes vides sont conservés, dans l'ordre ; seuls les tableaux sont réécrits
    assert [x for x in a[debut_a:fin_a] if not x.startswith("|")] == [x for x in b[debut_b:fin_b] if not x.startswith("|")]
    # les tableaux de la section 2 (hors zone) gardent leur colonne Score
    assert "| X1 | Nulle-part-sur-Marne | 100 m² | 100 000 € | ~60 |" in apres
    assert "Score" in "\n".join(b[fin_b:])


def test_option_date_et_idempotence(pret, capsys):
    p = pret / "shortlist.md"
    assert lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")[0] == 0
    premiere = p.read_bytes()
    assert lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")[0] == 0
    assert p.read_bytes() == premiere, "deux générations le même jour doivent être identiques"
    assert lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-09")[0] == 0
    diff = [(x, y) for x, y in zip(premiere.decode().split("\n"), p.read_bytes().decode().split("\n")) if x != y]
    assert diff == [("Dernière mise à jour : **2026-10-08**.", "Dernière mise à jour : **2026-10-09**.")]
    # sans --date : la date du jour
    from datetime import date
    assert lancer(capsys, sl, "--dossier", pret)[0] == 0
    assert f"Dernière mise à jour : **{date.today().isoformat()}**." in lire(p)
    # une date mal formée est refusée par l'analyse des arguments
    with pytest.raises(SystemExit):
        sl.main(["--dossier", str(pret), "--date", "08/10/2026"])


def test_generation_refuse_d_ecrire_si_une_etude_n_a_pas_de_bloc(pret, capsys):
    retirer_le_bloc(pret / "analyses" / "quai-268k-2026-09-12.md")
    reecrire_le_bloc(pret / "analyses" / "ormes-140k-2026-09-13.md", lambda b: b.update(score=70))
    avant = (pret / "shortlist.md").read_bytes()
    rc, out, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 1 and (pret / "shortlist.md").read_bytes() == avant, "une ligne ne doit jamais disparaître en silence"
    assert "quai-268k-2026-09-12" in err and "bloc absent" in err
    assert "ormes-140k-2026-09-13" in err and "clé inconnue" in err


# --------------------------------------------------------------------------------------------
# 4. --check : un cas qui passe et un cas qui refuse, pour chaque contrôle
# --------------------------------------------------------------------------------------------

@pytest.fixture
def genere(pret, capsys) -> Path:
    assert lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")[0] == 0
    return pret


def test_check_conforme_code_0_et_n_ecrit_rien(genere, capsys):
    avant = {p: p.read_bytes() for p in genere.rglob("*") if p.is_file()}
    rc, out, err = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 0, out + err
    assert sum(ligne.startswith("OK ") for ligne in out.split("\n")) == len(ETUDES)
    assert "ÉCHEC" not in out and "0 en échec" in out and "conforme" in out
    assert {p: p.read_bytes() for p in genere.rglob("*") if p.is_file()} == avant


def test_check_bloc_absent_refuse(genere, capsys):
    retirer_le_bloc(genere / "analyses" / "moulin-104k-2026-09-03.md")
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1
    assert "ÉCHEC moulin-104k-2026-09-03 : bloc absent" in out
    # les autres études, dotées d'un bloc, ne sont pas mises en cause
    assert "ÉCHEC orme-90k-2026-09-02" not in out


def test_check_verdict_contradictoire_refuse(genere, capsys):
    """Le bloc dit 🟥, l'en-tête de l'étude dit maintenant 🟩 : le contrôle doit le refuser."""
    etude = genere / "analyses" / "moulin-104k-2026-09-03.md"
    modifier_le_corps(etude, lambda corps: corps.replace("🟥 **À écarter**", "🟩 **Go**"))
    ligne = next(n for n, texte in enumerate(lire(etude).split("\n"), 1) if "🟩" in texte)
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1, out
    assert f"ÉCHEC moulin-104k-2026-09-03 : verdict du bloc 🟥 ≠ verdict de l'en-tête 🟩 (ligne {ligne})" in out
    assert "OK moulin-104k-2026-09-03" not in out


def test_check_verdict_concordant_passe(genere, capsys):
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 0 and "verdict du bloc" not in out
    # le premier émoji de verdict fait foi, pas ceux qui suivent (verger : 🟨 puis 🟥 dans la même ligne)
    assert "OK verger-97k-2026-09-04" in out


def test_check_verdict_non_lisible_dans_l_entete_est_une_note_sans_echec(genere, capsys):
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 0
    assert "NOTE orme-180k-2026-09-01 : verdict non lisible dans l'en-tête" in out  # étude d'un format ancien
    # l'émoji repoussé après la ligne 20 n'est plus dans l'en-tête
    etude = genere / "analyses" / "ormes-140k-2026-09-13.md"
    modifier_le_corps(etude, lambda corps: corps.replace("## Verdict\n\n🟩 **Go**", "## Verdict\n\n" + "\n" * 20 + "🟩 **Go**"))
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 0 and "NOTE ormes-140k-2026-09-13 : verdict non lisible dans l'en-tête" in out


def test_le_bloc_lui_meme_n_est_pas_lu_comme_l_entete(genere, capsys):
    """Une étude de moins de 20 lignes : la dernière ligne (le bloc, qui porte son verdict) ne doit pas servir d'en-tête."""
    etude = genere / "analyses" / "orme-180k-2026-09-01.md"
    assert len(lire(etude).split("\n")) < 20 and "🟨" in lire(etude).split("\n")[-2]
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert "NOTE orme-180k-2026-09-01 : verdict non lisible" in out


def test_check_valeur_absente_du_texte_refusee(genere, capsys):
    etude = genere / "analyses" / "orme-180k-2026-09-01.md"
    # le titre dit aussi « 180 k€ » (exact, donc valable) : les deux écritures du prix disparaissent
    modifier_le_corps(etude, lambda corps: corps.replace("180 000 €", "cent quatre-vingt mille euros")
                      .replace("180 k€", "cent quatre-vingts mille"))
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1
    assert "ÉCHEC orme-180k-2026-09-01 : prix_fai 180000 absent du texte de l'étude" in out
    assert out.count("ÉCHEC orme-180k-2026-09-01") == 1, "seule la valeur absente est signalée"


def test_check_valeur_du_bloc_pas_cherchee_dans_le_bloc_lui_meme(genere, capsys):
    """Le bloc contient toutes ses valeurs : si l'on cherchait dedans, rien ne manquerait jamais."""
    etude = genere / "analyses" / "quai-268k-2026-09-12.md"
    texte = lire(etude)
    corps, bloc = texte.rstrip("\n").rsplit("\n", 1)
    assert bloc.startswith(sl.PREFIXE_BLOC) and "171250" in bloc
    etude.write_text(corps.replace("171 250 €", "près de deux cent mille euros") + "\n" + bloc + "\n", encoding="utf-8")
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "plafond 171250 absent du texte de l'étude" in out


@pytest.mark.parametrize("valeur,texte", [
    (87436, "plafond 87 436 € net vendeur"),
    (87436, "plafond 87436 euros"),
    (87436, "plafond 87,4 k€"),
    (87436, "plafond 87,44 k€"),
    (87436, "plafond 87\u202f436 €"),
    (87436, "plafond 87\u00a0436 €"),
    (87436, "plafond 87 436,00 €"),
    (145424.28, "plafond 145 424 €"),
    (-871, "cash-flow de −871 €/mois"),
    (-870.8, "cash-flow de -871 €/mois"),
    (95, "+95 €/mois"),
    (0.0567, "rendement brut 5,67 %"),
    (0.0567, "rendement brut 5,7 %"),
    (0.046, "rendement brut de 4,64 %"),   # la cellule d'une shortlist arrondit à une décimale : 4,6 % pour 4,64 %
    (84.5, "surface de 84,53 m²"),
    (0.05, "rendement brut 5 %"),      # sans décimale, valable pour un nombre exact seulement
    (87000, "plafond 87 k€"),
    (84.5, "84,5 m²"),
    (1842, "1 842 €/m²"),
])
def test_valeur_retrouvee_quel_que_soit_le_format(valeur, texte):
    assert sl.valeur_dans_texte(valeur, texte)


@pytest.mark.parametrize("valeur,texte", [
    (87436, "plafond 87 k€"),          # trop grossier : 87 k€ n'est pas 87 436
    (87436, "plafond 87,5 k€"),
    (87436, "plafond 87 437 €"),
    (87436, "plafond 874 36"),
    (87436, "plafond 187 436 €"),
    (-871, "perte de 871 €/mois"),     # le signe compte
    (871, "cash-flow de -871 €/mois"),
    (0.0567, "rendement brut 6 %"),    # trop grossier
    (0.046, "rendement brut de 4,66 %"),   # 4,66 s'arrondit en 4,7, pas en 4,6
    (0.046, "rendement brut de 4,5 %"),
    (85000, "prix de 85 312 €"),           # une valeur sans décimale ne valide pas un nombre plus précis qu'elle
    (85000, "prix de 85 000,4 €"),
    (0.05, "rendement de 4,64 %"),
    (0.0567, "rendement brut 5,67"),   # sans « % » : ce n'est pas la fraction 0,0567
    (5.67, "rendement brut 5,67 %"),   # un pourcentage dans le bloc n'est pas la fraction du contrat
    (1250, "le 12 50 mars"),
])
def test_valeur_absente_ou_trop_grossiere_refusee(valeur, texte):
    assert not sl.valeur_dans_texte(valeur, texte)


def test_check_shortlist_differente_du_genere_refusee(genere, capsys):
    p = genere / "shortlist.md"
    sain = lire(p)
    # une ligne éditée à la main dans la zone dérivée
    p.write_text(sain.replace("| 97 000 € |", "| 98 000 € |", 1), encoding="utf-8")
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "diffère de ce qui serait généré" in out
    assert "98 000" in out, "le rapport montre la ligne en cause"
    assert "0 en échec" in out, "les études sont conformes : seul le fichier diffère"
    # regénérée : conforme à nouveau
    assert lancer(capsys, sl, "--dossier", genere, "--date", "2026-10-08")[0] == 0
    assert lancer(capsys, sl, "--check", "--dossier", genere)[0] == 0
    # un bloc modifié sans régénérer la shortlist : le fichier est périmé
    reecrire_le_bloc(genere / "analyses" / "plaine-200k-2026-09-14.md",
                     lambda b: b.update(verdict="🟥", ligne_shortlist={**b["ligne_shortlist"], "verdict": "🟥 **À écarter**"}))
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "diffère de ce qui serait généré" in out


def test_check_ignore_la_date_de_derniere_mise_a_jour(genere, capsys):
    p = genere / "shortlist.md"
    p.write_text(lire(p).replace("**2026-10-08**", "**2025-01-01**"), encoding="utf-8")
    assert lancer(capsys, sl, "--check", "--dossier", genere)[0] == 0


# --------------------------------------------------------------------------------------------
# 7. Cas limites de la lecture et de l'entrée en ligne de commande
# --------------------------------------------------------------------------------------------

def test_dossier_introuvable_code_2_et_dossier_sans_etude_code_1(tmp_path, capsys):
    rc, _, err = lancer(capsys, sl, "--dossier", tmp_path / "absent")
    assert rc == 2 and "introuvable" in err
    vide = tmp_path / "vide"
    (vide / "analyses").mkdir(parents=True)
    (vide / "shortlist.md").write_text(poser_marqueurs(lire(FIXTURES / "dossier" / "shortlist.md")), encoding="utf-8")
    avant = (vide / "shortlist.md").read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", vide)
    assert rc == 1 and "aucune étude" in err
    assert (vide / "shortlist.md").read_bytes() == avant, "sans étude, les tableaux ne sont pas vidés"


def test_lancement_en_script(pret):
    """`python scripts/<nom>.py` : l'import voisin et le point d'entrée fonctionnent hors pytest."""
    import subprocess

    def lancer_script(nom, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / nom), *args, "--dossier", str(pret)],
                              capture_output=True, text=True, cwd=pret)

    res = lancer_script("immo_shortlist.py", "--date", "2026-10-08")
    assert res.returncode == 0, res.stderr
    assert "shortlist.md régénérée : §1 4 ligne(s) (complet), §1 bis 4 ligne(s) (rapide)" in res.stdout
    res = lancer_script("immo_shortlist.py", "--check")
    assert res.returncode == 0 and "conforme à ce qui serait généré" in res.stdout


# --------------------------------------------------------------------------------------------
# 8. Bornes : cas limites ajoutés après des tests par mutation
# --------------------------------------------------------------------------------------------

def test_zone_a_trois_tableaux_code_2(pret, capsys):
    p = pret / "shortlist.md"
    lignes = lire(p).split("\n")
    lignes.remove(sl.FIN)
    i = next(k for k, ligne in enumerate(lignes) if ligne.startswith("| X1 |"))
    lignes.insert(i + 1, sl.FIN)  # la zone embarque le tableau de la section 2 : trois tableaux
    p.write_text("\n".join(lignes), encoding="utf-8")
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 2 and "3 trouvé" in err and p.read_bytes() == avant


def test_ligne_de_derniere_mise_a_jour_en_double_code_2(pret, capsys):
    p = pret / "shortlist.md"
    p.write_text(lire(p).replace("## Légende", "Dernière mise à jour : **2026-01-01**.\n\n## Légende", 1), encoding="utf-8")
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 2 and "Dernière mise à jour" in err and p.read_bytes() == avant


def test_l_entete_est_lu_sur_vingt_lignes_exactement():
    assert sl.verdict_entete("\n" * 18 + "🟩 Go") == ("🟩", 19)
    assert sl.verdict_entete("\n" * 19 + "🟩 Go") == ("🟩", 20)
    assert sl.verdict_entete("\n" * 20 + "🟩 Go") is None


def test_generation_refuse_meme_pour_une_seule_etude_invalide(pret, capsys):
    retirer_le_bloc(pret / "analyses" / "plaine-200k-2026-09-14.md")
    avant = (pret / "shortlist.md").read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 1 and "1 étude(s) sans bloc valide" in err
    assert (pret / "shortlist.md").read_bytes() == avant


def test_check_rendement_absent_du_texte_refuse(genere, capsys):
    modifier_le_corps(genere / "analyses" / "orme-180k-2026-09-01.md", lambda corps: corps.replace("9,2 %", "neuf pour cent"))
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "ÉCHEC orme-180k-2026-09-01 : rendement_brut_realiste 0.092 absent du texte de l'étude" in out


def test_jetons_k_majuscule_identifiants_et_dates_collees_a_un_tiret():
    assert [(j.valeur, j.unite) for j in sl.jetons("plafond 87,4 K€ ; 2 760 €/mois")] == [(Decimal("87.4"), "k€"),
                                                                                       (Decimal("2760"), "€/mois")]
    # un nombre collé à un tiret est un identifiant, une date ou un intervalle : pas un jeton
    assert [j.valeur for j in sl.jetons("étude exemple-64k-03 du 2025-03-14, lots 2-4")] == [Decimal("2025"), Decimal("2")]
    assert sl.valeur_dans_texte(87436, "plafond 87,4 K€")


def test_un_rendement_ne_se_retrouve_que_dans_un_pourcentage(genere, capsys):
    """0,0567 s'arrondit à 0 : sans cette garde, tout « 0 € » du texte validerait n'importe quel rendement."""
    pourcent = sl.UNITES_ADMISES["rendement_brut_realiste"]
    assert not sl.valeur_dans_texte(0.0567, "IS 0 € la première année", pourcent)
    assert not sl.valeur_dans_texte(0.0567, "reste 0", pourcent)
    assert sl.valeur_dans_texte(0.0567, "brut 5,67 %", pourcent)
    assert sl.valeur_dans_texte(0.05, "brut 5 %", pourcent)
    # dans --check : le rendement de orme-180k n'est plus écrit en %, mais le texte dit « 0 € » ailleurs
    modifier_le_corps(genere / "analyses" / "orme-180k-2026-09-01.md",
                      lambda corps: corps.replace("9,2 %", "neuf pour cent") + "\n- Impôt de la première année : 0 €.")
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "rendement_brut_realiste 0.092 absent du texte de l'étude" in out


def test_arrondi_demi_superieur():
    assert sl.valeur_dans_texte(2.5, "au moins 3")
    assert sl.valeur_dans_texte(-2.5, "perte de -3")
    assert sl.valeur_dans_texte(1250.5, "soit 1 251 €")
    assert not sl.valeur_dans_texte(2.5, "au moins 2")


@pytest.mark.parametrize("cle,valeur,texte,attendu", [
    ("surface_m2", 39, "39 m²", True),
    ("surface_m2", 39, "39 m2", True),           # « m2 » ASCII : sans unité reconnue, admis
    ("surface_m2", 39, "39 €/m²", False),
    ("surface_m2", 39, "39 %", False),
    ("prix_fai", 1044, "1 044 €", True),
    ("prix_fai", 1044, "1 044", True),
    ("prix_fai", 1044, "1 044 €/m²", False),     # un prix au m² ne valide pas un prix
    ("plafond", 1044, "loyer de 1 044 €/mois", False),
    ("cible", 87436, "87,4 k€", True),
    ("eur_m2_fai", 1842, "1 842 €/m²", True),
    ("eur_m2_fai", 1842, "1 842 m²", False),
    ("cf_realiste_mensuel", 7, "+7 €/mois", True),
    ("cf_realiste_mensuel", 7, "7 %", False),
    ("cf_realiste_mensuel", -871, "perte de −871 € par mois", True),
    ("rendement_brut_realiste", 0.0567, "5,67 %", True),
    ("rendement_brut_realiste", 0.0567, "5,67 € par m²", False),
])
def test_une_valeur_ne_se_retrouve_que_sous_une_unite_qui_lui_convient(cle, valeur, texte, attendu):
    assert sl.valeur_dans_texte(valeur, texte, sl.UNITES_ADMISES[cle]) is attendu


def test_check_valeur_ecrite_sous_une_autre_unite_refusee(genere, capsys):
    """La surface de orme-90k (40 m²) n'est plus écrite que « 40 €/m² » : l'étude ne la porte plus."""
    modifier_le_corps(genere / "analyses" / "orme-90k-2026-09-02.md",
                      lambda corps: corps.replace("Surface 40 m²", "Surface 40 €/m²"))
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 1 and "ÉCHEC orme-90k-2026-09-02 : surface_m2 40 absent du texte de l'étude" in out


def test_tiret_demi_cadratin_colle_a_un_nombre_est_un_moins_mais_pas_un_intervalle():
    assert sl.valeur_dans_texte(-871, "perte –871 €/mois")
    assert not sl.valeur_dans_texte(871, "perte –871 €/mois")
    assert [j.valeur for j in sl.jetons("de 10–20 m²")] == [Decimal("10"), Decimal("20")]


def test_valeur_enorme_refusee_et_sans_trace():
    b = bloc_type(prix_fai=10 ** 30)
    assert any("prix_fai" in e for e in sl.valider_bloc(b, STEM))
    assert not sl.valeur_dans_texte(10 ** 30, "x 1 €")
    assert not sl.valeur_dans_texte(1e300, "x 1 €")


def test_fins_de_ligne_crlf_code_2_avec_leur_vraie_cause(pret, capsys):
    p = pret / "shortlist.md"
    p.write_bytes(lire(p).replace("\n", "\r\n").encode("utf-8"))
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 2 and "CRLF" in err and p.read_bytes() == avant


def test_generation_refuse_de_faire_disparaitre_une_ligne(pret, capsys):
    """Une étude renommée hors du motif, ou une ligne ajoutée à la main dans la zone : la génération les effacerait."""
    p = pret / "shortlist.md"
    (pret / "analyses" / "plaine-200k-2026-09-14.md").rename(pret / "analyses" / "plaine-200k-2026-09-14-v2.md")
    avant = p.read_bytes()
    rc, out, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 1 and p.read_bytes() == avant
    assert "ligne de la zone sans étude (plaine-200k-2026-09-14)" in err and "disparaître" in err
    assert "NOTE plaine-200k-2026-09-14-v2.md" in err, "le fichier ignoré est nommé"
    assert "moulin-104k-2026-09-03-annexes.md" not in err, "les fichiers liés connus ne font pas de bruit"
    # une ligne de la main, sans lien vers une étude
    (pret / "analyses" / "plaine-200k-2026-09-14-v2.md").rename(pret / "analyses" / "plaine-200k-2026-09-14.md")
    texte = lire(p)
    ligne = next(x for x in texte.split("\n") if "analyses/orme-90k-2026-09-02.md" in x)
    p.write_text(texte.replace(ligne, ligne + "\n| - | Note écrite à la main | sans lien |"), encoding="utf-8")
    avant = p.read_bytes()
    rc, _, err = lancer(capsys, sl, "--dossier", pret)
    assert rc == 1 and "(aucun lien vers une étude) : | - | Note écrite à la main" in err and p.read_bytes() == avant
    # retirée : la génération passe
    p.write_text(lire(p).replace("\n| - | Note écrite à la main | sans lien |", ""), encoding="utf-8")
    assert lancer(capsys, sl, "--dossier", pret, "--date", "2026-10-08")[0] == 0


def test_check_nomme_les_fichiers_md_inconnus_sans_echec(genere, capsys):
    (genere / "analyses" / "notes-v2.md").write_text("# brouillon\n", encoding="utf-8")
    rc, out, _ = lancer(capsys, sl, "--check", "--dossier", genere)
    assert rc == 0 and "NOTE notes-v2.md : ni une étude" in out


# --------------------------------------------------------------------------------------------
# Gabarit `templates/shortlist.md` sur un dossier de données neuf
# --------------------------------------------------------------------------------------------

GABARIT = ROOT.parent / "templates" / "shortlist.md"


def test_gabarit_sur_dossier_neuf_sans_analyses_code_0_rien_ecrit(tmp_path, capsys):
    neuf = tmp_path / "immo-data"
    neuf.mkdir()
    (neuf / "shortlist.md").write_bytes(GABARIT.read_bytes())
    for args in ((), ("--check",)):
        rc, out, err = lancer(capsys, sl, *args, "--dossier", neuf)
        assert rc == 0, err
        assert "aucune étude encore" in out
    (neuf / "analyses").mkdir()
    rc, out, _ = lancer(capsys, sl, "--dossier", neuf)
    assert rc == 0 and "aucune étude encore" in out
    assert (neuf / "shortlist.md").read_bytes() == GABARIT.read_bytes()


def test_gabarit_avec_une_etude_se_regenere_puis_se_controle(tmp_path, capsys):
    neuf = tmp_path / "immo-data"
    (neuf / "analyses").mkdir(parents=True)
    (neuf / "shortlist.md").write_bytes(GABARIT.read_bytes())
    shutil.copy(FIXTURES / "dossier" / "analyses" / "ormes-140k-2026-09-13.md", neuf / "analyses")
    rc, out, err = lancer(capsys, sl, "--date", "2026-10-08", "--dossier", neuf)
    assert rc == 0, err
    texte = lire(neuf / "shortlist.md")
    assert "Dernière mise à jour : **2026-10-08**." in texte and "analyses/ormes-140k-2026-09-13.md" in texte
    assert lancer(capsys, sl, "--check", "--dossier", neuf)[0] == 0
