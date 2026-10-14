# Grille de coûts par corps de métier (TTC)

> Grille rédigée 05/2026, datée ligne par ligne le 08/10/2026 : toujours revalider sur devis réels avant engagement.
>
> **Portée géographique.** Les lignes sourcées sont des prix moyens nationaux ; les repères internes ont été rédigés
> pour un chantier en Île-de-France (grande couronne) en 2026. Dans une autre région, les recalibrer sur des devis
> locaux ou un guide de prix régional daté, et l'écrire sur la ligne (source, date). Aucune ligne ne se modifie sans
> source.
>
> **Deux sortes de lignes.**
> - **Sourcée** : prix moyen national d'un guide public, avec la date de mise à jour de la page (« LMSG, MAJ
>   JJ/MM/AAAA » = La Maison Saint-Gobain, page lue le 08/10/2026 sauf mention ; adresses en fin de fichier). Ce
>   n'est ni un devis ni un prix local : un devis du bien le remplace.
> - **« repère interne 05/2026, non sourcé »** : valeur de la rédaction d'origine, gardée faute de source.
>
> **TVA.** Une ligne sourcée est TTC quand la page le dit (taux non précisé par la page) ; sinon elle porte « HT »
> ou « taxe non précisée ». Un repère interne est lu TTC au taux de 10 % (travaux de rénovation d'un logement
> achevé depuis plus de deux ans, CGI art. 279-0 bis ; BOI-TVA-LIQ-30-20-90-40, version du 09/09/2026). Ajuster par
> poste : 5,5 % pour les prestations de rénovation énergétique éligibles (BOI-TVA-LIQ-30-20-95), 20 % pour les
> diagnostics, études et honoraires, et sur tout le chantier si les travaux produisent un immeuble neuf (règle dans
> `references/decence-tva-aides.md`).

Chiffrer poste par poste avec cette grille ; le €/m² de la classe de chantier (`SKILL.md`) ne sert qu'à recouper,
jamais à additionner.

### Gros œuvre / structure
- Ouverture d'un mur non porteur : 500 – 900 € l'unité (repère interne 05/2026, non sourcé)
- Ouverture d'un mur porteur avec IPN : 3 000 – 6 000 € l'unité, étude de structure obligatoire (repère interne 05/2026, non sourcé)
- Reprise de plancher bois (solivage) : 200 – 400 €/m² (repère interne 05/2026, non sourcé)
- Création de plancher béton : 350 – 550 €/m² (repère interne 05/2026, non sourcé)
- Cloisonnement : 40 – 80 €/m² ; isolation phonique : 25 – 50 €/m², taxe non précisée (LMSG, MAJ 23/04/2026)

### Toiture / charpente
- Réfection de couverture en tuiles plates : 150 – 250 €/m² de toiture (repère interne 05/2026, non sourcé ; la page LMSG du 16/04/2026 donne 120 à 300 €/m² pour un remplacement de couverture selon le matériau, sans détailler la tuile plate)
- Réfection de zinguerie : 100 – 200 €/ml (repère interne 05/2026, non sourcé)
- Isolation des combles perdus, posée : 30 – 70 €/m² selon le procédé, TTC (LMSG, MAJ 06/07/2026)
- Isolation des combles aménageables par l'intérieur (sous rampants), posée : 75 – 100 €/m² ; par l'extérieur, dépose de la couverture comprise : 200 – 250 €/m², TTC (LMSG, MAJ 06/07/2026)
- Aménagement de combles (cloisons, isolation, sols, fenêtres de toit) : 900 – 1 300 €/m² créé (repère interne 05/2026, non sourcé)
- Nettoyage + démoussage de toiture : 25 – 35 €/m² ; avec hydrofuge : 35 – 45 €/m² (LMSG, MAJ 10/03/2026, lue le 07/10/2026)
- Remplacement partiel de tuiles : ~100 €/m² ; couverture en tuiles terre cuite refaite : ~130 €/m², TTC (LMSG, MAJ 16/04/2026)
- Réparation de charpente : ~60 €/m² de toiture ; remplacement : ~188 €/m² (même page, MAJ 16/04/2026) ; un remplacement complet compte pour le critère « immeuble neuf » de la TVA
- Traitement de charpente : préventif 15 – 30 €/m², curatif par injection ~35 €/m² (Obat, page mise à jour le 04/11/2024, ancienne, lue le 07/10/2026)

