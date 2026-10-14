# Terrain achat immobilier (`immo_achat`)

Méthode d'achat d'un bien à louer, encadrée par le socle (`socle.md`) et le droit (`droit.md`). Journal :
`immo-data/negociations/<slug>.json`, terrain `immo_achat`, rôle `acheteur`.

## Quand ce terrain s'applique

- Achat d'un bien pour le louer, étudié par `/immo` (étape 8 : négociation), dans la zone de l'investisseur (décision `zone` de `immo-data/profil.json`) ; ou toute question « combien offrir », « que répondre à l'agent », « contre-proposition » sur un bien à acheter.
- Hors `/immo`, sans sortie du moteur : ni plafond ni cible ne se donnent ; le dire et proposer `/immo`.
- Ne couvre pas : la rentabilité (moteur via `/immo`), un devis d'artisan (`artisans.md`), le crédit.

## Entrées et outils

| Entrée | Où la lire (citer, ne pas recopier) |
|---|---|
| Plafond, cible, sensibilité au loyer, test de réalisme | sortie nommée du moteur du plugin via `/immo` ; règles : `skills/immo/references/negociation_livrable.md` §Paliers |
| Montage (le montage de référence du profil) | `skills/immo/references/montages.md` |
| Ancienneté réelle, baisses, annonces liées | fiche `lbc-scraper` (`skills/lbc-scraper/SKILL.md` §Identité et ancienneté) |
| DPE à l'adresse, risques, PPRN, DVF (comparables, même parcelle) | fiche de données ouvertes `immo-data/bruts/<slug>-opendata-<AAAA-MM-JJ>.json` (`engine/scripts/immo_fiche_opendata.py`) |
| Comparables et marché | `market-context` (`skills/market-context/SKILL.md`) |
| Programme de travaux | `renovation-estimator` (`skills/renovation-estimator/SKILL.md`) ; d'abord les **pièces du vendeur** |
| Pièces à demander, message type | `skills/immo/references/pieces_a_demander.md` |
| Seuil de confort `S`, profil, zone | `immo-data/profil.json` |
| Fiabilité du dossier de l'acheteur | `immo-data/foyer.json` (lu, jamais recopié) |
| Leçons du terrain, journal | `retex.md` §Leçons de départ ; `negoc_journal.py bilan --terrain immo_achat` |

**Contexte local** : le marché de la zone se **mesure**, il ne se suppose pas. Dans un marché détendu,
des biens restent longtemps en vente, surtout les atypiques ; la durée se mesure bien par bien et se
compare aux annonces du secteur relevées dans les cribles de `/immo` (`immo-data/bruts/`). Les
particuliers négocient souvent plus que les agences ; les notaires sur vente amiable ou succession
peuvent être rigides. Biais courants du vendeur : prix calé sur une estimation d'agent gonflée
(captation du mandat) ou sur un voisin vendu cher avant la remontée des taux. **Aucune marge ni aucun
délai de vente par défaut** : ils se relèvent, datés et sourcés, à chaque négociation (lacune française
du socle : aucune étude française ne les fixe).

## Ce qui s'exige et ce qui se négocie

- **S'exige** (droit, `droit.md`) : DDT complet avant l'avant-contrat (D11), ERP dès la visite (D12), audit énergétique pour une maison ou un immeuble hors copropriété classé E, F ou G (D13) ; signature de l'acceptation par tous les vendeurs (D18) ; aucun versement avec l'offre (D7, D9).
- **Se négocie** : prix net vendeur ; honoraires d'agence (libres et négociables, D18) ; date de signature et de libération ; mobilier (ventilation à faire valider par le notaire) ; conditions suspensives écrites au compromis (prêt pour une SCI, certificat d'urbanisme) ; délai de rétractation accordé par contrat à une SCI (D-J13).
- **Ne se négocie jamais** : une protection légale (renoncer au DDT, à l'ERP, à la condition de prêt d'une personne physique).

## Leviers

Pour chaque levier applicable, **quantifier l'impact en euros** ; un argument non chiffré ne vaut rien
à l'écrit. Les pourcentages ci-dessous sont des **repères non sourcés : ne pas citer au vendeur** ; un
montant tiré d'une pièce (audit, devis, diagnostic) ou d'une sortie du moteur les remplace toujours, et
la stratégie dit lequel elle a utilisé. Chaque levier porte sa colonne **citable** (pièce du vendeur,
fait daté) ou **interne** (étude, repère, statistique).

