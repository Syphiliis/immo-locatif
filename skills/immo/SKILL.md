---
name: immo
description: "Point d'entrée de toute étude d'un bien à vendre pour le louer, dans la zone de l'investisseur (décision `zone` de immo-data/profil.json), même si l'utilisateur ne dit pas /immo : lien Leboncoin, texte d'annonce, adresse, « ça vaut le coup ? », « rentable ? », « combien offrir ? », « trie cette recherche ». Fiche, données ouvertes, marché, travaux, potentiel, rentabilité et fiscalité par le moteur Python du plugin, montages (montage de référence du profil, comparé à la SCI à l'IS et au nom propre), négociation, verdict sourcé ; modes rapide (tri), complet, maj et crible. Appelle lbc-scraper, market-context, renovation-estimator, value-add-analyzer et negoc, chacun pour une étape. NE couvre PAS vos propres biens, une annonce de location que vous publiez, ni les devis de travaux d'un bien que vous possédez déjà."
---

# /immo - étudier un bien locatif, de l'annonce au verdict

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Usage : `/immo <URL Leboncoin | adresse | texte d'annonce> [rapide | complet]`, `complet` par défaut ;
`/immo maj <slug> <notes ou chemins de pièces>` pour mettre une étude à jour (§Mode `maj`) ;
`/immo crible <URL de recherche Leboncoin>` pour trier une recherche sans étudier chaque bien :
`${CLAUDE_SKILL_DIR}/references/crible.md`.

| Mode | Étapes |
|---|---|
| `rapide` (tri) | 0, 1, 2, 3r, 6, verdict ; ni skill de marché ni sous-agent ; travaux à 0 |
| `complet` | 0 à 9 ; 3, 4 et 5 déléguées à des sous-agents |
| `maj` | relecture de l'étude, pièces et notes intégrées, sorties concernées relancées |
| `crible` | recherche lue au navigateur page par page, triée par `immo_crible.py`, pistes proposées : `references/crible.md` |

Livrable : `immo-data/analyses/<slug>.md` (300 lignes au plus, écrite au fil des étapes, close par le
bloc `<!-- immo:ligne … -->`, qui porte aussi la ligne de la shortlist) et `<slug>-annexes.md`.
`immo-data/shortlist.md` n'est jamais écrite par l'étude : elle se régénère depuis les blocs
(`python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_shortlist.py"`, lancé par une seule session, une fois
les études closes). À la demande : présentation, pense-bête de visite, one-pager
(`${CLAUDE_SKILL_DIR}/references/presentation_visite.md`).

Les références citées ci-dessous (`references/<fichier>.md`) sont dans `${CLAUDE_SKILL_DIR}/references/`.

## Première utilisation

1. **Dossier de données** : créer `immo-data/` dans le répertoire de travail (ou un autre dossier, désigné
   par la variable `IMMO_DATA_DIR`) et y copier les gabarits de `${CLAUDE_PLUGIN_ROOT}/templates/` :
   `profil.json`, `foyer.json`, `MARCHE.md`, `communes.md`, `params_local.json`, `shortlist.md` et
   `pistes.json`. Les valeurs des gabarits sont fictives : aucune ne sert telle quelle. `MARCHE.md` reste à
   remplir par `market-context` (étape marché) avant tout contrôle de fraîcheur (`immo_fraicheur.py`).
2. **Profil** (`immo-data/profil.json`) : remplir avec l'investisseur chaque décision (`zone` : commune
   centre, code INSEE, département, communes étudiées ; cible (les cibles acceptées par le crible sont listées dans le `_lisez_moi` de
   `templates/profil.json` ; `--types` du crible couvre les autres), budget, premier achat, apport, montage de
   référence, comptabilité de la SCI, seuil de confort, division, vacance, meublé), avec sa date et sa source.
   Supprimer l'exception d'annonce d'exemple du gabarit (identifiant manifestement factice), si elle y figure.
   Une décision absente se demande, elle ne se suppose pas.
3. **Foyer** (`immo-data/foyer.json`) : TMI, revenus d'activité, loyers et revenus fonciers existants,
   mensualités des prêts en cours, chacun avec `source` et `date`. Pour un premier achat, loyers et revenus fonciers
   existants valent 0 (un 0 choisi et daté, pas une inconnue). Il ne sert qu'au moteur (flag `--foyer`) ;
   ses valeurs ne s'écrivent dans aucune étude.
