#!/usr/bin/env python3
"""Shortlist dérivée des études /immo : `shortlist.md` §1 et §1 bis se régénèrent depuis le bloc de fin des études.

Chaque étude `immo-data/analyses/<slug>-AAAA-MM-JJ.md` porte, en dernière ligne non vide, un bloc
`<!-- immo:ligne {...} -->` (contrat : référence `negociation_livrable.md` du skill `immo`, §Bloc de fin). Sa clé
`ligne_shortlist` donne, en texte tel qu'il s'affiche, les 12 cellules de sa ligne de shortlist, plus une cellule optionnelle
`rang` (le contenu de la colonne « # » : `**1**`, `T3`...), sans colonne « Score » ; les clés
numériques servent au classement et au contrôle.

Ce script :
  - génère les deux tableaux de `shortlist.md` qui se trouvent entre `<!-- shortlist:derivee:debut -->` et
    `<!-- shortlist:derivee:fin -->` : le premier reçoit les blocs `complet` (§1), le second les blocs `rapide`
    (§1 bis), en 13 colonnes, classés par verdict (🟩 🟨 ⬜ 🟥 ⬛), puis cash-flow décroissant (null en dernier), puis
    slug. La colonne « # » reçoit la cellule `rang` du bloc, « - » si elle est absente. Titres, paragraphes et lignes vides de
    la zone sont conservés ;
    tout le reste du fichier est recopié octet pour octet, hors la ligne « Dernière mise à jour » ;
  - ne régénère rien tant qu'une étude n'a pas un bloc valide, ni tant que la zone porte une ligne qui ne cite aucune
    étude dotée d'un bloc : une ligne ne disparaît jamais en silence ;
  - contrôle (`--check`) chaque bloc contre son étude : bloc absent ou invalide, verdict du bloc différent de celui de
    l'en-tête (premier émoji de verdict des 20 premières lignes), valeur numérique du bloc introuvable dans le texte
    de l'étude (comparaison insensible au format : `87 436 €`, `87436`, `87,4 k€` ; sous une unité qui convient à la clé :
    un rendement ne se retrouve que dans un `%`).

Usage :
  python3 engine/scripts/immo_shortlist.py [--date AAAA-MM-JJ]       # régénère (date du jour par défaut)
  python3 engine/scripts/immo_shortlist.py --check                   # contrôle, n'écrit rien
  --dossier <chemin> : dossier contenant analyses/ et shortlist.md (défaut : $IMMO_DATA_DIR, sinon ./immo-data)

Un fichier `.md` de `analyses/` qui n'est ni une étude ni un fichier lié connu (-annexes, -visite, -one-pager, -projet-*) est
nommé en `NOTE` et ignoré.

Codes de sortie : 0 ; 1 (un bloc absent ou invalide, une ligne de la zone sans étude dotée d'un bloc ; avec --check, un écart
bloc / étude, ou `shortlist.md` qui diffère de ce qui serait généré, hors la ligne « Dernière mise à jour ») ; 2 (dossier
illisible, marqueurs absents ou mal posés, zone qui ne contient pas exactement deux tableaux, ligne « Dernière mise à jour »
absente, fins de ligne CRLF). En code 1 ou 2, rien n'est écrit.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
sys.path.insert(0, str(ROOT))

from src.immo.donnees import dossier_donnees  # noqa: E402

DEBUT = "<!-- shortlist:derivee:debut -->"
FIN = "<!-- shortlist:derivee:fin -->"
PREFIXE_BLOC = "<!-- immo:ligne "
SUFFIXE_BLOC = " -->"

VERDICTS = ("🟩", "🟨", "⬜", "🟥", "⬛")  # ordre de classement
MODES = ("complet", "rapide")  # §1 reçoit `complet`, §1 bis reçoit `rapide`
MONTAGES = ("sci_is", "lmnp_reel")
LIGNES_ENTETE = 20  # le verdict d'une étude se lit dans ses 20 premières lignes

# Les 12 cellules affichées de `ligne_shortlist`, dans l'ordre des colonnes (après « # »). La colonne « # » est la cellule
# optionnelle `rang` ; « - » quand elle est absente.
CLE_RANG = "rang"
RANG_ABSENT = "-"
CLES_CELLULES = ("quartier", "type", "surface", "prix", "eur_m2", "dpe", "rendement", "cf", "verdict", "prix_cible",
                 "annonces", "liens")
COLONNES = ("#", "Quartier", "Type", "Surface", "Prix FAI", "€/m² FAI", "DPE", "Rdt brut réal.", "CF réal. (montage)",
            "Verdict", "Prix cible", "ID LBC", "Analyse")
CLES_NUMERIQUES = ("surface_m2", "prix_fai", "prix_net_vendeur", "eur_m2_fai", "rendement_brut_realiste",
                   "cf_realiste_mensuel", "plafond", "cible", "ancrage")
# Unités sous lesquelles le texte de l'étude peut écrire la valeur d'une clé : un nombre n'en valide pas un autre d'une autre
# nature (un rendement ne se retrouve que dans un `%`, un prix pas dans un « 1 044 €/m² » ni dans un « 7 pièces » chiffré en m²).
PRIX = (None, "€", "k€")
UNITES_ADMISES = {
    "surface_m2": (None, "m²"),
    "prix_fai": PRIX, "prix_net_vendeur": PRIX, "plafond": PRIX, "cible": PRIX, "ancrage": PRIX,
    "eur_m2_fai": (None, "€", "€/m²"),
    "rendement_brut_realiste": ("%",),
    "cf_realiste_mensuel": (None, "€", "€/mois"),
}
VALEUR_MAX = 10 ** 12  # au-delà, ce n'est plus un prix ni une surface

CLES_BLOC = ("slug", "date", "mode", "verdict", "quartier", "type", "surface_m2", "prix_fai", "prix_net_vendeur",
             "eur_m2_fai", "dpe", "rendement_brut_realiste", "cf_realiste_mensuel", "montage", "plafond", "cible",
             "ancrage", "ids_annonces", "etapes_faites", "ligne_shortlist")

ETUDE_RE = re.compile(r"[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.md")  # une étude finit par sa date : ni -annexes, -visite, -projet-*...
DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_MAJ = re.compile(r"Dernière mise à jour : \*\*(\d{4}-\d{2}-\d{2}|AAAA-MM-JJ)\*\*\.")  # AAAA-MM-JJ : gabarit neuf
PIPE_NON_ECHAPPE = re.compile(r"(?<!\\)\|")
SEPARATEUR = re.compile(r"\|[\s:|-]+\|")  # |---|---|
CITE = re.compile(r"analyses/([a-z0-9-]+-\d{4}-\d{2}-\d{2})\.md")  # lien vers une étude
FICHIER_LIE_RE = re.compile(r".+-(annexes|visite|one-pager)\.md|.+-projet-.+\.md")  # fichiers liés à une étude
# Tout ce que `str.splitlines()` coupe en lignes : une cellule n'en contient aucun.
SAUT_DE_LIGNE = re.compile(r"[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")


class Structure(Exception):
    """`shortlist.md` ne se prête pas à la génération (code de sortie 2)."""


# --------------------------------------------------------------------------------------------
# Le bloc de fin : lecture, validation, sérialisation
# --------------------------------------------------------------------------------------------

def _sans_doublon(paires: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for cle, valeur in paires:
        if cle in out:
            raise ValueError(f"clé en double : {cle}")
        out[cle] = valeur
    return out


def extraire_bloc(texte: str) -> tuple[dict | None, list[str]]:
    """Bloc de la dernière ligne non vide de l'étude, ou (None, [raison])."""
    lignes = texte.split("\n")
    while lignes and not lignes[-1].strip():
        lignes.pop()
    derniere = lignes[-1].strip() if lignes else ""
    ouvertures = sum(1 for ligne in lignes if ligne.strip().startswith(PREFIXE_BLOC.rstrip()))
    if ouvertures > 1:
        return None, ["plusieurs blocs `immo:ligne` : un seul, en dernière ligne"]
    if not (derniere.startswith(PREFIXE_BLOC) and derniere.endswith(SUFFIXE_BLOC)):
        if ouvertures:
            return None, ["bloc `immo:ligne` présent mais pas en dernière ligne non vide, sur une seule ligne"]
        return None, ["bloc absent"]
    brut = derniere[len(PREFIXE_BLOC):-len(SUFFIXE_BLOC)]
    try:
        bloc = json.loads(brut, object_pairs_hook=_sans_doublon)
    except json.JSONDecodeError as e:
        return None, [f"bloc : JSON invalide ({e})"]
    except ValueError as e:
        return None, [f"bloc : {e}"]
    if not isinstance(bloc, dict):
        return None, ["bloc : le JSON n'est pas un objet"]
    return bloc, []