### Façade / extérieur
- Ravalement de pierre avec rejointoiement (bâti ancien de centre-ville) : 80 – 150 €/m² de façade (repère interne 05/2026, non sourcé)
- Enduit de façade, pose comprise : 50 – 80 €/m² ; enduit à la chaux ou terre : 70 – 80 €/m², TTC (LMSG, MAJ 25/08/2026)
- ITE (isolation thermique par l'extérieur), fournie et posée : 130 – 215 €/m² (sous enduit 130 – 190, sous bardage 140 – 215), TTC (LMSG, MAJ 06/10/2026)
- Isolation des murs par l'intérieur (ITI) : 80 – 130 €/m² TTC posé (LMSG, MAJ 28/05/2026, lue le 07/10/2026) ; aucun prix pour un mur en pierre, qui demande un artisan du bâti ancien (`SKILL.md`, § Points du bâti ancien)

### Menuiseries extérieures
- Fenêtre PVC double vitrage, fournie et posée en remplacement : 870 – 1 170 € l'unité, TTC (LMSG, MAJ 13/02/2026)
- Fenêtre bois, taille moyenne, posée : ~1 500 € l'unité ; porte-fenêtre bois : ~2 400 €, TTC (LMSG, MAJ 04/12/2025) ; c'est la ligne des abords de monument historique si l'ABF impose le bois
- Porte d'entrée fournie et posée, dépose comprise : 1 500 – 4 000 € (PVC 1 500, bois ou acier 2 000, aluminium 3 000), TTC (LMSG, MAJ 22/12/2025)
- Volets roulants motorisés : 600 – 1 000 € l'unité (repère interne 05/2026, non sourcé)

### Électricité
- Réhabilitation totale du réseau : 80 – 100 €/m² HT, soit 88 – 110 €/m² TTC à 10 % (LMSG, MAJ 06/05/2026 ; une autre page du même site, MAJ 27/05/2025, donne 125 à 200 €/m² : écart à lever sur devis)
- Mise aux normes du tableau : 300 – 1 200 € ; remplacement complet du tableau : ~1 300 €, taxe non précisée (LMSG, MAJ 06/05/2026)
- Rafraîchissement prises / points lumineux : 30 – 50 €/m² (repère interne 05/2026, non sourcé)
- Diagnostic de l'installation électrique : ~100 € (LMSG, MAJ 06/05/2026) ; attestation Consuel « jaune » (habitation), si elle est exigée : 147,66 € TTC l'unité au tarif non professionnel, formulaire électronique (barème Consuel applicable au 01/09/2026 en métropole, document SC120_39)

### Plomberie / chauffage
- Refonte complète de la plomberie d'un logement de 50 à 80 m² : 4 000 – 8 000 € (repère interne 05/2026, non sourcé ; la borne basse recoupe le « budget minimal de 4 000 euros » d'une rénovation totale, LMSG, MAJ 23/07/2026)
- Chaudière gaz à condensation, remplacement fourni et posé (logement de 100 m²) : 4 500 – 6 200 €, TTC (LMSG, MAJ 04/12/2025)
- PAC air/eau fournie et posée, logement bien isolé, hors travaux connexes (radiateurs) : 12 100 € (moins de 100 m²), 14 700 € (100 à 150 m²), 16 000 € (plus de 150 m²) ; avec eau chaude : 13 400, 16 100 et 17 400 €, TTC (LMSG, MAJ 21/01/2026)
- Radiateur électrique à inertie, posé : 800 € (700 W, pièce de 5 à 9 m²) à 1 600 € (2 000 W, 20 à 25 m²), taxe non précisée (LMSG, MAJ 13/04/2026)
- Chauffe-eau thermodynamique 200 L sur air ambiant, installé : 2 000 – 4 000 € ; sur air extérieur : 2 500 – 3 500 €, taxe non précisée (LMSG, MAJ 21/01/2026)

### Cuisine (pièce de 12 m², pose comprise, hors électroménager)
- Entrée de gamme, souvent en kit : 2 200 – 2 900 €, TTC (LMSG, MAJ 04/12/2025)
- Milieu de gamme : 3 100 – 4 000 €, TTC (même page, MAJ 04/12/2025)
- Haut de gamme ou sur-mesure : 6 000 € à plus de 20 000 €, TTC (même page, MAJ 04/12/2025)

