# Messages : règles d'écriture, gabarits, contrôle avant envoi

Tout message de `/negoc` est un **brouillon** : l'investisseur le relit, le valide et l'envoie
lui-même ; Claude n'envoie rien (retex I9). Ce fichier porte les règles communes aux deux terrains. Le
gabarit de la **première offre immobilière** et de sa **fiche travaux** est dans `immo_achat.md`
§Messages ; celui d'une contre-proposition sur un devis dans `artisans.md` §Messages.

## Règles d'écriture

**Règles de méthode issues des leçons** (elles priment sur la recherche quand elles divergent,
`socle.md` en-tête) :

1. **Ce qui fonde un message, ce sont les pièces de l'autre partie** (diagnostics, audits, devis, offre
   écrite, bail) : chaque fait vient d'une pièce nommée, relue ; jamais un « au moins X € » tiré du
   bas de notre propre fourchette (retex I1).
2. **Aucun argument de loyer, de rendement ni de cash-flow, aucune statistique de marché interne**
   (médiane DVF, liste de ventes, « sources publiques ») dans un message (retex I1). Ils restent dans
   le calcul interne.
3. **Face à un chiffre avancé par l'autre** (loyer, devis, offre concurrente) : ne pas lui opposer un
   autre chiffre ; demander la pièce qui le prouve (dernier loyer pratiqué et bail, contenu du devis,
   offre écrite) (retex I2, I8).
4. **Ton humain, sans style « IA »** : quelques paragraphes de longueurs inégales, pas de listes
   partout, pas de formules creuses, pas de gras, pas d'enthousiasme (retex I1).
5. **Pas de politesses en ouverture** (retex I1) : « Bonjour », puis le fait. Au plus **une**
   phrase d'empathie, seulement si la situation la justifie (succession, maison de famille), jamais en
   ouverture [B7, E8].
6. **Message qui force une décision** (retex G1) : l'option positive détaillée et prête à
   exécuter ; l'option négative courte et neutre ; la conséquence énoncée comme un fait ; **aucun
   amortisseur** (« aucun souci », « pas de problème », « dites-le-moi franchement »).
7. **Une affirmation négative** adressée à l'autre partie (« aucune annonce », « aucune offre ») se
   tente de réfuter avant l'envoi ; à défaut, écrire « en l'absence de preuve contraire » (retex G2).
8. **Ne rien promettre qui échappe à notre maîtrise** (accord d'un tiers, autorisation administrative)
   (retex L3).
9. **Aucun tiret cadratin** (le caractère U+2014), y compris dans un objet ou un PDF : ` - ` à la place
   (retex G4).

**Règles du socle** :

10. **Offre brève et ferme** : montant, motif court, validité ; polie, sans excès de remerciements,
    d'excuses ni de conditionnels ; un langage ferme obtient de meilleures contre-offres sans coût de
    satisfaction [B7] (moyen).
11. **Un seul motif de prix, tiré d'une contrainte réelle** (« le compte n'y est pas »), jamais du
    dénigrement (« ça ne vaut pas plus ») [A15, E2, E3] (moyen). Aucun jugement sur l'objet négocié.
12. **Deux ou trois arguments forts, pas davantage** : un argument moyen dilue [E10] ; les arguments
    accolés à une offre ambitieuse se contestent un par un [A14] (moyen à fort). Le détail va en pièce
    jointe (`immo_achat.md` §Messages pour l'immobilier).
13. **Ni ultimatum, ni langage contraignant** (« vous devez », « dernier délai ») ; une échéance réelle
    et motivée, suivie d'une phrase qui laisse le choix [E7, D16] (moyen).
14. **Précision modérée** : 3 ou 4 chiffres significatifs, jamais de centimes ; face à un
    professionnel, une phrase de méthode [A10, A11] (moyen).
15. **Prix d'abord net pour l'autre partie, puis honoraires ou frais à part** (immobilier : FAI et net
    vendeur) [E11] (faible, pour la clarté).
16. **Toute offre porte une date de validité** et ne dit que ce qu'on signerait tel quel [D4, D6,
    D-J1] (droit).
