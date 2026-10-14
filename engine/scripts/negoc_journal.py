#!/usr/bin/env python3
"""Journal des négociations menées avec `/negoc` : un JSON par négociation, contrôlé par script.

Un journal = `immo-data/negociations/<slug>.json` (schéma `negoc-journal/1`) : repères (ouverture, cible, limite),
coups datés, issue et leçons. Deux terrains : achat immobilier (`immo_achat`) et devis d'artisans (`artisan`).
Les tiers y sont désignés par leur RÔLE, jamais par leur nom. Bibliothèque standard seule.
Référence : `skills/negoc/references/journal.md`.

Usage (depuis le skill, `${CLAUDE_PLUGIN_ROOT}` substitué) :
  python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" nouveau --slug S --terrain T --role R --objet "..." [...]
  python3 ".../negoc_journal.py" coup --fichier CHEMIN --de nous|eux --type TYPE --canal CANAL --resume "..." [...]
  python3 ".../negoc_journal.py" clore --fichier CHEMIN --statut S [--date AAAA-MM-JJ] [--montant-final X] [...]
  python3 ".../negoc_journal.py" check [--fichier CHEMIN]
  python3 ".../negoc_journal.py" bilan [--terrain T] [--detail] [--json]
Option commune : --donnees DIR (dossier de données ; défaut : $IMMO_DATA_DIR, sinon `immo-data/` du répertoire
courant). Les journaux vivent dans `<donnees>/negociations/`. Un CHEMIN relatif se lit depuis le répertoire courant.

Codes de sortie : 0 ; 1 (check : au moins un ÉCHEC ; nouveau, coup, clore : refus, rien n'est écrit) ;
2 (usage, fichier introuvable ou hors du dossier des journaux, entrée-sortie).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

MOTEUR = Path(__file__).resolve().parent.parent  # engine/
if str(MOTEUR) not in sys.path:
    sys.path.insert(0, str(MOTEUR))

SCHEMA = "negoc-journal/1"
DOSSIER_JOURNAUX = "negociations"  # sous le dossier de données

TERRAINS = ("immo_achat", "artisan")
# Sur les deux terrains, on achète : on veut moins (`baisse`). Le mécanisme `hausse` reste pour un rôle vendeur.
ROLES_BAISSE = ("acheteur", "client")
ROLES_HAUSSE: tuple[str, ...] = ()
ROLES = ROLES_BAISSE + ROLES_HAUSSE
TYPES_CONTREPARTIE = ("particulier", "agence", "entreprise", "artisan", "autre")
SIGNAUX = ("annonce_ancienne", "baisse_de_prix", "bien_vide", "succession", "vente_contrainte", "mutation",
           "separation", "double_charge", "multi_agences", "mandat_exclusif", "travaux_lourds", "dpe_f_g",
           "zone_inondable", "concurrence_annoncee", "delai_impose", "autre")
UNITES = ("eur", "eur_ht", "eur_ttc")
DE = ("nous", "eux")
CANAUX = ("ecrit", "telephone", "visite", "rendez_vous", "plateforme")
TYPES_COUP = ("offre", "contre_offre", "concession", "demande", "information", "question", "refus", "acceptation",
              "relance", "ultimatum", "retrait", "silence")
TACTIQUES = ("ancrage_precis", "ancrage_rond", "fourchette", "offres_multiples", "justification_contrainte",
             "justification_pieces", "justification_marche", "cadrage_pertes", "question_ouverte",
             "question_presupposee", "fiche_jointe", "silence", "date_limite", "concession_contre_contrepartie",
             "concession_seche", "alternative_reelle", "recadrage_legal", "prise_de_contact", "etiquetage", "autre")
STATUTS = ("en_cours", "conclu", "rompu_par_nous", "rompu_par_eux", "perdu", "abandonne")
SANS_ACCORD = ("rompu_par_nous", "rompu_par_eux", "perdu", "abandonne")

CLES = ("schema", "slug", "terrain", "objet", "notre_role", "contrepartie", "devise", "reperes",
        "batna", "coups", "issue")
CLES_CONTREPARTIE = ("type", "intermediaire", "signaux")
CLES_REPERES = ("prix_affiche", "ouverture", "cible", "limite", "unite", "source")
CLES_COUP = ("n", "date", "de", "canal", "type", "montant", "conditions", "leviers", "tactiques", "resume", "source")
CLES_ISSUE = ("statut", "date", "montant_final", "conditions_finales", "lecons", "retex_integre")

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,80}")
LEVIER = re.compile(r"[a-z0-9_]{1,40}")
DATE_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Contrôle 6 : motifs du contrat, appliqués aux VALEURS texte (les clés ne sont pas lues).
PII = (
    ("courriel", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("téléphone", re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:(?:[\s-]?[A-Z0-9]{4}){3,7}|[A-Z0-9]{11,30})\b", re.IGNORECASE)),
    ("civilité et nom", re.compile(r"\b(?:M\.|Mme|Mlle|Madame|Monsieur|Maître)\s+[A-ZÉÈÀÂÎÔÛ][a-zéèêëàâîïôöûüç-]+")),
)

AVERTISSEMENT = "⚠ moins de 5 négociations conclues : descriptif, aucune conclusion"
SEUIL_CONCLUS = 5

_ABSENT = object()


def aujourdhui() -> date:
    return date.today()


def sens_du_role(role) -> str | None:
    """`baisse` (on veut moins) ou `hausse` (on veut plus) ; None si le rôle est inconnu."""
    if role in ROLES_BAISSE:
        return "baisse"
    if role in ROLES_HAUSSE:
        return "hausse"
    return None


# --------------------------------------------------------------------------------------- chemins et lecture

def donnees_par_defaut() -> Path:
    """`$IMMO_DATA_DIR` s'il est posé, sinon `immo-data/` du répertoire courant."""
    env = os.environ.get("IMMO_DATA_DIR")
    return Path(env) if env else Path.cwd() / "immo-data"


