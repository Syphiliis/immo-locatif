---
name: value-add-analyzer
description: "Évalue, en mode profil, les leviers de valeur d'un bien candidat que les décisions de l'investisseur laissent ouverts (immo-data/profil.json, lu en premier) : sortie de passoire DPE, meublé des logements de 2 pièces ou moins, local commercial, loyers, avec la règle qui les permet ou les bloque (PLU, ABF, PPRI, loi du 6 juillet 1989) ; un levier coupé par une décision (division, création de logements) tient en une ligne, sauf exception écrite pour l'annonce ; le reste en 3 lignes « Hors décision ». À déclencher pour toute question de potentiel, de transformation ou de value-add sur un bien candidat. Étape 5 de `/immo` ; préalables : lbc-scraper + market-context (+ renovation-estimator s'il a tourné) ; suivant : yield-calculator."
---

# Value-Add Analyzer - leviers de valeur, en mode profil

> Racine du plugin : `${CLAUDE_PLUGIN_ROOT}`. Dans les fichiers de référence lus ensuite, `${CLAUDE_PLUGIN_ROOT}` désigne ce chemin (il n'y est pas remplacé automatiquement). Les données de l'utilisateur vivent dans `immo-data/` du répertoire courant (ou `$IMMO_DATA_DIR`).

Le skill dit, pour un bien candidat, quels leviers les décisions de l'investisseur laissent ouverts, ce qu'ils changent et la
règle qui les permet ou les bloque. Il ne chiffre ni les travaux (`renovation-estimator`) ni la rentabilité (moteur,
via `/immo`) : il les nourrit. Il tourne à l'étape 5 de `/immo` (sous-agent C) ou seul, pour un bien
candidat.

## Premier geste : le profil

Lire `immo-data/profil.json`, source unique des décisions de l'investisseur, et écrire en tête de la section
« profil.json lu le <AAAA-MM-JJ> ». Pour chaque décision qui touche un levier : valeur, date, exceptions. Une
exception écrite pour l'annonce étudiée (champ `exceptions`, par numéro d'annonce) lève la coupure pour ce bien
seulement. Une décision plus récente, citée par `/immo` à l'étape 0, s'y ajoute. Aucune valeur du profil ne se
recopie ailleurs : on cite la clé. Une décision absente du profil n'est pas une coupure : le levier s'évalue, et la
section le dit (« clé `<cle>` absente de profil.json »).

## Leviers coupés par le profil

- **Division et création de logements** (clé `division`, quand elle vaut `false`) : une ligne, « coupé par le profil (décision du <date de
  la clé>) », sans évaluation. Une conversion qui crée un logement distinct (local commercial, grenier, dépendance)
  est une création de logement : même ligne.
- Un bien déjà divisé en parties indépendantes s'étudie entier et par parties (`${CLAUDE_PLUGIN_ROOT}/skills/immo/SKILL.md`,
  étape 1) : ce n'est pas un levier.
- Exception écrite pour l'annonce : le levier s'évalue (§ Division, sur exception seulement).

## Leviers évalués

Ceux du sous-agent C de `/immo` (`${CLAUDE_PLUGIN_ROOT}/skills/immo/references/sous_agents.md`). Pour chacun : applicable ou non,
effet (€/mois de loyer, € de valeur, ou « non chiffré »), coût (renvoi au programme ou aux options de
`renovation-estimator`, ou à un devis), délai, et la règle qui le permet ou le bloque, avec sa source et sa date.

### 1. Sortie de passoire (DPE F ou G, ou classe sous la classe visée)

- **Louabilité** : calendrier de la décence énergétique (loi n° 89-462, art. 6 : G non décent depuis le 01/01/2025,
  F à partir du 01/01/2028, E à partir du 01/01/2034 ; texte cité dans
  `${CLAUDE_PLUGIN_ROOT}/skills/renovation-estimator/references/decence-tva-aides.md`). La classe visée vient de `/immo`.