def serialiser_bloc(bloc: dict) -> str:
    """Le bloc sur une seule ligne. Un `-->` dans une cellule fermerait le commentaire : il est écrit `--\\u003e`."""
    corps = json.dumps(bloc, ensure_ascii=False).replace("-->", "--\\u003e")
    return f"{PREFIXE_BLOC}{corps}{SUFFIXE_BLOC}"


def _nombre(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) < VALEUR_MAX


def premier_verdict(texte: str) -> str | None:
    """Premier émoji de verdict (🟩 🟨 ⬜ 🟥 ⬛) du texte."""
    for c in texte:
        if c in VERDICTS:
            return c
    return None


def valider_bloc(bloc: dict, stem: str) -> list[str]:
    """Erreurs du bloc contre le contrat (liste vide si valide). Une clé inconnue ou manquante est refusée."""
    erreurs = [f"clé inconnue : {c}" for c in bloc if c not in CLES_BLOC]
    erreurs += [f"clé manquante : {c}" for c in CLES_BLOC if c not in bloc]
    if erreurs:
        return erreurs
    if bloc["slug"] != stem:
        erreurs.append(f"slug : {bloc['slug']!r} ≠ nom du fichier {stem!r}")
    d = bloc["date"]
    if not (isinstance(d, str) and DATE_ISO.fullmatch(d) and _date_valide(d)):
        erreurs.append(f"date : AAAA-MM-JJ attendu (reçu {d!r})")
    if bloc["mode"] not in MODES:
        erreurs.append(f"mode : {' ou '.join(MODES)} attendu (reçu {bloc['mode']!r})")
    if bloc["verdict"] not in VERDICTS:
        erreurs.append(f"verdict : un de {' '.join(VERDICTS)} attendu (reçu {bloc['verdict']!r})")
    if bloc["montage"] is not None and bloc["montage"] not in MONTAGES:
        erreurs.append(f"montage : {' ou '.join(MONTAGES)} ou null attendu (reçu {bloc['montage']!r})")
    for cle in CLES_NUMERIQUES:
        if bloc[cle] is not None and not _nombre(bloc[cle]):
            erreurs.append(f"{cle} : nombre ou null attendu (reçu {bloc[cle]!r})")
    dpe = bloc["dpe"]
    if dpe is not None and not (isinstance(dpe, str) and len(dpe) == 1 and dpe in "ABCDEFG"):
        erreurs.append(f"dpe : une lettre de A à G ou null attendu (reçu {dpe!r})")
    for cle in ("quartier", "type"):
        if bloc[cle] is not None and not isinstance(bloc[cle], str):
            erreurs.append(f"{cle} : texte ou null attendu (reçu {bloc[cle]!r})")
    for cle in ("ids_annonces", "etapes_faites"):
        v = bloc[cle]
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            erreurs.append(f"{cle} : liste de textes ou null attendu (reçu {v!r})")
    erreurs += _valider_cellules(bloc, stem)
    return erreurs


