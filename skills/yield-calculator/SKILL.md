---
name: yield-calculator
description: "Produit le tableur Excel (.xlsx) de rentabilité locative d'un bien étudié : rendements brut / net / net-net selon le régime fiscal, cash-flow mensuel avec prêt paramétrable, TRI 10 ans, en 3 scénarios (pessimiste / réaliste / optimiste). À déclencher pour toute question de rendement, rentabilité, cash-flow, TRI ou simulation de prêt sur un bien candidat. Étape 6 de `/immo` (moteur) ; préalables : market-context (+ renovation-estimator / value-add-analyzer si pertinents) ; suivant : negoc. Pour l'étude d'un bien, passer par `/immo` : le moteur fait les calculs ; ce skill est la spécification du tableur ; le générateur .xlsx n'est pas encore fourni par le moteur et, d'ici là, la rentabilité se lit dans la sortie du moteur."
---

# Yield Calculator - rentabilité et cash-flow

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Produit le **fichier Excel de décision** qui répond à la seule vraie question : *ce bien va-t-il me rapporter de l'argent chaque mois après tout, et combien au bout de 10 ans ?*

## Statut : une spécification, le générateur `.xlsx` n'est pas encore fourni

Ce skill **ne calcule rien** : les calculs (frais d'acquisition, prêt, cash-flow, fiscalité, prix d'équilibre) sont ceux du moteur (`${CLAUDE_PLUGIN_ROOT}/engine/src/immo`), appelé par `/immo`, qui n'invoque pas ce skill (`${CLAUDE_PLUGIN_ROOT}/skills/immo/SKILL.md`, § Règles de conduite). Ce skill décrit le **tableur** de présentation des sorties du moteur. Le générateur `.xlsx` **n'est pas encore fourni par le moteur** : d'ici là, la rentabilité (rendements, cash-flow, fiscalité, revente et TRI) se lit dans la sortie JSON du moteur et dans l'étude de `/immo`, et aucun tableur ne se réécrit à la main (`${CLAUDE_PLUGIN_ROOT}/skills/immo/references/negociation_livrable.md`, § Tableur). La revente et le TRI sont calculés par le moteur (`engine/src/immo/sortie.py`, bloc `sortie` décrit dans `${CLAUDE_PLUGIN_ROOT}/skills/immo/references/entree_moteur.md`) : l'onglet 7 reprendra ses flux et ses hypothèses datées quand le générateur existera, et ses repères de revalorisation non sourcés ci-dessous ne s'appliquent pas à une étude.

Les chiffres réglementaires ne se recopient pas ici : taux d'IS, prélèvements sociaux, PFU et droits de mutation se lisent dans `engine/src/immo/params.json` (clé citée), complété par `immo-data/params_local.json` pour la zone de l'utilisateur ; la situation du foyer (TMI, revenus, prêts en cours) dans `immo-data/foyer.json`. Les valeurs par défaut d'exploitation ci-dessous sont reprises par `${CLAUDE_PLUGIN_ROOT}/skills/immo/references/entree_moteur.md` : elles ne changent pas sans source, et celles marquées « repère non sourcé » restent des hypothèses affichées.

## Quand l'utiliser

- Étape 6 de `/immo`, celle du moteur (après lbc-scraper, market-context, renovation-estimator, value-add-analyzer)
- Demande explicite sur rendement / cash-flow / TRI

## Production du tableur (quand le générateur existera)

Le .xlsx se produira avec openpyxl : multi-onglets, formules natives Excel (pas de valeurs en dur quand une formule est possible), formats monétaires et pourcentages lisibles.

## Structure du tableur à produire

Fichier : `immo-data/analyses/[quartier]-[prix-k€]-[YYYY-MM-DD].xlsx`

### Onglet 1 - « Paramètres »

Toutes les variables d'entrée, modifiables par l'utilisateur, avec **cellules colorées en vert** pour les inputs :