def dossier_journaux(donnees: Path) -> Path:
    return donnees / DOSSIER_JOURNAUX


def dans_le_dossier(chemin: Path, donnees: Path) -> bool:
    """True si `chemin` vit directement dans `<donnees>/negociations/` (le parent seul est résolu)."""
    return chemin.parent.resolve() == dossier_journaux(donnees).resolve()


def relatif(chemin: Path) -> str:
    """Chemin affiché : relatif au répertoire courant s'il y est, sinon absolu (réutilisable tel quel en --fichier)."""
    complet = chemin.parent.resolve() / chemin.name
    try:
        return complet.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(complet)


def journaux(donnees: Path) -> list[Path]:
    dossier = dossier_journaux(donnees)
    return sorted(dossier.glob("*.json")) if dossier.is_dir() else []


def _ecrire(chemin: Path, obj: dict) -> None:
    """Écriture atomique : fichier temporaire dans le même dossier, puis `os.replace`."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=f".{chemin.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------------------------ validateurs de schéma

def _joint(base: str, cle: str) -> str:
    return f"{base}.{cle}" if base else cle


def _cles(obj, attendues, base: str, echecs: list) -> bool:
    if not isinstance(obj, dict):
        echecs.append(f"{base or 'journal'} : objet attendu")
        return False
    echecs += [f"clé manquante : {_joint(base, k)}" for k in attendues if k not in obj]
    echecs += [f"clé inconnue : {_joint(base, k)}" for k in obj if k not in attendues]
    return True


def _est_nombre(v) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v) and v >= 0
    except OverflowError:
        return False


def _iso(v) -> date | None:
    if isinstance(v, str) and DATE_ISO.fullmatch(v):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return None


def _texte(v, chemin, echecs, maxi, mini=0, nullable=False) -> None:
    if v is _ABSENT or (nullable and v is None):
        return
    if not isinstance(v, str):
        echecs.append(f"{chemin} : texte attendu{' ou null' if nullable else ''}")
    elif not mini <= len(v) <= maxi:
        echecs.append(f"{chemin} : longueur {len(v)} hors de {mini} à {maxi}")


def _nombre(v, chemin, echecs) -> None:
    if v is not _ABSENT and v is not None and not _est_nombre(v):
        echecs.append(f"{chemin} : nombre positif ou nul attendu, ou null")


def _date(v, chemin, echecs, nullable=False) -> None:
    if v is _ABSENT or (nullable and v is None):
        return
    if _iso(v) is None:
        echecs.append(f"{chemin} : date AAAA-MM-JJ attendue")


def _enum(v, chemin, valeurs, echecs) -> bool:
    if v is _ABSENT:
        return False
    if not isinstance(v, str) or v not in valeurs:
        echecs.append(f"{chemin} : valeur hors enum ({repr(v)[:40]})")
        return False
    return True


def _liste(v, chemin, echecs) -> bool:
    if v is _ABSENT:
        return False
    if not isinstance(v, list):
        echecs.append(f"{chemin} : liste attendue")
        return False
    return True


def _liste_enum(v, chemin, valeurs, echecs) -> None:
    if _liste(v, chemin, echecs):
        vus = set()
        for i, x in enumerate(v):
            if _enum(x, f"{chemin}[{i}]", valeurs, echecs):
                if x in vus:
                    echecs.append(f"{chemin}[{i}] : doublon ({x})")
                vus.add(x)


def _liste_textes(v, chemin, maxi, echecs) -> None:
    if _liste(v, chemin, echecs):
        for i, x in enumerate(v):
            _texte(x, f"{chemin}[{i}]", echecs, maxi)


def _liste_leviers(v, chemin, echecs) -> None:
    if _liste(v, chemin, echecs):
        vus = set()
        for i, x in enumerate(v):
            if not isinstance(x, str) or not LEVIER.fullmatch(x):
                echecs.append(f"{chemin}[{i}] : motif invalide (^[a-z0-9_]{{1,40}}$)")
            elif x in vus:
                echecs.append(f"{chemin}[{i}] : doublon ({x})")
            else:
                vus.add(x)


def _coup(c, i: int, echecs: list) -> None:
    base = f"coups[{i}]"
    if not _cles(c, CLES_COUP, base, echecs):
        return
    n = c.get("n", _ABSENT)
    if n is not _ABSENT:
        if isinstance(n, bool) or not isinstance(n, int):
            echecs.append(f"{base}.n : entier attendu")
        elif n != i + 1:
            echecs.append(f"{base}.n : {n} au lieu de {i + 1} (numéros consécutifs depuis 1)")
    _date(c.get("date", _ABSENT), f"{base}.date", echecs)
    _enum(c.get("de", _ABSENT), f"{base}.de", DE, echecs)
    _enum(c.get("canal", _ABSENT), f"{base}.canal", CANAUX, echecs)
    _enum(c.get("type", _ABSENT), f"{base}.type", TYPES_COUP, echecs)
    _nombre(c.get("montant", _ABSENT), f"{base}.montant", echecs)
    _liste_textes(c.get("conditions", _ABSENT), f"{base}.conditions", 120, echecs)
    _liste_leviers(c.get("leviers", _ABSENT), f"{base}.leviers", echecs)
    _liste_enum(c.get("tactiques", _ABSENT), f"{base}.tactiques", TACTIQUES, echecs)
    _texte(c.get("resume", _ABSENT), f"{base}.resume", echecs, 280, mini=1)
    _texte(c.get("source", _ABSENT), f"{base}.source", echecs, 200, nullable=True)


def _structure(j, echecs: list) -> None:
    """Contrôle 1 : clés, types, enums, longueurs, motifs, doublons."""
    if not _cles(j, CLES, "", echecs):
        return
    if "schema" in j and j["schema"] != SCHEMA:
        echecs.append(f"schema : valeur attendue {SCHEMA}")
    if "devise" in j and j["devise"] != "EUR":
        echecs.append("devise : valeur attendue EUR")
    if "slug" in j and (not isinstance(j["slug"], str) or not SLUG.fullmatch(j["slug"])):
        echecs.append("slug : motif invalide (^[a-z0-9][a-z0-9-]{2,80}$)")
    _enum(j.get("terrain", _ABSENT), "terrain", TERRAINS, echecs)
    _texte(j.get("objet", _ABSENT), "objet", echecs, 120, mini=1)
    _enum(j.get("notre_role", _ABSENT), "notre_role", ROLES, echecs)
    _texte(j.get("batna", _ABSENT), "batna", echecs, 280, nullable=True)

    cp = j.get("contrepartie", _ABSENT)
    if cp is not _ABSENT and _cles(cp, CLES_CONTREPARTIE, "contrepartie", echecs):
        _enum(cp.get("type", _ABSENT), "contrepartie.type", TYPES_CONTREPARTIE, echecs)
        _texte(cp.get("intermediaire", _ABSENT), "contrepartie.intermediaire", echecs, 120, nullable=True)
        _liste_enum(cp.get("signaux", _ABSENT), "contrepartie.signaux", SIGNAUX, echecs)

    r = j.get("reperes", _ABSENT)
    if r is not _ABSENT and _cles(r, CLES_REPERES, "reperes", echecs):
        for k in ("prix_affiche", "ouverture", "cible", "limite"):
            _nombre(r.get(k, _ABSENT), f"reperes.{k}", echecs)
        _enum(r.get("unite", _ABSENT), "reperes.unite", UNITES, echecs)
        _texte(r.get("source", _ABSENT), "reperes.source", echecs, 200, nullable=True)

    coups = j.get("coups", _ABSENT)
    if _liste(coups, "coups", echecs):
        for i, c in enumerate(coups):
            _coup(c, i, echecs)

    iss = j.get("issue", _ABSENT)
    if iss is not _ABSENT and _cles(iss, CLES_ISSUE, "issue", echecs):
        _enum(iss.get("statut", _ABSENT), "issue.statut", STATUTS, echecs)
        _date(iss.get("date", _ABSENT), "issue.date", echecs, nullable=True)
        _nombre(iss.get("montant_final", _ABSENT), "issue.montant_final", echecs)
        _liste_textes(iss.get("conditions_finales", _ABSENT), "issue.conditions_finales", 120, echecs)
        _liste_textes(iss.get("lecons", _ABSENT), "issue.lecons", 280, echecs)
        if "retex_integre" in iss and not isinstance(iss["retex_integre"], bool):
            echecs.append("issue.retex_integre : booléen attendu")


# ------------------------------------------------------------------------------------ contrôles de cohérence

def _identite(j: dict, chemin: Path, echecs: list) -> None:
    """Contrôle 2 : slug = nom du fichier."""
    slug = j.get("slug")
    if isinstance(slug, str) and slug != chemin.stem:
        echecs.append(f"slug : {slug} différent du nom du fichier ({chemin.stem})")


def _dates_des_coups(j: dict, echecs: list) -> None:
    """Contrôle 3 (suite) : dates non décroissantes d'un coup au suivant."""
    coups = j.get("coups")
    if not isinstance(coups, list):
        return
    precedente = None
    for i, c in enumerate(coups):
        d = _iso(c.get("date")) if isinstance(c, dict) else None
        if d is None:
            continue
        if precedente is not None and d < precedente:
            echecs.append(f"coups[{i}].date : antérieure à celle du coup précédent")
        precedente = d