17. **L'oral pour découvrir, l'écrit pour confirmer** : un appel avant le premier écrit ; après un
    échange oral, un écrit bref qui reprend ce qui a été dit ; si le climat se tend, rester à l'écrit,
    bref et factuel [B11, E9] (fort, moyen).
18. **Aucune affirmation inexacte**, ni sur un fait, ni sur une alternative, ni sur une contrainte
    [D15] (droit). Aucune priorité, urgence ou coût de temps propre dévoilé [A6, B3].
19. **Coûts de portage** (bien vide) : au plus une fois, chiffrés et vérifiables, sans menace [E6]
    (fort) ; jamais un cadrage en pertes comme levier.

## Gabarits

Chaque crochet se remplit depuis une pièce, une sortie nommée ou le journal ; un crochet impossible à
remplir reste `[●]` et va dans « À vérifier avant envoi ». Objets et corps sans tiret cadratin.

**Réponse à une contre-proposition** (règles 3, 6, 10 à 13 ; `concessions.md` §Lire une
contre-proposition ; jamais d'acceptation dans le même échange [B2]) :

```
Objet : [objet] - votre proposition du [date]

Bonjour [interlocuteur],

[Ce que leur pièce confirme : poste, pièce, montant.] [Ce qui reste à prouver : "Pourriez-vous nous transmettre [la pièce : devis détaillé, bail, offre écrite] ?"]

Avec ces éléments, le compte n'y est pas à [leur chiffre]. [Une seule option :] Nous pouvons porter notre proposition à [montant] si [contrepartie précise], [ou : nous maintenons notre proposition de [montant]]. Elle est valable jusqu'au [date].

Bien cordialement,
[signature]
```

**Confirmation après un appel** (l'écrit qui confirme l'oral, règle 17 ; aucune politesse en
ouverture, ni remerciement) :

```
Objet : [objet] - suite à notre appel du [date]

Bonjour [interlocuteur],

Je reprends les points de notre appel : [deux ou trois faits dits par l'interlocuteur, tels qu'il les a dits].

Pour préparer notre proposition, pourriez-vous nous transmettre [pièces manquantes] ?

Bien cordialement,
[signature]
```

**Relance après silence** (après la pause convenue, sans pression ; `concessions.md` §Délais, silence
et dernier mot) :

```
Objet : [objet] - notre proposition du [date]

Bonjour [interlocuteur],

Je reviens vers vous au sujet de notre proposition du [date], valable jusqu'au [date]. [Un fait nouveau et vérifiable, s'il existe : pièce reçue, question restée ouverte.]

Pouvez-vous me dire où en est la réflexion de [la partie qui décide] ?

Bien cordialement,
[signature]
```

**Dernier mot** (structure G1 : option positive prête, option négative courte et neutre, conséquence
factuelle, aucun amortisseur ; seulement au palier de la limite, et seulement si c'est vrai) :

```
Objet : [objet] - notre dernière proposition

Bonjour [interlocuteur],

Nous avons revu le dossier une dernière fois. Notre proposition est de [montant], [conditions], valable jusqu'au [date et heure].

Si elle vous convient, [ce qui se passe ensuite, prêt à exécuter : rendez-vous chez le notaire, signature du devis révisé].

Sinon, nous en resterons là, sans difficulté de notre part. [Conséquence factuelle : "nous poursuivons nos autres recherches."] La décision vous appartient.

Bien cordialement,
[signature]
```

**Script d'appel à l'agent ou à l'interlocuteur** (questions qui présupposent un problème courant
[B12] ; rien sur le budget, la limite, l'urgence, le projet [A6] ; terrain immobilier :
`immo_achat.md` §Séquence) :

```
Ouverture : [qui j'appelle, au sujet de quoi, en une phrase]

Sur l'objet (questions qui présupposent un problème courant) :
- Quels problèmes de [humidité / toiture / chauffage / retards] avez-vous eus ?
- Quels travaux ont été repoussés, et pourquoi ?
- Quels points le diagnostic ou l'audit a-t-il relevés ?

Sur la transaction (questions ouvertes) :
- Depuis quand [le bien est-il en vente / le devis est-il établi] ? Quelles baisses ?
- Combien de visites, et quelles offres écrites avez-vous reçues ?
- Quel est le calendrier de [vendeur / entreprise], et qu'est-ce qui le contraint ?
- Qui décide et qui signe ?
- À quel prix pensez-vous que [vendeur] accepterait de conclure ?
- Comment se répartissent [net vendeur et honoraires / fourniture et pose] ?

À ne pas dire : budget, limite, cible, loyer ou rendement visé, délai qui nous presse, coup de cœur.
Après l'appel : écrit bref qui confirme les points importants ; coup "information" au journal.
```

**Demande de pièces** : le message type et la liste par type de bien sont dans
`skills/immo/references/pieces_a_demander.md` §Message type à l'agent (immobilier) ; pour un devis,
`artisans.md` §Entrées et outils. On demande les pièces **avant** l'offre
écrite (`socle.md` règle 9).

**Gabarit générique** (contexte, faits, proposition, contrainte, validité ; quand aucun gabarit du
terrain ne convient) :

```
Objet : [objet] - [proposition / réponse] du [date]

Bonjour [interlocuteur],

[Contexte en une phrase : ce dont on parle, pièce de référence et sa date.]

[Les faits, deux ou trois au plus, chacun avec sa pièce.]

[La contrainte, en une phrase : ce qui fait que le compte n'y est pas.] Nous vous proposons [montant et conditions, précision modérée].

Cette proposition est valable jusqu'au [date]. [Phrase qui laisse le choix : "Je reste disponible pour en parler de vive voix."]

Bien cordialement,
[signature]
```

## Avant envoi

Contrôle **binaire**, sous chaque brouillon, en liste « À vérifier avant envoi » ; un point non coché
reste visible pour l'investisseur :

- [ ] Chaque fait relu contre la pièce citée (nom, date, montant) ; aucune affirmation non prouvée,
      ni affirmation négative non tentée de réfutation (G2).
- [ ] Aucun chiffre interne : limite, cible, paliers, loyer, rendement, cash-flow, statistique DVF,
      budget, chiffre du foyer.
- [ ] Aucune grandeur inconnue (coût d'assurance, frais, date) présentée comme connue : une valeur
      absente se dit absente ou se demande.
- [ ] Une date de validité.
- [ ] Immobilier : prix en FAI et en net vendeur ; honoraires inconnus en `[●]`.
- [ ] Aucun tiret cadratin : `grep -c $'\u2014'` sur le brouillon rend `0`.
- [ ] Aucun amortisseur (« aucun souci », « pas de problème », « dites-le-moi franchement »), aucune
      politesse en ouverture, au plus une phrase d'empathie.
- [ ] Deux ou trois arguments au plus dans le corps ; une seule concession au plus, avec sa
      contrepartie.
- [ ] Destinataires (tous les décideurs ; pour une offre d'achat, tous les vendeurs), objet, pièce
      jointe présente et à jour (G4).
- [ ] **Offre immobilière, formule de l'offre** (`droit.md` §Formule de l'offre) : sans réserve de
      financement, « une offre précise acceptée peut former la vente, sans condition de financement
      écrite ; risque assumé par l'investisseur (`droit.md` §Offre et acceptation). » Et pour une **SCI** : « pas de délai de rétractation (D-J12), condition de prêt
      légale probablement absente (D10) : à écrire au compromis. »
- [ ] L'investisseur valide et envoie ; Claude n'envoie rien. Le coup est noté au journal après l'envoi réel.