def _date_valide(d: str) -> bool:
    try:
        _date.fromisoformat(d)
    except ValueError:
        return False
    return True


def _valider_cellules(bloc: dict, stem: str) -> list[str]:
    cellules = bloc["ligne_shortlist"]
    if not isinstance(cellules, dict):
        return ["ligne_shortlist : objet attendu"]
    erreurs = [f"ligne_shortlist : clé inconnue : {c}" for c in cellules if c != CLE_RANG and c not in CLES_CELLULES]
    erreurs += [f"ligne_shortlist : clé manquante : {c}" for c in CLES_CELLULES if c not in cellules]
    if erreurs:
        return erreurs
    presentes = ((CLE_RANG,) if CLE_RANG in cellules else ()) + CLES_CELLULES
    for cle in presentes:
        v = cellules[cle]
        if not isinstance(v, str):
            erreurs.append(f"cellule {cle} : texte attendu (reçu {v!r})")
        elif SAUT_DE_LIGNE.search(v):
            erreurs.append(f"cellule {cle} : saut de ligne interdit")
        elif PIPE_NON_ECHAPPE.search(v):
            erreurs.append(f"cellule {cle} : barre verticale (pipe) non échappée, écrire \\|")
    if erreurs:
        return erreurs
    if f"analyses/{stem}.md" not in cellules["liens"]:
        erreurs.append(f"cellule liens : doit citer analyses/{stem}.md (la ligne d'une étude se retrouve par ce lien)")
    if premier_verdict(cellules["verdict"]) != bloc["verdict"]:
        erreurs.append(f"cellule verdict : premier émoji {premier_verdict(cellules['verdict'])!r} ≠ verdict du bloc "
                       f"{bloc['verdict']!r}")
    return erreurs