### Salle de bains (main-d'œuvre incluse)
- Rafraîchissement : 400 – 800 €/m², TTC (LMSG, MAJ 13/02/2026)
- Rénovation complète d'une salle de bains de 4 à 8 m² : 1 500 €/m² (entrée de gamme) à 2 500 €/m² (haut de gamme), 2 000 en milieu de gamme, soit 6 000 – 12 500 € pour 4 à 5 m² ; sous 4 m² : 2 000 à 3 000 €/m², TTC (même page, MAJ 13/02/2026)
- Création d'une salle de bains : 1 100 – 3 300 €/m², TTC (même page, MAJ 13/02/2026)

### Sols (fournis et posés)
- Sol stratifié : 69 – 91 €/m², TTC (LMSG, MAJ 02/02/2026)
- Parquet contrecollé : 95 – 151 €/m² ; parquet massif : 149 – 212 €/m², TTC (même page, MAJ 02/02/2026)
- Carrelage en grès cérame : 110 – 150 €/m² ; pose seule : 50 – 70 €/m², TTC (LMSG, MAJ 30/07/2026)
- Ponçage et vitrification d'un parquet existant : 35 – 50 €/m², TTC (LMSG, MAJ 02/02/2026)

### Peintures / finitions (au m² de surface peinte, mur ou plafond, pas de surface habitable)
- Peinture des murs : 20 – 35 €/m² en blanc, 25 – 45 €/m² en couleur ; des plafonds : 50 – 65 €/m² en blanc, 55 – 70 €/m² en couleur ; main-d'œuvre comprise, hors dépose de l'ancien revêtement, TTC (LMSG, MAJ 23/07/2026)
- Ratissage : simple 10 – 25 €/m² ; avec rebouchage 15 – 35 €/m² ; avec peinture 25 – 40 €/m², TTC (LMSG, MAJ 19/06/2026)
- Papier peint neuf milieu de gamme posé : 40 – 70 €/m² (repère interne 05/2026, non sourcé)

### Divers
- Désamiantage (colle ou dalles) : 50 – 120 €/m² traité (repère interne 05/2026, non sourcé)
- Injection contre les remontées capillaires : 20 – 200 €/ml selon la résine et l'état du mur, taxe non précisée (LMSG, MAJ 29/10/2024, page ancienne)
- Drainage périphérique : 200 – 300 €/ml (LMSG, MAJ 01/06/2026)
- VMC simple flux en rénovation : 600 € (autoréglable) à 1 200 € (hygroréglable) ; extracteur ponctuel : ~500 €, taxe non précisée (LMSG, MAJ 31/03/2026)
- VMC double flux, fournie et posée : 1 600 – 3 500 €, taxe non précisée (même page, MAJ 31/03/2026)
- Évacuation des gravats et encombrants, benne au forfait (livraison, 7 jours de mise à disposition, enlèvement, traitement), HT : 8 m³ 150 – 400 € (moyen 250 €) ; 10 m³ 200 – 600 € ; 15 m³ 300 – 800 € ; plus de 20 m³ 400 – 1 000 € ; benne sur la voie publique : autorisation et redevance de la commune en plus (conseils.hellopro.fr, « chiffres constatés en octobre 2026 », lu le 13/10/2026)

### Compteurs (immeuble de rapport, location par parties)
- Installation d'un compteur électrique : 1 000 – 2 500 € ; d'un compteur d'eau : 800 – 1 500 €, budget estimatif, taxe non précisée (LMSG, MAJ 23/04/2026)

### Assainissement non collectif
- Fosse toutes eaux : 7 000 – 10 000 € ; micro-station : 8 000 – 11 000 € ; phytoépuration : 4 000 – 5 000 €, taxe non précisée (LMSG, MAJ 23/07/2026)
- Étude de sol : 600 – 800 € ; dépose de l'ancien système : 2 000 – 5 000 € (même page, MAJ 23/07/2026)

### Maîtrise d'œuvre
- Honoraires de maîtrise d'œuvre : 8 à 12 % du HT des travaux (repère interne 05/2026, non sourcé) ; quand ils entrent au programme : `SKILL.md`, § Programme de référence