def _au_dela(sens: str, valeur, limite) -> bool:
    return valeur > limite if sens == "baisse" else valeur < limite


def _reperes(j: dict, echecs: list, notes: list) -> None:
    """Contrôle 4 : ouverture et cible du bon côté de la limite ; NOTE pour un coup nôtre au-delà de la limite."""
    sens = sens_du_role(j.get("notre_role"))
    r = j.get("reperes")
    if sens is None or not isinstance(r, dict) or not _est_nombre(r.get("limite")):
        return
    limite = r["limite"]
    for nom in ("ouverture", "cible"):
        if _est_nombre(r.get(nom)) and _au_dela(sens, r[nom], limite):
            echecs.append(f"reperes.{nom} : {r[nom]} au-delà de reperes.limite {limite} (sens {sens})")
    coups = j.get("coups")
    for i, c in enumerate(coups if isinstance(coups, list) else []):
        if (isinstance(c, dict) and c.get("de") == "nous" and _est_nombre(c.get("montant"))
                and _au_dela(sens, c["montant"], limite)):
            n = c["n"] if isinstance(c.get("n"), int) and not isinstance(c["n"], bool) else i + 1
            notes.append(f"coup {n} au-delà de la limite : décision à tracer")


def _issue(j: dict, echecs: list) -> None:
    """Contrôle 5 : cohérence statut, date, montant final et retour d'expérience."""
    iss = j.get("issue")
    if not isinstance(iss, dict) or iss.get("statut") not in STATUTS:
        return
    statut, d, montant = iss["statut"], iss.get("date"), iss.get("montant_final")
    if statut == "en_cours":
        if d is not None:
            echecs.append("issue.date : doit être null tant que le statut est en_cours")
        if montant is not None:
            echecs.append("issue.montant_final : doit être null tant que le statut est en_cours")
        if iss.get("retex_integre") is True:
            echecs.append("issue.retex_integre : doit être faux tant que le statut est en_cours")
    else:
        if d is None:
            echecs.append(f"issue.date : requise pour le statut {statut}")
        if statut == "conclu" and montant is None:
            echecs.append("issue.montant_final : requis pour le statut conclu")
        if iss.get("retex_integre") is True and not iss.get("lecons"):
            echecs.append("issue.retex_integre : vrai exige des leçons")
    coups = j.get("coups")
    dates = [_iso(c.get("date")) for c in coups if isinstance(c, dict)] if isinstance(coups, list) else []
    dates = [x for x in dates if x]
    if _iso(d) and dates and _iso(d) < max(dates):
        echecs.append("issue.date : antérieure au dernier coup")


