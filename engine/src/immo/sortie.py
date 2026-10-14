"""Sortie d'une SCI à l'IS : projection année par année, revente à N ans, liquidation, boni, TRI et VAN des associés.

`projeter(bien, scenario, params, contexte)` prolonge sur
`sortie.horizon_ans` années le modèle de l'année 1 de `fiscal_sci._sci_is` : mêmes charges déductibles, même base
amortissable, mêmes règles d'IS, de report des déficits et d'intérêts de compte courant, importées sans être
modifiées. Fonctions pures, sans arrondi interne. Toute hypothèse de projection (horizon, indexations, classe DPE,
politique de distribution) entre par le bloc `sortie` du bien, validé par `modele.valider_sortie`, sans valeur par
défaut.

`revendre` refait l'année N avec la plus-value de cession, `liquider` partage l'actif de la SCI et `imposer_boni`
impose le boni comme un revenu distribué ; `flux_associes` et `rentabilite` donnent les flux des associés (t = 0 à
N), leur TRI et leur VAN ; `sortir` enchaîne le tout pour un scénario (clé `sortie` du contrat d'`analyser`). Les
fonctions de règle sont pures et un cas de contrôle les teste au centime.

Règles du module, citées par leur identifiant dans le code et les tests : S1 à S3 (plus-value dans le résultat, sur la valeur nette
comptable, au taux de l'IS), S4 (terrain non amortissable, chaque composant amorti jusqu'à la fin de sa durée), S5
(durée de la structure, point incertain), S7 (pas de réserve légale pour une SCI), S8 à S11 (boni, droit de partage,
assiette, enregistrement), S12 (intérêts de compte courant : revenus de capitaux mobiliers), S13 (aucune révision
du loyer d'un logement classé F ou G).
"""
from __future__ import annotations

from .acquisition import frais_acquisition
from .exploitation import charges, loyer_annuel_theorique, loyers_encaisses
from .financement import apport, assurance_mensuelle, crd_apres, echeancier_bien, emprunt
from .fiscal_nom_propre import _charges_lmnp
from .fiscal_sci import distribution, impot_societes, imputer_deficits, interets_cca
from .indicateurs import tri, van
from .modele import MONETAIRES_EXPLOITATION, SCENARIOS, valeur, valider_bien

CLASSES_SANS_REVISION = ("F", "G")

CONVENTIONS_PROJECTION = [
    "projection : loyers de l'année 1 du scénario × (1 + sortie.indexation_loyers_annuelle)^(t - 1), vacance "
    "constante ; charges fixes × (1 + sortie.indexation_charges_annuelle)^(t - 1) ; gestion, GLI et capex sur les "
    "loyers de l'année",
    "capex : sortie de trésorerie chaque année, ni déduite du résultat ni immobilisée (convention du cash-flow du "
    "moteur)",
    "année t = 12 mois ; résultat comptable pris égal au résultat fiscal ; IS payé dans l'année de l'exercice ; "
    "intérêts de compte courant calculés sur le solde d'ouverture de l'année et versés chaque année ; versements de "
    "l'année dans cet ordre : distribution, puis remboursement du compte courant",
]
RAISON_PLAFOND_REPORT = (
    "distribution (sci.distribution_annuelle) plafonnée au report à nouveau bénéficiaire, résultat après IS de "
    "l'année compris (aucune réserve légale : C. com. L. 232-10 ne vise que les SARL et les sociétés par actions)")
RAISON_PLAFOND_TRESORERIE = "distribution plafonnée à la trésorerie disponible de la SCI"
RAISON_CCA_SOLDE = ("remboursement de compte courant (sci.remboursement_cca_annuel) plafonné au solde du compte "
                    "courant")
