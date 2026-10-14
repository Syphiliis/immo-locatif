#!/usr/bin/env python3
"""Fiche « données ouvertes » d'un bien : géocodage, parcelle cadastrale, urbanisme, bâtiment, copropriété, loyers,
ventes DVF, DPE, risques, taxe foncière.

Interroge uniquement des API publiques, en GET, sans clé (voir `src/opendata/`) et écrit une fiche JSON
datée et sourcée. Le fichier est écrit MÊME si le géocodage échoue (tous les blocs à `null`, motif dans
`erreurs`) : un fichier périmé ne doit jamais passer pour une fiche fraîche. À ranger sous
`immo-data/bruts/<slug>-opendata-<AAAA-MM-JJ>.json`.

Le type du point géocodé décide de ce qui est lu : urbanisme, bâtiment et copropriété sont lus pour un numéro de rue ;
pour une rue ou un lieu-dit, lus avec une alerte (« point sur la rue ») ; pour le centre d'une commune (type
`municipality`), non lus, avec une alerte. Le bâtiment lit la parcelle du cadastre : cadastre en échec, il est en
erreur (« parcelle inconnue (cadastre en échec) »), donc code 3.

Code de sortie : 2 si le géocodage échoue (aucun résultat, aucun candidat dans le code postal de l'adresse) ou si son
score est inférieur à 0,5 (rien de fiable derrière) ;
3 si le géocodage tient mais qu'au moins un bloc a échoué (fiche partielle : le JSON est écrit, et chaque bloc
en échec est écrit sur stderr, une ligne « bloc : message ») ; 0 sinon. Les alertes (`alertes` : ce qui ne
bloque pas, comme une fenêtre DVF courte ou un contrôle de commune non fait) ne changent pas le code.

Mode `--point` (annonce sans adresse) : classe des adresses candidates depuis le point de l'annonce (géocodage inverse
de la BAN) et, avec `--surface`, depuis les DPE de la commune (surface à ± `adresse.TOLERANCE_SURFACE`, étiquette,
date). Même contrat de sortie : le JSON est écrit, code 2 si le géocodage inverse échoue, 3 si les DPE échouent (une
ligne par erreur sur stderr), 0 sinon. `--adresse` et `--point` s'excluent ; `--surface`, `--etiquette`, `--date-dpe`,
`--code-postal` et `--insee` ne valent qu'avec `--point` (`--etiquette`, `--date-dpe` et `--insee` exigent `--surface`) ;
`--rayon`, `--fenetre-mois` et `--fenetre-immeubles-mois` ne valent qu'avec `--adresse`. Une latitude négative
s'écrit `--point=-21.1,55.5` (avec le signe égal).

Usage :
  python3 engine/scripts/immo_fiche_opendata.py --adresse "12 rue de l'Exemple 99999 Exempleville" --out fiche.json
  python3 engine/scripts/immo_fiche_opendata.py --adresse "Exempleville 99999" --rayon 300 --fenetre-mois 12 --out fiche.json
  python3 engine/scripts/immo_fiche_opendata.py --point 48.000000,2.500000 --surface 130 --etiquette F --code-postal 99999 --out point.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
sys.path.insert(0, str(ROOT))

from src.opendata import adresse  # noqa: E402
from src.opendata.dvf import FENETRE_IMMEUBLES_MOIS  # noqa: E402
from src.opendata.fiche import code_sortie, construire_fiche, resume  # noqa: E402
from src.opendata.http import make_client  # noqa: E402


def _mois_positif_ou_nul(texte: str) -> int:
    mois = int(texte)
    if mois < 0:
        raise argparse.ArgumentTypeError(f"{mois} : un nombre de mois négatif n'a pas de sens (0 : désactivé)")
    return mois


def _point(texte: str) -> tuple[float, float]:
    """`<lat>,<lon>` en degrés décimaux (la latitude d'abord, comme sur une carte ; le point est un nombre à point)."""
    morceaux = [m.strip() for m in texte.split(",")]
    erreur = argparse.ArgumentTypeError(f"« {texte} » : attendu <lat>,<lon>, deux nombres (latitude puis longitude)")
    if len(morceaux) != 2:
        raise erreur
    try:
        lat, lon = float(morceaux[0]), float(morceaux[1])
    except ValueError:
        raise erreur from None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise argparse.ArgumentTypeError(f"« {texte} » : latitude entre -90 et 90, longitude entre -180 et 180")
    return lat, lon


def _surface(texte: str) -> float:
    try:
        valeur = float(texte.replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"« {texte} » n'est pas un nombre") from None
    if not math.isfinite(valeur) or valeur <= 0:
        raise argparse.ArgumentTypeError(f"« {texte} » : une surface est un nombre strictement positif")
    if not math.isfinite(valeur * 2):  # les bornes ±tolérance débordent : pas une surface
        raise argparse.ArgumentTypeError(f"« {texte} » : trop grand pour être une surface")
    return int(valeur) if valeur.is_integer() else valeur


def _etiquette(texte: str) -> str:
    lettre = texte.strip().upper()
    if lettre not in tuple("ABCDEFG"):
        raise argparse.ArgumentTypeError(f"« {texte} » : une lettre de A à G")
    return lettre


def _date_dpe(texte: str) -> str:
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texte):
            raise ValueError(texte)
        date.fromisoformat(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"« {texte} » : attendu AAAA-MM-JJ, une date existante") from None
    return texte


