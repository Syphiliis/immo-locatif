# Rapport marché - <Commune centre> et sa zone · <Mois AAAA>

<!--
Gabarit du rapport de marché de la zone de recherche. Copier dans immo-data/MARCHE.md, puis remplir
(skill market-context, § Construire le contexte de la zone). Les communes sont celles de la décision `zone`
de immo-data/profil.json.

Règles :
- Chaque chiffre porte sa source (lien) et sa date de lecture. Une valeur non trouvée s'écrit « non trouvé »,
  avec les lieux cherchés ; jamais une valeur estimée ou reprise de mémoire.
- Ce rapport cadre ; il ne fonde pas une étude. Une étude s'ancre sur DVF et sur le relevé d'annonces de
  location du bien (market-context).
- Le relire au moins tous les 6 mois : la ligne « Date de référence » ci-dessous est lue par le script de
  fraîcheur de /immo (format exact : **Date de référence** : AAAA-MM-JJ).
- Supprimer ce commentaire une fois le rapport rempli.
-->

**Périmètre** : <commune centre (code postal)> + <n> communes de la zone
**Date de référence** : AAAA-MM-JJ
**Sources macro** : <liste des sources consultées : DVF (data.gouv.fr), indicateurs des notaires, carte des loyers (ANIL / data.gouv.fr), INSEE, Géorisques, sites de prix (MeilleursAgents, SeLoger, PAP...), offres d'emploi, transporteur>
**Cribles d'annonces** : <fichiers immo-data/bruts/scan-lbc-AAAA-MM-JJ.md utilisés, s'il y en a>

---

## 1. Synthèse exécutive

<!-- 5 à 10 lignes : les régimes de marché distincts de la zone (pôle urbain, communes desservies, villages
sans transport...), avec pour chacun une fourchette de €/m² de vente et de loyer €/m² sourcés, et la ou les
thèses d'investissement qui en découlent. -->

---

## 2. Grille synthétique des communes

<!-- Une ligne par commune de la zone. €/m² : DVF (médiane des 24 derniers mois, par type) ou indicateurs des
notaires ; loyer : carte des loyers (millésime) et relevé d'annonces ; tendance : même source à 12 mois
d'écart ; transport : gare et temps de trajet vers le pôle d'emploi principal (horaires du transporteur) ;
risque : Géorisques (PPRI, argiles) ; population : INSEE (dernier recensement). -->

| Commune | €/m² maison médiane | €/m² appart médiane | Loyer €/m²/mois | Tendance 12 mois | Gare / transport | Risque principal (PPRI...) | Pop. |
|---|---|---|---|---|---|---|---|
| <Commune> | | | | | | | |

**Sources de la grille** : <une ligne par colonne, avec date de lecture>

---

## 3. Analyse par commune

<!-- Une sous-section par commune, dans l'ordre de la grille. -->

### 3.1 <Commune> <code postal> - <rôle dans la zone>, <population> hab.

**Profil** : <pôle urbain ou village ; services (commerces, santé, enseignement) ; bassin d'emploi (nombre
d'offres actives, source et date) ; secteurs protégés (abords de monuments historiques, site patrimonial
remarquable)>

**Marché vente** : <€/m² maison et appartement, sources datées ; dynamique (stable, hausse, baisse) ; produits
rares (immeubles de rapport, grandes surfaces)>

**Marché locatif** : <loyer €/m² (carte des loyers, millésime ; relevé d'annonces, date) ; loyers types par
typologie ; profil des locataires ; tension (nombre d'annonces actives)>

**Risques** :
- <PPRI ou autre plan de prévention : zones, date d'approbation, source Géorisques ou préfecture>
- <Contraintes ABF / patrimoine>
- <Autre risque local daté et sourcé>

**Micro-quartiers** (ordre décroissant de cash-flow attendu, chacun justifié par une source) :
1. <quartier> - <ce qui le distingue>

**Thèse** : <type de bien qui fonctionne ici, ou « à éviter » et pourquoi>

---

## 4. Infrastructure - transports et pôles d'emploi

<!-- Lignes de train ou de car (temps de trajet vers les pôles d'emploi, fréquence, source : horaires du
transporteur, date) ; projets d'infrastructure datés et sourcés (nouvelle gare, ZAC, arrivée d'un employeur) ;
principaux employeurs de la zone. -->

---

## 5. Thèses d'investissement

<!-- 2 à 4 thèses, chacune : type de bien, communes, fourchette de prix d'achat, loyer attendu, points de
vigilance. Les fourchettes viennent des sections 2 et 3, avec leurs sources. -->

### Thèse A - <intitulé>

### Thèses à éviter

---

## 6. Grille de décision - critères « bonne opportunité »

<!-- Critères de tri des annonces, à adapter à la zone et au profil.json de l'utilisateur. Les seuils sont des
choix de l'utilisateur, pas des faits : les dater. Exemple de structure : -->

Un bien est qualifié « opportunité à investiguer » si **au moins <n> des <m> critères** sont remplis :

| Critère | Seuil | Pondération |
|---|---|---|
| **Prix €/m² sous médiane commune** | <-x % ou plus> | <%> |
| **Ancienneté de l'annonce** | <> n jours OU baisse de prix> | <%> |
| **Potentiel value-add** | <DPE F/G améliorable, combles, changement d'usage...> | <%> |
| **Position transport** | <moins de n min de la gare ou du pôle d'emploi> | <%> |
| **Risque naturel acceptable** | <zone du PPRI acceptée> | <%> |

Score ≥ <x> % = **à étudier en priorité**.
Score <y>-<x> % = **à mettre en veille**.
Score < <y> % = **à écarter**.

---

## 7. Risque structurel de la zone

<!-- Le risque majeur de la zone (inondation, retrait-gonflement des argiles, cavités, littoral...), avec son
plan de prévention : nom, date d'approbation, zonage réglementaire et ce que chaque zone implique pour un
investisseur (construction, rénovation, assurance, revente). Sources : Géorisques, préfecture, DICRIM de la
commune. -->

| Zone | Règle | Impact investisseur |
|---|---|---|
| <zone> | <ce que le règlement interdit ou encadre> | <écarter / vigilance / acceptable> |

**Consigne** : ne signer aucun compromis sans vérification Géorisques à l'adresse exacte.

---

## 8. Sources

<!-- Toutes les URL citées ci-dessus, groupées par thème, chacune avec sa date de lecture. -->

**Prix de marché** :
- <source> (lu le AAAA-MM-JJ)

**Risques** :
- <source> (lu le AAAA-MM-JJ)

**Transport** :
- <source> (lu le AAAA-MM-JJ)

**Emploi** :
- <source> (lu le AAAA-MM-JJ)
