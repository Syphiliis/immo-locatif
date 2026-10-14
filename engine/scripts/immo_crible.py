#!/usr/bin/env python3
"""Crible Leboncoin de `/immo` : trie des pages de résultats lues au navigateur, sans aucun accès au site.

Entrée : des fichiers JSON, chacun une liste d'annonces telle que `searchData.ads` de `__NEXT_DATA__` (une page ou une
passe), sauvegardés depuis le navigateur selon la référence `crible.md` du skill `immo`. Le script ne fait AUCUN accès
réseau : il ne lit que ces fichiers, le profil de l'investisseur (`immo-data/profil.json`) et des fiches de données ouvertes.

Il réconcilie les comptes (lues, identifiants uniques, doublons entre pages, écartées par motif, retenues), écarte (motifs
listés avec l'annonce : prix, type, bien non résidentiel probable, surface minimale, neuf probable, viager probable), pose
des drapeaux sans écarter (bien mixte, €/m² sous le premier décile, commune hors de la décision `zone` du profil, date
affichée), signale les doublons probables sans jamais les fusionner, estime un rendement brut indicatif (loyer de `src.immo.loyer.loyer_3r`, importé, jamais réécrit,
divisé par prix × 1,08), classe, puis écrit :
- `--out` : le scan en Markdown, au format des scans de `immo-data/bruts/` ;
- `--pistes-out` : des pistes PROPOSÉES, aux clés de `immo-data/pistes.json`.
Il n'écrit ni dans `pistes.json` ni dans `bruts/` (refus, code 2, quelle que soit la casse du chemin : le volume macOS ne
la distingue pas), ni sur un lien physique, ni sur une de ses entrées : écrire dans un dossier temporaire, relire, puis laisser l'écrivain
désigné de ces fichiers les verser. Un champ d'annonce illisible devient une absence dite (« surface absente ou illisible »), jamais une
valeur devinée ; une annonce sans identifiant de 10 chiffres arrête le crible (code 2). Le dossier de données
(`pistes.json`, `bruts/`, `profil.json`) est `$IMMO_DATA_DIR`, sinon `./immo-data`.

Usage :
  python3 engine/scripts/immo_crible.py --pages p1.json p2.json [--profil immo-data/profil.json] \
      [--prix-max 150000] [--types 1,5] [--surface-min 40] [--fiche <fiche-opendata.json> ...] \
      [--volume-affiche 67] [--top 8] [--date AAAA-MM-JJ] [--source bruts/scan-lbc-<...>.md] \
      [--out scan.md] [--pistes-out pistes-proposees.json]

Codes de sortie : 0 ; 2 si une entrée est illisible, un argument invalide ou une écriture refusée.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from immo_entree import Illisible, _decisions, _json, profil_par_defaut  # noqa: E402
from src.immo.donnees import dossier_donnees  # noqa: E402
from src.immo.loyer import loyer_3r  # noqa: E402

# --- Seuils et règles de méthode : constantes nommées, dites dans chaque sortie ------------------------------------
# Doublon probable, même commune : écart relatif au plus grand des deux, une tolérance par grandeur : surface à ±5 % et
# prix à ±10 % (une même maison republiée par deux agences, à quelques mètres carrés et quelques pour cent de prix
# près, doit être vue).
TOLERANCE_DOUBLON_SURFACE = 0.05
TOLERANCE_DOUBLON_PRIX = 0.10
POINT_PARTAGE_MAX = 3             # un point partagé par plus de 3 annonces est un centre de commune, pas un point précis
DECILE_QUANTILES = 10             # premier décile = premier des 9 quantiles de `statistics.quantiles(n=10, inclusive)`
MIN_RETENUES_DECILE = 10          # sous 10 retenues avec un €/m², un décile ne veut rien dire : non calculé
NB_CANDIDATS = 8                  # « /immo rapide sur les 5 à 8 meilleurs » : le haut du classement
CHARGES_MAISON_MENSUELLES = 0.0   # charges récupérables d'une maison (hypothèse dite) : loyer HC = loyer CC
# Rendement brut indicatif = loyer réaliste annuel ÷ (prix × COEF_COUT_ACQUISITION) : convention du crible, qui approche
# les frais d'acquisition de l'ancien ; le moteur de `/immo`, lui, divise par le coût total réel.
COEF_COUT_ACQUISITION = 1.08

# Types Leboncoin (`attributes.real_estate_type`), tels que relevés en octobre 2026 : 1 « Maison », 5 « Autre »
# (`real_estate_type=5` : « Type de bien : Autre » à l'écran). Un autre code se lit tel quel.
TYPES_LBC = {"1": "Maison", "5": "Autre"}
# `cible` du profil -> types Leboncoin où ce bien se publie : les immeubles d'agence sont en « Autre », les maisons de
# ville en « Maison » (une recherche « Maison » + « Autre » s'écrit `real_estate_type=1,5`).
# Seules ces deux correspondances ont été relevées sur les pages de résultats : une autre cible (appartement, maison
# isolée...) n'est pas devinée, elle se crible avec --types.
TYPES_PAR_CIBLE = {"immeuble_de_rapport": {"1", "5"}, "maison_de_ville": {"1"}}
TYPE_AUTRE = "5"                  # `real_estate_type` « Autre » (voir TYPES_LBC) : le seul type où le motif non résidentiel vaut
# Bien non résidentiel : écarté (péniche, garage, mobil-home sur terrain...). Le
# motif ne vaut que pour le type 5 « Autre » (où se publient aussi les immeubles d'agence) et seulement si le titre ou
# la description ne nomme aucun logement : « Immeuble avec garage » reste retenu.
MOTS_NON_RESIDENTIELS = ("péniche", "bateau", "mobil-home", "garage", "box", "parking", "terrain", "hangar", "entrepôt")
MOTS_LOGEMENT = ("maison", "immeuble", "appartement", "logement", "studio", "pavillon")
# Logements nommés autrement, dans le sens prudent : un bien de type 5 n'est écarté que s'il nomme un bien non
# résidentiel ET aucun logement. Mots entiers ; casse, accents et pluriel ignorés (« lotissement » n'est pas « N lots »).
# Mots : maisonnette, appart, villa, longère, duplex, triplex, loft, « rapport locatif », T1 à T6, F1 à F6, « N pièces » ;
# appt, logt, habitation, fermette, corps de ferme ; propriété, bâtisse, chalet, bungalow, manoir, château, moulin, demeure,
# bastide, résidence, « hôtel particulier », « ensemble immobilier » ; ni « mas », ni « bien immobilier », ni « ferme » seul. « lot » seul ne dit pas un logement (« Lot de parkings », « Lot de 3 garages » restent écartés) : « N lots »,
# avec un nombre avant « lot », en dit un. Effet connu : un nom de rue ou de résidence (« rue du Moulin », « Résidence Les
# Pins », « propriété privée ») retient un bien non résidentiel qui le contient.
MOTS_LOGEMENT_AJOUTES = ("maisonnette", "appart", "appt", "logt", "villa", "longère", "duplex", "triplex", "loft", "habitation",
                         "fermette", "corps de ferme", "rapport locatif",
                         "propriété", "bâtisse", "chalet", "bungalow", "manoir", "château", "moulin", "demeure", "bastide",
                         "résidence", "hôtel particulier", "ensemble immobilier")
FORMES_LOGEMENT_AJOUTEES = {"T1 à T6": r"t[1-6]", "F1 à F6": r"f[1-6]", "N pièces": r"\d+ pieces?",
                            "N lots": r"\d+ lots?"}                                           # sur texte normalisé
# Autre orthographe d'un mot de ces listes, en fragment de motif sur le texte normalisé : aucun mot de plus. « mobil-home »
# s'écrit aussi « mobile home » ou « mobile-home ».
VARIANTES_ORTHOGRAPHE = {"mobil-home": r"mobile? ?home"}
# Neuf de constructeur. Signal fort : `immo_sell_type = new`, lu dans la page de résultats. Règle de repli : « Maison N
# pièces », DPE A, sans honoraires ; « sans honoraires » se lit « aucun honoraire à la charge de l'acquéreur » (honoraires
# d'un professionnel : `fees_at_the_expanse_of` = `seller`, `fees_price` nul ou absent, forme relevée en octobre 2026).
TYPE_VENTE_NEUF = "new"
RE_NEUF_TITRE = re.compile(r"^\s*maison\s+\d+\s+pi[eè]ces?\b", re.I)
# Viager (singulier, pluriel, « viagère ») : le prix affiché est un bouquet, pas le prix du bien.
RE_VIAGER = re.compile(r"\bviag(?:er|[eè]re)s?\b", re.I)
RE_MIXTE = re.compile(r"\b(local|locaux|commerce|commerces|commercial|commerciale|commerciaux|commerciales|"
                      r"boutique|boutiques)\b", re.I)
RE_LOTS = re.compile(r"\b(immeubles?|rapport|lots?|logements?|appartements?|studios?)\b", re.I)
URL_ANNONCE = "https://www.leboncoin.fr/ad/ventes_immobilieres/{id}"
CHAMPS_DE_CONTENU = ("prix", "surface", "type_code", "titre", "type_vente", "commune", "dpe")   # un même identifiant relu
MOTIFS = ("prix absent", "hors prix", "hors type", "non résidentiel probable", "surface sous le minimum", "neuf probable",
          "viager probable")                  # l'ordre est celui des motifs : le premier de la liste l'emporte
def proteges() -> tuple[Path, Path]:
    """`pistes.json` et `bruts/` du dossier de données (`$IMMO_DATA_DIR` ou `./immo-data`), résolus à l'appel."""
    dossier = dossier_donnees()
    return dossier / "pistes.json", dossier / "bruts"