### 1. Ancienneté de l'annonce

- L'**ancienneté réelle** estimée par `lbc-scraper` (§Identité et ancienneté), date la plus ancienne et sa source ; jamais la date affichée seule (Leboncoin republie).
- Lecture (repère non sourcé : ne pas citer au vendeur) : moins d'un mois, pas de levier ; un à deux mois, léger levier ; deux à quatre mois, levier fort ; au-delà, très fort. Socle : une annonce nettement plus ancienne que le délai de vente local (à relever et dater) ou déjà baissée justifie d'ouvrir plus bas [C4, C6, C7] (moyen).
- **Chiffrage** (repère non sourcé : ne pas citer au vendeur) : −2 à −5 % du prix affiché, seulement si l'ancienneté réelle est établie par une date sourcée ; sinon 0 €. **Citable** : la date, en fait daté, sans commentaire.

> **Les 5 prix mentaux d'un vendeur** dont le bien ne se vend pas (modèle de praticien, **non sourcé**, le socle ne l'établit pas) : (1) « plus-value rêvée », (2) « je rembourse mon prêt », (3) « équilibre », (4) « légère décote », (5) « réel de marché ». Plus l'annonce est ancienne et baissée, plus le vendeur est descendu ; une annonce ancienne sans vente est souvent bloquée au niveau 2 ou 3 : la négociation l'amène au niveau 5, ses propres pièces à l'appui. Le socle confirme le fond : un vendeur sous son point de référence affiche haut, attend et cède peu [C1-C3] (fort).

### 2. Baisses de prix successives

- Chaque baisse antérieure montre un vendeur qui a accepté de descendre ; `old_price` et les annonces liées (`lbc-scraper` §Identité et ancienneté) les montrent. Une baisse attire de nouvelles offres [C4].
- **Chiffrage** : la marge entre prix d'origine et prix actuel est déjà acquise ; on négocie sur le prix actuel ; le repère de −3 à −5 % supplémentaires (non sourcé : ne pas citer au vendeur) se lit dans le chiffre commun aux leviers 1 et 2, jamais en plus. Leviers 1 et 2 forment **un seul chiffre**, de −2 à −5 % du prix affiché, jamais additionnés (règle de méthode).

### 3. DPE défavorable

- **Calendrier de décence énergétique** (métropole ; loi n° 89-462 art. 6 modifié par la loi n° 2021-1104 ; décret n° 2023-796 du 18/08/2023 ; ANIL, page du 11/09/2023, lue le 07/10/2026) : G non décent depuis le 01/01/2025, F au 01/01/2028, E au 01/01/2034 ; pour les nouveaux baux, puis à leur renouvellement ou reconduction.
- **Chiffrage** : coût de la rénovation énergétique pour passer en E ou D, pris dans **l'audit ou un devis** du vendeur ; à défaut de pièce : −5 à −15 % selon surface et état (repère non sourcé : ne pas citer au vendeur). Ce coût est **déjà dans le levier 4** : ne pas le compter deux fois.
- **Argument clé (citable)** : l'audit chiffre lui-même les travaux pour sortir de la passoire ; c'est la pièce du vendeur, le levier écrit le plus difficile à réfuter. L'audit prime sur le modèle DPE de l'étude ; le demander dès E, F ou G (retex I6 ; `droit.md` D13).
- **Valeur verte (interne)** : décote, à caractéristiques égales, face à un bien classé D (Notaires de France, valeur verte des transactions 2024, page du 07/01/2026 [C23]) ; lire la ligne de la région et du type de bien. Exemple de l'étude, grande couronne francilienne, maisons : E −5 à −4 %, F −12 à −10 %, G −17 à −15 %. À n'employer qu'en interne, face à des comparables classés D ou mieux, et **jamais en plus** du coût des travaux qui mènent à D (double compte ; déduction de la méthode).
- **Données ouvertes** : `dpe.a_l_adresse` de la fiche (`etiquette_dpe`, `conso_5_usages_par_m2_ep`, `date_etablissement_dpe`, drapeau `avant_reforme_coef_elec`) ; un écart avec la classe annoncée est un argument ; bloc vide ou `null` : lire `erreurs`, demander le DPE. Électricité : facteur 1,9 en 2026, 1,7 au 01/01/2027 (`droit.md` D14) ; vérifier l'étiquette avant d'en faire un argument.