RAISON_CCA_TRESORERIE = "remboursement de compte courant plafonné à la trésorerie restante après la distribution"
RAISONS_REVENTE = [
    "seul le prix d'achat est revalorisé ; les travaux n'ajoutent aucune valeur de revente (hypothèse prudente, à "
    "reprendre dans À vérifier)",
    "plus-value de cession de l'immeuble comprise dans le résultat de l'année N et imposée au taux de l'IS, sans "
    "régime du long terme ni abattement pour durée de détention (CGI 38-1, 209-I, 219 I-a quater ; BOI-IS-BASE-20 §10 "
    "et §20 ; CGI 150 U ne vise pas une société à l'IS)",
    "valeur nette comptable = base amortissable (terrain compris, jamais amorti) + travaux immobilisés + mobilier - "
    "amortissements cumulés (BOI-BIC-PVMV-10-20 §30 ; BOI-BIC-AMT-10-20 §230) ; plus-value = prix de revente - frais "
    "de revente - valeur nette comptable",
    "structure amortie sur 50 ans (fiscal.lmnp.composants, pratique à vérifier) : pour un immeuble de placement, "
    "l'administration ne fixe aucune durée, la durée réelle s'applique (BOI-BIC-AMT-10-40-10 §130, §140, §200, "
    "exemple illustratif à 80 ans) ; une durée plus longue baisse les amortissements, donc l'IS épargné pendant la "
    "détention, et la plus-value",
    "trésorerie avant l'IS de l'année N = trésorerie de fin d'année N + IS de l'année N sans cession (après la "
    "distribution et le remboursement de compte courant de l'année N) ; actif après cession = trésorerie avant l'IS + "
    "prix - frais de revente - capital restant dû - indemnités de remboursement anticipé - IS de l'année N avec la "
    "plus-value",
]
RAISON_IRA = ("indemnités de remboursement anticipé (sortie.indemnites_remboursement_anticipe) payées sur le prix, "
              "non déduites du résultat imposable de l'année N (traitement non tranché, hypothèse prudente)")
RAISON_IRA_SANS_EMPRUNT = ("indemnités de remboursement anticipé non dues : aucun emprunt "
                           "(sortie.indemnites_remboursement_anticipe ignorées)")
RAISON_IRA_PRET_SOLDE = ("indemnités de remboursement anticipé non dues : prêt soldé au plus tard à la fin de "
                         "l'année N (sortie.indemnites_remboursement_anticipe ignorées)")
RAISONS_LIQUIDATION = [
    "actif net partagé = actif après cession - comptes courants restants (passif, CGI 747 ; BOI-ENR-AVS-30-20-10 §110 "
    "et §170) - frais de liquidation (sortie.frais_liquidation, non déduits du résultat imposable)",
    "comptes courants remboursés tenus pour non imposables (remboursement d'un prêt), sans texte explicite trouvé "
    "(point incertain)",
    "apports remboursés non imposables (CGI 112-1°) ; boni = actif net partagé - droit de partage - apports, revenu "
    "distribué (CGI 109-1-1° ; BOI-RPPM-RCM-10-20-40 §50 et §70)",
    "acte de dissolution sans transmission enregistré gratuitement (CGI 811-2°) ; acte de partage à enregistrer dans "
    "le mois (CGI 635-1 7°)",
]


def _pct(taux: float) -> str:
    """0.015 → '1,5 %'."""
    return format(taux * 100, ".4f").rstrip("0").rstrip(".").replace(".", ",") + " %"


def _euros(montant: float) -> str:
    """12345.678 → '12 345,68 €'."""
    return format(montant, ",.2f").replace(",", " ").replace(".", ",") + " €"


def _annees(annees: list[int]) -> str:
    """[3] → 'année 3' ; [1, 2, 3, 5] → 'années 1 à 3 et 5' ; [2, 4, 6] → 'années 2, 4 et 6'."""
    if len(annees) == 1:
        return f"année {annees[0]}"
    plages: list[list[int]] = []
    for a in annees:
        if plages and a == plages[-1][-1] + 1:
            plages[-1].append(a)
        else:
            plages.append([a])
    morceaux = []
    for p in plages:
        morceaux += [f"{p[0]} à {p[-1]}"] if len(p) > 2 else [str(a) for a in p]
    return "années " + (morceaux[0] if len(morceaux) == 1 else ", ".join(morceaux[:-1]) + " et " + morceaux[-1])


# --------------------------------------------------------------------------------------------
# Règles (fonctions pures)
# --------------------------------------------------------------------------------------------

def amortissements_annee(base: float, travaux: float, nature_travaux: str, mobilier: float, annee: int,
                         params: dict) -> dict:
    """Amortissement de l'année `annee` (1 = première) : chaque composant du bâti tant que annee ≤ sa durée (S4),
    terrain exclu ; travaux d'amélioration et mobilier sur leurs durées. En année 1, égal à
    `amortissements_composants`."""
    composants = valeur(params, "fiscal.lmnp.composants")
    bati = base * sum(c[0] / c[1] for nom, c in composants.items() if nom != "terrain" and annee <= c[1])
    duree_travaux = valeur(params, "fiscal.lmnp.duree_travaux_amelioration")
    trav = travaux / duree_travaux if nature_travaux == "amelioration" and annee <= duree_travaux else 0.0
    duree_mobilier = valeur(params, "fiscal.lmnp.duree_mobilier")
    mob = mobilier / duree_mobilier if annee <= duree_mobilier else 0.0
    return {"bati": bati, "travaux": trav, "mobilier": mob, "total": bati + trav + mob}


# --------------------------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------------------------

