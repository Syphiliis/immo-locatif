"""Crible Leboncoin de `/immo` : tri par script d'un JSON lu au navigateur.

Jeux FICTIFS (`tests/fixtures/immo_crible/`) bâtis sur la structure réelle de `searchData.ads` relevée le 07/10/2026 :
identifiants 9 000 000 xxx, communes inventées, aucun vendeur. Les annonces des cas limites sont construites en mémoire
par `_annonce`. Le gabarit `templates/profil.json` du plugin n'est lu que pour vérifier la lecture du profil (jamais
écrit). Le loyer est celui de la vraie fonction `src.immo.loyer.loyer_3r`.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import immo_crible as crible  # noqa: E402
from src.immo.loyer import loyer_3r  # noqa: E402

SCRIPT = ROOT / "scripts" / "immo_crible.py"
FIXTURES = ROOT / "tests" / "fixtures" / "immo_crible"
PAGE_1 = json.loads((FIXTURES / "demo_page_1.json").read_text(encoding="utf-8"))
PAGE_2 = json.loads((FIXTURES / "demo_page_2.json").read_text(encoding="utf-8"))
FICHE = json.loads((FIXTURES / "fiche_fictibourg.json").read_text(encoding="utf-8"))
PROFIL = json.loads((FIXTURES / "profil_fictif.json").read_text(encoding="utf-8"))
PROFIL_GABARIT = ROOT.parent / "templates" / "profil.json"
PISTES_DEFAUT = ROOT / "immo-data" / "pistes.json"        # dossier de données par défaut du lancement (cwd = ROOT)
BRUTS = ROOT / "immo-data" / "bruts"
CLES_PISTE_COMMUNES = {"id", "url", "titre", "commune", "prix", "surface", "rendement", "source", "repere_le",
                       "categorie"}


def _annonce(list_id: int, titre: str = "Maison de ville 90 m²", prix: int | None = 80000, surface: int | None = 90,
             commune: str = "Fictibourg", *, type_code: str | None = "1", source: str = "city",
             point: tuple[float, float] | None = None, attrs: dict | None = None, corps: str = "") -> dict:
    """Une annonce à la structure réelle de `searchData.ads` (projection : seuls les champs lus par le crible)."""
    lat, lng = point if point else (48.0 + (list_id % 1000) * 1e-4, 2.0 + (list_id % 1000) * 1e-4)
    attributs = [] if type_code is None else [{"key": "real_estate_type", "value": type_code}]
    if surface is not None:
        attributs.append({"key": "square", "value": str(surface)})
    attributs += [{"key": k, "value": str(v)} for k, v in (attrs or {}).items()]
    return {"list_id": list_id, "subject": titre, "body": corps, "price": [] if prix is None else [prix],
            "first_publication_date": "2026-09-01 10:00:00",
            "location": {"city": commune, "zipcode": "99001", "lat": lat, "lng": lng, "source": source,
                         "is_shape": source == "city"},
            "owner": {"type": "pro"}, "attributes": attributs}


def _cribler(pages, **kw) -> dict:
    kw.setdefault("profil", PROFIL)
    return crible.cribler(pages, **kw)


def _par_id(lignes: list[dict]) -> dict:
    return {a["id"]: a for a in lignes}


def _lancer(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def _args_demo(tmp_path: Path, *extra: str) -> list[str]:
    return ["--pages", str(FIXTURES / "demo_page_1.json"), str(FIXTURES / "demo_page_2.json"),
            "--profil", str(FIXTURES / "profil_fictif.json"), "--fiche", str(FIXTURES / "fiche_fictibourg.json"),
            "--surface-min", "25", "--date", "2026-10-07", "--source", "bruts/scan-demo.md",
            "--out", str(tmp_path / "scan.md"), "--pistes-out", str(tmp_path / "pistes.json"), *extra]


# --- comptes réconciliés ---------------------------------------------------------------------------------------

def test_une_annonce_sur_deux_pages_comptee_une_fois():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    c = res["comptes"]
    assert (c["lues"], c["uniques"], c["doublons_entre_pages"]) == (21, 19, 2)
    tout = [a["id"] for a in res["retenues"]] + [a["id"] for a in res["ecartees"]]
    assert tout.count("9000000001") == 1 and tout.count("9000000012") == 1


def test_comptes_reconcilies_uniques_egal_ecartees_plus_retenues():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    c = res["comptes"]
    assert c["lues"] == c["uniques"] + c["doublons_entre_pages"]
    assert c["uniques"] == c["ecartees"] + c["retenues"] == 19
    assert (c["ecartees"], c["retenues"]) == (len(res["ecartees"]), len(res["retenues"])) == (4, 15)
    assert c["par_motif"] == {"hors prix": 1, "hors type": 1, "surface sous le minimum": 1, "neuf probable": 1}
    assert sum(c["par_motif"].values()) == c["ecartees"]


def test_volume_affiche_reconcilie_avec_les_annonces_lues():
    ok = _cribler([PAGE_1, PAGE_2], volume_affiche=21)["comptes"]
    ko = _cribler([PAGE_1, PAGE_2], volume_affiche=25)["comptes"]
    assert ok["ecart_volume"] == 0
    assert ko["ecart_volume"] == -4 and ko["volume_affiche"] == 25
    assert "ecart_volume" not in _cribler([PAGE_1, PAGE_2])["comptes"]


# --- motifs d'écart --------------------------------------------------------------------------------------------

def test_chaque_motif_d_ecart_est_liste_avec_son_annonce():
    ec = _par_id(_cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)["ecartees"])
    assert {i: a["motif"] for i, a in ec.items()} == {
        "9000000006": "hors prix", "9000000005": "hors type", "9000000007": "surface sous le minimum",
        "9000000004": "neuf probable"}
    assert all(a["titre"] and a["detail"] for a in ec.values())


def test_prix_strictement_inferieur_au_plafond_du_profil():
    res = _cribler([[_annonce(9000000101, prix=99999), _annonce(9000000102, prix=100000)]])
    assert [a["id"] for a in res["retenues"]] == ["9000000101"]
    assert _par_id(res["ecartees"])["9000000102"]["motif"] == "hors prix"


def test_prix_absent_est_un_motif_d_ecart_pas_une_retenue():
    res = _cribler([[_annonce(9000000103, prix=None)]])
    assert res["retenues"] == []
    assert res["ecartees"][0]["motif"] == "prix absent"


def test_hors_type_selon_le_profil_et_selon_types_explicite():
    pages = [[_annonce(9000000104, type_code="1"), _annonce(9000000105, type_code="5", titre="Immeuble 140 m²"),
              _annonce(9000000106, type_code="2"), _annonce(9000000107, type_code=None)]]
    par_defaut = _cribler(pages)
    assert sorted(a["id"] for a in par_defaut["retenues"]) == ["9000000104", "9000000105"]
    assert {a["id"]: a["motif"] for a in par_defaut["ecartees"]} == {"9000000106": "hors type",
                                                                      "9000000107": "hors type"}
    maisons = _cribler(pages, types={"1"})
    assert [a["id"] for a in maisons["retenues"]] == ["9000000104"]


def test_surface_sous_le_minimum_seulement_si_un_minimum_est_pose():
    pages = [[_annonce(9000000108, surface=24), _annonce(9000000109, surface=25), _annonce(9000000110, surface=None)]]
    sans = _cribler(pages)
    assert len(sans["retenues"]) == 3 and sans["ecartees"] == []
    avec = _cribler(pages, surface_min=25)
    assert _par_id(avec["ecartees"])["9000000108"]["motif"] == "surface sous le minimum"
    retenues = _par_id(avec["retenues"])
    assert set(retenues) == {"9000000109", "9000000110"}
    assert any("surface absente" in d for d in retenues["9000000110"]["drapeaux"])


@pytest.mark.parametrize("titre, dpe, attrs, neuf", [
    ("Maison 5 pièces 95 m²", "a", {}, True),                                              # la règle de repli
    ("Maison 5 pièces 95 m²", "d", {}, False),                                             # DPE autre que A
    ("Maison 5 pièces 95 m²", "a", {"fees_price": 4000}, False),                          # honoraires affichés
    ("Maison 5 pièces 95 m²", "a", {"fees_at_the_expanse_of": "buyer"}, False),           # honoraires à la charge de l'acquéreur
    # forme réelle d'une annonce de professionnel (P1 du 07/10/2026) : honoraires à la charge du vendeur ou nuls
    ("Maison 5 pièces 95 m²", "a", {"fees_at_the_expanse_of": "seller"}, True),
    ("Maison 5 pièces 95 m²", "a", {"fees_at_the_expanse_of": "seller", "fees_price": 0, "price_except_fees": 80000}, True),
    ("Maison de ville 5 pièces", "a", {}, False),                                          # pas un « Maison N pièces »
    ("Maison 3 pièce 70 m²", "a", {}, True),
    ("Maison de ville 80 m²", "d", {"immo_sell_type": "new"}, True),                       # signal du scan du 05/10/2026
    ("Maison de ville 80 m²", "d", {"immo_sell_type": "old"}, False),
])
def test_neuf_probable_regle_de_la_memoire(titre, dpe, attrs, neuf):
    res = _cribler([[_annonce(9000000111, titre=titre, attrs={"energy_rate": dpe, **attrs})]])
    if neuf:
        assert res["retenues"] == [] and res["ecartees"][0]["motif"] == "neuf probable"
    else:
        assert [a["id"] for a in res["retenues"]] == ["9000000111"]


@pytest.mark.parametrize("attrs, neuf, dans_le_detail", [
    ({}, True, "titre"),                                       # aucun type de vente : la règle du titre s'applique (inchangé)
    ({"immo_sell_type": ""}, True, "titre"),                   # type de vente vide : non renseigné, la règle du titre s'applique
    ({"immo_sell_type": "new"}, True, "new"),                  # le signal fort écarte, quel que soit le titre
    ({"immo_sell_type": "old"}, False, None),                  # explicite et différent de `new` : prime sur la règle du titre
    ({"immo_sell_type": "valeur-jamais-observee"}, False, None),   # la valeur d'un ancien n'est pas attestée : pas de littéral `old`
])
def test_type_de_vente_explicite_non_new_prime_sur_la_regle_du_titre(attrs, neuf, dans_le_detail):
    """« Maison N pièces », DPE A, sans honoraires ne vaut que sans type de vente."""
    a = _annonce(9000000114, titre="Maison 4 pièces 80 m²", attrs={"energy_rate": "a", **attrs})
    res = _cribler([[a]])
    if neuf:
        assert res["retenues"] == [] and [e["motif"] for e in res["ecartees"]] == ["neuf probable"]
        assert dans_le_detail in res["ecartees"][0]["detail"]
    else:
        assert [r["id"] for r in res["retenues"]] == ["9000000114"] and res["ecartees"] == []


def test_markdown_dit_que_le_type_de_vente_renseigne_prime_sur_la_regle_du_titre():
    seuils = crible.rendre_markdown(_cribler([PAGE_1]), date="2026-10-08", source="s", pages=["p.json"]).split("## Retenues")[0]
    neuf = next(ligne for ligne in seuils.splitlines() if ligne.startswith("- Neuf probable"))
    assert "type de vente renseigné et différent de new" in neuf and "l'emporte" in neuf


def test_motif_retenu_est_le_premier_de_la_liste_prix_type_surface_neuf():
    a = _annonce(9000000112, titre="Maison 5 pièces 20 m²", prix=500000, surface=20, type_code="2",
                 attrs={"energy_rate": "a"})
    res = _cribler([[a]], surface_min=25)
    assert [e["motif"] for e in res["ecartees"]] == ["hors prix"] and res["comptes"]["ecartees"] == 1


# --- biens non résidentiels ----------------------------------------------------

@pytest.mark.parametrize("type_code, titre, corps, ecartee", [
    # écartées : type « Autre », un bien non résidentiel nommé, aucun logement nommé
    ("5", "Péniche aménagée", "", True),                           # le scan du 05/10/2026 l'écartait à la main
    ("5", "Mobilier sur terrain", "", True),                       # idem
    ("5", "Garage 18 m²", "", True),                               # idem
    ("5", "Bateau à quai", "", True),
    ("5", "Bateaux de plaisance", "", True),                       # pluriel en x
    ("5", "Mobil-home 30 m²", "", True),
    ("5", "Mobil home sur emplacement", "", True),
    ("5", "Mobilhome", "", True),
    ("5", "Mobile home 3 chambres", "", True),                     # autre orthographe du même mot (revue du 08/10/2026)
    ("5", "Mobile-homes", "", True),
    ("5", "Box fermé", "", True),                                  # « fermé » n'est pas « ferme » : pas de logement
    ("5", "Garage", "", True),                                     # un bien non résidentiel seul, sans rien d'autre
    ("5", "Terrain en lotissement", "", True),                     # « lotissement » n'est pas « N lots »
    # « lot » seul ne dit pas un logement, un lot de garages reste écarté ; « N lots » en dit un
    ("5", "Lot de parkings", "", True),
    ("5", "Lot de 3 garages", "", True),
    ("5", "Lot de 10 box", "", True),
    ("5", "Garages, lot de 4", "", True),
    # mots d'habitation non retenus (mas, bien immobilier, ferme seul)
    ("5", "Mas avec terrain", "", True),
    ("5", "Bien immobilier avec garage", "", True),
    ("5", "Ferme avec hangar", "", True),
    ("5", "Garage et stock de pièces détachées", "", True),        # « pièces » sans nombre n'est pas « N pièces »
    ("5", "Terrain constructible", "", True),
    ("5", "Hangar agricole", "", True),
    ("5", "Entrepôt 400 m²", "", True),
    ("5", "ENTREPOT 400 M2", "", True),                            # casse et accents ignorés
    ("5", "PÉNICHE", "", True),
    ("5", "Garages en bloc", "", True),
    ("5", "Bien 120 m²", "Grand hangar avec bureaux", True),       # nommé dans la description seulement
    # retenues : un logement est nommé, ou le type n'est pas « Autre », ou le mot n'est pas dans la liste
    ("5", "Immeuble avec garage", "", False),                      # le cas de référence
    ("1", "Maison avec garage", "", False),                        # le cas de référence : type « Maison »
    ("5", "Maison avec terrain", "", False),
    ("5", "Pavillon et garage", "", False),
    ("5", "Appartement avec parking", "", False),
    ("5", "Studio et box", "", False),
    ("5", "Logement avec hangar", "", False),
    ("5", "Immeubles avec terrains", "", False),
    ("5", "Garage", "Maison de ville avec garage attenant", False),   # le logement est nommé dans la description
    ("5", "Immeuble de rapport 3 lots", "", False),
    # retenues : logements nommés autrement (sens prudent) ; les sept premières
    # sont des cas sondés comme « écartés à tort »
    ("5", "Villa avec garage", "", False),
    ("5", "Longère avec hangar", "", False),
    ("5", "Duplex avec parking", "", False),
    ("5", "T3 avec box", "", False),
    ("5", "Appart avec parking", "", False),
    ("5", "Maisonnettes sur terrain", "", False),
    ("5", "Rapport locatif 3 lots + garage", "", False),
    ("5", "Ensemble immobilier 3 lots avec terrain", "", False),   # « lots »
    ("5", "Habitation avec garage", "", False),
    ("5", "Triplex avec garage", "", False),
    ("5", "Lofts avec parkings", "", False),
    ("5", "F2 avec garage", "", False),
    ("5", "5 pièces avec terrain", "", False),                     # « N pièces »
    ("5", "Appt 3 pièces et box", "", False),
    ("5", "Fermette avec hangar", "", False),
    ("5", "Corps de ferme, hangar et terrain", "", False),
    ("5", "3 lots avec garage", "", False),                        # « N lots » : un nombre avant « lot », sans autre mot de logement
    ("5", "1 lot et parking", "", False),
    ("5", "Garage", "Villa de 120 m² avec garage", False),         # le logement est nommé dans la description, mot ajouté
    ("5", "Belle terrasse 40 m²", "", False),                      # « terrasse » n'est pas « terrain »
    ("5", "Local commercial 80 m²", "", False),                    # hors de la liste des mots non résidentiels
    ("1", "Garage 20 m²", "", False),                              # le motif ne vaut que pour le type « Autre »
])
def test_non_residentiel_probable_type_autre_sans_logement_nomme(type_code, titre, corps, ecartee):
    res = _cribler([[_annonce(9000000600, titre=titre, type_code=type_code, corps=corps)]])
    if ecartee:
        assert res["retenues"] == []
        assert [e["motif"] for e in res["ecartees"]] == ["non résidentiel probable"]
        assert "logement" in res["ecartees"][0]["detail"] and res["comptes"]["par_motif"] == {"non résidentiel probable": 1}
    else:
        assert [a["id"] for a in res["retenues"]] == ["9000000600"] and res["ecartees"] == []


def test_listes_du_motif_non_residentiel():
    assert crible.MOTS_NON_RESIDENTIELS == ("péniche", "bateau", "mobil-home", "garage", "box", "parking", "terrain",
                                            "hangar", "entrepôt")
    assert crible.MOTS_LOGEMENT == ("maison", "immeuble", "appartement", "logement", "studio", "pavillon")
    for mot in crible.MOTS_NON_RESIDENTIELS:                     # chaque mot de la liste écarte un type « Autre »
        res = _cribler([[_annonce(9000000601, titre=f"{mot} 30 m²", type_code="5")]])
        assert [e["motif"] for e in res["ecartees"]] == ["non résidentiel probable"], mot
        assert mot in res["ecartees"][0]["detail"]
        for logement in crible.MOTS_LOGEMENT:                     # et chaque logement nommé le retient
            res = _cribler([[_annonce(9000000601, titre=f"{logement} avec {mot}", type_code="5")]])
            assert [a["id"] for a in res["retenues"]] == ["9000000601"], (logement, mot)


def test_logements_ajoutes_le_08_10_2026_sont_epingles_et_chacun_retient_un_type_autre():
    """Sens prudent : les six mots de logement de base ne changent pas, d'autres disent un logement."""
    assert crible.MOTS_LOGEMENT_AJOUTES == (
        # première passe
        "maisonnette", "appart", "appt", "logt", "villa", "longère", "duplex", "triplex", "loft", "habitation", "fermette",
        "corps de ferme", "rapport locatif",
        # ni « mas », ni « bien immobilier », ni « ferme » seul
        "propriété", "bâtisse", "chalet", "bungalow", "manoir", "château", "moulin", "demeure", "bastide", "résidence",
        "hôtel particulier", "ensemble immobilier")
    assert list(crible.FORMES_LOGEMENT_AJOUTEES) == ["T1 à T6", "F1 à F6", "N pièces", "N lots"]
    exemples = [*crible.MOTS_LOGEMENT_AJOUTES, *(f"{lettre}{n}" for lettre in "TF" for n in range(1, 7)),
                "1 pièce", "2 pièces", "12 pièces", "1 lot", "3 lots", "12 lots"]
    for logement in exemples:
        for mot in crible.MOTS_NON_RESIDENTIELS:                   # un logement nommé retient, quel que soit le bien non résidentiel
            res = _cribler([[_annonce(9000000607, titre=f"{logement} avec {mot}", type_code="5")]])
            assert [a["id"] for a in res["retenues"]] == ["9000000607"], (logement, mot)
    for logement in ("maisonnettes", "apparts", "villas", "longères", "lofts", "châteaux", "propriétés", "résidences",
                     "T3", "f4", "3 LOTS"):                                                              # pluriel, casse
        res = _cribler([[_annonce(9000000607, titre=f"{logement} et parking", type_code="5")]])
        assert [a["id"] for a in res["retenues"]] == ["9000000607"], logement
    for sans_logement in ("T7 et parking", "F0 et parking", "Parking a1 t", "Hangar et 12 m² de pièces", "Box fermé",
                          "Lot de 3 garages", "Garages, lot de 4"):
        res = _cribler([[_annonce(9000000607, titre=sans_logement, type_code="5")]])        # mots entiers : aucun de ces titres
        assert [e["motif"] for e in res["ecartees"]] == ["non résidentiel probable"], sans_logement


