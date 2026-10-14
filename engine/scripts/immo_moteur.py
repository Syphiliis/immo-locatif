#!/usr/bin/env python3
"""Lanceur du moteur immo : mêmes arguments, même sortie et mêmes codes que `python -m src.immo`.

`python -m src.immo` dépend du répertoire courant : si celui-ci a son propre paquet `src/`, c'est lui qui est
importé. Ce lanceur met `engine/` en TÊTE de `sys.path`, puis exécute `src.immo.__main__`.

Usage :
  python3 engine/scripts/immo_moteur.py --bien <bien.json> [--foyer [<foyer.json>]]
"""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ENGINE))
    for nom in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[nom]  # un `src` étranger déjà importé ne doit pas masquer celui du moteur
    from src.immo.__main__ import main as main_moteur
    return main_moteur(argv)


if __name__ == "__main__":
    raise SystemExit(main())
