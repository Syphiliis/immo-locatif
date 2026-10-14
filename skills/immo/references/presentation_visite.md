# Présentation du projet et pense-bête de visite (livrables dérivés, à la demande)

Deux livrables tirés de l'étude, faits seulement quand l'utilisateur les demande. Ils ne portent
**que** des chiffres de l'étude ou d'une sortie nommée du moteur (garde-fou 8 du SKILL.md), et se
régénèrent quand l'étude change (décision, configuration, loyer, travaux, montage).

## Présentation du projet (`.md`, gardée avec l'étude)

- Fichier : `immo-data/analyses/<slug>-projet-<montage>-<classe>.md`, par exemple
  `centre-ville-120k-2026-01-15-projet-sci-is-dpe-e.md` (exemple fictif).
- En-tête : étude source, décisions du profil appliquées (avec leur date), verdict chiffré.
- Sections, avec un sommaire :
  1. En bref : tableau « travaux au plancher / travaux hauts » (travaux, loyer, prêt et mensualité,
     rendements brut et net, cash-flow au prix affiché, plafond, cible), puis 4 à 6 puces.
  2. Le bien.
  3. Ce qui peut être fait.
  4. Travaux par poste.
  5. Loyer.
  6. Charges.
  7. Impôts du montage.
  8. Prêt et rendement selon le prix négocié : prix affiché, -10 %, -20 %, ancrage, plafond, cible.
  9. Négociation.
  10. Ce qui améliore le rendement.
  11. Financement.
  12. À vérifier.
  13. Annexes : `fiscalite.hypotheses` en entier, sources et dates.
- `--verifier` contre chaque sortie citée, `rc=0` (SKILL.md, « Avant la version finale »). Pas de
  tiret cadratin : elle peut être partagée.

## Pense-bête de visite (PDF, privé)

- Fichier : `immo-data/pdfs/visite-<slug court>-<AAAA-MM-JJ>.pdf`, à ne pas partager. Exemple fictif :
  `visite-centre-ville-120k-2026-01-20.pdf`.
- Pages de visite, montrables :
  - but de la visite et ce qu'il faut pour la classe visée ;
  - questions à l'agent (cases à cocher) ;
  - points à vérifier sur place, par partie ou par bâtiment ;
  - « Ce que dit l'annonce, ce qu'on sait » ;
  - le DPE ;
  - les travaux par poste ;
  - des cadres de notes.
- Pages « Pour toi seulement », sous un encadré « À NE PAS MONTRER À L'AGENT » :
  - loyer, charges, taxes et impôts par an ;
  - prêt et rendement selon le prix ;
  - paliers et leviers ;
  - après la visite ;
  - sources.
- Fabrication :
  1. HTML et CSS dans le scratchpad : A4, `@page` avec pied de page et « page X / Y ».
  2. `weasyprint <html> <pdf>` (outil à installer à part ; absent, le dire et livrer le HTML).
  3. Espaces insécables dans les nombres, pour qu'un montant ne se coupe pas en fin de ligne.
- Contrôles :
  - `pdfinfo` pour le nombre de pages ;
  - lecture des pages rendues (Read, paramètre `pages`) ;
  - `pdftotext -layout` pour retrouver les montants clés et vérifier qu'aucun ne se coupe.
- Date de visite en blanc si elle n'est pas connue. Aucune offre ni prix annoncé sur place.

## One-pager (PDF, privé)

- Source `immo-data/analyses/<slug>-one-pager.md`, PDF
  `immo-data/pdfs/one-pager-<slug>-<AAAA-MM-JJ>.pdf`, une page A4, même fabrication.
- Contenu : prix affiché ; prix à viser (cible, cash-flow `S`) selon le budget travaux, une ligne
  par niveau, chacun repassé au moteur (sortie nommée) ; loyers par logement ; travaux par poste ;
  conditions avant offre.
- Aucune donnée du foyer (pas de taux d'effort) ; pas de tiret cadratin.
