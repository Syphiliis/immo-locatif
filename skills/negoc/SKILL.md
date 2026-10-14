---
name: negoc
description: Négocie sur deux terrains, l'achat d'un bien immobilier à louer et les devis d'artisans - situation, ouverture, cible et limite, leviers sourcés, objections, concessions, brouillons de messages, journal qui apprend. À déclencher sur « combien offrir », « que répondre à l'agent », « que répondre au vendeur », « il me fait une contre-proposition », « négocier un devis d'artisan ». Étape 8 de /immo pour un bien étudié (paliers lus dans le moteur, jamais recalculés). Ne calcule pas la rentabilité (c'est /immo, dont le moteur donne les paliers de prix), ne rédige pas d'acte (notaire), n'envoie jamais un message.
argument-hint: "<situation> | immo <slug> | reponse <slug> <message reçu> | point <slug> | bilan <slug> | retex"
---

# /negoc : négocier avec une méthode sourcée et un journal qui apprend

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

`/negoc` prépare une négociation, rédige les brouillons et tient le journal. Il ne décide pas à la
place de l'investisseur, ne calcule pas la rentabilité d'un bien (moteur du plugin via `/immo`) et
n'envoie rien : chaque message est un brouillon que l'investisseur valide et envoie lui-même. Les règles
viennent du socle vérifié (`references/socle.md`, `references/droit.md`), des leçons passées
(`references/retex.md`) et des décisions de l'investisseur (`immo-data/profil.json`) ; chacune porte sa
source.

Chemins : `references/...` est relatif à ce skill ; `skills/...` et `engine/...` sont relatifs à
`${CLAUDE_PLUGIN_ROOT}` ; `immo-data/...` est le dossier de données de l'utilisateur (répertoire courant,
ou `IMMO_DATA_DIR`).

## Quand l'utiliser

- Une offre d'achat à faire ou à recevoir : « combien offrir ? », « à quel prix ouvrir ? », « que
  répondre à l'agent ? », « le vendeur fait une contre-proposition », « prépare mon appel ».
- Un devis d'artisan ou d'entreprise à discuter : prix, contenu, TVA, acompte, délais.
- L'étape 8 de `/immo` (négociation d'un bien étudié) : les paliers viennent du moteur.
- Le point sur une négociation en cours, son bilan, ou les leçons de toutes les négociations.

