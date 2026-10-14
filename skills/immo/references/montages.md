# Montages : montage de référence du profil, lu dans le moteur (étape 7)

Comparer sur le scénario réaliste, année 1 ; la revente et le TRI de la SCI à l'IS viennent du bloc `sortie` du moteur
(`references/entree_moteur.md` §Bloc `sortie`, section « Sortie » de la synthèse).

## Le montage de référence

Le montage de référence est la décision `montage_reference` de `immo-data/profil.json` (`sci_is`, ou un régime
du nom propre : `foncier_reel`, `lmnp_reel`…), avec sa date et sa source. Le skill le **calcule et le
recommande**. Les autres montages sont des **lignes de comparaison** : chiffres en regard, **jamais une
recommandation**, sauf si l'investisseur la demande explicitement dans la session. Un montage de comparaison qui
bat la référence sur un bien se dit (« écart de X €/mois, à examiner avec l'investisseur ») ; la recommandation
ne change pas.

Le moteur évalue toujours les deux familles côte à côte : l'entrée porte toujours le bloc `sci`, et les régimes
du nom propre sortent dès que le foyer est lu. Ci-dessous, les deux cas sont décrits ; celui de la référence
ouvre la section de l'étude, l'autre tient en une ligne de comparaison.

## Lire la SCI dans la sortie

Le moteur calcule `sci_is` et `sci_ir` **seulement si l'entrée porte le bloc `sci`**
(`references/entree_moteur.md`) ; sans lui, les deux régimes sortent `non évaluable : bloc sci
absent`. La synthèse (`immo_synthese.py`) les affiche dans le tableau « Fiscalité », avec la
colonne « CF foyer (distribution) » dès qu'une distribution est demandée.

| Ce qu'on écrit | Clé de `fiscalite.scenarios.realiste.regimes.sci_is` |
|---|---|
| IS de l'année 1 | `impot_total` (détail : `is_detail`, base au taux réduit et au taux normal) |
| Cash-flow de la SCI, après IS | `cash_flow_mensuel_net_net` |
| Rendement net-net | `rendement_net_net` |
| Résultat fiscal, amortissements | `resultat_fiscal`, `amortissements.{bati,travaux,mobilier,total}` |
| Déficit reporté (reste dans la SCI) | `deficit_reporte` |
| Cash-flow du foyer, s'il est distribué | `distribution.cash_flow_mensuel_foyer`, `distribution.distribuable`, `distribution.option_la_plus_favorable` |

- Une extraction ciblée de ces clés est permise (ce sont des clés du bien) ; jamais `hcsf.entrees_foyer`
  ni `effet_foyer.impot_foyer_*`.
- **Deux cash-flows, montrés séparément** : celui de la SCI (après IS) et celui du foyer (ce qui est
  distribué, net de son imposition). Distribuer n'est pas obligatoire : par défaut l'entrée met
  `distribution_annuelle` à 0 (la SCI capitalise) ; une exécution nommée `<slug>-distribution-sortie.json`
  chiffre une distribution quand l'investisseur la demande.
- Les taux (IS, taux réduit des PME et sa limite, prélèvements sociaux, PFU) sont ceux de
  `engine/src/immo/params.json`, sourcés et datés (champs `source`, `verifie_le`) : les citer avec leur source,
  et dire s'ils sont périmés (`immo_fraicheur.py`).
- `fiscalite.hypotheses` va **en entier** dans l'annexe (« À vérifier »), lignes SCI comprises.

**SCI à l'IR** : `sci_ir` (foncier réel en quote-part `sci.quote_part_foyer`). Il exige la TMI :
sans foyer, il sort non évaluable ; le dire. Micro-foncier exclu pour un associé (raison du moteur).

**Sans foyer** (`foyer.json` absent, incomplet ou exécution refusée) : `sci_is` reste **évaluable** (IS,
cash-flow de la SCI, rendement net-net) ; manquent le barème des dividendes (le PFU seul sort, raison « barème
non évalué »), `sci_ir`, les régimes du nom propre et le taux d'effort. Les écrire « non chiffrés : foyer
non lu », jamais estimés à la main. Si la référence du profil est un régime du nom propre, le verdict attend le
foyer : le dire.

## Nom propre

Meilleur régime **éligible et évaluable** du nom propre (`micro_foncier`, `foncier_reel`,
`lmnp_micro_bic`, `lmnp_reel`, `bailleur_prive`), lu dans la même table : `impot_total`,
`cash_flow_mensuel_net_net`, `rendement_net_net`, et `raisons` s'il est écarté. Référence du profil : le
régime qu'elle nomme, et le meilleur des autres en comparaison s'il fait mieux.

- **Une raison peut citer un montant du foyer** (revenus fonciers bruts du micro-foncier, par
  exemple) : la reformuler sans le montant (« revenus fonciers du foyer au-delà du plafond, CGI
  art. 32 »).
- **`effet_foyer`** (foncier réel) : impôt du foyer avec le bien moins sans, la même année. S'il
  diverge de `impot_total` du régime (bien seul), l'effet marginal fait foi : cash-flow net-net du
  foyer = cash-flow avant impôt − `effet_marginal` / 12, à dire comme tel. Les montants du foyer
  (`impot_foyer_seul`, `impot_foyer_avec_bien`, `report_entrant`) ne se recopient pas.
- **Un LMNP n'absorbe pas le report de déficit foncier du foyer** : ce report ne s'impute que sur
  les revenus fonciers des 10 années suivantes (BOI-RFPI-BASE-30-20, §110, 160, 310 et 450) ; un
  bien loué nu l'absorbe, un meublé (BIC) non.

## SCI à l'IS : points pratiques

- **Comptabilité** : selon `immo-data/profil.json` (`comptabilite_sci_dans_cash_flow`) ; hors cash-flow du
  bien, 0, à dire dans l'étude. Hors comptabilité, SCI à l'IS et nom propre ont le même cash-flow avant impôt ;
  l'écart tient à l'impôt et à la revente.
- **Revente** : plus-value calculée sur la valeur nette comptable, après amortissements, sans
  abattement pour durée de détention, imposée à l'IS (CGI 38-1, 219 I-a quater ; BOI-BIC-PVMV-10-20 §30 ;
  relus le 07/10/2026) ; chiffrée par le bloc `sortie` du moteur, avec la liquidation (droit de partage 2,5 %,
  CGI 746 ; boni imposé comme un revenu distribué).
