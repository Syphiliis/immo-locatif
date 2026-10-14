---
name: lbc-scraper
description: "Extrait une annonce de vente immobilière Leboncoin (URL leboncoin.fr/ad/ventes_immobilieres/, texte collé ou captures) en fiche JSON structurée pour une analyse d'achat locatif. Déclenche-toi dès qu'une annonce de vente est à évaluer comme investissement (« analyse cette annonce », « qu'en penses-tu ? » + lien LBC). Ne concerne pas vos propres biens, ni une annonce de location que vous publiez. Première étape obligatoire de toute analyse d'investissement locatif. Étape 1 de `/immo` (toujours en premier) ; étape suivante : market-context. Pour l'étude complète d'un bien (rentabilité, montages, verdict), l'entrée est `/immo`, qui appelle ce skill à l'étape 1."
---

# LBC Scraper - extraction d'annonces Leboncoin

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Ce skill sert à transformer une URL Leboncoin en **fiche structurée** exploitable par les autres skills du pipeline d'étude d'un bien. Il est toujours le **premier maillon** de la chaîne d'analyse.

## Quand l'utiliser

- URL commençant par `https://www.leboncoin.fr/ad/ventes_immobilieres/`
- Mention d'une annonce immobilière à analyser
- Tout input du type « j'ai vu ce bien, qu'en penses-tu ? » avec un lien LBC

## Stratégie d'extraction

Leboncoin est **très protégé** (DataDome, challenges anti-bot). Tenter `requests` ou `httpx` échouera dans 95% des cas. Utiliser cet ordre de priorité :

### Option A - Navigateur (préférée)
Si un outil de navigation Chrome est disponible dans la session (extension Claude in Chrome ou navigateur intégré ; charger ses outils différés au besoin) : ouvrir l'URL, récupérer le texte visible de la page, puis la structure DOM si nécessaire.

### Option B - Contenu fourni par l'utilisateur
Si la nav Chrome n'est pas dispo, **demander à l'utilisateur de coller** :
- Le titre
- La description complète
- Les caractéristiques (surface, pièces, étage, DPE/GES, chauffage)
- Les charges mentionnées, la TF, les frais d'agence
- Les 5 à 10 photos qu'il juge les plus parlantes (humidité, cuisine, SdB, façade, combles)

### Option C - Capture d'écran
L'utilisateur peut fournir des screenshots ; tu les lis nativement (Read tool sur .png/.jpg).

Ne jamais tenter curl/wget/requests.get sur leboncoin.fr : cela viole les restrictions sandbox ET l'ASP anti-bot rend l'output inutile.

## Champs à extraire (obligatoires)

Remplir systématiquement ce schéma JSON. Si une valeur est absente, mettre `null` et noter dans `a_verifier`.

```json
{
  "url": "",
  "titre": "",
  "prix_fai": 0,
  "frais_agence_inclus": true,
  "type_vendeur": "particulier|agence|notaire",
  "date_publication": "YYYY-MM-DD",
  "age_annonce_jours": 0,
  "nb_baisses_prix": 0,
  "old_price": null,
  "dates_leboncoin": {
    "first_publication_date": null,
    "index_date": null,
    "lue_le": "YYYY-MM-DD"
  },
  "anciennete_reelle": {
    "date_la_plus_ancienne": null,
    "source": "",
    "jours": null,
    "dates": []
  },
  "annonces_liees": [],
  "localisation": {
    "commune": "",
    "code_postal": "",
    "quartier": "",
    "adresse_precise_ou_secteur": "",
    "lat": null,
    "lon": null,
    "coord_nature": null,
    "coord_source": ""
  },
  "bien": {
    "type": "appartement|maison|immeuble|terrain|local",
    "surface_habitable_m2": 0,
    "surface_carrez_m2": null,
    "surface_terrain_m2": null,
    "nb_pieces": 0,
    "nb_chambres": 0,
    "etage": null,
    "nb_etages_immeuble": null,
    "ascenseur": null,
    "annee_construction": null,
    "etat_general": "à rénover|rafraîchir|bon état|refait à neuf"
  },
  "energie": {
    "dpe_lettre": "A..G",
    "dpe_valeur_kwh_m2_an": null,
    "ges_lettre": "A..G",
    "ges_valeur_kgco2_m2_an": null,
    "date_dpe": null,
    "type_chauffage": "",
    "type_eau_chaude": ""
  },
  "charges_fiscalite": {
    "charges_copro_annuelles": null,
    "charges_copro_mensuelles": null,
    "taxe_fonciere_annuelle": null,
    "nb_lots_copro": null,
    "procedure_copro_en_cours": null
  },
  "description_brute": "",
  "photos_urls": [],
  "nb_photos": 0,
  "points_saillants": {
    "gare_mentionnee": false,
    "distance_gare_mentionnee_min": null,
    "cave": false,
    "parking_garage": false,
    "balcon_terrasse_jardin": false,
    "travaux_mentionnes": false,
    "humidite_ou_defauts_visibles": [],
    "meuble": false,
    "loue_actuellement": false,
    "loyer_actuel_si_loue": null
  },
  "a_verifier": []
}
```

