---
name: renovation-estimator
description: "Chiffre le programme de travaux de référence d'un bien étudié à l'achat - les seuls postes qui le rendent décent et louable et l'amènent à la classe DPE visée, en bornes basse et haute TTC sans marge - à partir des photos, de la description, du DPE et de l'audit du vendeur ; présente à part les options (équipements, avec leur gain de classe) et les aléas, et classe le chantier en cadrage. À déclencher pour estimer les travaux d'un bien candidat ou confronter un devis reçu pour ce bien ; peut tourner isolé. Ne couvre pas le suivi des travaux, devis et factures de vos propres biens. Étape 4 de `/immo` ; préalables : lbc-scraper (+ market-context si pipeline complet) ; suivant : value-add-analyzer ou yield-calculator."
---

# Renovation Estimator - programme de travaux d'un bien candidat

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Le skill chiffre le **programme de référence** d'un bien étudié à l'achat : les seuls travaux qui le rendent décent
et louable et l'amènent à la classe DPE visée. À part : les **options**, avec leur gain de classe, et les **aléas**,
sur une ligne nommée. `/immo` met le programme face au **budget travaux supportable** (étape 6). Prix :
`references/grille-couts-2026-05.md` (« LMSG » : guide de prix La Maison Saint-Gobain, date de mise à jour
par ligne ; prix moyens nationaux et repères rédigés pour l'Île-de-France en 2026, **à recalibrer sur des devis
locaux** dans une autre région) ; textes : `references/decence-tva-aides.md`. Pour un bien candidat (étape 4 de `/immo`, sous-agent B, ou
seul) et pour confronter un devis reçu ; pas pour un bien « refait à neuf », sauf doute sur la qualité.

## Entrées

1. **Classe DPE visée** : donnée par `/immo` ; à défaut, **E** (décence au 01/01/2028), et **D** (au 01/01/2034)
   chiffrée en sensibilité pour une détention au-delà de 2034 (réglage par défaut du skill, modifiable par une
   décision du `profil.json` de l'utilisateur).
2. **Audit énergétique ou DPE projeté du vendeur** : il prime. Reprendre son parcours vers la classe visée (travaux,
   coûts TTC, classes, facteur électrique), garder ce skill pour le reste, dire l'écart. Les recommandations jointes
   à un DPE sont indicatives (loi n° 89-462, art. 3-3) : un repère, pas un DPE projeté.
3. **Le bien** : fiche `lbc-scraper`, photos (les demander si elles manquent), description ; fiche de données
   ouvertes `immo-data/bruts/<slug>-opendata-<AAAA-MM-JJ>.json` : `dpe.a_l_adresse`
   (`periode_construction`, `type_energie_principale_chauffage`, `conso_5_usages_par_m2_ep`, `etiquette_dpe` ; vide :
   lire `erreurs`), et le bloc `urbanisme` s'il existe (`abords_monument_historique`).

## Programme de référence

Les seuls postes nécessaires pour (a) un logement décent et louable et (b) la classe visée. Rien de « confort » par
défaut.

**(a) Décent** : critères du décret n° 2002-120 (lu le 08/10/2026, versions dans `references/decence-tva-aides.md`).
Un critère appelle un poste seulement si les photos, le DPE, la description ou la visite le montrent manquant, et
alors le poste le plus simple qui le remplit :
- clos et couvert, sans infiltration ni remontée d'eau (art. 2, 1°) : reprise de couverture ou de menuiserie là où
  l'eau entre, traitement des remontées ;
- étanchéité à l'air des ouvrants et des parois, trappe aux cheminées (2°) : calfeutrer ; remplacer une fenêtre hors
  d'usage, pas une fenêtre qui ferme ;
- garde-corps et escaliers en état (3°) ; matériaux sans risque manifeste (4°) : plomb ou amiante dégradés traités ;
- électricité, gaz, chauffage et eau chaude conformes aux normes de sécurité et en bon état (5°) : mise en sécurité
  selon le diagnostic, réfection totale seulement s'il l'impose ;
- aération suffisante et évacuation de l'humidité (6°) : ventilation des pièces humides si elle manque ;
- chauffage normal, eau potable, évacuations, coin cuisine avec évier en eau chaude et froide, WC séparé, douche ou
  baignoire, électricité suffisante (art. 3) : l'équipement qui manque, en entrée de gamme (radiateurs électriques,
  cuisine et salle d'eau d'entrée de gamme) ;