def _textes(noeud, base: str = ""):
    """Chemin et valeur de chaque texte du journal ; les clés ne sont jamais lues."""
    if isinstance(noeud, str):
        yield base, noeud
    elif isinstance(noeud, dict):
        for k, v in noeud.items():
            yield from _textes(v, _joint(base, str(k)))
    elif isinstance(noeud, list):
        for i, v in enumerate(noeud):
            yield from _textes(v, f"{base}[{i}]")


def _donnees_personnelles(j: dict, echecs: list) -> None:
    """Contrôle 6."""
    for chemin, valeur in _textes(j):
        for type_, motif in PII:
            if motif.search(valeur):
                echecs.append(f"donnée personnelle probable ({type_}) dans {chemin}")


def controler(j, chemin: Path) -> tuple[list[str], list[str]]:
    """(ÉCHECS, NOTES) d'un journal déjà chargé ; `chemin` est celui où il vit (ou vivra)."""
    echecs: list[str] = []
    notes: list[str] = []
    _structure(j, echecs)
    if isinstance(j, dict):
        _identite(j, chemin, echecs)
        _dates_des_coups(j, echecs)
        _reperes(j, echecs, notes)
        _issue(j, echecs)
        _donnees_personnelles(j, echecs)
    return echecs, notes


def controler_fichier(chemin: Path) -> tuple[list[str], list[str], object]:
    """Lit puis contrôle ; lève OSError si le fichier ne se lit pas, ÉCHEC si le JSON est illisible."""
    try:
        j = json.loads(chemin.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"JSON illisible ({exc})"], [], None
    echecs, notes = controler(j, chemin)
    return echecs, notes, j


