---
name: market-context
description: "Compare un bien immobilier à son marché local (la zone de recherche de l'utilisateur, décision `zone` de immo-data/profil.json) via DVF, la carte des loyers et un relevé d'annonces de location pour sortir le €/m² de vente médian, le loyer de marché, la décote et au moins 3 comparables DVF récents à moins de 500 m ; vérifie que les paramètres de la zone (DMTO du département, zone locative de la commune) sont connus du moteur et les ajoute, sourcés, s'ils manquent ; construit au besoin immo-data/MARCHE.md et immo-data/communes.md. À déclencher dès que l'utilisateur demande « ce prix est-il cohérent », « combien ça vaut vraiment », « compare avec le marché », « DVF », « cherche des comparables ». Étape 3 de `/immo` ; préalable : lbc-scraper ; suivant : renovation-estimator, value-add-analyzer, puis le moteur via /immo."
---

# Market Context - comparaison marché

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Ce skill sert à répondre à la question qui tue avant tout calcul de rendement : **ce prix est-il bien aligné avec le marché réel ?** Un rendement brut de 8 % sur un bien payé 30 % trop cher n'est pas une bonne affaire.

## Quand l'utiliser

- Juste après `lbc-scraper` (appel systématique dans le pipeline d'étude d'un bien)
- Question directe sur les prix de marché d'une commune de la zone de recherche
- Validation d'une estimation MeilleursAgents / SeLoger
- Première étude dans une nouvelle zone : construire `immo-data/MARCHE.md` et `immo-data/communes.md` (§ Construire le contexte de la zone)

## Premier geste : la zone

Lire la décision `zone` de `immo-data/profil.json` (`commune_centre`, `code_insee`, `departement`, `communes`). Le bien est-il dans une commune de la liste ? Sinon, le dire à l'utilisateur et lui demander confirmation avant de poursuivre (la zone se change dans `profil.json`, pas dans ce skill). Sans décision `zone` : le dire, et demander à l'utilisateur sa commune centre et ses communes de recherche avant tout chiffre.

## Paramètres de la zone (obligatoire, avant le moteur)

Le moteur ne calcule les frais d'acquisition et l'éligibilité aux dispositifs fiscaux que pour un département et une commune qu'il connaît. Il lit `${CLAUDE_PLUGIN_ROOT}/engine/src/immo/params.json`, sur lequel il fusionne `immo-data/params_local.json` ; un département absent (DMTO) l'arrête toujours, en disant quoi ajouter ; une commune absente de la feuille des zones ne l'arrête que si le régime du bailleur privé est évaluable (`code_insee`, `immeuble_collectif`, `date_acquisition` et `bailleur_prive` présents dans l'entrée), sinon ce régime sort « non évaluable ». Ce skill vérifie les deux entrées **avant** l'appel du moteur :

1. **DMTO du département du bien** : `dmto.departements.<code département>.taux_departemental`.
2. **Zone locative de la commune du bien** (zonage A bis / A / B1 / B2 / C) : `fiscal.bailleur_prive.zones`, clé = code INSEE de la commune.

Les entrées de `params.json` sont des exemples sourcés ; une autre zone s'ajoute dans `immo-data/params_local.json`, sous **le même chemin de clé**, entrée par entrée (forme exacte : `${CLAUDE_PLUGIN_ROOT}/templates/params_local.json` du plugin). Si une entrée manque :