```
SECTION A - Bien
  Prix affiché FAI            [input]
  Frais d'agence              [input ou déduit]
  Prix net vendeur            [calculé]
  Frais d'acquisition         [sortie du moteur, aucun forfait : droits de mutation calculés par engine/src/immo/acquisition.py (dmto_detail, taux de engine/src/immo/params.json § dmto) + autres_frais_acquisition (émoluments, débours, CSI : ${CLAUDE_PLUGIN_ROOT}/skills/immo/references/entree_moteur.md)]
  Travaux estimés             [input depuis renovation-estimator]
  Ameublement (si meublé)     [input, typiquement 3-5 k€ par logement : repère non sourcé, devis ou liste chiffrée à préférer]
  COÛT TOTAL D'ACQUISITION    [calculé]

SECTION B - Financement
  Apport                      [input ; décision `apport` de immo-data/profil.json]
  Montant emprunté            [calculé]
  Taux d'intérêt nominal      [input, taux du jour relevé auprès des banques ou d'un courtier, date de consultation notée à côté]
  Durée                       [input, 20 ou 25 ans]
  Différé de remboursement    [input, mois, partiel/total pendant travaux ; lève le cash-flow année 0-1, à négocier]
  Assurance emprunteur        [input, 0.25-0.40% du capital : repère non sourcé ; offre de prêt ou devis de délégation à préférer]
  Mensualité totale           [calculé, formule PMT]

SECTION C - Loyer
  Loyer mensuel HC scénario réaliste [input depuis market-context]
  Loyer mensuel HC scénario pessimiste [input, -10%]
  Loyer mensuel HC scénario optimiste  [input, +10% ou scénario value-add]
  Charges récupérables mensuelles      [input]

SECTION D - Charges d'exploitation
  Taxe foncière annuelle               [input : annonce ou avis du vendeur ; la fiche de données ouvertes donne le taux communal, pas la base]
  Charges copro non récupérables       [input]
  Assurance PNO                        [input, ~120-250 €/an : repère non sourcé ; devis à préférer]
  Gestion locative (si externalisée)   [input, 5-8% TTC du loyer encaissé : repère non sourcé ; 0 en gestion directe]
  Comptable LMNP (si applicable)       [input, 400-800 €/an : repère non sourcé ; devis à préférer. SCI à l'IS : décision `comptabilite_sci_dans_cash_flow` de immo-data/profil.json]
  Provision CAPEX                      [input, 5% du loyer : repère non sourcé]
  Vacance locative                     [input : décision `vacance_realiste` de immo-data/profil.json ; à défaut 8 %, valeur par défaut du skill, ajustable]

SECTION E - Fiscalité (3 régimes)
  TMI du foyer                         [input : immo-data/foyer.json, clé `tmi` (avec sa source et sa date) ; recalibrer par scénario foncier : les loyers nets remontent au foyer]
  Prélèvements sociaux                 [input par régime, taux lus dans engine/src/immo/params.json § fiscal.prelevements_sociaux (revenus_fonciers ; bic_lmnp ; revenus_placement pour les dividendes), avec la source et la date de chaque clé]
  Régime cible                         [liste déroulante : LMNP réel / SCI IS / foncier réel / micro-foncier]
```

### Onglet 2 - « Rendements »

Tableau synthèse 3 scénarios côte à côte :

| Indicateur | Pessimiste | Réaliste | Optimiste |
|---|---|---|---|
| Loyer annuel HC | | | |
| **Rendement brut** = loyer annuel / coût total d'acquisition | | | |
| Charges d'exploitation annuelles | | | |
| **Rendement net (avant impôt)** = (loyer - charges) / coût total | | | |
| Impôt annuel (selon régime) | | | |
| **Rendement net-net (après impôt)** = (loyer - charges - impôt) / coût total | | | |
| **Cash-flow mensuel net-net** = (loyer encaissé - charges exploitation - impôt - mensualité totale) / 12 | | | |
| Enrichissement patrimonial mensuel = capital amorti / 12 (remboursé par le locataire) | | | |
| **Rendement cash-on-cash** = cash-flow annuel net-net / cash investi (apport + frais notaire + travaux + meublé) | | | |
| Ratio de couverture = loyer mensuel / (mensualité + charges mensualisées) : >1 : le bien s'autofinance | | | |

**Important** :
- Le rendement net-net et le cash-flow dépendent du régime fiscal choisi (cellule E régime cible).
- **Ne pas confondre cash-flow et enrichissement.** Le cash-flow est ce qui reste sur le compte chaque mois (la mensualité, capital compris, en sort). L'enrichissement réel sur 20 ans vient surtout du **capital remboursé par le locataire** (amortissement) + de la **plus-value latente** - souvent bien plus que le cash-flow. D'où deux lignes distinctes : ne jamais gonfler le cash-flow en y réinjectant le capital amorti.

### Onglet 3 - « Amortissement prêt »

Tableau année par année sur la durée du prêt :

| Année | Mensualités annuelles | Intérêts | Principal remboursé | Capital restant dû |
|---|---|---|---|---|

Formules Excel standard : `IPMT()`, `PPMT()`, `CUMPRINC()`, `CUMIPMT()`.

### Onglet 4 - « Fiscalité - LMNP réel »

- Loyer BIC annuel
- Charges déductibles (intérêts prêt, assurance, TF, copro non récup, PNO, compta, gestion, frais de bail, etc.)
- **Amortissements** :
  - Bien hors foncier : 80-85% du prix HT sur 25-30 ans → taux annuel 3.3-4%
  - Foncier (terrain) : non amortissable (15-20% du prix)
  - Mobilier : 7-10 ans
  - Travaux : immobilisés ou passés en charge selon montant