### Postes sans prix de référence (à chiffrer sur devis)
- Isolation du plancher bas (par le dessous si vide sanitaire ou cave ; sur terre-plein, dépose du sol en plus)
- Raccordement au tout-à-l'égout (partie privée + participation au financement de l'assainissement collectif)
- Diagnostics avant vente, avant location ou avant travaux (DPE, plomb, amiante avant travaux)

### Matériaux seuls, pour l'autoconstruction (TTC, achat d'un particulier ou d'une SCI : TVA de 20 %)
À présenter à côté du prix d'un artisan seulement si l'utilisateur prévoit de poser lui-même ; prix de magasin, à revérifier le jour de l'achat.
- Isolants en rouleau ou en panneaux, liants et enduits (chaux, sable), petites fournitures de réseaux (regards, tampons) : relever le prix sur la fiche produit d'une enseigne de bricolage, avec l'enseigne, la référence et la date de lecture ; aucun prix de cette famille n'est tenu à jour ici
- Mise en œuvre : suivre la notice du fabricant et les règles de l'art du poste

### Pages lues (La Maison Saint-Gobain, `https://www.lamaisonsaintgobain.fr/…`, le 08/10/2026 sauf mention)

| Lignes | Chemin de la page |
|---|---|
| combles | `guides-travaux/isolation/prix-isolation-combles` |
| toiture, charpente | `guides-travaux/toiture-charpente/quel-prix-pour-votre-renovation-de-toiture` ; nettoyage : `…/prix-nettoyage-toiture-m2` (07/10/2026) |
| enduit | `facades/conseils/avant-de-vous-lancer-dans-les-travaux-de-facades/prix-enduit-m2` |
| ITE ; ITI | `guides-travaux/isolation/prix-isolation-thermique-par-l-exterieur-ite-au-m2` ; `…/isolation/prix-isolation-par-l-interieur-iti` (07/10/2026) |
| fenêtre PVC ; fenêtre bois ; porte | `guides-travaux/menuiseries-exterieures/prix-fenetre-pvc` ; `…/prix-changement-de-fenetre` ; `…/prix-porte-d-entree` |
| électricité (2026 ; 2025) | `guides-travaux/questions-travaux/combien-coute-une-mise-aux-normes-electrique` ; `guides-travaux/tout-savoir-sur-l-electricite/prix-renovation-electrique-travaux-electricite` |
| plomberie ; assainissement | `guides-travaux/plomberie-sanitaire/tarif-plombier-et-prix-des-travaux-de-plomberie` ; `…/prix-assainissement-individuel-maison` |
| chaudière ; PAC ; radiateur ; VMC | `guides-travaux/tout-savoir-sur-le-chauffage-et-la-ventilation/` + `prix-remplacement-chaudiere-gaz`, `le-prix-d-une-pompe-chaleur-air-eau`, `radiateur-inertie-pour-salle-de-bain`, `quelle-vmc-choisir` |
| chauffe-eau thermodynamique | `guides-travaux/plomberie-sanitaire/prix-chauffe-eau-thermodynamique` |
| cuisine ; salle de bains | `cuisines/conseils/concevoir-sa-cuisine/prix-cuisine` ; `salles-de-bain/conseils/renovation-de-la-salle-de-bain/prix-d-une-salle-de-bain` |
| sols ; carrelage | `guides-travaux/amenagement-interieur/prix-pose-parquet` ; `…/prix-carrelage` |
| peinture ; ratissage | `guides-travaux/amenagement-interieur/prix-peinture-au-m2` ; `…/prix-ratissage-m2` |
| remontées capillaires ; drainage | `facades/conseils/renover-la-facade-de-sa-maison/remontees-capillaires-quels-traitements` ; `guides-travaux/renovation-maison/drainage-maison` |
| cloisonnement, compteurs | `guides-travaux/renovation-maison/comment-transformer-une-maison-en-deux-appartements` |

Consuel : `https://www.consuel.com/wp-content/uploads/2026/08/SC120_39.pdf` (tarif applicable à partir du 01/09/2026,
métropole), lu le 08/10/2026. Obat : `https://travaux.obat.fr/guides/prix-traitement-charpente/`.
