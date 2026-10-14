# Crible Leboncoin : cribler une URL de recherche, puis étudier les meilleurs (`/immo crible <URL>`)

`/immo` étudie **un bien à la fois**. Le crible part d'une **URL de recherche** (`leboncoin.fr/recherche?…`, pas une
annonce) ou d'une zone à passer au peigne, trie des dizaines d'annonces **sans les ouvrir**, puis propose les 5 à 8
meilleures pour `/immo rapide`.

Répartition : la **lecture** se fait au navigateur, par vous, page par page ; le **tri** se fait par
`immo_crible.py` (`${CLAUDE_PLUGIN_ROOT}/engine/scripts/`), qui ne lit que des fichiers JSON et n'a aucun accès réseau (un test le garde). Le script
**propose** : il n'écrit ni `immo-data/pistes.json` ni `immo-data/bruts/` (refus, code 2).

## Règles de lecture (garde-fou 7 du skill)

- Navigateur intégré, comme un utilisateur : une page à la fois, à son rythme. **Aucune requête directe** à
  leboncoin.fr depuis un script, aucune API non publique.
- Vérification anti-robot affichée par Leboncoin : **ne pas la résoudre**, s'arrêter et le dire.
- Les pages lues vivent dans le scratchpad de la session, jamais publiées. Les jeux de test du script sont fictifs
  (`engine/tests/fixtures/immo_crible/`).

## Structure lue (page de résultats)

Chemin : `props.pageProps.searchData` de `__NEXT_DATA__` ; clés : `ads`, `total`, `total_all`, `total_pro`, `total_private`,
`max_pages`, `pivot`, … Une annonce de `ads` porte :

