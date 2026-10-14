# Terrain artisans : devis de travaux, d'entretien et services récurrents

> Terrain de `/negoc` (`SKILL.md` route ici). Les règles communes (préparer, ouvrir, concéder, conclure) sont
> dans `socle.md` et ne sont pas recopiées ; la loyauté et l'offre-acceptation dans `droit.md`. Chaque règle
> porte sa source courte : `[G11]` renvoie au socle vérifié (volet G, droit lu sur Légifrance au 10/10/2026),
> `[G-E1, moyen]` à une étude et à son niveau de preuve, `retex A1` à une leçon (`retex.md`).

## Quand ce terrain s'applique

- Négocier un **devis reçu** pour un bien de l'investisseur (acheté, ou en cours d'achat) : travaux,
  rénovation énergétique, dépannage, réparation, entretien.
- Service récurrent (entretien, ménage, maintenance) : tarif, durée, conditions générales.
- **Hors terrain** : chiffrer le programme de travaux d'un bien étudié à l'achat (`renovation-estimator`,
  appelé par `/immo`) ; le suivi des factures et du financement d'un chantier en cours.

## Entrées et outils

| Entrée | Où | Règle |
|---|---|---|
| Le devis, ses annexes, les fiches techniques | pièce reçue | Lu ligne par ligne contre le catalogue et la fiche technique `retex A3`. |
| Prix de marché | grille de coûts datée de `renovation-estimator` (`skills/renovation-estimator/references/`, lignes sourcées et datées, repères internes signalés) | Un repère, jamais un devis ; date de la ligne citée. |
| TVA, décence, aides, RGE | `skills/renovation-estimator/references/decence-tva-aides.md` | Relu avant tout chiffre de TVA `retex A7`. |
| Alertes sur un devis | `skills/renovation-estimator/SKILL.md` §Vérifier les devis reçus | Seuils du skill, ordres de grandeur non sourcés. |
| Prix publics du matériel | relevés au navigateur, URL et date notées | Prix TTC du jour, page capturée ; un prix sans date ne sert pas. |
| Dossier d'aide | dossier du référent (Anah, CEE) | Toute décision d'entreprise passe par son accord écrit `retex A4`. |
| Journal | `immo-data/negociations/`, commandes de `journal.md` | Terrain `artisan`, rôle `client`, contrepartie `artisan`. |

## Ce qui s'exige et ce qui se négocie

**S'exige (une correction légale n'est jamais une remise `[G1-G11] ; retex A2`)** :
- Devis détaillé avant toute prestation de dépannage, réparation ou entretien, sans seuil : date,
  entreprise, client, lieu, nature exacte, prix unitaires et quantités, déplacement, HT, TTC et taux de TVA,
  durée de validité, devis gratuit ou payant `[G1]` (arrêté du 24/01/2017, relu). Rénovation : écrit non
  imposé en général, mais information précontractuelle due ; toujours exiger un devis écrit `[G2]`.
- Attestation d'assurance décennale jointe, couvrant l'**activité exacte** du devis `[G10]`.
- **Taux de TVA exact, ligne par ligne** : 10 % pour un logement achevé depuis plus de 2 ans (hors gros
  équipements) ; 5,5 % pour l'isolation, le chauffage, la ventilation et l'eau chaude sous critères ; 20 % si
  les travaux produisent un immeuble neuf, ajoutent plus de 10 % de surface ou posent une chaudière
  fossile ; **le client certifie sur le devis ou la facture** et répond solidairement d'une inexactitude qui
  vient de lui `[G11]`. Le taux d'une ligne se décide sur le texte (`decence-tva-aides.md`), jamais sur le
  devis ; la demande de correction cite l'article : CGI 279-0 bis (10 %), 278-0 bis A (5,5 %).
- Aucune modification unilatérale du prix ou des caractéristiques (clause abusive) : prix ferme, ou
  indexation écrite `[G4]`.
- Contrat signé au domicile : contrat papier, formulaire de rétractation, **aucun paiement avant 7 jours**
  (sauf réparation urgente sollicitée), rétractation de 14 jours ; exclusions : urgence, sur-mesure,
  construction neuve, « transformation importante » d'un bâtiment `[G8]`. Bailleur personne physique : sa
  qualité de consommateur n'est pas vérifiée au socle ; « aucun versement avant 7 jours » s'écrit donc au
  devis comme condition de signature, exigée et jamais échangée contre une concession.
