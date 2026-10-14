# Retex : les leçons des négociations

Les leçons, par terrain, et la façon dont une leçon nouvelle y entre. Une leçon ne recopie pas la
règle : elle **renvoie** à la section où la règle vit. Aucun nom de tiers, aucune adresse, aucun
chiffre du foyer (`SKILL.md` §Lignes rouges).

## Comment une leçon entre ici

1. **Bilan** : à la clôture d'une négociation (`clore`), ou quand l'investisseur corrige un brouillon,
   lancer `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/negoc_journal.py" bilan --terrain <terrain> --detail`
   et relire le journal (`journal.md` §Bilan et calibration).
2. **Proposition** : Claude propose à l'investisseur une leçon en une phrase, avec l'incident qui la
   fonde et la règle qu'elle changerait (fichier et section), ou « aucune ».
3. **Validation de l'investisseur** : rien n'entre sans son accord explicite.
4. **Entrée datée**, une ligne dans le tableau §Leçons ajoutées : date ; terrain (`immo_achat`,
   `artisan`, ou `commun` pour une leçon transverse) ; journal (`immo-data/negociations/<slug>.json`, ou
   « sans journal ») ; situation anonymisée (rôles, jamais de noms) ; la leçon ; la règle modifiée :
   fichier et section, ou « aucune ».
5. **Règle modifiée** : si la leçon change une règle, éditer la référence concernée (ligne datée
   « JJ/MM/AAAA »), dans le périmètre de ce skill ; un fichier d'un autre skill se signale, il ne
   s'édite pas en silence.
6. **Journal** : passer `issue.retex_integre` à `true` dans le JSON (édition directe, l'une des deux
   exceptions prévues ; l'autre est la révision d'un repère, `journal.md` §Commandes), puis
   `check --fichier <chemin>` doit rendre `RESULT=NEGOC_JOURNAL_OK`.

## Leçons de départ

Livrées avec la méthode, tirées de négociations passées et rendues génériques. Préfixe `I` : achat
immobilier ; `A` : artisans ; `L` et `G` : communes aux deux terrains. Les autres fichiers les citent
sous la forme « retex I1 ».