- **DMTO** : lire la **table des taux DMTO publiée par la DGFiP** (impots.gouv.fr, espace partenaires, notaires, « DMTO » : PDF des taux applicables au 1er jour du mois, la plus récente), à la ligne du département : taux départemental de droit commun (celui d'un investissement locatif), et le taux réduit éventuel (primo-accédant) pour mémoire. Vérifier sur la même table que la commune n'a pas voté de taux communal dérogatoire. Recouper si possible par notaires.fr.
- **Zone locative** : lire **l'arrêté de zonage A/B/C en vigueur** (arrêté du 1er août 2014 modifié, dernière version consolidée sur Legifrance, ou dernier arrêté modificatif au Journal officiel) et la liste des communes par zone publiée par le ministère chargé du logement (ecologie.gouv.fr, simulateur ou fichier du zonage). Relever la zone de la commune, avec son code INSEE.
- Écrire chaque valeur dans `immo-data/params_local.json` avec `valeur`, `source` (texte, URL, ligne ou article lu, date de publication) et `verifie_le` (date du jour, AAAA-MM-JJ). Dire à l'utilisateur ce qui a été ajouté.
- **Aucun chiffre inventé ni repris de mémoire.** Source officielle illisible ou introuvable : ne rien écrire, le dire, et donner à l'utilisateur l'adresse de la source et la clé à remplir. Une entrée existante dont `verifie_le` a plus de 6 mois se relit avant usage.

## Construire le contexte de la zone (`immo-data/MARCHE.md`, `immo-data/communes.md`)

Les deux fichiers sont propres à l'utilisateur ; ils partent des gabarits `${CLAUDE_PLUGIN_ROOT}/templates/MARCHE.md` et `${CLAUDE_PLUGIN_ROOT}/templates/communes.md` du plugin (copiés dans `immo-data/` puis remplis). Ils servent de **cadrage** ; une étude se fonde toujours sur DVF et le relevé de loyers du bien.

- **`MARCHE.md`** : rapport de marché de la zone, une fois par semestre environ. La ligne `**Date de référence** : AAAA-MM-JJ` est obligatoire (le script de fraîcheur de `/immo` la lit). Les micro-marchés d'une même commune (centre, quartier de gare, quartiers résidentiels, villages) varient fortement : toute évaluation doit être localisée, jamais fondée sur une moyenne communale.
- **`communes.md`** : une section par commune de la zone, titrée exactement `## <Commune> (<code INSEE>)` (`/immo` la lit seule par ce titre), avec les rubriques du gabarit dans l'ordre. Chaque valeur porte son URL et sa date de lecture, ou « non trouvé » avec les lieux cherchés ; deux sources qui divergent s'écrivent toutes les deux, sans trancher. Une rubrique de plus de 6 mois se relit avant usage.
- Remplir au navigateur ou par WebFetch sur les sources publiques nommées dans chaque rubrique du gabarit ; ne jamais recopier une valeur d'une autre zone ni d'une étude précédente sans la relire à la source.

## Fondamentaux de la commune (pré-filtre, avant tout calcul)

Avant de chiffrer, screener la commune sur 5 indicateurs INSEE (gratuits, primaires) :

| Indicateur | Où le trouver | Lecture |
|---|---|---|
| Évolution population (10 ans) | INSEE *Comparateur des territoires* / *Statistiques locales* | En baisse = demande locative qui s'érode, vigilance forte |
| Taux d'emploi / part d'actifs occupés | INSEE dossier complet commune | Proxy de solvabilité des locataires |
| Part de locataires (vs propriétaires occupants) | INSEE *logement* (RP) | Commune à plus de 90 % de propriétaires = marché locatif étroit, relocation lente |
| **Taux de logements vacants** | INSEE RP ; LOVAC (base ANAH/DGALN des logements vacants) | **Plus de 8-9 % = signal d'alerte** (offre supérieure à la demande, vacance structurelle) |
| Revenu médian (Filosofi) | INSEE | Cadre le loyer soutenable et le risque d'impayés |

Outils tiers à recouper avec l'INSEE (source primaire) : *Chacun Son Lieu*, *LocService* (tensiomètre locatif), *ANIL*.

## Workflow

### 1. Comparables DVF (source primaire, obligatoire)

Interroger **app.dvf.etalab.gouv.fr** ou le dataset DVF open data. Objectif : **au moins 3 ventes comparables** dans les 24 derniers mois, dans un rayon de 500 m, sur le même type de bien (apparts vs maisons vs immeubles à ne pas mélanger), surface ±20 %.

**Données ouvertes (script).** Lancer d'abord `python3 "${CLAUDE_PLUGIN_ROOT}/engine/scripts/immo_fiche_opendata.py" --adresse "<adresse du bien, avec le numéro et le code postal>" --out immo-data/bruts/<slug>-opendata-<AAAA-MM-JJ>.json` (rayon 500 m et 24 mois par défaut). Lire `dvf.par_type` (n, médiane et quartiles en €/m², par type de bien) et `dvf.comparables` (les 15 ventes les plus récentes, mutations mono-local dédoublonnées ; les mutations à plusieurs locaux en sont exclues et comptées dans `dvf.compteurs`, les ventes d'immeubles de la commune étant dans `dvf.immeubles`, à lire selon l'étape 2 de `/immo`), puis filtrer à la main sur le type et la surface ±20 %. Lire aussi `alertes` (fenêtre DVF courte, DPE tronqués). Si `dvf` vaut `null` (code de sortie 3 : fiche partielle, JSON écrit), lire `erreurs` puis revenir à la consultation manuelle ci-dessous. La fiche reste locale : les CGU DGFiP du DVF interdisent la réidentification des personnes et l'indexation web.

Pour chaque comparable, noter :
- Date de mutation
- Adresse (au moins la rue)
- Surface réelle (surface bâtie cadastrale)
- Prix net vendeur
- €/m² calculé
- Nature (appartement / maison / immeuble / terrain+maison)

Si aucun comparable exploitable dans 500 m, élargir à 1 km en le précisant.

### 2. Référentiels secondaires

**MeilleursAgents** et **SeLoger** pour :
- €/m² moyen ville et quartier (à prendre avec recul, souvent lissé)
- Loyer mensuel €/m² par typologie (studio, T2, T3, T4+, maison)

Attention : ces deux sources reposent en partie sur des estimations algorithmiques. Elles sont un **repère**, jamais un ancrage : la vente s'ancre sur DVF, le loyer sur le relevé d'annonces réelles (§ Relevé de loyers). En Île-de-France, les indicateurs des notaires (prix médians par commune) complètent DVF ; ailleurs, la chambre des notaires du département publie souvent l'équivalent.

### 3. Loyers de marché

**Données ouvertes (script).** Ancrer d'abord le loyer sur le bloc `loyers` de la fiche (commande en § 1) : `valeur_m2` (loyer d'annonce prédit par la carte ANIL, **charges comprises**, non meublé, à ne pas lire comme un loyer hors charges), intervalle `ip_bas` à `ip_haut`, `n` annonces, `maille` (`commune` ou maille plus large) et `millesime`. Les annonces Leboncoin et SeLoger ci-dessous restent le contrôle terrain.