@pytest.mark.parametrize("titre", [
    "Propriété avec garage", "Bâtisse avec hangar", "Chalet avec garage", "Bungalow avec parking", "Manoir avec hangar",
    "Château avec parc et terrain", "Moulin avec terrain", "Demeure avec garage", "Bastide avec hangar",
    "Résidence avec parking", "Hôtel particulier avec garage", "Ensemble immobilier avec terrain"])
def test_habitation_nommee_retient_un_type_autre_dernier_passe_du_08_10(titre):
    """Un test par mot ajouté à la dernière passe : l'habitation nommée, avec un bien non résidentiel dans le titre, est retenue."""
    res = _cribler([[_annonce(9000000608, titre=titre, type_code="5")]])
    assert [a["id"] for a in res["retenues"]] == ["9000000608"] and res["ecartees"] == []


def test_non_residentiel_probable_vient_apres_hors_type_et_avant_la_surface_minimale():
    assert crible.MOTIFS[crible.MOTIFS.index("hors type") + 1] == "non résidentiel probable"
    assert crible.MOTIFS.index("non résidentiel probable") < crible.MOTIFS.index("surface sous le minimum")
    def motifs(a, **kw):
        return [e["motif"] for e in _cribler([[a]], **kw)["ecartees"]]
    assert motifs(_annonce(9000000602, titre="Garage", type_code="2")) == ["hors type"]
    assert motifs(_annonce(9000000603, titre="Garage", type_code="5", prix=500000)) == ["hors prix"]
    assert motifs(_annonce(9000000604, titre="Garage", type_code="5", surface=20), surface_min=25) == [
        "non résidentiel probable"]