# --- Profil -------------------------------------------------------------------------------------------------------

def _exceptions(decision: dict, cle: str) -> dict[str, dict]:
    """Exceptions d'une décision du profil, par identifiant d'annonce (toujours une chaîne)."""
    brutes = decision.get("exceptions", [])
    if not isinstance(brutes, list):
        raise Illisible(f"profil : les `exceptions` de {cle} doivent être une liste (reçu {type(brutes).__name__})")
    detail = {}
    for e in brutes:
        if not isinstance(e, dict) or e.get("annonce") in (None, ""):
            raise Illisible(f"profil : exception de {cle} sans `annonce` : {e!r}")
        ident = int(e["annonce"]) if isinstance(e["annonce"], float) and e["annonce"].is_integer() else e["annonce"]
        detail[str(ident).strip()] = e
    return detail


def regles_du_profil(profil: dict) -> dict:
    """Plafond de prix, types Leboncoin admis et leurs exceptions, lus dans `profil.json` (rien n'est recopié)."""
    d = _decisions(profil)
    try:
        cible, prix = d["cible"], d["premier_achat_prix_max"]
        if isinstance(prix["valeur"], bool):
            raise ValueError("un booléen n'est pas un plafond")
        plafond, valeur_cible = float(prix["valeur"]), list(cible["valeur"])
        if not math.isfinite(plafond) or plafond <= 0:
            raise ValueError(f"plafond {plafond!r} : un nombre fini et positif est attendu")
    except (KeyError, TypeError, ValueError) as exc:
        raise Illisible(f"profil : décisions `cible` et `premier_achat_prix_max` valides attendues "
                        f"(premier_achat_prix_max.valeur : nombre fini positif) ({type(exc).__name__}: {exc})") from exc
    types: set[str] = set()
    for c in valeur_cible:
        if c not in TYPES_PAR_CIBLE:
            raise Illisible(f"profil : cible « {c} » sans type Leboncoin connu (connus : {', '.join(TYPES_PAR_CIBLE)}) ; "
                            "cibles reconnues par le crible : immeuble_de_rapport (types 1 et 5), maison_de_ville (type 1) ; pour une "
                            "autre cible (appartement, maison isolée...), passer --types avec les codes real_estate_type "
                            "relevés sur la page de recherche (ex. --types 1,5)")
        types |= TYPES_PAR_CIBLE[c]
    detail_prix, detail_types = _exceptions(prix, "premier_achat_prix_max"), _exceptions(cible, "cible")
    return {"plafond": plafond, "types": types, "detail_prix": detail_prix, "detail_types": detail_types,
            "exceptions_prix": set(detail_prix), "exceptions_types": set(detail_types), "zone": zone_du_profil(d)}


def zone_du_profil(decisions: dict) -> list[str] | None:
    """Communes de la décision `zone` du profil (`commune_centre` puis `communes`), ou None sans décision `zone`.

    Une commune s'écrit par son nom, ou par un objet `{"nom": ..., "code_insee": ...}`. La zone ne sert qu'à poser un
    drapeau « hors zone » : la recherche Leboncoin par rayon ramène des communes voisines, que l'investisseur juge.
    """
    if "zone" not in decisions:
        return None
    valeur = decisions["zone"].get("valeur")
    if not isinstance(valeur, dict):
        raise Illisible("profil : la décision `zone` porte un objet {commune_centre, code_insee, departement, communes}")
    brutes = [valeur.get("commune_centre")] + list(valeur.get("communes") or [])
    noms = []
    for c in brutes:
        nom = c.get("nom") if isinstance(c, dict) else c
        if isinstance(nom, str) and nom.strip() and nom.strip() not in noms:
            noms.append(nom.strip())
    if not noms:
        raise Illisible("profil : décision `zone` sans commune (commune_centre ou communes)")
    return noms