| Champ | Contenu |
|---|---|
| `list_id` | identifiant, nombre à 10 chiffres ; `url` = `https://www.leboncoin.fr/ad/ventes_immobilieres/<list_id>` |
| `subject`, `body` | titre ; **`body` est vide** dans une page de résultats (la description exige l'annonce : `props.pageProps.ad.body`) |
| `price` | **tableau** `[prix]` (euros) ; `price_cents` = prix × 100 |
| `location` | `city`, `city_label`, `zipcode`, `department_id`, `department_name`, `region_id`, `region_name`, `country_id`, `lat`, `lng`, `source`, `is_shape`, `type`, `origin_type`, `provider`, `feature` |
| `attributes` | liste de `{key, value, values, value_label, generic}` ; **valeurs en chaînes** ; clés utiles ci-dessous |
| `first_publication_date`, `index_date` | `AAAA-MM-JJ hh:mm:ss` |
| `owner` | `type` (`pro` ou `private`), plus des champs d'identité que le crible ne lit pas |

**Attributs lus par le script** : `real_estate_type` (1 « Maison », 5 « Autre » ; un autre code se lit tel quel), `square`,
`energy_rate` (DPE, classes A à G seules), `old_price` (prix avant baisse), `property_tax` (taxe foncière),
`fees_at_the_expanse_of` (honoraires : `seller` ou `buyer`), `fees_price` et `immo_sell_type` (type de vente). **Gardés par la
projection pour l'étude, non lus par le script** : `ges`, `price_except_fees`, `rooms`, `building_year`, `heating_mode`,
`annual_charges`. Autres clés présentes, ni gardées ni lues : `annual_energy_budget_min/max` (retrouver l'adresse par l'ADEME, voir
le skill `lbc-scraper`), `bedrooms`, `nb_bathrooms`, `nb_shower_room`, `nb_parkings`, `nb_floors_building`,
`elevator`, `floor_number`, `floor_display`, `land_plot_surface`, `heating_type`, `global_condition`, `outside_access`,
`specificities`, `estimated_notary_fees`, `estimated_total_property_price`, `price_per_square_meter`, `negotiating_fees_percentage`,
`security_deposit`, `lease_type`, `mandate_type`, `custom_ref`, `external_ad_id`, `district_*`, `virtual_tour` et des clés de
vendeur. `immo_sell_type` : `old` pour l'ancien, `new` pour le neuf ; `type_real_estate_sale` : `ancien`. Les autres valeurs
d'`immo_sell_type` ne sont pas documentées (réglage du script : il ne code que `new`, plus toute valeur contenant « viager »).

**`location.source` dit ce que vaut le point** : `address` (particulier, point précis) ou `city` (professionnel,
`is_shape` vrai : point **décalé** autour du centre de commune, distinct d'une annonce à l'autre, donc **jamais précis**).

## Pièges (chacun a sa ligne, `grep -n` au rapport)

- **Lecture** : `JSON.parse(document.getElementById('__NEXT_DATA__').textContent).props.pageProps.searchData.ads` ; 35 annonces par page, page suivante `&page=N`, nombre de pages dans `max_pages`.
- **Date republiée** : `first_publication_date` est souvent celle d'une republication (une annonce vue en avril s'affichait en septembre) ; seule une date ancienne affichée est fiable, une date récente ne prouve rien ; le script la note comme date affichée, jamais comme ancienneté ; l'ancienneté réelle se demande à l'agent (`lbc-scraper`, § Identité et ancienneté).
- **`__NEXT_DATA__` périmé** après un filtre posé dans l'interface : la page se met à jour côté client, `__NEXT_DATA__` garde la page chargée avant : le volume lu ne correspond plus au volume affiché ; recharger l'URL obtenue, navigation normale, avant de lire.
- **Comptage par identifiant** à 10 chiffres (`\b[0-9]{10}\b`), jamais par motif d'URL : des annonces exclues sont écrites sans URL. Le script compte par ensemble d'identifiants, normalisés en 10 chiffres.
- **Neuf de constructeur** : les « Maison N pièces », DPE A, sans honoraires, sont du terrain plus maison. Écartés comme « neuf probable » : `immo_sell_type` = `new`, **ou**, quand aucun `immo_sell_type` n'est renseigné, la règle empirique suivante : titre « Maison N pièces », DPE A, et **aucun honoraire à la charge de l'acquéreur**, c'est-à-dire ni `fees_at_the_expanse_of` = `buyer`, ni `fees_price` positif (donc aussi une annonce sans aucune clé d'honoraires, ou à honoraires `seller` nuls : forme courante chez un professionnel). **Réglage du script** : un `immo_sell_type` renseigné et différent de `new` l'emporte sur la règle de titre (le script ne code pas le littéral `old` : la valeur exacte d'un ancien n'est pas attestée, seul compte « renseigné et différent de `new` ») ; un type de vente vide est un type non renseigné. Ce que « sans honoraires » veut dire dans cette règle n'est pas tranché : à confirmer sur un vrai neuf de constructeur.
- **Viager** : le prix affiché est le bouquet, pas le prix du bien (rendement absurde, tête de classement). Écarté comme « viager probable » sur « viager », « viagers » ou « viagère » dans le titre ou la description ; un viager dont le titre ne le dit pas (« Maison 5 pièces 97 m² ») passe : la valeur de `immo_sell_type` d'un viager n'est pas documentée.
- **Bien mixte** : la surface annoncée compte les locaux : la surface habitable du DPE ADEME peut en être une fraction, et la « décote » apparente disparaît une fois la bonne surface prise ; drapeau « comparer à la surface du DPE », jamais d'écart automatique. `body` étant vide, le drapeau ne lit que le titre.
- **Un même immeuble, plusieurs annonces** : plusieurs agences peuvent publier le même immeuble (photos identiques, surfaces et DPE différents selon l'annonce), que le crible compte alors comme autant de candidats. Le script signale les **doublons probables sans jamais les fusionner** ; les photos tranchent (voir § Lecture de la sortie).
- **`street_view_url`** (attribut posé par le vendeur, souvent un particulier) donne le point du bien, en général à quelques mètres de l'adresse ; le géocoder en inverse (BAN) avant de chercher l'adresse par l'ADEME. Le script ne le lit pas.
- **Troncature de `javascript_tool`** : environ 1 000 caractères par chaîne ; renvoyer un objet dont une propriété est un tableau de chaînes (800 points de code chacune) et reconstituer le fichier (§ Sauvegarde).
- **`window.name`** survit aux navigations du même site et porte l'état d'une page à l'autre (pages déjà lues, compteurs).
- **Grande surface bon marché** : cache souvent un hangar, une grange ou un bien hors commune (« à 10 mn de <ville> ») ; le drapeau « sous le premier décile » dit de **lire la description** (`props.pageProps.ad.body`) avant de croire le €/m².
- **Rayon** : le curseur a des paliers (0, 1, 5, 10, 20 km… ; un cran au clavier, flèche droite) ; l'URL écrit `5000_10000` (le second nombre est le rayon posé, en mètres) ; « Maison » + « Autre » = `real_estate_type=1,5`. Le rayon retient les **communes qui touchent le cercle** : des points jusqu'à 15 km à « 10 km ».
- **Type « Autre »** : contient les « Immeuble N m² » d'agences, mais aussi des garages, du mobilier sur terrain, une péniche. **Réglage du script** : les biens non résidentiels sont écartés, comme « non résidentiel probable », quand le titre ou la description nomme un bien non résidentiel (péniche, bateau, mobil-home ou mobile home, garage, box, parking, terrain, hangar, entrepôt) **sans nommer un logement** (maison, immeuble, appartement, logement, studio, pavillon ; compléments : maisonnette, appart, appt, logt, villa, longère, duplex, triplex, loft, habitation, fermette, corps de ferme, rapport locatif, propriété, bâtisse, chalet, bungalow, manoir, château, moulin, demeure, bastide, résidence, hôtel particulier, ensemble immobilier, T1 à T6, F1 à F6, N pièces, N lots) ; le motif ne vaut que pour le type « Autre » (« Maison avec garage », type « Maison », reste) et « Immeuble avec garage » reste retenu. Lire les écartées de ce motif (une erreur d'écart y est visible) et poser `--surface-min`.
- **Mot-clé** : le premier clic dans la barre du haut, juste après un chargement, ne donne pas le focus (re-cliquer, voir les suggestions, puis taper) ; valider par Entrée, jamais par une suggestion ; « Rechercher dans le titre uniquement » décochée = titre et texte ; le moteur est flou (« maison de ville » ramène aussi beaucoup de neufs).
- **Loyer ANIL brut × surface** surestime les grandes surfaces : le script appelle `src.immo.loyer.loyer_3r` (élasticité H2) et ne réécrit pas la formule ; la série `maison` est toujours une extrapolation (dite).
- **Médianes DVF** autour de la mairie peuvent sous-estimer les appartements du centre : le crible ne lit pas DVF, c'est `/immo rapide`, étape 2, qui le fait à l'adresse.

