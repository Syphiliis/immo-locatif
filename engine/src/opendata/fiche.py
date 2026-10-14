"""Assemblage de la fiche « données ouvertes » d'un bien.

Une adresse libre devient une fiche JSON datée et sourcée : géocodage, parcelle cadastrale, urbanisme (zone,
prescriptions, servitudes), bâtiment (BDNB), copropriété (RNIC), loyers de marché, ventes DVF comparables, DPE,
risques Géorisques, taux de taxe foncière. Chaque source est un module de `src/opendata/` ; ce module les enchaîne
et rassemble leurs résultats.

Particularités :
- Les clés de premier niveau sont exactement `CLES`, dans cet ordre, même quand tout échoue : le
  lecteur (script, skill) peut s'y fier.
- Chaque collecteur tourne dans un `try` isolé. Un bloc en échec vaut `None` et laisse une entrée dans
  `erreurs` ; jamais un 0 ou une liste vide à sa place. Une exception inattendue (une API qui change de
  forme) est captée comme une `OpendataError` : la fiche ne plante pas.
- Géocodage en échec, ou score sous `SCORE_MIN` : aucun autre appel réseau, tous les autres blocs à
  `None` (`cle_bien` et `cadastre` compris). Le géocodage à faible score est conservé pour qu'on voie le score.
- `cle_bien` = `{parcelle, identifiant_ban, fiable}` identifie le bien : l'IDU
  de la parcelle cadastrale et l'identifiant BAN du géocodage. `fiable` ne vaut vrai que si le géocodage est un numéro de
  rue (`housenumber`), si la parcelle CONTIENT le point (`cadastre.METHODE_CONTENANT`) ET si elle est dans la commune
  du géocodage (une alerte `cle_bien` le dit sinon). Cadastre en échec : `parcelle` vaut `None`, l'identifiant BAN
  reste.
- `urbanisme`, `batiment` et `copropriete` passent après le cadastre.
  `batiment` lit la parcelle du cadastre : sans elle (cadastre en échec), le bloc vaut `None` avec l'erreur « parcelle
  inconnue (cadastre en échec) » ; sur une parcelle seulement la plus proche, l'appel est fait et une alerte dit
  « à confirmer ». `copropriete` reçoit la parcelle, ou `None`. Selon le type du point géocodé : `municipality` (centre
  de la commune) saute les trois blocs, avec une alerte ; `street` (ou un lieu-dit) les lit, avec une alerte.
- `erreurs` dit ce qui a ÉCHOUÉ (bloc à `None`, ou sous-bloc) ; `alertes` dit ce qui n'a pas échoué mais que le
  lecteur doit savoir (fenêtre DVF courte, liste DPE tronquée). Toujours une liste, jamais `None`. Seules les
  erreurs changent le code de sortie (`code_sortie`).
- `genere_le` garde le fuseau local de `maintenant` ; la date d'extraction des sources et la fenêtre DVF
  suivent cette même date locale (jamais l'UTC).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.opendata import batiment, cadastre, copropriete, dpe, dvf, fiscalite_locale, georisques, loyers, urbanisme
from src.opendata.geocodage import CONTROLE_NON_FAIT, NB_CANDIDATS, SCORE_MIN, SOURCE as SOURCE_GEOCODAGE, geocoder
from src.opendata.http import OpendataError, Resultat

CLES = (
    "adresse_demandee", "genere_le", "geocodage", "commune", "cle_bien", "cadastre", "urbanisme", "batiment",
    "copropriete", "loyers", "dvf", "dpe", "risques", "fiscalite_locale", "sources", "erreurs", "alertes",
)
ALERTE_POINT_COMMUNE = "point de commune : urbanisme, bâtiment et copropriété non lus"
ALERTES_POINT = {"street": "point sur la rue", "locality": "point sur un lieu-dit"}  # autre type : « point de type X »


def _nombre(valeur: float | None, decimales: int = 2) -> str:
    return "n/d" if valeur is None else f"{valeur:.{decimales}f}".replace(".", ",")


def _message(exc: Exception) -> str:
    """Un échec d'API porte déjà un message lisible ; une autre exception garde son type."""
    return str(exc) if isinstance(exc, OpendataError) else f"{type(exc).__name__}: {exc}"