- **Résultat fiscal BIC** = loyers – charges – amortissements (plafonné à 0 en LMNP non pro, le solde d'amortissement se reporte)
- Impôt = résultat positif × (TMI + PS sur les BIC meublés non pro : engine/src/immo/params.json § fiscal.prelevements_sociaux.bic_lmnp). Souvent 0 € pendant 8-15 ans grâce aux amortissements (repère non sourcé : la sortie du moteur fait foi).
- Revente : les amortissements déduits sont réintégrés dans la plus-value (CGI art. 150 VB III, LF 2025 art. 84, cessions depuis le 15/02/2025 ; hors résidences étudiantes, seniors et EHPAD) : à intégrer au TRI de l'onglet 7.

### Onglet 5 - « Fiscalité - SCI IS »

- Chiffre d'affaires (loyers HT)
- Toutes charges déductibles + **amortissements** (idem LMNP mais en comptabilité IS)
- IS : taux réduit des PME dans une limite de bénéfice, taux normal au-delà : valeurs, conditions et source dans les clés que lit le moteur, `engine/src/immo/params.json` § fiscal.is (taux_reduit, taux_normal, limite_taux_reduit_12_mois)
- Distribution aux associés via dividendes : PFU (part IR : engine/src/immo/params.json § fiscal.dividendes.pfu_ir ; PS : § fiscal.prelevements_sociaux.revenus_placement) OU option barème : TMI sur le dividende après abattement (§ fiscal.dividendes.abattement_bareme), plus les PS sur le dividende brut (CSG déductible : § fiscal.dividendes.csg_deductible)
- Piège : imposition de la plus-value de cession au régime IS (pas de durée d'abattement), impact à long terme

### Onglet 6 - « Fiscalité - Foncier réel »

- Revenu brut foncier (loyers nus HC)
- Charges déductibles (intérêts, TF, PNO, gestion, travaux d'entretien/réparation/amélioration)
- Si charges > revenus : **déficit foncier** imputable sur revenu global jusqu'à **10 700 €/an** (hors intérêts d'emprunt ; l'excédent et les intérêts se reportent sur les seuls revenus fonciers des 10 années suivantes) ; limite rehaussée sur option, **à concurrence des seules dépenses de rénovation énergétique** et au plus **21 400 €/an**, quand les travaux font passer le logement de E/F/G à A-D (devis accepté depuis le 05/11/2022, dépenses payées du 01/01/2023 au 31/12/2027, DPE A-D à justifier au plus tard le 31/12/2027, professionnels RGE quand l'éco-PTZ l'exige ; CGI art. 156 I 3°, LF 2026 art. 47, vérifié le 23/09/2026 ; plafonds lus par le moteur : `engine/src/immo/params.json` § fiscal.deficit_foncier)
- Imposition du revenu foncier net : TMI + PS des revenus fonciers (engine/src/immo/params.json § fiscal.prelevements_sociaux.revenus_fonciers)
- Régime pertinent surtout si TMI ≥30% ET travaux lourds la 1ère année

### Onglet 7 - « TRI 10 ans »

Projection cash-flows annuels sur 10 ans :
- Année 0 : -apport -frais notaire -travaux
- Années 1-10 : cash-flow net-net annuel + remboursement de capital
- Année 10 : revente estimée (prix acquisition × (1 + taux_revalorisation)^10) – CRD – frais revente 6-8% (repère non sourcé) – PV imposable

**Hypothèse de revalorisation** (valeurs par défaut du skill, repère non sourcé, à ajuster au marché de la zone : `immo-data/MARCHE.md`, tendance des prix) :
- Pessimiste : 0 %/an (marché stable)
- Réaliste : +1 %/an
- Optimiste : +2 %/an (uniquement si levier value-add réalisé)

Formule : `=IRR()` sur la colonne des cash-flows nets annuels.

### Onglet 8 - « Synthèse »

1 page imprimable avec :
- Résumé du bien (5 lignes)
- Tableau Rendements 3 scénarios (onglet 2 recopié)
- TRI 10 ans 3 scénarios
- **Enrichissement patrimonial à 10 ans** = capital amorti cumulé + plus-value latente (scénario réaliste) - le « vrai » gain, distinct du cash-flow
- **Verdict** : Go / No-go / À creuser
- 3 questions à poser au vendeur/agent
- **Prix d'achat d'équilibre** : prix FAI pour lequel le cash-flow mensuel réaliste s'annule (repris par `/negoc` comme prix plafond, `${CLAUDE_PLUGIN_ROOT}/skills/negoc/references/immo_achat.md` §Paliers)
- **Prix cible** : prix FAI pour lequel le cash-flow mensuel réaliste atteint le seuil de confort (décision `seuil_confort_cf_mensuel` de immo-data/profil.json) (repris comme prix cible) ; ces deux prix sont recalculés en formules (notaire, prêt, fiscalité suivent le prix)

## Hypothèses par défaut (ajustables)

À pré-remplir ; une décision de `immo-data/profil.json` prime sur la valeur par défaut, et l'utilisateur peut ajuster chaque cellule :

| Paramètre | Valeur par défaut | Source |
|---|---|---|
| Vacance locative | décision `vacance_realiste` du profil ; à défaut **8 %** | valeur par défaut du skill, repère non sourcé, ajustable |
| CAPEX | 5 % du loyer | repère non sourcé : standard conservateur |
| Gestion locative externalisée | 7 % TTC (6.5% HT) | repère non sourcé : ordre de grandeur, à vérifier auprès des agences de la zone ; 0 en gestion directe |
| Assurance PNO | 180 €/an | repère non sourcé : ordre de grandeur ; devis à préférer |
| Taxe foncière | **à vérifier** via ancien avis TF ou fiche d'évaluation cadastrale (gratuite, centre des impôts fonciers - permet aussi de contester une surface/catégorie erronée) | Taux de la commune : rubrique « Taxe foncière, taux » de `immo-data/communes.md`. Si rénovation énergétique éligible art. 1383-0 B CGI **et** délibération commune : exonération 50-100 % années 1-3 |
| Frais d'acquisition | calculés par le moteur (`engine/src/immo/acquisition.py`, `engine/src/immo/params.json` § dmto) + `autres_frais_acquisition` | Aucun forfait : `${CLAUDE_PLUGIN_ROOT}/skills/immo/references/entree_moteur.md` |
| Taux emprunt | **relevé du jour** auprès des banques, d'un courtier ou d'un baromètre lu le jour même, avec sa date | Aucune valeur par défaut |
| Assurance emprunteur | 0.30 % du capital initial par an | repère non sourcé : offre de prêt ou devis de délégation à préférer |
| Revalorisation (réaliste) | 1 %/an | repère non sourcé : prudent, à ajuster au marché de la zone |

**Affiner la vacance par la rotation locative** : la vacance n'est pas qu'un % forfaitaire, c'est surtout le **coût des relocations**. Durées d'occupation moyennes (repère non sourcé : ordres de grandeur terrain, à ajuster localement) : studio/T1 ~2 ans, T2 ~2,5 ans, T3 ~4-5 ans, T4+ ~5-7 ans. Chaque relocation coûte **1 à 2 mois de loyer** (vacance + remise en état + frais). Un studio près de la gare reloué ~10 fois en 20 ans, c'est 10-20 mois de loyer perdus : la vacance réelle d'un petit logement à fort turnover dépasse souvent les 8 % par défaut. Une vacance différente de celle du profil (`vacance_realiste` de `immo-data/profil.json`) se justifie par un fait du bien (colocation, forte rotation), dit dans l'étude : jamais un taux forfaitaire. Corollaire : un T3/T4 stable peut battre un studio « plus rentable sur le papier ».

## Garde-fous

1. Ne jamais montrer un rendement unique. Toujours pessimiste/réaliste/optimiste, même pour un bien excellent.
2. **Le cash-flow mensuel** est la priorité si l'objectif de l'investisseur est le cash-flow (`profil.json`). Si le cash-flow réaliste est négatif, le signaler d'emblée en rouge sur l'onglet Synthèse.
3. **Le TRI 10 ans** doit toujours inclure un scénario « je revends » ET un scénario « je garde et je capitalise » (sans plus-value de cession).
4. Si l'utilisateur n'a pas encore tranché son régime fiscal, sortir les **3 régimes en parallèle** sur l'onglet Synthèse, et recommander lequel optimise le cash-flow sur ce bien précis.
5. Marquer en rouge toute cellule où on a mis une valeur « à vérifier » (TF, taux, etc.) pour que l'utilisateur ne la loupe pas.
6. Si le rendement brut est inférieur au seuil de rendement minimal, et qu'aucun levier value-add n'est activable, c'est un **No-go quasi automatique** (le cash-flow sera négatif et le financement difficile). Seuil : une décision de `immo-data/profil.json` sur ce point, si l'utilisateur en a écrit une ; à défaut **6 % brut**, valeur par défaut du skill (repère non sourcé, ajustable : plus bas en marché tendu à faible risque locatif, plus haut en marché détendu).
7. Ne pas mélanger immeubles entiers et lots isolés dans les comparables.
8. Baser les loyers sur le médian du marché, pas le haut de fourchette.