## Procédure

1. **Quand** : l'investisseur donne une URL de recherche, ou une zone à cribler (commune, rayon, budget). Une annonce seule : `/immo` directement.
2. **Passes** : une par type de bien et par mot-clé (exemple : une passe « Autre » sans mot-clé ; puis « Maison » avec « immeuble », « maison de ville », « logements », « rapport », « investisseur »). **Recharger l'URL obtenue après chaque filtre** posé dans l'interface, puis lire. Noter pour chaque passe l'URL obtenue et le volume affiché (texte « N annonces » du DOM, qui fait foi).
3. **Lecture page par page**, une à la fois : ne passer à `&page=N+1` qu'une fois la page N sauvegardée ; vérifier que `searchData.total` égale le volume du DOM et que la dernière page lue est `max_pages`.
4. **Sauvegarde** de chaque page dans le scratchpad, en contournant la troncature :

   ```js
   const sd = JSON.parse(document.getElementById('__NEXT_DATA__').textContent).props.pageProps.searchData;
   const GARDE = ['square','rooms','energy_rate','ges','old_price','fees_at_the_expanse_of','price_except_fees','fees_price','property_tax','annual_charges','building_year','heating_mode','real_estate_type','immo_sell_type','type_real_estate_sale'];
   const proj = sd.ads.map(a => ({list_id:a.list_id, subject:a.subject, body:a.body, price:a.price, first_publication_date:a.first_publication_date, location:{city:a.location.city, zipcode:a.location.zipcode, lat:a.location.lat, lng:a.location.lng, source:a.location.source, is_shape:a.location.is_shape}, owner:{type:a.owner.type}, attributes:a.attributes.filter(t=>GARDE.includes(t.key)).map(t=>({key:t.key,value:t.value}))}));
   const s = JSON.stringify(proj); const cps = Array.from(s); const chunks = [];
   for (let i=0;i<cps.length;i+=800) chunks.push(cps.slice(i,i+800).join(''));
   let h = 0; for (const ch of s) { h = (Math.imul(h,31) + ch.codePointAt(0)) >>> 0; }
   ({n_ads: proj.length, total: sd.total, nb_code_points: cps.length, hash31: h, chunks})
   ```

   Ajouter `street_view_url` à `GARDE` pour garder le point du vendeur (le script ne le lit pas). Écrire les `chunks`, bout à bout, dans `<scratchpad>/crible/<passe>-page<N>.json`, puis **contrôler** :
   `python3 -I -c "import json,sys,functools; s=open(sys.argv[1],encoding='utf-8').read(); print(len(s), functools.reduce(lambda h,c:(h*31+ord(c))&0xFFFFFFFF, s, 0), len(json.loads(s)))" <fichier>` doit rendre `nb_code_points`, `hash31` et `n_ads` (les trois valeurs doivent concorder). Chaque fichier est une **liste d'annonces** (une page ou une passe).