def _alertes_geocodage(geo: dict) -> list[dict]:
    """Ce que le contrôle de commune du géocodage laisse à savoir : contrôle non fait (pas de code postal dans
    l'adresse), ou candidat retenu au-delà du premier (les premiers n'étaient pas dans le code postal demandé)."""
    alertes = []
    if geo["controle_commune"] == CONTROLE_NON_FAIT:
        alertes.append({"bloc": "geocodage", "message": (
            f"contrôle de commune non fait : pas de code postal dans l'adresse, premier résultat pris tel quel "
            f"({geo['label']})")})
    if geo["rang_candidat"] > 1:
        alertes.append({"bloc": "geocodage", "message": (
            f"candidat de rang {geo['rang_candidat']} retenu parmi les {NB_CANDIDATS} lus, car les candidats de rang "
            f"inférieur ne sont pas dans le code postal demandé ({geo['controle_commune']}) : {geo['label']}")})
    return alertes


def _alerte_point(geo: dict) -> dict | None:
    """Ce que le type du point géocodé change pour l'urbanisme, le bâtiment et la copropriété : rien pour un numéro
    de rue ; une alerte pour une rue ou un lieu-dit (lus quand même) ; une alerte pour le centre d'une commune (non
    lus)."""
    type_point = geo["type"]
    if type_point == "housenumber":
        return None
    if type_point == "municipality":
        return {"bloc": "geocodage", "message": ALERTE_POINT_COMMUNE}
    return {"bloc": "geocodage", "message": ALERTES_POINT.get(type_point, f"point de type {type_point}")}


def _commune_differente(geo: dict, parcelle: dict | None) -> bool:
    """Vrai si la commune de la parcelle (`code_insee`, quand l'API la donne) n'est pas celle du géocodage."""
    return parcelle is not None and parcelle["code_insee"] is not None and parcelle["code_insee"] != geo["citycode"]


def _cle_bien(geo: dict, parcelle: dict | None) -> dict:
    """Clé d'identité du bien : parcelle (IDU) + identifiant BAN. `fiable` : numéro de rue, parcelle qui contient le
    point ET parcelle dans la commune du géocodage."""
    contient = parcelle is not None and parcelle["methode"] == cadastre.METHODE_CONTENANT
    return {
        "parcelle": None if parcelle is None else parcelle["idu"],
        "identifiant_ban": geo["identifiant_ban"],
        "fiable": geo["type"] == "housenumber" and contient and not _commune_differente(geo, parcelle),
    }


def _a_confirmer(resultat: Resultat, parcelle: dict, bloc: str, libelle: str) -> Resultat:
    """Met en tête des alertes « <libelle> d'une parcelle à confirmer » quand le cadastre n'a donné que la parcelle la
    plus proche du point (aucune ne le contient) : elle qualifie tout le bloc."""
    if parcelle["methode"] != cadastre.METHODE_PLUS_PROCHE:
        return resultat
    alerte = {"bloc": bloc, "message": f"{libelle} d'une parcelle à confirmer"}
    return resultat._replace(alertes=[alerte, *resultat.alertes])


def _batiment(client: httpx.Client, parcelle: dict | None, sleep: Callable[[float], Any]) -> Resultat:
    """Bâtiments de la parcelle du cadastre. Sans parcelle (cadastre en échec) : erreur nommée, aucun appel."""
    if parcelle is None:
        raise OpendataError("parcelle inconnue (cadastre en échec)")
    return _a_confirmer(batiment.collecter(client, parcelle["idu"], sleep=sleep), parcelle, "batiment", "bâtiment")


def _copropriete(client: httpx.Client, geo: dict, parcelle: dict | None, sleep: Callable[[float], Any]) -> Resultat:
    """Copropriétés du RNIC. Sans parcelle (cadastre en échec), le RNIC est lu sans correspondance possible."""
    resultat = copropriete.collecter(client, geo, None if parcelle is None else parcelle["idu"], sleep=sleep)
    return resultat if parcelle is None else _a_confirmer(resultat, parcelle, "copropriete", "copropriété")


