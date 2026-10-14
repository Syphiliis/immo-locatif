#!/usr/bin/env python3
"""Âge des repères d'une étude immo, à afficher en tête de `/immo` (étape 0). Sans réseau, n'écrit rien.

Repères lus :
- `immo-data/MARCHE.md` (dossier de données : `$IMMO_DATA_DIR`, sinon `./immo-data`) :
  « **Date de référence** : AAAA-MM-JJ » ;
- grille de travaux (`skills/renovation-estimator/references/grille-couts-*.md` du plugin, la plus récente par nom) :
  « rédigée MM/AAAA », datée au premier du mois (âge majoré, jamais minoré) ;
- carte des loyers : `MILLESIME` de `engine/src/opendata/loyers.py`, datée au 31/12 du millésime (âge minoré : la
  carte décrit les annonces de l'année ; le dire si elle paraît fraîche) ;
- `engine/src/immo/params.json` : la plus ancienne `verifie_le`, avec le compte des `verifie_le` et des `a_verifier` ;
  chaque table datée par `cloture_au` doit couvrir la date du jour ; de même pour `immo-data/params_local.json` s'il
  existe ;
- `immo-data/foyer.json`, s'il existe : la plus ancienne `date` AAAA-MM-JJ de ses valeurs ;
- avec `--fiche` : dernière mutation DVF, exercice REI (31/12) et millésime de la carte de cette fiche.

Usage :
  python3 engine/scripts/immo_fraicheur.py [--fiche immo-data/bruts/<slug>-opendata-<date>.json]

Codes de sortie : 0 ; 1 si un repère a plus de `SEUIL_JOURS` jours ou si une table datée du moteur ne couvre
plus la date du jour ; 2 si un repère est illisible.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

SEUIL_JOURS = 180
ENGINE = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
RACINE = ENGINE.parent                           # racine du plugin (engine/ et skills/)
sys.path.insert(0, str(ENGINE))

from src.immo.donnees import dossier_donnees  # noqa: E402

MARCHE = "MARCHE.md"                                   # dans le dossier de données
FOYER = "foyer.json"                                   # dans le dossier de données
PARAMS_LOCAL = "params_local.json"                     # dans le dossier de données
GRILLES = "skills/renovation-estimator/references"     # depuis la racine du plugin
MOTIF_GRILLE = "grille-couts-*.md"
LOYERS = "engine/src/opendata/loyers.py"
PARAMS = "engine/src/immo/params.json"


class Illisible(Exception):
    pass


def _cherche(chemin: Path, motif: str) -> re.Match:
    try:
        m = re.search(motif, chemin.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Illisible(f"{chemin} : {exc}") from exc
    if not m:
        raise Illisible(f"{chemin} : date introuvable (motif {motif!r})")
    return m


def _repere(nom: str, d: date, aujourdhui: date, note: str = "") -> dict:
    age = (aujourdhui - d).days
    return {"repere": nom, "date": d, "age": age, "seuil": SEUIL_JOURS,
            "etat": "OK" if age <= SEUIL_JOURS else "PÉRIMÉ", "note": note}


def _feuilles_datees(noeud, chemin=()):
    if isinstance(noeud, dict):
        if "verifie_le" in noeud:
            yield ".".join(chemin), noeud
        for k, v in noeud.items():
            yield from _feuilles_datees(v, chemin + (k,))


def _params(chemin: Path, aujourdhui: date) -> list[dict]:
    nom = chemin.name
    try:
        params = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Illisible(f"{chemin} : {exc}") from exc
    feuilles = [(c, f) for c, f in _feuilles_datees(params) if not c.startswith("_") and ("._" not in c)]
    if not feuilles:
        if nom == PARAMS_LOCAL:
            return []  # surcharge vide : rien à dater
        raise Illisible(f"{chemin} : aucune entrée `verifie_le`")
    try:
        cle, plus_ancienne = min(feuilles, key=lambda f: date.fromisoformat(str(f[1]["verifie_le"])))
    except ValueError as exc:
        raise Illisible(f"{chemin} : verifie_le illisible ({exc})") from exc
    n_av = sum(1 for _, f in feuilles if f.get("a_verifier"))
    sortie = [_repere(f"{nom} : plus ancienne vérification", date.fromisoformat(plus_ancienne["verifie_le"]),
                      aujourdhui, f"{cle} ; {len(feuilles)} verifie_le, {n_av} a_verifier")]
    for cle, f in feuilles:
        lignes = f.get("valeur")
        if isinstance(lignes, list) and lignes and all(isinstance(t, dict) and "cloture_au" in t for t in lignes):
            fin = date.fromisoformat(max(t["cloture_au"] for t in lignes))
            r = _repere(f"{nom} : table {cle}", fin, aujourdhui, "dernière cloture_au")
            r["age"], r["seuil"] = (aujourdhui - fin).days, 0
            r["etat"] = "OK" if fin >= aujourdhui else "NON COUVERT"
            sortie.append(r)
    return sortie


def reperes(racine: Path, aujourdhui: date, fiche: dict | None = None, donnees: Path | None = None) -> list[dict]:
    """`racine` : racine du plugin (engine/, skills/) ; `donnees` : dossier de données (défaut : `dossier_donnees()`)."""
    donnees = dossier_donnees() if donnees is None else donnees
    try:
        brut = (donnees / MARCHE).read_text(encoding="utf-8")
    except OSError as exc:
        raise Illisible(f"{donnees / MARCHE} : {exc} (copier templates/MARCHE.md dans le dossier de données, puis "
                        "lancer market-context)") from exc
    if re.search(r"(?m)^\*\*Date de référence\*\*\s*:\s*AAAA-MM-JJ\s*$", brut):
        raise Illisible(f"{donnees / MARCHE} : MARCHE.md pas encore rempli (Date de référence AAAA-MM-JJ) : lancer "
                        "market-context")
    m = _cherche(donnees / MARCHE, r"\*\*Date de référence\*\*\s*:\s*(\d{4}-\d{2}-\d{2})")
    sortie = [_repere("marché (MARCHE.md)", date.fromisoformat(m.group(1)), aujourdhui)]
    grilles = sorted((racine / GRILLES).glob(MOTIF_GRILLE))
    if not grilles:
        raise Illisible(f"{racine / GRILLES} : aucune {MOTIF_GRILLE}")
    m = _cherche(grilles[-1], r"rédigée (\d{2})/(\d{4})")
    sortie.append(_repere(f"grille de travaux ({grilles[-1].name})", date(int(m.group(2)), int(m.group(1)), 1),
                          aujourdhui, "datée au premier du mois"))
    m = _cherche(racine / LOYERS, r'MILLESIME\s*=\s*"(\d{4})"')
    sortie.append(_repere("carte des loyers (MILLESIME)", date(int(m.group(1)), 12, 31), aujourdhui,
                          f"millésime {m.group(1)}, daté au 31/12"))
    sortie += _params(racine / PARAMS, aujourdhui)
    if (donnees / PARAMS_LOCAL).is_file():
        sortie += _params(donnees / PARAMS_LOCAL, aujourdhui)
    if (donnees / FOYER).is_file():
        sortie += _foyer(donnees / FOYER, aujourdhui)
    if fiche is not None:
        sortie += _fiche(fiche, aujourdhui)
    return sortie


def _foyer(chemin: Path, aujourdhui: date) -> list[dict]:
    from src.immo.foyer import date_la_plus_ancienne
    try:
        trouvee = date_la_plus_ancienne(chemin)
    except (OSError, ValueError) as exc:
        raise Illisible(f"{chemin} : {exc}") from exc
    if trouvee is None:
        return [{"repere": "foyer.json", "date": None, "age": None, "seuil": SEUIL_JOURS, "etat": "NON DATÉ",
                 "note": "aucune date AAAA-MM-JJ dans le fichier"}]
    cle, d = trouvee
    return [_repere("foyer.json : plus ancienne date", d, aujourdhui, cle)]


def _fiche(fiche: dict, aujourdhui: date) -> list[dict]:
    try:
        mutation = date.fromisoformat(fiche["dvf"]["parametres"]["derniere_mutation"])
        exercice = int(fiche["fiscalite_locale"]["exercice"])
        millesimes = sorted({s["millesime"] for s in fiche["loyers"].values() if isinstance(s, dict)})
    except KeyError as exc:
        raise Illisible(f"fiche incomplète : clé « {exc.args[0]} » absente (bloc DVF, fiscalité locale ou loyers) ; "
                        "régénérer la fiche avec engine/scripts/immo_fiche_opendata.py") from exc
    except (TypeError, ValueError, AttributeError) as exc:
        raise Illisible(f"fiche : repère invalide (dernière mutation DVF, exercice REI ou millésime des loyers) : {exc} ; "
                        "régénérer la fiche avec engine/scripts/immo_fiche_opendata.py") from exc
    if not millesimes:
        raise Illisible("fiche : aucun millésime de loyers")
    return [_repere("fiche : dernière mutation DVF", mutation, aujourdhui),
            _repere("fiche : exercice REI (fiscalité locale)", date(exercice, 12, 31), aujourdhui,
                    f"exercice {exercice}, daté au 31/12"),
            _repere("fiche : millésime de la carte des loyers", date(int(millesimes[0]), 12, 31), aujourdhui,
                    f"millésime {', '.join(millesimes)}, daté au 31/12")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Âge des repères d'une étude immo (marché, grille, loyers, params).")
    parser.add_argument("--fiche", help="fiche de données ouvertes du bien")
    parser.add_argument("--racine", default=str(RACINE), help=argparse.SUPPRESS)
    parser.add_argument("--donnees", default=None, help="dossier de données (défaut : $IMMO_DATA_DIR ou ./immo-data)")
    parser.add_argument("--aujourdhui", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    aujourdhui = date.fromisoformat(args.aujourdhui) if args.aujourdhui else date.today()
    try:
        fiche = json.loads(Path(args.fiche).read_text(encoding="utf-8")) if args.fiche else None
        lignes = reperes(Path(args.racine), aujourdhui, fiche, Path(args.donnees) if args.donnees else None)
    except (OSError, ValueError) as exc:
        print(f"erreur : fiche illisible : {exc}", file=sys.stderr)
        return 2
    except Illisible as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    print(f"Fraîcheur des repères au {aujourdhui.isoformat()} (seuil {SEUIL_JOURS} jours)\n")
    print("| repère | date | âge (j) | seuil (j) | état |")
    print("|---|---|---|---|---|")
    for r in lignes:
        note = f" ({r['note']})" if r["note"] else ""
        quand = r["date"].isoformat() if r["date"] else "n/d"
        age = r["age"] if r["age"] is not None else "n/d"
        print(f"| {r['repere']}{note} | {quand} | {age} | {r['seuil']} | {r['etat']} |")
    hors = [r for r in lignes if r["etat"] != "OK"]
    if hors:
        print(f"\nfraicheur : {len(hors)} repère(s) à revoir : {' ; '.join(r['repere'] for r in hors)}")
        return 1
    print("\nfraicheur : tous les repères sont dans le seuil")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