# ------------------------------------------------------------------------------------------------ commandes

class Refus(Exception):
    """Refus d'écriture : `RESULT=NEGOC_JOURNAL_REFUS(<raison>)`, rien n'est écrit."""

    def __init__(self, raison: str, code: int = 1, lignes=()):
        super().__init__(raison)
        self.raison, self.code, self.lignes = raison, code, list(lignes)


def _donnees(a) -> Path:
    return Path(a.donnees) if a.donnees else donnees_par_defaut()


def _chemin(arg: str) -> Path:
    p = Path(arg)
    return p if p.is_absolute() else Path.cwd() / p


def _refus_controle(echecs, chemin: Path, prefixe: str = "") -> Refus:
    rel = relatif(chemin)
    return Refus(prefixe + echecs[0], 1, [f"ÉCHEC {rel} : {e}" for e in echecs])


def _publier(obj: dict, chemin: Path, notes) -> int:
    try:
        _ecrire(chemin, obj)
    except OSError as exc:
        raise Refus(f"écriture impossible ({exc.strerror or exc})", 2) from exc
    rel = relatif(chemin)
    for n in notes:
        print(f"NOTE {rel} : {n}")
    print(f"RESULT=NEGOC_JOURNAL_ECRIT {rel}")
    return 0


def _ouvrir(arg: str, donnees: Path) -> tuple[Path, object]:
    chemin = _chemin(arg)
    if not dans_le_dossier(chemin, donnees):
        raise Refus(f"fichier hors du dossier des journaux ({dossier_journaux(donnees)})", 2)
    try:
        return chemin, json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refus("fichier introuvable", 2) from None
    except OSError as exc:
        raise Refus(f"lecture impossible ({exc.strerror or exc})", 2) from exc
    except ValueError:
        raise Refus("journal illisible (JSON invalide)") from None


def _ouvrir_valide(arg: str, donnees: Path) -> tuple[Path, dict, list[str]]:
    """Journal existant, déjà conforme : sinon refus (on ne modifie pas un journal cassé)."""
    chemin, j = _ouvrir(arg, donnees)
    echecs, notes = controler(j, chemin)
    if echecs:
        raise _refus_controle(echecs, chemin, "journal existant invalide : ")
    return chemin, j, notes


def cmd_nouveau(a) -> int:
    donnees = _donnees(a)
    if not SLUG.fullmatch(a.slug):
        raise Refus(f"slug invalide ({a.slug})")
    chemin = dossier_journaux(donnees) / f"{a.slug}.json"
    if os.path.lexists(chemin):
        raise Refus("fichier existant")
    obj = {
        "schema": SCHEMA, "slug": a.slug, "terrain": a.terrain, "objet": a.objet,
        "notre_role": a.role,
        "contrepartie": {"type": a.contrepartie, "intermediaire": a.intermediaire, "signaux": a.signal or []},
        "devise": "EUR",
        "reperes": {"prix_affiche": a.prix_affiche, "ouverture": a.ouverture, "cible": a.cible, "limite": a.limite,
                    "unite": a.unite, "source": a.source_reperes},
        "batna": a.batna, "coups": [],
        "issue": {"statut": "en_cours", "date": None, "montant_final": None, "conditions_finales": [],
                  "lecons": [], "retex_integre": False},
    }
    echecs, notes = controler(obj, chemin)
    if echecs:
        raise _refus_controle(echecs, chemin)
    return _publier(obj, chemin, notes)


def cmd_coup(a) -> int:
    donnees = _donnees(a)
    chemin, j, notes_avant = _ouvrir_valide(a.fichier, donnees)
    if j["issue"]["statut"] != "en_cours":
        raise Refus("journal clos")
    jour = a.date or aujourdhui().isoformat()
    if j["coups"] and _iso(jour) and _iso(jour) < _iso(j["coups"][-1]["date"]):
        raise Refus("date antérieure au dernier coup")
    j["coups"].append({
        "n": len(j["coups"]) + 1, "date": jour, "de": a.de, "canal": a.canal, "type": a.type, "montant": a.montant,
        "conditions": a.condition or [], "leviers": a.levier or [], "tactiques": a.tactique or [],
        "resume": a.resume, "source": a.source,
    })
    echecs, notes = controler(j, chemin)
    if echecs:
        raise _refus_controle(echecs, chemin)
    return _publier(j, chemin, [n for n in notes if n not in notes_avant])