def construire_fiche(adresse: str, *, client: httpx.Client, rayon_m: int = 500, fenetre_mois: int = 24,
                     maintenant: datetime | None = None, sleep: Callable[[float], Any] = time.sleep,
                     fenetre_immeubles_mois: int | None = None) -> dict:
    """Fiche complète de `adresse`. Ne lève jamais pour une panne de source : elle va dans `erreurs`.
    `fenetre_immeubles_mois` (None ou 0 : désactivé) ajoute `dvf.immeubles` ; le script l'active à 60 mois."""
    if maintenant is None:
        maintenant = datetime.now().astimezone()
    genere_le = maintenant.isoformat(timespec="seconds")
    fiche: dict[str, Any] = dict.fromkeys(CLES)
    fiche.update(adresse_demandee=adresse, genere_le=genere_le)
    erreurs: list[dict] = []
    alertes: list[dict] = []
    sources: list[dict] = []

    try:
        geo = geocoder(client, adresse, sleep=sleep)
    except Exception as exc:
        erreurs.append({"bloc": "geocodage", "message": _message(exc)})
    else:
        fiche["geocodage"] = geo
        sources.append(SOURCE_GEOCODAGE)
        if geo["score"] < SCORE_MIN:
            erreurs.append({"bloc": "geocodage", "message":
                            f"score {_nombre(geo['score'], 4)} < {_nombre(SCORE_MIN, 1)} : rien de fiable derrière"})
        else:
            fiche["commune"] = {"insee": geo["citycode"], "nom": geo["city"], "code_postal": geo["postcode"]}
            alertes.extend(_alertes_geocodage(geo))
            alerte_point = _alerte_point(geo)
            if alerte_point is not None:
                alertes.append(alerte_point)
            reglementaires = () if geo["type"] == "municipality" else (  # centre de commune : rien à lire à ce point
                ("urbanisme", lambda: urbanisme.collecter(client, geo, sleep=sleep)),
                ("batiment", lambda: _batiment(client, fiche["cadastre"], sleep)),
                ("copropriete", lambda: _copropriete(client, geo, fiche["cadastre"], sleep)),
            )
            collecteurs = (
                ("cadastre", lambda: cadastre.collecter(client, geo, sleep=sleep)),
                *reglementaires,  # après le cadastre : batiment et copropriete lisent sa parcelle
                ("loyers", lambda: loyers.collecter(client, geo, sleep=sleep)),
                ("dvf", lambda: dvf.collecter(client, geo, rayon_m=rayon_m, fenetre_mois=fenetre_mois,
                                              aujourdhui=maintenant.date(), sleep=sleep,
                                              fenetre_immeubles_mois=fenetre_immeubles_mois)),
                ("dpe", lambda: dpe.collecter(client, geo, sleep=sleep)),
                ("risques", lambda: georisques.collecter(client, geo, sleep=sleep)),
                ("fiscalite_locale", lambda: fiscalite_locale.collecter(client, geo, sleep=sleep)),
            )
            for nom, collecter in collecteurs:
                try:
                    resultat = collecter()
                except Exception as exc:
                    erreurs.append({"bloc": nom, "message": _message(exc)})
                    continue
                fiche[nom] = resultat.bloc
                erreurs.extend(resultat.erreurs)
                alertes.extend(resultat.alertes)
                sources.extend(resultat.sources)
            fiche["cle_bien"] = _cle_bien(geo, fiche["cadastre"])
            if _commune_differente(geo, fiche["cadastre"]):
                parcelle = fiche["cadastre"]
                alertes.append({"bloc": "cle_bien", "message": (
                    f"clé du bien non fiable : la parcelle {parcelle['idu']} est dans la commune "
                    f"{parcelle['code_insee']}, le géocodage dit {geo['citycode']}")})

    date_extraction = genere_le[:10]
    fiche["sources"] = [
        {"bloc": s["bloc"], "url": s["url"], "date_extraction": date_extraction,
         "licence": s["licence"], "millesime": s["millesime"]}
        for s in sources
    ]
    fiche["erreurs"] = erreurs
    fiche["alertes"] = alertes
    return fiche


def code_sortie(fiche: dict) -> int:
    """2 si rien de fiable n'a pu être tiré du géocodage ; 3 si le géocodage tient mais qu'un bloc a échoué
    (`erreurs` non vide : fiche partielle) ; 0 sinon. Une alerte (`alertes`) ne change pas le code."""
    geo = fiche["geocodage"]
    if geo is None or geo["score"] < SCORE_MIN:
        return 2
    return 3 if fiche.get("erreurs") else 0


def _taille(liste: list | None) -> str:
    return "n/d" if liste is None else str(len(liste))