- Garanties légales intactes : parfait achèvement 1 an, biennale, décennale ; clauses limitatives non
  écrites `[G9]`.
- Aides : artisan et sous-traitant RGE ; demande déposée avant les travaux `[G12]`.

**Se négocie** : prix global et prix unitaires ; contenu et gamme ; délais et pénalités de retard
(sans délai convenu : 30 jours au plus, `[G7]`) ; acompte et échéancier (qualifié acompte ou arrhes au devis,
aucun plafond légal général trouvé `[G6]`) ; prix ferme ou indexé `[G4]` ; durée de validité ; condition
suspensive d'aide au devis `[G12]` ; regroupement de lots ; calendrier.

## Leviers

1. **Prix de marché ligne par ligne et marge d'installateur explicite** `retex A1` : fourniture au prix
   public relevé et daté, pose sur la grille datée, plus une marge d'installateur **écrite** (taux choisi par
   l'investisseur, ou hypothèse annoncée comme telle : aucun taux n'est sourcé). L'écart se calcule ligne par ligne,
   jamais en remise globale ronde (une remise ronde jugée trop faible a dû être refaite ligne par ligne,
   `retex A1`). Un prix d'appareil très au-dessus du prix public (`retex A3`) se montre avec la page
   datée.
2. **Plan B chiffré en TTC réel** `[G11] ; retex A1, A7` : (a) matériel fourni par le client et pose
   seule : fourniture au taux de 20 % (le taux réduit ne vaut que pour la pose), pose seule au taux réduit,
   garantie de l'appareil perdue côté artisan, aide réduite ou perdue `[G11, G12]` ; (b) autre poseur.
   **Contradiction A1/A7 arbitrée** : ce plan B se compare en TTC réel et vaut d'abord pour un lot non aidé
   (`retex.md`, arbitrages). La responsabilité de l'artisan sur un matériel fourni n'est pas sourcée.
3. **Mise en concurrence calibrée** `[G-E1, moyen ; G-E3, moyen]` : programme complet et arrêté, 3 ou 4
   entreprises, nombre annoncé ; programme flou ou existant incertain, diagnostic et métrés d'abord, puis
   négociation avec une ou deux entreprises présélectionnées. Plus de concurrence n'est pas toujours moins
   cher (malédiction du vainqueur, `[G-E3]`).
4. **Détail unitaire et contre-expertise face à un tiers payeur** `[G-E4, fort dans son cadre ; G-E5,
   moyen]` : une aide ou une assurance visible attire la surfacturation (client assuré : environ +80 %,
   `[G-E4]`) ; exiger le détail unitaire, comparer à un devis établi sans aide, contre-expertiser un
   diagnostic coûteux.
5. **Valeur nette d'une remise sur un chantier aidé** `[G12, calcul du volet]` : par geste, 1 € de remise
   rapporte 1 € tant que l'écrêtement ne joue pas, sinon 0,10, 0,25 ou 0,40 € selon les revenus ;
   rénovation d'ampleur sous plafond (TVA 5,5 %), 1 € HT de remise rapporte 1,055 € moins le taux d'aide
   (0,255, 0,455, 0,605 ou 0,955 €) ; au-dessus du plafond, 1,055 €. Exemple du volet : devis de 45 000 € HT,
   aide de 32 000 € (80 % de 40 000), ramener le devis à 40 000 € HT fait gagner 5 000 × 1,055 = 5 275 € TTC ;
   en dessous, 0,255 € par euro HT. Sous plafond, la remise devient monnaie d'échange (délais, contenu, lot non
   aidé) ; un devis calé juste sous un plafond appelle le contrôle des prix unitaires `retex A2`.
6. **Contreparties** (calendrier souple, acompte, regroupement de lots, période creuse) : pratique non
   sourcée `[G, non vérifié]` ; chacune s'échange contre un pas de prix (`concessions.md`).

## Paliers

Fixés **ligne par ligne, sur le marché daté, jamais sur les prix de l'artisan** `retex A1`, puis sommés :

| Palier, par ligne | Calcul |
|---|---|
| Ouverture | fourniture au prix public daté + pose au bas de la grille datée + marge basse |
| Cible | fourniture au prix public daté + pose au milieu de la grille + marge écrite |
| Limite | fourniture au prix public daté + pose au haut de la grille + marge haute ; au-delà, plan B |

