"""Dossier de données de l'utilisateur : `immo-data/` du répertoire courant, ou la variable `IMMO_DATA_DIR`.

Il porte `profil.json`, `foyer.json`, `params_local.json` (optionnel), `MARCHE.md`, `pistes.json`, `analyses/`,
`bruts/`, `shortlist.md` et `negociations/`. Le moteur et les scripts le résolvent ici, et nulle part ailleurs.
"""
from __future__ import annotations

import os
from pathlib import Path

VARIABLE = "IMMO_DATA_DIR"
NOM_PAR_DEFAUT = "immo-data"


def dossier_donnees() -> Path:
    """`$IMMO_DATA_DIR` s'il est défini et non vide, sinon `./immo-data` (répertoire courant)."""
    env = os.environ.get(VARIABLE, "").strip()
    return Path(env).expanduser() if env else Path.cwd() / NOM_PAR_DEFAUT


def fichier(nom: str) -> Path:
    """Chemin d'un fichier du dossier de données (il peut ne pas exister)."""
    return dossier_donnees() / nom