| # | Terrain | Situation (incident) | Leçon | Règle : où elle vit |
|---|---|---|---|---|
| I1 | immo_achat | trois réécritures d'une offre ; argument de loyer retourné par l'agent | message bâti sur les pièces du vendeur, sans loyer, rendement ni statistique DVF ; 2 ou 3 postes dans le message, le détail en fiche jointe | `immo_achat.md` §Messages ; `messages.md` §Règles d'écriture (1, 2) |
| I2 | immo_achat | loyer avancé par l'agent, lu comme acquis | demander le dernier loyer pratiqué, bail à l'appui, sans opposer un autre chiffre | `immo_achat.md` §Séquence, §Objections ; `messages.md` §Règles d'écriture (3) |
| I3 | immo_achat | bien remis en vente peu après son achat, nettement plus cher | levier contraire compté à 0 ; la vente DVF de la même parcelle est le point de référence du vendeur ; bien à travaux : plafond moins travaux | `immo_achat.md` §Leviers (4, 7) |
| I4 | immo_achat | rendement annoncé par l'agence | le recalculer au moteur ; le prix qui le rendrait vrai est un ancrage interne | `immo_achat.md` §Paliers |
| I5 | immo_achat | palier de loyer manqué sur un comparable non relu | relire un comparable à la source, texte entier | `immo_achat.md` §Entrées et outils |
| I6 | immo_achat | modèle DPE contredit par l'audit du vendeur | l'audit prime sur le modèle DPE ; le demander dès E, F ou G | `immo_achat.md` §Leviers (3) |
| I7 | immo_achat | décotes génériques proposées par un praticien | prise de contact orale d'abord ; décotes génériques écartées | `immo_achat.md` §Séquence |
| I8 | immo_achat | les devis du vendeur contredisaient le brouillon | n'affirmer que ce que prouvent les pièces ; une partie du bien se recalcule seule ; un concurrent annoncé reste non étayé sans offre écrite | `immo_achat.md` §Messages, §Objections ; `concessions.md` §Lire une contre-proposition |
| I9 | immo_achat | un nombre du foyer recopié dans un brouillon, rattrapé par le contrôle | brouillon validé par l'investisseur, chiffres repassés au moteur, aucun chiffre du foyer recopié | `SKILL.md` §Lignes rouges ; `messages.md` §Avant envoi |
| A1 | artisan | remise globale ronde jugée trop faible, refaite ligne par ligne | paliers ligne par ligne sur le marché daté plus une marge explicite ; plan B crédible ; pas décroissants contre une contrepartie | `artisans.md` §Leviers, §Paliers |
| A2 | artisan | devis à 20 % de TVA partout | ce qui s'exige ne se négocie pas ; sur un chantier aidé en pourcentage, un euro de remise ne rapporte qu'une fraction | `artisans.md` §Ce qui s'exige, §Leviers |
| A3 | artisan | équipement facturé nettement au-dessus du modèle posé | lignes relues contre catalogue et fiche technique ; RGE exact ; raison sociale lue | `artisans.md` §Entrées et outils, §Objections |
| A4 | artisan | version non signée renvoyée ; changement d'entreprise sur un chantier aidé | accord écrit du référent ; vérifier que le PDF renvoyé est signé | `artisans.md` §Séquence |
| A5 | artisan | mauvais étage chiffré ; promotion expirée | périmètre figé avant le devis ; prix et validités datés ; une remise sans réponse écrite n'est pas acquise | `artisans.md` §Séquence, §Messages |
| A6 | artisan | programme haut réduit d'un tiers | « matériaux seuls » à côté du prix artisan ; poste exigé ou choisi ; une forte baisse sans changement du cahier des charges est une alerte | `artisans.md` §Paliers |
| A7 | artisan | taux de TVA appliqué sans relire le texte | TVA ligne par ligne ; relire les références de `renovation-estimator` avant tout chiffre | `artisans.md` §Entrées et outils, §Ce qui s'exige |
| L1 | commun | souplesse demandée sur un droit déjà acquis | recadrer le statut légal, concéder une nouveauté bornée, verrouiller par défaut | `concessions.md` §Plan de concessions (8) |
| L2 | commun | concession de souplesse abandonnée pour une sortie libre | souplesse personnelle, non cessible, contrepartie consignée | `concessions.md` §Plan de concessions (8) |
| L3 | commun | promesse hors de notre maîtrise | ne rien promettre qui dépend d'un tiers | `messages.md` §Règles d'écriture (8) |
| L4 | commun | document engageant envoyé avec une annexe vide | pièce jointe vérifiée avant envoi | `messages.md` §Avant envoi ; `SKILL.md` §La méthode (rédiger) |
| G1 | commun | message qui force une décision, amorti | option positive prête, option négative courte et neutre, aucun amortisseur | `messages.md` §Règles d'écriture (6), §Gabarits (dernier mot) |
| G2 | commun | affirmation négative non vérifiée | la tenter de réfuter avant l'envoi, sinon « en l'absence de preuve contraire » | `messages.md` §Règles d'écriture (7), §Avant envoi |
| G3 | commun | décision structurante prise sans options chiffrées | deux à quatre options chiffrées, seuils de bascule écrits | `concessions.md` §Plan de concessions (7) |
| G4 | commun | pièce jointe et tiret cadratin non vérifiés | contrôle binaire avant envoi | `messages.md` §Règles d'écriture (9), §Avant envoi |
| G5 | commun | coût récurrent présenté sans spectre d'options | faire soi-même, intermédiaire, tout compris, avec le seuil de rentabilité | `concessions.md` §Plan de concessions (7) |

**Arbitrages entre leçons** : I1 prime sur I4 (le loyer reste interne) ; I7 cède au droit (aucune
pression sur une succession, `droit.md` D16, D17) ; une offre porte toujours une date de validité (I1
contre I8) ; A1 contre A6 et A7 : `artisans.md` §Paliers.

## Leçons ajoutées

| Date | Terrain | Journal | Situation (incident) | Leçon | Règle modifiée |
|---|---|---|---|---|---|