def test_markdown_dit_la_regle_non_residentielle_ses_listes_et_ses_ecartees():
    pages = [[_annonce(9000000605, titre="Péniche aménagée", type_code="5"), _annonce(9000000606)]]
    md = crible.rendre_markdown(_cribler(pages), date="2026-10-08", source="s", pages=["p.json"])
    seuils, ecartees = md.split("## Retenues")[0], md.split("## Écartées")[1]
    assert "Non résidentiel probable" in seuils and "type 5" in seuils
    assert all(mot in seuils for mot in (*crible.MOTS_NON_RESIDENTIELS, *crible.MOTS_LOGEMENT, *crible.MOTS_LOGEMENT_AJOUTES,
                                         *crible.FORMES_LOGEMENT_AJOUTEES))
    assert "mobile home" in seuils and "pluriel" in seuils                              # l'orthographe alternative est dite
    assert "non résidentiel probable 1" in md.split("## Seuils")[0]                       # compté dans les comptes
    assert "### non résidentiel probable (1)" in ecartees and "9000000605" in ecartees


# --- exception du profil, plafond explicite --------------------------------------------------------------------

def test_exception_du_profil_leve_le_plafond_pour_son_annonce_seulement():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    retenues = _par_id(res["retenues"])
    assert "9000000012" in retenues and retenues["9000000012"]["prix"] == 130000
    assert any("exception du profil" in d for d in retenues["9000000012"]["drapeaux"])
    autre = _annonce(9000000099, prix=130000)  # même prix, sans exception
    res2 = _cribler([[autre]])
    assert res2["retenues"] == [] and res2["ecartees"][0]["motif"] == "hors prix"


def test_prix_max_explicite_remplace_le_profil_et_ses_exceptions():
    res = _cribler([PAGE_1, PAGE_2], prix_max=100000)
    assert _par_id(res["ecartees"])["9000000012"]["motif"] == "hors prix"          # l'exception ne vaut que pour le profil
    large = _cribler([PAGE_1, PAGE_2], prix_max=200000)
    assert "9000000006" in _par_id(large["retenues"])                                # 150 000 < 200 000
    assert large["plafond"]["origine"] == "--prix-max" and large["plafond"]["valeur"] == 200000


def test_exception_du_profil_sur_la_cible_leve_le_type_pour_son_annonce():
    profil = copy.deepcopy(PROFIL)
    cible = next(d for d in profil["decisions"] if d["cle"] == "cible")
    cible["exceptions"] = [{"annonce": "9000000106", "portee": "appartement admis", "date": "2026-01-03"}]
    pages = [[_annonce(9000000106, type_code="2"), _annonce(9000000113, type_code="2")]]
    res = crible.cribler(pages, profil=profil)
    assert [a["id"] for a in res["retenues"]] == ["9000000106"]
    assert _par_id(res["ecartees"])["9000000113"]["motif"] == "hors type"


def _gabarit_rempli() -> dict:
    """Le gabarit `templates/profil.json`, sources remplacées comme le ferait l'investisseur."""
    profil = json.loads(PROFIL_GABARIT.read_text(encoding="utf-8"))
    for d in profil["decisions"]:
        d["source"] = "décision de l'investisseur (test)"
    return profil


def test_profil_du_gabarit_non_rempli_refuse():
    with pytest.raises(crible.Illisible, match="profil non rempli"):
        crible.regles_du_profil(json.loads(PROFIL_GABARIT.read_text(encoding="utf-8")))


def test_profil_du_gabarit_rempli_lu_sans_chiffre_recopie():
    profil = _gabarit_rempli()
    regles = crible.regles_du_profil(profil)
    decisions = {d["cle"]: d for d in profil["decisions"]}
    assert regles["plafond"] == decisions["premier_achat_prix_max"]["valeur"]
    assert regles["exceptions_prix"] == {e["annonce"] for e in decisions["premier_achat_prix_max"]["exceptions"]}
    attendus = set().union(*(crible.TYPES_PAR_CIBLE[c] for c in decisions["cible"]["valeur"]))
    assert regles["types"] == attendus
    assert regles["zone"] == [decisions["zone"]["valeur"]["commune_centre"], *decisions["zone"]["valeur"]["communes"][1:]]


def test_cible_inconnue_du_profil_est_refusee_pas_ignoree():
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "cible")["valeur"] = ["chateau"]
    with pytest.raises(crible.Illisible, match="chateau"):
        crible.regles_du_profil(profil)


# --- doublons probables, jamais fusionnés ----------------------------------------------------------------------

def test_doublon_probable_groupe_et_non_fusionne():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    groupe = next(g for g in res["doublons"] if "9000000001" in g["ids"])
    assert groupe["ids"] == ["9000000001", "9000000002"]
    assert any("même commune" in r and "5 %" in r for r in groupe["raisons"])
    retenues = _par_id(res["retenues"])
    assert "9000000001" in retenues and "9000000002" in retenues                    # deux lignes, rien n'est fusionné
    assert res["comptes"]["retenues"] == 15
    assert all(any(groupe["groupe"] in d for d in retenues[i]["drapeaux"]) for i in groupe["ids"])


def test_doublon_probable_tolerances_surface_5_pour_cent_et_prix_10_pour_cent():
    """Surface à ±5 % et prix à ±10 %, écart relatif au plus grand des deux."""
    a = _annonce(9000000122, prix=100000, surface=100)
    for prix_b, surface_b, attendu in [(105000, 100, True),     # 4,8 % sur le prix
                                       (106000, 100, True),     # 5,7 % sur le prix : hors de l'ancien seuil de 5 %, dans celui de 10 %
                                       (111000, 100, True),     # 9,9 % sur le prix
                                       (112000, 100, False),    # 10,7 % sur le prix
                                       (100000, 105, True),     # 4,8 % sur la surface
                                       (100000, 106, False),    # 5,7 % sur la surface : la surface reste à ±5 %
                                       (111000, 106, False),    # prix dans ±10 % mais surface hors de ±5 %
                                       (100000, 100, True)]:
        b = _annonce(9000000123, prix=prix_b, surface=surface_b)
        res = _cribler([[a, b]], prix_max=200000)
        assert bool(res["doublons"]) is attendu, (prix_b, surface_b)
        if attendu:
            assert res["doublons"][0]["ids"] == ["9000000122", "9000000123"]
    autre_commune = _annonce(9000000123, prix=100000, surface=100, commune="Exempleville")  # mêmes prix et surface
    assert _cribler([[a, autre_commune]], prix_max=200000)["doublons"] == []


def test_doublon_210_et_212_m2_a_182000_et_195000_euros_est_groupe():
    """Même immeuble publié deux fois (valeurs fictives) : un écart de prix de 6,7 %, hors de ±5 %, est vu avec ±10 %."""
    a = _annonce(9000000500, titre="Immeuble 210 m²", prix=182000, surface=210, type_code="5")
    b = _annonce(9000000501, titre="Immeuble 212 m²", prix=195000, surface=212, type_code="5")
    assert 0.05 < abs(182000 - 195000) / 195000 < 0.10                        # 6,7 % : au-delà de ±5 %, dans ±10 %
    res = _cribler([[a, b]], prix_max=200000)
    assert [g["ids"] for g in res["doublons"]] == [["9000000500", "9000000501"]]
    assert any("même commune" in r and "surface à ±5 %" in r and "prix à ±10 %" in r for r in res["doublons"][0]["raisons"])
    retenues = _par_id(res["retenues"])
    assert set(retenues) == {"9000000500", "9000000501"}                      # deux lignes, rien n'est fusionné
    assert all(any("doublon probable G1" in d for d in retenues[i]["drapeaux"]) for i in retenues)