# --------------------------------------------------------------------------------------------
# Les études
# --------------------------------------------------------------------------------------------

def lister_etudes(analyses: Path) -> list[Path]:
    """Les études de `analyses/` : `<nom>-AAAA-MM-JJ.md`, hors -annexes, -visite, -one-pager et -projet-*."""
    return sorted(p for p in analyses.glob("*.md") if ETUDE_RE.fullmatch(p.name))


@dataclass
class Etude:
    stem: str
    chemin: Path
    corps: str  # texte de l'étude sans la ligne du bloc
    bloc: dict | None  # None si le bloc est absent ou invalide
    erreurs: list[str]


def sans_bloc(texte: str) -> str:
    """Le texte de l'étude sans sa dernière ligne non vide, si c'est un bloc : ses valeurs ne comptent pas comme texte."""
    lignes = texte.rstrip().split("\n")
    derniere = lignes[-1].strip()
    if derniere.startswith(PREFIXE_BLOC) and derniere.endswith(SUFFIXE_BLOC):
        return "\n".join(lignes[:-1])
    return texte


def charger_etude(chemin: Path) -> Etude:
    texte = chemin.read_bytes().decode("utf-8")
    bloc, erreurs = extraire_bloc(texte)
    if bloc is not None:
        erreurs = valider_bloc(bloc, chemin.stem)
        if erreurs:
            bloc = None
    return Etude(chemin.stem, chemin, sans_bloc(texte), bloc, erreurs)


def charger_etudes(analyses: Path) -> list[Etude]:
    return [charger_etude(p) for p in lister_etudes(analyses)]


# --------------------------------------------------------------------------------------------
# Les nombres d'un texte : jetons, et valeur du bloc retrouvée « quel que soit le format »
# --------------------------------------------------------------------------------------------

class Jeton(NamedTuple):
    valeur: Decimal
    decimales: int
    unite: str | None  # "€", "k€", "%", "m²", "€/mois", "€/m²"... ou None
    debut: int
    fin: int


# Pas collé à un mot, à un autre nombre, à un point, à une virgule, à une barre ni à un tiret (identifiants, dates
# AAAA-MM-JJ, intervalles) ; milliers par espace ; virgule ou point décimal.
NOMBRE = re.compile(r"(?<![\w.,/-])(?P<signe>[-+]?)(?P<entier>\d{1,3}(?: \d{3})+|\d+)(?:[.,](?P<dec>\d+))?(?!\d)"
                    r"(?: ?(?P<unite>[kK]€|€/\w+|€|%|m²))?")


TIRET_MOINS = re.compile(r"(?<![\w.,])\u2013(?=\d)")  # « –123 » (pas « 10–20 »)


def normaliser(texte: str) -> str:
    """Espaces insécables et fines en espace, signe moins typographique et tiret demi-cadratin collé à un nombre en « - »
    (remplacements un pour un : les positions du texte sont conservées)."""
    t = texte.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ").replace("\u2212", "-")
    return TIRET_MOINS.sub("-", t)


def jetons(texte: str) -> list[Jeton]:
    t = normaliser(texte)
    out = []
    for m in NOMBRE.finditer(t):
        dec = m.group("dec")
        valeur = Decimal(m.group("entier").replace(" ", "") + ("." + dec if dec else ""))
        if m.group("signe") == "-":
            valeur = -valeur
        unite = m.group("unite")
        out.append(Jeton(valeur, len(dec) if dec else 0, "k€" if unite == "K€" else unite, m.start(), m.end()))
    return out