def projeter(bien: dict, scenario: str, params: dict, contexte: dict | None = None) -> dict:
    """Projection de la SCI à l'IS, une ligne par année t = 1 à `sortie.horizon_ans`, et ses raisons.

    `contexte` (forme de `foyer.contexte()`) donne l'année de revenus de l'année 1, qui date la clôture de chaque
    exercice (intérêts de compte courant) ; sans contexte, `fiscal.annee_revenus` du bien. Le bien n'est pas modifié.
    Une trésorerie qui serait négative en fin d'année est ramenée à 0 par un apport des associés en compte courant
    (`apport_cca`), qui rejoint le solde du compte courant (même taux, même traitement).
    """
    valider_bien(bien)
    if "sortie" not in bien:
        raise ValueError("champ requis absent : sortie")
    if scenario not in SCENARIOS:
        raise ValueError(f"scénario inconnu : {scenario!r} (attendu : {', '.join(SCENARIOS)})")
    sortie, sci, e = bien["sortie"], bien["sci"], bien["exploitation"]
    s = bien["scenarios"][scenario]
    annee_revenus = contexte["annee"] if contexte is not None else bien.get("fiscal", {}).get("annee_revenus")
    raisons: list[str] = []
    par_annee: dict[str, list[int]] = {}  # raison → années où elle joue

    def noter(raison: str, t: int) -> None:
        par_annee.setdefault(raison, []).append(t)

    cca = float(sci["cca"]["montant"])
    mise = apport(bien, params)
    apports_capital = mise - cca
    if apports_capital < 0:
        raise ValueError(f"apports en capital négatifs : apport {_euros(mise)} < compte courant (sci.cca.montant) "
                         f"{_euros(cca)}")
    raisons.append(f"apports en capital = apport (coût total - emprunt) - compte courant (sci.cca.montant) = "
                   f"{_euros(apports_capital)} : convention, la part de l'apport qui n'est pas prêtée à la SCI en "
                   "compte courant est apportée au capital")

    indexation = sortie["indexation_loyers_annuelle"][scenario]
    classe = sortie["classe_dpe_location"]
    if classe in CLASSES_SANS_REVISION:
        raisons.append(f"classe DPE {classe} pendant la détention : aucune révision du loyer (loi 89-462 art. 17-1, "
                       "version du 24/08/2022 ; loi 2022-1158 art. 12), indexation des loyers forcée à 0 (entrée : "
                       f"{_pct(indexation)})")
        indexation = 0.0
    duree_1 = sci["duree_premier_exercice_mois"]
    if duree_1 != 12:
        raisons.append(f"premier exercice de {duree_1} mois : seule la limite du taux réduit d'IS de l'année 1 est "
                       "proratisée, comme l'année 1 du moteur ; les années suivantes sont des exercices de 12 mois "
                       "(décalage des clôtures non modélisé)")
    if not sci["capital_libere"]:
        raisons.append("taux réduit de 15 % non appliqué : capital non entièrement libéré (CGI 219 I-b)")
    raisons += CONVENTIONS_PROJECTION

    # Base amortissable et déductions de l'année 1 : celles de fiscal_sci._sci_is.
    nature = bien.get("travaux_nature", "amelioration")
    frais = frais_acquisition(bien, params)
    en_charges = sci["frais_acquisition"] == "charges"
    base = bien["prix_net_vendeur"] + bien["frais_agence_acquereur"] + (0.0 if en_charges else frais)
    pret = echeancier_bien(bien)
    assurance_mois = assurance_mensuelle(bien)

    deficit = report_a_nouveau = tresorerie = 0.0
    annees, annees_apport = [], []
    for t in range(1, sortie["horizon_ans"] + 1):
        k_charges = (1 + sortie["indexation_charges_annuelle"]) ** (t - 1)
        s_t = {**s, "loyer_mensuel_hc": s["loyer_mensuel_hc"] * (1 + indexation) ** (t - 1)}
        b_t = {**bien, "exploitation": {**e, **{c: e[c] * k_charges for c in MONETAIRES_EXPLOITATION}}}
        encaisses = loyers_encaisses(s_t)
        charges_annee = charges(b_t, s_t)
        mois = pret[12 * (t - 1):12 * t]  # vide après la fin du prêt
        interets = sum((m["interets"] for m in mois), 0.0)
        capital = sum((m["capital"] for m in mois), 0.0)
        assurance = assurance_mois * len(mois)
        amort = amortissements_annee(base, bien["travaux"], nature, bien["mobilier"], t, params)

        duree = duree_1 if t == 1 else 12
        cloture = f"{annee_revenus + t - 1}-12-31" if annee_revenus is not None else None
        icca = interets_cca({"montant": cca, "taux": sci["cca"]["taux"]}, sci["capital_libere"], cloture, duree,
                            params)
        for r in icca["raisons"]:
            noter(r.replace(cloture, "31/12 de l'année") if cloture else r, t)

        an1 = t == 1
        deductibles = (_charges_lmnp(b_t, s_t) + interets + assurance
                       + (bien["travaux"] if an1 and nature == "entretien" else 0.0)
                       + icca["deductibles"] + (frais if an1 and en_charges else 0.0))
        resultat = encaisses - deductibles - amort["total"]
        report = imputer_deficits(resultat, deficit, params)
        impot = impot_societes(report["imposable"], duree, params,
                               taux_reduit_applicable=sci["capital_libere"])["impot"]
        apres_is = resultat - impot

        disponible = (tresorerie + encaisses - charges_annee - (interets + capital + assurance) - icca["verses"]
                      - impot)
        distribuable = report_a_nouveau + apres_is
        distribution = 0.0
        if sortie["politique_distribution"] == "annuelle":
            distribution = float(sci["distribution_annuelle"])
            if distribution > max(0.0, distribuable):
                distribution = max(0.0, distribuable)
                noter(RAISON_PLAFOND_REPORT, t)
            if distribution > max(0.0, disponible):
                distribution = max(0.0, disponible)
                noter(RAISON_PLAFOND_TRESORERIE, t)
        remboursement = float(sci["remboursement_cca_annuel"])
        if remboursement > cca:
            if cca > 0 or an1:
                noter(RAISON_CCA_SOLDE, t)
            remboursement = cca
        if remboursement > max(0.0, disponible - distribution):
            remboursement = max(0.0, disponible - distribution)
            noter(RAISON_CCA_TRESORERIE, t)

        cca -= remboursement
        report_a_nouveau = distribuable - distribution
        tresorerie = disponible - distribution - remboursement
        apport_cca = 0.0
        if tresorerie < 0:  # manque apporté par les associés en compte courant (convention du moteur)
            apport_cca, tresorerie = -tresorerie, 0.0
            cca += apport_cca
            annees_apport.append(t)
        deficit = report["deficit_reporte"]
        annees.append({
            "annee": t,
            "loyers_theoriques": loyer_annuel_theorique(s_t),
            "loyers_encaisses": encaisses,
            "charges": charges_annee,
            "charges_deductibles": deductibles,
            "interets": interets,
            "assurance": assurance,
            "capital_rembourse": capital,
            "crd_fin": crd_apres(pret, 12 * t),
            "amortissements": amort,
            "interets_cca": {"verses": icca["verses"], "deductibles": icca["deductibles"]},
            "resultat": resultat,
            "deficit_reporte": deficit,
            "imposable": report["imposable"],
            "impot": impot,
            "resultat_apres_is": apres_is,
            "report_a_nouveau": report_a_nouveau,
            "distribution": distribution,
            "remboursement_cca": remboursement,
            "apport_cca": apport_cca,
            "cca_restant": cca,
            "tresorerie_fin": tresorerie,
        })

    raisons += [f"{r} ({_annees(ans)})" for r, ans in par_annee.items()]
    if annees_apport:
        raisons.append(f"trésorerie de la SCI insuffisante en fin d'année ({_annees(annees_apport)}) : les associés "
                       f"apportent le manque en compte courant, {_euros(sum(l['apport_cca'] for l in annees))} au "
                       "total sur la durée (flux négatif des associés l'année de l'apport) ; l'avance porte intérêt au "
                       "taux du compte courant (sci.cca.taux) et se rembourse avec lui, au plus tard à la liquidation")
    return {"scenario": scenario, "apports_capital": apports_capital, "base_amortissable": base,
            "travaux_immobilises": bien["travaux"] if nature == "amelioration" else 0.0, "annees": annees,
            "raisons": raisons}