La carte donne un loyer d'annonce **non meublé**, souvent à maille communale ou plus large : elle cadre, elle ne fonde pas seule le loyer réaliste. Le relevé ci-dessous le fonde.

### Relevé de loyers

Le loyer est le premier levier du prix plafond : il se fonde sur des **annonces de location réelles, relues en entier**, jamais sur un extrait de moteur, un souvenir ou une estimation algorithmique.

**Sélection.**
- **Au moins 5 annonces** de location, de la **même typologie** que le logement étudié (nombre de pièces, maison ou appartement, surface voisine), à **10 km au plus** du bien, **les plus récentes** disponibles. Moins de 5 trouvées : le dire, et baisser la confiance du loyer réaliste.
- **Logement de 2 pièces ou moins, quand la décision `meuble_logements_2_pieces_ou_moins` de `profil.json` vaut `true`** (scénario meublé étudié) : relever **séparément** au moins 5 annonces **non meublées** et au moins 5 annonces **meublées**. Le loyer meublé vient des annonces meublées, jamais d'une majoration forfaitaire du loyer nu. Moins de 5 annonces meublées : le dire, le scénario meublé reste « à vérifier ».
- Colocation (si le bien s'y prête) : annonces de chambres en colocation, relevées de même.

**Lecture, annonce par annonce.**
- Au **navigateur** (Leboncoin, SeLoger), page par page, comme un utilisateur : ouvrir l'annonce, lire le **texte entier**. Aucune requête directe à leboncoin.fr, aucune API non publique, aucun WebFetch sur une annonce.
- Relever sur l'annonce même : loyer affiché, **paliers** (loyer réduit pendant N mois puis loyer plein), franchise, **charges** (comprises ou non, montant, taxe foncière ou TEOM refacturées), **nu ou meublé**, surface, nombre de pièces, commune, **date de l'annonce** (date affichée, dite comme telle : Leboncoin peut republier), `old_price` s'il existe.
- Le loyer retenu est le loyer **hors charges** plein, après palier. Un palier ou une franchise se note sur la ligne, il n'abaisse pas le loyer retenu.
- **Capture** de chaque annonce (navigateur, `screenshot`), copiée dans `immo-data/captures/loyers/<slug>-<id annonce>.png`. Annonce retirée avant la capture : le dire, la ligne reste un repère, pas une base de calcul.
- Un extrait non relu (crible, sortie d'un sous-agent, ancienne étude) reste un **repère**, marqué tel, jamais une base de calcul.

**Tableau du relevé** (dans l'analyse) :

| # | URL | Date de l'annonce | Lu le | Commune (km) | Type, pièces, m² | Nu / meublé | Loyer HC | Charges | Paliers, franchise | €/m² HC | Capture |
|---|---|---|---|---|---|---|---|---|---|---|---|

**Synthèse.**
- Loyer €/m² HC **médian** du relevé, par régime (nu ; meublé pour 2 pièces ou moins si le profil l'étudie), et loyer mensuel du bien étudié. Le réaliste prend la médiane, pas le haut de fourchette.
- **Confrontation à la carte des loyers** : convertir le loyer médian relevé en **charges comprises** (charges relevées sur les annonces) avant de le comparer à l'intervalle `ip_bas` à `ip_haut` de la fiche (non meublé, charges comprises). Dans l'intervalle : le dire. Hors de l'intervalle : expliquer l'écart (surface, état, meublé, maille large) ou baisser la confiance.
- MeilleursAgents et SeLoger (prix au m² de quartier) se citent en regard, comme **repère** seulement, avec leur date de consultation.
- Tension locative perçue : nombre d'annonces actives de la typologie sur le secteur, au jour du relevé.
- Présenter un loyer à l'utilisateur : le **milieu** d'abord, puis la borne haute, nommée comme un plafond rare.

### 4. Calculs de synthèse

```
Décote vs médiane DVF = (prix_m2_annonce - mediane_DVF_500m) / mediane_DVF_500m × 100
Loyer de marché mensuel nu = surface × loyer_m2_median
Rendement brut théorique (sur prix FAI, hors frais et travaux) = (loyer_mensuel_nu × 12) / prix_fai × 100 ; le rendement sur coût total d'acquisition est calculé par le moteur (via /immo)
```

### 5. Sortie structurée

Produire une section markdown à insérer dans le fichier d'analyse du bien, `immo-data/analyses/[quartier]-[prix-k€]-[YYYY-MM-DD].md` (même préfixe que la fiche `bruts/` de `lbc-scraper`) :

```markdown
## Contexte marché

**Commune, micro-marché** : [commune, quartier / village]
**Paramètres de la zone** : DMTO [département] [connu | ajouté le AAAA-MM-JJ, source] ; zone locative [zone] [connue | ajoutée le AAAA-MM-JJ, source]
**€/m² annoncé** : X €/m²
**Médiane DVF 500 m (24 derniers mois)** : Y €/m² (n = Z ventes)
**Décote vs médiane** : ±X % [lecture : sous-coté / cohérent / au-dessus]

### Comparables DVF retenus

| Date | Adresse | Surface | Prix net | €/m² | Nature |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

### Loyer de marché

| Régime | Loyer mensuel estimé | €/m² | Source |
|---|---|---|---|
| Nu | ... € HC | ... | médiane de n annonces relevées (tableau ci-dessous) |
| Meublé (2 pièces ou moins) | ... € HC | ... | médiane de n annonces meublées relevées |
| Colocation (par chambre) | ... € HC | - | n annonces relevées |

**Carte des loyers** : ip_bas à ip_haut €/m² CC (maille, millésime) ; loyer relevé converti CC : ... €/m² [dans l'intervalle / écart expliqué].

### Annonces de location relevées

[Tableau du § Relevé de loyers, une ligne par annonce, capture comprise]

**Tension locative** : [faible / moyenne / forte], justifiée par [nombre d'annonces actives, durée moyenne].

### Sources et dates de consultation

- Fiche données ouvertes (script) : `immo-data/bruts/<slug>-opendata-AAAA-MM-JJ.json` ; sources, millésimes et dates d'extraction : bloc `sources` de la fiche
- DVF : consulté le YYYY-MM-DD via app.dvf.etalab.gouv.fr
- MeilleursAgents : YYYY-MM-DD
- SeLoger : YYYY-MM-DD
- Observatoire local des loyers : [si la commune en a un]
```

## Outils de récupération

Ordre de priorité :
1. **DVF** : `https://app.dvf.etalab.gouv.fr` (pas de DataDome) via WebFetch.
2. **MeilleursAgents / SeLoger** (prix de quartier, repère) via WebFetch ; si 403/DataDome, au navigateur.
3. **Annonces de location** (Leboncoin, SeLoger) : au navigateur seulement, page par page (§ Relevé de loyers).
4. **Paramètres de la zone** : table DMTO de la DGFiP (impots.gouv.fr) et arrêté de zonage A/B/C (Legifrance), par WebFetch ou au navigateur.
5. Sinon : demander l'info à l'utilisateur.

## Garde-fous

- Ne JAMAIS citer un chiffre DVF sans indiquer la date de la mutation et la distance au bien analysé.
- Si moins de 3 comparables trouvés, le dire explicitement et baisser la confiance de l'analyse.
- Si la géolocalisation du bien est imprécise, marquer le rayon des comparables comme approximatif.
- Ne JAMAIS fonder un loyer réaliste sur une annonce non relue en entier le jour de l'étude : un prix affiché peut n'être qu'un palier, ou inclure des charges (une annonce peut afficher un loyer d'appel valable quelques mois, suivi d'un loyer nettement plus haut).
- Ne JAMAIS écrire dans `params_local.json` une valeur qui n'a pas été lue à sa source officielle le jour même, avec sa source et sa date.
- Hors des grandes métropoles tendues, une projection de valorisation future au-delà de +1-2 %/an doit être justifiée par un élément spécifique (nouvelle gare, ZAC, arrivée d'un employeur majeur), daté et sourcé.