4. **Dépendances** : Python 3.11 ou plus, puis
   `python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/engine/requirements.txt"`.
5. **Zone** : le département du bien (droits de mutation) et sa commune (zone locative) se déclarent dans
   `${CLAUDE_PLUGIN_ROOT}/engine/src/immo/params.json` (ses entrées actuelles sont des exemples) ou dans
   `immo-data/params_local.json`, chaque entrée avec `source` et `verifie_le`. Un département absent (DMTO)
   arrête toujours le moteur, avec un message qui dit quoi ajouter et où. Une commune absente de la feuille des
   zones ne l'arrête que si le régime du bailleur privé est évaluable (`code_insee`, `immeuble_collectif`,
   `date_acquisition` et `bailleur_prive` présents dans l'entrée) ; sinon ce régime sort « non évaluable » et le
   moteur rend son code 0. L'étape marché (`market-context`) vérifie ces entrées et, si elles manquent, les cherche
   à la source officielle et les écrit, datées et sourcées ; en mode `rapide`, appliquer cette seule partie de
   `market-context` avant l'étape 6. **Aucun taux ni zonage inventé.**

## Règles de conduite

- Une étape sautée se dit, elle ne disparaît pas.
- Un tri ne rend jamais « Go » : 🟨 À creuser, 🟥 À écarter ou ⬜ À qualifier.
- Les skills du pipeline sont ceux de **ce plugin** (`${CLAUDE_PLUGIN_ROOT}/skills/<nom>/SKILL.md`, lus par
  chemin), jamais une copie homonyme installée ailleurs ; chacun pour son étape seulement, sans suivre ses
  relais vers le suivant.
- `yield-calculator` ne s'invoque pas : le moteur calcule. Le générateur du tableur `.xlsx` n'est pas encore
  fourni par le moteur ; d'ici là, la rentabilité se lit dans la sortie du moteur (le skill reste la
  spécification du tableur).
- Commandes depuis le répertoire de travail qui contient `immo-data/` (ou avec `IMMO_DATA_DIR`), avec le
  Python où les dépendances sont installées. Scripts : `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/<script>.py" …` ;
  moteur : `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_moteur.py" …`.
- Le moteur refuse `null` : une inconnue devient une hypothèse affichée (« À vérifier ») ; un 0 est
  une valeur choisie et dite.
- **Un verdict 🟥 n'écarte rien** : abandonner un bien est la décision de l'investisseur, prise après
  l'étude revue avec lui ; l'étude reste consultable.
- **Montage** : celui de `profil.json` (`montage_reference`), calculé par le moteur ; les autres montages
  (SCI à l'IS, meilleur régime du nom propre) sont des lignes de comparaison, jamais une recommandation sauf
  demande explicite de l'investisseur (`references/montages.md`).

## Étape 0 - contexte

- Modèle Opus ou au-dessus (fiscalité, courrier à un tiers) ; sinon le dire avant l'étape 6.
- `immo-data/profil.json` : **décisions en vigueur** de l'investisseur, une entrée par décision (zone,
  cible, budget, premier achat, montage de référence, comptabilité de la SCI, seuil de confort S, division,
  vacance, meublé), avec date, source et exceptions par annonce ; le champ `_lisez_moi` du gabarit en donne le
  sens. Elles priment sur les valeurs par défaut des références ; le skill y renvoie, il ne les recopie pas.
  Quand une décision change, reprendre les études qu'elle touche (mode `maj`). La commune du bien hors de
  `zone.communes` : le dire, et demander avant d'aller plus loin.
- **Fraîcheur des repères**, en tête de l'étude (tableau collé tel quel ; relancé après l'étape 2 avec
  `--fiche` et la fiche de données ouvertes) :
  `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_fraicheur.py"`. Code 1 : chaque repère `PÉRIMÉ`
  ou `NON COUVERT` se dit dans l'étude avec ce qu'il fragilise (loyer de la carte, comparables DVF,
  taux de compte courant « à vérifier ») ; ce n'est pas un arrêt. Code 2 : repère illisible, le dire.
- `immo-data/shortlist.md` : bien déjà étudié ? Repartir de son analyse (l'en-tête dit les étapes faites ;
  sans en-tête, elle se réécrit) et dire ce qui a changé.