def cmd_clore(a) -> int:
    donnees = _donnees(a)
    chemin, j, notes_avant = _ouvrir_valide(a.fichier, donnees)
    if j["issue"]["statut"] != "en_cours":
        raise Refus("journal déjà clos")
    if a.statut == "en_cours":
        raise Refus("statut en_cours : rien à clore")
    if a.statut == "conclu" and a.montant_final is None:
        raise Refus("conclu sans --montant-final")
    jour = a.date or aujourdhui().isoformat()
    if j["coups"] and _iso(jour) and _iso(jour) < _iso(j["coups"][-1]["date"]):
        raise Refus("date antérieure au dernier coup")
    j["issue"] = {"statut": a.statut, "date": jour, "montant_final": a.montant_final,
                  "conditions_finales": a.condition_finale or [], "lecons": a.lecon or [], "retex_integre": False}
    echecs, notes = controler(j, chemin)
    if echecs:
        raise _refus_controle(echecs, chemin)
    return _publier(j, chemin, [n for n in notes if n not in notes_avant])


def cmd_check(a) -> int:
    donnees = _donnees(a)
    if a.fichier:
        chemin = _chemin(a.fichier)
        if not dans_le_dossier(chemin, donnees):
            print(f"erreur : {a.fichier} est hors du dossier des journaux ({dossier_journaux(donnees)})",
                  file=sys.stderr)
            return 2
        if not chemin.is_file():
            print(f"erreur : {a.fichier} est introuvable", file=sys.stderr)
            return 2
        fichiers = [chemin]
    else:
        fichiers = journaux(donnees)
        if not fichiers:
            print(f"aucun journal trouvé (dossier lu : {dossier_journaux(donnees)})")
            print("RESULT=NEGOC_JOURNAL_OK")
            return 0
    en_echec = 0
    for f in fichiers:
        echecs, notes, _ = controler_fichier(f)
        rel = relatif(f)
        for e in echecs:
            print(f"ÉCHEC {rel} : {e}")
        for n in notes:
            print(f"NOTE {rel} : {n}")
        if not echecs and not notes:
            print(f"OK {rel}")
        en_echec += bool(echecs)
    if en_echec:
        print(f"RESULT=NEGOC_JOURNAL_FAIL({en_echec} en échec)")
        return 1
    print("RESULT=NEGOC_JOURNAL_OK")
    return 0


# -------------------------------------------------------------------------------------------------- bilan

def pct(v) -> str:
    """Rapport (fraction) en pourcentage signé, une décimale, virgule décimale, signe moins ASCII."""
    if v is None:
        return "n.d."
    x = round(v * 100, 1)
    return f"{x + 0.0:+.1f} %".replace(".", ",")


def nombre(v) -> str:
    """Médiane de coups ou de jours : entière si elle l'est, sinon une décimale."""
    if v is None:
        return "n.d."
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}".replace(".", ",")


def _rapport(valeur, repere):
    return None if valeur is None or repere is None or repere <= 0 else valeur / repere - 1


def _analyser(j: dict) -> dict:
    """Mesures d'un journal valide ; celles d'un accord restent None tant que le journal n'est pas `conclu`."""
    r, iss, coups = j["reperes"], j["issue"], j["coups"]
    sens = sens_du_role(j["notre_role"])
    nous = [c for c in coups if c["de"] == "nous"]
    premiere = next((c for c in nous if c["type"] in ("offre", "contre_offre") and c["montant"] is not None), None)
    x = {"slug": j["slug"], "terrain": j["terrain"], "sens": sens, "statut": iss["statut"],
         "premiere_offre_vs_affiche": _rapport(premiere["montant"], r["prix_affiche"]) if premiere else None,
         "tactiques": {t for c in nous for t in c["tactiques"]},
         "final_vs_affiche": None, "final_vs_ouverture": None, "final_vs_cible": None, "dans_cible": None,
         "coups_jusqu_accord": None, "jours_jusqu_accord": None}
    if iss["statut"] == "conclu":
        final, cible = iss["montant_final"], r["cible"]
        x["final_vs_affiche"] = _rapport(final, r["prix_affiche"])
        x["final_vs_ouverture"] = _rapport(final, r["ouverture"])
        x["final_vs_cible"] = _rapport(final, cible)
        if cible is not None:
            x["dans_cible"] = final <= cible if sens == "baisse" else final >= cible
        x["coups_jusqu_accord"] = len(coups)
        if coups:
            x["jours_jusqu_accord"] = (date.fromisoformat(iss["date"]) - date.fromisoformat(coups[0]["date"])).days
    return x