- Ramener chaque ligne au même taux de TVA que la ligne du devis corrigée (HT et TTC distingués) ; la
  correction de TVA se fait **avant** le calcul de l'écart et n'entre pas dans la remise `[G11] ; retex A2`.
- L'ouverture découle de l'écart au marché ligne par ligne ; elle s'écrit en 3 ou 4 chiffres significatifs
  (`socle.md` §Ouvrir).
- Le plan B en TTC réel fixe le seuil de rupture d'un lot : si la limite dépasse le plan B, on bascule.
- **Une forte baisse s'accompagne d'une révision du cahier des charges** : une baisse de plus de 10 % sans
  changement du cahier des charges est l'alerte de `renovation-estimator` `retex A6` ; une ouverture très
  basse s'écrit avec le cahier des charges révisé (`retex.md`, arbitrages A1/A6).
- Chantier aidé : paliers sur la part non aidée d'abord ; sur la part aidée, valeur nette du levier 5.

## Séquence

1. **Périmètre figé avant le devis** ; prix et validités datés `retex A5`.
2. **Devis comparables** (même périmètre, même gamme), 3 ou 4 sur un programme arrêté `[G-E1, G-E3]`.
3. **Contrôle de conformité** (§Ce qui s'exige) et corrections demandées à part, sans les compter.
4. **Appel** pour le rapport et les questions qui présupposent un problème courant (`socle.md` §Échanger et
   concéder), puis **contre-proposition par écrit séparé** : un devis annoté n'est pas un contrat, une
   acceptation modifiée vaut offre nouvelle `[G3]`. Puis devis révisé.
5. Pause, puis pas décroissants échangés contre une contrepartie (date, acompte) `retex A1`.
6. **Chantier aidé** : signature après l'attribution de l'aide ; CEE, offre formalisée avant la signature du
   devis (au plus tard 14 jours après) `[G12]` ; changement d'entreprise seulement avec l'accord écrit du
   référent `retex A4`.
7. **Signature** : devis signé relu (version signée bien renvoyée, `retex A4`), acompte qualifié, aucun
   paiement au domicile avant 7 jours `[G8]`.
8. **En cours de chantier** : avenant chiffré et signé avant tout supplément `[G5]`.
9. **Réception écrite avec réserves** `[G9]`.

## Messages

Message bref, un motif réel, deux ou trois arguments, une date de validité ; le détail ligne par ligne en
**pièce jointe** (tableau : ligne, prix du devis, repère daté et sa source, écart) ; aucun tiret cadratin.
Une remise demandée sans réponse écrite n'est pas acquise `retex A5`.

**Contre-proposition sur un devis**

> Objet : votre devis n° [référence] du [date]
>
> Bonjour,
>
> Avant d'aller plus loin, deux points de forme : [l'attestation décennale couvrant
> l'activité exacte] et [le taux de TVA de la ligne X, à corriger en Y % (article Z)].
>
> Sur le prix, notre budget pour ce chantier est de [montant] € TTC. Le tableau joint compare chaque
> ligne aux prix publics relevés le [date] et à une pose aux tarifs courants : l'écart porte surtout sur
> [ligne 1] et [ligne 2].
>
> Nous pouvons vous proposer [montant] € TTC pour l'ensemble, avec [contrepartie : date de démarrage à
> votre convenance | acompte de X % à la commande], devis révisé avant le [date].
>
> Cordialement,

**Suite sans réponse (après 48 h au moins)** : une phrase qui rappelle la proposition et sa date de
validité, une question ouverte (« comment pouvez-vous ajuster la ligne X ? »).

**Dernier mot** (`retex G1`) : option positive prête à signer (montant, date, acompte) ; option négative
courte et neutre (« sinon nous retiendrons une autre entreprise pour ce lot ») ; aucun amortisseur.

## Objections