### 4. Travaux lourds

- Le chiffrage de `renovation-estimator`, et d'abord les **pièces du vendeur** (audit, devis, diagnostics) : ce sont elles que le message cite (retex I1).
- **Chiffrage** : 60 à 80 % du coût des travaux déductible du prix (repère non sourcé : ne pas citer au vendeur ; `/immo` compte les travaux à 80 % du plancher faute de devis) ; jamais 100 %, sinon le vendeur n'a aucun intérêt. Bien à travaux : plafond = prix d'équilibre à travaux nuls moins les travaux, et le budget que chaque prix laisse se dit au vendeur (retex I3 ; `skills/immo/references/negociation_livrable.md` §Paliers).

### 5. Défauts objectifs

- Rez-de-chaussée humide, pas d'ascenseur au-delà de 3 étages, pas d'extérieur, plein nord, vis-à-vis.
- **Chiffrage** : −2 à −8 % cumulés selon l'empilement (repère non sourcé : ne pas citer au vendeur). **Citable** seulement si une pièce ou un constat de visite le prouve.

### 6. Contraintes locales

- **PPRI** (zone rouge ou bleue : assurance, travaux, valorisation) : −5 à −12 % (repère non sourcé : ne pas citer au vendeur). Socle, **interne** : décote française mesurée de 3 à 7 %, jusqu'à 11 % selon la commune, plus forte en rez-de-chaussée et en marché détendu [C20, C21] ; l'effet « après crue » ne vaut que pour un bien sinistré récemment [C19]. Au vendeur, on cite son ERP, pas une étude.
- **Nuisances** (grand axe routier, voie ferrée, zone industrielle) : −2 à −5 % ; **copropriété en difficulté** : −5 à −10 % (repères non sourcés : ne pas citer au vendeur).
- **Données ouvertes** : bloc `risques` de la fiche (`risques.commune`, `risques.adresse`, `risques.pprn`) ; un sous-bloc `null` n'est pas une absence de risque : lire `erreurs`, puis Géorisques.
- Décote PPRi et travaux de protection : **sans double compte**.

### 7. Comparables DVF

- Ventes comparables à moins de 500 m, même type, **même état**, sous le prix au m² affiché : elles fondent l'**ancrage** ; elles ne se citent **pas** au vendeur (retex I1 : une médiane ignore l'état et plaide pour le vendeur dès que son plancher s'en approche). **Interne.**
- **Chiffrage** : écart entre le prix affiché et la médiane du type, 0 € quand le prix est déjà sous la médiane ; un levier qui joue contre nous vaut 0, jamais retourné (retex I3).
- **Données ouvertes** : `dvf.comparables` (mutations mono-local dédoublonnées), médiane `dvf.par_type` ; pas les mutations exclues (`dvf.compteurs`) ; adresse, date et prix seulement (CGU DGFiP).
- **Même parcelle, point de référence du vendeur** (fort [C1-C3] ; retex I3) : une vente DVF du bien lui-même peu avant est son prix d'achat probable, le levier le plus fort. **Citable** par adresse, date et prix, ou posée à l'oral (« depuis quand êtes-vous propriétaire ? »). Calculer, pour chaque palier, sa plus-value ou sa perte en euros ; une perte annonce une négociation longue ; et le coût net d'une baisse pour lui (`droit.md` D19, interne).

### 8. Profil acheteur

- Ne se chiffre pas. Un dossier prêt rassure, mais rien n'est affiché sur le financement (§Messages, formule de l'offre). La fiabilité se dit à l'oral, sans chiffre : situation professionnelle stable (`immo-data/foyer.json`, lu, jamais recopié) et accord de principe bancaire s'il existe. À 0 quand le taux d'effort HCSF du foyer dépasse le plafond (sortie du moteur).

