# Négociation (étape 8) et livrable (étape 9)

## Étape 8 - négociation

Skill `negoc` (`${CLAUDE_PLUGIN_ROOT}/skills/negoc/SKILL.md`), terrain achat immobilier (ses `references/immo_achat.md`),
avec les prix du **moteur**, **sur le montage de référence** du profil (`references/montages.md`). La section s'ouvre sur deux lignes :

1. **Sensibilité au loyer** : « +50 €/mois de loyer ⇒ +X € de plafond », X tiré de l'exécution
   `<slug>-loyer50-sortie.json` (`references/entree_moteur.md` §Sensibilité au loyer).
2. **Test de réalisme** : écart du plafond (FAI) au prix affiché, et à la valeur DVF de biens
   comparables **du même état** (€/m² des comparables retenus × surface, avec `n` et dates), chacun en
   € et en %. L'étude affiche l'écart ; elle ne fixe pas de seuil. Offrir au-delà d'une marge
   observée et sourcée est la décision de l'investisseur.

### Paliers

- **Prix plafond** = `prix_equilibre.realiste` : le prix **net vendeur** qui annule le cash-flow
  réaliste **avant impôt**, travaux compris. En `prix_plus_travaux`, le cash-flow ne dépend que de
  prix + travaux : **plafond = prix d'équilibre à travaux nuls − travaux**, exactement, et le
  **budget travaux supportable** au prix affiché = prix d'équilibre à travaux nuls − prix. Le
  convertir en FAI (honoraires acquéreur ajoutés) avant de le comparer au prix affiché. Si l'impôt du
  montage de référence (IS de la SCI, ou impôt du nom propre) est positif, le plafond après impôt est plus bas :
  le dire, avec l'impôt mensuel en regard.
- **Bien à restaurer** : avant toute étude complète, moteur à travaux nuls, budget supportable face
  au plancher de la classe de chantier (`renovation-estimator`). Budget sous le plancher : 🟥 quasi
  certain, l'étude complète ne se lance pas sans demande de l'investisseur.
- **Prix cible** : le prix net vendeur qui porte le cash-flow réaliste avant impôt au seuil de
  confort `S` (`immo-data/profil.json`, `seuil_confort_cf_mensuel`). En `prix_plus_travaux` : prix cible = `prix_equilibre.realiste` −
  `S` × `financement.emprunt` / `financement.mensualite_totale`, vérifié par une exécution du moteur
  à ce prix, puis converti en FAI.
- En mode `"fixe"`, le cash-flow ne dépend pas du prix : ni plafond ni cible. Le dire.
- **Ancrage** (première offre) : formule de `negoc`, ses `references/immo_achat.md` §Paliers ; travaux
  à 80 % du plancher faute de devis. Face aux paliers :
  - sous la cible : c'est la première offre ;
  - entre la cible et le plafond : encore la première offre, la cible n'étant pas atteignable sur
    pièces ; le dire ;
  - au-dessus du plafond : **pas d'offre chiffrée**. Le courrier reste en brouillon, prix en `[●]`,
    à n'utiliser que si le plancher du vendeur passe sous le plafond. Chiffrer au moteur les leviers
    qui y ramèneraient l'ancrage (loyer prouvé, taux, devis).
- **Plafond et cible par voie de travaux** de la classe visée (E ou D), avec le €/m² face aux ventes
  DVF ; une offre sous toutes les ventes voisines se dit indéfendable.
- **Loyer inconnu** (local, bail non publié) : ne pas l'inventer ; tabuler le plafond pour quelques
  loyers, et le loyer qui annule le cash-flow au prix affiché.
- **Leviers qui jouent contre l'acheteur** (DVF quand le bien est déjà sous le p25 ; médiane DVF dont
  le plancher du vendeur s'approche) : à 0, jamais retournés.