# --------------------------------------------------------------------------------------------
# Revente de l'immeuble en fin d'année N de la SCI : règles pures, puis `revendre`
# --------------------------------------------------------------------------------------------

def valeur_nette_comptable(base: float, travaux_immobilises: float, mobilier: float,
                           amortissements_cumules: float) -> float:
    """Prix de revient (base amortissable, terrain compris, + travaux immobilisés + mobilier) - amortissements
    pratiqués (S2) ; le terrain n'est jamais amorti (S4)."""
    return base + travaux_immobilises + mobilier - amortissements_cumules


def plus_value_cession(prix_revente: float, frais_revente: float, vnc: float) -> float:
    """Prix de cession net des frais - valeur nette comptable (S2) ; une moins-value est négative."""
    return prix_revente - frais_revente - vnc


def is_annee_cession(resultat_courant: float, plus_value: float, deficit_anterieur: float, duree_exercice_mois: int,
                     params: dict, taux_reduit_applicable: bool = True) -> dict:
    """IS de l'année N refaite avec la plus-value dans le résultat (S1, S3) ; déficits antérieurs imputés d'abord."""
    resultat = resultat_courant + plus_value
    report = imputer_deficits(resultat, deficit_anterieur, params)
    i = impot_societes(report["imposable"], duree_exercice_mois, params, taux_reduit_applicable)
    return {"resultat_courant": resultat_courant, "plus_value": plus_value, "resultat": resultat,
            "deficit_anterieur": deficit_anterieur, "deficit_impute": report["deficit_impute"],
            "imposable": report["imposable"], "deficit_reporte": report["deficit_reporte"],
            "base_taux_reduit": i["base_taux_reduit"], "base_taux_normal": i["base_taux_normal"],
            "duree_exercice_mois": duree_exercice_mois, "impot": i["impot"]}