**Signaux de vendeur motivé, interne** [C13-C17] (moyen), à vérifier avant usage :
bien **vide** (photos sans meubles, « libre de suite », constaté en visite ; coût de détention [C15]) ;
**succession** ou indivision (qui signe, quelle échéance ; rabais mesurés [C16, C17] mais règle de la
méthode : fiabilité, aucune pression, §Lignes rouges et droit) ; mutation, achat déjà signé, prêt relais
(échéance demandée, dates recoupées). Signal vérifié : viser le bas de la fourchette et offrir en
échange rapidité et certitude. **Signaux contraires** : achat récent au-dessus de notre offre visible
dans DVF, forte dette (vendeur rigide). **Agent** : payé au pourcentage, il gagne peu par euro de plus
et pousse à conclure [C10-C12] (non testé en France) : offre écrite et chiffrée, limite jamais
révélée ; lui demander l'historique de l'annonce, les visites et les offres reçues.

## Paliers

- **Plafond et cible : lus, jamais recalculés.** Ils sortent du moteur du plugin via `/immo`, sur le montage retenu ; règles : `skills/immo/references/negociation_livrable.md` §Paliers. Chaque palier cite sa **sortie nommée** du moteur, en net vendeur, puis converti en FAI en **ajoutant le montant en euros des honoraires à la charge de l'acquéreur affichés par l'annonce** (FAI = net vendeur + honoraires affichés ; convention de `skills/immo/references/negociation_livrable.md` §Paliers, « honoraires acquéreur ajoutés »), jamais par un pourcentage supposé ; un barème du mandat en pourcentage se signale dans « À vérifier avant envoi », sans changer la conversion ; honoraires inconnus : `[●]`. La même conversion vaut pour l'ancrage et chaque pas du plan de concessions. Plafond = `prix_equilibre.realiste` (walk-away) ; cible = prix au cash-flow de confort `S`. Écrire en interne : « au-delà de [plafond FAI] €, pas d'accord ».
- **Garde-fous des paliers** : aucune offre sans les paliers du moteur ; vérifier que le plafond ne fait pas passer le cash-flow réaliste sous 0 €/mois et que la cible laisse le cash-flow de confort `S` : sinon ce n'est pas un plafond, c'est un no-go (une belle négociation sur un bien non rentable reste une perte de temps). Un comparable DVF utilisé dans la stratégie porte sa date et son adresse ; il ne se cite pas au vendeur.
- **Ancrage** (première offre écrite), formule de la méthode, leviers 1 et 2 lus en un seul chiffre :

  ```
  prix_ancrage = prix_annonce − impact des leviers sans double compte − 3 % de marge de repli
                 (rénovation énergétique du levier 3 déjà incluse dans le levier 4 ;
                  leviers 1 et 2 en un seul chiffre, −2 à −5 %)
  ```

  Les 3 % de repli sont une convention de méthode (laisser de quoi remonter), pas un fait de marché. Les 3 % de repli se prennent sur le prix affiché, la même assiette que les leviers 1 et 2 (exemple fictif : sur un prix affiché de 160 000 €, leviers 1 et 2 à 3 % et repli à 3 %, soit 4 800 € chacun) ; travaux à 80 % du plancher faute de devis. Attendu : refus et contre-offre, c'est normal.