5. **Volume du DOM contre volume lu** : la somme des volumes affichés des passes (`--volume-affiche`) égale le nombre d'annonces lues ; sinon le script écrit « ATTENTION » : relire les pages manquantes avant de conclure.
6. **Appel du script** (depuis le répertoire de travail qui contient `immo-data/`) :

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_crible.py" --pages <scratchpad>/crible/*.json \
     --fiche immo-data/bruts/<commune>-<…>-opendata-<date>.json [--fiche …] \
     --surface-min <m²> --volume-affiche <somme> --source bruts/scan-lbc-<zone>-<AAAA-MM-JJ>.md \
     --out <scratchpad>/scan-lbc-<zone>-<AAAA-MM-JJ>.md --pistes-out <scratchpad>/pistes-proposees.json
   ```

   Le plafond de prix, les types et ses exceptions viennent de `immo-data/profil.json` (`premier_achat_prix_max`,
   `cible` : les cibles acceptées par le crible sont listées dans le `_lisez_moi` de `templates/profil.json`, `--types` couvre les autres) ; `--prix-max` ou `--types` les remplacent, exceptions comprises (la sortie le dit). `--surface-min` n'a **pas de
   défaut** : c'est un choix de l'investisseur. `--fiche` : une par commune qui compte, sinon « non calculé ». Un argument invalide
   (plafond non fini ou négatif, `--top` à 0, date mal écrite, `--types` vide) ou une annonce sans identifiant de 10 chiffres
   arrête le script avec « erreur : » et le code 2. **Le script refuse d'écrire** dans `immo-data/pistes.json`, sous
   `immo-data/bruts/` (quelle que soit la casse du chemin : un volume insensible à la casse ne la distingue pas), sur un lien physique
   (fichier à plusieurs noms) et sur l'une de ses entrées.
7. **Lecture de la sortie** : dans l'ordre, les comptes (uniques = écartées + retenues ; `ATTENTION` s'il y a un écart de
   volume), les seuils dits, le tableau classé, les écartées (parcourir chaque motif : une erreur d'écart est visible), les doublons, les
   points partagés. **Contrôler chaque « doublon probable » par les photos** (façade, pièces) dans le navigateur, avec
   `old_price` et `street_view_url`, **avant toute étude** : un groupe n'est jamais fusionné par le script.
   Chaque drapeau a sa suite : « bien mixte » → surface du DPE ADEME ; « sous le premier décile » → description de l'annonce ;
   « date affichée » → demander l'ancienneté réelle à l'agent ; « contenu différent entre pages » (un même identifiant relu avec un
   autre prix, une autre surface ou un autre type : la première lecture est gardée, le verdict dépend de l'ordre des pages) →
   relire la page.
8. **Pistes** : copier le scan dans `immo-data/bruts/` et verser les pistes de `pistes-proposees.json` dans
   `immo-data/pistes.json` **par une seule session** (un seul écrivain par fichier), après relecture ;
   retirer d'abord celles qu'une étude a déjà couvertes (même `id`).
9. **`/immo rapide`** sur les 5 à 8 meilleurs (`candidat`, haut du classement), une annonce à la fois.

## Ce que le tri fait et ne fait pas

- **Comptes** : annonces lues ; identifiants uniques (ensemble) ; doublons entre pages (un même identifiant relu, y compris
  sur la même page) ; écartées par motif (le premier motif de la liste l'emporte : prix absent, hors prix, hors type, non
  résidentiel probable, surface sous le minimum, neuf probable, viager probable) ; retenues. Prix, surface ou coordonnées
  illisibles deviennent une absence dite.
- **Hors prix** : prix **strictement inférieur** au plafond ; l'exception du profil lève le plafond pour son annonce seule.
- **Non résidentiel probable** (réglage du script) : type « Autre » seulement ; le titre ou la description nomme un
  bien de la liste (`MOTS_NON_RESIDENTIELS` : péniche, bateau, mobil-home, garage, box, parking, terrain, hangar, entrepôt)
  sans nommer un logement (`MOTS_LOGEMENT` : maison, immeuble, appartement, logement, studio, pavillon). **Compléments**,
  dans le sens prudent (n'est écarté que ce qui nomme un bien non résidentiel ET aucun logement) :
  `MOTS_LOGEMENT_AJOUTES` (maisonnette, appart, appt, logt, villa, longère, duplex, triplex, loft, habitation, fermette, corps de
  ferme, rapport locatif ; dernière passe : propriété, bâtisse, chalet, bungalow, manoir, château, moulin, demeure, bastide,
  résidence, hôtel particulier, ensemble immobilier) et `FORMES_LOGEMENT_AJOUTEES` (T1 à T6, F1 à F6, N pièces, N lots). Ni « mas »,
  ni « bien immobilier », ni « ferme » seul (choix du script). **« lot » seul ne dit pas un logement** : « N lots »
  (un nombre avant « lot ») en dit un, donc « Rapport locatif 3 lots + garage » est retenu et « Lot de parkings », « Lot de 3
  garages », « Lot de 10 box », « Garages, lot de 4 » restent écartés. Mots entiers (« lotissement » n'est pas « N lots », « fermé »
  n'est pas « ferme »), casse et accents ignorés, pluriel reconnu, « mobile home » lu comme « mobil-home » (`VARIANTES_ORTHOGRAPHE`).
  Placé après « hors type » : un type hors cible ou un prix hors plafond l'emporte, la surface minimale vient après. Listes en
  constantes nommées, dites dans la sortie.
- **Doublon probable** (réglage du script) : même commune, surface à 5 % près **et** prix à 10 % près (écart relatif au
  plus grand des deux, une tolérance par grandeur : `TOLERANCE_DOUBLON_SURFACE`, `TOLERANCE_DOUBLON_PRIX`), **ou** même point
  précis (coordonnées identiques, partagées par au plus 3 annonces, et jamais pour un point de commune :
  `location.source = city` ou `is_shape` vrai, qui vont ensemble). Seuils nommés dans le script et dits dans la sortie.
  Un groupe se forme par chaînage de paires : ses extrémités peuvent s'écarter de plus de 5 % en surface et de 10 % en prix.
- **Rendement brut indicatif** (réglage du script) : loyer réaliste annuel de `loyer_3r` (série `maison`, charges
  récupérables 0, hypothèse dite) ÷ (prix annoncé × 1,08) (`COEF_COUT_ACQUISITION`), travaux à 0 : une convention qui approche les frais
  d'acquisition de l'ancien. Le moteur de `/immo`, lui, divise par le coût total réel : les
  deux chiffres ne coïncident pas. Exemple fictif (100 m², 120 000 €, loyer réaliste 750 €/mois) : 9 000 / 129 600 = 6,94 %,
  contre 7,50 % si l'on divisait par le prix seul. Immeuble ou bien à lots inconnus : « non
  calculé » ; une commune sans fiche : « non calculé ».
- **Classement** : rendement décroissant ; à défaut, €/m² croissant.
- **Premier décile** : calculé dès 10 retenues avec surface (`MIN_RETENUES_DECILE`) ; en dessous, aucun drapeau « sous le premier
  décile » et aucune piste `remarquable` ; la sortie le dit.

## Limites connues

- **Doublon vu, mais pas tous** : avec les seuils actuels (surface à 5 % près, prix à 10 % près), deux annonces
  d'un même bien publiées par des professionnels sont groupées par la règle de commune, leurs points de centre de commune étant
  distincts. Un doublon dont le prix s'écarte de plus de 10 % ou la surface de plus de 5 % (une agence peut annoncer une autre
  surface) reste invisible, et le chaînage peut réunir des biens distincts : les photos tranchent.
- **Biens non résidentiels : le motif a des bords, dans les deux sens.** « Non résidentiel probable » ne vaut que pour le type
  « Autre » et lit le titre et la description (vide dans une page de résultats : le titre seul en pratique). *Ce qui passe* :
  - un bien non résidentiel publié en « Maison », ou titré sans un mot de la liste ; un titre qui nomme un logement (« hangar
    transformé en logement ») ; une description qui cite un logement même en passant ou par négation (« proche de la maison de
    retraite ») ;
  - **« N lots de garages »** : un nombre avant « lot » suffit, « 2 lots de garages », « Vente de 3 lots de box », « 4 lots de
    parkings » sont retenus ; « Lot de parkings », « Lot de 3 garages » restent écartés ;
  - **un nom de rue, de résidence ou une expression qui contient un mot d'habitation ajouté** : « Garage rue du Moulin », « Parking
    rue du Château », « Box résidence Les Pins », « Parking résidence sécurisée », « Parking propriété privée », « Garage allée de la
    Bastide », « Garage chemin du Manoir » sont retenus. Ce sont des annonces de garages et de parkings, le
    cœur de la cible du motif : propriété, résidence, moulin, château, manoir et bastide sont les mots à retirer d'abord si ce bruit
    gêne (une ligne chacun dans `MOTS_LOGEMENT_AJOUTES`, un cas de test chacun).
  *Ce qui est encore écarté à tort* : la liste des logements reste fermée, donc une habitation nommée par un mot hors liste et qui
  contient un mot non résidentiel tombe (par exemple : « Mas avec terrain », « Ferme avec hangar »,
  « Bien immobilier avec garage », ces trois exclus par choix du script ; « Gîte avec garage », « Bâtiment avec garage »,
  « Cottage avec garage », « Pied-à-terre avec parking »). Un immeuble de rapport se publie en type « Autre » : lire la section
  « Écartées » de ce motif, qui donne le mot déclencheur. Sans rendement, le classement par €/m² croissant met en tête les non
  résidentiels qui passent (mobilier sur terrain, péniche, garage) : lire le haut du tableau avant
  de désigner des candidats, et poser `--surface-min`, un choix de l'investisseur sans défaut.
- **Un rendement extrapolé peut être aberrant** : sur le jeu fictif, une grange de 200 m² à 40 000 € sort à 37,5 %
  (÷ (prix × 1,08) ; 40,5 % si l'on divisait par le prix seul), la série `maison` étant hors du domaine de la carte. Les drapeaux
  « extrapolation » et « sous le premier décile » sont les seuls garde-fous ; la question de la piste candidate reprend l'alerte
  du décile. Lire l'annonce avant `/immo rapide`.
- **Neuf par le titre : un type de vente renseigné l'emporte** (réglage du script) : une annonce titrée « Maison N pièces »,
  DPE A, sans honoraires, mais portant un `immo_sell_type` renseigné autre que `new`, reste retenue ; si c'est un neuf de
  constructeur, seul `new` l'écarte. Quand `immo_sell_type` est renseigné partout, la règle du titre ne joue
  plus ; elle ne joue que sur une annonce sans aucun type de vente. Lire l'annonce avant `/immo rapide`.
- **Pas de filtre de distance** (réglage du script) : le point d'un professionnel est décalé autour du centre de commune, le script ne calcule aucune distance. Lire la commune au
  tableau.
- **Bien mixte : le titre seul** (`body` vide) : un titre muet sur le local n'est pas vu ; un
  titre qui dit « local » sur un garage lève le drapeau.
- Les réglages du script (doublon, non résidentiel, type de vente) sont testés sur des jeux fictifs : vérifier leur effet
  sur la sortie de chaque scan.
