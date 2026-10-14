"""Foyer de l'investisseur : lecture et validation de `foyer.json` (option CLI `--foyer <chemin>`).

Le foyer ne s'écrit jamais à la main dans le JSON du bien : il vient de ce fichier, passé au moteur par le flag.
Chemin par défaut : `<dossier de données>/foyer.json` (`immo-data/` du répertoire courant, ou `IMMO_DATA_DIR`).

Forme du fichier : chaque valeur est une feuille `{"valeur": ..., "source": "...", "date": "AAAA-MM-JJ"}` ; une
source ou une date encore « à remplir » (gabarit) est refusée, la date doit être une vraie date AAAA-MM-JJ.

    annee                              année des revenus étudiée (entier)
    tmi                                taux marginal d'imposition du foyer (0 à 0,45)
    revenus_activite_mensuels          revenus d'activité nets après impôt du foyer, €/mois
    loyers_existants_mensuels          loyers HC des biens déjà loués, €/mois (baux en cours)
    revenus_fonciers_bruts_existants   revenus fonciers bruts annuels des biens déjà détenus, €
    a_un_bien_ij                       le foyer détient-il un logement au statut du bailleur privé (CGI 31 I-1° i/j) ?
    ponderation_loyers                 (optionnelle) part des loyers retenue par la banque (0 à 1)
    foncier_existant.R / .I / .C       recettes, intérêts et autres charges fonciers annuels des biens détenus, €
    foncier_existant.report_disponible déficit foncier reportable disponible, €
    mensualites.actuelle               somme des mensualités de crédit en cours, assurances comprises, €/mois
    mensualites.future                 la même une fois tous les prêts amortissables (prêt relais, différé ou
                                       anticipation terminés) ; égale à `actuelle` si aucune ne change
    mensualites.nb_prets               nombre de prêts en cours

Aucune valeur n'est complétée par défaut : une clé absente ou invalide lève `ValueError` en la nommant.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

NOM_FICHIER = "foyer.json"
CHAMPS_FEUILLE = ("valeur", "source", "date")
TMI_MAX = 0.45
A_REMPLIR = "à remplir"


def chemin_par_defaut() -> Path:
    from .donnees import fichier
    return fichier(NOM_FICHIER)


def _feuille(brut: dict, chemin: str, fichier: str):
    noeud = brut
    for cle in chemin.split("."):
        if not isinstance(noeud, dict) or cle not in noeud:
            raise ValueError(f"{fichier} : clé requise absente : {chemin} (forme : {{\"valeur\": ..., \"source\": "
                             "\"...\", \"date\": \"AAAA-MM-JJ\"}, voir templates/foyer.json)")
        noeud = noeud[cle]
    if not isinstance(noeud, dict) or "valeur" not in noeud:
        raise ValueError(f"{fichier} : {chemin} doit être un objet {{valeur, source, date}}")
    manquants = [c for c in ("source", "date") if not isinstance(noeud.get(c), str) or not noeud[c].strip()]
    if manquants:
        raise ValueError(f"{fichier} : {chemin} sans {' ni '.join(manquants)} (chaque valeur du foyer est sourcée "
                         "et datée)")
    for champ in ("valeur", "source", "date"):
        if isinstance(noeud.get(champ), str) and A_REMPLIR in noeud[champ].casefold():
            raise ValueError(f"{fichier} : {chemin}.{champ} vaut encore « à remplir » : renseigner la valeur, sa "
                             "source (pièce justificative) et sa date (AAAA-MM-JJ)")
    try:
        date.fromisoformat(noeud["date"].strip())
    except ValueError as exc:
        raise ValueError(f"{fichier} : {chemin}.date doit être une date AAAA-MM-JJ (reçu {noeud['date']!r})") from exc
    return noeud["valeur"]


def _nombre(brut: dict, chemin: str, fichier: str, *, mini: float = 0.0, maxi: float | None = None,
            entier: bool = False) -> float:
    v = _feuille(brut, chemin, fichier)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{fichier} : {chemin}.valeur doit être un nombre fini (reçu {v!r})")
    if entier and v != int(v):
        raise ValueError(f"{fichier} : {chemin}.valeur doit être un entier (reçu {v!r})")
    if v < mini or (maxi is not None and v > maxi):
        bas, haut = format(mini, "g"), format(maxi, "g") if maxi is not None else None
        borne = f"entre {bas} et {haut}" if haut is not None else f"supérieur ou égal à {bas}"
        raise ValueError(f"{fichier} : {chemin}.valeur doit être {borne} (reçu {v!r})")
    return int(v) if entier else float(v)


def valider(brut: dict, fichier: str = NOM_FICHIER) -> dict:
    """Contexte du foyer, à la forme attendue par `analyser(..., contexte_foyer=...)`, depuis le JSON brut."""
    if not isinstance(brut, dict):
        raise ValueError(f"{fichier} : objet JSON attendu à la racine")
    annee = _nombre(brut, "annee", fichier, mini=2000, maxi=2100, entier=True)
    a_un_bien_ij = _feuille(brut, "a_un_bien_ij", fichier)
    if not isinstance(a_un_bien_ij, bool):
        raise ValueError(f"{fichier} : a_un_bien_ij.valeur doit être true ou false (reçu {a_un_bien_ij!r})")
    actuelle = _nombre(brut, "mensualites.actuelle", fichier)
    future = _nombre(brut, "mensualites.future", fichier)
    nb_prets = _nombre(brut, "mensualites.nb_prets", fichier, entier=True)
    if nb_prets == 0 and (actuelle or future):
        raise ValueError(f"{fichier} : mensualites.nb_prets vaut 0 mais une mensualité est non nulle")
    ctx = {
        "annee": annee,
        "tmi": _nombre(brut, "tmi", fichier, maxi=TMI_MAX),
        "revenus_fonciers_bruts_existants": _nombre(brut, "revenus_fonciers_bruts_existants", fichier),
        "a_un_bien_ij": a_un_bien_ij,
        "foncier_existant": {
            "R": _nombre(brut, "foncier_existant.R", fichier),
            "I": _nombre(brut, "foncier_existant.I", fichier),
            "C": _nombre(brut, "foncier_existant.C", fichier),
            "report_disponible": _nombre(brut, "foncier_existant.report_disponible", fichier),
        },
        "mensualites": {"actuelle": actuelle, "future": future, "nb_prets": nb_prets},
        "revenus_activite_mensuels": _nombre(brut, "revenus_activite_mensuels", fichier),
        "loyers_existants_mensuels": _nombre(brut, "loyers_existants_mensuels", fichier),
    }
    if "ponderation_loyers" in brut:
        ctx["ponderation_loyers"] = _nombre(brut, "ponderation_loyers", fichier, maxi=1.0)
    return ctx


def _chemins_dates(brut: dict, prefixe: str = ""):
    for cle, val in brut.items():
        if isinstance(val, dict) and "date" in val and "valeur" in val:
            yield (prefixe + cle, str(val["date"]))
        elif isinstance(val, dict):
            yield from _chemins_dates(val, prefixe + cle + ".")


def charger(chemin: str | Path | None = None) -> dict:
    """Lit `foyer.json` (chemin par défaut : `immo-data/foyer.json`) et rend le contexte validé."""
    cible = Path(chemin) if chemin is not None else chemin_par_defaut()
    try:
        texte = cible.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"foyer introuvable : {cible} (copier templates/foyer.json dans immo-data/foyer.json et le "
                         "remplir, ou passer --foyer <chemin>)") from exc
    except OSError as exc:
        raise ValueError(f"foyer illisible : {cible} ({exc})") from exc
    try:
        brut = json.loads(texte)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{cible} : JSON invalide ({exc})") from exc
    return valider(brut, cible.name)


def contexte(chemin: str | Path | None = None) -> dict:
    """Alias de `charger` : contexte du foyer à la forme attendue par `analyser`."""
    return charger(chemin)


def date_la_plus_ancienne(chemin: str | Path | None = None) -> tuple[str, date] | None:
    """(clé, date) de la plus ancienne date AAAA-MM-JJ du fichier, ou None si aucune n'est lisible."""
    cible = Path(chemin) if chemin is not None else chemin_par_defaut()
    brut = json.loads(cible.read_text(encoding="utf-8"))
    dates = []
    for cle, texte in _chemins_dates(brut):
        try:
            dates.append((cle, date.fromisoformat(texte)))
        except ValueError:
            continue
    return min(dates, key=lambda d: d[1]) if dates else None


def bloc_hcsf(ctx: dict, ponderation: float) -> dict:
    """Bloc `foyer` du taux d'effort : mensualité FUTURE (prêts en cours pris à leur mensualité d'amortissement)
    et revenus.

    revenus_nets_mensuels = revenus d'activité + ponderation × loyers HC existants. La pondération est celle de
    foyer.json (sinon le défaut de params.json) : la même vaut pour les loyers existants et pour le loyer du bien
    étudié.
    """
    return {"revenus_nets_mensuels": ctx["revenus_activite_mensuels"] + ponderation * ctx["loyers_existants_mensuels"],
            "mensualites_existantes": ctx["mensualites"]["future"],
            "ponderation_loyers": ponderation}
