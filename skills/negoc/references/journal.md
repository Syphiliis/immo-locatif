# Journal des négociations (référence du skill /negoc)

Chaque négociation menée avec `/negoc` laisse un **journal JSON** contrôlé par script : coups datés, repères
(ouverture, cible, limite), issue et leçons, sans nom de tiers. Un bilan chiffré par terrain sort de ces journaux
pour calibrer les négociations suivantes. Tout passe par `engine/scripts/negoc_journal.py` (bibliothèque standard
seule) ; le skill n'écrit jamais le JSON à la main, à deux exceptions près : `issue.retex_integre` et la révision
d'un repère (voir la section Commandes, après `clore`).

Les commandes s'écrivent `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" <commande> ...` ; ci-dessous, pour la lecture, `negoc_journal.py <commande> ...`. Les
exemples ont été exécutés dans un répertoire de travail temporaire, avec des données fictives.

## Où vit un journal

Un journal est le fichier `immo-data/negociations/<slug>.json`, UTF-8, un seul objet JSON, écrit par
`json.dumps(obj, ensure_ascii=False, indent=2) + "\n"` en écriture atomique (fichier temporaire dans le même
dossier, puis `os.replace`).

- Le dossier de données est `immo-data/` du **répertoire courant**, ou celui que désigne la variable
  `IMMO_DATA_DIR` ; l'option `--donnees DIR` les remplace (essais, tests). Les journaux vivent dans son
  sous-dossier `negociations/`, créé par `nouveau` au premier journal.
- `--fichier CHEMIN` accepte un chemin absolu ou relatif **au répertoire courant** ; le fichier doit vivre dans
  `<donnees>/negociations/`, sinon c'est une erreur d'usage (code 2). Le chemin rendu par
  `RESULT=NEGOC_JOURNAL_ECRIT <chemin>` se rejoue tel quel dans la commande suivante.

## Schéma

Version `negoc-journal/1`. Le schéma est **strict** : toute clé absente ou inconnue, à tous les niveaux, est un
ÉCHEC de `check`.