def _pluriel(n: int | None, mot: str) -> str:
    """« 0 voisine », « 1 voisine », « 2 voisines » (le pluriel commence à 2 en français) ; `n/d` si n est inconnu."""
    return f"n/d {mot}s" if n is None else f"{n} {mot}{'s' if n > 1 else ''}"


def _oui_non(valeur: bool) -> str:
    return "oui" if valeur else "non"


def _ligne_urbanisme(bloc: dict | None) -> str:
    """Zone (et son document), abords de monument historique (AC1), plan de prévention des risques (PM1), prescriptions
    et taille du carré où elles sont lues (lue dans `portee.prescriptions`). `n/d` : donnée absente."""
    if bloc is None:
        return "Urbanisme : n/d"
    zone, documents = bloc["zone"], bloc["documents"]
    if zone is None:
        texte_zone = "zone n/d" + (" (commune au RNU)" if bloc["commune"]["rnu"] else "")
    else:
        document = ""
        if documents:
            document = f" ({' '.join(str(d) for d in (documents[0]['nom'], documents[0]['type']) if d)})"
        texte_zone = f"zone {zone['libelle']}{document}"
    carre = re.search(r"(\d+) × (\d+) m", bloc["portee"]["prescriptions"])
    texte_carre = f" (carré ~{carre.group(1)} × {carre.group(2)} m)" if carre else ""
    return (f"Urbanisme : {texte_zone}, abords MH {_oui_non(bloc['abords_monument_historique'])}, "
            f"PPR {_oui_non(bloc['plan_prevention_risques'])}, {_pluriel(len(bloc['prescriptions']), 'prescription')}"
            f"{texte_carre}")


def _ligne_batiment(bloc: dict | None) -> str:
    """Année et murs du groupe principal (le plus de logements), total des logements des groupes, nombre de groupes.
    Valeurs brutes de la BDNB. `n/d` : donnée absente."""
    if bloc is None:
        return "Bâtiment : n/d"
    groupes = bloc["groupes"]
    if not groupes:
        return "Bâtiment : aucun groupe BDNB sur la parcelle"
    principal = groupes[0]
    logements = [g["nb_log"] for g in groupes if g["nb_log"] is not None]
    annee = "n/d" if principal["annee_construction"] is None else principal["annee_construction"]
    murs = "n/d" if principal["mat_mur_txt"] is None else principal["mat_mur_txt"]
    total = _pluriel(None if not logements else round(sum(logements)), "logement")
    return f"Bâtiment : {annee} · {murs} · {total} (BDNB, {_pluriel(bloc['n_groupes'], 'groupe')})"


def _ligne_copropriete(bloc: dict | None) -> str:
    """Immatriculation de la parcelle au RNIC (l'absence ne prouve rien) et copropriétés voisines dans le rayon."""
    if bloc is None:
        return "Copropriété : n/d"
    statuts = {
        "parcelle": "immatriculée sur la parcelle",
        "aucune": "aucune sur la parcelle (l'absence ne prouve rien)",
        "parcelle inconnue": "parcelle inconnue (correspondance impossible)",
    }
    parametres = bloc["parametres"]
    voisines = _pluriel(parametres["voisines_dans_le_rayon"], "voisine")
    return (f"Copropriété : {statuts[bloc['correspondance']]}, {voisines} à moins de "
            f"{parametres['rayon_voisines_m']} m")