def actif_apres_cession(tresorerie_avant_is: float, prix_revente: float, frais_revente: float, crd: float,
                        indemnites: float, impot: float) -> float:
    """Trésorerie de la SCI une fois l'immeuble vendu, le prêt soldé et l'IS de l'année N payé."""
    return tresorerie_avant_is + prix_revente - frais_revente - crd - indemnites - impot


def revendre(bien: dict, scenario: str, params: dict, contexte: dict | None = None,
             projection: dict | None = None) -> dict:
    """Revente de l'immeuble en fin d'année N = `sortie.horizon_ans`, à partir de la projection du même scénario
    (calculée si elle n'est pas donnée). Dit l'IS de l'année N sans et avec la cession."""
    sortie, sci = bien["sortie"], bien["sci"]
    if projection is None:
        projection = projeter(bien, scenario, params, contexte)
    n, lignes = sortie["horizon_ans"], projection["annees"]
    if len(lignes) != n or projection["scenario"] != scenario:
        raise ValueError(f"projection incohérente : {len(lignes)} ans, scénario {projection['scenario']!r} ; attendu "
                         f"{n} ans (sortie.horizon_ans), scénario {scenario!r}")
    derniere = lignes[-1]
    taux_reval = sortie["revalorisation_annuelle"][scenario]
    prix = bien["prix_net_vendeur"] * (1 + taux_reval) ** n
    frais = prix * sortie["frais_revente_taux"]
    signe = "+" if taux_reval >= 0 else "-"
    raisons = [f"prix de revente = prix net vendeur × (1 {signe} {_pct(abs(taux_reval))})^{n} = {_euros(prix)} "
               f"(sortie.revalorisation_annuelle) ; frais de revente à {_pct(sortie['frais_revente_taux'])} du prix "
               "(sortie.frais_revente_taux)"] + RAISONS_REVENTE
    cumul = sum(l["amortissements"]["total"] for l in lignes)
    vnc = valeur_nette_comptable(projection["base_amortissable"], projection["travaux_immobilises"],
                                 bien["mobilier"], cumul)
    pv = plus_value_cession(prix, frais, vnc)
    if pv < 0:
        raisons.append(f"moins-value de cession de {_euros(-pv)} déduite du résultat de l'année N (BOI-BIC-PVMV-10-20 "
                       "§30) ; la distribution de l'année N, calculée sans la cession, n'est pas revue")
    detail = is_annee_cession(derniere["resultat"], pv, lignes[-2]["deficit_reporte"] if n > 1 else 0.0,
                              12 if n > 1 else sci["duree_premier_exercice_mois"], params, sci["capital_libere"])
    if detail["deficit_reporte"] > 0:
        raisons.append(f"déficit non imputé de {_euros(detail['deficit_reporte'])} perdu à la liquidation de la SCI")

    # Prêt en cours à la fin de l'année N : se lit sur la durée, pas sur le capital restant dû, dont la dernière
    # échéance laisse un résidu flottant (±1e-10) quand l'horizon tombe sur la fin du prêt.
    sans_emprunt = emprunt(bien) <= 0
    pret_en_cours = not sans_emprunt and 12 * n < bien["financement"]["duree_mois"]
    crd = derniere["crd_fin"] if pret_en_cours else 0.0
    ira = sortie["indemnites_remboursement_anticipe"] if pret_en_cours else 0.0
    if pret_en_cours:
        raisons.append(RAISON_IRA)
    elif sortie["indemnites_remboursement_anticipe"] > 0:
        raisons.append(RAISON_IRA_SANS_EMPRUNT if sans_emprunt else RAISON_IRA_PRET_SOLDE)
    tresorerie_avant_is = derniere["tresorerie_fin"] + derniere["impot"]
    return {"annee": n, "prix_revente": prix, "frais_revente": frais, "amortissements_cumules": cumul,
            "valeur_nette_comptable": vnc, "plus_value": pv, "is_sans_cession": derniere["impot"],
            "is_avec_cession": detail["impot"], "is_detail": detail, "crd_rembourse": crd,
            "indemnites_remboursement_anticipe": ira, "tresorerie_avant_is": tresorerie_avant_is,
            "actif_apres_cession": actif_apres_cession(tresorerie_avant_is, prix, frais, crd, ira, detail["impot"]),
            "raisons": raisons}


