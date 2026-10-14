# Entrée du moteur (étape 6)

Le JSON d'entrée suit le format de `${CLAUDE_PLUGIN_ROOT}/engine/tests/fixtures/immo/bien_fictif.json`, plus le bloc
`sci` (`${CLAUDE_PLUGIN_ROOT}/engine/tests/fixtures/immo/bien_fictif_sci_is.json`). Il s'écrit **dans le scratchpad
de la session**, jamais dans `immo-data/`. Il ne contient **ni bloc `foyer` ni `fiscal.tmi`** : le foyer vient de
`immo-data/foyer.json` par le flag `--foyer`, et le moteur avertit s'il trouve l'un de ces blocs dans l'entrée. Les fixtures sont **fictives** : n'en reprendre aucune valeur. Le moteur refuse
`null` : une inconnue devient une hypothèse affichée, listée dans « À vérifier ».

## Champs

| Champ | Valeur |
|---|---|
| `departement` | département du bien ; il doit figurer dans `engine/src/immo/params.json` ou `immo-data/params_local.json` (droits de mutation, sourcés et datés), sinon le moteur s'arrête (SKILL.md, §Première utilisation) |
| `prix_net_vendeur`, `frais_agence_acquereur` | étape 1 |
| `autres_frais_acquisition` | émoluments, débours et contribution de sécurité immobilière, **hors droits de mutation** : le moteur calcule les droits, les reprendre les compterait deux fois. Source : simulation notaires.fr datée, ou calcul daté au barème réglementé des émoluments du notaire et de la contribution de sécurité immobilière, lus à la source (Légifrance, notaires.fr) à la date de l'étude ; débours en hypothèse affichée. Sans aucune source datée : en `rapide`, ce barème en hypothèse affichée avec sa date ; en `complet`, l'étude s'arrête au tri. Ces frais touchent le coût total (rendements), pas le cash-flow : l'apport les paie. |
| `travaux` | étape 4, borne haute du **programme de référence** de la classe visée (celle que fixe l'utilisateur, sinon celle de l'étude), sans les aléas ; la borne basse, les aléas et les options en sensibilité ; 0 en mode `rapide`. Si le plafond est absurde à la borne haute, les paliers se donnent à la borne basse avec la condition « devis ≤ X » : 1 € de devis en plus retire 1 € au plafond. Le coût différé vers la classe suivante (E puis D avant 2034) compte les équipements remplacés (VMC simple flux puis double flux). Un audit énergétique du vendeur prime sur le modèle de l'étude (SKILL.md, « Vérifier avant d'utiliser ») |
| `mobilier` | 0 en location nue ; scénario meublé : voir §Scénario meublé. L'apport le paie (hors emprunt en `prix_plus_travaux`) |
| `financement.emprunt_mode` | `"prix_plus_travaux"` : l'emprunt couvre prix net vendeur et travaux, l'apport paie les frais. `"fixe"`, avec `financement.emprunt`, pour un autre montant ; le prix d'équilibre peut alors rester introuvable : le moteur le dit par une note sur la sortie d'erreur (« prix d'équilibre introuvable »), à reprendre dans l'étude. |
| `financement.taux_nominal` | **daté** : taux de la dernière offre ou simulation bancaire reçue par l'investisseur (banque, date), sinon observatoire mensuel publié (Crédit Logement/CSA ou baromètre de courtier, mois et date de lecture), à la durée retenue. Source et date sur la ligne « Financement » de l'étude et dans l'annexe ; un taux sans date est une hypothèse « À vérifier » |
| `financement.duree_mois` | 240 ou 300 (`yield-calculator` : 20 ou 25 ans ; HCSF : 300 mois au plus) |
| `financement.taux_assurance_annuel` | offre de prêt ou devis de délégation ; sinon 0,003, hypothèse (`yield-calculator`, valeurs par défaut) |
| `exploitation.taxe_fonciere` | voir §Taxe foncière |
| `exploitation.pno` | devis ; sinon 180, hypothèse (`yield-calculator`) |
| `exploitation.copro_non_recuperable` | dernier relevé de charges ou procès-verbal d'AG ; 0 pour une maison |
| `exploitation.cfe` | 0 en location nue ; scénario meublé : §Scénario meublé |
| `exploitation.comptable` | SCI à l'IS : selon `immo-data/profil.json` (`comptabilite_sci_dans_cash_flow` ; faux : comptabilité hors cash-flow du bien, 0, à dire dans l'analyse ; vrai : devis ou hypothèse affichée) ; au micro : 0 ; LMNP réel étudié pour lui-même : devis ou hypothèse (`yield-calculator` : 400 à 800 €/an), dans une exécution à part |
| `exploitation.gestion_taux` | 0 en gestion directe ; 0,07 si elle est externalisée (`yield-calculator`) |
| `exploitation.gli_taux` | 0 avec une garantie Visale ; sinon le taux d'un devis de GLI |
| `exploitation.capex_taux` | 0,05 (`yield-calculator`) |
| `scenarios` | voir « Scénarios » |
| `sci` | **toujours présent** (référence ou comparaison selon `montage_reference`, `references/montages.md`) : `{"regime": "is", "quote_part_foyer": 1.0, "duree_premier_exercice_mois": 12, "frais_acquisition": "incorpores", "capital_libere": true, "cca": {"montant": 0, "taux": 0}, "distribution_annuelle": 0, "remboursement_cca_annuel": 0}`. Chaque valeur est un choix à dire dans l'étude : capital libéré et exercice de 12 mois supposés (à confirmer aux statuts), aucune distribution ni compte courant rémunéré sauf demande de l'investisseur |
| `sortie` | pour chiffrer la revente, la liquidation et le TRI (SCI à l'IS seulement, `sci.regime` = `is`) : voir §Bloc `sortie`. Bloc complet ou absent : aucun champ n'a de valeur par défaut ; absent, la sortie n'a pas de clé `sortie` et l'étude dit « revente non chiffrée » |
| `foyer` | **absent** (le moteur avertit s'il le trouve) : `--foyer immo-data/foyer.json` le fournit. Une pondération bancaire des loyers différente de `hcsf.ponderation_loyers_defaut` (`params.json`) s'écrit dans `foyer.json` (`ponderation_loyers`), pas dans l'entrée |

**Champs optionnels de la fiscalité** (contrôlés par `engine/src/immo/modele.py` s'ils sont présents ;
absents, le moteur le dit dans `raisons` ou `hypotheses`) : `surface_habitable`, `code_insee`,
`immeuble_collectif`, `vefa`, `date_acquisition` (AAAA-MM-JJ), `travaux_deductibles_foncier`,
`travaux_nature` (`entretien` ou `amelioration`), `renovation_energetique` (`classe_avant`,
`classe_apres`, `depenses`), `bailleur_prive` (`regime` `i` ou `j`, `location` `intermediaire`,
`social` ou `tres_social`), `financement.differe`. Ne pas écrire `fiscal.tmi` ni
`fiscal.annee_revenus` : `--foyer` les fournit (depuis `foyer.json`).

## Quand le foyer manque

`immo-data/foyer.json` absent ou incomplet (une valeur sans `source` ni `date`), ou exécution avec `--foyer`
refusée (classifieur du mode auto, motif données personnelles, par exemple) : ne pas contourner, ni relance
déguisée, ni bloc `foyer` ou `fiscal.tmi` écrit à la main dans l'entrée.

1. Relancer **sans** `--foyer`, même entrée, sortie nommée `<slug>-sansfoyer-sortie.json`.
2. Ce qui sort : scénarios, prix d'équilibre (plafond, cible), `sci_is` (IS, cash-flow de la SCI).
   Ce qui manque : taux d'effort HCSF, `sci_ir`, régimes du nom propre, barème des dividendes.
3. L'étude dit, dans l'en-tête et dans « À vérifier » : « foyer non lu (raison, AAAA-MM-JJ) : taux d'effort,
   SCI à l'IR et nom propre non chiffrés ». Le verdict se rend sur la SCI à l'IS si c'est la référence ; sinon il
   attend le foyer. La ligne du nom propre reste vide.
4. Proposer à l'investisseur de compléter `foyer.json` (gabarit `${CLAUDE_PLUGIN_ROOT}/templates/foyer.json`) ou de
   lancer lui-même la commande (`! python3 "<racine du plugin>/engine/scripts/immo_moteur.py" --bien <entrée>
   --foyer immo-data/foyer.json > <sortie>`), puis lire la synthèse et compléter (mode `maj`).

## Scénarios

Une seule définition, celle des valeurs par défaut de `yield-calculator`.

| Scénario | `loyer_mensuel_hc` | `vacance` |
|---|---|---|
| `pessimiste` | loyer réaliste − 10 % | vacance de `profil.json` |
| `realiste` | loyer réaliste hors charges (étape 3, ou 3r en `rapide`) | vacance de `profil.json` |
| `optimiste` | loyer réaliste + 10 %, **seulement** si un levier (étape 5) ou le terrain le justifie ; sinon le loyer réaliste | vacance de `profil.json` |

La vacance est celle de `immo-data/profil.json` (`vacance_realiste`), local commercial compris ; elle
prime sur toute autre règle. Sans valeur au profil : 0,08, et 0,10 à 0,12 pour une colocation ou un
petit logement à forte rotation, justifié dans l'étude (`yield-calculator`, « Affiner la vacance »).
Le taux de logements vacants de l'INSEE n'est pas une vacance locative.

**Variante du mode `rapide`** (étape 3r) : l'optimiste est le loyer calculé à `ip_haut` de la carte
des loyers, le pessimiste le loyer réaliste − 10 %.

**Bien en parties indépendantes** (SKILL.md, étape 1) : un loyer par configuration. Entier : série
`maison` (ou `appartement`) de la carte, ramenée à la surface totale ; par parties : une série par
partie (`appartement_t1_t2`, `appartement_t3_plus`). La configuration retenue par l'utilisateur va
dans `scenarios`, l'autre en sensibilité.

## Correction de surface (étape 3r, et repère de l'étape 3)

La carte des loyers donne un €/m² pour une surface type (`engine/src/opendata/loyers.py`,
`SURFACES_TYPES_M2` : 37 m² pour `appartement_t1_t2`, 72 pour `appartement_t3_plus`, 92 pour
`maison`, 52 pour `appartement`). Le loyer au m² baisse quand la surface croît. Sur la fiche de la
commune :

```
e = ln(v_t3plus / v_t1t2) / ln(72 / 37)        (négatif : v_t1t2 > v_t3plus)
loyer au m² = valeur_m2 × (S / S_type)^e
```

`v_t1t2` et `v_t3plus` : `loyers.appartement_t1_t2.valeur_m2` et `loyers.appartement_t3_plus.valeur_m2`
de la fiche ; `S` la surface habitable retenue (étape 1) ; `S_type` et `valeur_m2` ceux de la série
choisie. Afficher `e`, le facteur `(S / S_type)^e` et le loyer obtenu. **Hypothèse « extrapolation »**,
écrite comme telle, si `S` sort de [37 ; 92] m², ou si la série est `maison` (l'élasticité est celle
des appartements). Sans l'une des deux séries, pas de correction : le dire.

## Scénario meublé (si `profil.json` le demande)

Quand la décision `meuble_logements_2_pieces_ou_moins` de `immo-data/profil.json` est vraie, pour **chaque
logement de 2 pièces ou moins**, une exécution nommée `<slug>-meuble-<partie>-sortie.json`
(la partie nommée comme à l'étape 1), en
SCI à l'IS (bloc `sci` inchangé), à côté de l'exécution nue :

- **Loyer** : loyer meublé du relevé du marché (`market-context` §« Relevé de loyers »),
  chaque annonce relue et datée. Sans relevé meublé : pas de scénario meublé chiffré, le dire. La
  carte ANIL ne publie pas de loyer meublé.
- **`mobilier`** : liste minimale du logement meublé (voir les règles ci-dessous) chiffrée par
  poste, avec la source et la date des prix ; hypothèse affichée sinon. Amortissement : durée
  `fiscal.lmnp.duree_mobilier` de `params.json` (pratique, `a_verifier`), appliquée par le moteur.
- **Vacance** : celle de `profil.json`, comme le nu, sans exception ; un écart supposé (rotation d'un bail
  d'un an) se chiffre en sensibilité seulement, dans une exécution nommée, sans changer la vacance
  du scénario.
- **`exploitation.cfe`** : voir les règles ci-dessous ; montant par avis de la commune, sinon
  hypothèse affichée.
- Effets propres à la location meublée par une SCI à l'IS (sources lues le 07/10/2026) :
  - **CFE due** : la location meublée est réputée exercée à titre professionnel, la location nue
    d'habitation non (CGI art. 1447 I, Légifrance, version du 21/02/2026) ; exonération de la
    cotisation minimum si les recettes ne dépassent pas 5 000 € (CGI art. 1647 D ;
    BOI-IF-CFE-20-20-40-10-20190626) ; les exonérations de l'art. 1459, 3° visent tout ou partie
    de l'habitation personnelle du loueur, pas un logement d'une SCI (BOI-IF-CFE-10-30-30-50-20160706
    §280, déduction : à confirmer par l'expert-comptable).
  - **Bail meublé d'un an** (9 mois pour un étudiant), même pour une SCI : l'art. 25-3 de la loi du
    6 juillet 1989 ne rend pas l'art. 10 (6 ans) applicable aux meublés (art. 25-7) ; dépôt de
    garantie de 2 mois de loyer hors charges au plus (art. 25-6).
  - **Mobilier minimal** : 11 éléments (décret n° 2015-981 du 31/07/2015, art. 2) : literie avec
    couette ou couverture, occultation des chambres, plaques, four ou micro-ondes, réfrigérateur avec
    compartiment à −6 °C au plus, vaisselle, ustensiles, table et sièges, étagères, luminaires,
    matériel d'entretien.
  - **TVA** : location meublée d'habitation exonérée, sauf si le bailleur fournit au moins 3 des 4
    prestations para-hôtelières (petit-déjeuner, nettoyage régulier, linge, réception) (CGI art.
    261 D 4° ; BOI-TVA-CHAMP-10-10-50-20-20250326).
  - Pas de statut LMNP pour la SCI à l'IS : la distinction LMP / LMNP s'apprécie au niveau du foyer
    ou des associés d'une société à l'IR (CGI art. 155 IV ; BOI-BIC-CHAMP-40-10-20260415 §50 et §140) ;
    SCI à l'IS : par déduction, ces textes ne visant pas l'IS ; l'amortissement suit les règles
    de l'IS, appliquées par le moteur.
  - **À vérifier** (non relus à la source) : l'objet social des statuts de la SCI doit couvrir la
    location meublée (à valider par le notaire) ; la CFE n'est pas due l'année de création (CGI
    art. 1478 II).
  - Une SCI **à l'IR** qui louerait en meublé deviendrait passible de l'IS au-delà de 10 % de
    recettes commerciales (CGI art. 206-2 ; BOI-IS-CHAMP-10-30-20180704 §250 et s.) : la ligne
    `sci_ir` d'un scénario meublé ne se lit pas comme un montage possible.

Un logement de plus de 2 pièces n'a pas de scénario meublé, sauf demande de l'investisseur ; la décision
fausse ou absente : pas de scénario meublé, sauf demande.

## Bloc `sortie` (revente, liquidation, TRI)

Revente de l'immeuble en fin d'année N, liquidation de la SCI, TRI et VAN des flux des associés
(`engine/src/immo/sortie.py`). Chaque hypothèse se cite dans l'étude avec sa source et sa date ; sans source datée,
hypothèse « À vérifier ». Le moteur refuse un champ absent.

| Champ | Valeur et source |
|---|---|
| `horizon_ans` | entier de 1 à 40 : horizon de revente ; 10 pour le TRI de référence (convention de la méthode), sauf demande de l'investisseur |
| `revalorisation_annuelle` | un taux par scénario (`pessimiste`, `realiste`, `optimiste`), dans ]-1 ; 1[ : évolution annuelle du prix au m² de la commune tirée de DVF (étape 2, `market-context`), période et date de lecture citées ; sans série datée, hypothèse « À vérifier » |
| `indexation_loyers_annuelle` | un taux par scénario : glissement annuel de l'IRL, série INSEE 001515333 (au 07/10/2026 : 148,37 au 2e trimestre 2026, +1,15 % sur un an, publié le 10/07/2026, insee.fr/fr/statistiques/9022797), la révision étant plafonnée à la variation annuelle de l'IRL (loi 89-462 art. 17-1, version du 24/08/2022). **Logement F ou G pendant la détention : aucune révision** (même article ; loi 2022-1158 art. 12) ; le moteur force 0 et le dit dans `raisons` |
| `indexation_charges_annuelle` | taux annuel des charges fixes (taxe foncière, PNO, copropriété, CFE, comptabilité) : source datée (évolution de la taxe foncière de la commune, indice des prix de l'INSEE) ; sinon hypothèse « À vérifier » |
| `classe_dpe_location` | classe DPE pendant la détention : celle d'après les travaux de l'étape 4 s'ils précèdent la mise en location |
| `frais_revente_taux` | frais de vente à la charge de la SCI, en part du prix, dans [0 ; 1[ (honoraires d'agence, diagnostics) : barème d'agence relevé et daté ; sinon hypothèse « À vérifier » |
| `indemnites_remboursement_anticipe` | € : clause de l'offre de prêt ; sans offre, hypothèse « À vérifier ». Ignorées si le prêt est soldé à l'année N ; non déduites du résultat imposable (hypothèse prudente du moteur) |
| `frais_liquidation` | € : greffe, actes et annonces légales de la dissolution et de la clôture. Annonces au tarif 2026 : nomination du liquidateur 153 € HT, clôture 111 € HT (service-public A18724) ; greffe et rédaction des actes : devis ou tarif daté, sinon hypothèse « À vérifier » |
| `politique_distribution` | `annuelle` : `sci.distribution_annuelle` versée chaque année, plafonnée par le report à nouveau puis par la trésorerie ; `liquidation` : rien avant la sortie. Choix de l'investisseur, à dire |
| `option_bareme` | `false` (PFU) sauf choix de l'investisseur ; le moteur dit quand le barème serait plus favorable sur un seul montant (option globale du foyer, CGI 200 A, 2) |
| `taux_actualisation` | taux de la VAN, choix dit dans l'étude (par exemple le rendement d'un placement sans risque de même durée, cité avec sa source et sa date) ; `null` : pas de VAN |

Lecture : la synthèse (`immo_synthese.py`) donne la section « Sortie » : par scénario, TRI, VAN, plus-value,
IS de la cession (IS de l'année N avec - sans la plus-value), boni net et reçu à la sortie. Les raisons
(`sortie.<scénario>.raisons`) s'extraient à part (SKILL.md, étape 6) ; détail dans `revente`, `liquidation` et
`flux_associes` (t = 0 à N ; au barème, les flux comptent la CSG déductible, pas `recu_associes` ni `boni_net`).
Limites dites dans `raisons`, à reprendre dans « À vérifier » : durée de la structure (50 ans aux paramètres,
durée réelle selon le BOFiP), droit de partage payé sur la masse, remboursement des comptes courants non imposable
(sans texte explicite), intérêts de compte courant au PFU même avec l'option pour le barème, TMI fixe au barème.
Une dette de la SCI à la sortie (vente qui ne couvre pas le prêt) est supportée par les associés (C. civ. art. 1857,
lu le 08/10/2026) : flux négatif à l'année N, dit dans `raisons`. Des flux qui changent de signe plus d'une fois donnent
un TRI absent ou non unique : citer alors la VAN.
Un manque de trésorerie de la SCI est apporté par les associés en compte courant (flux négatif l'année de
l'apport, remboursé au plus tard à la liquidation) : le total apporté est dit dans `raisons` et se cite dans l'étude.

## Sensibilité au loyer

Une exécution nommée `<slug>-loyer50-sortie.json` : entrée réaliste, `loyer_mensuel_hc` du scénario
`realiste` + 50 €. La ligne « +50 €/mois de loyer ⇒ +X € de plafond » donne X =
`prix_equilibre.realiste` de cette sortie − celui de la sortie de base (`references/negociation_livrable.md`).

## Taxe foncière

1. **L'avis de taxe foncière du vendeur** (dernier avis, pièce n° 1, `references/pieces_a_demander.md`) ;
   à défaut, le montant de l'annonce relevé par `lbc-scraper`, cité comme tel.
2. Sinon, **un ratio documenté de la même commune** (€/m² ou rapport TF/TEOM tiré d'un avis ou d'une
   annonce de cette commune, cité avec sa source et sa date ; montants déjà relevés : rubrique « Taxe foncière,
   montants observés » de `immo-data/communes.md`), jamais celui d'une autre commune ;
   le taux communal de la fiche (`fiscalite_locale`) ne donne pas la base.
3. Sinon, pas de montant inventé : hypothèse affichée, chiffrée en sensibilité (convention de méthode
   de ce skill : ± 500 €/an sur le plafond, exécution nommée) et la pièce demandée.

TEOM et taxe foncière viennent de la même base cadastrale : une TEOM supposée pour passer d'un loyer
charges comprises au hors charges fixe une taxe foncière implicite ; garder les deux cohérentes ou
dire l'écart.

## Taux d'effort

`--foyer immo-data/foyer.json` construit le bloc `foyer` (`engine/src/immo/foyer.py`) selon cette règle :
mensualité **future** de chaque prêt existant (`mensualites.future`), revenus d'activité du foyer plus les loyers
HC existants pondérés comme celui du bien. La sortie en montre les clés dans `hcsf.entrees_foyer` ; leurs valeurs
ne se recopient pas dans l'analyse. Le taux d'effort est un indicateur : la banque décide, et la décision HCSF lui
laisse une marge de dérogation. Pour un prêt consenti à une SCI à l'IS, l'application de la norme HCSF n'est pas
établie : l'écrire au conditionnel (« si la banque applique la norme au prêt de la SCI »).
