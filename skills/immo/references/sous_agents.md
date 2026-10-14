# Sous-agents des étapes 3 à 5 (`complet`) : gabarits de prompt

A, B et C partent **dans le même message** (`run_in_background`). C travaille en mode profil : il ne
dépend pas de A et B, et intègre leurs résultats s'ils arrivent avant lui.

| | Skill du plugin | Modèle | Étape |
|---|---|---|---|
| A, marché | `${CLAUDE_PLUGIN_ROOT}/skills/market-context/SKILL.md` | `sonnet` | 3 |
| B, travaux | `${CLAUDE_PLUGIN_ROOT}/skills/renovation-estimator/SKILL.md` | `sonnet` | 4 |
| C, potentiel | `${CLAUDE_PLUGIN_ROOT}/skills/value-add-analyzer/SKILL.md` | `opus` | 5 |

Le modèle se nomme à chaque lancement : `sonnet` pour une tâche cadrée (relevés, chiffrage poste par
poste), `opus` pour le raisonnement réglementaire et le jugement sur les leviers. Dans le prompt, écrire le
chemin du SKILL.md en clair (la variable `${CLAUDE_PLUGIN_ROOT}` remplacée par sa valeur).

## Bloc commun, en tête de chaque prompt

Le remplir à partir de `immo-data/profil.json` **lu le jour de l'étude**. Recopier le texte et la valeur
des décisions qui touchent ce sous-agent, avec leur date : c'est la seule copie permise, elle vit dans le
prompt, pas dans un fichier de l'étude.

```
## Décisions en vigueur (immo-data/profil.json, lu le <AAAA-MM-JJ>)
<texte et valeur des décisions qui touchent ce sous-agent, avec leur date>

Règles tirées de ces décisions, sauf exception écrite dans profil.json pour ce bien :
- division (`division`) : <si faux> aucune division ni création de logement par division (une maison se
  loue entière ; un bien déjà divisé s'étudie entier ET par parties) ;
- montage (`montage_reference`) : <valeur> ; les autres montages sont des lignes de comparaison, jamais
  recommandés ;
- comptabilité de la SCI (`comptabilite_sci_dans_cash_flow`) : <si faux> 0 dans le cash-flow du bien ;
- vacance : celle de profil.json (`vacance_realiste`), pas une autre ;
- meublé (`meuble_logements_2_pieces_ou_moins`) : <si vrai> pour un logement de 2 pièces ou moins, un
  scénario meublé est étudié, en plus du nu.

## Cadre
- Lis <chemin du SKILL.md> (et ses references/) ; applique-le pour ton étape seulement, sans suivre ses
  relais vers l'étape suivante.
- Fiche d'annonce : <immo-data/bruts/<slug>.json> ; fiche de données ouvertes :
  <immo-data/bruts/<slug>-opendata-….json>. Ne relance pas le script de la fiche.
- Écris ta section AU FIL DE L'EAU dans <scratchpad>/<slug>-etape<N>.md : un premier jet dès que
  possible, puis des compléments. Chaque chiffre a sa source et sa date.
- Aucun scraping ; aucune action sur un compte connecté (lecture seule au navigateur).
- Rends au plus 15 lignes, puis, à part :
  « Hors décision : 3 lignes au plus » (ce que tu as vu hors des décisions ci-dessus, sans le chiffrer).
```

## A, marché

```
<bloc commun>
## Tâche
Étape 3 de /immo pour <slug> : loyer réaliste HC et €/m² de vente face au marché.
- Zone : vérifie que le département (DMTO) et la commune (zone locative) du bien figurent dans
  params.json ou immo-data/params_local.json ; sinon, suis market-context pour les chercher à la
  source officielle et les écrire, datés et sourcés. Aucune valeur inventée.
- Loyer : suis market-context §« Relevé de loyers » (annonces de location relues en entier,
  paliers et charges compris, date). Logement de 2 pièces ou moins et meublé au profil : relevé
  meublé aussi.
- Comparables DVF : pris dans la fiche (dvf.comparables, dvf.par_type, dvf.atypiques), même état
  que le bien si possible ; un comparable atypique se signale.
- Rends : loyer réaliste HC (et meublé le cas échéant), €/m², décote, intervalle ANIL, valeur DVF de
  biens comparables du même état (€/m², n, dates), et ce qui a été ajouté aux paramètres de zone.
```

## B, travaux

```
<bloc commun>
## Tâche
Étape 4 de /immo pour <slug> : programme de référence pour la classe DPE visée <classe>.
- Programme (décent, louable, classe visée), options et aléas selon le skill, poste par poste avec
  la grille, bornes basse et haute TTC sans marge ; classe de chantier en cadrage.
- Un audit énergétique ou un DPE projeté du vendeur prime sur ton modèle : reprends ses parcours
  (travaux, coûts TTC, classes, facteur électrique), garde ton modèle pour ce qu'il ne couvre pas,
  dis l'écart. La PAC n'entre au programme que si l'audit ou le DPE projeté l'exige.
- Rends, séparément : le programme (bornes basse et haute, classe visée démontrée ou non), les
  options (bornes, gain de classe ou « gain non chiffré »), les aléas (taux, montants), « À lever en
  visite », la classe de chantier, ce que l'audit couvre ou non. Le budget supportable se remplit à
  l'étape 6, pas ici.
```

## C, potentiel (mode profil)

```
<bloc commun>
## Tâche
Étape 5 de /immo pour <slug>, en MODE PROFIL : les leviers coupés par une décision du profil (division,
création de logements si `division` est faux) tiennent en une ligne, sauf exception de profil.json pour
ce bien. Ne développe que les leviers restants :
- sortie de passoire (classe visée, gain de loyer ou de louabilité) ;
- meublé (logements de 2 pièces ou moins, si le profil le demande) ;
- local commercial (usage, bail, linéaire commercial du PLU) ;
- loyers (écart au marché, sous-location, annexes louables).
Réglementaire à lire pour ces leviers : zone du PLU, prescriptions, servitudes (ABF), PPRI. Bloc
`urbanisme` de la fiche quand il existe ; sinon, méthode : API Carto GPU de l'IGN, sans clé
(`https://apicarto.ign.fr/api/gpu/zone-urba`,
`prescription-lin`, `prescription-surf`, `assiette-sup-s`, point de la fiche), puis le règlement écrit
sur le Géoportail de l'urbanisme, pages citées.
Si les sections de A et B existent déjà dans le scratchpad, intègre-les ; sinon, n'attends pas.
- Rends : leviers activables, leur effet chiffré ou « non chiffré », la règle qui les permet ou les
  bloque (source et date).
```

## Pendant que les sous-agents tournent

- **Ne pas attendre** : continuer moteur, montages, négociation et livrable avec la section concernée
  marquée « en cours » (en-tête et corps), l'optimiste au réaliste tant qu'aucun levier n'est validé.
- Un sous-agent notifié « stalled » ou « failed » : **lire d'abord son fichier
  `<scratchpad>/<slug>-etape<N>.md`** ; s'il est complet, l'utiliser ; sinon relancer pour la partie
  manquante seulement.
- Au retour : « Vérifier avant d'utiliser » (SKILL.md), intégrer, relancer le moteur si une entrée
  bouge, mettre l'en-tête à jour.