- **Durée du bail nu** : une SCI bailleresse loue pour 6 ans au moins, sauf SCI « familiale »
  (associés parents ou alliés jusqu'au 4e degré), 3 ans (loi du 6 juillet 1989, art. 10 et 13 ;
  ecologie.gouv.fr, mise à jour du 19/12/2025). Qualification de la SCI de l'investisseur : à confirmer par le
  notaire. Bail meublé : `references/entree_moteur.md` §Scénario meublé.
- **Achat avant l'immatriculation** : faculté de substitution au profit de la SCI, ou achat au nom
  de la SCI en formation avec reprise des engagements (C. civ. art. 1843, non relu) ; à valider par
  le notaire.
- **Apports en compte courant** : ils financent le cash-flow négatif ; leur remboursement n'est pas
  imposable (sans texte cité : à confirmer avec l'expert-comptable). Intérêts : `sci.cca` de l'entrée,
  plafonnés par le moteur.
- **Aides** (état relevé le 04/10/2026, à relire à la source à la date de l'étude) : MaPrimeRénov', non
  (personnes morales exclues) ; éco-PTZ, non (sociétés civiles à l'IS exclues) ; Denormandie et déficit
  foncier majoré, non (impôt sur le revenu) ; primes CEE, oui (artisan RGE, avant de signer le devis) ; TVA
  réduite sur la rénovation, oui sous critères ; exonération de taxe foncière (CGI 1383-0 B), si la commune
  l'a votée (rubrique de `immo-data/communes.md`).

## Sources

Tout taux ou plafond cité porte sa source et sa date : `engine/src/immo/params.json` et
`immo-data/params_local.json` (champs `source`, `verifie_le`), sinon Légifrance ou le BOFiP, lus à la date de
l'étude.

## Conclusion de la section

Une ligne : **le montage de référence**, son cash-flow réaliste après impôt et son impôt de l'année 1 (IS pour
la SCI), puis la ligne de comparaison (SCI à l'IS ou meilleur régime du nom propre : cash-flow net-net, écart en
€/mois). Les paliers d'offre (étape 8) se calculent avant impôt, puis se disent après l'impôt du montage de
référence.