## Enrichissements systématiques

Après extraction brute, **compléter** :

1. **Distance à la gare la plus proche** (en minutes à pied), ou au pôle de transport ou d'emploi que retient le rapport de marché de la zone (`immo-data/MARCHE.md`, grille de décision). Utiliser Google Maps / OpenStreetMap pour estimer depuis l'adresse/secteur. Hors des grandes villes, c'est souvent un **filtre primaire** de la demande locative : le seuil (par exemple moins de 15 min à pied, ou accès voiture rapide) se lit dans `immo-data/MARCHE.md`, pas dans ce skill. Si l'adresse précise manque, estimer à partir du quartier annoncé et marquer « estimation large ».

2. **Prix au m²** calculé : `prix_fai / surface_habitable_m2`.

3. **Âge de l'annonce** : la date affichée ne suffit pas (Leboncoin republie). L'ancienneté réelle et les annonces d'un même bien se relèvent selon § Identité et ancienneté ; c'est elle que `/negoc` utilise (`${CLAUDE_PLUGIN_ROOT}/skills/negoc/references/immo_achat.md`, levier 1).

4. **Red flags visibles dans la description** :
   - « vente rapide », « urgent », « succession » → motivation vendeur
   - « à rafraîchir », « travaux à prévoir » → sous-estimation possible des travaux
   - « copropriété en difficulté », « procédure » → danger majeur
   - « loué » → DPE F/G bloque la hausse de loyer, bail en cours à récupérer
   - **Signaux implicites de succession / vendeur non averti** (opportunité, même si le mot « succession » n'apparaît pas) : titre sec (« Vends maison F4 »), photos sombres ou au flash, description de 1-2 lignes, téléphone fixe ou absent, prix rond non aligné sur le marché. Ce profil = vendeur peu outillé, souvent pressé, marge de négociation supérieure. Le noter dans `a_verifier` comme hypothèse à confirmer.

5. **Risques Géorisques (systématique)**. Interroger `georisques.gouv.fr` sur l'adresse/parcelle (mention légale obligatoire en bas de chaque annonce LBC/SeLoger, mais rarement détaillée). Relever : **PPRI inondation** (plan de prévention du risque inondation de la commune, zone rouge/bleue = assurance chère ou refus, levier de négo majeur), retrait-gonflement des argiles, BASOL/BASIAS (pollution sols), radon, cavités. C'est gratuit, officiel, 30 secondes - et un PPRI découvert après signature coûte très cher.

6. **Contrôle Street View (pré-visite, 10 min)**. Avant toute visite, vérifier sur Google Street View ce que le grand angle des photos masque : vis-à-vis, immeuble d'en face, rue passante, parking ou activité bruyante voisine, état réel des trottoirs et façades du quartier (les photos d'annonce isolent le bien de son environnement). Noter tout écart entre l'annonce et la réalité du quartier.

## Identité et ancienneté

Deux questions avant toute étude : **depuis quand ce bien est-il réellement en vente**, et **est-il déjà en vente sous une autre annonce** (autre agence, particulier, autre surface ou DPE annoncés) ? Leboncoin republie les annonces, et un même immeuble peut avoir plusieurs annonces aux descriptions divergentes (un même immeuble peut apparaître sous plusieurs annonces aux surfaces et aux DPE différents, comptées comme candidats distincts par le crible).

Lecture au navigateur seulement, annonce par annonce (Option A ; `props.pageProps.ad` de `__NEXT_DATA__` sur la page déjà chargée) ; aucune requête directe à leboncoin.fr, aucune API non publique.

**Coordonnées** (`localisation.lat`, `localisation.lon`) :
- Remplies quand l'annonce les donne : attribut `street_view_url` (point posé par le vendeur, souvent un particulier) ou localisation précise de la carte de l'annonce.
- `coord_nature` dit ce qu'elles valent : `point_vendeur` (`street_view_url`, point posé sur le bien), `adresse_geocodee` (adresse retrouvée puis géocodée, BAN), ou `centre_commune` (localisation par défaut de Leboncoin : ne situe pas le bien). `coord_source` dit d'où elles viennent (attribut, carte, géocodage, avec la date de lecture).
- Un `point_vendeur` se géocode en inverse (BAN) avant de chercher l'adresse par l'ADEME ; un `centre_commune` ne sert ni au rayon DVF ni au dédoublonnage.