def valeur_dans(valeur: float, js: list[Jeton], unites: tuple | None = None) -> bool:
    """La valeur et un nombre du texte sont le même, à la précision du plus grossier des deux. Un `%` se lit comme une
    fraction (5,67 % pour 0,0567) et un `k€` comme des milliers (87,4 k€ pour 87 436). Un jeton `%` ou `k€` sans décimale ne
    vaut que pour un nombre exact : « 5 % » valide 0,05 mais pas 0,0567, « 87 k€ » valide 87 000 mais pas 87 436. Une valeur à
    une décimale ou plus valide un jeton plus précis qu'elle (4,6 % pour 4,64 %) : c'est un arrondi de la cellule d'une
    shortlist. `unites` restreint les jetons à ceux écrits sous une de ces unités (`UNITES_ADMISES`) : sans cela, un « 0 » du
    texte validerait n'importe quel rendement (0,0567 s'arrondit à 0)."""
    try:
        v = Decimal(str(valeur))
    except InvalidOperation:
        return False
    for j in js:
        if unites is not None and j.unite not in unites:
            continue
        echelle = v * 100 if j.unite == "%" else v / 1000 if j.unite == "k€" else v
        if j.unite in ("%", "k€") and j.decimales < 1:
            if echelle == j.valeur:
                return True
            continue
        decimales_valeur = max(0, -echelle.normalize().as_tuple().exponent)
        try:
            if echelle.quantize(Decimal(1).scaleb(-j.decimales), rounding=ROUND_HALF_UP) == j.valeur:
                return True
            if 1 <= decimales_valeur < j.decimales and \
                    j.valeur.quantize(Decimal(1).scaleb(-decimales_valeur), rounding=ROUND_HALF_UP) == echelle:
                return True
        except InvalidOperation:  # hors de la précision de Decimal : la valeur ne peut pas être dans le texte
            continue
    return False


def valeur_dans_texte(valeur: float, texte: str, unites: tuple | None = None) -> bool:
    return valeur_dans(valeur, jetons(texte), unites)


# --------------------------------------------------------------------------------------------
# Contrôle de cohérence d'une étude
# --------------------------------------------------------------------------------------------

def verdict_entete(corps: str) -> tuple[str, int] | None:
    """(émoji, numéro de ligne) du premier émoji de verdict dans les 20 premières lignes, ou None."""
    for n, ligne in enumerate(corps.split("\n")[:LIGNES_ENTETE], 1):
        v = premier_verdict(ligne)
        if v:
            return v, n
    return None


def _affiche(v: float) -> str:
    return str(v)


def controler(etude: Etude) -> tuple[list[str], list[str]]:
    """(échecs, notes) d'une étude. Un bloc absent ou invalide est un échec."""
    if etude.bloc is None:
        return list(etude.erreurs), []
    bloc = etude.bloc
    echecs: list[str] = []
    notes: list[str] = []
    entete = verdict_entete(etude.corps)
    if entete is None:
        notes.append("verdict non lisible dans l'en-tête")
    elif entete[0] != bloc["verdict"]:
        echecs.append(f"verdict du bloc {bloc['verdict']} ≠ verdict de l'en-tête {entete[0]} (ligne {entete[1]})")
    js = jetons(etude.corps)
    for cle in CLES_NUMERIQUES:
        v = bloc[cle]
        if v is not None and not valeur_dans(v, js, UNITES_ADMISES[cle]):
            echecs.append(f"{cle} {_affiche(v)} absent du texte de l'étude")
    return echecs, notes


# --------------------------------------------------------------------------------------------
# Génération
# --------------------------------------------------------------------------------------------

def cle_classement(bloc: dict) -> tuple:
    cf = bloc["cf_realiste_mensuel"]
    return (VERDICTS.index(bloc["verdict"]), cf is None, -(cf or 0), bloc["slug"])


def trier(blocs: list[dict]) -> list[dict]:
    """Verdict (🟩 🟨 ⬜ 🟥 ⬛), puis cash-flow décroissant (null en dernier), puis slug."""
    return sorted(blocs, key=cle_classement)


def ligne_tableau(bloc: dict) -> str:
    cellules = bloc["ligne_shortlist"]
    return "| " + " | ".join([cellules.get(CLE_RANG, RANG_ABSENT)] + [cellules[c] for c in CLES_CELLULES]) + " |"


def tableau(blocs: list[dict]) -> list[str]:
    entete = "| " + " | ".join(COLONNES) + " |"
    return [entete, "|" + "---|" * len(COLONNES)] + [ligne_tableau(b) for b in trier(blocs)]