| L'artisan dit | Réponse | Source |
|---|---|---|
| « C'est le prix du matériel. » | Page du prix public datée ; demander la référence exacte et la fiche technique. | `retex A3` |
| « Je ne pose pas du matériel fourni. » | Plan B autre poseur, chiffré en TTC réel. | `retex A1` |
| « La TVA à 20 %, c'est plus simple. » | Le taux suit le texte ; la correction n'est pas une remise. | `[G11] ; retex A2` |
| « Il me faut 40 % à la signature. » | Montant à négocier ; au domicile, rien avant 7 jours. | `[G6, G8]` |
| « Le prix tient compte de l'aide. » | Détail unitaire et comparaison à un devis sans aide. | `[G-E4]` |
| « Ce supplément était imprévisible. » | Avenant chiffré et signé avant exécution. | `[G5]` |
| « Le devis n'est valable que 8 jours. » | Une échéance du vendeur ne presse pas notre décision ; nouvelle date demandée. | `socle.md` §Échanger et concéder |

## Lignes rouges et droit

- **Matériel fourni par le client** : TVA à 20 % sur la fourniture, aide réduite ou perdue ; responsabilité
  de l'artisan non sourcée `[G11, G12]`.
- **Supplément sans avenant écrit** : jamais `[G5]`.
- **Acompte au domicile avant 7 jours** : jamais, sauf réparation urgente sollicitée `[G8]`.
- **Devis signé avant l'attribution d'une aide**, ou hors du délai CEE : aide perdue `[G12]`.
- **SCI exclue de MaPrimeRénov'** (personnes morales exclues) `[G12]`.
- La mention de TVA signée engage le client `[G11]` : ne rien certifier d'inexact.
- Aucun devis concurrent inventé ni prix public déformé (dol, C. civ. 1137 ; `droit.md`).
- **Non vérifié dans le socle, aucune règle n'en dépend** : retenue de garantie (loi 71-584, plafond non
  lu) ; équipement ajouté sur un existant et décennale (arrêt du 21/03/2024, non relu) ; jurisprudence de
  l'article 1793 ; base HT ou TTC de l'écrêtement par geste ; qualité de consommateur d'un bailleur ou d'une
  SCI ; saisonnalité des prix et valeur des contreparties.

## Leçons des négociations passées

Leçons du terrain, chacune avec la section où la règle vit : `retex.md` §Leçons de départ, A1 à A7
(et G5 pour un service récurrent : présenter le spectre, faire soi-même, intermédiaire, tout compris,
avec le seuil de rentabilité ; achat ponctuel, un seul choix), et §Leçons ajoutées.

## Sources

Droit (Légifrance, versions en vigueur au 10/10/2026, lues par le volet G du socle) :
- C. civ. 1113, 1116 à 1118, 1121 (offre, acceptation) ; 1165, 1193, 1195 (prix, modification,
  imprévision) ; 1219, 1220 (exception d'inexécution) ; 1792 à 1792-6 (garanties) ; 1793 (forfait).
- C. conso. L111-1 (information précontractuelle) ; R212-1 3° (clause abusive) ; L214-1 à L214-3 (sommes
  versées d'avance) ; L216-1, L216-6, L216-7 (délai) ; L221-2 12°, L221-9, L221-10, L221-18, L221-28
  (contrat hors établissement).
- C. assur. L243-1-1 II, L243-2, L243-3 (assurance décennale).
- CGI 279-0 bis (loi 2025-127, art. 32) et 278-0 bis A (loi 2026-103, art. 92) (TVA réduite).
- arrêté du 24/01/2017, art. 1 à 5 (devis de dépannage, réparation, entretien ; art. 4 I relu).
- Anah, *Les aides financières en 2026* (édition de septembre 2026, mise en ligne le 31/08/2026), p. 7 à 32.
- service-public.gouv.fr, fiches F2533 (vérifiée le 28/03/2024), F2958 (25/09/2026), F2034, F23568, F35083
  (01/09/2026).

Études :
- Bajari P., McMillan R., Tadelis S. (2009). Auctions versus negotiations in procurement: An empirical
  analysis. *Journal of Law, Economics, and Organization* 25(2):372-399.
- Bajari P., Tadelis S. (2001). Incentives versus transaction costs. *RAND Journal of Economics*
  32(3):387-407.
- Hong H., Shum M. (2002). *Review of Economic Studies* 69(4):871-898 ; Li T., Zheng X. (2009). *Review of
  Economic Studies* 76(4):1397-1429.
- Kerschbamer R., Neururer D., Sutter M. (2016). *PNAS* 113(27):7454-7458 ; Schneider H.S. (2012).
  *Journal of Industrial Economics* 60(3):406-433.
- Pless J., van Benthem A.A. (2019). *AEJ: Applied Economics* 11(4):367-401.
