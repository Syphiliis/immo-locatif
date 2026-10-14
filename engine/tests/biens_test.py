"""Biens de test complets : fixture FICTIVE + blocs `foyer` / `fiscal` ajoutés ici, jamais écrits dans les fixtures.

Le foyer d'un vrai bien vient de `foyer.json` (option `--foyer`) ; les fixtures `tests/fixtures/immo/bien_fictif*.json`
n'en portent donc aucun. Les tests unitaires du taux d'effort et de la fiscalité, qui ont besoin d'un foyer sans
passer par `foyer.json`, lisent ici une copie complétée, écrite dans un dossier temporaire au premier import.
"""
from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "immo"
FOYER_DE_TEST = {"revenus_nets_mensuels": 5000, "mensualites_existantes": 1000, "ponderation_loyers": 0.7}
FISCAL_DE_TEST = {"tmi": 0.14, "annee_revenus": 2026}
BLOCS = {
    "bien_fictif.json": {"foyer": FOYER_DE_TEST},
    "bien_fictif_bailleur_prive.json": {"foyer": FOYER_DE_TEST, "fiscal": FISCAL_DE_TEST},
    "bien_fictif_differe_27ans.json": {"foyer": FOYER_DE_TEST},
    "bien_fictif_incomplet.json": {"foyer": FOYER_DE_TEST},
    "bien_fictif_sci_is.json": {"fiscal": FISCAL_DE_TEST},
    "bien_fictif_sci_is_sortie.json": {"fiscal": FISCAL_DE_TEST},
}
_DOSSIER = Path(tempfile.mkdtemp(prefix="biens-test-"))
atexit.register(shutil.rmtree, _DOSSIER, True)


def brut(nom: str) -> dict:
    """La fixture complétée de ses blocs de test (nouvel objet à chaque appel)."""
    d = json.loads((FIXTURES / nom).read_text(encoding="utf-8"))
    d.update(json.loads(json.dumps(BLOCS.get(nom, {}))))
    return d


def chemin(nom: str) -> Path:
    """Chemin d'une copie complétée de la fixture `nom`, au même format (indentation 2)."""
    cible = _DOSSIER / nom
    if not cible.exists():
        cible.write_text(json.dumps(brut(nom), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cible