def regenerer(texte: str, blocs: list[dict], date_maj: str | None = None) -> str:
    """`shortlist.md` avec les deux tableaux de la zone réécrits (le premier avec les blocs `complet`, le second avec les
    `rapide`) et, si `date_maj` est donnée, la ligne « Dernière mise à jour ». Le reste est recopié tel quel."""
    if "\r" in texte:
        raise Structure("fins de ligne CR ou CRLF : le fichier doit être en LF (rien n'est réécrit)")
    lignes = texte.split("\n")
    debuts = [i for i, ligne in enumerate(lignes) if ligne.strip() == DEBUT]
    fins = [i for i, ligne in enumerate(lignes) if ligne.strip() == FIN]
    if len(debuts) != 1 or len(fins) != 1 or debuts[0] > fins[0]:
        raise Structure(f"marqueurs `{DEBUT}` puis `{FIN}` : exactement un de chaque, dans cet ordre "
                        f"(trouvés : {len(debuts)} et {len(fins)})")
    dates = [i for i, ligne in enumerate(lignes) if DATE_MAJ.fullmatch(ligne)]
    if len(dates) != 1:
        raise Structure("la ligne « Dernière mise à jour : **AAAA-MM-JJ**. » doit figurer exactement une fois "
                        f"(trouvée : {len(dates)})")
    if date_maj is not None:
        lignes[dates[0]] = f"Dernière mise à jour : **{date_maj}**."
    zone = lignes[debuts[0] + 1:fins[0]]
    par_mode = [[b for b in blocs if b["mode"] == mode] for mode in MODES]
    nouvelle: list[str] = []
    tableaux = 0
    i = 0
    while i < len(zone):
        if zone[i].startswith("|"):
            j = i
            while j < len(zone) and zone[j].startswith("|"):
                j += 1
            if tableaux < len(MODES):
                nouvelle += tableau(par_mode[tableaux])
            tableaux += 1
            i = j
        else:
            nouvelle.append(zone[i])
            i += 1
    if tableaux != len(MODES):
        raise Structure(f"la zone entre les marqueurs doit contenir exactement {len(MODES)} tableaux "
                        f"(§1 puis §1 bis) : {tableaux} trouvé(s)")
    return "\n".join(lignes[:debuts[0] + 1] + nouvelle + lignes[fins[0]:])


def lignes_orphelines(texte: str, slugs: set[str]) -> list[str]:
    """Lignes de données des tableaux de la zone qui ne citent aucune étude connue : la génération les ferait disparaître.
    À appeler sur un fichier dont `regenerer` a déjà validé la structure."""
    lignes = texte.split("\n")
    debut = next(i for i, ligne in enumerate(lignes) if ligne.strip() == DEBUT)
    fin = next(i for i, ligne in enumerate(lignes) if ligne.strip() == FIN)
    return [ligne for ligne in lignes[debut + 1:fin]
            if ligne.startswith("|") and not SEPARATEUR.fullmatch(ligne.strip()) and not ligne.startswith("| # |")
            and not any(c in slugs for c in CITE.findall(ligne))]


def fichiers_inconnus(analyses: Path) -> list[str]:
    """Fichiers `.md` de `analyses/` qui ne sont ni une étude ni un fichier lié connu : ils sont ignorés, sans bruit."""
    return sorted(p.name for p in analyses.glob("*.md") if not ETUDE_RE.fullmatch(p.name) and not FICHIER_LIE_RE.fullmatch(p.name))


# --------------------------------------------------------------------------------------------
# Ligne de commande
# --------------------------------------------------------------------------------------------

def _date_iso(valeur: str) -> str:
    if not (DATE_ISO.fullmatch(valeur) and _date_valide(valeur)):
        raise argparse.ArgumentTypeError(f"AAAA-MM-JJ attendu (reçu {valeur!r})")
    return valeur


