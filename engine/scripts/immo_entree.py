#!/usr/bin/env python3
"""Entrée du moteur immo : contrôle contre le profil de l'investisseur, et loyer du tri rapide corrigé de la surface.

`controle` lit l'entrée du moteur (`--bien`) et `immo-data/profil.json` (`--profil`, défaut :
`$IMMO_DATA_DIR/profil.json` ou `./immo-data/profil.json`), sans rien
écrire. Il refuse (code 1, violations nommées sur stderr) :
- une vacance de scénario différente de `vacance_realiste`, sauf `--justification-vacance` non vide
  (colocation, petit logement à forte rotation : voir les références du skill `immo`) ;
- une comptabilité (`exploitation.comptable`) non nulle quand l'entrée a un bloc `sci` et que le profil met
  la comptabilité de la SCI hors cash-flow.
Il avertit sans refuser quand prix net vendeur + frais d'agence n'est pas inférieur à `premier_achat_prix_max`,
sauf exception de l'annonce (`--annonce`).

`loyer-3r` calcule les loyers de l'étape 3r depuis une fiche de données ouvertes (`src/immo/loyer.py`).

Usage :
  python3 engine/scripts/immo_entree.py controle --bien <entree.json> [--profil immo-data/profil.json] \
      [--justification-vacance "<texte>"] [--annonce <id>]
  python3 engine/scripts/immo_entree.py loyer-3r --fiche <fiche-opendata.json> --serie appartement_t1_t2 \
      --surface 40 [--charges 30] [--json]

Codes de sortie : 0 ; 1 si `controle` refuse ; 2 si une entrée est illisible ou invalide.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
sys.path.insert(0, str(ROOT))

from src.immo.donnees import fichier  # noqa: E402
from src.immo.loyer import SERIES, loyer_3r  # noqa: E402


def profil_par_defaut() -> Path:
    """`profil.json` du dossier de données (`$IMMO_DATA_DIR` ou `./immo-data`), résolu à l'appel."""
    return fichier("profil.json")


class Illisible(Exception):
    pass


def _json(chemin: str) -> dict:
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Illisible(f"{chemin} : {type(exc).__name__} : {exc}") from exc
    if not isinstance(d, dict):
        raise Illisible(f"{chemin} : objet JSON attendu")
    return d


MARQUEURS_GABARIT = ("exemple fictif", "à remplacer")  # source d'une décision du gabarit non encore remplie


def _decisions(profil: dict) -> dict:
    """Décisions du profil par clé ; refuse un profil encore au gabarit (source « exemple fictif » ou « à remplacer »)."""
    try:
        decisions = {d["cle"]: d for d in profil["decisions"]}
    except (KeyError, TypeError) as exc:
        raise Illisible(f"profil : liste `decisions` de {{cle, valeur, …}} attendue ({exc})") from exc
    non_remplies = [cle for cle, d in decisions.items()
                    if isinstance(d, dict) and any(m in str(d.get("source", "")).casefold() for m in MARQUEURS_GABARIT)]
    if non_remplies:
        raise Illisible(f"profil non rempli : {', '.join(non_remplies)} porte(nt) encore la source du gabarit "
                        "(« exemple fictif : à remplacer ») ; remplacer chaque valeur par la sienne, avec sa source et sa "
                        "date, dans immo-data/profil.json")
    return decisions


def _exception(decision: dict, annonce: str | None) -> dict | None:
    return next((e for e in decision.get("exceptions", []) if annonce and e.get("annonce") == annonce), None)


def _decision_nombre(cle: str, valeur, *, maxi: float | None = None, strictement_positif: bool = False) -> None:
    """Valeur numérique d'une décision du profil : un nombre fini, sinon `Illisible` qui nomme la décision."""
    ok = isinstance(valeur, (int, float)) and not isinstance(valeur, bool) and math.isfinite(valeur)
    ok = ok and (valeur > 0 if strictement_positif else valeur >= 0) and (maxi is None or valeur < maxi)
    if not ok:
        borne = "un nombre strictement positif" if strictement_positif else f"un nombre entre 0 et {maxi:g} (exclu)"
        raise Illisible(f"profil : {cle}.valeur doit être {borne} (reçu {valeur!r}) ; corriger profil.json")


