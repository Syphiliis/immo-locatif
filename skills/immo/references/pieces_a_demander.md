# Pièces à demander au vendeur (étapes 8 et 9, mode `maj`)

Les pièces remplacent des hypothèses : on les demande **avant l'offre**, par écrit, et on les range
dans `immo-data/pieces/<slug>/` (privé, jamais partagé). Bases légales lues le 07/10/2026 sur
Légifrance, le BOFiP, service-public.gouv.fr ou impots.gouv.fr ; à relire si l'étude date de plus de
6 mois. Une pièce légale est due **à la promesse**, sauf l'état des risques et l'audit, dus dès la
première visite ; avant l'offre, le vendeur donne les autres s'il le veut :
ce qu'il refuse se dit dans l'étude.

## Pour tout bien

| Pièce | Pourquoi | Base |
|---|---|---|
| **Dernier avis de taxe foncière** (pièce n° 1) | ligne de cash-flow ; TEOM | aucune obligation : due par le propriétaire au 1er janvier (CGI art. 1415), le prorata entre vendeur et acquéreur est un accord privé (impots.gouv.fr, mise à jour du 20/07/2026) |
| Dossier de diagnostic technique (DDT) | travaux, louabilité, risques | CCH art. L.271-4 (version du 11/04/2024) : CREP (plomb, permis avant le 01/01/1949), amiante (permis avant le 01/07/1997), termites (zone arrêtée), gaz et électricité (installation de plus de 15 ans), état des risques, DPE **et audit énergétique**, assainissement non collectif, mérule (zone arrêtée), bruit des aérodromes, appareil de chauffage au bois (zone PPA), arrêtés de police de sécurité ou de salubrité ; seuils de date : service-public F10798 |
| État des risques | PPR, sismicité, radon | C. env. art. L.125-5 ; dû dès la première visite (depuis le 01/01/2023), pas seulement à la promesse ; moins de 6 mois ; couvre PPR naturels, miniers et technologiques, sismicité 2 à 5, radon de niveau 3, recul du trait de côte (service-public F12239, vérifié le 28/09/2026). **Les argiles n'y figurent pas** : les lire dans la fiche (Géorisques) |
| Baux, quittances, dernier loyer pratiqué | loyer réel, garanties | aucune obligation avant la promesse ; le bail se transmet avec le bien loué |
| Factures et garanties des travaux récents (décennale) | état réel, levier | aucune obligation avant la promesse |
| Date d'acquisition par le vendeur | levier (prix d'achat) | question orale ; DVF à la même parcelle |

## Maison individuelle

- **Audit énergétique** si le DPE est E, F ou G : obligatoire à la vente d'un logement individuel,
  F et G depuis le 01/04/2023, **E depuis le 01/01/2025**, D au 01/01/2034 ; valable 5 ans ;
  remis au plus tard **à la première visite** (CCH art. L.126-28-1 et L.271-4 ; ecologie.gouv.fr,
  mise à jour du 03/10/2024 ; service-public F37110, vérifié le 14/09/2026). C'est la pièce qui
  tranche la fourchette des travaux : son chiffrage prime sur le modèle de l'étude.
- **Assainissement** : non collectif, contrôle du SPANC de moins de 3 ans, à la charge du vendeur
  (CSP art. L.1331-11-1) ; travaux de mise en conformité par l'acquéreur dans l'année suivant la
  vente (CCH art. L.271-4, II). Collectif : aucune obligation nationale de contrôle à la vente ; un
  arrêté municipal ou le règlement de service peut l'imposer (service-public F31685, vérifié le
  26/02/2025) ; vérifier si le décret n° 2022-93 vise la commune du bien (rubrique assainissement de
  `immo-data/communes.md`). Demander le mode
  d'assainissement et, s'il existe, le dernier contrôle de raccordement.

## Immeuble en monopropriété (immeuble de rapport)

Tout ce qui vaut pour une maison (l'audit énergétique vise aussi un immeuble de plusieurs logements
hors copropriété, CCH art. L.126-28-1), plus :
- un DPE par logement, ou celui de l'immeuble ; leurs numéros, pour les lire dans la base ADEME ;
- les baux de chaque logement, l'état locatif (loyers, dépôts, dates d'entrée, impayés) ;
- la déclaration ou l'autorisation de mise en location si la commune ou l'EPCI l'a instaurée par
  délibération (CCH art. L.634-1 et s., L.635-1 et s. ; amende jusqu'à 5 000 € pour défaut de
  déclaration, jusqu'à 15 000 € pour une location malgré un refus d'autorisation : service-public
  F34210, vérifié le 05/11/2024).

## Immeuble mixte (logements et local)

Tout ce qui vaut pour une monopropriété, plus :
- le bail commercial du local (durée, loyer, indexation, charges et taxe foncière refacturées,
  destination), le dernier avis d'échéance et l'état des impayés ;
- la surface de chaque partie au DPE ou au plan (la surface du DPE prime sur l'annonce).

## Lot de copropriété

Si la décision `cible` du profil l'exclut, sans objet ; si un lot est étudié : pièces annexées à la promesse (CCH
art. L.721-2, version en vigueur depuis le 01/01/2024) : fiche synthétique ; règlement de
copropriété et état descriptif de division, avec leurs modificatifs publiés ; procès-verbaux des AG
des 3 dernières années ; charges payées sur les 2 derniers exercices ; sommes dues, impayés, fonds de
travaux ; carnet d'entretien ; notice d'information ; conclusions du diagnostic technique global ;
plan pluriannuel de travaux ou son projet. Plus le DDT du lot.

## Message type à l'agent

Envoyé **seulement après validation de l'investisseur** (garde-fou 6), jamais par Claude. Pas de tiret
cadratin, aucun loyer ni statistique.

```
Bonjour,

Le bien <adresse ou référence> m'intéresse et je souhaite préparer une offre sérieuse. Pourriez-vous
me transmettre, avant une éventuelle visite ou juste après :
- le dernier avis de taxe foncière ;
- le dossier de diagnostics (DPE, plomb, amiante, électricité, gaz, état des risques) ;
- <audit énergétique, s'il est classé E, F ou G> ;
- <mode d'assainissement et dernier contrôle> ;
- <baux en cours et dernier loyer pratiqué, s'il est loué> ;
- les factures des travaux récents.

Merci d'avance,
<signature>
```