def _rapport_check(etudes: list[Etude]) -> tuple[int, int]:
    nb_echecs = nb_notes = 0
    for etude in etudes:
        echecs, notes = controler(etude)
        if not echecs:
            print(f"OK {etude.stem}")
        for e in echecs:
            print(f"ÉCHEC {etude.stem} : {e}")
        for n in notes:
            print(f"NOTE {etude.stem} : {n}")
        nb_echecs += bool(echecs)
        nb_notes += len(notes)
    return nb_echecs, nb_notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shortlist dérivée des études /immo (régénération et contrôle).")
    parser.add_argument("--check", action="store_true", help="contrôle la cohérence blocs / études / shortlist.md, n'écrit rien")
    parser.add_argument("--date", type=_date_iso, help="date de « Dernière mise à jour » (AAAA-MM-JJ ; défaut : aujourd'hui)")
    parser.add_argument("--dossier", type=Path, default=None,
                        help="dossier contenant analyses/ et shortlist.md (défaut : $IMMO_DATA_DIR ou ./immo-data)")
    args = parser.parse_args(argv)
    args.dossier = args.dossier or dossier_donnees()

    analyses, shortlist = args.dossier / "analyses", args.dossier / "shortlist.md"
    if not shortlist.is_file() or (analyses.exists() and not analyses.is_dir()):
        print(f"erreur : {shortlist} (fichier) introuvable, ou {analyses} n'est pas un dossier (copier "
              "templates/shortlist.md dans le dossier de données)", file=sys.stderr)
        return 2
    texte = shortlist.read_bytes().decode("utf-8")
    try:
        regenerer(texte, [], None)  # la structure d'abord : sans elle, rien ne s'écrit
    except Structure as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2

    etudes = charger_etudes(analyses) if analyses.is_dir() else []
    if not etudes:
        if lignes_orphelines(texte, set()):
            print(f"erreur : aucune étude (<nom>-AAAA-MM-JJ.md) dans {analyses}, mais la zone dérivée porte des lignes : "
                  "rien n'est écrit (les tableaux ne sont pas vidés)", file=sys.stderr)
            return 1
        print(f"shortlist.md : aucune étude encore dans {analyses} ; tableaux vides, rien à générer")
        return 0
    invalides = [e for e in etudes if e.bloc is None]
    for nom in fichiers_inconnus(analyses):
        print(f"NOTE {nom} : ni une étude (<nom>-AAAA-MM-JJ.md) ni un fichier lié (-annexes, -visite, -one-pager, -projet-*) : ignoré",
              file=sys.stderr if not args.check else sys.stdout)

    if args.check:
        nb_echecs, nb_notes = _rapport_check(etudes)
        etat = "non comparée (bloc absent ou invalide)"
        ecart = False
        if not invalides:
            attendu = regenerer(texte, [e.bloc for e in etudes], None)  # la date du fichier est gardée : elle n'est pas comparée
            if attendu == texte:
                etat = "conforme à ce qui serait généré"
            else:
                etat = "diffère de ce qui serait généré (python3 engine/scripts/immo_shortlist.py)"
                ecart = True
                diff = list(difflib.unified_diff(texte.split("\n"), attendu.split("\n"), "shortlist.md (fichier)",
                                                 "shortlist.md (généré)", lineterm="", n=0))
                print("\n".join(diff[:40]) + ("\n[...]" if len(diff) > 40 else ""))
        print(f"bilan : {len(etudes)} étude(s), {nb_echecs} en échec, {nb_notes} note(s) ; shortlist.md {etat}")
        return 1 if nb_echecs or ecart else 0

    if invalides:
        for e in invalides:
            for erreur in e.erreurs:
                print(f"{e.stem} : {erreur}", file=sys.stderr)
        print(f"erreur : {len(invalides)} étude(s) sans bloc valide ; rien n'est écrit (une ligne ne doit pas disparaître "
              "en silence). Poser le bloc : voir skills/immo/references/negociation_livrable.md, § Bloc de fin", file=sys.stderr)
        return 1
    orphelines = lignes_orphelines(texte, {e.stem for e in etudes})
    if orphelines:
        for ligne in orphelines:
            cites = ", ".join(CITE.findall(ligne)) or "aucun lien vers une étude"
            print(f"ligne de la zone sans étude ({cites}) : {ligne[:100]}", file=sys.stderr)
        print(f"erreur : {len(orphelines)} ligne(s) de la zone ne citent aucune étude dotée d'un bloc ; la génération les ferait "
              "disparaître. Les retirer à la main (ou rétablir l'étude) avant de régénérer ; rien n'est écrit.", file=sys.stderr)
        return 1
    blocs = [e.bloc for e in etudes]
    date_maj = args.date or _date.today().isoformat()
    nouveau = regenerer(texte, blocs, date_maj)
    if nouveau != texte:
        shortlist.write_bytes(nouveau.encode("utf-8"))
    nb = [sum(1 for b in blocs if b["mode"] == mode) for mode in MODES]
    print(f"shortlist.md régénérée : §1 {nb[0]} ligne(s) (complet), §1 bis {nb[1]} ligne(s) (rapide) ; "
          f"dernière mise à jour {date_maj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