- **Vente DVF sur la même parcelle peu avant** : probable prix d'achat du vendeur, levier fort ; la
  citer par adresse, date et prix seulement (conditions d'usage de DVF).

### Ce qui améliore le rendement

Tableau des leviers chiffrés au moteur, au prix affiché et au plancher des travaux. Lignes : chaque
10 000 € de prix ; devis haut ou bas ; aléas du programme ; chaque option chiffrée ; loyer +50 €/mois ;
scénario meublé (logement de 2 pièces ou moins, si le profil le demande) ; taux du baromètre ; taxe foncière ± 500 €/an tant
que l'avis manque ; exonération de taxe foncière ; configuration écartée (entier ou par parties).
Colonnes : cash-flow obtenu, rendements brut et net, plafond (et cible).

### Courrier d'offre

Destiné à un tiers : `negoc`, ses `references/immo_achat.md` §Messages et `references/messages.md`
(accroche, pièces du vendeur, message bref et fiche jointe, contrôle avant envoi). Une règle n'a
qu'une source ; ici, seulement le lien avec l'étude :
- aucun argument de loyer, de rendement ni de cash-flow, aucune statistique DVF, prix en FAI **et** en
  net vendeur (honoraires inconnus : `[●]`), aucun tiret cadratin, brouillon validé par l'investisseur et jamais
  envoyé par Claude : `negoc`, ses `references/immo_achat.md` §Messages et `references/messages.md`
  §Avant envoi ;
- le message ne cite que des leviers comptés dans l'ancrage de l'étape 8 (§Paliers ci-dessus), sinon
  ils vont dans « À vérifier avant envoi » ;
- achat par une SCI à créer : `negoc`, ses `references/immo_achat.md` §Messages ; le montage et ses
  points pratiques, `references/montages.md`.

## Étape 9 - livrable

### Deux fichiers

- `immo-data/analyses/<slug>.md` : **300 lignes au plus** (`wc -l`), tableaux, verdict
  chiffré en tête.
- `immo-data/analyses/<slug>-annexes.md` : sections complètes des sous-agents, toutes les
  exécutions du moteur (nom de la sortie, entrée en clair, synthèse), `fiscalite.hypotheses` en
  entier, relevés et sources détaillées. Dans l'étude, chaque section d'étape 3 à 5 tient en
  **15 lignes au plus** et renvoie à l'annexe.

### Squelette, créé dès l'étape 1

```markdown
# <slug> - <type>, <commune>
> Étude en cours - étapes faites : 1 · annexes : [<slug>-annexes.md](<slug>-annexes.md)
> Verdict : à faire
> Bien : parcelle <IDU, `cle_bien.parcelle` de la fiche ; « à confirmer » si `cle_bien.fiable` est faux> · annonces : <identifiants, ceux du bloc de fin>
> Contrôle : `--verifier` rc <n>, le <AAAA-MM-JJ>

## Verdict
## Sommaire
## Le bien
## Marché
## Travaux
## Potentiel
## Rentabilité
## Montages
## Négociation
## Réglementaire
## Pièces et questions au vendeur
## À vérifier
## Glossaire
## Retours
## Sources et dates
<!-- immo:ligne {...} -->
```

- **Les 25 premières lignes gardent leur forme** : titre `# ` en ligne 1, bloc `>` dès la ligne 2
  (`immo_shortlist.py --check` y lit le verdict), et le verdict écrit `🟥 À écarter`,
  `🟨 À creuser`, `🟩 Go` ou `⬜ À qualifier` suivi de sa raison, dans le bloc `>` et dans la section Verdict. Le
  sommaire vient après la section Verdict.
- Chaque étape remplit sa section et met l'en-tête à jour (`étapes faites : 1, 2, 3r, 6`) ; une étude
  interrompue se reprend à la première étape absente. En fin d'étude : `> Étude <rapide | complète>
  du <AAAA-MM-JJ> - étapes faites : … ; sautées : … (raison)`. Une révision se note dans l'en-tête
  (« révisée le … : ce qui change ») ; mode `maj` : SKILL.md. La ligne « Bien » porte la parcelle dès l'étape 2 et
  chaque annonce liée trouvée ; la ligne « Contrôle », le code retour et la date du dernier `--verifier`.
- Une section sans objet le dit (« Travaux : non estimés en mode rapide »), elle ne disparaît pas.
- **Toute liste de biens** (comparables, pistes, doublons) porte pour chacun l'URL de l'annonce et
  son prix de négociation (plafond ou cible, ou « non chiffré »).
- **Rentabilité** : les 3 scénarios avant impôt, cash-flow et enrichissement séparés, le rendement
  brut recalculé à la main sur une ligne (loyer annuel / `acquisition.cout_total`), et la ligne du
  scénario meublé s'il existe.
- **Réglementaire** : la check-list ci-dessous.
- **Pièces et questions au vendeur** : `references/pieces_a_demander.md`, type du bien ; le message
  type à l'agent part seulement après validation de l'investisseur.
- **À vérifier** : les hypothèses de l'étude (dont la taxe foncière si l'avis manque) ; la liste
  complète `fiscalite.hypotheses` est dans l'annexe.
- **Glossaire** (5 lignes) : *plafond*, prix net vendeur à cash-flow réaliste nul ; *cible*, prix
  net vendeur au cash-flow de confort `S` ; *ancrage*, première offre ; *plancher des travaux*,
  borne basse du programme de référence ; *prix net vendeur*, prix hors honoraires d'agence à la
  charge de l'acquéreur.
- **Retours** : ce que l'investisseur a corrigé pendant l'étude (date, correction, section touchée), une ligne
  chacun ; à reverser ensuite au profil ou à la méthode. « Aucun » sinon.
- Les chiffres du foyer ne s'y écrivent jamais : renvoyer à `immo-data/foyer.json`, avec la date de ses
  valeurs.

### Check-list réglementaire

Une ligne par rubrique : valeur, source, date de lecture ; ou « non établi » et où chercher.

| Rubrique | Où la lire |
|---|---|
| PPRI de la parcelle | fiche, bloc `risques` (Géorisques) ; zone du plan au règlement du PPRI |
| Argiles (retrait-gonflement) | fiche, bloc `risques` (Géorisques) |
| Radon | fiche, bloc `risques` (potentiel radon de la commune) |
| ABF (abords d'un monument historique) | API Carto GPU, `assiette-sup-s`, servitude `ac1` |
| Zone du PLU et prescriptions | API Carto GPU, `zone-urba`, `prescription-lin`, `prescription-surf` ; règlement écrit sur le Géoportail de l'urbanisme |
| Permis de louer | délibération de la commune ou de l'EPCI (`references/pieces_a_demander.md`, base légale) |
| Assainissement | collectif ou non collectif : demander au vendeur ; non collectif, contrôle du SPANC (`references/pieces_a_demander.md`) |

Le bloc `urbanisme` de la fiche (étape 2) nourrit les lignes ABF, zone et prescriptions, et la ligne PPRI par la seule
enveloppe du plan (PM1, jamais sa zone) : le citer avec sa `portee`. L'appel direct ci-dessous ne sert qu'à défaut du bloc.
La fiche de la commune (`immo-data/communes.md`, étape 2) nourrit les lignes permis de louer, PPRI (plan qui
couvre la commune), argiles et radon (niveaux communaux) et assainissement (zonage, SPANC) ; à la parcelle, la fiche de
données ouvertes et les pièces du vendeur priment.

API Carto GPU de l'IGN, sans clé : `https://apicarto.ign.fr/api/gpu/<endpoint>`, paramètre `geom` en
GeoJSON, point BAN de la fiche (pour les prescriptions, un petit polygone autour du point :
± 0,00025°, convention de méthode, pas une règle de l'API). Une dérogation de transformation (CU L. 152-6-5, non relu par ce skill : à vérifier) n'est jamais comptée comme acquise.

### Bloc de fin, lisible par script

Dernière ligne de l'étude, sur une seule ligne, mise à jour à chaque étape et à chaque `maj` :

```
<!-- immo:ligne {"slug": "…", "date": "AAAA-MM-JJ", "mode": "rapide|complet", "verdict": "🟨", "quartier": "…", "type": "…", "surface_m2": 0, "prix_fai": 0, "prix_net_vendeur": 0, "eur_m2_fai": 0, "dpe": "E", "rendement_brut_realiste": 0.0, "cf_realiste_mensuel": 0, "montage": "sci_is", "plafond": 0, "cible": 0, "ancrage": 0, "ids_annonces": ["…"], "etapes_faites": ["1", "2"], "ligne_shortlist": {"rang": "T1", "quartier": "…", "type": "…", "surface": "…", "prix": "…", "eur_m2": "…", "dpe": "…", "rendement": "…", "cf": "…", "verdict": "🟨 **À creuser** …", "prix_cible": "…", "annonces": "[…](…)", "liens": "[…](analyses/<slug>.md)"}} -->
```

| Clé | Source |
|---|---|
| `slug`, `date`, `mode`, `etapes_faites` | l'étude (en-tête) ; `slug` : le nom du fichier sans `.md`, date comprise, et `date` celle de ce nom ; `mode` : `complet` range la ligne dans §1 de `shortlist.md`, `rapide` dans §1 bis |
| `verdict` | un de 🟩 🟨 ⬜ 🟥 ⬛ (vocabulaire de `shortlist.md`), le même que le premier émoji de verdict des 20 premières lignes de l'étude |
| `quartier`, `type`, `surface_m2`, `prix_fai`, `ids_annonces` | fiche d'annonce (`bruts/<slug>.json` : `localisation.quartier`, `bien`, `prix_fai`, l'identifiant tiré de `url` (motif `/(\d{6,})`), plus `annonces_liees[].id` quand la fiche le porte) ; surface retenue à l'étape 1 |
| `prix_net_vendeur` | `acquisition.prix_net_vendeur` de la sortie de base |
| `eur_m2_fai` | `prix_fai` / `surface_m2` |
| `dpe` | étiquette DPE retenue à l'étape 1 (base ADEME si elle contredit l'annonce) : une lettre de A à G, `null` si elle n'est pas communiquée ou le logement non soumis |
| `rendement_brut_realiste`, `cf_realiste_mensuel` | `scenarios.realiste.indicateurs.rendement_brut` et `.cash_flow_mensuel_avant_impot` de la sortie de base (avant impôt) ; le rendement est une fraction, comme dans le moteur (0,0482 pour 4,82 %) |
| `montage` | le `montage_reference` du profil : `"sci_is"`, ou le régime du nom propre (`"lmnp_reel"`…) dont le cash-flow est alors celui de ce régime ; `null` si aucun montage n'est évalué |
| `plafond`, `cible`, `ancrage` | prix **net vendeur** : `prix_equilibre.realiste` ; sortie de la cible ; ancrage de l'étape 8 |
| `ligne_shortlist` | les 12 cellules de la ligne de `shortlist.md`, en texte tel qu'il s'affiche (gras, liens markdown) : `quartier`, `type`, `surface`, `prix`, `eur_m2`, `dpe`, `rendement`, `cf`, `verdict`, `prix_cible`, `annonces`, `liens`, plus `rang`, **optionnelle** : le contenu de la colonne « # » (`**1**`, `T3`...), un tiret dans le tableau quand elle est absente. Pas de « Score » (retirée). `verdict` commence par l'émoji du bloc ; `liens` cite `analyses/<slug>.md` ; `cf` donne le cash-flow mensuel réaliste du `montage` du bloc, qu'il nomme (pour `sci_is`, celui de `cf_realiste_mensuel`, avant impôt) ; une barre verticale s'écrit `\|`, aucune cellule ne passe à la ligne |