**Dates de Leboncoin** : enregistrées **telles quelles**, sans interprétation, dans `dates_leboncoin` (`first_publication_date`, `index_date`, et `lue_le`, date de lecture). `date_publication` reprend la date affichée et `age_annonce_jours` l'âge qui en découle : c'est un âge **affiché**, pas l'ancienneté réelle. `old_price` (prix précédent affiché) se recopie s'il existe, et `nb_baisses_prix` en découle.

**Ancienneté réelle** (`anciennete_reelle`) : estimée par la **plus ancienne** des dates disponibles, chacune avec sa source, dans `dates` (`{"date", "nature", "source"}`) :
- `date_leboncoin` : `first_publication_date` de l'annonce et de chaque annonce liée ;
- `dpe` : `date_etablissement_dpe` du DPE à l'adresse (bloc `dpe.a_l_adresse` de la fiche de données ouvertes, `${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_fiche_opendata.py`). Le DPE est obligatoire dès la mise en vente : sa date est une **borne probable** de la mise en vente, pas une preuve (un DPE peut précéder la vente de loin, ou avoir été refait) ;
- `crible` : première apparition de l'identifiant ou du bien dans un crible (`grep -l <id> immo-data/bruts/scan-lbc-*.md`, date du crible dans le nom du fichier) ;
- `annonce_liee` : date affichée la plus ancienne parmi les annonces d'un même bien (ci-dessous).
`date_la_plus_ancienne`, `source` et `jours` (jours écoulés jusqu'à la date de lecture) résument la plus ancienne. Aucune date trouvée hors celle de Leboncoin : le dire, et poser la question à l'agent (« depuis quand le bien est-il en vente ? »). Une date ancienne affichée par Leboncoin est fiable ; une date récente ne prouve rien.

**Annonces d'un même bien** (`annonces_liees`) : chercher, sur les cribles et au navigateur, les annonces de la même commune dont **les photos sont les mêmes** (façade, pièces), la **surface et le prix sont voisins**, ou le **point** (`street_view_url`) est le même. Chaque annonce liée est **listée**, jamais fusionnée sans contrôle : `{"url", "id", "vendeur", "prix", "old_price", "surface_m2", "dpe", "indices", "vue_le"}`, `indices` disant ce qui les relie (`photos`, `surface`, `prix`, `commune`, `point`). Les écarts entre annonces (surface, DPE, prix) se notent dans `a_verifier` : ils sont des questions au vendeur, et un levier quand le même bien est moins cher ailleurs. Un doute sur l'identité (photos différentes, point absent) se dit, le bien reste distinct.

## Sauvegarde

Écrire la sortie brute dans `immo-data/bruts/[quartier]-[prix-k€]-[YYYY-MM-DD].json`.

## Capture de l'annonce (recommandée)

Une capture de l'annonce garde la mémoire du bien une fois l'annonce retirée (photos, prix, texte). Dans le
navigateur (Option A), annonce ouverte, attendre 2 s puis prendre une capture d'écran ; la ranger dans
`immo-data/captures/<prefix>.png`, où `<prefix>` est le nom de la fiche sans `.json` (`piste-<id annonce>` pour un
bien ajouté aux pistes, `immo-data/pistes.json`). Regarder la capture : photos et prix visibles. Annonce déjà
retirée : pas de capture, le dire. Sans navigateur (Options B et C), une capture fournie par l'utilisateur se range
de même.

## Sortie attendue

1. Le JSON rempli
2. Un **résumé court** en français pour l'utilisateur : prix FAI, €/m², surface, DPE/GES, distance gare estimée, ancienneté réelle (date la plus ancienne et sa source), annonces liées d'un même bien, et chaque red flag majeur relevé (PPRI, copro en difficulté, DPE absent…)
3. Un passage explicite de relais au skill `market-context` avec les coordonnées et le prix pour lancer la comparaison DVF

## Garde-fous

- Ne jamais inventer un chiffre qui n'est pas dans l'annonce. Toute estimation (distance gare, année de construction typique, etc.) doit être explicitement marquée « estimation ».
- Le DPE est obligatoire dans toute annonce de vente ; son absence est un signal de vigilance (infraction possible du vendeur) : le réclamer.
- Si l'annonce est en dehors de la zone de recherche (décision `zone` de `immo-data/profil.json` : commune centre et communes listées), **prévenir l'utilisateur et demander confirmation** avant de lancer l'analyse complète.