def test_markdown_dit_les_deux_tolerances_du_doublon_avant_les_resultats():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    seuils = crible.rendre_markdown(res, date="2026-10-08", source="s", pages=["p.json"]).split("## Retenues")[0]
    assert "surface à ±5 % et prix à ±10 %" in seuils
    assert (res["seuils"]["tolerance_doublon_surface"], res["seuils"]["tolerance_doublon_prix"]) == (0.05, 0.10)
    assert (crible.TOLERANCE_DOUBLON_SURFACE, crible.TOLERANCE_DOUBLON_PRIX) == (0.05, 0.10)


def test_surface_absente_empeche_le_doublon_par_prix_et_surface():
    a, b = _annonce(9000000124, prix=100000, surface=None), _annonce(9000000125, prix=100000, surface=None)
    assert _cribler([[a, b]], prix_max=200000)["doublons"] == []


def test_meme_point_precis_groupe_deux_annonces_de_particulier():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    groupe = next(g for g in res["doublons"] if "9000000013" in g["ids"])
    assert groupe["ids"] == ["9000000013", "9000000014"]
    assert any("même point" in r for r in groupe["raisons"])


def test_point_partage_par_4_annonces_n_est_pas_un_point_precis():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    quatre = {"9000000008", "9000000009", "9000000010", "9000000011"}
    assert not any(quatre & set(g["ids"]) for g in res["doublons"])
    partage = next(p for p in res["points_partages"] if set(p["ids"]) == quatre)
    assert len(partage["ids"]) == 4 and partage["lat"] == 48.1 and partage["lng"] == 2.1
    # le même point partagé par 3 annonces à adresse précise reste un point précis
    point = (48.2, 2.2)
    trois = [_annonce(9000000130 + i, prix=50000 + 20000 * i, surface=60 + 30 * i, source="address", point=point)
             for i in range(3)]
    assert [g["ids"] for g in _cribler([trois])["doublons"]] == [["9000000130", "9000000131", "9000000132"]]
    quatre_adresses = trois + [_annonce(9000000133, prix=50000 + 20000 * 3, surface=60 + 30 * 3, source="address",
                                        point=point)]
    assert _cribler([quatre_adresses])["doublons"] == []


def test_point_de_commune_source_city_n_est_jamais_precis_meme_a_deux():
    point = (48.3, 2.3)
    a = _annonce(9000000140, prix=50000, surface=60, source="city", point=point)
    b = _annonce(9000000141, prix=80000, surface=90, source="city", point=point)
    assert _cribler([[a, b]])["doublons"] == []


def test_point_precis_sans_champ_source_retombe_sur_la_regle_des_trois_annonces():
    point = (48.4, 2.4)
    paire = [_annonce(9000000150 + i, prix=40000 + 25000 * i, surface=50 + 30 * i, point=point) for i in range(2)]
    for a in paire:
        del a["location"]["source"], a["location"]["is_shape"]
    assert [g["ids"] for g in _cribler([paire])["doublons"]] == [["9000000150", "9000000151"]]


# --- rendement indicatif avec la formule du tri rapide ---------------------------------------------------------

def test_rendement_calcule_avec_loyer_3r_vraie_fonction_et_fiche_fictive():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    retenues = _par_id(res["retenues"])
    # loyer annuel ÷ (prix × 1,08), convention du crible (frais d'acquisition de l'ancien)
    # 92 m² = surface type de la série maison : facteur 1, loyer = 10,0 €/m² × 92 = 920 €/mois (calcul à la main)
    assert retenues["9000000001"]["rendement"] == pytest.approx(920 * 12 / (80000 * 1.08))
    for ident in ("9000000001", "9000000018", "9000000015"):
        a = retenues[ident]
        loyer = loyer_3r(FICHE, "maison", float(a["surface"]), 0.0)["scenarios"]["realiste"]["loyer_hc"]
        assert a["rendement"] == pytest.approx(loyer * 12 / (a["prix"] * 1.08)), ident
    assert retenues["9000000018"]["rendement"] != pytest.approx(920 * 12 / (85000 * 1.08))   # la correction de surface s'applique


def test_rendement_divise_par_prix_fois_1_08_et_le_texte_le_dit():
    """Le moteur divise par le coût total réel, le crible approche les frais de l'ancien."""
    assert crible.COEF_COUT_ACQUISITION == 1.08
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    a = _par_id(res["retenues"])["9000000001"]
    assert a["rendement"] == pytest.approx(920 * 12 / (80000 * 1.08)) and a["rendement"] < 920 * 12 / 80000
    assert a["rendement_texte"].startswith(f"{a['rendement'] * 100:.1f} %".replace(".", ","))
    assert "÷ (prix × 1,08)" in a["rendement_texte"]
    assert res["seuils"]["coef_cout_acquisition"] == 1.08
    pistes = {p["id"]: p for p in _pistes(res, nb_candidats=15)}
    assert "÷ (prix × 1,08)" in pistes["9000000001"]["rendement"]                  # la piste reprend le texte du crible


def test_markdown_dit_que_le_rendement_est_divise_par_prix_fois_1_08():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])
    seuils = crible.rendre_markdown(res, date="2026-10-08", source="s", pages=["p.json"]).split("## Retenues")[0]
    ligne = next(t for t in seuils.splitlines() if t.startswith("- Rendement brut indicatif"))
    assert "divisé par (prix annoncé × 1,08)" in ligne and "convention du crible" in ligne
    assert "coût total réel" in ligne and "frais d'acquisition de l'ancien" in ligne        # le moteur, lui, divise par le coût réel
    assert "ne se compare pas" not in ligne


def test_rendement_extrapolation_reprise_dans_le_drapeau():
    a = _par_id(_cribler([PAGE_1, PAGE_2], fiches=[FICHE])["retenues"])["9000000001"]
    assert any("extrapolation" in d and "série maison" in d for d in a["drapeaux"])
    assert "extrapolation" in a["rendement_texte"]


@pytest.mark.parametrize("ident, raison", [
    ("9000000003", "lots inconnus"),          # type Autre, « immeuble », local
    ("9000000017", "lots inconnus"),          # type Autre, « immeuble de rapport 3 lots »
    ("9000000008", "aucune fiche"),           # maison d'une commune sans fiche
])
def test_rendement_non_calcule_pour_immeuble_a_lots_inconnus_ou_sans_fiche(ident, raison):
    a = _par_id(_cribler([PAGE_1, PAGE_2], fiches=[FICHE])["retenues"])[ident]
    assert a["rendement"] is None
    assert a["rendement_texte"].startswith("non calculé") and raison in a["rendement_texte"]


def test_maison_divisee_en_appartements_est_un_immeuble_a_lots_inconnus():
    a = _annonce(9000000160, titre="Maison divisée en 2 appartements", prix=90000, surface=78)
    r = _cribler([[a]], fiches=[FICHE])["retenues"][0]
    assert r["rendement"] is None and "lots inconnus" in r["rendement_texte"]


def test_fiche_inutilisable_donne_non_calcule_avec_la_raison():
    fiche = copy.deepcopy(FICHE)
    del fiche["loyers"]["maison"]
    r = _cribler([[_annonce(9000000161)]], fiches=[fiche])["retenues"][0]
    assert r["rendement"] is None and r["rendement_texte"].startswith("non calculé") and "maison" in r["rendement_texte"]


# --- classement et drapeaux ------------------------------------------------------------------------------------

def test_classement_rendement_decroissant_puis_prix_m2_croissant():
    retenues = _cribler([PAGE_1, PAGE_2], fiches=[FICHE])["retenues"]
    avec = [a for a in retenues if a["rendement"] is not None]
    sans = [a for a in retenues if a["rendement"] is None]
    assert retenues == avec + sans and len(sans) > 0 and len(avec) > 0
    assert [a["rendement"] for a in avec] == sorted((a["rendement"] for a in avec), reverse=True)
    assert [a["prix_m2"] for a in sans] == sorted(a["prix_m2"] for a in sans)
    assert [a["rang"] for a in retenues] == list(range(1, len(retenues) + 1))


def test_classement_sans_aucune_fiche_est_par_prix_m2_croissant():
    retenues = _cribler([PAGE_1, PAGE_2])["retenues"]
    assert all(a["rendement"] is None for a in retenues)
    assert [a["prix_m2"] for a in retenues] == sorted(a["prix_m2"] for a in retenues)


def test_drapeau_bien_mixte_titre_ou_description():
    res = _cribler([PAGE_1, PAGE_2, [_annonce(9000000170, titre="Maison de ville 100 m²", corps="avec ancien commerce")]])
    retenues = _par_id(res["retenues"])
    for ident in ("9000000003", "9000000019", "9000000170"):
        assert any(d.startswith("bien mixte") and "surface du DPE" in d for d in retenues[ident]["drapeaux"]), ident
    assert not any(d.startswith("bien mixte") for d in retenues["9000000002"]["drapeaux"])


def test_drapeau_sous_le_premier_decile_des_retenues():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)           # 15 retenues : premier décile à l'indice 1,4
    retenues = _par_id(res["retenues"])
    sous = {i for i, a in retenues.items() if any("premier décile" in d for d in a["drapeaux"])}
    assert sous == {"9000000015", "9000000003"}                                     # 200 et 500 €/m² sous le premier décile = 553,3
    assert any("grange" in d and "hors commune" in d for d in retenues["9000000015"]["drapeaux"])
    assert res["seuils"]["decile_prix_m2"] == pytest.approx(500 + 0.4 * (633.3333333 - 500), rel=1e-4)


def test_decile_non_calcule_sous_dix_retenues():
    res = _cribler([[_annonce(9000000180 + i, prix=40000 + 5000 * i, surface=80) for i in range(9)]])
    assert res["seuils"]["decile_prix_m2"] is None
    assert not any("premier décile" in d for a in res["retenues"] for d in a["drapeaux"])
    dix = _cribler([[_annonce(9000000190 + i, prix=40000 + 5000 * i, surface=80) for i in range(10)]])
    assert dix["seuils"]["decile_prix_m2"] is not None