def _mesure(valeurs: list) -> dict:
    return {"mediane": statistics.median(valeurs) if valeurs else None, "n": len(valeurs)}


def _groupe(terrain: str, sens: str, items: list[dict], detail: bool) -> dict:
    conclus = [x for x in items if x["statut"] == "conclu"]
    cpt = Counter(x["statut"] for x in items)
    # par effectif décroissant, l'ordre de l'enum départage les égalités (le tri est stable)
    statuts = dict(sorted(((s, cpt[s]) for s in STATUTS if cpt[s]), key=lambda kv: -kv[1]))
    g = {"terrain": terrain, "sens": sens, "n": len(items), "statuts": statuts,
         "premiere_offre_vs_affiche": _mesure([x["premiere_offre_vs_affiche"] for x in items
                                               if x["premiere_offre_vs_affiche"] is not None])}
    for cle in ("final_vs_affiche", "final_vs_ouverture", "final_vs_cible"):
        g[cle] = _mesure([x[cle] for x in conclus if x[cle] is not None])
    dans = [x["dans_cible"] for x in conclus if x["dans_cible"] is not None]
    g["dans_cible"] = {"oui": sum(dans), "n": len(dans)}
    for cle in ("coups_jusqu_accord", "jours_jusqu_accord"):
        g[cle] = _mesure([x[cle] for x in conclus if x[cle] is not None])
    tactiques: dict[str, dict] = {}
    for x in items:
        colonne = "conclu" if x["statut"] == "conclu" else "clos_sans_accord" if x["statut"] in SANS_ACCORD else None
        for t in (x["tactiques"] if colonne else ()):
            tactiques.setdefault(t, {"conclu": 0, "clos_sans_accord": 0})[colonne] += 1
    g["tactiques"] = dict(sorted(tactiques.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])))
    g["avertissement"] = AVERTISSEMENT if len(conclus) < SEUIL_CONCLUS else None
    if detail:
        g["journaux"] = [{"slug": x["slug"], "statut": x["statut"],
                          "premiere_offre_vs_affiche": x["premiere_offre_vs_affiche"],
                          "final_vs_affiche": x["final_vs_affiche"]} for x in items]
    return g


def _texte_groupe(g: dict) -> list[str]:
    def mesure(titre: str, m: dict, fmt) -> str:
        return f"  {titre} : médiane {fmt(m['mediane'])} (n {m['n']})"

    lignes = [f"== {g['terrain']} / {g['sens']} : {g['n']} {'journaux' if g['n'] > 1 else 'journal'} ==",
              "statuts : " + ", ".join(f"{s} {c}" for s, c in g["statuts"].items()),
              "première offre / affiché : médiane " + pct(g["premiere_offre_vs_affiche"]["mediane"])
              + f" (n {g['premiere_offre_vs_affiche']['n']})",
              "sur les journaux conclus :",
              mesure("final / affiché", g["final_vs_affiche"], pct),
              mesure("final / ouverture", g["final_vs_ouverture"], pct),
              mesure("final / cible", g["final_vs_cible"], pct),
              f"  dans la cible : {g['dans_cible']['oui']} sur {g['dans_cible']['n']}",
              mesure("coups jusqu'à l'accord", g["coups_jusqu_accord"], nombre),
              mesure("jours jusqu'à l'accord", g["jours_jusqu_accord"], nombre)]
    if g["tactiques"]:
        lignes.append("tactiques jouées par nous (journaux conclus / clos sans accord) :")
        lignes += [f"  {t} : {c['conclu']} / {c['clos_sans_accord']}" for t, c in g["tactiques"].items()]
    for jr in g.get("journaux", []):
        lignes.append(f"  {jr['slug']} : {jr['statut']} ; première offre / affiché "
                      f"{pct(jr['premiere_offre_vs_affiche'])} ; final / affiché {pct(jr['final_vs_affiche'])}")
    if g["avertissement"]:
        lignes.append(g["avertissement"])
    return lignes


def cmd_bilan(a) -> int:
    donnees = _donnees(a)
    lus: list[dict] = []
    ignores: list[str] = []
    for f in journaux(donnees):
        echecs, _, j = controler_fichier(f)
        if echecs:
            ignores.append(relatif(f))
        elif not a.terrain or j["terrain"] == a.terrain:
            lus.append(_analyser(j))
    par_groupe: dict[tuple, list] = {}
    for x in lus:
        par_groupe.setdefault((x["terrain"], x["sens"]), []).append(x)
    groupes = [_groupe(t, s, items, a.detail) for (t, s), items in sorted(par_groupe.items())]
    genere_le = aujourdhui().isoformat()
    if a.json:
        print(json.dumps({"genere_le": genere_le, "journaux_lus": len(lus), "ignores": ignores, "groupes": groupes},
                         ensure_ascii=False, indent=2))
        sys.stdout.flush()  # sous `2>&1` derrière un tube, sans cela RESULT= passerait avant le JSON
        print("RESULT=NEGOC_BILAN_OK", file=sys.stderr)  # stdout reste un JSON pur
        return 0
    for rel in ignores:
        print(f"ignoré (check en échec) : {rel}")
    if not lus:
        print("aucun journal")
    else:
        n = len(lus)
        print(f"Bilan des négociations au {genere_le} : {n} {'journaux lus' if n > 1 else 'journal lu'}")
        for g in groupes:
            print()
            print("\n".join(_texte_groupe(g)))
    print("RESULT=NEGOC_BILAN_OK")
    return 0