- une pièce principale d'au moins 9 m² et 2,20 m sous plafond, ou de 20 m³ (art. 4) : sans elle, le logement n'est
  pas louable.

**Louable** : au loyer réaliste de l'étape 3 de `/immo`, qui suppose un état d'usage. Peintures et sols seulement là
où les photos les montrent dégradés ; une cuisine ou une salle de bains qui fonctionne reste. Les diagnostics annexés
au bail (loi n° 89-462, art. 3-3) sont un poste.

**(b) Classe visée.** Avec un audit ou un DPE projeté : les postes de son parcours vers la classe visée. Sans eux, et
classe actuelle sous la visée : les postes d'énergie que (a) impose (chauffage absent ou hors d'usage, ventilation
manquante), plus l'isolation des combles ou des rampants s'ils ne sont pas isolés, poste d'énergie le moins cher au m²
de la grille ; écrire « classe visée non démontrée : DPE projeté à demander avant offre ferme ». **La PAC n'entre
jamais dans le programme par défaut** : seulement si l'audit ou le DPE projeté la rend nécessaire à la classe visée,
et le programme le dit (« PAC exigée par <audit | DPE projeté> du <date> »).

**Maîtrise d'œuvre** : poste du programme si un permis de construire est nécessaire (architecte obligatoire pour une
personne morale, SCI comprise : `references/decence-tva-aides.md`, § Architecte) ou si le programme est une
restructuration ; sinon, option. Taux : grille.

**Chiffrage** : poste par poste avec la grille, bornes basse et haute TTC, quantité dite (mesurée, au plan, ou
« hyp. »), ni marge ni option dans les bornes. Un poste dont la nécessité est inconnue (toiture ou réseaux non vus)
ne gonfle pas la borne haute : il va dans « À lever en visite », avec son coût si la visite le confirme.

## Options