- **Même bien, autre annonce** : `cle_bien.parcelle` (IDU de la parcelle cadastrale, étape 2) identifie le bien
  mieux que l'URL ou le prix. Une fiche de données ouvertes de même parcelle dans `immo-data/bruts/` est la
  trace d'une étude déjà faite : `grep -l '"parcelle": "<IDU>"' immo-data/bruts/*-opendata-*.json`. Sans
  fiche pour ce bien, la faire d'abord (étape 2). Seule une `cle_bien.fiable` vraie vaut identité ; sinon (adresse
  sans numéro, parcelle seulement la plus proche du point) c'est une piste à confirmer. Un bien sur plusieurs
  parcelles a plusieurs IDU : chercher aussi les parcelles voisines.
- **`shortlist.md`** : l'étude ne l'écrit jamais ; sa ligne est la clé `ligne_shortlist` du bloc de fin
  (13 colonnes, sans « Score »), et la régénération se fait par `immo_shortlist.py`. Une autre session
  sur le même slug : un seul écrivain par fichier, s'arrêter et le dire.
- Le foyer : le flag `--foyer immo-data/foyer.json` (étape 6) le donne au moteur. Aucune valeur de
  `foyer.json` ne se recopie dans le JSON du bien ni dans l'étude.

## Étape 1 - fiche

- URL, texte ou captures → `lbc-scraper` → `immo-data/bruts/<slug>.json`. Adresse seule :
  fiche minimale, inconnues à `null`, « à demander ».