# --------------------------------------------------------------------------------------------
# Liquidation de la SCI et imposition du boni
# --------------------------------------------------------------------------------------------

def liquider(actif_apres_cession: float, cca_restant: float, apports_capital: float, frais_liquidation: float,
             params: dict) -> dict:
    """Partage de l'actif : frais de liquidation, comptes courants (passif, S10), droit de partage sur l'actif net
    partagé (S9), apports puis boni (S8). Un boni négatif est un mali."""
    if valeur(params, "fiscal.liquidation.droit_partage_sur_masse") is not True:
        raise ValueError("fiscal.liquidation.droit_partage_sur_masse : seul le droit payé sur la masse partagée, avant "
                         "le calcul du boni, est codé")
    taux = valeur(params, "fiscal.liquidation.droit_partage")
    raisons = list(RAISONS_LIQUIDATION)
    raisons.insert(1, f"droit de partage de {_pct(taux)} (CGI 746 ; les taux réduits ne visent que le divorce et la "
                      "rupture de PACS) payé sur la masse partagée avant le calcul du boni "
                      "(fiscal.liquidation.droit_partage_sur_masse, hypothèse à vérifier)")
    reste = actif_apres_cession - frais_liquidation
    dette = max(0.0, -reste)
    if dette > 0:
        raisons.append(f"dette de la SCI à la sortie, supportée par les associés : {_euros(dette)} que l'actif après "
                       "cession ne couvre pas (prêt, indemnités, IS ou frais de liquidation) ; les associés répondent "
                       "indéfiniment des dettes sociales à proportion de leur part dans le capital (C. civ. art. "
                       "1857) : flux négatif des associés à l'année N")
    cca_rembourses = min(cca_restant, max(0.0, reste))
    cca_non_rembourses = cca_restant - cca_rembourses
    if cca_non_rembourses > 0:
        raisons.append(f"actif insuffisant : comptes courants remboursés à hauteur de {_euros(cca_rembourses)} sur "
                       f"{_euros(cca_restant)}, {_euros(cca_non_rembourses)} non remboursés (créance perdue, hors "
                       "boni)")
    actif_net = max(0.0, reste - cca_restant)  # rien à partager si l'actif ne couvre pas le passif
    droit = taux * actif_net
    boni = actif_net - droit - apports_capital
    apports_rembourses = min(apports_capital, actif_net - droit)
    if boni < 0:
        raisons.append(f"mali de liquidation de {_euros(-boni)} : apports remboursés à hauteur de "
                       f"{_euros(apports_rembourses)} sur {_euros(apports_capital)}")
    return {"actif_apres_cession": actif_apres_cession, "frais_liquidation": frais_liquidation,
            "cca_restant": cca_restant, "cca_rembourses": cca_rembourses, "cca_non_rembourses": cca_non_rembourses,
            "actif_net_partage": actif_net,
            "droit_partage": droit, "apports_capital": apports_capital,
            "apports_rembourses": apports_rembourses, "boni": boni, "mali": boni < 0, "dette_associes": dette,
            "raisons": raisons}