- **Loyer** : la révision annuelle et la majoration pour travaux d'amélioration ne peuvent pas s'appliquer à un
  logement de classe F ou G (loi n° 89-462, art. 17-1, III, version du 24/08/2022, location nue ; Légifrance, lu le
  08/10/2026). Sortir de F ou G les rend de nouveau possibles.
- **Exonération de taxe foncière** : sur **délibération de la commune ou de l'EPCI** (art. 1383-0 B CGI, version en vigueur du 01/01/2025 au 01/01/2027 issue de la loi 2023-1322 art. 143, lue sur Légifrance le 07/10/2026), exonération de **50 % à 100 % de la TFPB pendant 3 ans** à compter de l'année qui suit le paiement, pour un logement **achevé depuis plus de dix ans** au 1er janvier de la première année d'exonération, ayant fait l'objet par le propriétaire de **dépenses de prestations de rénovation énergétique et d'équipements associés** (celles du 3° du I de l'art. 278-0 bis A, hors entretien). Seuils : dépenses payées **> 10 000 € par logement** l'année précédente, ou **> 15 000 € par logement** sur les 3 années précédentes ; non renouvelable dans les 10 ans suivant l'expiration ; **déclaration au service des impôts avant le 1er janvier** de la première année, avec les justificatifs. La version à compter du 01/01/2027 (ordonnance 2025-1247, art. 10, lue le 07/10/2026) garde ces conditions et renvoie à l'art. L. 213-248 du CIBS au lieu du 278-0 bis A. **À vérifier auprès de la mairie de la commune / du centre des impôts fonciers** (rubrique « Taxe foncière » de `immo-data/communes.md`) : toutes les communes ne l'ont pas votée. Si applicable, la chiffrer au moteur (`/immo`, « Ce qui améliore le rendement », ligne « exonération de taxe foncière »).
- **Valeur** : aucune décote ni prime de classe chiffrée sans étude datée à la maille du bien.
- **Coût** : programme et options de `renovation-estimator` ; le gain de classe vient d'un audit ou d'un DPE projeté,
  sinon « non chiffré ».

### 2. Meublé (logements de 2 pièces ou moins)