def test_date_affichee_est_notee_comme_telle_pas_comme_anciennete():
    a = _cribler([PAGE_1])["retenues"][0]
    assert any("date affichée 2026-09-01" in d and "ancienneté" in d and "date ancienne" in d and "récente ne prouve rien" in d
               for d in a["drapeaux"])


# --- structure réelle : lecture des champs ---------------------------------------------------------------------

def test_identifiant_et_url_depuis_la_structure_reelle():
    brute = next(a for a in PAGE_1 if a["list_id"] == 9000000001)                     # avec `url` et champs en plus
    sans_url = _annonce(9000000200)
    sans_id = _annonce(9000000201)
    del sans_id["list_id"]
    sans_id["url"] = "https://www.leboncoin.fr/ad/ventes_immobilieres/9000000201"
    res = _cribler([[brute, sans_url, sans_id]])
    par = _par_id(res["retenues"])
    assert par["9000000001"]["url"] == brute["url"]
    assert par["9000000200"]["url"] == "https://www.leboncoin.fr/ad/ventes_immobilieres/9000000200"
    assert "9000000201" in par


def test_annonce_sans_identifiant_est_illisible_pas_ignoree():
    sans = _annonce(9000000202)
    del sans["list_id"]
    with pytest.raises(crible.Illisible, match="identifiant"):
        _cribler([[sans]])
    with pytest.raises(crible.Illisible):
        _cribler([["pas une annonce"]])


def test_colonnes_dpe_baisse_et_taxe_fonciere():
    a = _par_id(_cribler([PAGE_1])["retenues"])["9000000001"]
    assert (a["dpe"], a["taxe_fonciere"], a["surface"], a["commune"]) == ("D", 900, 92.0, "Fictibourg")
    assert a["baisse"]["ancien_prix"] == 90000 and a["baisse"]["pourcent"] == pytest.approx(-100 * 10000 / 90000)
    sans = _par_id(_cribler([PAGE_1])["retenues"])["9000000002"]
    assert sans["baisse"] is None and sans["taxe_fonciere"] is None


# --- pistes proposées ------------------------------------------------------------------------------------------

def _pistes(res, **kw):
    return crible.proposer_pistes(res, date="2026-10-07", source="bruts/scan-demo.md", **kw)


def test_cles_des_pistes_proposees():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    pistes = _pistes(res, nb_candidats=2)
    assert {p["categorie"] for p in pistes} == {"candidat", "remarquable"}
    for p in pistes:
        attendu = CLES_PISTE_COMMUNES | ({"rang"} if p["categorie"] == "candidat" else set())
        assert set(p) - {"question", "note"} == attendu, p["id"]
        assert ("question" in p) != ("note" in p), p["id"]                            # l'une ou l'autre, jamais les deux
        assert isinstance(p["id"], str) and isinstance(p["prix"], int) and p["surface"].endswith(" m²")
        assert p["source"] == "bruts/scan-demo.md" and p["repere_le"] == "2026-10-07"
        assert p["url"] == f"https://www.leboncoin.fr/ad/ventes_immobilieres/{p['id']}"


def test_candidats_sont_le_haut_du_classement_remarquables_ont_un_drapeau_d_interet():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    pistes = _pistes(res, nb_candidats=3)
    candidats = [p for p in pistes if p["categorie"] == "candidat"]
    assert [p["id"] for p in candidats] == [a["id"] for a in res["retenues"][:3]]
    assert [p["rang"] for p in candidats] == [1, 2, 3]
    retenues = _par_id(res["retenues"])
    remarquables = [p for p in pistes if p["categorie"] == "remarquable"]
    assert remarquables and all(any("premier décile" in d for d in retenues[p["id"]]["drapeaux"])
                                for p in remarquables)
    assert not {p["id"] for p in remarquables} & {p["id"] for p in candidats}
    assert len({p["id"] for p in pistes}) == len(pistes)


def test_pistes_par_defaut_huit_candidats_au_plus():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    assert sum(p["categorie"] == "candidat" for p in _pistes(res)) == crible.NB_CANDIDATS == 8


def test_piste_candidate_d_un_doublon_probable_le_dit_dans_sa_question():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    pistes = {p["id"]: p for p in _pistes(res, nb_candidats=15)}
    assert "9000000002" in pistes["9000000001"]["question"] and "photos" in pistes["9000000001"]["question"]
    assert "rendement" in pistes["9000000001"]
    assert pistes["9000000003"]["rendement"].startswith("non calculé")
    assert re.search(r"\d+,\d %", pistes["9000000001"]["rendement"])


# --- rendu Markdown --------------------------------------------------------------------------------------------

def test_markdown_au_format_des_scans_comptes_seuils_tableau_ecartees_doublons():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25, volume_affiche=21)
    md = crible.rendre_markdown(res, date="2026-10-07", source="bruts/scan-demo.md", pages=["p1.json", "p2.json"])
    assert md.startswith("# Crible Leboncoin") and "2026-10-07" in md.splitlines()[0]
    for titre in ("## Comptes", "## Seuils de méthode", "## Retenues", "## Écartées", "## Doublons probables"):
        assert titre in md
    assert "| Rang | Identifiant | URL | Titre | Commune | Prix | Surface | €/m² | DPE | Baisse | Taxe foncière |" in md
    assert "Rendement brut indicatif | Drapeaux |" in md
    assert "21 annonces lues" in md and "19 identifiants uniques" in md and "2 doublons entre pages" in md
    assert "4 écartées" in md and "15 retenues" in md and "volume affiché 21" in md
    assert "| 9000000001 | https://www.leboncoin.fr/ad/ventes_immobilieres/9000000001 |" in md
    for constante in ("±5 %", "premier décile", "3 annonces"):
        assert constante in md.split("## Retenues")[0]                                # seuils dits avant les résultats
    assert md.count("| 9000000006 |") == 0 and "9000000006" in md.split("## Écartées")[1]
    assert "jamais fusionnés" in md.split("## Doublons probables")[1]


def test_markdown_dit_ce_que_valent_les_champs_absents():
    md = crible.rendre_markdown(_cribler([PAGE_1]), date="2026-10-07", source="s", pages=["p.json"])
    assert "description absente" in md                                                # `body` vide dans une page de résultats
    assert "aucune fiche" in md                                                       # pas de --fiche : rendement non calculé


# --- ligne de commande -----------------------------------------------------------------------------------------

def test_cli_demonstration_ecrit_le_scan_et_les_pistes(tmp_path):
    r = _lancer(*_args_demo(tmp_path))
    assert r.returncode == 0, r.stderr
    md = (tmp_path / "scan.md").read_text(encoding="utf-8")
    assert "21 annonces lues" in md and "15 retenues" in md
    pistes = json.loads((tmp_path / "pistes.json").read_text(encoding="utf-8"))
    assert [p["categorie"] for p in pistes["pistes"]].count("candidat") == 8
    assert all(p["source"] == "bruts/scan-demo.md" for p in pistes["pistes"])
    assert "21 annonces lues" in r.stdout and "15 retenues" in r.stdout


def test_cli_source_par_defaut_est_le_nom_du_scan_sous_bruts(tmp_path):
    args = [a for a in _args_demo(tmp_path)]
    i = args.index("--source")
    del args[i:i + 2]
    assert _lancer(*args).returncode == 0
    pistes = json.loads((tmp_path / "pistes.json").read_text(encoding="utf-8"))["pistes"]
    assert {p["source"] for p in pistes} == {"bruts/scan.md"}


def test_cli_types_et_prix_max_explicites(tmp_path):
    r = _lancer(*_args_demo(tmp_path, "--types", "1", "--prix-max", "200000"))
    assert r.returncode == 0, r.stderr
    md = (tmp_path / "scan.md").read_text(encoding="utf-8")
    assert "hors type" in md and "--prix-max" in md
    assert _lancer(*_args_demo(tmp_path, "--types", "chateau")).returncode == 2


def _arbre_factice(racine: Path) -> Path:
    """Copie minimale de l'arborescence gardée : immo-data/{bruts/, pistes.json}, sans rien de réel."""
    (racine / "immo-data" / "bruts").mkdir(parents=True)
    pistes = racine / "immo-data" / "pistes.json"
    pistes.write_text('{"pistes": []}\n', encoding="utf-8")
    return pistes


def _avec_sortie(tmp_path: Path, option: str, cible: Path) -> list[str]:
    args = _args_demo(tmp_path)
    args[args.index(option) + 1] = str(cible)
    return args


# Relevé des écritures dans un processus fils : la preuve qu'une exécution n'écrit que là où elle le doit, sans toucher aux
# vrais fichiers pour le vérifier. Même méthode que `CODE_AUDIT_OPEN` de tests/test_immo_foyer.py : un crochet d'audit ne se
# retire pas, il vit donc dans le fils et jamais dans le processus de pytest. Le fils importe le crible, puis relève,
# pendant l'exécution de `code` seulement, les ouvertures en écriture (`open`, `io.open`, `Path.write_text`, `os.open`) et
# les mutations de chemins (renommage, suppression, création, troncature, lien...). Il rend le tout en JSON.
CODE_AUDIT_ECRITURES = """
import contextlib, io, json, os, sys
sys.dont_write_bytecode = True               # un import n'écrit pas son `.pyc` : le relevé ne voit que ce que fait `code`
racine, code, *argv = sys.argv[1:]
sys.path[:0] = [racine, os.path.join(racine, "scripts")]
import immo_crible                           # importé avant le relevé : ses imports n'en font pas partie
MUTATIONS = {"os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.link", "os.symlink", "os.utime",
             "os.chmod", "os.chown", "shutil.move", "shutil.copyfile", "shutil.rmtree"}
ecrits, mutations, actif = [], [], False
def _crochet(evenement, args):
    if not actif:
        return
    try:
        if evenement == "open":
            chemin, mode, flags = args
            en_ecriture = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)))
            if en_ecriture and isinstance(chemin, (str, bytes, os.PathLike)):
                ecrits.append(os.fsdecode(chemin))
        elif evenement in MUTATIONS:
            mutations.append([evenement, [os.fsdecode(a) for a in args if isinstance(a, (str, bytes, os.PathLike))]])
    except Exception:                        # un crochet d'audit qui lève interromprait l'opération observée : il ne lève jamais
        pass
sys.addaudithook(_crochet)
resultat = {}
actif = True
with contextlib.redirect_stdout(io.StringIO()):
    exec(code, {"immo_crible": immo_crible, "argv": argv, "resultat": resultat})
actif = False
print(json.dumps({"resultat": resultat, "ecrits": sorted(set(ecrits)), "mutations": mutations}))
"""