def _code_postal(texte: str) -> str:
    if not re.fullmatch(r"[0-9]{5}", texte):
        raise argparse.ArgumentTypeError(f"« {texte} » : un code postal a 5 chiffres")
    return texte


def _insee(texte: str) -> str:
    if not re.fullmatch(r"[0-9]{5}|2[AB][0-9]{3}", texte):
        raise argparse.ArgumentTypeError(f"« {texte} » : un code INSEE a 5 chiffres (2A ou 2B pour la Corse)")
    return texte


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fiche données ouvertes d'un bien (JSON datée et sourcée), ou "
                                                 "adresses candidates d'une annonce sans adresse (--point).")
    cible = parser.add_mutually_exclusive_group(required=True)
    cible.add_argument("--adresse", help="adresse libre, géocodée par la BAN (avec son code postal : la commune est "
                                         "contrôlée)")
    cible.add_argument("--point", type=_point, metavar="LAT,LON",
                       help="annonce sans adresse : point de l'annonce, ex. 48.000000,2.500000 (latitude négative : "
                            "--point=-21.1,55.5)")
    parser.add_argument("--rayon", type=int, default=500,
                        help="(--adresse) rayon des ventes DVF comparables, en mètres (500)")
    parser.add_argument("--fenetre-mois", type=int, default=24, help="(--adresse) fenêtre des ventes DVF, en mois (24)")
    parser.add_argument("--fenetre-immeubles-mois", type=_mois_positif_ou_nul, default=FENETRE_IMMEUBLES_MOIS,
                        help=f"(--adresse) fenêtre des ventes d'immeubles (plusieurs locaux) de la commune, en mois "
                             f"({FENETRE_IMMEUBLES_MOIS} ; 0 : pas de bloc dvf.immeubles)")
    parser.add_argument("--surface", type=_surface, metavar="M2",
                        help=f"(--point) surface annoncée, en m² : cherche les DPE de la commune à "
                             f"±{round(adresse.TOLERANCE_SURFACE * 100)} %%")
    parser.add_argument("--etiquette", type=_etiquette, metavar="A-G", help="(--point) étiquette DPE annoncée")
    parser.add_argument("--date-dpe", type=_date_dpe, metavar="AAAA-MM-JJ", help="(--point) date du DPE annoncée")
    parser.add_argument("--code-postal", type=_code_postal, metavar="CP",
                        help="(--point) code postal de l'annonce : alerte si le premier candidat BAN en a un autre")
    parser.add_argument("--insee", type=_insee, metavar="CODE",
                        help="(--point) force la commune de la recherche DPE (code INSEE)")
    parser.add_argument("--out", required=True, help="chemin du JSON à écrire (dossier parent créé si besoin)")
    return parser


def _valider(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    options_point = (args.surface, args.etiquette, args.date_dpe, args.code_postal, args.insee)
    if args.point is None and any(valeur is not None for valeur in options_point):
        parser.error("--surface, --etiquette, --date-dpe, --code-postal et --insee ne valent qu'avec --point")
    if args.surface is None and (args.etiquette is not None or args.date_dpe is not None or args.insee is not None):
        parser.error("--etiquette, --date-dpe et --insee requièrent --surface (la recherche DPE part de la surface)")


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None,
         maintenant: datetime | None = None, sleep: Callable[[float], Any] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _valider(parser, args)
    sortie = Path(args.out)
    client_cree = client is None
    if client is None:
        client = make_client()
    attente = time.sleep if sleep is None else sleep
    try:
        if args.point is not None:
            donnees = adresse.rechercher(
                *args.point, client=client, surface=args.surface, etiquette=args.etiquette, date_dpe=args.date_dpe,
                code_postal=args.code_postal, insee=args.insee, maintenant=maintenant, sleep=attente)
        else:
            donnees = construire_fiche(
                args.adresse, client=client, rayon_m=args.rayon, fenetre_mois=args.fenetre_mois,
                maintenant=maintenant, sleep=attente, fenetre_immeubles_mois=args.fenetre_immeubles_mois)
    finally:
        if client_cree:
            client.close()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.point is not None:
        print(adresse.resume(donnees, sortie))
        code = adresse.code_sortie(donnees)
    else:
        print(resume(donnees, sortie))
        code = code_sortie(donnees)
    if code == 3:  # fiche partielle : un bloc en échec par ligne, le message sur une seule ligne
        for erreur in donnees["erreurs"]:
            print(f"{erreur['bloc']} : {' '.join(erreur['message'].split())}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