- **Adresse** : sans numéro, la classer par le mode `--point`, avec le point `localisation.lat`/`lon` de la fiche :
  `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_fiche_opendata.py" --point <lat>,<lon> --surface <m²> --etiquette <A-G> --code-postal <cp> --out immo-data/bruts/<slug>-adresse-<AAAA-MM-JJ>.json`
  (`--date-dpe AAAA-MM-JJ` si l'annonce la donne, `--insee <code>` pour forcer la commune des DPE). Le JSON
  donne `candidats_ban` (les 5 adresses BAN les plus proches du point) et `candidats_dpe` (DPE de la commune dont
  la surface est à 10 % près de celle de l'annonce ;
  une ligne par adresse, son DPE le plus récent, par distance, 10 au plus). Code 2 : géocodage inverse en échec ;
  code 3 : DPE en échec ; `alertes` : code postal différent de celui du premier candidat, liste DPE tronquée.
  **Ce que vaut une distance dépend de `localisation.coord_nature`** (lbc-scraper) : `point_vendeur` ou
  `adresse_geocodee`, le candidat BAN le plus proche et un DPE à quelques dizaines de mètres sont de bons
  candidats ; `centre_commune` (localisation par défaut de Leboncoin), le point ne situe pas le bien : aucune
  distance ne départage, seules la surface, l'étiquette, la date et le GES du DPE concordent ou non.
  Concordances à vérifier à la main : date, GES, type, énergie primaire recalculée (électricité à 2,3 pour un DPE
  d'avant 2026, 1,9 depuis le 01/01/2026, 1,7 au 01/01/2027 selon l'arrêté du 19/08/2026, vu par recherche web, à
  vérifier au Journal officiel). Écrire « adresse probable, à confirmer par l'agent ».
- **DPE et surface** : la lettre se lit dans la base ADEME (`etiquette_dpe`), pas sur l'image de
  l'annonce ; la surface du DPE prime sur celle de l'annonce quand elles divergent (bien mixte
  compris), et l'écart est un levier ; sans DPE, le loyer se calcule sur la plus prudente des
  surfaces annoncées.
- `<slug>` = `[quartier]-[prix-k€]-[AAAA-MM-JJ]`, la commune à défaut de quartier. Sans prix :
  `[quartier]-prixnc-[AAAA-MM-JJ]`, l'étude s'arrête après l'étape 3 (ou 3r), ⬜, sans moteur.
- **Prix net vendeur** : honoraires vendeur ou sans agence → prix affiché, `frais_agence_acquereur`
  à 0 ; honoraires acquéreur → leur montant, et le FAI moins ce montant (un taux : vérifier sa base
  sur l'annonce) ; inconnus → à demander, hypothèse affichée. Avec des honoraires vendeur, le
  « prix net vendeur » du moteur est donc le FAI, pas ce que touche le vendeur (FAI moins
  honoraires) : le courrier donne les deux (étape 8).
- **Un bien vendu en un lot reste un bien.** Ses parties s'appellent comme dans l'annonce
  (« partie 1 », « partie 2 »), jamais « logement A / B », qui se lit comme deux biens. Déjà divisé
  en parties indépendantes, il s'étudie **entier et par parties** (le loyer en dépend) et
  l'investisseur tranche (`profil.json`, clé `division`) ; la configuration écartée se chiffre en levier
  (étape 8).
- **Créer l'analyse maintenant** : sections fixes de `references/negociation_livrable.md`, chacune
  « à faire », en-tête `> Étude en cours - étapes faites : 1`. Chaque étape remplit sa section et
  met l'en-tête à jour : c'est ce qui rend l'étude reprenable.

## Étape 2 - données ouvertes

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_fiche_opendata.py" --adresse "<adresse>" --out immo-data/bruts/<slug>-opendata-<AAAA-MM-JJ>.json
```

- Code 2 : géocodage en échec, score sous 0,5 ou aucun candidat dans le code postal de l'adresse (le message de
  `erreurs` le dit), blocs à `null`. Le dire, demander l'adresse exacte.
- Code 3 : fiche **partielle**, JSON écrit : le géocodage tient, au moins un bloc a échoué (une ligne
  « bloc : message » par bloc sur stderr). Le dire en citant les blocs. Une adresse sans numéro donne
  toujours le code 3 (`dpe.a_l_adresse` et `risques.adresse` en erreurs) : attendu, pas une panne. Un cadastre en
  échec met aussi `batiment` en erreur (« parcelle inconnue (cadastre en échec) »). Un 429 ou une connexion
  réinitialisée est déjà rejoué par le script ; s'il persiste, relancer plus tard.
- Sans numéro, le point géocodé est la rue ou la commune (`geocodage.type`) : DVF centré dessus, DPE
  et risques « à l'adresse » en `erreurs`. Le dire, demander l'adresse exacte. `urbanisme`, `batiment` et
  `copropriete` sont lus avec l'alerte « point sur la rue » (rue ou lieu-dit) et NON lus (blocs `null`) avec l'alerte
  « point de commune : urbanisme, bâtiment et copropriété non lus » (centre de la commune). Une telle fiche est
  **provisoire** : elle se relance sur l'adresse confirmée (candidats : mode `--point` ci-dessus) avant le verdict ;
  un verdict rendu sur elle se dit provisoire.
- Commune incertaine (« à 12 min de <ville> ») : fiche sur la commune affichée, à dire ; demander la
  commune et l'adresse.
- Lire `erreurs` (ce qui a échoué : un bloc `null` se signale, aucune estimation ne le remplace) **et**
  `alertes` (ce qui borne la lecture sans avoir échoué : fenêtre DVF courte, DPE tronqués) ; l'analyse dit
  les deux. Une fiche sans clé `alertes` (version antérieure du script) : le dire, sans en conclure que rien
  n'est à signaler.
- Commune et identité du bien : donner l'adresse AVEC son code postal. `geocodage.controle_commune` dit « code
  postal <cp> concordant » ou « non fait » (alerte `geocodage` : pas de code postal, premier résultat pris tel
  quel) ; `rang_candidat` supérieur à 1 (alerte) : les résultats mieux classés étaient hors de ce code postal.
  `cadastre` : `idu`, `section`, `numero`, `contenance_m2` (lue comme des m², unité non documentée par l'API) et
  `methode` ; « parcelle la plus proche du point (point hors parcelle), à confirmer » (alerte `cadastre`,
  `contenance_m2` null) veut dire qu'aucune parcelle ne contient le point. `cle_bien` = `{parcelle,
  identifiant_ban, fiable}` : `fiable` n'est vrai que pour un numéro de rue ET une parcelle qui contient le point ;
  sinon l'identité est une piste (étape 0). `fiable` est aussi faux quand la parcelle est dans une autre commune que le
  géocodage (alerte `cle_bien`).
- Cadre réglementaire, bâtiment et copropriété : blocs `urbanisme`, `batiment` et `copropriete`, lus à la parcelle du
  `cadastre`. Des sources brutes, à citer avec leurs limites :
  - `urbanisme` : `zone` (libellé, document, date d'approbation tirée de l'identifiant du document, lien du règlement
    écrit), `prescriptions`, `servitudes`. `abords_monument_historique` = servitude AC1 (ABF). `plan_prevention_risques`
    = servitude PM1, qui est l'**enveloppe** du plan de prévention des risques et **pas la zone** (rouge, bleue) : la
    zone se lit au règlement du plan. Les prescriptions sont lues sur un carré d'environ 37 × 56 m autour du point
    (`portee` : à confirmer sur le règlement) et une liste vide ne prouve pas l'absence de servitude. Commune au RNU
    (`commune.rnu`, alerte) : pas de zone ni de prescription de PLU, les servitudes restent à lire. Alerte « document
    opposable peut-être non publié » : à vérifier en mairie.
  - `batiment` (BDNB) : année, murs, logements, niveaux et usage de chaque groupe de bâtiments de la parcelle, en
    valeurs **brutes** que le DPE ou l'annonce peuvent contredire : dire l'écart, ne pas trancher.
    `usage_mixte_indice` null = champ non renseigné, pas « pas d'usage mixte » (l'usage mixte n'est pas publié en accès
    ouvert). `parcelle_principale` se cite tel quel, sans l'interpréter.
  - `copropriete` (RNIC) : `correspondance` `parcelle` = immatriculée sur la parcelle ; `aucune` = **l'absence du RNIC ne
    prouve pas l'absence de copropriété** (une copropriété peut être immatriculée sur une parcelle voisine, à quelques dizaines
    de mètres) ; `parcelle inconnue` = aucune correspondance possible. `voisines` : copropriétés immatriculées à moins de
    50 m, un indice et non un statut.
  - Parcelle seulement la plus proche du point (alertes « bâtiment d'une parcelle à confirmer » et « copropriété d'une
    parcelle à confirmer ») : ces deux blocs décrivent peut-être une parcelle voisine, à confirmer avant de les citer.
- Fraîcheur DVF : `dvf.parametres.derniere_mutation` et `annees_absentes` disent jusqu'où va DVF. Alerte
  « fenêtre effective de N mois sur M demandés » (N < 18) : les ventes récentes manquent et la médiane ne
  dit pas le marché d'aujourd'hui, à écrire tel quel. DVF est mis à jour en avril et en octobre
  (data.gouv.fr, consulté le 07/10/2026 ; dernière mise à jour le 05/04/2026) : une fiche écrite avant une
  publication se relance après elle (mode `maj`).
- `dvf.atypiques` : nombre de ventes au €/m² atypique par type (`null` sous le minimum de ventes) ;
  un comparable `atypique` se cite avec son drapeau, jamais comme repère central.
- Immeuble de rapport : `dvf.immeubles` liste les ventes de la COMMUNE du bien (60 mois, option
  `--fenetre-immeubles-mois`, 0 pour la couper) à 2 locaux bâtis ou plus dont un logement, que
  `dvf.comparables` exclut. Par vente : `valeur_fonciere` (prix global), `nb_logements`,
  `nb_locaux_activite`, `eur_m2_bati` (surface bâtie totale), `eur_par_logement` (part des locaux
  d'activité incluse), `distance_m`, `parcelles`, `surface_habitation_m2` et `surface_activite_m2`, `atypique`
  (motifs `bloc` : 20 logements ou plus ; `activite_dominante` : plus d'activité que d'habitation) et
  `dans_reference`. `ventes` : les 20 plus proches, sans rayon ; `compteurs` : vues, retenues, écartées par motif.
  **La seule médiane citable est `dvf.immeubles.reference`** (règle de la méthode) : ventes à 3 logements
  ou plus, sans vente atypique, une seule vente par groupe de parcelles (la plus récente). Citer `n`,
  `mediane_eur_m2_bati` et `mediane_eur_par_logement` (`null` sous 3 ventes, avec `raison_mediane_absente` : la
  dire), `ecartees` (`moins_de_3_logements`, `atypique`, `revente_meme_parcelle`) et `criteres` (les seuils).
  **Ne jamais citer la médiane de `statistiques`** : elle porte sur toutes les ventes retenues, maisons à 1 ou 2
  logements, sites industriels, résidences vendues en bloc et reventes d'un même immeuble comprises. L'écart
  entre les deux peut être important : seule la référence se cite.
  Lire `nb_logements` et `types_locaux` de chaque vente pour juger d'un cas limite.
- Conditions d'usage : DVF, ni réidentification ni indexation (la fiche reste dans `immo-data/`, privé, jamais
  publiée) ; loyers, citer « Estimations ANIL, à partir des données du Groupe SeLoger et de leboncoin ».
- **Fiche de la commune** : lire la seule section de la commune dans `immo-data/communes.md`
  (`sed -n '/^## <Commune> (<code INSEE>)$/,/^## /p' immo-data/communes.md` ; le fichier peut être gros).
  Ses rubriques sont sourcées et datées (permis de louer, document d'urbanisme, PPRI, argiles et radon, taxe
  foncière en taux et en montants observés, assainissement, ABF, INSEE, gare, notaires) : elles nourrissent la
  check-list réglementaire (`references/negociation_livrable.md`) et le ratio de taxe foncière de la même commune
  (`references/entree_moteur.md`). Une rubrique lue il y a plus de 6 mois, ou marquée en réserve, se relit à sa
  source avant usage ; « non trouvé » se dit tel quel ; une commune absente du fichier se dit (`market-context`
  peut la remplir).

## Étape 3r - loyer et prix depuis la fiche (`rapide`)

Carte des loyers : loyers d'annonce, charges comprises, en €/m²/mois ; prendre la typologie la plus
proche dans `loyers` (`appartement_t1_t2`, `appartement_t3_plus`, `maison`).

- Loyers par la commande, qui applique la correction de surface (`engine/src/immo/loyer.py` ; formule et cas
  d'extrapolation : `references/entree_moteur.md` §Correction de surface) :
  `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_entree.py" loyer-3r --fiche <fiche de données ouvertes> --serie <série> --surface <S> --charges <charges récupérables>`
- **Loyer réaliste HC** = loyer au m² corrigé × surface habitable − charges récupérables estimées
  (hypothèse affichée). **Optimiste** : le même calcul à `ip_haut`. **Pessimiste** : le réaliste
  − 10 %. Citer `maille`, `n`, `millesime` et l'élasticité ; drapeau `EXTRAPOLATION` dit dans l'étude.
- **Décote** : prix net vendeur au m² face à `dvf.par_type.<Maison|Appartement>.mediane`, avec
  `p25`, `p75` et `n` en regard (`mediane` nulle sous 2 ventes : le dire).
- Pourquoi : la carte et DVF suffisent à trier ; le contrôle terrain reste au mode `complet`.
- Travaux à 0 (« hors travaux ») : le résultat est un majorant. 🟥 seulement si le rendement brut du
  moteur reste sous 6 % **même au loyer optimiste**, sans levier visible dans l'annonce.

## Étapes 3 à 5 - sous-agents (`complet`)

A (marché, `sonnet`), B (travaux, `sonnet`) et C (potentiel en mode profil, `opus`) partent **dans le
même message**, chacun avec le gabarit de `references/sous_agents.md` : bloc « Décisions en vigueur »
(`immo-data/profil.json`) en tête, « Hors décision : 3 lignes au plus » en fin. Chacun écrit sa section au fil
de l'eau dans `<scratchpad>/<slug>-etape<N>.md` et rend au plus 15 lignes sourcées et datées.

**Ne pas attendre** un sous-agent lent : avancer moteur, montages et négociation, section « en
cours » ; un sous-agent « stalled » se juge sur son fichier de scratchpad avant toute relance.

**Vérifier avant d'utiliser** : un comparable DVF cité existe dans la fiche ; un loyer de comparable
qui fonde le réaliste a été relu à la source, texte entier (`market-context` §« Relevé de loyers ») ; le
loyer est dans l'intervalle ANIL, ou l'écart s'explique ; la classe de chantier colle aux photos et au
DPE ; **un audit énergétique du vendeur prime sur le modèle DPE** de l'étude (dire l'écart). Les
scénarios de `references/entree_moteur.md` priment sur les bornes de loyer d'un sous-agent. Les sections
entières vont dans l'annexe, un résumé de 15 lignes au plus dans l'étude. Le moteur prend la borne haute
du **programme** de référence (`renovation-estimator`), sans les aléas ; la borne basse, les aléas et les
options vont en sensibilité.

## Étape 6 - moteur

JSON d'entrée selon `references/entree_moteur.md`, dans le scratchpad, avec le bloc `sci` et **sans
bloc `foyer` ni `fiscal.tmi`** (le moteur avertit s'il les trouve ; une pondération bancaire des loyers
se règle dans `foyer.json`). Taux d'emprunt daté. Département et commune
présents dans `params.json` ou `immo-data/params_local.json` (§Première utilisation, point 5).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_entree.py" controle --bien <scratchpad>/<slug>-moteur.json --profil immo-data/profil.json --annonce <id>
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_moteur.py" --bien <scratchpad>/<slug>-moteur.json --foyer immo-data/foyer.json > <scratchpad>/<slug>-base-sortie.json
python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_synthese.py" --sortie <scratchpad>/<slug>-base-sortie.json
```

- **`controle` d'abord**, sur chaque entrée nommée : code 1 = l'entrée contredit le profil (vacance
  hors profil sans `--justification-vacance`, comptabilité dans le cash-flow d'une SCI quand le profil
  l'exclut) ; corriger l'entrée, ne pas lancer le moteur. Une justification de vacance est un fait du bien
  (colocation, forte rotation), jamais le taux INSEE. L'avertissement « premier achat » se reprend dans
  l'étude.
- **Moteur arrêté sur la zone** (département ou commune absents des paramètres) : ne pas contourner ;
  ajouter l'entrée manquante, sourcée et datée, dans `immo-data/params_local.json` (§Première utilisation),
  puis relancer.
- **Seule la synthèse se lit**, jamais la sortie entière ; une extraction ciblée de clés du bien
  est permise, jamais `hcsf.entrees_foyer` ni `effet_foyer.impot_foyer_*`. Code 2 : lire stderr,
  corriger l'entrée.
- **Foyer absent ou refusé** (`foyer.json` manquant ou incomplet, exécution refusée) : ne pas le
  contourner ; chemin écrit dans `references/entree_moteur.md` §Quand le foyer manque (moteur sans foyer, ce
  qui manque alors, commande à proposer à l'investisseur).
- **Une sortie par cas, nommée** (`<slug>-<cas>-sortie.json`, la base comprise :
  `<slug>-base-sortie.json`, que le contrôle `--verifier` ci-dessous prend) : `base`, `loyer50`
  (sensibilité au loyer), `meuble-<partie>` (logement de 2 pièces ou moins, si `profil.json` le demande),
  cible, leviers, `travaux-bas`, `travaux-aleas` (borne haute du programme plus les aléas) et
  `option-<nom>` (sensibilités des travaux). Chaque chiffre d'un livrable vient d'une sortie nommée.
  Si le plugin a été mis à jour depuis les exécutions, les relancer toutes et comparer avant de livrer.
- **Budget travaux supportable** (section Travaux, face au programme) : en `prix_plus_travaux`,
  `travaux + prix_equilibre.realiste − prix_net_vendeur`, lus dans la sortie de base ; négatif : « le
  bien ne supporte aucuns travaux au prix demandé » ; en `fixe` : « non calculable (financement
  fixe) ». Seconde ligne au seuil de confort `S` : `travaux + prix de la sortie cible − prix_net_vendeur`.
  Écrire, pour chacune, ses écarts à la borne basse, à la borne haute, et à la borne haute plus les aléas.
- Entrée, sortie et synthèse (chiffres du foyer) restent au scratchpad, telles quelles.
- **Revente et TRI** : l'entrée de base porte le bloc `sortie` (`references/entree_moteur.md` §Bloc `sortie`,
  chaque hypothèse sourcée et datée) ; sans lui, « revente non chiffrée ». La synthèse a une section « Sortie »
  (TRI, VAN, plus-value, IS de la cession, boni net, reçu à la sortie, par scénario) et la CLI écrit sur stderr
  « Sortie à N ans (SCI à l'IS) : TRI pessimiste … %, réaliste … %, optimiste … % ; VAN … ». Les raisons, seules,
  s'extraient à part :
  `python3 -c "import json,sys; d=json.load(open(sys.argv[1]))['sortie']; [print(s, *d[s]['raisons'], sep='\n  ') for s in d]" <scratchpad>/<slug>-base-sortie.json`.
  L'étude cite le TRI des trois scénarios avec leurs `raisons` (hypothèses « à vérifier » reprises dans
  « À vérifier », total apporté en compte courant s'il y en a un).

## Étape 7 - montages (`complet`)

Lire `references/montages.md` : montage de référence du profil, les autres en lignes de comparaison.

## Étapes 8 et 9 - négociation et livrable

Lire `references/negociation_livrable.md` (sensibilité au loyer et test de réalisme en tête,
paliers, étude courte, check-list réglementaire, bloc de fin) et `references/pieces_a_demander.md`
(pièces par type de bien, taxe foncière d'abord). Livrables dérivés, à la demande :
`references/presentation_visite.md`.

## Mode `maj`

`/immo maj <slug> <notes ou chemins de pièces>` :
1. Lire l'étude par son en-tête (étapes faites, révisions) et le bloc `immo:ligne`.
2. Intégrer les notes de visite, les réponses de l'agent et les pièces données par chemin. Les
   pièces se rangent dans `immo-data/pieces/<slug>/` (privé, jamais partagé) ; une pièce remplace
   l'hypothèse qu'elle couvre (avis de TF, audit, diagnostics, baux, devis), citée avec sa date.
3. Relancer les sorties nommées que ces entrées touchent, puis `--verifier`.
4. Mettre à jour l'en-tête (« révisée le … : ce qui change »), les sections touchées, la section
   Retours et le bloc de fin (dont `ligne_shortlist`) ; régénérer les dérivés (garde-fou 8).

## Avant la version finale de l'analyse

```bash
for f in <slug> <slug>-annexes; do for s in <scratchpad>/<slug>-*-sortie.json; do python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_synthese.py" --sortie "$s" --verifier immo-data/analyses/$f.md >/dev/null || echo "ÉCHEC $f $s"; done; done
f=immo-data/analyses/<slug>.md; wc -l < $f; tail -1 $f | sed -E 's/^<!-- immo:ligne (.*) -->$/\1/' | python3 -m json.tool >/dev/null && echo "bloc de fin OK"
```

Étude de 300 lignes au plus, bloc de fin en JSON valide sur la dernière ligne. Puis
`python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_shortlist.py" --check` : lire les lignes de l'étude
(`ÉCHEC` : corriger le bloc ou le texte ; les autres études sont à d'autres sessions).

→ `rc=0` exigé **contre chaque sortie citée**, et sur chaque livrable dérivé (présentation) ; sans
moteur, `--verifier` seul ; une présentation `.html` (ou le HTML d'un PDF) se passe telle quelle. Code retour et
date s'inscrivent dans la ligne « Contrôle » de l'en-tête. Le contrôle couvre aussi le montant ×12 d'une valeur
mensuelle du foyer. Un montant du bien égal par hasard à l'un d'eux est signalé aussi : l'écrire en k€
(« ≈ 1,2 k€ »). Avertissement « plus de 300 lignes » : le détail part dans `<slug>-annexes.md`. Les numéros
d'article et les identifiants (DPE, mutation DVF) ne sont pas contrôlés. Puis le rendement brut recalculé à la
main, sur une ligne : loyer annuel / `acquisition.cout_total`.

## Garde-fous

1. Aucun chiffre inventé ; une absence se dit ; une hypothèse se signale comme telle.
2. Tout chiffre de marché ou de fiscalité porte sa source et sa date.
3. Jamais un seul scénario ; cash-flow et enrichissement ne s'additionnent pas.
4. Rendement brut du moteur sous 6 % sans levier activable : 🟥 À écarter, quasi automatiquement
   (`yield-calculator`, §Garde-fous).
5. Aucun chiffre du foyer dans une étude ni dans un livrable : renvoyer à `immo-data/foyer.json` et à la
   date de ses valeurs, rien n'en est recopié. `--verifier` le contrôle.
6. Rien ne part vers un tiers sans validation explicite de l'utilisateur.
7. Aucun scraping : Leboncoin, MeilleursAgents et SeLoger se lisent au navigateur, page par page, comme un
   utilisateur ; aucune requête directe ni API non publique ; le crible suit `references/crible.md`.
8. Un livrable dérivé (présentation, pense-bête) ne porte que des chiffres de l'étude ou d'une sortie
   nommée, et se régénère quand l'étude change.