Le bloc ne contient que des valeurs du bien, aucune du foyer. Il échappe à l'écriture en k€ : une
coïncidence avec un montant du foyer que `--verifier` y signale se dit à l'investisseur. `null` pour une valeur
absente (mode `rapide` sans ancrage, prix non communiqué, cible non calculée) ; toutes les clés sont présentes et
aucune clé inconnue n'est admise. JSON valide sur une ligne, guillemets doubles. La colonne « Score » de
`shortlist.md` est retirée : le bloc n'en porte pas.

Contrôle : `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_shortlist.py" --check` rend, par étude, `OK`, `NOTE` ou `ÉCHEC`. Il refuse un bloc absent
ou invalide, un `verdict` différent du premier émoji de verdict des 20 premières lignes de l'étude, et toute valeur
numérique non nulle du bloc introuvable dans le texte de l'étude (au format près : `87 400 €`, `87400`, `87,4 k€`, et sous
une unité qui convient à la clé : un rendement s'y lit en `%`, une surface en `m²`, un prix n'est pas un `€/m²`). Chaque nombre
du bloc s'écrit donc aussi dans l'étude.

### Ligne de `shortlist.md`

La ligne vit dans le bloc de fin (clé `ligne_shortlist`) : l'étude n'écrit pas `shortlist.md`. Une seule session
régénère §1 (blocs `complet`) et §1 bis (blocs `rapide`) par
`python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_shortlist.py"`, en 13 colonnes classées par verdict, puis cash-flow décroissant (`null` en
dernier), puis slug ; la colonne « # » est la cellule `rang` (un tiret si absente). Colonne « CF réal. (montage) » : le cash-flow du `montage` du bloc ; pour `lmnp_reel`,
`fiscalite.scenarios.realiste.regimes.lmnp_reel.cash_flow_mensuel_net_net` si `eligible` (et `evaluable`), sinon
« n/a » suivi de la raison.

### Tableur

Le générateur du tableur `.xlsx` n'est pas encore fourni par le moteur. D'ici là, la rentabilité se lit dans la
sortie du moteur et dans l'étude ; aucun tableur réécrit à la main (`yield-calculator` reste la spécification du tableur).

### Livrables dérivés

Présentation du projet, pense-bête de visite et one-pager, à la demande :
`references/presentation_visite.md`.