def _imposer(montant: float, tmi: float | None, option_bareme: bool, params: dict, objet: str) -> dict:
    """Revenu distribué (`objet` : boni ou distribution) imposé par `fiscal_sci.distribution` : PFU, ou barème avec
    l'abattement de 40 % si `option_bareme` et une TMI ; barème demandé sans TMI : PFU, raison dite."""
    d = distribution(montant, montant, tmi, 0.0, 0.0, params)
    raisons = list(d["raisons"])
    ps = valeur(params, "fiscal.prelevements_sociaux.revenus_placement")
    if option_bareme and d["bareme"] is not None:
        b = d["bareme"]
        rendu = {"regime": "bareme", "impot": b["impot"], "net": b["net"], "ir": b["ir"], "ps": b["ps"],
                 "csg_deductible_n1": b["csg_deductible_n1"]}
        abattement = valeur(params, "fiscal.dividendes.abattement_bareme")
        csg = valeur(params, "fiscal.dividendes.csg_deductible")
        raisons.append(f"{objet} au barème : abattement de {_pct(abattement)} (CGI 158-3-2° ; "
                       f"BOI-RPPM-RCM-20-10-30-10 §230), IR à la TMI fixe de {_pct(tmi)} (un montant qui fait changer "
                       f"de tranche est mal évalué), prélèvements sociaux {_pct(ps)} ; CSG déductible ({_pct(csg)}) : "
                       "économie d'IR de l'année suivante, comptée dans les flux des associés l'année même du "
                       "versement (approximation d'un an), pas dans boni_net ni recu_associes")
    else:
        if option_bareme:
            raisons.append(f"barème demandé (sortie.option_bareme) sans TMI : PFU ({objet}, CGI 200 A)")
        pfu_ir = valeur(params, "fiscal.dividendes.pfu_ir")
        rendu = {"regime": "pfu", "impot": d["pfu"]["impot"], "net": d["pfu"]["net"], "ir": montant * pfu_ir,
                 "ps": montant * ps, "csg_deductible_n1": 0.0}
        raisons.append(f"{objet} au PFU : {_pct(pfu_ir)} + prélèvements sociaux {_pct(ps)} (CGI 200 A ; LFSS 2026)")
    favorable = d["option_la_plus_favorable"]
    if favorable is not None and favorable != rendu["regime"]:
        autre = "le barème" if favorable == "bareme" else "le PFU"
        raisons.append(f"sur ce seul montant ({objet}), {autre} serait plus favorable à TMI fixe : un boni ou un "
                       "dividende qui change de tranche est mal évalué ; l'option pour le barème est globale pour les "
                       "revenus de capitaux du foyer de l'année (CGI 200 A, 2)")
    return {**rendu, "option_la_plus_favorable": favorable, "raisons": raisons}


def imposer_boni(boni: float, tmi: float | None, option_bareme: bool, params: dict) -> dict:
    """Boni imposé comme un revenu distribué (S8) : PFU, ou barème avec l'abattement de 40 % si `option_bareme` et une
    TMI. Barème demandé sans TMI : PFU, raison dite. Mali : aucun impôt."""
    if boni <= 0:
        return {"regime": None, "impot": 0.0, "net": 0.0, "ir": 0.0, "ps": 0.0, "csg_deductible_n1": 0.0,
                "option_la_plus_favorable": None,
                "raisons": [f"boni nul ou négatif (mali de liquidation, {_euros(boni)}) : aucun impôt"]}
    return _imposer(boni, tmi, option_bareme, params, "boni")


def recu_associes(liquidation: dict, imposition: dict) -> float:
    """Reçu par les associés à la sortie : comptes courants et apports remboursés, boni net d'impôt, moins la dette de
    la SCI qu'ils supportent (négatif si elle l'emporte)."""
    return (liquidation["cca_rembourses"] + liquidation["apports_rembourses"] + imposition["net"]
            - liquidation["dette_associes"])


# --------------------------------------------------------------------------------------------
# Flux des associés, TRI et VAN
# --------------------------------------------------------------------------------------------

def versements_nets(ligne: dict, tmi: float | None, option_bareme: bool, params: dict) -> dict:
    """Versements d'une année aux associés, nets d'impôt : distribution (PFU, ou barème avec la CSG déductible comptée
    l'année même), remboursement de compte courant (non imposable), intérêts de compte courant nets du PFU (S12),
    moins l'apport en compte courant du manque de trésorerie de l'année."""
    distribution_nette, raisons = 0.0, []
    if ligne["distribution"] > 0:
        imp = _imposer(ligne["distribution"], tmi, option_bareme, params, "distribution")
        distribution_nette, raisons = imp["net"] + imp["csg_deductible_n1"], imp["raisons"]
    taux_pfu = (valeur(params, "fiscal.dividendes.pfu_ir")
                + valeur(params, "fiscal.prelevements_sociaux.revenus_placement"))
    interets_nets = ligne["interets_cca"]["verses"] * (1 - taux_pfu)
    return {"distribution_nette": distribution_nette, "remboursement_cca": ligne["remboursement_cca"],
            "interets_cca_nets": interets_nets, "apport_cca": ligne["apport_cca"],
            "total": distribution_nette + ligne["remboursement_cca"] + interets_nets - ligne["apport_cca"],
            "raisons": raisons}


