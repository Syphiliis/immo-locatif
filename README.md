# immo-locatif

**Plugin Claude Code pour étudier un bien à vendre en vue de le louer, de l'annonce au verdict.**

Vous collez un lien Leboncoin, une adresse ou le texte d'une annonce ; Claude déroule une étude complète et
sourcée : fiche du bien, données ouvertes, marché local, travaux, leviers de valeur, rentabilité et fiscalité
calculées par un moteur Python, comparaison des montages, stratégie de négociation et verdict.

Fonctionne partout en France. Votre zone, votre profil d'investisseur et votre foyer fiscal restent chez
vous, dans un dossier `immo-data/` qui n'est jamais versionné ni partagé.

## Ce que fait le plugin

| Étape | Skill | Ce qu'il produit |
|---|---|---|
| 1 | `lbc-scraper` | La fiche structurée de l'annonce (prix, surface, lots, DPE, photos, signaux) |
| 2 | `immo` | Une fiche de données ouvertes : géocodage BAN, cadastre, DVF, DPE ADEME, urbanisme (API Carto / GPU), risques (Géorisques), copropriété (RNIC), fiscalité locale |
| 3 | `market-context` | Prix et loyers de marché, comparables DVF récents, décote ou surcote ; paramètres de zone |
| 4 | `renovation-estimator` | Le programme de travaux qui rend le bien décent et louable, en bornes basse et haute TTC |
| 5 | `value-add-analyzer` | Les leviers de valeur que votre profil laisse ouverts (sortie de passoire DPE, meublé, local commercial...) |
| 6 | moteur Python | Rendements, cash-flow, taux d'effort, TRI, prix d'équilibre, fiscalité : SCI à l'IS, LMNP réel, foncier réel ou micro |
| 7 | `immo` | Comparaison des montages, selon le montage de référence de votre profil |
| 8 | `negoc` | Fourchette d'offre (ouverture, cible, limite), leviers sourcés, objections, brouillons de messages, journal de négociation ; aussi pour les devis d'artisans |
| 9 | `immo` | Verdict sourcé et pièces à demander avant de signer |

Deux modes : `rapide` (tri d'une annonce en quelques minutes) et `complet` (étude entière).

`yield-calculator` décrit le tableur .xlsx de rentabilité ; son générateur n'est pas encore fourni, la
rentabilité se lit dans la sortie du moteur.

## Installation

Prérequis :

- [Claude Code](https://code.claude.com) ;
- Python 3.11 ou plus ;
- pour lire les annonces Leboncoin, un navigateur piloté par Claude (Claude in Chrome ou le navigateur
  intégré de l'application). À défaut, coller le texte de l'annonce ou des captures suffit.

Dans Claude Code :

```
/plugin marketplace add Syphiliis/immo-locatif
/plugin install immo-locatif@immo-locatif
```

Il reste à installer une fois les dépendances du moteur (`httpx`, `openpyxl`), de préférence dans un
environnement virtuel. Le skill `immo` vous donne la commande exacte, avec le chemin du plugin installé, à
la première utilisation.

## Premiers pas

1. Ouvrez Claude Code dans un dossier dédié à votre recherche.
2. Lancez `/immo-locatif:immo`. À la première utilisation, il crée `immo-data/` à partir des gabarits de
   `templates/` et vous aide à remplir :
   - `profil.json` : vos décisions d'investisseur (zone, cible, budget, apport, montage de référence,
     vacance, seuil de confort...), chacune datée et sourcée ;
   - `foyer.json` : TMI, revenus, loyers et prêts existants. Ils servent uniquement au moteur (taux
     d'effort, fiscalité) et ne sont jamais recopiés dans une étude ;
   - `params_local.json` : les droits de mutation de votre département et le zonage locatif de vos
     communes. Le plugin ne fournit qu'un département en exemple ; l'étape marché complète les vôtres à la
     source officielle, avec leur date. Aucun taux n'est deviné ;
   - `MARCHE.md` et `communes.md` : votre étude de marché, construite par `market-context`.
3. Ensuite : `/immo-locatif:immo <lien Leboncoin | adresse | texte d'annonce> [rapide | complet]`.

## Principes

- **Aucun chiffre inventé.** Tout taux, plafond ou barème du moteur (`engine/src/immo/params.json`) porte
  sa source et sa date de vérification. Une donnée manquante est signalée comme manquante.
- **Vos données restent chez vous.** `immo-data/` est exclu du dépôt (`.gitignore`). Le moteur refuse un
  profil ou un foyer encore rempli avec les valeurs d'exemple.
- **Rien n'est envoyé à votre place.** Les messages de négociation sont des brouillons ; aucune offre,
  aucun message ni aucune signature ne part sans vous.

## Limites

- Les paramètres fiscaux et réglementaires vieillissent : revérifiez-les avant une décision, surtout après
  une loi de finances. Le script `engine/scripts/immo_fraicheur.py` signale les sources périmées ; une
  alerte « PÉRIMÉ » ou « NON COUVERT » dès le premier jour est une invitation à vérifier, pas une panne.
- La grille de coûts de travaux (`skills/renovation-estimator/references/`) est calibrée en 2026 sur des
  prix moyens nationaux et franciliens : recalez-la sur vos devis locaux.
- Le tri automatique des annonces reconnaît les immeubles de rapport et les maisons de ville ; les autres
  types se passent avec l'option `--types`.
- Leboncoin : le plugin lit les annonces que vous ouvrez, via votre navigateur, une par une. Respectez les
  conditions d'utilisation du site ; le plugin ne fait pas d'aspiration automatisée en masse et ne doit pas
  servir à en faire.
- Ce plugin est un outil d'aide à l'analyse. Il ne remplace ni un notaire, ni un expert-comptable, ni un
  conseiller en investissement financier, et ne constitue pas un conseil en investissement.

## Développement

Les tests du moteur tournent hors ligne (les appels aux API publiques sont simulés) :

```bash
cd engine
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

Les contributions sont bienvenues : ouvrez une issue ou une pull request. Toute valeur fiscale ou
réglementaire ajoutée doit citer sa source officielle et sa date de vérification.

## Licence

[MIT](LICENSE).