def _types_explicites(texte: str) -> set[str]:
    etiquettes = {v.lower(): k for k, v in TYPES_LBC.items()}
    codes = set()
    for jeton in (t.strip().lower() for t in texte.split(",") if t.strip()):
        if jeton.isascii() and jeton.isdigit():
            codes.add(jeton)
        elif jeton in etiquettes:
            codes.add(etiquettes[jeton])
        else:
            raise Illisible(f"--types : « {jeton} » inconnu (codes `real_estate_type` : "
                            f"{', '.join(f'{k} {v}' for k, v in TYPES_LBC.items())} ; un autre code s'écrit tel quel)")
    if not codes:
        raise Illisible("--types : aucun type donné")
    return codes


# --- Lecture des annonces -----------------------------------------------------------------------------------------

def _norm(texte: str | None) -> str:
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", texte or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sans_accent.casefold()).strip()


def _nombre(valeur) -> float | None:
    """Nombre fini et strictement positif, sinon `None` (une absence, jamais une valeur devinée)."""
    if isinstance(valeur, bool):
        return None
    try:
        n = float(str(valeur).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def _coordonnee(valeur) -> float | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur):
        return None
    return float(valeur)


def _identifiant(brute: dict, repere: str) -> str:
    valeur = brute.get("list_id")
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    if valeur not in (None, "", 0):
        texte = str(valeur).strip() if isinstance(valeur, (int, str)) and not isinstance(valeur, bool) else ""
        if not re.fullmatch(r"[0-9]{10}", texte):
            raise Illisible(f"{repere} : identifiant invalide {valeur!r} (`list_id` à 10 chiffres attendu)")
        return texte
    m = re.search(r"\b[0-9]{10}\b", str(brute.get("url") or ""))
    if not m:
        raise Illisible(f"{repere} : identifiant absent (ni `list_id`, ni `url` à identifiant de 10 chiffres)")
    return m.group(0)


def _annonce(brute, repere: str) -> dict:
    """Annonce normalisée depuis un élément de `searchData.ads` (champs réels : voir `references/crible.md`)."""
    if not isinstance(brute, dict):
        raise Illisible(f"{repere} : objet d'annonce attendu, reçu {type(brute).__name__}")
    ident = _identifiant(brute, repere)
    liste = brute.get("attributes") if isinstance(brute.get("attributes"), list) else []
    attrs = {t.get("key"): t.get("value") for t in liste if isinstance(t, dict)}
    loc = brute.get("location") if isinstance(brute.get("location"), dict) else {}
    prix_liste = brute.get("price")
    prix = _nombre(prix_liste[0] if isinstance(prix_liste, list) and prix_liste else prix_liste)
    surface = _nombre(attrs.get("square"))
    ancien = _nombre(attrs.get("old_price"))
    taxe = _nombre(attrs.get("property_tax"))
    dpe_brut = str(attrs.get("energy_rate") or "").strip()
    lat, lng = _coordonnee(loc.get("lat")), _coordonnee(loc.get("lng"))
    if lat is None or lng is None:
        lat = lng = None
    ville = loc.get("city")
    commune = (ville.strip() if isinstance(ville, str) else "") or "?"
    coordonnees_illisibles = lat is None and (loc.get("lat") not in (None, "") or loc.get("lng") not in (None, ""))
    date = str(brute.get("first_publication_date") or "")[:10]
    url = brute.get("url") if isinstance(brute.get("url"), str) and ident in brute["url"] else URL_ANNONCE.format(id=ident)
    return {
        "id": ident, "url": url, "titre": str(brute.get("subject") or "").strip(), "corps": str(brute.get("body") or ""),
        "commune": commune, "commune_connue": commune != "?", "code_postal": loc.get("zipcode"),
        "prix": None if prix is None or int(prix) < 1 else int(prix), "surface": surface,
        "surface_brute": attrs.get("square") if surface is None and attrs.get("square") not in (None, "") else None,
        "prix_m2": prix / surface if prix and surface else None,
        "dpe": dpe_brut.upper() if dpe_brut.upper() in tuple("ABCDEFG") else None, "dpe_brut": dpe_brut or None,
        "baisse": ({"ancien_prix": int(ancien), "pourcent": (prix - ancien) / ancien * 100}
                   if prix and ancien and ancien > prix else None),
        "taxe_fonciere": None if taxe is None else int(taxe),
        "type_code": None if attrs.get("real_estate_type") is None else str(attrs["real_estate_type"]),
        "type_vente": str(attrs.get("immo_sell_type") or "").strip().lower() or None,
        "lat": lat, "lng": lng, "coordonnees_illisibles": coordonnees_illisibles, "point_ville": loc.get("source") == "city" or loc.get("is_shape") is True,
        "date_affichee": date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None,
        "honoraires_acquereur": (attrs.get("fees_at_the_expanse_of") == "buyer"
                                 or _nombre(attrs.get("fees_price")) is not None),
    }


