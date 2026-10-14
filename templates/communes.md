# Fiches communales de la zone de recherche

<!--
Gabarit des fiches communales. Copier dans immo-data/communes.md, puis remplir (skill market-context,
§ Construire le contexte de la zone). Une section par commune de la décision `zone` de immo-data/profil.json.

Règles :
- Titre de section exactement « ## <Commune> (<code INSEE>) » : /immo lit la section seule par ce titre.
  Code INSEE : https://geo.api.gouv.fr/communes?nom=<commune> (ne pas confondre avec le code postal).
- Les 14 rubriques, dans l'ordre. Chaque valeur porte son URL et sa date de lecture (« lu le AAAA-MM-JJ »), ou
  « non trouvé » avec les lieux cherchés. Deux sources qui divergent s'écrivent toutes les deux, sans trancher.
- Une rubrique de plus de 6 mois se relit avant usage.
- Supprimer ce commentaire une fois les fiches remplies.
-->

Collecte du AAAA-MM-JJ au AAAA-MM-JJ : chaque rubrique se relit avant un usage de plus de 6 mois, la date de lecture est portée par chaque ligne.

Format : 14 rubriques par commune, dans l'ordre ; une valeur porte son URL et sa date de lecture, ou « non trouvé » avec les lieux cherchés. Deux sources qui divergent sont écrites toutes les deux, sans trancher.

## <Commune> (<code INSEE>)

- **Intercommunalité** : <EPCI et son code> ; compétences utiles (urbanisme / PLUi, habitat et permis de louer, déchets, assainissement). Sources : geo.api.gouv.fr (`/communes/<code INSEE>?fields=nom,code,codeEpci,codesPostaux`, puis `/epcis/<code EPCI>`) ; Banatic (banatic.interieur.gouv.fr, fiche de l'EPCI et arrêté de statuts). - source : <URL> (lu le AAAA-MM-JJ)
- **Document d'urbanisme** : <PLU, PLUi, carte communale ou RNU ; date d'approbation ; procédures en cours>. Sources : Géoportail de l'urbanisme (geoportail-urbanisme.gouv.fr, API ou fiche du document), API Carto GPU (apicarto.ign.fr), site de la commune (enquêtes publiques). - source : <URL> (lu le AAAA-MM-JJ)
- **Permis de louer** : <autorisation préalable ou déclaration de mise en location (CCH art. L. 634-1 et L. 635-1) : délibération, date d'effet, périmètre ; permis de diviser (CCH art. L. 126-18) s'il existe ; ou « aucune délibération trouvée »>. Sources : site de la commune et de l'EPCI (délibérations), recueil des actes administratifs. - source : <URL> (lu le AAAA-MM-JJ)
- **Zonage A/B/C** : <zone A bis / A / B1 / B2 / C>. Source : arrêté du 1er août 2014 modifié (Legifrance, version consolidée ou dernier arrêté modificatif au JO) ; liste des communes par zone du ministère chargé du logement (ecologie.gouv.fr). À reporter aussi dans immo-data/params_local.json si le moteur ne connaît pas la commune (market-context, § Paramètres de la zone). - source : <URL> (lu le AAAA-MM-JJ)
- **PPRI** : <plan de prévention du risque inondation (ou autre PPR) : nom, date d'approbation, zones présentes sur la commune>. Sources : Géorisques (georisques.gouv.fr, API GASPAR), API Carto GPU (servitudes PM1), site de la préfecture du département. - source : <URL> (lu le AAAA-MM-JJ)
- **Argiles et radon** : <exposition au retrait-gonflement des argiles (faible / moyenne / forte) ; potentiel radon (catégorie 1, 2 ou 3)>. Source : Géorisques (API, par commune). - source : <URL> (lu le AAAA-MM-JJ)
- **Taxe foncière, taux** : <taux communal et intercommunal de TFPB votés, exercice ; TEOM ; délibération d'exonération CGI art. 1383-0 B si connue>. Source : fichier REI de la DGFiP (data.economie.gouv.fr, impôts locaux, exercice le plus récent). - source : <URL> (lu le AAAA-MM-JJ)
- **Taxe foncière, montants observés** : <montants annuels lus sur des annonces ou avis réels, avec surface et date ; jamais un €/m² d'une autre commune>. Source : annonces relues, avis de taxe foncière fournis par un vendeur. - source : <URL ou pièce> (lu le AAAA-MM-JJ)
- **Assainissement** : <collectif ou non collectif selon les secteurs ; service gestionnaire (commune, syndicat, EPCI) ; SPANC>. Sources : services.eaufrance.fr (fiche commune), zonage d'assainissement (annexe du PLU), site du syndicat. - source : <URL> (lu le AAAA-MM-JJ)
- **Monuments historiques et ABF** : <monuments protégés, périmètres des abords (servitude AC1), site patrimonial remarquable (SPR)>. Sources : API Carto GPU (servitudes AC1, AC4), Géoportail de l'urbanisme, liste des SPR du ministère de la Culture, base Mérimée (data.gouv.fr). - source : <URL> (lu le AAAA-MM-JJ)
- **Carte des loyers** : <loyer prédit €/m² charges comprises, appartement et maison, intervalle de prédiction, nombre d'annonces, maille, millésime>. Source : carte des loyers de l'ANIL et du ministère (data.gouv.fr, jeu « Carte des loyers », millésime le plus récent). - source : <URL> (lu le AAAA-MM-JJ)
- **INSEE** : <population et évolution sur 10 ans, part de locataires, taux de logements vacants, revenu médian (Filosofi), taux d'emploi>. Source : insee.fr, dossier complet de la commune (dernier recensement). - source : <URL> (lu le AAAA-MM-JJ)
- **Gare et transports** : <gare la plus proche (distance), ligne, temps de trajet vers le pôle d'emploi principal, fréquence ; car, bus>. Sources : données ouvertes du transporteur (SNCF open data, horaires régionaux), geo.api.gouv.fr pour les distances, site de la commune. - source : <URL> (lu le AAAA-MM-JJ)
- **Indicateurs des notaires** : <prix médian au m² appartements et maisons, période, évolution sur un an ; ou « non publié pour la commune »>. Source : base des notaires (Île-de-France : notairesdugrandparis.fr ; ailleurs : immobilier.notaires.fr ou la chambre départementale). - source : <URL> (lu le AAAA-MM-JJ)

<!-- Répéter la section ci-dessus pour chaque commune de la zone. -->

## Écarts avec les études

<!-- Facultatif. Quand une fiche contredit une étude déjà écrite (immo-data/analyses/), lister ici : fichier et
ligne, ce que dit l'étude, ce que dit la fiche, verdict (concordant / à corriger / non vérifiable). Les études
ne se modifient pas depuis ce fichier. -->
