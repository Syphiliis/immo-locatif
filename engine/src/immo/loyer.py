"""Loyer du tri rapide (`/immo`, étape 3r) depuis la carte des loyers d'une fiche, corrigé de la surface.

La carte des loyers (ANIL, `src/opendata/loyers.py`) donne un loyer d'annonce au m², charges comprises, pour un
bien de surface type (`surface_type_m2` de la série : 37, 72 ou 92 m², 52 toutes typologies). Le loyer au m²
baisse quand la surface monte : la correction de surface le ramène à la surface du bien.

Formules (écrites aussi dans le skill `immo`, étape 3r) :
- élasticité de la commune : `e = ln(v_t3plus / v_t1t2) / ln(72 / 37)`, sur les `valeur_m2` des séries
  `appartement_t3_plus` et `appartement_t1_t2` de la fiche (négative en général : le loyer au m² baisse quand la surface monte) ;
- loyer au m² réaliste = `valeur_m2 × (S / S_type)^e` ; optimiste : le même calcul à `ip_haut` ;
- loyer CC = loyer au m² × S ; HC = CC − charges récupérables, si elles sont données ;
- pessimiste = réaliste − 10 % (CC et HC).
Hors de [37 ; 92] m², ou pour la série `maison` (élasticité dérivée sur les appartements, entre 37 et 72 m²),
le résultat est une extrapolation, drapeau levé.
"""
from __future__ import annotations

import math

SERIES = ("appartement", "appartement_t1_t2", "appartement_t3_plus", "maison")
DOMAINE_M2 = (37.0, 92.0)
SURFACE_T1_T2, SURFACE_T3_PLUS = 37.0, 72.0
DECOTE_PESSIMISTE = 0.10


def _serie(fiche: dict, nom: str) -> dict:
    s = (fiche.get("loyers") or {}).get(nom)
    if not isinstance(s, dict) or not s.get("valeur_m2"):
        raise ValueError(f"série de loyers absente ou vide dans la fiche : loyers.{nom}")
    return s


def loyer_3r(fiche: dict, serie: str, surface_m2: float, charges_mensuelles: float | None = None) -> dict:
    """Loyers mensuels réaliste, optimiste et pessimiste d'un bien de `surface_m2`, série `serie` de la fiche."""
    if serie not in SERIES:
        raise ValueError(f"série inconnue : {serie} (attendu : {', '.join(SERIES)})")
    if not surface_m2 > 0:
        raise ValueError(f"surface invalide : {surface_m2}")
    if charges_mensuelles is not None and charges_mensuelles < 0:
        raise ValueError(f"charges invalides : {charges_mensuelles}")
    s = _serie(fiche, serie)
    v12, v3 = _serie(fiche, "appartement_t1_t2")["valeur_m2"], _serie(fiche, "appartement_t3_plus")["valeur_m2"]
    e = math.log(v3 / v12) / math.log(SURFACE_T3_PLUS / SURFACE_T1_T2)
    s_type = float(s["surface_type_m2"])
    facteur = (surface_m2 / s_type) ** e

    def _scenario(m2: float) -> dict:
        cc = m2 * surface_m2
        return {"loyer_m2_cc": m2, "loyer_cc": cc,
                "loyer_hc": None if charges_mensuelles is None else cc - charges_mensuelles}

    realiste = _scenario(s["valeur_m2"] * facteur)
    optimiste = _scenario(s["ip_haut"] * facteur) if s.get("ip_haut") else None
    pessimiste = {k: None if v is None else v * (1 - DECOTE_PESSIMISTE) for k, v in realiste.items()}
    raisons = []
    if serie == "maison":
        raisons.append("série maison : élasticité dérivée sur les appartements, entre 37 et 72 m²")
    if not DOMAINE_M2[0] <= surface_m2 <= DOMAINE_M2[1]:
        raisons.append(f"surface de {'%g' % surface_m2} m² hors du domaine de la carte [37 ; 92] m²")
    return {
        "serie": serie, "surface_m2": surface_m2, "surface_type_m2": s_type, "elasticite": e, "facteur": facteur,
        "maille": s.get("maille"), "n": s.get("n"), "millesime": s.get("millesime"),
        "charges_mensuelles": charges_mensuelles,
        "extrapolation": bool(raisons), "raison_extrapolation": " ; ".join(raisons),
        "scenarios": {"pessimiste": pessimiste, "realiste": realiste, "optimiste": optimiste},
    }