def _audit_ecritures(code: str, *argv: str) -> dict:
    r = subprocess.run([sys.executable, "-c", CODE_AUDIT_ECRITURES, str(ROOT), code, *argv], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("option, relatif", [
    ("--out", "immo-data/bruts/scan.md"),
    ("--out", "immo-data/bruts/sous-dossier/scan.md"),
    ("--pistes-out", "immo-data/bruts/pistes.json"),
    ("--pistes-out", "immo-data/pistes.json"),
    ("--out", "immo-data/pistes.json"),
    # le volume macOS ne distingue pas la casse : toute variante désigne le même dossier ou fichier
    ("--out", "Immo-Data/BRUTS/scan.md"),
    ("--out", "immo-data/Bruts/neuf/scan.md"),
    ("--pistes-out", "immo-data/PISTES.JSON"),
    ("--pistes-out", "IMMO-DATA/Pistes.json"),
])
def test_cli_refuse_d_ecrire_dans_bruts_ni_sur_pistes_json_meme_en_variante_de_casse(tmp_path, option, relatif):
    racine = tmp_path / "depot"
    pistes = _arbre_factice(racine)
    avant = pistes.read_bytes()
    r = _lancer(*_avec_sortie(tmp_path, option, racine / relatif))
    assert r.returncode == 2, (option, relatif, r.stderr)
    assert "bruts" in r.stderr or "pistes.json" in r.stderr
    assert pistes.read_bytes() == avant
    assert list((racine / "immo-data" / "bruts").rglob("*")) == []
    assert not (tmp_path / "scan.md").exists() and not (tmp_path / "pistes.json").exists()


def test_cli_ecrit_hors_de_l_arbre_garde_meme_a_cote(tmp_path):
    racine = tmp_path / "depot"
    _arbre_factice(racine)
    (racine / "immo-data" / "scratch").mkdir()
    cible = racine / "immo-data" / "scratch" / "scan.md"        # voisin de bruts/, pas dedans
    assert _lancer(*_avec_sortie(tmp_path, "--out", cible)).returncode == 0
    assert cible.exists()


CIBLES_REELLES = [
    ("--out", PISTES_DEFAUT), ("--pistes-out", PISTES_DEFAUT),
    ("--out", Path(str(ROOT / "IMMO-DATA" / "PISTES.JSON"))),
    ("--pistes-out", BRUTS / "zz_test_refus_pistes.json"),
    ("--out", BRUTS / "zz_test_refus_scan.md"),
    ("--out", Path(str(ROOT / "immo-data" / "BRUTS" / "zz_test_refus_scan.md"))),
]


@pytest.mark.parametrize("option, cible", CIBLES_REELLES)
def test_cli_refuse_les_chemins_du_dossier_de_donnees(option, cible):
    """La garde de sortie refuse `pistes.json` et `bruts/` du dossier de données, variantes de casse comprises.

    Elle est appelée directement, sans lancer la CLI : `_verifier_sortie` résout et compare des chemins, elle n'ouvre rien
    en écriture (le test suivant le relève). Une garde en défaut fait donc échouer ce test sans pouvoir rien écrire.
    """
    with pytest.raises(crible.Illisible) as refus:
        crible._verifier_sortie(str(cible), option)
    assert str(refus.value).startswith(f"{option} : ") and "refusée" in str(refus.value), refus.value


def test_la_garde_de_sortie_n_ecrit_rien_en_refusant_les_chemins_proteges():
    """Preuve du « sans pouvoir écrire » du test précédent : mêmes appels, dans un fils qui relève ses écritures."""
    code = ("import json\n"
            "refuse = []\n"
            "for option, chemin in json.loads(argv[0]):\n"
            "    try:\n"
            "        immo_crible._verifier_sortie(chemin, option)\n"
            "        refuse.append(False)\n"
            "    except immo_crible.Illisible:\n"
            "        refuse.append(True)\n"
            "resultat['refuse'] = refuse\n")
    audit = _audit_ecritures(code, json.dumps([[option, str(cible)] for option, cible in CIBLES_REELLES]))
    assert audit == {"resultat": {"refuse": [True] * len(CIBLES_REELLES)}, "ecrits": [], "mutations": []}


def test_cli_refuse_un_lien_physique_vers_pistes_json(tmp_path, monkeypatch):
    """Un lien physique vers `pistes.json` est refusé par la garde (identité sur disque, pas le nom).

    Sur un arbre factice dont `proteges()` est substitué, et par appel direct de la garde : la CLI n'est lancée vers aucun
    fichier réel.
    """
    import os
    racine = tmp_path / "depot"
    pistes = _arbre_factice(racine)
    monkeypatch.setattr(crible, "proteges", lambda: (pistes, racine / "immo-data" / "bruts"))
    lien = tmp_path / "lien.json"
    try:
        os.link(pistes, lien)
    except OSError:
        pytest.skip("lien physique impossible sur ce volume")
    avant = pistes.read_bytes()
    with pytest.raises(crible.Illisible, match="pistes.json"):
        crible._verifier_sortie(str(lien), "--pistes-out")
    assert pistes.read_bytes() == avant


def test_cli_refuse_d_ecraser_une_entree_ou_de_confondre_les_deux_sorties(tmp_path):
    memes_sorties = _args_demo(tmp_path)
    memes_sorties[memes_sorties.index("--pistes-out") + 1] = str(tmp_path / "scan.md")
    r = _lancer(*memes_sorties)
    assert r.returncode == 2 and "même fichier" in r.stderr
    copie_profil = tmp_path / "profil.json"
    copie_profil.write_bytes((FIXTURES / "profil_fictif.json").read_bytes())
    args = _args_demo(tmp_path)
    args[args.index("--profil") + 1] = str(copie_profil)
    args[args.index("--out") + 1] = str(copie_profil)
    avant = copie_profil.read_bytes()
    r = _lancer(*args)
    assert r.returncode == 2 and "entrée" in r.stderr
    assert copie_profil.read_bytes() == avant


def test_cli_ne_modifie_ni_pistes_json_ni_bruts(tmp_path):
    """Une exécution de la CLI n'écrit que sous `tmp_path` : ses deux sorties, et rien d'autre.

    `main` s'exécute dans un processus fils qui relève ses ouvertures en écriture et ses mutations de chemins (renommage,
    suppression, création...). Le test ne compare plus l'état de `bruts/`, où le sourcing peut écrire pendant la suite :
    seul compte ce que la CLI fait.
    """
    audit = _audit_ecritures("resultat['rc'] = immo_crible.main(argv)", *_args_demo(tmp_path))
    assert audit["resultat"] == {"rc": 0} and audit["mutations"] == []
    ecrits = {Path(p).resolve() for p in audit["ecrits"]}
    assert ecrits == {(tmp_path / "scan.md").resolve(), (tmp_path / "pistes.json").resolve()}
    assert PISTES_DEFAUT.resolve() not in ecrits and not any(BRUTS.resolve() in p.parents for p in ecrits)


def test_le_releve_des_ecritures_voit_ouvertures_et_mutations_mais_pas_les_lectures(tmp_path):
    """Témoin de l'instrument : sans lui, un relevé aveugle ferait passer les tests précédents à vide."""
    code = ("import os\n"
            "from pathlib import Path\n"
            "d = Path(argv[0])\n"
            "(d / 'a.txt').write_text('x')\n"                                    # Path.write_text
            "with open(d / 'b.txt', 'w') as f:\n"                                # open() en écriture
            "    f.write('x')\n"
            "with open(d / 'b.txt', 'a') as f:\n"                                # ajout
            "    f.write('y')\n"
            "os.close(os.open(d / 'c.txt', os.O_WRONLY | os.O_CREAT))\n"          # os.open, sans mode texte
            "os.replace(d / 'a.txt', d / 'a2.txt')\n"                            # renommage
            "os.remove(d / 'c.txt')\n"                                           # suppression
            "os.mkdir(d / 'sous')\n"                                             # création de dossier
            "(d / 'a2.txt').read_text()\n"                                       # lectures : non relevées
            "with open(d / 'b.txt') as f:\n"
            "    f.read()\n"
            "os.stat(d / 'b.txt')\n"
            "os.listdir(d)\n")
    audit = _audit_ecritures(code, str(tmp_path))
    assert sorted(Path(p).name for p in audit["ecrits"]) == ["a.txt", "b.txt", "c.txt"]
    assert sorted((evenement, len(chemins)) for evenement, chemins in audit["mutations"]) == [
        ("os.mkdir", 1), ("os.remove", 1), ("os.rename", 2)]


@pytest.mark.parametrize("contenu", ["pas du json", '{"ads": []}', "[1, 2]", "[{\"subject\": \"sans id\"}]"])
def test_cli_page_illisible_code_2_sans_rien_ecrire(tmp_path, contenu):
    page = tmp_path / "page.json"
    page.write_text(contenu, encoding="utf-8")
    args = _args_demo(tmp_path)
    args[args.index("--pages") + 1:args.index("--profil")] = [str(page)]
    r = _lancer(*args)
    assert r.returncode == 2 and "erreur" in r.stderr
    assert not (tmp_path / "scan.md").exists() and not (tmp_path / "pistes.json").exists()


def test_cli_page_absente_code_2(tmp_path):
    args = _args_demo(tmp_path)
    args[args.index("--pages") + 1] = str(tmp_path / "absente.json")
    assert _lancer(*args).returncode == 2


def test_cli_profil_du_dossier_de_donnees_par_defaut_et_aucune_ecriture_sans_out(tmp_path):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    (donnees / "profil.json").write_text(json.dumps(_gabarit_rempli(), ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--pages", str(FIXTURES / "demo_page_1.json"), "--date", "2026-10-07"],
                       capture_output=True, text=True, cwd=ROOT, env={**os.environ, "IMMO_DATA_DIR": str(donnees)})
    assert r.returncode == 0, r.stderr
    plafond = _gabarit_rempli()
    valeur = next(d for d in plafond["decisions"] if d["cle"] == "premier_achat_prix_max")["valeur"]
    assert f"{valeur:,}".replace(",", " ") in r.stdout and "profil" in r.stdout
    assert [p.name for p in tmp_path.iterdir()] == ["donnees"] and [p.name for p in donnees.iterdir()] == ["profil.json"]


def test_aucun_acces_reseau_dans_le_script():
    source = SCRIPT.read_text(encoding="utf-8")
    assert re.findall(r"requests|httpx|urllib|aiohttp|socket|http\.client|webbrowser|subprocess", source) == []


# --- défauts relevés en revue ---------------------------------------------------

@pytest.mark.parametrize("option, valeur", [
    ("--prix-max", "nan"), ("--prix-max", "inf"), ("--prix-max", "0"), ("--prix-max", "-5"),
    ("--surface-min", "nan"), ("--surface-min", "-1"), ("--surface-min", "0"),
    ("--top", "0"), ("--top", "-1"), ("--volume-affiche", "-3"),
    ("--date", "pas-une-date"), ("--date", "2026-13-40"), ("--date", "20261007"),
    ("--types", ""), ("--types", " , "), ("--types", "chateau"), ("--types", "１"),
])
def test_cli_refuse_un_argument_invalide_au_lieu_de_l_accepter_en_silence(tmp_path, option, valeur):
    r = _lancer(*_args_demo(tmp_path, option, valeur))
    assert r.returncode == 2, (option, valeur, r.stdout[-200:], r.stderr[-200:])
    assert "erreur" in r.stderr and "Traceback" not in r.stderr
    assert not (tmp_path / "scan.md").exists()


def test_plafond_du_profil_non_fini_ou_negatif_refuse():
    for valeur in ("nan", "inf", 0, -1, "abc", None):
        profil = copy.deepcopy(PROFIL)
        next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["valeur"] = valeur
        with pytest.raises(crible.Illisible, match="premier_achat_prix_max"):
            crible.regles_du_profil(profil)


def test_exception_du_profil_ecrite_en_entier_s_applique_comme_en_chaine():
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["exceptions"] = [
        {"annonce": 9000000012, "portee": "levée, identifiant écrit en entier", "date": "2026-01-02"}]
    res = crible.cribler([[_annonce(9000000012, prix=130000)]], profil=profil)
    assert [a["id"] for a in res["retenues"]] == ["9000000012"]
    assert any("exception du profil" in d for d in res["retenues"][0]["drapeaux"])


@pytest.mark.parametrize("exceptions", [None, "9000000012", ["9000000012"], [{"portee": "sans annonce"}], [3]])
def test_exceptions_malformees_du_profil_refusees_avec_un_message(exceptions):
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["exceptions"] = exceptions
    with pytest.raises(crible.Illisible, match="exception"):
        crible.regles_du_profil(profil)


def test_exception_sans_portee_ni_date_ne_plante_pas():
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["exceptions"] = [
        {"annonce": "9000000012"}]
    res = crible.cribler([[_annonce(9000000012, prix=130000)]], profil=profil)
    assert any("exception du profil" in d for d in res["retenues"][0]["drapeaux"])


def test_meme_identifiant_au_contenu_different_est_signale_pas_tu():
    a, b = _annonce(9000000300, prix=90000), _annonce(9000000300, prix=70000)
    pour_ordre = [_cribler([[a], [b]]), _cribler([[b], [a]])]
    for res in pour_ordre:
        assert res["comptes"]["doublons_entre_pages"] == 1
        assert [(c["id"], sorted(c["champs"])) for c in res["contenus_differents"]] == [("9000000300", ["prix"])]
        assert any("contenu différent" in d for d in res["retenues"][0]["drapeaux"])
    md = crible.rendre_markdown(pour_ordre[0], date="2026-10-07", source="s", pages=["p1.json", "p2.json"])
    assert "contenu différent" in md and "9000000300" in md.split("## Comptes")[1].split("## Seuils")[0]
    identique = _cribler([[a], [copy.deepcopy(a)]])
    assert identique["contenus_differents"] == []
    assert not any("contenu différent" in d for d in identique["retenues"][0]["drapeaux"])


def test_identifiant_normalise_en_entier_de_10_chiffres_sinon_refuse():
    flottant = _annonce(9000000301)
    flottant["list_id"] = 9000000301.0
    res = _cribler([[_annonce(9000000301), flottant]])
    assert res["comptes"]["uniques"] == 1 and res["retenues"][0]["id"] == "9000000301"
    assert res["retenues"][0]["url"].endswith("/9000000301")
    chaine = _annonce(9000000302)
    chaine["list_id"] = " 9000000302 "
    assert _cribler([[chaine]])["retenues"][0]["id"] == "9000000302"
    for mauvais in ("abc", -5, 1.5, True, 123, "12345678901", 0.0, [9000000303]):
        a = _annonce(9000000303)
        a["list_id"] = mauvais
        if mauvais in (0.0,):
            a["url"] = "https://www.leboncoin.fr/ad/ventes_immobilieres/9000000303"   # 0 = absent : repli sur l'URL
            assert _cribler([[a]])["retenues"][0]["id"] == "9000000303"
            continue
        with pytest.raises(crible.Illisible, match="identifiant"):
            _cribler([[a]])


def _malforme(**champs) -> dict:
    a = _annonce(9000000310)
    a.update(champs)
    return a


@pytest.mark.parametrize("a", [
    _malforme(price=[float("inf")]), _malforme(price=[float("nan")]), _malforme(price=[0.5]), _malforme(price=[-1]),
    _malforme(price="182000"), _malforme(price=[None]), _malforme(price={"a": 1}), _malforme(price=None),
    _malforme(location="Fictibourg"), _malforme(location=["Fictibourg"]), _malforme(location=None),
    _malforme(location={"city": None, "lat": "48.1", "lng": [2.1]}),
    _malforme(location={"city": "Fictibourg", "lat": float("nan"), "lng": float("nan")}),
    _malforme(attributes=5), _malforme(attributes={"square": 90}), _malforme(attributes=["square", None]),
    _malforme(attributes=[{"key": "square", "value": "92 m²"}]), _malforme(attributes=[{"key": "square", "value": "-5"}]),
    _malforme(attributes=[{"key": "square", "value": "1e999"}]), _malforme(subject=None), _malforme(body=None),
    _malforme(first_publication_date=None), _malforme(first_publication_date=20261007),
])
def test_entree_malformee_ne_plante_pas_elle_devient_une_absence_dite(a):
    res = _cribler([[a]], fiches=[FICHE], prix_max=500000)
    c = res["comptes"]
    assert c["uniques"] == 1 == c["ecartees"] + c["retenues"]
    md = crible.rendre_markdown(res, date="2026-10-07", source="s", pages=["p.json"])
    assert md.startswith("# Crible")
    crible.proposer_pistes(res, date="2026-10-07", source="s")


def test_commune_absente_ne_fait_pas_un_faux_doublon_ni_coordonnees_nan_un_faux_point():
    a = _annonce(9000000320, prix=90000, surface=90, source="address")
    b = _annonce(9000000321, prix=91000, surface=91, source="address")
    for x in (a, b):
        x["location"] = {"lat": float("nan"), "lng": float("nan"), "source": "address"}      # ni commune ni point
    assert _cribler([[a, b]])["doublons"] == []


def test_surface_illisible_est_dite_avec_sa_valeur_brute():
    a = _annonce(9000000322, surface=None, attrs={"square": "92 m²"})
    a["attributes"] = [t for t in a["attributes"] if t["key"] != "square"] + [{"key": "square", "value": "92 m²"}]
    r = _cribler([[a]], surface_min=25)["retenues"][0]
    assert any("surface absente ou illisible" in d and "92 m²" in d for d in r["drapeaux"])


@pytest.mark.parametrize("titre, attrs, motif", [
    ("Maison en viager 5 pièces 85 m²", {}, "viager probable"),
    ("Propriété en Viager 4 pièces 66 m²", {}, "viager probable"),
    ("Maison de ville, vente avec rente viagère", {}, "viager probable"),
    ("Maison de ville 90 m²", {"immo_sell_type": "viager"}, "viager probable"),
    ("Maison de ville 90 m², pas un viager", {}, "viager probable"),    # un titre qui parle de viager reste à lire
    ("Maison de ville 90 m²", {}, None),
    ("Maison de ville, pas de rente", {}, None),
])
def test_viager_probable_est_un_motif_d_ecart_comme_dans_le_scan_du_05_10(titre, attrs, motif):
    res = _cribler([[_annonce(9000000330, titre=titre, attrs=attrs)]])
    if motif:
        assert [e["motif"] for e in res["ecartees"]] == [motif] and res["retenues"] == []
        assert "bouquet" in res["ecartees"][0]["detail"]
    else:
        assert [a["id"] for a in res["retenues"]] == ["9000000330"]


def test_dpe_hors_classes_a_g_n_est_pas_affiche_comme_une_classe():
    a = _annonce(9000000340, attrs={"energy_rate": "n", "ges": "n"})
    r = _cribler([[a]])["retenues"][0]
    assert r["dpe"] is None
    md = crible.rendre_markdown(_cribler([[a]]), date="2026-10-07", source="s", pages=["p.json"])
    assert "| N |" not in md


def test_les_doublons_se_cherchent_par_commune_et_par_point_pas_par_paire_quelconque(monkeypatch):
    """Sur 1 200 annonces réparties en 60 communes, le nombre de comparaisons reste très inférieur à n²/2."""
    appels = []
    vrai = crible._proche
    monkeypatch.setattr(crible, "_proche", lambda x, y: appels.append(1) or vrai(x, y))
    annonces = [_annonce(9100000000 + i, prix=40000 + 10 * i, surface=40 + (i % 90), commune=f"Commune{i % 60}",
                         source="address") for i in range(1200)]
    for a in annonces:
        a["location"]["zipcode"] = "99001"
    _cribler([annonces], prix_max=10**9)
    assert 0 < len(appels) < 1200 * 1199 / 2 / 10


def test_plafond_explicite_est_dit_avec_ses_exceptions_non_appliquees():
    md = crible.rendre_markdown(_cribler([PAGE_1], prix_max=100000), date="2026-10-07", source="s", pages=["p.json"])
    assert "--prix-max" in md and "exceptions du profil non appliquées" in md


# --- deuxième tour de revue ----------------------------------------------------------

@pytest.mark.parametrize("modifier", [
    lambda f: f.__setitem__("loyers", ["x"]),                                     # AttributeError dans loyer_3r
    lambda f: f["loyers"].__setitem__("maison", ["x"]),
    lambda f: f["loyers"]["maison"].__setitem__("surface_type_m2", 0),            # ZeroDivisionError
    lambda f: f["loyers"]["maison"].__setitem__("surface_type_m2", "abc"),
    lambda f: f["loyers"]["appartement_t1_t2"].__setitem__("valeur_m2", "abc"),
    lambda f: f["loyers"]["appartement_t3_plus"].__setitem__("valeur_m2", -3),
])
def test_fiche_inutilisable_quelle_que_soit_sa_forme_donne_non_calcule_sans_trace(modifier):
    fiche = copy.deepcopy(FICHE)
    modifier(fiche)
    r = _cribler([[_annonce(9000000400)]], fiches=[fiche])["retenues"][0]
    assert r["rendement"] is None and r["rendement_texte"].startswith("non calculé : fiche inutilisable")


def test_cli_refuse_un_lien_physique_meme_vers_un_fichier_protege_d_un_autre_arbre(tmp_path):
    racine = tmp_path / "depot"
    pistes = _arbre_factice(racine)
    lien = tmp_path / "autre-nom.json"
    import os
    os.link(pistes, lien)                                         # même fichier, nom sans rapport avec pistes.json
    avant = pistes.read_bytes()
    r = _lancer(*_avec_sortie(tmp_path, "--pistes-out", lien))
    assert r.returncode == 2 and "lien physique" in r.stderr
    assert pistes.read_bytes() == avant
    seul = tmp_path / "scan-seul.md"                                # un fichier à un seul nom reste écrivable
    assert _lancer(*_avec_sortie(tmp_path, "--out", seul)).returncode == 0 and seul.exists()


def test_conseil_du_decile_garde_ses_virgules_et_les_milliers_prennent_une_espace():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    drapeau = next(d for a in res["retenues"] for d in a["drapeaux"] if "premier décile" in d)
    assert "lire la description (grange, hangar, hors commune)" in drapeau
    assert "  " not in drapeau
    gros = _cribler([[_annonce(9000000410 + i, prix=40000 + 100000 * i, surface=40) for i in range(10)]],
                    prix_max=10**9)
    drapeau = next(d for a in gros["retenues"] for d in a["drapeaux"] if "premier décile" in d)
    assert re.search(r"\(\d( \d{3})* < \d( \d{3})*\)", drapeau), drapeau            # « 1 000 < 4 500 », pas « 1,000 »


@pytest.mark.parametrize("titre", ["Maisons en viagers", "Viagers divers", "Maison, rente viagère mensuelle",
                                   "Maison viagère", "Maison en VIAGER"])
def test_viager_pluriel_et_viagere_sont_ecartes(titre):
    res = _cribler([[_annonce(9000000420, titre=titre)]])
    assert [e["motif"] for e in res["ecartees"]] == ["viager probable"]


def test_exception_du_profil_ecrite_en_flottant_entier_s_applique():
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["exceptions"] = [
        {"annonce": 9000000012.0, "portee": "flottant entier", "date": "2026-01-02"}]
    res = crible.cribler([[_annonce(9000000012, prix=130000)]], profil=profil)
    assert [a["id"] for a in res["retenues"]] == ["9000000012"]


def test_plafond_booleen_du_profil_refuse_et_commune_non_texte_est_une_absence():
    profil = copy.deepcopy(PROFIL)
    next(d for d in profil["decisions"] if d["cle"] == "premier_achat_prix_max")["valeur"] = True
    with pytest.raises(crible.Illisible, match="premier_achat_prix_max"):
        crible.regles_du_profil(profil)
    a = _annonce(9000000430)
    a["location"]["city"] = ["Fictibourg"]
    r = _cribler([[a]])["retenues"][0]
    assert r["commune"] == "?" and any("commune absente" in d for d in r["drapeaux"])


def test_contenu_different_voit_aussi_le_titre_le_type_de_vente_et_la_commune():
    a = _annonce(9000000440, titre="Maison de ville 90 m²", attrs={"immo_sell_type": "old"})
    b = _annonce(9000000440, titre="Maison en viager 90 m²", attrs={"immo_sell_type": "new"}, commune="Exempleville")
    champs = set(_cribler([[a], [b]])["contenus_differents"][0]["champs"])
    assert {"titre", "type_vente", "commune"} <= champs


def test_coordonnees_illisibles_et_commune_absente_sont_dites():
    a = _annonce(9000000450)
    a["location"]["lat"], a["location"]["lng"] = "48.1", "2.1"
    r = _cribler([[a]])["retenues"][0]
    assert any("coordonnées illisibles" in d for d in r["drapeaux"])
    sans = _annonce(9000000451)
    sans["location"] = {}
    assert any("commune absente" in d for d in _cribler([[sans]])["retenues"][0]["drapeaux"])


def test_type_autre_n_est_pas_presente_comme_un_immeuble_a_lots_connu():
    # Un type « Autre » titré « Garage » est désormais écarté (non résidentiel
    # probable), il ne parvient plus au rendement ; « Immeuble avec garage » nomme un logement et reste retenu.
    r = _cribler([[_annonce(9000000460, titre="Immeuble avec garage", type_code="5")]])["retenues"][0]
    assert "lots inconnus" in r["rendement_texte"] and "garage" in r["rendement_texte"]


def test_markdown_dit_les_exceptions_de_type_non_appliquees_et_les_ecartees_vides():
    md = crible.rendre_markdown(_cribler([PAGE_1], types={"1", "5"}), date="2026-10-07", source="s", pages=["p.json"])
    assert "--types explicite" in md and "exceptions du profil sur la cible non appliquées" in md
    vide = crible.rendre_markdown(_cribler([[_annonce(9000000470)]]), date="2026-10-07", source="s", pages=["p.json"])
    assert vide.split("## Écartées")[1].split("## Doublons")[0].strip() == "Aucune."


def test_la_piste_candidate_garde_l_alerte_du_decile_dans_sa_question():
    res = _cribler([PAGE_1, PAGE_2], fiches=[FICHE], surface_min=25)
    pistes = {p["id"]: p for p in _pistes(res, nb_candidats=15)}
    assert "premier décile" in pistes["9000000015"]["question"]
    assert "premier décile" not in pistes["9000000016"]["question"]


def test_libelle_du_type_sans_nom_connu_ne_dit_pas_code_inconnu():
    res = _cribler([[_annonce(9000000480, type_code="2")]])
    assert "code inconnu" not in res["ecartees"][0]["detail"] and "libellé non relevé" in res["ecartees"][0]["detail"]


# --- zone du profil (décision `zone`) ------------------------------------------------------------------------------

def _profil_avec_zone(communes: list, centre: str = "Fictibourg") -> dict:
    profil = copy.deepcopy(PROFIL)
    profil["decisions"].append({"cle": "zone", "valeur": {"commune_centre": centre, "code_insee": "99999",
                                                           "departement": "99", "communes": communes},
                                "unite": "zone", "date": "2026-01-01", "source": "fictif", "exceptions": []})
    return profil


def test_zone_du_profil_drapeau_hors_zone_sans_ecarter():
    pages = [[_annonce(9000000501, commune="Fictibourg"), _annonce(9000000502, commune="Ailleurs-sur-Rien")]]
    res = crible.cribler(pages, profil=_profil_avec_zone([{"nom": "Bourg-Exemple", "code_insee": "99998"}]))
    par = _par_id(res["retenues"])
    assert set(par) == {"9000000501", "9000000502"}
    assert not any("hors zone" in d for d in par["9000000501"]["drapeaux"])
    assert any("hors zone du profil" in d for d in par["9000000502"]["drapeaux"])
    assert res["zone"] == ["Fictibourg", "Bourg-Exemple"]
    md = crible.rendre_markdown(res, date="2026-10-08", source="s", pages=["p.json"])
    assert "zone du profil : Fictibourg, Bourg-Exemple" in md


def test_sans_decision_zone_aucun_drapeau_hors_zone():
    res = crible.cribler([[_annonce(9000000503, commune="Ailleurs-sur-Rien")]], profil=PROFIL)
    assert res["zone"] is None
    assert not any("hors zone" in d for d in res["retenues"][0]["drapeaux"])


def test_zone_sans_commune_refusee():
    with pytest.raises(crible.Illisible, match="zone"):
        crible.regles_du_profil(_profil_avec_zone([], centre=""))


def test_cli_profil_du_gabarit_non_rempli_code_2(tmp_path):
    r = _lancer("--pages", str(FIXTURES / "demo_page_1.json"), "--profil", str(PROFIL_GABARIT))
    assert r.returncode == 2 and "profil non rempli" in r.stderr and "Traceback" not in r.stderr