- **Face aux paliers** (`skills/immo/references/negociation_livrable.md` §Paliers) : sous la cible, c'est la première offre ; entre la cible et le plafond, encore la première offre, et la stratégie dit que la cible n'est pas atteignable sur pièces ; au-dessus du plafond, **pas d'offre chiffrée** (prix en `[●]`).
- **Encadrement par le socle** :
  - chaque euro entre le prix affiché et l'ancrage est adossé à un **levier documenté** [A2, A9] ;
  - **test de défendabilité** : une offre sous toutes les ventes voisines de même état est indéfendable (`skills/immo/references/negociation_livrable.md` §Paliers ; [A2, A9]) : la remonter ou la justifier par une pièce ;
  - **risque d'offense et d'impasse** : ambitieux sur le chiffre, ménagé sur le ton [A2, A9] ;
  - **précision modérée** : 3 ou 4 chiffres significatifs (87 400 plutôt que 87 000), pas de centimes ; face à l'agent, une phrase de méthode (« sur la base des montants de l'audit ») [A10, A11] ;
  - **point de référence du vendeur** (prix d'achat DVF, valeur de succession) et **coût net d'une baisse** pour lui (`droit.md` D19), en interne ;
  - aucune marge « typique » ni pourcentage du prix affiché comme base [C6, C8, C9].
- **Loyer inconnu** : ne pas l'inventer ; tabuler le plafond (`skills/immo/references/negociation_livrable.md` §Paliers). Rendement annoncé par l'agence : le recalculer avec nos loyers ; le prix qui le rendrait vrai est un ancrage **interne** (retex I4).
- **Plan de concessions** entre l'ancrage et le plafond : `concessions.md` §Plan de concessions.

## Séquence

0. **Préparer** (`socle.md` règles 3 et 4) : écrire les **intérêts probables du vendeur** (calendrier, certitude de la vente, fin des frais d'un bien vide, simplicité pour une famille ou des héritiers, point de référence) et les **échanges hors prix** possibles (date de signature ou de libération, mobilier, conditions, délai des conditions suspensives) ; ils nourrissent les questions de l'appel et le plan de concessions.
1. **Prise de contact orale** (avant l'offre écrite ; retex I7 ; script : `messages.md` §Gabarits) :
   1. demander à l'agent le prix plancher du vendeur : « à quel prix pensez-vous que le vendeur accepterait de céder ? » ;
   2. questionner les défauts par des questions qui présupposent un problème courant [B12], et la vente (date réelle de mise en vente, visites, offres écrites reçues, motif et calendrier, qui signe, net vendeur et honoraires, dernier loyer ou bail, contenu des devis) ;
   3. ne rien dire du budget, de la limite, du loyer visé, de l'urgence ni d'un coup de cœur [A6] ;
   4. si l'agent avance un loyer : ne pas opposer un autre chiffre, demander le dernier loyer pratiqué, bail à l'appui (retex I2) ;
   5. après l'appel : écrit bref qui confirme les points importants ; coup `information` au journal.
2. **Pause** de 24 à 48 h (pratique, non prouvée [B4]).
3. **Formule ouverte, pas un ultimatum** : « j'arrive difficilement à ce prix compte tenu de [travaux / DPE / diagnostics] ; comment peut-on faire ? » ; l'agent plaide alors notre dossier.
4. **Offre écrite** (§Messages), une seule à la fois : **pas d'offres fermes simultanées** sur plusieurs biens (`droit.md` §Loyauté et lignes rouges).
5. **Contre-propositions** : `concessions.md` §Lire une contre-proposition ; réponse courte (§Messages).
6. **Dernier mot** au palier de la limite, structure G1 (`messages.md` §Gabarits).
7. **Compromis** chez le notaire : pièces exigées avant (§Ce qui s'exige), conditions écrites.

**Options équivalentes possibles** (MESO, `concessions.md` §Plan de concessions) : prix contre date de
signature, mobilier, date de libération ; **jamais** une option qui renonce à une protection légale.
Bien à fort potentiel de transformation : offre plus généreuse **assortie d'une condition suspensive
de certificat d'urbanisme** au compromis.

## Messages

Règles du message au vendeur (retex I1, I8), plus les règles communes de `messages.md` §Règles
d'écriture :

- **Brouillon** relu et validé par l'investisseur, jamais envoyé par Claude ; bâti sur les **propres pièces du vendeur**.
- **Accroche** : les défauts que les pièces du vendeur documentent (amiante, plomb, humidité, classe DPE, audit), chacun seulement là où une pièce le prouve, avec le nom de la pièce ; pas de politesses en ouverture.
- **Deux ou trois postes** : dans le message, **seulement les 2 ou 3 postes les plus lourds**, aux montants des pièces ; la liste détaillée, chiffrée par les pièces, en **fiche jointe**, qui dit ce qu'elles ne comptent pas. Jamais « au moins X € » tiré du bas de notre fourchette. Conclusion : « le compte n'y est pas » au prix affiché ; ton neutre, aucun jugement sur le bien.
- **Aucun argument de loyer, de rendement ni de cash-flow** (retex I1) ; **aucune statistique DVF**, sauf une vente du bien lui-même (levier 7).
- **Formule de l'offre** : « à formaliser par un compromis chez le notaire, avec les conditions habituelles », plus « sous réserve de notre financement » selon le choix de l'investisseur lu dans `immo-data/profil.json` (`droit.md` §Formule de l'offre ; absent : lui demander). Sans réserve de financement, le risque est assumé (`droit.md` §Offre et acceptation) : ne rien écrire qu'on ne signerait pas.
- **Ancienneté** citée seulement si une date sourcée l'établit, en fait daté, sans commentaire.
- **Prix** en FAI **et** en net vendeur, **date de validité** ; jamais le plafond, la cible ni les paliers ; il ne cite que des leviers comptés dans l'ancrage, les autres vont dans « À vérifier avant envoi ». Les défauts de l'accroche sont des faits que prouvent les pièces du vendeur, pas des leviers : ils se citent même non chiffrés ; tout montant cité dans le message est, lui, compté dans l'ancrage.
- **Ton** humain et bref, paragraphes de longueurs inégales, pas de listes partout, chaque fait vrai et vérifié ; aucun tiret cadratin.

**Gabarit, pièce 1 : message bref**

```
Objet : [Type], [rue ou secteur], [commune] - offre d'achat (annonce [ID])

Bonjour [Madame, Monsieur / prénom de l'agent],

Nous avons étudié de près le dossier de [la maison / l'immeuble], et ses propres diagnostics posent le sujet : [défaut 1, pièce qui le prouve], [défaut 2, pièce], [classe DPE, audit ou DPE et sa date].

Les travaux qui en découlent sont chiffrés par ces pièces : [poste 1, montant de la pièce], [poste 2, montant de la pièce][, poste 3, montant]. Le détail, poste par poste, est dans la fiche jointe, avec ce que les pièces ne comptent pas.

Avec ces travaux, le compte n'y est pas au prix affiché. Nous vous proposons [PRIX FAI] € frais d'agence inclus, soit [PRIX NET VENDEUR] € net vendeur, à formaliser par un compromis chez le notaire, avec les conditions habituelles. Cette offre est valable jusqu'au [date].

Nous restons disponibles pour en parler de vive voix.

Bien cordialement,

[prénom nom]
[téléphone]
```

**Gabarit, pièce 2 : fiche travaux jointe**

```
Fiche jointe : travaux documentés par les pièces du dossier, [type], [commune]

| Poste | Pièce du vendeur (nature, date) | Montant de la pièce | Ce que la pièce ne compte pas |
|---|---|---|---|
| [poste] | [audit énergétique du JJ/MM/AAAA, scénario retenu] | [montant] € TTC | [maîtrise d'œuvre, imprévus, mise aux normes...] |
| [défaut prouvé, non chiffré] | [diagnostic amiante / plomb / électricité du JJ/MM/AAAA] | non chiffré par les pièces | [ce que le diagnostic signale] |
| Total chiffré par les pièces | | [somme] € TTC | |

Montants repris tels qu'ils figurent dans les pièces citées.
```

**Réponse à une contre-proposition** (retex I2, I8 ; `messages.md` §Gabarits pour la forme) : courte ;
travaux admis et confirmés par les pièces du vendeur ; devis du vendeur : demander leur contenu (postes,
périmètre) avant de les retenir, l'audit reste la référence tant qu'ils ne sont pas vus ; loyer avancé : demander **dans le message écrit** le dernier loyer pratiqué, bail à l'appui, sans contre-chiffre ; « un acquéreur se positionne » :
non étayé tant qu'aucune offre écrite n'est montrée ; « d'autres visites en cours » seulement si c'est
vrai ; le compte n'y est pas ; offre maintenue ou une seule petite concession contre contrepartie, avec
une date de validité ; une partie du bien seule se recalcule seule au moteur, jamais par division.

**Achat par une SCI à créer** : faculté de substitution au profit de la SCI, ou achat au nom de la SCI
en formation avec reprise des engagements (`skills/immo/references/montages.md` §SCI à l'IS :
points pratiques), **à valider par le notaire** (`droit.md` §Offre et acceptation).

## Objections

| Objection | Réponse | À ne pas dire |
|---|---|---|
| « Avec [X] € de loyer, ça se rentabilise vite. » | Demander le dernier loyer pratiqué, bail à l'appui (retex I2). | Un autre loyer, un rendement, un cash-flow. |
| « Le vendeur a fait faire des devis plus bas. » | Demander les devis : postes, périmètre, date ; l'audit reste la référence tant qu'ils ne sont pas vus (retex I8). | « Vos devis sont faux » ; nos estimations. |
| « Un autre acquéreur se positionne. » | Une question sur l'existence d'une offre écrite ; offre maintenue avec sa validité (retex I8). | Une hausse, une contre-annonce inventée. |
| « Une partie seule du bien vous intéresserait ? » | « À étudier » : recalcul de cette partie seule au moteur via `/immo` ; aucun prix dérivé de l'ensemble. | Un prix par division du prix de l'ensemble. |
| « Le prix est celui de l'estimation de l'agence. » | L'estimation est ancrée sur le prix affiché [A16] : revenir aux pièces du bien. | Une médiane DVF. |
| « La famille ne descendra pas sous [X]. » | Prendre acte ; si [X] dépasse le plafond, « le compte n'y est pas » et porte ouverte. | Une pression sur la famille ou la succession. |

Objections transverses : `concessions.md` §Objections.

## Lignes rouges et droit

Détail et sources : `droit.md`. Pour ce terrain :

- **Offre acceptée = vente** : une offre précise acceptée forme la vente (D-J1 à D-J5, D6) ; sans réserve de financement (choix de l'investisseur, `droit.md` §Formule de l'offre), le risque est rappelé en une ligne au contrôle avant envoi (`messages.md` §Avant envoi). Pas d'offres fermes simultanées sur plusieurs biens.
- **SCI** : pas de délai de rétractation (CCH L271-1, D-J12) ; condition de prêt légale probablement absente (C. conso. L313-1 3°, D10) : l'écrire au compromis ; délai de rétractation contractuel possible (D-J13).
- **Aucun versement** avec l'offre (D7, D9) ; dépôt de garantie chez le notaire seulement.
- **Agent et mandat** : l'agent n'engage le vendeur que par pouvoir exprès ; l'acceptation se signe par tous les vendeurs (D18, D-J6, D-J7) ; jamais d'achat direct pour écarter l'agent par fraude (D-J8, D-J9) ; offrir par un autre agent mandaté est permis sans lien contractuel (D-J10).
- **DDT, ERP, audit** exigés avant l'avant-contrat (D11 à D13).
- **Vendeur vulnérable**, succession, vente conduite par la famille : fiabilité, délais respectés, aucune pression ni allusion à sa situation, orientation vers son notaire (D16, D17 ; règle de la méthode : ne pas chercher à pressurer). Le signal calibre l'ouverture, il ne s'écrit pas.
- **Honoraires** libres et négociables (D18) ; **mobilier** : ventilation à faire valider par le notaire (non vérifié au socle), jamais surévalué.
- **Données** : aucun nom de tiers ni chiffre du foyer dans un journal ou un fichier partagé (retex I9).

## Leçons des négociations passées

Leçons du terrain, chacune avec la section où la règle vit : `retex.md` §Leçons de départ, I1 à I9, et
§Leçons ajoutées.

## Sources

Études : `socle.md` §Sources (identifiants A, B, C, E cités ici). Droit : `droit.md`. Calendrier de
décence : loi n° 89-462 art. 6, loi n° 2021-1104, décret n° 2023-796, ANIL (lue le 07/10/2026). Valeur
verte : Notaires de France / ADNOV, décembre 2025 [C23]. Leçons : `retex.md`.

## Sortie dans l'étude

Forme de la section `## Négociation` d'une étude `/immo` : **40 lignes au plus** dans l'étude, le
détail en annexe (`skills/immo/references/negociation_livrable.md` §Étape 9,
annexes). Elle s'ouvre sur les deux lignes de `skills/immo/references/negociation_livrable.md` §Étape 8 (sensibilité au loyer,
test de réalisme).

```markdown
## Négociation

[Sensibilité au loyer : +50 €/mois ⇒ +X € de plafond (sortie <slug>-loyer50-sortie.json)]
[Test de réalisme : plafond FAI face au prix affiché et à la valeur DVF de même état, en € et en %]

| Palier | Net vendeur | FAI | Source |
|---|---|---|---|
| Ancrage (première offre) | … € | … € | formule §Paliers, leviers ci-dessous |
| Cible | … € | … € | sortie moteur <nom> |
| Plafond (walk-away) | … € | … € | sortie moteur <nom> ; au-delà, pas d'accord |

| Levier | Impact € | Pièce ou repère | Citable / interne |
|---|---|---|---|
| 1. Ancienneté | … | date la plus ancienne, source | citable (date) |
| … | … | … | … |

Séquence : appel → pause 24-48 h → offre écrite → contre-propositions → dernier mot (détail en annexe).
Plan de concessions : budget, pas, contreparties (annexe).
Message et fiche travaux : en annexe, brouillons à valider par l'investisseur.
À vérifier avant envoi : [points ouverts ; ligne de la formule de l'offre ; SCI].
```