| clé | type | règle |
|---|---|---|
| `schema` | texte | `negoc-journal/1` |
| `slug` | texte | `^[a-z0-9][a-z0-9-]{2,80}$`, égal au nom du fichier sans `.json` |
| `terrain` | enum | `immo_achat`, `artisan` |
| `objet` | texte | 1 à 120 caractères |
| `notre_role` | enum | `acheteur` (achat immobilier), `client` (devis d'artisan) |
| `contrepartie.type` | enum | `particulier`, `agence`, `entreprise`, `artisan`, `autre` |
| `contrepartie.intermediaire` | texte ou null | 120 caractères au plus ; un **rôle** (« agence, mandat exclusif »), jamais un nom |
| `contrepartie.signaux` | liste d'enum, sans doublon | `annonce_ancienne`, `baisse_de_prix`, `bien_vide`, `succession`, `vente_contrainte`, `mutation`, `separation`, `double_charge`, `multi_agences`, `mandat_exclusif`, `travaux_lourds`, `dpe_f_g`, `zone_inondable`, `concurrence_annoncee`, `delai_impose`, `autre` |
| `devise` | texte | `EUR` |
| `reperes.prix_affiche`, `.ouverture`, `.cible`, `.limite` | nombre ≥ 0 ou null | `limite` = prix de rupture (walk-away) |
| `reperes.unite` | enum | `eur`, `eur_ht`, `eur_ttc` |
| `reperes.source` | texte ou null | 200 caractères au plus : chemin et section qui fixent les paliers |
| `batna` | texte ou null | 280 caractères au plus |
| `coups` | liste d'objets | peut être vide |
| `issue` | objet | `statut`, `date`, `montant_final`, `conditions_finales`, `lecons`, `retex_integre` |

Un **coup** porte exactement :

| clé | type | règle |
|---|---|---|
| `n` | entier | de 1 à N, sans trou |
| `date` | texte | `AAAA-MM-JJ` ; dates non décroissantes d'un coup au suivant |
| `de` | enum | `nous`, `eux` |
| `canal` | enum | `ecrit`, `telephone`, `visite`, `rendez_vous`, `plateforme` |
| `type` | enum | `offre`, `contre_offre`, `concession`, `demande`, `information`, `question`, `refus`, `acceptation`, `relance`, `ultimatum`, `retrait`, `silence` |
| `montant` | nombre ≥ 0 ou null | |
| `conditions` | liste de textes | 120 caractères au plus chacun |
| `leviers` | liste sans doublon | motif `^[a-z0-9_]{1,40}$` |
| `tactiques` | liste d'enum, sans doublon | `ancrage_precis`, `ancrage_rond`, `fourchette`, `offres_multiples`, `justification_contrainte`, `justification_pieces`, `justification_marche`, `cadrage_pertes`, `question_ouverte`, `question_presupposee`, `fiche_jointe`, `silence`, `date_limite`, `concession_contre_contrepartie`, `concession_seche`, `alternative_reelle`, `recadrage_legal`, `prise_de_contact`, `etiquetage`, `autre` |
| `resume` | texte | 1 à 280 caractères |
| `source` | texte ou null | 200 caractères au plus |

L'**issue** : `statut` (`en_cours`, `conclu`, `rompu_par_nous`, `rompu_par_eux`, `perdu`, `abandonne`), `date`
(`AAAA-MM-JJ` ou null), `montant_final` (nombre ≥ 0 ou null), `conditions_finales` (textes de 120 caractères au
plus), `lecons` (textes de 280 caractères au plus), `retex_integre` (booléen). Règles : `en_cours` impose `date` et
`montant_final` null et `retex_integre` faux ; `conclu` impose une `date` et un `montant_final` ; tout autre statut
impose une `date` ; la `date` de l'issue ne précède pas le dernier coup ; `retex_integre` vrai impose un statut clos
et des `lecons`.

**Sens.** Sur les deux terrains on achète : le sens est `baisse` (on veut moins), pour `acheteur` comme pour
`client`. `ouverture` et `cible` ne passent pas au-dessus de la `limite`.

Journal produit par les commandes ci-dessous (deux coups sur six montrés) :

```json
{
  "schema": "negoc-journal/1",
  "slug": "exemple-maison-de-ville",
  "terrain": "immo_achat",
  "objet": "Maison de ville fictive, exemple de la référence",
  "notre_role": "acheteur",
  "contrepartie": {
    "type": "agence",
    "intermediaire": "agence, mandat exclusif",
    "signaux": ["annonce_ancienne", "baisse_de_prix"]
  },
  "devise": "EUR",
  "reperes": {
    "prix_affiche": 200000, "ouverture": 160000, "cible": 175000, "limite": 185000,
    "unite": "eur", "source": "exemple fictif, section Paliers"
  },
  "batna": "autre bien visité, même secteur",
  "coups": [
    {"n": 1, "date": "2026-01-05", "de": "nous", "canal": "ecrit", "type": "offre", "montant": 160000,
     "conditions": [], "leviers": ["travaux"], "tactiques": ["justification_pieces", "fiche_jointe"],
     "resume": "Première offre avec la fiche de travaux jointe.", "source": null},
    {"n": 2, "date": "2026-01-08", "de": "eux", "canal": "telephone", "type": "contre_offre", "montant": 190000,
     "conditions": [], "leviers": [], "tactiques": [],
     "resume": "Contre-proposition de l'agence, sans justification.", "source": null}
  ],
  "issue": {
    "statut": "conclu", "date": "2026-01-20", "montant_final": 172000,
    "conditions_finales": ["signature à date convenue"],
    "lecons": ["La pièce jointe du premier coup a cadré la discussion."],
    "retex_integre": false
  }
}
```

(Le fichier réel est écrit en `indent=2` sur toutes les lignes ; la mise en forme ci-dessus est condensée.)

## Commandes

Codes de sortie, pour toutes les commandes : **0** ; **1** (ÉCHEC de `check`, ou refus d'écriture) ; **2** (usage,
fichier introuvable ou hors du dossier des journaux, erreur d'entrée-sortie). Un refus n'écrit **rien** et se termine
par `RESULT=NEGOC_JOURNAL_REFUS(<raison courte>)`. Les enums des options ne sont pas filtrés par la ligne de
commande : une valeur hors enum est un refus (code 1) qui nomme la clé fautive. Seule exception : `bilan --terrain`,
où une valeur inconnue est une erreur d'usage (code 2).

**`nouveau`** : crée le journal (`coups` vide, issue `en_cours`).

```
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" nouveau --slug S --terrain T --role R --objet "..."
    [--contrepartie TYPE] [--intermediaire "..."] [--signal SIG]... [--prix-affiche X] [--ouverture X]
    [--cible X] [--limite X] [--unite U (défaut eur)] [--source-reperes "..."] [--batna "..."] [--donnees DIR]
```

```
$ negoc_journal.py nouveau --slug exemple-maison-de-ville --terrain immo_achat --role acheteur --objet "Maison de ville fictive, exemple de la référence" --contrepartie agence --intermediaire "agence, mandat exclusif" --signal annonce_ancienne --signal baisse_de_prix --prix-affiche 200000 --ouverture 160000 --cible 175000 --limite 185000 --source-reperes "exemple fictif, section Paliers" --batna "autre bien visité, même secteur"
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-maison-de-ville.json
(rc=0)
```

Refus : fichier existant ; journal résultant qui ne passe pas `check` (terrain, rôle ou slug invalide, donnée
personnelle...).

**`coup`** : ajoute le coup `n = N + 1` (`--date` : aujourd'hui par défaut).

```
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" coup --fichier CHEMIN --de nous|eux --type TYPE --canal CANAL --resume "..."
    [--date AAAA-MM-JJ] [--montant X] [--condition "..."]... [--levier L]... [--tactique T]... [--source "..."]
    [--donnees DIR]
```

```
$ negoc_journal.py coup --fichier immo-data/negociations/exemple-maison-de-ville.json --de nous --type offre --canal ecrit --resume "Première offre avec la fiche de travaux jointe." --date 2026-01-05 --montant 160000 --tactique justification_pieces --tactique fiche_jointe --levier travaux
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-maison-de-ville.json
(rc=0)
```

Refus : journal clos ; date antérieure au dernier coup ; journal existant déjà invalide ; journal résultant qui ne
passe pas `check`.

```
$ negoc_journal.py coup --fichier immo-data/negociations/exemple-maison-de-ville.json --de nous --type relance --canal ecrit --resume "Relance après clôture."
RESULT=NEGOC_JOURNAL_REFUS(journal clos)
(rc=1)
```

Une **NOTE** s'affiche, code 0, quand un coup `de = nous` passe au-dessus de la `limite` : la décision de dépasser
la limite est permise, mais elle doit être **tracée** (résumé du coup, leçon). Seules les NOTES nouvelles de ce
coup sont affichées.

```
$ negoc_journal.py coup --fichier immo-data/negociations/exemple-note-limite.json --de nous --type offre --canal ecrit --resume "Offre au-dessus de la limite fixée." --date 2026-02-01 --montant 190000
NOTE immo-data/negociations/exemple-note-limite.json : coup 1 au-delà de la limite : décision à tracer
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-note-limite.json
(rc=0)
```

**`clore`** : pose l'issue (statut autre que `en_cours` ; `--date` : aujourd'hui par défaut).

```
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" clore --fichier CHEMIN --statut S [--date AAAA-MM-JJ] [--montant-final X]
    [--condition-finale "..."]... [--lecon "..."]... [--donnees DIR]
```

```
$ negoc_journal.py clore --fichier immo-data/negociations/exemple-maison-de-ville.json --statut conclu --date 2026-01-20 --montant-final 172000 --condition-finale "signature à date convenue" --lecon "La pièce jointe du premier coup a cadré la discussion."
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-maison-de-ville.json
(rc=0)
```

Refus : journal déjà clos ; `conclu` sans `--montant-final` ; date antérieure au dernier coup ; statut `en_cours`.

```
$ negoc_journal.py clore --fichier immo-data/negociations/exemple-donnee-perso.json --statut conclu
RESULT=NEGOC_JOURNAL_REFUS(conclu sans --montant-final)
(rc=1)
```

`retex_integre` reste **faux** après `clore`. C'est le skill qui le passe à `true` quand la leçon est versée dans
`references/retex.md` : il édite le JSON (première des deux modifications manuelles admises), puis relance `check`.
Exemple exécuté plus bas, après la révision d'un repère.

**Réviser un repère.** Aucune commande ne modifie les repères après `nouveau`, et la révision n'est pas un coup.
Quand un repère change (devis concurrent, information nouvelle, décision de l'investisseur), le skill :

1. édite dans le JSON la clé voulue de `reperes` (`prix_affiche`, `ouverture`, `cible` ou `limite`) ;
2. ajoute à `reperes.source` la date et le motif de la révision, **200 caractères au plus en tout** (la valeur
   entière, ancien texte compris) ;
3. relance `check --fichier`.

**Pas de coup** : un coup trace un échange avec l'autre partie, et il fausserait `coups_jusqu_accord` du bilan.
Journal fictif `artisan`, en `eur_ttc` ; `limite` passe de 8 800 à 9 200 (`diff` avant / après l'édition) :

```
$ negoc_journal.py nouveau --slug exemple-devis --terrain artisan --role client --objet "Devis fictif de chauffage, exemple de la référence" --contrepartie artisan --unite eur_ttc --ouverture 7400 --cible 8100 --limite 8800 --source-reperes "exemple fictif, section Paliers"
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-devis.json
(rc=0)

$ diff avant.json apres.json
17c17
<     "limite": 8800,
---
>     "limite": 9200,
19c19
<     "source": "exemple fictif, section Paliers"
---
>     "source": "exemple fictif, section Paliers ; révisé le 2026-10-11 : limite relevée après un second devis"

$ negoc_journal.py check --fichier immo-data/negociations/exemple-devis.json
OK immo-data/negociations/exemple-devis.json
RESULT=NEGOC_JOURNAL_OK
(rc=0)
```

`check` refuse une révision mal faite : repère du mauvais côté de la limite, source de plus de 200 caractères.
Ici `limite` est éditée à 8 000, sous la cible 8 100 :

```
$ negoc_journal.py check --fichier immo-data/negociations/exemple-devis.json
ÉCHEC immo-data/negociations/exemple-devis.json : reperes.cible : 8100 au-delà de reperes.limite 8000 (sens baisse)
RESULT=NEGOC_JOURNAL_FAIL(1 en échec)
(rc=1)
```

**Passer `retex_integre` à vrai.** Seulement quand la leçon a été validée par l'investisseur et versée dans
`references/retex.md`. Le journal doit être clos (`clore`) avec au moins un `--lecon` : `check` refuse
`retex_integre` à vrai sans leçon (`vrai exige des leçons`) et tant que le statut est `en_cours`. Sur le même
journal fictif, encore `en_cours`, `retex_integre` édité à `true` :

```
$ negoc_journal.py check --fichier immo-data/negociations/exemple-devis.json
ÉCHEC immo-data/negociations/exemple-devis.json : issue.retex_integre : doit être faux tant que le statut est en_cours
RESULT=NEGOC_JOURNAL_FAIL(1 en échec)
(rc=1)
```

Journal clos avec une leçon, puis `retex_integre` édité de `false` à `true` :

```
$ negoc_journal.py clore --fichier immo-data/negociations/exemple-devis.json --statut abandonne --date 2026-10-11 --lecon "Un second devis chiffré a pesé plus que la remise demandée."
RESULT=NEGOC_JOURNAL_ECRIT immo-data/negociations/exemple-devis.json
(rc=0)

$ grep -n retex_integre immo-data/negociations/exemple-devis.json
31:    "retex_integre": false

$ grep -n retex_integre immo-data/negociations/exemple-devis.json   # après l'édition
31:    "retex_integre": true

$ negoc_journal.py check --fichier immo-data/negociations/exemple-devis.json
OK immo-data/negociations/exemple-devis.json
RESULT=NEGOC_JOURNAL_OK
(rc=0)
```

**`check`** : lecture seule. Lit `--fichier`, ou tous les `*.json` de `<donnees>/negociations/`. Une ligne par
motif : `ÉCHEC <chemin> : <motif>`, `NOTE <chemin> : <motif>` ; un journal sans ÉCHEC ni NOTE donne `OK <chemin>`.
Dernière ligne : `RESULT=NEGOC_JOURNAL_OK` ou `RESULT=NEGOC_JOURNAL_FAIL(<n> en échec)` (n = nombre de journaux).
Code 2 si `--fichier` est introuvable ou hors du dossier des journaux.

```
$ negoc_journal.py check
OK immo-data/negociations/exemple-maison-de-ville.json
RESULT=NEGOC_JOURNAL_OK
(rc=0)
```

Sans journal : `aucun journal trouvé (dossier lu : <donnees>/negociations)` puis `RESULT=NEGOC_JOURNAL_OK`. Les six
contrôles : (1) JSON lisible, schéma, clés manquantes ou inconnues, types, enums, longueurs, motifs, doublons ;
(2) `slug` = nom du fichier ; (3) coups numérotés de 1 à N, dates ISO non décroissantes ; (4) repères du bon côté
de la limite (NOTE pour un coup au-delà) ; (5) cohérence de l'issue ; (6) données personnelles dans les valeurs
texte (voir la section Confidentialité).

**`bilan`** : lecture seule. Lit les journaux qui passent `check` ; les autres sont listés
`ignoré (check en échec) : <chemin>`. Options : `--terrain T`, `--detail` (une ligne par journal), `--json`.
Dernière ligne `RESULT=NEGOC_BILAN_OK` (code 2 en cas d'erreur d'entrée-sortie). Avec `--json`, la sortie standard
est un JSON pur et la ligne `RESULT=` passe sur la sortie d'erreur (avec `2>&1`, elle reste la dernière ligne).

```
$ negoc_journal.py bilan
Bilan des négociations au 2026-10-14 : 1 journal lu

== immo_achat / baisse : 1 journal ==
statuts : conclu 1
première offre / affiché : médiane -20,0 % (n 1)
sur les journaux conclus :
  final / affiché : médiane -14,0 % (n 1)
  final / ouverture : médiane +7,5 % (n 1)
  final / cible : médiane -1,7 % (n 1)
  dans la cible : 1 sur 1
  coups jusqu'à l'accord : médiane 6 (n 1)
  jours jusqu'à l'accord : médiane 15 (n 1)
tactiques jouées par nous (journaux conclus / clos sans accord) :
  concession_contre_contrepartie : 1 / 0
  date_limite : 1 / 0
  fiche_jointe : 1 / 0
  justification_pieces : 1 / 0
⚠ moins de 5 négociations conclues : descriptif, aucune conclusion
RESULT=NEGOC_BILAN_OK
(rc=0)
```

Sans journal : `aucun journal` puis `RESULT=NEGOC_BILAN_OK`.

## Confidentialité

Un journal peut être relu par une session future, copié ou partagé : il ne contient que ce qui peut circuler.

- **Des rôles, jamais des noms.** Les tiers sont « la vendeuse », « l'agence », « l'artisan ».
  `contrepartie.intermediaire` porte un rôle (« agence, mandat exclusif »), `resume` et `conditions` disent « la
  vendeuse a répondu », pas son nom. Ni adresse précise de tiers, ni courriel, ni téléphone, ni IBAN.
- **Des signaux, jamais de détails sur la personne.** `contrepartie.signaux` prend des valeurs d'une liste fermée
  (`succession`, `separation`, `mutation`, `double_charge`…) : on y range la situation du dossier, jamais l'état de
  santé, l'âge ou le détail de la situation familiale d'un tiers. Si le signal ne tient pas dans la liste, `autre`,
  sans le développer dans un texte libre.
- **Aucun revenu, impôt ou solde du foyer dans un journal.** Un repère de négociation (ouverture, cible, limite)
  est un prix de transaction, pas un chiffre du foyer ; la capacité d'emprunt, le TMI, l'épargne ou la mensualité
  qui les ont fixés restent dans leur source (`immo-data/foyer.json`, l'étude `/immo`) : y renvoyer via
  `reperes.source`, sans les recopier.
- **Ce que `check` détecte, et ce qu'il ne détecte pas.** Il cherche dans toutes les valeurs texte (pas dans les
  clés) un courriel, un téléphone français, un IBAN et une civilité suivie d'un nom : `donnée personnelle probable
  (courriel) dans coups[0].resume`. Ce sont des motifs, pas une garantie :
  - un **IBAN** est reconnu en majuscules ou en minuscules, écrit avec des espaces (`FR14 2004 …`), des tirets
    (`FR14-2004-…`) ou collé (`FR1420…`) ;
  - un **téléphone** est reconnu quand il n'est collé à aucun autre chiffre, ni avant ni après : un numéro de dossier
    ou de référence plus long que dix chiffres d'affilée ne passe donc pas pour un téléphone (dix chiffres d'affilée
    qui commencent par `0` restent pris pour un téléphone) ;
  - une **civilité suivie d'une majuscule** est prise pour un nom, y compris « Madame Le Gall », qui est un nom réel
    et reste refusé : **une fonction s'écrit en minuscules** (« madame la présidente » passe, « Madame La
    Présidente » est refusé) ;
  - un nom de personne sans civilité n'est pas vu.

  Il ne remplace pas la relecture de ce qu'on écrit.

```
$ negoc_journal.py coup --fichier immo-data/negociations/exemple-donnee-perso.json --de eux --type information --canal ecrit --resume "Contact : contact@exemple.fr"
ÉCHEC immo-data/negociations/exemple-donnee-perso.json : donnée personnelle probable (courriel) dans coups[0].resume
RESULT=NEGOC_JOURNAL_REFUS(donnée personnelle probable (courriel) dans coups[0].resume)
(rc=1)
```

## Bilan et calibration

`bilan` regroupe les journaux valides par (`terrain`, `sens`) et sort, par groupe :

- `n` et le compte par `statut` ;
- `premiere_offre_vs_affiche` : pour les journaux dont le `prix_affiche` est > 0, `montant / prix_affiche - 1` de
  **notre première offre ou contre-offre chiffrée** ;
- sur les seuls journaux `conclu` : `final_vs_affiche`, `final_vs_ouverture`, `final_vs_cible` (chacun seulement si
  le repère est > 0), `dans_cible` (en `baisse`, `montant_final ≤ cible` ; en `hausse`, `≥`), `coups_jusqu_accord`
  et `jours_jusqu_accord` (date de l'issue moins date du premier coup) ;
- les **tactiques** jouées par nous (au moins un coup `de = nous`), comptées une fois par journal, séparées entre
  journaux `conclu` et journaux clos sans accord (`rompu_par_nous`, `rompu_par_eux`, `perdu`, `abandonne`) ; les
  journaux `en_cours` n'y comptent pas.

**Lire un bilan.**

- Chaque mesure est une **médiane** accompagnée de son **`n`** : la médiane de 2 valeurs n'a pas le poids de celle
  de 30, et `n` peut être inférieur au nombre de journaux (un repère absent ou nul exclut le journal de la mesure).
  Une mesure sans valeur affiche `n.d.`.
- Un pourcentage est signé, à une décimale, avec une virgule décimale : `-11,0 %` (en `baisse`, on a payé 11 % de
  moins que l'affiché), `+7,9 %` (le final est 7,9 % au-dessus de notre ouverture), `+0,3 %`.
- Sous **5 journaux conclus** dans le groupe, la ligne `⚠ moins de 5 négociations conclues : descriptif, aucune
  conclusion` s'affiche (clé `avertissement` en JSON). **Un bilan décrit, il ne prouve pas** : à ce stade il dit ce
  qui s'est passé dans nos propres négociations, il ne dit pas ce qui marche. Ne pas en tirer de règle, ne pas
  l'opposer à un repère sourcé.
- Les tactiques ne se lisent pas comme des causes : une tactique jouée par des journaux tous conclus peut être
  jouée dans des cas faciles. Le compte `conclu / clos sans accord` dit seulement où elle a été essayée.
- Les groupes sont indépendants : `immo_achat / baisse` et `artisan / baisse` ne se comparent pas.

Pour **calibrer** la négociation suivante : lire le groupe du terrain (`bilan --terrain T`), comparer ses médianes
aux repères que l'on s'apprête à fixer, et ne laisser entrer une leçon dans `references/retex.md` qu'après
validation de l'investisseur (puis passer `retex_integre` à `true` et relancer `check`). `--detail` donne la ligne de chaque
journal pour vérifier d'où vient une médiane ; `--json` sert à un traitement par script.