def flux_associes(apport_initial: float, versements: list[float], liquidation: dict, imposition: dict) -> list[float]:
    """Flux des associés, en € par an. t = 0 : - apport (capital et compte courant) ; t = 1 à N : versements nets de
    l'année ; t = N, en plus : comptes courants et apports remboursés, boni net (au barème, avec la CSG déductible du
    boni, comptée l'année même), moins la dette de la SCI à la sortie, supportée par les associés."""
    flux = [-apport_initial] + list(versements)
    flux[-1] += (liquidation["cca_rembourses"] + liquidation["apports_rembourses"] + imposition["net"]
                 + imposition["csg_deductible_n1"] - liquidation["dette_associes"])
    return flux


def rentabilite(flux: list[float], taux_actualisation: float | None) -> dict:
    """TRI (None, et la raison, s'il est indéfini) et VAN au taux d'actualisation (None sans taux). Des flux à plus d'un
    changement de signe (par exemple une dette de la SCI supportée à la sortie) peuvent avoir zéro ou plusieurs TRI :
    la raison le dit."""
    raisons = []
    signes = [f > 0 for f in flux if f != 0]
    changements = sum(1 for avant, apres in zip(signes, signes[1:]) if avant != apres)
    if changements > 1:
        raisons.append(f"flux à {changements} changements de signe (par exemple une dette de la SCI supportée par les "
                       "associés à la sortie) : le TRI peut ne pas exister ou ne pas être unique ; préférer la VAN")
    try:
        taux_interne = tri(flux)
    except ValueError as exc:
        taux_interne = None
        raisons.append(f"TRI non calculé : {exc}")
    if taux_actualisation is None:
        raisons.append("VAN non calculée : sortie.taux_actualisation vaut null")
    return {"tri": taux_interne, "van": None if taux_actualisation is None else van(taux_actualisation, flux),
            "raisons": raisons}


def sortir(bien: dict, scenario: str, params: dict, contexte: dict | None = None) -> dict:
    """Un scénario de bout en bout : projection, revente en fin d'année N, liquidation, imposition du boni, flux des
    associés, TRI et VAN. Clés : annees, revente, liquidation, flux_associes, tri, van, raisons.

    La TMI vient du contexte du foyer, sinon de `fiscal.tmi` du bien. Les raisons des étapes sont réunies dans
    `raisons`, dans l'ordre des étapes.
    """
    entree = bien["sortie"]
    projection = projeter(bien, scenario, params, contexte)
    revente = revendre(bien, scenario, params, contexte, projection)
    lignes = projection["annees"]
    liquidation = liquider(revente["actif_apres_cession"], lignes[-1]["cca_restant"], projection["apports_capital"],
                           entree["frais_liquidation"], params)
    tmi = contexte["tmi"] if contexte is not None else bien.get("fiscal", {}).get("tmi")
    imposition = imposer_boni(liquidation["boni"], tmi, entree["option_bareme"], params)
    raisons = projection["raisons"] + revente.pop("raisons") + liquidation.pop("raisons") + imposition.pop("raisons")
    liquidation.update(imposition=imposition, boni_net=imposition["net"],
                       recu_associes=recu_associes(liquidation, imposition))

    versements, par_annee = [], {}
    for ligne in lignes:
        v = versements_nets(ligne, tmi, entree["option_bareme"], params)
        versements.append(v["total"])
        for r in v["raisons"]:
            par_annee.setdefault(r, []).append(ligne["annee"])
    flux = flux_associes(apport(bien, params), versements, liquidation, imposition)
    indicateurs = rentabilite(flux, entree["taux_actualisation"])
    raisons += [f"{r} ({_annees(ans)})" for r, ans in par_annee.items()]
    raisons.append("flux de l'ensemble des associés, imposés à la TMI du foyer : t = 0, - apport (capital et compte "
                   "courant) ; t = 1 à N, distribution nette + remboursement de compte courant + intérêts de compte "
                   "courant nets ; t = N, en plus, comptes courants, apports et boni net de la liquidation ; la part "
                   "du foyer (sci.quote_part_foyer) les multiplie sans changer le TRI")
    if any(l["interets_cca"]["verses"] > 0 for l in lignes):
        pfu_ir = valeur(params, "fiscal.dividendes.pfu_ir")
        ps = valeur(params, "fiscal.prelevements_sociaux.revenus_placement")
        raisons.append(f"intérêts de compte courant : revenus de capitaux mobiliers de l'associé (service-public "
                       f"F32966), nets du PFU ({_pct(pfu_ir)} + {_pct(ps)}) ; l'option globale pour le barème "
                       "(CGI 200 A, 2) les y soumettrait aussi : non modélisé")
    raisons += indicateurs["raisons"]
    return {"annees": lignes, "revente": revente, "liquidation": liquidation, "flux_associes": flux,
            "tri": indicateurs["tri"], "van": indicateurs["van"], "raisons": raisons}