# ---------------------------------------------------------------------------------------------- ligne de commande

def _montant(txt: str):
    try:
        v = float(txt)
    except ValueError:
        raise argparse.ArgumentTypeError(f"nombre attendu : {txt!r}") from None
    if not math.isfinite(v):
        raise argparse.ArgumentTypeError(f"nombre fini attendu : {txt!r}")
    return int(v) if v.is_integer() else v


def _parser() -> argparse.ArgumentParser:
    commun = argparse.ArgumentParser(add_help=False)
    aide_donnees = "dossier de données (défaut : $IMMO_DATA_DIR, sinon ./immo-data)"
    commun.add_argument("--donnees", metavar="DIR", default=argparse.SUPPRESS, help=aide_donnees)
    p = argparse.ArgumentParser(prog="negoc_journal.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--donnees", metavar="DIR", default=None, help=aide_donnees)
    sp = p.add_subparsers(dest="commande", required=True)

    n = sp.add_parser("nouveau", parents=[commun], help="crée un journal vide")
    for opt in ("--slug", "--terrain", "--role", "--objet"):
        n.add_argument(opt, required=True)
    n.add_argument("--contrepartie", default="autre", metavar="TYPE", help="type de contrepartie (défaut : autre)")
    n.add_argument("--intermediaire", help="un rôle (« agence, mandat exclusif »), jamais un nom")
    n.add_argument("--signal", action="append", help="signal de la contrepartie (répétable)")
    for opt in ("--prix-affiche", "--ouverture", "--cible", "--limite"):
        n.add_argument(opt, type=_montant, metavar="X")
    n.add_argument("--unite", default="eur", help="unité des repères (défaut : eur)")
    n.add_argument("--source-reperes", help="chemin et section qui fixent les paliers")
    n.add_argument("--batna")
    n.set_defaults(fn=cmd_nouveau)

    c = sp.add_parser("coup", parents=[commun], help="ajoute un coup daté")
    c.add_argument("--fichier", required=True, metavar="CHEMIN")
    for opt in ("--de", "--type", "--canal", "--resume"):
        c.add_argument(opt, required=True)
    c.add_argument("--date", metavar="AAAA-MM-JJ", help="défaut : aujourd'hui")
    c.add_argument("--montant", type=_montant, metavar="X")
    c.add_argument("--condition", action="append", help="répétable")
    c.add_argument("--levier", action="append", help="répétable")
    c.add_argument("--tactique", action="append", help="répétable")
    c.add_argument("--source")
    c.set_defaults(fn=cmd_coup)

    k = sp.add_parser("clore", parents=[commun], help="pose l'issue du journal")
    k.add_argument("--fichier", required=True, metavar="CHEMIN")
    k.add_argument("--statut", required=True)
    k.add_argument("--date", metavar="AAAA-MM-JJ", help="défaut : aujourd'hui")
    k.add_argument("--montant-final", type=_montant, metavar="X")
    k.add_argument("--condition-finale", action="append", help="répétable")
    k.add_argument("--lecon", action="append", help="répétable")
    k.set_defaults(fn=cmd_clore)

    v = sp.add_parser("check", parents=[commun], help="contrôle un journal, ou tous (lecture seule)")
    v.add_argument("--fichier", metavar="CHEMIN")
    v.set_defaults(fn=cmd_check)

    b = sp.add_parser("bilan", parents=[commun], help="bilan chiffré par terrain (lecture seule)")
    b.add_argument("--terrain", choices=TERRAINS)
    b.add_argument("--detail", action="store_true", help="une ligne par journal")
    b.add_argument("--json", action="store_true", help="sortie JSON ; RESULT= passe sur la sortie d'erreur")
    b.set_defaults(fn=cmd_bilan)
    return p


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    try:
        return a.fn(a)
    except Refus as r:
        for ligne in r.lignes:
            print(ligne)
        print(f"RESULT=NEGOC_JOURNAL_REFUS({r.raison})")
        return r.code
    except OSError as exc:
        print(f"erreur d'entrée-sortie : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