Ne couvre pas : la rentabilité (`/immo`), un acte juridique (notaire, avocat), l'envoi d'un message,
toute autre négociation (crédit, contrat, cession d'entreprise, bail).

## Modes

| Mode | Ce qu'il fait |
|---|---|
| `/negoc <situation>` | Méthode complète sur une situation décrite : terrain, position, leviers, paliers, plan de concessions, objections, séquence, brouillons, commandes du journal. |
| `/negoc immo <slug>` | Terrain achat immobilier sur un bien étudié par `/immo` : paliers lus dans l'étude et la sortie du moteur (`references/immo_achat.md` §Paliers), section Négociation de l'étude (§Sortie dans l'étude). |
| `/negoc reponse <slug> <message reçu>` | Lecture d'une contre-proposition (`references/concessions.md` §Lire une contre-proposition), décision, brouillon de réponse, coups `eux` puis `nous` au journal. |
| `/negoc point <slug>` | État d'une négociation : journal relu (`check --fichier`), écart à la limite, prochain coup. |
| `/negoc bilan <slug>` | Clôture : `clore`, bilan du terrain, leçon proposée à l'investisseur (`references/retex.md`). |
| `/negoc retex` | Bilan des deux terrains (`bilan --detail`), leçons à proposer, entrées de `retex.md` à écrire après validation. |

## La méthode

Les temps, dans l'ordre. Chacun renvoie à la référence qui porte ses règles.

1. **Situer** : le terrain (§Terrains), notre rôle (acheteur ou client), le journal existant
   (`check --fichier`, ou `nouveau` s'il n'existe pas), le bilan du terrain (`bilan --terrain <terrain>`,
   §Journal et apprentissage) et les leçons du terrain (`references/retex.md` §Leçons de départ et §Leçons ajoutées, puis la section
   « Leçons des négociations passées » du fichier du terrain).
2. **Cadrer** : l'objet exact, ce qui s'exige (droit, non négociable) et ce qui se négocie (fichier du
   terrain, §Ce qui s'exige et ce qui se négocie) ; les pièces à obtenir avant tout chiffre. Une liste du
   fichier du terrain (ce qui s'exige, ce qui se négocie, questions de l'appel) se reprend **en entier**,
   un point par ligne, même pour en écarter un en disant pourquoi ; elle ne se résume pas.
3. **Sa position** : la valeur établie sans le prix affiché (`references/socle.md` §Préparer, règle
   1) ; quatre nombres arrêtés avant tout échange, ouverture, cible, limite et seuil de rupture (règle
   2), lus dans les outils du plugin (moteur via `/immo`, devis, grilles datées de
   `renovation-estimator`), jamais inventés ; l'alternative réelle (règle 6). Les chiffres du foyer se
   lisent dans `immo-data/foyer.json` et ne se recopient pas.
4. **L'autre partie** : point de référence, dette, échéances, fiscalité, motivation, intérêts hors
   prix, incitations de l'intermédiaire (`references/socle.md` règles 3 à 5) ; prendre sa perspective.
5. **Leviers** : ceux du fichier du terrain, chacun chiffré en euros, sourcé, marqué **citable**
   (pièces de l'autre partie, faits datés) ou **interne** (études, repères, statistiques).
6. **Paliers et plan de concessions** : ouverture ambitieuse mais défendable, précision modérée
   (`references/socle.md` §Ouvrir) ; budget de concessions, pas et contreparties, offres équivalentes
   (`references/concessions.md` §Plan de concessions).
7. **Objections** : les plus probables, avec la réponse (fait, pièce ou question) et ce qu'il ne faut
   pas dire (`references/concessions.md` §Objections, puis §Objections du terrain).
8. **Canal et tempo** : l'oral pour découvrir, l'écrit pour proposer et confirmer ; pauses ; échéance
   commune annoncée si vraie, coûts de temps propres tus (`references/socle.md` §Échanger et concéder ;
   `references/concessions.md` §Délais, silence et dernier mot).
9. **Rédiger** : les brouillons, selon `references/messages.md` §Règles d'écriture et le gabarit du
   terrain ; puis le contrôle `references/messages.md` §Avant envoi sous chaque brouillon. Un document
   engageant ne part pas avec une annexe vide (retex L4).
10. **Journal** : imprimer les commandes `nouveau` et `coup` (§Journal et apprentissage) ; un coup ne
    s'écrit qu'après l'envoi réel par l'investisseur ou l'échange réel.
11. **Après chaque réponse** : `/negoc reponse` ; lire, décider, répondre, noter ; jamais d'acceptation
    dans le même échange.
12. **Clore** : `clore`, bilan, leçon proposée (`references/retex.md` §Comment une leçon entre ici).

Si une donnée manque (pièce, sortie du moteur, repère daté), le dire et dire comment l'obtenir ; ne
jamais la supposer, et poser la question en cas de doute. Un repère de marché daté (marge, décote, délai
de vente) ne devient jamais une valeur par défaut : il se relève, avec sa source et sa date, à chaque
négociation.

## Terrains

| Terrain (`terrain`) | Rôle | Référence | Outils et sources du plugin |
|---|---|---|---|
| Achat immobilier (`immo_achat`) | `acheteur` | `references/immo_achat.md` | `/immo` et le moteur du plugin (`skills/immo/references/negociation_livrable.md` §Paliers), `lbc-scraper`, `market-context`, `renovation-estimator`, `engine/scripts/immo_fiche_opendata.py`, `skills/immo/references/pieces_a_demander.md` |
| Devis d'artisans (`artisan`) | `client` | `references/artisans.md` | `renovation-estimator` et `skills/renovation-estimator/references/` (TVA, aides, grille de coûts datée) |

Une autre négociation (crédit, assurance, contrat, cession, bail) est hors du skill : le dire ; seul
le socle commun (`references/socle.md`, `references/droit.md`, `references/messages.md`,
`references/concessions.md`) peut servir de lecture, sans journal ni terrain.

## Lignes rouges

Droit (`references/droit.md`) et règles de la méthode ; aucune ne se négocie :

- **Aucune affirmation inexacte** : ni offre concurrente, ni devis, ni défaut, ni échéance, ni
  contrainte inventés (C. civ. 1137, D15).
- **Aucune exploitation d'une vulnérabilité** : dettes, deuil, succession, détresse ; vendeur
  vulnérable ou vente conduite par la famille : fiabilité, aucune pression, orientation vers son
  notaire (D16, D17).
- **Aucun versement** joint à une offre d'achat immobilier (D7, D9).
- **Aucune offre ferme qu'on ne signerait pas telle quelle** : une offre précise acceptée peut former
  le contrat (D4, D6, D-J1) ; **pas d'offres fermes simultanées** sur plusieurs biens.
- **Aucun contournement frauduleux d'un agent** (D-J8, D-J9).
- **Aucun envoi par Claude** : brouillons seulement, validés et envoyés par l'investisseur.
- **Aucun nom de tiers ni chiffre du foyer dans un journal ou un fichier partagé** : les tiers par leur
  rôle ; les chiffres du foyer lus dans `immo-data/foyer.json`, jamais recopiés (retex I9).
- **Aucun dépassement de la limite sans décision de l'investisseur tracée au journal**
  (`references/socle.md` règle 24 ; NOTE « au-delà de la limite » de `check`).
- Aucun tiret cadratin dans un message ; aucun argument de loyer, de rendement ni statistique DVF dans
  un message immobilier (retex I1).

## Journal et apprentissage

Un journal par négociation, JSON dans `immo-data/negociations/<slug>.json`, tiers désignés par leur rôle
(schéma et confidentialité : `references/journal.md`). **Quand écrire un coup** : après chaque échange
réel (offre ou message envoyé par l'investisseur, réponse reçue, appel, visite), jamais pour un
brouillon. En mode scénario ou tant que l'investisseur n'a pas envoyé, **imprimer** les commandes au
lieu de les lancer.

Les cinq commandes (lancées depuis le répertoire de travail de l'utilisateur, celui qui contient
`immo-data/`) :

```
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" nouveau --slug S --terrain T --role R --objet "…"
    [--contrepartie TYPE] [--intermediaire "…"] [--signal SIG]… [--prix-affiche X] [--ouverture X]
    [--cible X] [--limite X] [--unite U (défaut eur)] [--source-reperes "…"] [--batna "…"] [--donnees DIR]
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" coup --fichier CHEMIN --de nous|eux --type TYPE
    --canal CANAL --resume "…" [--date AAAA-MM-JJ (défaut : aujourd'hui)] [--montant X] [--condition "…"]…
    [--levier L]… [--tactique T]… [--source "…"] [--donnees DIR]
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" clore --fichier CHEMIN --statut S
    [--date AAAA-MM-JJ] [--montant-final X] [--condition-finale "…"]… [--lecon "…"]… [--donnees DIR]
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" check [--fichier CHEMIN] [--donnees DIR]
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" bilan [--terrain T] [--detail] [--json] [--donnees DIR]
```

`--donnees DIR` remplace le dossier de données (défaut : `IMMO_DATA_DIR`, sinon `./immo-data`).

Valeurs utiles : `--terrain` `immo_achat`, `artisan` ; `--role` `acheteur` (immo_achat), `client`
(artisan) ; `--de` `nous`, `eux` ; `--type` `offre`, `contre_offre`, `concession`, `demande`,
`information`, `question`, `refus`, `acceptation`, `relance`, `ultimatum`, `retrait`, `silence` ;
`--canal` `ecrit`, `telephone`, `visite`, `rendez_vous`, `plateforme` ; `--tactique` notamment
`ancrage_precis`, `justification_contrainte`, `justification_pieces`, `question_presupposee`,
`question_ouverte`, `fiche_jointe`, `silence`, `date_limite`, `concession_contre_contrepartie`,
`offres_multiples`, `alternative_reelle`, `prise_de_contact` (liste complète : `references/journal.md`
§Schéma) ; `--contrepartie` `particulier`, `agence`, `entreprise`, `artisan`, `autre` ; `--signal`
`annonce_ancienne`, `baisse_de_prix`, `bien_vide`, `succession`, `vente_contrainte`, `mutation`,
`separation`, `double_charge`, `multi_agences`, `mandat_exclusif`, `travaux_lourds`, `dpe_f_g`,
`zone_inondable`, `concurrence_annoncee`, `delai_impose`, `autre` (aucune autre valeur : `check` la
refuse). Un montant se note dans l'unité des repères (`--unite` `eur`, `eur_ht` ou `eur_ttc`), le même
côté (FAI ou net) que le prix affiché. Les paliers vont dans `--prix-affiche`, `--ouverture`, `--cible`,
`--limite`, avec `--source-reperes` (chemin et section qui les fixent).

**Boucle d'apprentissage** : bilan → leçon proposée par Claude → validation de l'investisseur → entrée
datée dans `references/retex.md` → `issue.retex_integre` à `true` dans le journal, puis `check`. Une
leçon qui change une règle édite la référence concernée, ligne datée.

## Sortie attendue

Forme courte d'une réponse `/negoc` (pour `/immo`, la section de l'étude :
`references/immo_achat.md` §Sortie dans l'étude) :

1. **Situation** : terrain, rôle, objet, journal (chemin ou « à créer »), ce qui manque ; ce qui s'exige
   et ce qui se négocie, listes du terrain reprises en entier (§La méthode, temps 2).
2. **L'autre partie** : intérêts probables, point de référence, signaux, et échanges hors prix possibles
   (date, mobilier, conditions).
3. **Position et sources** : valeur ; ouverture, cible, limite et seuil de rupture, chacun avec sa
   source (sortie nommée, pièce, repère daté) ; la phrase interne « au-delà de X, pas d'accord » ;
   l'alternative réelle.
4. **Leviers** en tableau : levier, montant en euros, pièce ou repère, **citable** ou **interne**.
5. **Plan de concessions** : budget, pas, contrepartie de chaque pas, offres équivalentes éventuelles.
6. **Objections et réponses** : les trois ou quatre plus probables.
7. **Séquence** : canal, ordre des coups, pauses, échéances.
8. **Brouillons** : message(s) et pièce jointe éventuelle.
9. **À vérifier avant envoi** : le contrôle de `references/messages.md` §Avant envoi, coché ou ouvert.
10. **Commandes du journal**, imprimées.

## Références

- `references/socle.md` : règles sourcées par phase (préparer, ouvrir, échanger et concéder,
  conclure), ce qu'on n'utilise pas, sources complètes.
- `references/droit.md` : loyauté et lignes rouges, offre et acceptation, formule de l'offre, renvois
  par terrain.
- `references/messages.md` : règles d'écriture, gabarits communs, contrôle avant envoi.
- `references/concessions.md` : plan de concessions, lecture d'une contre-proposition, objections,
  délais et dernier mot.
- `references/immo_achat.md` : terrain achat immobilier (8 leviers, paliers, séquence, message et
  fiche travaux, sortie dans l'étude).
- `references/artisans.md` : terrain devis d'artisans et d'entreprises.
- `references/journal.md` : où vit un journal, schéma, commandes, confidentialité, bilan.
- `references/retex.md` : leçons, et comment une leçon nouvelle y entre.