def controle(bien: dict, profil: dict, justification: str | None, annonce: str | None) -> tuple[list, list, list]:
    """(violations, avertissements, notes) ; lève `Illisible` sur une entrée incomplète."""
    d = _decisions(profil)
    violations, avertissements, notes = [], [], []
    try:
        vacance_profil = d["vacance_realiste"]["valeur"]
        compta_dans_cf = d["comptabilite_sci_dans_cash_flow"]["valeur"]
        prix_max = d["premier_achat_prix_max"]
        scenarios = {nom: float(sc["vacance"]) for nom, sc in bien["scenarios"].items()}
        comptable = float(bien["exploitation"]["comptable"])
        prix = float(bien["prix_net_vendeur"]) + float(bien["frais_agence_acquereur"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise Illisible(f"champ attendu absent ou invalide : {type(exc).__name__} : {exc}") from exc
    _decision_nombre("vacance_realiste", vacance_profil, maxi=1.0)
    _decision_nombre("premier_achat_prix_max", prix_max.get("valeur"), strictement_positif=True)
    if not isinstance(compta_dans_cf, bool):
        raise Illisible("profil : comptabilite_sci_dans_cash_flow.valeur doit être true ou false "
                        f"(reçu {compta_dans_cf!r})")
    if not scenarios:
        raise Illisible("aucun scénario dans `scenarios`")

    ecarts = {nom: v for nom, v in scenarios.items() if abs(v - vacance_profil) > 1e-9}
    justifiee = bool(justification and justification.strip())
    for nom, v in ecarts.items():
        if justifiee:
            notes.append(f"vacance {nom} = {v:g} ≠ profil {vacance_profil:g}, justifiée : « {justification.strip()} »")
        else:
            violations.append(f"vacance : scenarios.{nom}.vacance = {v:g} ≠ vacance_realiste du profil "
                              f"({vacance_profil:g}) ; sans --justification-vacance (colocation, forte rotation), "
                              "le taux de logements vacants de l'INSEE ne justifie pas un écart")

    if "sci" in bien and compta_dans_cf is False and comptable != 0:
        violations.append(f"exploitation.comptable = {comptable:g} avec un bloc `sci` : le profil met la comptabilité "
                          "de la SCI hors cash-flow du bien (comptabilite_sci_dans_cash_flow = false) → 0, à dire "
                          "dans l'analyse")

    if prix >= prix_max["valeur"]:
        exc = _exception(prix_max, annonce)
        if exc:
            notes.append(f"premier_achat_prix_max : exception de l'annonce {annonce} ({exc['portee']}, {exc['date']})")
        else:
            avertissements.append(f"premier_achat_prix_max : prix net vendeur + frais d'agence = {prix:g} €, non "
                                  f"inférieur à {prix_max['valeur']:g} € (premier achat) ; à dire dans l'analyse")
    return violations, avertissements, notes


def _cmd_controle(args) -> int:
    args.profil = args.profil or str(profil_par_defaut())
    bien, profil = _json(args.bien), _json(args.profil)
    violations, avertissements, notes = controle(bien, profil, args.justification_vacance, args.annonce)
    for a in avertissements:
        print(f"avertissement : {a}", file=sys.stderr)
    for n in notes:
        print(f"note : {n}")
    if violations:
        for v in violations:
            print(f"violation : {v}", file=sys.stderr)
        print(f"controle : {len(violations)} violation(s) du profil ; corriger l'entrée avant le moteur",
              file=sys.stderr)
        return 1
    print(f"controle : entrée conforme au profil ({Path(args.profil).name})")
    return 0


def _euros(x: float | None) -> str:
    return "-" if x is None else f"{x:,.0f} €".replace(",", " ")


def _cmd_loyer(args) -> int:
    fiche = _json(args.fiche)
    try:
        r = loyer_3r(fiche, args.serie, args.surface, args.charges)
    except (ValueError, KeyError, TypeError) as exc:
        raise Illisible(str(exc)) from exc
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    commune = (fiche.get("commune") or {}).get("nom", "?")
    print(f"loyer-3r : {commune}, série {r['serie']}, {r['surface_m2']:g} m² (type {r['surface_type_m2']:g} m²), "
          f"maille {r['maille']}, n = {r['n']}, millésime {r['millesime']}")
    print(f"élasticité e = {r['elasticite']:.4f} ; facteur (S / S_type)^e = {r['facteur']:.4f}")
    if r["charges_mensuelles"] is not None:
        print(f"charges récupérables (hypothèse) : {_euros(r['charges_mensuelles'])}/mois")
    print("scénario     €/m² CC   loyer CC   loyer HC")
    for nom, sc in r["scenarios"].items():
        if sc is None:
            print(f"{nom:<12} ip_haut absent de la fiche")
            continue
        print(f"{nom:<12} {sc['loyer_m2_cc']:>7.2f}   {_euros(sc['loyer_cc']):>8}   {_euros(sc['loyer_hc']):>8}")
    if r["extrapolation"]:
        print(f"EXTRAPOLATION : {r['raison_extrapolation']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Entrée du moteur immo : contrôle du profil, loyer du tri rapide.")
    sous = parser.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("controle", help="refuse une entrée qui contredit le profil de l'investisseur")
    c.add_argument("--bien", required=True, help="JSON d'entrée du moteur")
    c.add_argument("--profil", default=None, help="profil.json (défaut : immo-data/profil.json)")
    c.add_argument("--justification-vacance", help="raison d'une vacance différente du profil (colocation…)")
    c.add_argument("--annonce", help="identifiant de l'annonce, pour les exceptions du profil")
    l = sous.add_parser("loyer-3r", help="loyers de l'étape 3r, corrigés de la surface")
    l.add_argument("--fiche", required=True, help="fiche de données ouvertes (immo-data/bruts/*-opendata-*.json)")
    l.add_argument("--serie", required=True, choices=SERIES)
    l.add_argument("--surface", required=True, type=float, help="surface habitable, m²")
    l.add_argument("--charges", type=float, help="charges récupérables, €/mois (hypothèse affichée)")
    l.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return _cmd_controle(args) if args.commande == "controle" else _cmd_loyer(args)
    except Illisible as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