def resume(fiche: dict, chemin: str | Path) -> str:
    """Quatorze lignes : une par bloc (six), le cadastre, l'urbanisme, le bâtiment, la copropriété, les ventes
    d'immeubles, les erreurs, les alertes, le chemin de la fiche. `n/d` = donnée absente."""
    geo, loyer, ventes, diagnostics = fiche["geocodage"], fiche["loyers"], fiche["dvf"], fiche["dpe"]
    risques, taxe = fiche["risques"], fiche["fiscalite_locale"]

    if geo is None:
        ligne_geo = "Géocodage : échec"
    else:
        ligne_geo = (f"Géocodage : {geo['label']} (type {geo['type']}, score {_nombre(geo['score'])}, "
                     f"INSEE {geo['citycode']})")

    parcelle = fiche["cadastre"]
    if parcelle is None:
        ligne_cadastre = "Cadastre : n/d"
    else:
        contenance = ("contenance n/d" if parcelle["contenance_m2"] is None
                      else f"{_nombre(parcelle['contenance_m2'], 0)} m²")
        ligne_cadastre = f"Cadastre : parcelle {parcelle['idu']} ({contenance}, {parcelle['methode']})"

    if loyer is None:
        ligne_loyers = "Loyers : n/d"
    else:
        valeurs = {t: _nombre(b["valeur_m2"]) if b else "n/d" for t, b in loyer.items()}
        ligne_loyers = (f"Loyers 2025 (EUR/m2/mois) : appartement {valeurs['appartement']}, "
                        f"T1-T2 {valeurs['appartement_t1_t2']}, T3 et plus {valeurs['appartement_t3_plus']}, "
                        f"maison {valeurs['maison']}")

    if ventes is None:
        ligne_dvf = "DVF : n/d"
    else:
        c, p, t = ventes["compteurs"], ventes["parametres"], ventes["par_type"]
        absentes = ", ".join(str(a) for a in p["annees_absentes"]) or "aucune"
        ligne_dvf = (f"DVF : {c['retenues']} comparables retenus sur {c['mutations']} mutations "
                     f"(rayon {p['rayon_m']} m, {p['fenetre_mois']} mois) ; médiane EUR/m2 : "
                     f"maison {_nombre(t['Maison']['mediane'])}, appartement {_nombre(t['Appartement']['mediane'])} ; "
                     f"dernière mutation {p['derniere_mutation'] or 'n/d'} ; années absentes {absentes}")

    if ventes is None:
        ligne_immeubles = "Immeubles : n/d"
    elif "immeubles" not in ventes:
        ligne_immeubles = "Immeubles : désactivé (--fenetre-immeubles-mois 0)"
    elif ventes["immeubles"] is None:
        ligne_immeubles = "Immeubles : n/d"
    else:
        immeubles = ventes["immeubles"]
        reference = immeubles["reference"]
        criteres = (f"référence ({reference['criteres']['nb_logements_min']} logements ou plus, une par parcelle, "
                    f"sans atypique)")
        debut = f"Immeubles : {immeubles['statistiques']['n']} ventes retenues ; {criteres}"
        if reference["mediane_eur_m2_bati"] is None:
            ligne_immeubles = f"{debut} : {reference['raison_mediane_absente']}"
        else:
            ligne_immeubles = (f"{debut} n = {reference['n']}, médiane {_nombre(reference['mediane_eur_m2_bati'])} "
                               f"€/m² bâti, {_nombre(reference['mediane_eur_par_logement'])} €/logement")

    if diagnostics is None:
        ligne_dpe = "DPE : n/d"
    else:
        a_l_adresse = diagnostics["a_l_adresse"]
        ligne_dpe = (f"DPE : {_nombre(diagnostics['commune_total'], 0)} dans la commune ; "
                     f"{'n/d' if a_l_adresse is None else a_l_adresse['total']} à l'adresse")

    if risques is None:
        ligne_risques = "Risques : n/d"
    else:
        commune = risques["commune"]
        ligne_risques = (f"Risques : {'n/d' if commune is None else len(commune['risques'])} risques "
                         f"recensés dans la commune ; rapport à l'adresse "
                         f"{'n/d' if risques['adresse'] is None else 'obtenu'} ; PPRN {_taille(risques['pprn'])}")

    if taxe is None:
        ligne_taxe = "Taxe foncière : n/d"
    else:
        ligne_taxe = (f"Taxe foncière : taux global {_nombre(taxe['taux_global_tfb'])} %, TEOM "
                      f"{_nombre(taxe['taux_plein_teom'])} % (exercice {taxe['exercice']}), aucun montant calculé")

    erreurs = fiche["erreurs"]
    ligne_erreurs = ("Erreurs : aucune" if not erreurs else
                     f"Erreurs : {len(erreurs)} ({', '.join(e['bloc'] for e in erreurs)})")

    alertes = fiche["alertes"]
    ligne_alertes = ("Alertes : aucune" if not alertes else
                     "Alertes : " + " ; ".join(f"{a['bloc']} : {a['message']}" for a in alertes))

    return "\n".join((ligne_geo, ligne_cadastre, _ligne_urbanisme(fiche["urbanisme"]),
                      _ligne_batiment(fiche["batiment"]), _ligne_copropriete(fiche["copropriete"]), ligne_loyers,
                      ligne_dvf, ligne_immeubles, ligne_dpe, ligne_risques, ligne_taxe, ligne_erreurs, ligne_alertes,
                      f"Fiche écrite : {chemin}"))