- Décision `meuble_logements_2_pieces_ou_moins` de `profil.json` (si elle vaut `true`, ou si elle est absente et que
  l'utilisateur demande le scénario) : lister les logements concernés, pièces principales comptées sur le plan ou
  l'annonce.
- Loyer, mobilier, CFE, bail et fiscalité de la SCI à l'IS : `${CLAUDE_PLUGIN_ROOT}/skills/immo/references/entree_moteur.md`,
  § Scénario meublé ; le moteur chiffre. Sans relevé de loyer meublé à l'étape 3 : « non chiffré ».

### 3. Local commercial

- Usage actuel et bail en place (loyer, échéance, destination, indexation) : pièces du vendeur.
- Le garder loué : loyer de marché du relevé de l'étape 3, vacance de `profil.json` (clé `vacance_realiste`).
- Le transformer : en logement distinct, c'est une création de logement (coupé par le profil, sauf exception) ;
  rattaché à un logement existant, à évaluer. Bloqué si le PLU protège un linéaire commercial ; sinon, autorisation
  d'urbanisme (le service instructeur dit laquelle), règlement sanitaire départemental (RSD du département) et, en copropriété,
  règlement de copropriété.

### 4. Loyers

- Loyer en place (baux, quittances) face au loyer réaliste de l'étape 3 : l'écart se chiffre ; sa résorption dépend
  du bail, elle ne se suppose pas dans le scénario réaliste.
- Sous-location constatée : la signaler, sans la chiffrer.
- Annexes louables à part (garage, cave, parking) : loyer du relevé de marché, sinon « non chiffré ».

## Réglementaire

Lire le bloc `urbanisme` de la fiche de données ouvertes quand il existe : `zone` (avec `reglement_url`),
`prescriptions` (linéaire commercial), `servitudes`, `abords_monument_historique`, `plan_prevention_risques`, et sa
`portee`. Sinon, méthode API Carto GPU de `${CLAUDE_PLUGIN_ROOT}/skills/immo/references/sous_agents.md` (§ C, potentiel), puis le
règlement écrit sur le Géoportail de l'urbanisme, pages citées. Risques : bloc `risques` de la fiche. Tout levier qui
dépend du PLU ou de l'ABF se marque « sous réserve du certificat d'urbanisme ».

## Division, sur exception seulement

Quand `profil.json` lève la coupure pour l'annonce :
- copropriété : la division crée un nouveau lot, souvent avec modification du règlement et vote de l'assemblée
  générale (non relu : à faire valider par le notaire) ;
- **Surface minimale légale** : une division d'immeuble ne peut pas créer de logement de moins de 14 m² et 33 m³ habitables, pièces communes exclues (art. L. 126-17, 2° CCH, ex-art. L. 111-6-1 abrogé au 01/07/2021) ; décence : au moins une pièce principale de 9 m² avec 2,20 m sous plafond, ou de 20 m³ (décret n° 2002-120, art. 4) - vérifié sur Légifrance le 23/09/2026
- éclairement naturel et ouvrant des pièces principales (décret n° 2002-120, art. 2, 7°, version du 21/08/2023, lu
  le 08/10/2026) ; accès séparés ; compteurs (grille de `renovation-estimator`) ;
- PLU : taille minimale de logement s'il en fixe une, stationnement ; ABF ;
- préférer un T1 (pièce de nuit cloisonnée, même partiellement) à un studio ;
- effet : loyers du relevé de marché par logement ; coût : `renovation-estimator` ; le moteur chiffre, aucun
  rendement type.

## Hors décision

Trois lignes au plus, sans chiffre : ce qui est vu hors des décisions (combles aménageables, colocation, location
saisonnière, revente par lots, extension). L'investisseur décide s'il les fait étudier.

## Sortie attendue

```markdown
## Potentiel (mode profil, profil.json lu le AAAA-MM-JJ)

| Levier | Statut | Effet | Coût | Règle qui le permet ou le bloque (source, date) |
|---|---|---|---|---|
| Division, création de logements | coupé par le profil (décision du JJ/MM/AAAA) | - | - | - |
| Sortie de passoire | évalué / sans objet (classe déjà au niveau visé) | ... | programme, options | ... |
| Meublé (2 pièces ou moins) | ... | ... | mobilier | entree_moteur.md, § Scénario meublé |
| Local commercial | ... | ... | ... | PLU (linéaire commercial), RSD |
| Loyers | ... | ... | ... | ... |

**Hors décision** (3 lignes au plus, non chiffré) : ...

## Points à vérifier avant offre

- [ ] Certificat d'urbanisme opérationnel (CUb) si un levier dépend du PLU
- [ ] Zone, linéaire commercial, abords de monument historique, PPRI (bloc `urbanisme` ou API Carto)
- [ ] Baux en place, quittances, destination du local commercial
- [ ] Copropriété, si le bien en est une : règlement, procès-verbaux d'assemblée générale, travaux votés, fonds de travaux, impayés, part des occupants et des bailleurs
- [ ] Étude de structure rapide (murs porteurs, charpente) si un levier touche la structure
- [ ] Règlement sanitaire départemental (RSD) du département pour un changement de destination
```

## Garde-fous

- Un levier sur le papier n'est jamais garanti : toujours un scénario où il est refusé ou trop cher, et l'opération
  doit tenir sans lui.
- Le loyer se plafonne au loyer de marché de `market-context`.
- Rénover n'est pas créer de la valeur : une cuisine refaite ne rapporte rien de plus si le marché la suppose déjà.
- Aucun ordre de grandeur sans source datée : un effet non sourcé s'écrit « non chiffré ».