def charger_pages(chemins: list[str]) -> list[list]:
    """Pages JSON (chacune une liste d'annonces) ; `Illisible` nomme le fichier fautif."""
    pages = []
    for chemin in chemins:
        try:
            page = json.loads(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Illisible(f"{chemin} : {type(exc).__name__} : {exc}") from exc
        if not isinstance(page, list):
            raise Illisible(f"{chemin} : liste d'annonces attendue (`searchData.ads`), reçu {type(page).__name__}")
        pages.append(page)
    return pages


# --- Règles d'écart, drapeaux, rendement --------------------------------------------------------------------------

def _eur(n) -> str:
    return f"{n:,.0f} €".replace(",", " ")


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _milliers(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def _taux(x: float) -> str:
    return f"{x * 100:g} %"


def _coef(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _surface(s) -> str:
    return "surface absente" if s is None else f"{s:g} m²"


def _alternance(mots: tuple[str, ...]) -> list[tuple[str, re.Pattern]]:
    """Un motif par mot de la liste, pour un texte passé par `_norm` : accents et casse ignorés, tiret ou espace facultatif
    (« mobil-home », « mobilhome »), pluriel en s, x ou es (« bateaux », « boxes »), orthographe de `VARIANTES_ORTHOGRAPHE`."""
    return [(mot, re.compile(r"\b(?:" + VARIANTES_ORTHOGRAPHE.get(mot, _norm(mot).replace(" ", " ?")) + r")(?:s|x|es)?\b"))
            for mot in mots]


_NON_RESIDENTIELS = _alternance(MOTS_NON_RESIDENTIELS)
_LOGEMENTS = _alternance((*MOTS_LOGEMENT, *MOTS_LOGEMENT_AJOUTES)) + [
    (libelle, re.compile(r"\b(?:" + motif + r")\b")) for libelle, motif in FORMES_LOGEMENT_AJOUTEES.items()]


def _non_residentiel_probable(a: dict) -> str | None:
    """Type « Autre » dont le titre ou la description nomme un bien non résidentiel sans nommer un logement."""
    if a["type_code"] != TYPE_AUTRE:
        return None
    texte = _norm(f"{a['titre']} {a['corps']}")
    nomme = next((mot for mot, motif in _NON_RESIDENTIELS if motif.search(texte)), None)
    if nomme is None or any(motif.search(texte) for _, motif in _LOGEMENTS):
        return None
    return (f"type {TYPE_AUTRE} (Autre) : « {nomme} » dans le titre ou la description, aucun logement nommé "
            "(liste dans « Seuils de méthode ») : bien non résidentiel probable")


def _neuf_probable(a: dict) -> str | None:
    if a["type_vente"] == TYPE_VENTE_NEUF:
        return "`immo_sell_type` = new : neuf de constructeur (type de vente lu dans la page de résultats)"
    if a["type_vente"] is not None:
        return None     # un type de vente renseigné et différent de `new` prime sur la règle du titre
    if RE_NEUF_TITRE.match(a["titre"]) and a["dpe"] == "A" and not a["honoraires_acquereur"]:
        return ("titre « Maison N pièces », DPE A, aucun honoraire à la charge de l'acquéreur, aucun type de vente "
                "renseigné : neuf de constructeur")
    return None


def _viager_probable(a: dict) -> str | None:
    if RE_VIAGER.search(f"{a['titre']} {a['corps']}") or "viager" in (a["type_vente"] or ""):
        return ("« viager » dans le titre, la description ou le type de vente : le prix affiché est un bouquet, "
                "pas le prix du bien")
    return None


def _motif(a: dict, plafond: float, types: set, exc_prix: set, exc_types: set, surface_min) -> tuple[str, str] | None:
    if a["prix"] is None:
        return "prix absent", "prix absent ou illisible dans l'annonce : plafond non vérifiable"
    if a["prix"] >= plafond and a["id"] not in exc_prix:
        return "hors prix", f"prix non inférieur au plafond de {_eur(plafond)}"
    if a["type_code"] not in types and a["id"] not in exc_types:
        code = a["type_code"]
        nom = "type absent" if code is None else f"type {code} ({TYPES_LBC.get(code, 'libellé non relevé')})"
        return "hors type", f"{nom}, hors des types admis ({', '.join(sorted(types))})"
    if (non_residentiel := _non_residentiel_probable(a)):
        return "non résidentiel probable", non_residentiel
    if surface_min is not None and a["surface"] is not None and a["surface"] < surface_min:
        return "surface sous le minimum", f"{_surface(a['surface'])} sous {surface_min:g} m²"
    if (neuf := _neuf_probable(a)):
        return "neuf probable", neuf
    if (viager := _viager_probable(a)):
        return "viager probable", viager
    return None


def _rendement(a: dict, fiches: dict) -> tuple[float | None, str, dict | None]:
    """(rendement brut, texte, résultat de loyer_3r) : loyer réaliste annuel de `loyer_3r` ÷ (prix × 1,08) ; jamais deviné."""
    if a["type_code"] != "1" or RE_LOTS.search(a["titre"]):
        if a["type_code"] != "1":
            return None, "non calculé : type Autre, immeuble à lots inconnus ou autre bien (garage, péniche, mobilier…)", None
        return None, f"non calculé : immeuble ou bien à lots inconnus (titre : « {RE_LOTS.search(a['titre']).group(0)} »)", None
    if a["surface"] is None:
        return None, "non calculé : surface absente ou illisible", None
    fiche = fiches.get(_norm(a["commune"])) if a["commune_connue"] else None
    if fiche is None:
        return None, "non calculé : aucune fiche de données ouvertes pour la commune", None
    try:
        r = loyer_3r(fiche, "maison", a["surface"], CHARGES_MAISON_MENSUELLES)
    except (ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError, OverflowError) as exc:
        return None, f"non calculé : fiche inutilisable ({type(exc).__name__}: {exc})", None
    rendement = r["scenarios"]["realiste"]["loyer_hc"] * 12 / (a["prix"] * COEF_COUT_ACQUISITION)
    texte = f"{_pct(rendement)} brut indicatif (loyer réaliste annuel ÷ (prix × {_coef(COEF_COUT_ACQUISITION)}), " \
            "série maison, travaux à 0" + (", extrapolation)" if r["extrapolation"] else ")")
    return rendement, texte, r


def _ecart_dans(x: float, y: float, tolerance: float) -> bool:
    """Écart relatif au plus grand des deux : `|x - y| <= tolerance × max(x, y)`."""
    return abs(x - y) <= tolerance * max(x, y)


def _proche(a: dict, b: dict) -> bool:
    """Deux annonces (surface et prix connus) d'un doublon probable : surface et prix, chacun à sa tolérance."""
    return (_ecart_dans(a["surface"], b["surface"], TOLERANCE_DOUBLON_SURFACE)
            and _ecart_dans(a["prix"], b["prix"], TOLERANCE_DOUBLON_PRIX))


def _doublons(annonces: list[dict], points: Counter) -> list[dict]:
    """Groupes de doublons probables (composantes connexes des paires) ; chaque annonce garde sa ligne.

    Les paires se cherchent dans la commune (surface et prix, chacun à sa tolérance : `TOLERANCE_DOUBLON_SURFACE`,
    `TOLERANCE_DOUBLON_PRIX`) et au point précis, pas sur toutes les paires.
    """
    def precis(a):
        return a["lat"] is not None and not a["point_ville"] and points[(a["lat"], a["lng"])] <= POINT_PARTAGE_MAX
    parent = {a["id"]: a["id"] for a in annonces}

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    par_commune, par_point = defaultdict(list), defaultdict(list)
    for a in annonces:
        if a["commune_connue"]:
            par_commune[_norm(a["commune"])].append(a)
        if precis(a):
            par_point[(a["lat"], a["lng"])].append(a)
    raison_commune = (f"même commune, surface à ±{_taux(TOLERANCE_DOUBLON_SURFACE)} "
                      f"et prix à ±{_taux(TOLERANCE_DOUBLON_PRIX)}")
    paires: list[tuple[str, str, str]] = []
    for voisines in par_commune.values():
        for i, a in enumerate(voisines):
            for b in voisines[i + 1:]:
                if None not in (a["surface"], b["surface"], a["prix"], b["prix"]) and _proche(a, b):
                    paires.append((a["id"], b["id"], raison_commune))
    for voisines in par_point.values():
        for i, a in enumerate(voisines):
            paires += [(a["id"], b["id"], "même point précis") for b in voisines[i + 1:]]
    for x, y, _ in paires:
        parent[racine(x)] = racine(y)
    groupes: dict[str, list[str]] = {}
    for a in annonces:
        groupes.setdefault(racine(a["id"]), []).append(a["id"])
    sortie = []
    for ids in sorted(sorted(g) for g in groupes.values() if len(g) > 1):
        raisons = sorted({f"{min(x, y)} et {max(x, y)} : {r}" for x, y, r in paires if x in ids and y in ids})
        sortie.append({"ids": ids, "raisons": raisons})
    for n, g in enumerate(sortie, 1):
        g["groupe"] = f"G{n}"
    return sortie


# --- Crible -------------------------------------------------------------------------------------------------------

def cribler(pages: list[list], *, profil: dict, prix_max: float | None = None, types: set | None = None,
            surface_min: float | None = None, fiches=(), volume_affiche: int | None = None,
            noms_pages: list[str] | None = None) -> dict:
    regles = regles_du_profil(profil)
    for nom, valeur in (("--prix-max", prix_max), ("--surface-min", surface_min)):
        if valeur is not None and (not math.isfinite(float(valeur)) or float(valeur) <= 0):
            raise Illisible(f"{nom} : un nombre fini et positif est attendu (reçu {valeur})")
    plafond = regles["plafond"] if prix_max is None else float(prix_max)
    exc_prix = regles["exceptions_prix"] if prix_max is None else set()    # l'exception vaut pour le plafond du profil
    types_admis = regles["types"] if types is None else set(types)
    exc_types = regles["exceptions_types"] if types is None else set()
    zone_normee = None if regles["zone"] is None else {_norm(c) for c in regles["zone"]}
    par_commune = {}
    for f in fiches:
        nom = _norm(f.get("commune", {}).get("nom") if isinstance(f.get("commune"), dict) else None)
        if not nom:
            raise Illisible("fiche sans `commune.nom` : commune non identifiable")
        if nom in par_commune:
            raise Illisible(f"deux fiches pour la commune « {f['commune']['nom']} »")
        par_commune[nom] = f

    lues, uniques, contenus_differents = 0, {}, []
    for k, page in enumerate(pages, 1):
        nom = noms_pages[k - 1] if noms_pages else f"page {k}"
        for j, brute in enumerate(page, 1):
            lues += 1
            a = _annonce(brute, f"{nom}, annonce n° {j}")
            premiere = uniques.setdefault(a["id"], a)
            if premiere is not a:
                champs = {c: [premiere[c], a[c]] for c in CHAMPS_DE_CONTENU if premiere[c] != a[c]}
                if champs:
                    contenus_differents.append({"id": a["id"], "champs": champs})
    annonces = list(uniques.values())
    divergents = {c["id"]: c["champs"] for c in contenus_differents}

    ecartees, retenues = [], []
    for a in annonces:
        m = _motif(a, plafond, types_admis, exc_prix, exc_types, surface_min)
        if m:
            ecartees.append({**a, "motif": m[0], "detail": m[1]})
        else:
            retenues.append(a)

    points = Counter((a["lat"], a["lng"]) for a in annonces if a["lat"] is not None)
    points_partages = [{"lat": p[0], "lng": p[1], "ids": sorted(a["id"] for a in annonces if (a["lat"], a["lng"]) == p)}
                       for p, n in sorted(points.items()) if n > POINT_PARTAGE_MAX]
    doublons = _doublons(annonces, points)
    statut = {a["id"]: "retenue" for a in retenues} | {e["id"]: f"écartée ({e['motif']})" for e in ecartees}
    for g in doublons:
        g["statuts"] = {i: statut[i] for i in g["ids"]}
    groupe_de = {i: g for g in doublons for i in g["ids"]}

    valeurs_m2 = [a["prix_m2"] for a in retenues if a["prix_m2"] is not None]
    decile = (statistics.quantiles(valeurs_m2, n=DECILE_QUANTILES, method="inclusive")[0]
              if len(valeurs_m2) >= MIN_RETENUES_DECILE else None)
    loyers_utilises: dict[str, dict] = {}
    for a in retenues:
        a["rendement"], a["rendement_texte"], loyer = _rendement(a, par_commune)
        if loyer:
            loyers_utilises.setdefault(a["commune"], {k: loyer[k] for k in ("maille", "n", "millesime", "elasticite")})
        drapeaux = []
        if RE_MIXTE.search(f"{a['titre']} {a['corps']}"):
            drapeaux.append("bien mixte : comparer à la surface du DPE")
        if decile is not None and a["prix_m2"] is not None and a["prix_m2"] < decile:
            drapeaux.append(f"€/m² sous le premier décile des retenues ({_milliers(a['prix_m2'])} < {_milliers(decile)}) : "
                            "lire la description (grange, hangar, hors commune)")
        exceptions_levees = []
        if prix_max is None and a["prix"] >= plafond:
            exceptions_levees.append(regles["detail_prix"].get(a["id"]))
        if types is None and a["type_code"] not in types_admis:
            exceptions_levees.append(regles["detail_types"].get(a["id"]))
        for exc in filter(None, exceptions_levees):
            drapeaux.append(f"exception du profil : {exc.get('portee', 'portée non renseignée')} "
                            f"({exc.get('date', 'date non renseignée')})")
        if not a["commune_connue"]:
            drapeaux.append("commune absente (location.city) : jamais rapprochée d'un doublon par commune ni d'une fiche")
        elif zone_normee is not None and _norm(a["commune"]) not in zone_normee:
            drapeaux.append("hors zone du profil : commune absente de la décision `zone`")
        if a["coordonnees_illisibles"]:
            drapeaux.append("coordonnées illisibles : point non comparé aux autres annonces")
        if a["surface"] is None:
            lu = "" if a["surface_brute"] is None else f" ou illisible ({a['surface_brute']!r})"
            drapeaux.append(f"surface absente{lu} : €/m² et rendement non calculés")
        if loyer and loyer["extrapolation"]:
            drapeaux.append(f"extrapolation : {loyer['raison_extrapolation']}")
        if a["id"] in divergents:
            detail = ", ".join(f"{c} {v[0]} puis {v[1]}" for c, v in divergents[a["id"]].items())
            drapeaux.append(f"contenu différent entre pages : {detail} (première lecture gardée : relire la page)")
        if a["id"] in groupe_de:
            g = groupe_de[a["id"]]
            drapeaux.append(f"doublon probable {g['groupe']} avec {', '.join(i for i in g['ids'] if i != a['id'])}")
        if a["date_affichee"]:
            drapeaux.append(f"date affichée {a['date_affichee']} : une date ancienne est fiable, une récente ne prouve "
                            "rien (Leboncoin republie), ce n'est pas l'ancienneté")
        a["drapeaux"] = drapeaux
        a["groupe"] = groupe_de[a["id"]]["groupe"] if a["id"] in groupe_de else None
    inf = float("inf")
    retenues.sort(key=lambda a: (0, -a["rendement"], a["id"]) if a["rendement"] is not None
                  else (1, inf if a["prix_m2"] is None else a["prix_m2"], a["id"]))
    for rang, a in enumerate(retenues, 1):
        a["rang"] = rang

    comptes = {"lues": lues, "uniques": len(annonces), "doublons_entre_pages": lues - len(annonces),
               "ecartees": len(ecartees), "retenues": len(retenues),
               "par_motif": {m: n for m in MOTIFS if (n := sum(e["motif"] == m for e in ecartees))}}
    if volume_affiche is not None:
        comptes |= {"volume_affiche": volume_affiche, "ecart_volume": lues - volume_affiche}
    return {
        "comptes": comptes, "retenues": retenues, "ecartees": ecartees, "doublons": doublons,
        "points_partages": points_partages, "loyers": loyers_utilises, "contenus_differents": contenus_differents,
        "plafond": {"valeur": plafond, "origine": "profil" if prix_max is None else "--prix-max",
                    "exceptions": sorted(exc_prix)},
        "types": {"codes": sorted(types_admis), "origine": "profil" if types is None else "--types"},
        "zone": regles["zone"],
        "surface_min": surface_min, "communes_sans_fiche": sorted({a["commune"] for a in retenues
                                                                    if a["type_code"] == "1" and
                                                                    _norm(a["commune"]) not in par_commune}),
        "corps_lus": any(a["corps"] for a in annonces),
        "seuils": {"tolerance_doublon_surface": TOLERANCE_DOUBLON_SURFACE, "tolerance_doublon_prix": TOLERANCE_DOUBLON_PRIX,
                   "point_partage_max": POINT_PARTAGE_MAX,
                   "decile_prix_m2": decile, "min_retenues_decile": MIN_RETENUES_DECILE,
                   "retenues_avec_prix_m2": len(valeurs_m2), "charges_maison_mensuelles": CHARGES_MAISON_MENSUELLES,
                   "coef_cout_acquisition": COEF_COUT_ACQUISITION},
    }


# --- Pistes proposées ---------------------------------------------------------------------------------------------

def _question(a: dict, doublons: list[dict]) -> str:
    multi = a["type_code"] != "1" or RE_LOTS.search(a["titre"]) or RE_MIXTE.search(f"{a['titre']} {a['corps']}")
    q = ("Quelle est la surface et le loyer de chaque lot, et lesquels sont loués ?" if multi else
         "Depuis quand est-elle réellement en vente (ancienneté), et jusqu'où le vendeur peut-il baisser ?")
    groupe = next((g for g in doublons if a["id"] in g["ids"]), None)
    if groupe:
        autres = ", ".join(i for i in groupe["ids"] if i != a["id"])
        q += f" Même bien que {autres} ? Comparer les photos avant toute étude."
    decile = next((d for d in a.get("drapeaux", []) if "premier décile" in d), None)
    return q + (f" {decile[0].upper()}{decile[1:]}." if decile else "")


def proposer_pistes(res: dict, *, date: str, source: str, nb_candidats: int = NB_CANDIDATS) -> list[dict]:
    """Entrées au format de `pistes.json` : `candidat` pour le haut du classement, `remarquable` pour un €/m² sous le premier décile."""
    def commun(a, categorie):
        return {"id": a["id"], "url": a["url"], "titre": a["titre"], "commune": a["commune"], "prix": a["prix"],
                "surface": _surface(a["surface"]), "rendement": a["rendement_texte"], "source": source,
                "repere_le": date, "categorie": categorie}
    pistes = []
    for a in res["retenues"][:nb_candidats]:
        pistes.append({**commun(a, "candidat"), "question": _question(a, res["doublons"]), "rang": a["rang"]})
    for a in res["retenues"][nb_candidats:]:
        interet = next((d for d in a["drapeaux"] if "premier décile" in d), None)
        if interet:
            pistes.append({**commun(a, "remarquable"), "note": interet[0].upper() + interet[1:] + "."})
    return pistes


# --- Rendu Markdown -----------------------------------------------------------------------------------------------

def _cellule(texte) -> str:
    return str(texte).replace("|", "/").replace("\n", " ")


def rendre_markdown(res: dict, *, date: str, source: str, pages: list[str]) -> str:
    c, s, p = res["comptes"], res["seuils"], res["plafond"]
    types = ", ".join(f"{k} {TYPES_LBC.get(k, 'libellé non relevé')}" for k in res["types"]["codes"])
    origine = "profil" if p["origine"] == "profil" else "--prix-max explicite ; exceptions du profil non appliquées"
    origine_types = ("profil" if res["types"]["origine"] == "profil"
                     else "--types explicite ; exceptions du profil sur la cible non appliquées")
    L = [f"# Crible Leboncoin - {source} - {date}", "",
         f"> Crible de `engine/scripts/immo_crible.py` du {date} sur {len(pages)} fichier(s) lu(s) au navigateur "
         f"({', '.join(Path(x).name for x in pages)}). Le script ne fait aucun accès au site : il ne lit que ces fichiers.",
         f"> Plafond : prix strictement inférieur à {_eur(p['valeur'])} ({origine}"
         + (f" ; exceptions {', '.join(p['exceptions'])}" if p["exceptions"] else "") + f") ; types {types} "
         f"({origine_types}) ; surface minimale : "
         + (f"{res['surface_min']:g} m²" if res["surface_min"] is not None else "aucune") + " ; zone du profil : "
         + (", ".join(res["zone"]) if res.get("zone") else "non renseignée (aucun drapeau hors zone)") + ".", "",
         "## Comptes", "",
         f"- **{c['lues']} annonces lues** = {c['uniques']} identifiants uniques + {c['doublons_entre_pages']} doublons entre pages "
         "(un même identifiant relu, d'une page ou d'une passe à l'autre).",
         f"- **{c['uniques']} identifiants uniques** = {c['ecartees']} écartées + {c['retenues']} retenues."]
    if c["par_motif"]:
        L.append("- Écartées par motif (le premier motif de la liste l'emporte) : "
                 + ", ".join(f"{m} {n}" for m, n in c["par_motif"].items()) + ".")
    if "volume_affiche" in c:
        L.append(f"- Réconciliation du volume : volume affiché {c['volume_affiche']} contre {c['lues']} lues : "
                 + ("égal." if c["ecart_volume"] == 0 else f"**ATTENTION, écart de {c['ecart_volume']:+d}** : "
                    "relire les pages avant de conclure."))
    for d in res["contenus_differents"]:
        detail = ", ".join(f"{k} {v[0]} puis {v[1]}" for k, v in d["champs"].items())
        L.append(f"- **ATTENTION, contenu différent** pour {d['id']} entre deux lectures ({detail}) : première lecture "
                 "gardée, relire la page.")
    L += ["", "## Seuils de méthode", "",
          f"- Doublon probable : même commune, surface à ±{_taux(s['tolerance_doublon_surface'])} et prix à "
          f"±{_taux(s['tolerance_doublon_prix'])} (écart relatif au plus grand des deux), "
          "ou même point précis ; jamais fusionnés ; un groupe se forme par chaînage de paires, ses extrémités peuvent "
          "donc s'écarter de plus de ces seuils.",
          f"- Point précis : coordonnées identiques, partagées par au plus {s['point_partage_max']} annonces "
          f"(au-delà de {s['point_partage_max']} annonces, centre de commune) et jamais pour `location.source = city` "
          "(point d'un vendeur professionnel : décalé autour du centre de commune).",
          f"- Drapeau €/m² : sous le premier décile des retenues, `statistics.quantiles(n={DECILE_QUANTILES}, inclusive)`, "
          f"calculé dès {s['min_retenues_decile']} retenues avec surface : "
          + (f"**{s['decile_prix_m2']:,.0f} €/m²**".replace(",", " ") + f" sur {s['retenues_avec_prix_m2']} retenues."
             if s["decile_prix_m2"] is not None else f"non calculé ({s['retenues_avec_prix_m2']} retenues avec surface)."),
          f"- Non résidentiel probable : type {TYPE_AUTRE} « Autre » dont le titre ou la description nomme un bien non "
          f"résidentiel ({', '.join(MOTS_NON_RESIDENTIELS)}) sans nommer un logement ({', '.join(MOTS_LOGEMENT)} ; "
          f"aussi : {', '.join((*MOTS_LOGEMENT_AJOUTES, *FORMES_LOGEMENT_AJOUTEES))}) ; mots entiers, casse, accents et "
          "pluriel ignorés, « mobile home » compte comme « mobil-home » ; le type « Maison » n'est pas concerné.",
          "- Neuf probable : `immo_sell_type` = new (type de vente lu dans la page), ou, sans aucun "
          "type de vente renseigné, titre « Maison N pièces », DPE A et aucun honoraire à la charge de l'acquéreur (règle de "
          "repli) : un type de vente renseigné et différent de new l'emporte sur cette règle de titre.",
          "- Viager probable : « viager » ou « rente viagère » dans le titre ou la description, ou un `immo_sell_type` viager "
          "(valeur non observée) : le prix affiché est un bouquet.",
          "- Rendement brut indicatif = loyer réaliste annuel de `src.immo.loyer.loyer_3r` (série `maison`, "
          f"charges récupérables {_eur(s['charges_maison_mensuelles'])}/mois, hypothèse) divisé par (prix annoncé × "
          f"{_coef(s['coef_cout_acquisition'])}), travaux à 0 : convention du crible, qui approche les frais "
          "d'acquisition de l'ancien ; le moteur de `/immo`, lui, divise par le coût total "
          "réel. Immeuble ou bien à lots inconnus : non calculé. Série maison : toujours une extrapolation.", ""]
    for commune, l in sorted(res["loyers"].items()):
        elasticite = f"{l['elasticite']:.4f}".replace(".", ",")
        L.append(f"- Loyers {commune} : carte ANIL {l['millesime']}, maille {l['maille']}, n = {l['n']}, "
                 f"élasticité {elasticite}.")
    if res["communes_sans_fiche"]:
        L.append(f"- Aucune fiche de données ouvertes pour : {', '.join(res['communes_sans_fiche'])} (rendement non calculé).")
    if not res["corps_lus"]:
        L.append("- Lecture : description absente (`body` vide dans une page de résultats), le drapeau « bien mixte » ne lit que le titre.")
    L += ["", "## Retenues (classées : rendement décroissant, puis €/m² croissant)", "",
          "| Rang | Identifiant | URL | Titre | Commune | Prix | Surface | €/m² | DPE | Baisse | Taxe foncière | Rendement brut indicatif | Drapeaux |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in res["retenues"]:
        baisse = "-" if a["baisse"] is None else f"{a['baisse']['pourcent']:.0f} % (était {_eur(a['baisse']['ancien_prix'])})"
        rendement = _pct(a["rendement"]) if a["rendement"] is not None else a["rendement_texte"]
        dpe = a["dpe"] or (f"({a['dpe_brut']})" if a["dpe_brut"] else "-")
        L.append("| " + " | ".join(_cellule(x) for x in (
            a["rang"], a["id"], a["url"], a["titre"], a["commune"], _eur(a["prix"]), _surface(a["surface"]),
            "-" if a["prix_m2"] is None else f"{a['prix_m2']:,.0f}".replace(",", " "), dpe, baisse,
            "-" if a["taxe_fonciere"] is None else _eur(a["taxe_fonciere"]), rendement, "; ".join(a["drapeaux"]))) + " |")
    L += ["", "## Écartées", ""]
    if not res["ecartees"]:
        L += ["Aucune.", ""]
    for motif in MOTIFS:
        lignes = [e for e in res["ecartees"] if e["motif"] == motif]
        if lignes:
            L += [f"### {motif} ({len(lignes)})", ""]
            L += [f"- [{e['id']}]({e['url']}) : {e['titre']}, {e['commune']}, "
                  + ("prix absent" if e["prix"] is None else _eur(e["prix"])) + f", {_surface(e['surface'])} : {e['detail']}"
                  for e in lignes]
            L.append("")
    L += ["## Doublons probables (jamais fusionnés : contrôler par les photos avant toute étude)", ""]
    if not res["doublons"]:
        L.append("Aucun.")
    for g in res["doublons"]:
        L.append(f"- **{g['groupe']}** : {', '.join(f'{i} ({st})' for i, st in g['statuts'].items())}")
        L += [f"  - {r}" for r in g["raisons"]]
    L += ["", f"## Points partagés par plus de {s['point_partage_max']} annonces (centre de commune, non précis)", ""]
    if not res["points_partages"]:
        L.append("Aucun.")
    L += [f"- ({q['lat']}, {q['lng']}) : {', '.join(q['ids'])}" for q in res["points_partages"]]
    return "\n".join(L) + "\n"


# --- Ligne de commande --------------------------------------------------------------------------------------------

def _verifier_sortie(chemin: str, option: str) -> Path:
    """Refuse `pistes.json` et `bruts/` (casse, lien symbolique), et tout fichier existant à plusieurs noms.

    Un lien physique vers le `pistes.json` d'un autre arbre se reconnaît à son nombre de liens, pas à son nom.
    """
    cible = Path(chemin).resolve()
    parts = [p.casefold() for p in cible.parts]
    nom_dossier = dossier_donnees().name.casefold()
    if len(parts) > 1 and parts[-1] == "pistes.json" and parts[-2] == nom_dossier:
        raise Illisible(f"{option} : écriture refusée sur {nom_dossier}/pistes.json (le script propose ; l'écrivain "
                        "désigné de pistes.json verse les pistes)")
    if any(parts[i:i + 2] == [nom_dossier, "bruts"] for i in range(len(parts) - 1)):
        raise Illisible(f"{option} : écriture refusée sous {nom_dossier}/bruts/ (écrire dans un dossier temporaire, "
                        "relire, puis copier le scan)")
    for protege in proteges():                    # identité sur disque : casse, lien physique, dossier voisin équivalent
        if not protege.exists():
            continue
        for candidat in (cible, *cible.parents):
            try:
                if candidat.exists() and os.path.samefile(candidat, protege):
                    raise Illisible(f"{option} : écriture refusée, {cible} désigne {protege} "
                                    "(pistes.json et bruts/ ne s'écrivent pas depuis le crible)")
            except OSError:
                continue
    try:
        if cible.is_file() and cible.stat().st_nlink > 1:
            raise Illisible(f"{option} : écriture refusée, {cible} est un lien physique (plusieurs noms pour un même "
                            "fichier : l'écriture traverserait jusqu'aux autres, peut-être pistes.json)")
    except OSError:
        pass
    return cible


def _meme_fichier(a: Path, b: Path) -> bool:
    try:
        return a == b or (a.exists() and b.exists() and os.path.samefile(a, b))
    except OSError:
        return False


def _ecrire(cible: Path, texte: str, option: str) -> None:
    try:
        cible.write_text(texte, encoding="utf-8")
    except OSError as exc:
        raise Illisible(f"{option} : {cible} : {type(exc).__name__} : {exc}") from exc


def _valider(args) -> str:
    """Arguments numériques, date et types : une valeur invalide arrête le crible (code 2) au lieu de passer en silence."""
    for nom, valeur, ok, attendu in (
            ("--prix-max", args.prix_max, lambda v: math.isfinite(v) and v > 0, "un nombre fini et positif"),
            ("--surface-min", args.surface_min, lambda v: math.isfinite(v) and v > 0, "un nombre fini et positif"),
            ("--top", args.top, lambda v: v >= 1, "un entier d'au moins 1"),
            ("--volume-affiche", args.volume_affiche, lambda v: v >= 0, "un entier non négatif")):
        if valeur is not None and not ok(valeur):
            raise Illisible(f"{nom} : valeur invalide ({valeur}) ; {attendu} est attendu")
    date = args.date or _date.today().isoformat()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError
        _date.fromisoformat(date)
    except ValueError as exc:
        raise Illisible(f"--date : AAAA-MM-JJ attendu (reçu « {date} »)") from exc
    return date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crible Leboncoin : tri de pages lues au navigateur, sans accès au site.")
    parser.add_argument("--pages", nargs="+", required=True, help="fichiers JSON, chacun une liste d'annonces (searchData.ads)")
    parser.add_argument("--profil", default=None, help="profil.json (défaut : immo-data/profil.json)")
    parser.add_argument("--prix-max", type=float, help="plafond strictement inférieur ; remplace le profil et ses exceptions")
    parser.add_argument("--types", help="codes real_estate_type (ex. 1,5) ou maison/autre ; défaut : la cible du profil")
    parser.add_argument("--surface-min", type=float, help="surface minimale, m² (aucune par défaut)")
    parser.add_argument("--fiche", action="append", default=[], help="fiche de données ouvertes d'une commune (répétable)")
    parser.add_argument("--volume-affiche", type=int, help="somme des volumes affichés par les passes, pour la réconciliation")
    parser.add_argument("--top", type=int, default=NB_CANDIDATS, help=f"candidats proposés (défaut {NB_CANDIDATS})")
    parser.add_argument("--date", default=None, help="date du scan (AAAA-MM-JJ), défaut : aujourd'hui")
    parser.add_argument("--source", help="référence du scan dans les pistes (défaut : bruts/<nom de --out>)")
    parser.add_argument("--out", help="scan en Markdown (jamais sous bruts/)")
    parser.add_argument("--pistes-out", help="pistes proposées en JSON (jamais pistes.json)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    args.profil = args.profil or str(profil_par_defaut())
    try:
        date = _valider(args)
        sorties = [(opt, _verifier_sortie(v, opt)) for opt, v in (("--out", args.out), ("--pistes-out", args.pistes_out)) if v]
        sortie = dict(sorties)
        if len(sorties) == 2 and _meme_fichier(sortie["--out"], sortie["--pistes-out"]):
            raise Illisible("--out et --pistes-out désignent le même fichier : le second écraserait le premier")
        for opt, cible in sorties:
            for entree in (*args.pages, args.profil, *args.fiche):
                if _meme_fichier(cible, Path(entree).resolve()):
                    raise Illisible(f"{opt} : {cible} écraserait une entrée du crible ({entree})")
        types = _types_explicites(args.types) if args.types is not None else None
        source = args.source or (f"bruts/{sortie['--out'].name}" if "--out" in sortie else f"crible Leboncoin du {date}")
        res = cribler(charger_pages(args.pages), profil=_json(args.profil), prix_max=args.prix_max, types=types,
                      surface_min=args.surface_min, fiches=[_json(f) for f in args.fiche],
                      volume_affiche=args.volume_affiche, noms_pages=args.pages)
        pistes = proposer_pistes(res, date=date, source=source, nb_candidats=args.top)
        if "--out" in sortie:
            _ecrire(sortie["--out"], rendre_markdown(res, date=date, source=source, pages=args.pages), "--out")
        if "--pistes-out" in sortie:
            doc = ("Pistes PROPOSÉES par engine/scripts/immo_crible.py : à relire, puis à verser dans immo-data/pistes.json "
                   "par son écrivain désigné. Chiffres du crible, sans recalcul.")
            _ecrire(sortie["--pistes-out"], json.dumps({"_doc": doc, "pistes": pistes}, ensure_ascii=False, indent=1) + "\n",
                    "--pistes-out")
    except Illisible as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    c = res["comptes"]
    print(f"crible : {c['lues']} annonces lues, {c['uniques']} identifiants uniques, {c['doublons_entre_pages']} doublons "
          f"entre pages ; {c['ecartees']} écartées, {c['retenues']} retenues")
    print(f"plafond : prix < {_eur(res['plafond']['valeur'])} ({res['plafond']['origine']}) ; types : "
          f"{', '.join(res['types']['codes'])} ({res['types']['origine']})")
    if "ecart_volume" in c and c["ecart_volume"] != 0:
        print(f"ATTENTION : volume affiché {c['volume_affiche']} contre {c['lues']} lues (écart {c['ecart_volume']:+d})",
              file=sys.stderr)
    for d in res["contenus_differents"]:
        print(f"ATTENTION : contenu différent entre deux lectures de {d['id']} : première lecture gardée", file=sys.stderr)
    for opt, cible in sorties:
        print(f"{opt} écrit : {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