Hors programme : PAC, chauffe-eau thermodynamique, VMC (hors ventilation manquante), isolation des murs, menuiseries
(hors fenêtre hors d'usage), plancher bas, cuisine ou salle de bains refaites alors qu'elles fonctionnent, finitions.
Chacune avec ses bornes TTC, son **gain de classe** (audit, DPE projeté ou source publiée et datée ; sinon « gain non
chiffré : DPE projeté à demander ») et son taux de TVA s'il diffère. Les options ne s'ajoutent pas au programme :
`/immo` les chiffre en sensibilité.

## Aléas

Une ligne nommée, hors de la borne haute : taux × programme, sur la borne basse et sur la borne haute. Taux **15 %** ;
**20 à 25 %** sur du bâti ancien en pierre ou en meulière, 20 % sur la borne basse et 25 % sur la haute (taux du skill,
repère interne 05/2026, non sourcé). Ils ne couvrent ni les options ni « À lever en visite ».

## Budget travaux supportable

Ligne remplie par `/immo` à l'étape 6 (lancé seul : « moteur non lancé »). En financement `prix_plus_travaux`,
l'emprunt vaut prix + travaux (`engine/src/immo/financement.py`) ; le budget qui annule le cash-flow réaliste avant impôt au
prix demandé vaut `travaux + prix_equilibre.realiste − prix_net_vendeur` (`engine/src/immo/indicateurs.py`), avec les travaux
de l'exécution du moteur. Négatif : « le bien ne supporte aucuns travaux au prix demandé ». Financement `fixe` :
`prix_equilibre` vaut `null`, « non calculable (financement fixe) ». Seconde ligne, au seuil de confort `S`
(décision `seuil_confort_cf_mensuel` de `immo-data/profil.json`) : `travaux + prix de la sortie « cible » − prix_net_vendeur`, par la
même identité (le cash-flow ne dépend que de prix + travaux). Écrire,
pour chacune, ses écarts à la borne basse, à la borne haute et à la borne haute plus les aléas.

## Classe de chantier (cadrage)

Pour recouper le programme, pas pour le chiffrer : son €/m² face à la bande de sa classe (TTC, moyenne nationale).

| Classe | Contenu | €/m² |
|---|---|---|
| Rafraîchissement | peintures, sols, petits raccords | 150 – 200 (LMSG, MAJ 18/06/2026) |
| Rénovation standard | cuisine, salle de bains, électricité, menuiseries en partie | 500 – 1 000 (LMSG, MAJ 18/06/2026) |
| Rénovation lourde | tout refait sans toucher la structure | 1 000 – 1 400 (repère interne 05/2026, non sourcé) |
| Restructuration | cloisons, planchers ou structure modifiés, surface créée | 1 500 – 3 000 et plus (LMSG, MAJ 18/06/2026) |

## Points du bâti ancien

1. **Pierre, meulière, moellon** : isolation par l'intérieur confiée à un artisan du bâti ancien (perspirance) ;
   aléas majorés.
2. **Combles** : relever l'isolation, la charpente (traditionnelle ou fermette) et l'accès ; leur aménagement n'est
   pas un poste du programme.
3. **Humidité** : salpêtre ou trace grise en pied de mur d'un rez-de-chaussée ancien appelle un traitement (art. 2, 1°).
4. **Abords de monument historique** : l'accord de l'ABF peut imposer bois, tuiles plates ou chaux ; les chiffrer avec
   leurs lignes de la grille, et dire les délais.
5. **Immeuble de rapport** : compteurs individuels ou collectifs, première question ; coût par compteur : grille.

## Sortie attendue

```markdown
## Diagnostic travaux

**Classe DPE visée** : [E | D] ([donnée par /immo | E par défaut, D en sensibilité]) ; atteinte : [démontrée par <audit | DPE projeté> du JJ/MM/AAAA | non démontrée : DPE projeté à demander avant offre ferme]
**Classe de chantier** (cadrage) : [classe], programme à [X – Y] €/m² pour une bande de [A – B]

| Programme de référence | Pourquoi (décret n° 2002-120, diagnostics, parcours de l'audit) | Quantité | Basse | Haute |
|---|---|---|---|---|
| ... | ... | ... | ... € | ... € |
| **Programme** | | | **A €** | **B € TTC** |

| Option (hors programme) | Basse | Haute | Gain de classe (source, ou « gain non chiffré : DPE projeté à demander ») |
|---|---|---|---|

**Aléas** ([15 % | 20 à 25 %, bâti ancien], hors borne haute) : C € – D €
**À lever en visite** (hors programme) : [poste : coût si la visite le confirme]
**Budget travaux supportable** (`/immo`, étape 6), au cash-flow nul puis au seuil `S` : [E € | le bien ne supporte aucuns travaux au prix demandé | non calculable (financement fixe) | moteur non lancé] ; écarts à la borne basse, à la borne haute, à la borne haute plus les aléas
**Aides** : aucune déduite des bornes ; TVA poste par poste
```

## Vérifier les devis reçus (5 signaux d'alerte)

Confronter chaque devis au programme et à la grille ; les seuils sont ceux du skill, des ordres de grandeur non sourcés
à ne pas citer comme des chiffres :
1. **Baisse > 10 % sans modification du cahier des charges** : l'artisan ne maîtrise pas son chiffrage, ou il était
   trop cher au départ.
2. **Devis très en dessous des autres** (> 25 % sous la fourchette) : sous-estimation, fournitures bas de gamme non
   dites, ou avenants à venir ; exiger le détail poste par poste.
3. **Pas de détail** (un montant global sans ligne par corps de métier) : impossible à comparer, refuser.
4. **Pas de mention TVA, assurance décennale, RGE** : l'artisan RGE conditionne MaPrimeRénov' et les CEE, pas la TVA
   à 5,5 % (`references/decence-tva-aides.md`, § Aides et artisans RGE) ; vérifier l'attestation.
5. **Acompte > 30 %** ou planning flou : trésorerie tendue côté artisan.

Laisser les spécialistes spécialiser (pas de salle de bains confiée à un électricien) ; le devis le plus bas n'est pas
le moins cher si les délais glissent ou si des reprises suivent. Faire valider le chiffrage par un homme de l'art avant
offre ferme.

## Garde-fous

- Toujours des bornes, jamais un chiffre unique ; jamais de marge dans le programme.
- Une pièce non photographiée (salle de bains, toiture, tableau électrique) ne se devine pas : la dire, la mettre dans
  « À lever en visite », conseiller une visite avec un artisan avant offre ferme.
- Le niveau de gamme se dit sur chaque ligne ; le programme prend l'entrée de gamme quand il remplace un équipement.
- Les imprévus du bâti ancien vont dans la ligne d'aléas, jamais dans une marge cachée dans les postes.
- Conseiller des échantillons (carrelage, sol, peinture) avant de commander : le rendu change entre l'écran, le
  magasin et le logement.
