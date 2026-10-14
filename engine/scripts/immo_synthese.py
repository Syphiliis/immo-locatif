#!/usr/bin/env python3
"""Synthèse Markdown de la sortie du moteur immo, et contrôle « aucune valeur du foyer » d'une analyse.

La sortie du moteur (`engine/scripts/immo_moteur.py`) pèse autant que le skill `/immo` : l'étude ne lit que cette synthèse
(au plus 80 lignes). Une clé attendue absente arrête tout (code 2, la clé nommée sur stderr) : jamais de
valeur par défaut. Les régimes fiscaux et les blocs de premier niveau sont lus tels que la sortie les
porte, sans liste en dur ; un bloc inconnu est signalé « non lu ». Le bloc `sortie` (revente, liquidation, TRI) a
sa section « Sortie », seulement s'il est présent.

`--verifier <analyse.md>` lit le foyer de l'investisseur (`foyer.json` : `--foyer <chemin>`, défaut
`immo-data/foyer.json` ou `$IMMO_DATA_DIR/foyer.json`, via `src.immo.foyer.contexte()`) et
les entrées foyer de la sortie (si `--sortie` est donnée : une étude arrêtée avant le moteur n'en a pas),
puis cherche chacune de leurs valeurs monétaires dans l'analyse, arrondie à l'euro (`1234`, `1 234`,
`1 234,xx`), ainsi que, pour un montant mensuel (clé `mensuel*`,
`mensualite*`), sa valeur ×12 de 100 € ou plus. Une source `.html` (livrable dérivé, HTML d'un
PDF) perd ses balises et ses entités avant la recherche. Les montants écrits en k€ restent ignorés (échappatoire
d'un montant du bien égal à un montant du foyer). Il nomme la clé et la ligne, jamais la valeur, et n'écrit rien ; une étude `.md` (nom sans
`-annexes`) de plus de 300 lignes est signalée sur stderr, sans changer le code.

Usage :
  python3 engine/scripts/immo_synthese.py --sortie <sortie.json>
  python3 engine/scripts/immo_synthese.py --sortie <sortie.json> --verifier immo-data/analyses/<slug>.md [--foyer <foyer.json>]
  python3 engine/scripts/immo_synthese.py --verifier immo-data/analyses/<slug>.md      # sans moteur

Codes de sortie : 0 ; 1 si `--verifier` trouve une valeur du foyer ; 2 si une clé attendue manque ou si
un fichier est illisible.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # engine/ : racine d'import de `src`
sys.path.insert(0, str(ROOT))

CONNUS = ("bien", "params_utilises", "acquisition", "financement", "scenarios", "prix_equilibre", "hcsf",
          "fiscalite", "sortie")
SCENARIOS = ("pessimiste", "realiste", "optimiste")
CHAMPS_REGIME = ("evaluable", "eligible", "raisons", "impot_total", "cash_flow_mensuel_net_net",
                 "rendement_net_net")
# Montants du foyer que porte la sortie elle-même (en plus de `contexte()`).
EFFET_FOYER = ("impot_foyer_seul", "impot_foyer_avec_bien", "report_entrant")
SEP = "[    ]"  # espace, insécable, fine insécable, fine


class CleAbsente(Exception):
    pass


def _cle(noeud, *chemin: str):
    """Valeur au chemin depuis la racine de la sortie ; CleAbsente nomme le chemin jusqu'à la clé manquante."""
    for i, cle in enumerate(chemin):
        if not isinstance(noeud, dict) or cle not in noeud:
            raise CleAbsente(".".join(chemin[: i + 1]))
        noeud = noeud[cle]
    return noeud


def euros(v, unite: str = " €") -> str:
    """À l'euro ; `unite=""` dans un tableau dont l'en-tête porte l'unité."""
    return "n/a" if v is None else f"{round(v):,}".replace(",", " ") + unite


def pct(v, unite: str = " %") -> str:
    return "n/a" if v is None else f"{v * 100:.2f}".replace(".", ",") + unite


def oui(v) -> str:
    return "n/a" if v is None else ("oui" if v else "non")


def synthese(d: dict, nom: str) -> list[str]:
    a = lambda k: _cle(d, "acquisition", k)  # noqa: E731
    f = lambda k: _cle(d, "financement", k)  # noqa: E731
    lignes = [f"# Synthèse du moteur - {nom}",
              "## Acquisition",
              f"prix net vendeur {euros(a('prix_net_vendeur'))} · frais d'acquisition "
              f"{euros(a('frais_acquisition'))} · travaux {euros(a('travaux'))} · coût total "
              f"{euros(a('cout_total'))}",
              "## Financement",
              f"emprunt {euros(f('emprunt'))} · apport {euros(f('apport'))} · taux nominal "
              f"{pct(f('taux_nominal'))} · durée {f('duree_mois')} mois · mensualité totale "
              f"{euros(f('mensualite_totale'))}",
              "## Scénarios (avant impôt)",
              "| scénario | loyer HC € | vacance % | rdt brut % | rdt net % | CF av. impôt €/mois "
              "| cash-on-cash % | enrichissement an 1 € |",
              "|---|---|---|---|---|---|---|---|"]
    for s in SCENARIOS:
        e = lambda k: _cle(d, "scenarios", s, "exploitation", k)  # noqa: E731
        i = lambda k: _cle(d, "scenarios", s, "indicateurs", k)  # noqa: E731
        lignes.append(f"| {s} | {euros(e('loyer_mensuel_hc'), '')} | {pct(e('vacance'), '')} | "
                      f"{pct(i('rendement_brut'), '')} | {pct(i('rendement_net'), '')} | "
                      f"{euros(i('cash_flow_mensuel_avant_impot'), '')} | {pct(i('cash_on_cash'), '')} | "
                      f"{euros(i('enrichissement_an1'), '')} |")

    lignes += ["## Prix d'équilibre (net vendeur, cash-flow avant impôt nul)",
               " · ".join(f"{s} {euros(_cle(d, 'prix_equilibre', s))}" for s in SCENARIOS)]

    lignes.append("## HCSF")
    if _cle(d, "hcsf", "calcule"):
        par = " ; ".join(f"{s} {pct(_cle(d, 'hcsf', 'par_scenario', s, 'taux_effort'))} "
                         f"{oui(_cle(d, 'hcsf', 'par_scenario', s, 'conforme'))}" for s in SCENARIOS)
        lignes.append(f"taux d'effort {pct(_cle(d, 'hcsf', 'taux_effort'))} (max "
                      f"{pct(_cle(d, 'hcsf', 'taux_effort_max'))}) · conforme : "
                      f"{oui(_cle(d, 'hcsf', 'conforme'))} · par scénario : {par}")
    else:
        lignes.append(f"non calculé : {_cle(d, 'hcsf', 'raison')}")
    entrees = d["hcsf"].get("entrees_foyer")
    lignes.append(f"entrees_foyer (clés seules) : {', '.join(entrees)}" if entrees
                  else "foyer : absent (sortie sans `--foyer`)")

    lignes += _fiscalite(d)
    if "sortie" in d:  # sortie du moteur sans bloc `sortie` : synthèse inchangée
        lignes += _sortie(d)
    lignes.append("## Hypothèses (toutes dans « À vérifier »)")
    lignes += [f"- {h}" for h in _cle(d, "fiscalite", "hypotheses")]
    inconnus = [k for k in d if k not in CONNUS]
    lignes.append(f"blocs non lus : {', '.join(inconnus) if inconnus else 'aucun'}")
    return lignes


def _fiscalite(d: dict) -> list[str]:
    scenarios = _cle(d, "fiscalite", "scenarios")
    lignes = [f"## Fiscalité (revenus {_cle(d, 'fiscalite', 'annee_revenus') or 'n/a'} ; source de la TMI : "
              f"{_cle(d, 'fiscalite', 'tmi_source') or 'n/a'})"]
    rangs, raisons, effets = [], {}, {}
    avec_distribution = False
    for s in SCENARIOS:
        for r in _cle(d, "fiscalite", "scenarios", s, "regimes"):
            g = lambda k: _cle(d, "fiscalite", "scenarios", s, "regimes", r, k)  # noqa: E731
            valeurs = {k: g(k) for k in CHAMPS_REGIME}
            foyer = None
            if scenarios[s]["regimes"][r].get("distribution"):  # `{}` : la SCI ne verse rien
                avec_distribution = True
                foyer = euros(_cle(d, "fiscalite", "scenarios", s, "regimes", r, "distribution",
                                   "cash_flow_mensuel_foyer"), "")
            rangs.append((s, r, valeurs, foyer))
            if valeurs["raisons"]:
                raisons.setdefault((r, tuple(valeurs["raisons"])), []).append(s)
            if "effet_foyer" in scenarios[s]["regimes"][r]:
                e = lambda k: _cle(d, "fiscalite", "scenarios", s, "regimes", r, "effet_foyer", k)  # noqa: E731
                effets.setdefault(r, []).append(f"{s} {euros(e('effet_marginal'))} (déficit global : "
                                                f"{oui(e('deficit_impute_global') > 0)})")
    entete = "| scénario | régime | évaluable | éligible | impôt total € | CF net-net €/mois | rdt net-net % |"
    lignes += [entete + (" CF foyer (distribution) €/mois |" if avec_distribution else ""),
               "|---" * (8 if avec_distribution else 7) + "|"]
    for s, r, v, foyer in rangs:
        lignes.append(f"| {s} | {r} | {oui(v['evaluable'])} | {oui(v['eligible'])} | {euros(v['impot_total'], '')} | "
                      f"{euros(v['cash_flow_mensuel_net_net'], '')} | {pct(v['rendement_net_net'], '')} |"
                      + (f" {foyer or ''} |" if avec_distribution else ""))
    for (r, motifs), scs in raisons.items():
        lignes.append(f"- raisons {r} ({', '.join(scs)}) : {' ; '.join(motifs)}")
    # L'impôt d'un régime est celui du bien seul ; effet_foyer donne l'effet du bien sur l'impôt du foyer.
    for r, valeurs in effets.items():
        lignes.append(f"- effet_foyer {r} (impôt du foyer avec le bien − sans, par an) : {' ; '.join(valeurs)}")
    return lignes


def _sortie(d: dict) -> list[str]:
    """Par scénario : TRI, VAN, plus-value, IS de la cession (IS de l'année N avec - sans la plus-value), boni net et
    reçu des associés à la sortie. Les raisons du bloc ne sont pas reprises : elles se lisent dans la sortie."""
    n = _cle(d, "bien", "sortie", "horizon_ans")
    taux = _cle(d, "bien", "sortie", "taux_actualisation")
    van = "VAN non calculée" if taux is None else f"VAN à {pct(taux)}"
    lignes = [f"## Sortie à {n} {'an' if n == 1 else 'ans'} (SCI à l'IS) : TRI et {van} des flux des associés ; IS "
              "de la cession = IS de "
              f"l'année {n} avec - sans la plus-value"]
    for s in SCENARIOS:
        g = lambda *chemin: _cle(d, "sortie", s, *chemin)  # noqa: E731
        is_cession = g("revente", "is_avec_cession") - g("revente", "is_sans_cession")
        lignes.append(f"- {s} : TRI {pct(g('tri'))} · VAN {euros(g('van'))} · plus-value "
                      f"{euros(g('revente', 'plus_value'))} · IS de la cession {euros(is_cession)} · boni net "
                      f"{euros(g('liquidation', 'boni_net'))} · reçu à la sortie "
                      f"{euros(g('liquidation', 'recu_associes'))}")
    return lignes


# --------------------------------------------------------------------------------------------
# --verifier
# --------------------------------------------------------------------------------------------

def _feuilles(noeud, chemin: tuple[str, ...] = ()):
    if isinstance(noeud, dict):
        for k, v in noeud.items():
            yield from _feuilles(v, chemin + (str(k),))
    elif isinstance(noeud, (int, float)) and not isinstance(noeud, bool):
        yield chemin, noeud


def _monetaire(chemin: tuple[str, ...], v: float) -> bool:
    nom = chemin[-1]
    return (math.isfinite(v) and abs(v) >= 100 and nom not in ("tmi", "annee")
            and not nom.startswith(("ponderation", "nb_")))


def valeurs_du_foyer(sortie: dict, chemin_foyer: str | None = None) -> list[tuple[str, float]]:
    """Feuilles monétaires de `contexte()` (foyer.json) et des blocs foyer de la sortie, par chemin de clé."""
    from src.immo import foyer
    trouvees = [(".".join(c), v) for c, v in _feuilles(foyer.contexte(chemin_foyer))]
    hcsf = sortie.get("hcsf", {})
    trouvees += [(".".join(("hcsf", "entrees_foyer") + c), v) for c, v in _feuilles(hcsf.get("entrees_foyer", {}))]
    for s, sc in sortie.get("fiscalite", {}).get("scenarios", {}).items():
        for r, regime in sc.get("regimes", {}).items():
            effet = regime.get("effet_foyer") or {}
            trouvees += [(f"fiscalite.scenarios.{s}.regimes.{r}.effet_foyer.{k}", effet[k])
                         for k in EFFET_FOYER if isinstance(effet.get(k), (int, float))]
    return [(cle, v) for cle, v in trouvees if _monetaire(tuple(cle.split(".")), v)]


# Ce qui, juste avant un nombre, en fait un numéro d'article (« art. 1843 », « CGI 156 », « R. 1331-23 »).
# Sans espace, « art.1843 » est déjà écarté par le point qui précède le nombre.
REFERENCES_DE_LOI = ("art.", "Art.", "article", "Article", "CGI", "R.", "L.", "D.")


def motif(v: float) -> re.Pattern:
    """`1234`, `1 234` (tous espaces), avec ou sans décimales, pour l'arrondi et la troncature à l'euro.

    Pas un numéro d'article (`REFERENCES_DE_LOI`), ni un nombre collé à une lettre (DPE ADEME, lot),
    ni un nombre suivi d'un tiret et de chiffres (mutation DVF, article à tiret)."""
    variantes = []
    for entier in sorted({math.floor(abs(v) + 0.5), math.floor(abs(v))}):
        t, groupes = str(entier), []
        while len(t) > 3:
            groupes.insert(0, t[-3:])
            t = t[:-3]
        variantes.append(f"{SEP}?".join([t] + groupes))
    references = "".join(f"(?<!{re.escape(r)}{SEP})" for r in REFERENCES_DE_LOI)
    return re.compile(rf"(?<![\d,.])(?<!\d{SEP})(?<![^\W\d_]){references}(?:{'|'.join(variantes)})(?:,\d+)?"
                      rf"(?!\d|{SEP}\d{{3}}(?!\d)|[^\W\d_]|-\d)")


LIGNES_MAX_ETUDE = 300
MENSUEL = re.compile(r"mensuel|mensualite")  # clé d'un montant mensuel : seule à recevoir le dérivé ×12


def _texte(analyse: Path) -> str:
    """Texte de l'analyse ; une source `.html` (livrable dérivé, HTML d'un PDF) perd ses balises, puis ses entités
    sont décodées (`&nbsp;` → insécable) : « 4<b>321</b> » et « 4&nbsp;321 » se lisent « 4321 » et « 4 321 »."""
    texte = analyse.read_text(encoding="utf-8")
    if analyse.suffix.lower() in (".html", ".htm"):
        texte = html.unescape(re.sub(r"<[^>]*>", "", texte))
    return texte


def verifier(sortie: dict, analyse: Path, chemin_foyer: str | None = None) -> int:
    controles = []
    for cle, v in valeurs_du_foyer(sortie, chemin_foyer):
        controles.append((cle, motif(v)))
        # ×12 seul : un montant mensuel annualisé, arrondi à l'euro par `motif`, gardé s'il fait 100 € ou plus. Pas de
        # ÷12 : trop de coïncidences pour aucune fuite trouvée.
        if MENSUEL.search(cle) and abs(v * 12) >= 100:
            controles.append((f"{cle} ×12", motif(v * 12)))
    lignes = _texte(analyse).splitlines()
    if analyse.suffix.lower() == ".md" and not analyse.stem.endswith("-annexes") and len(lignes) > LIGNES_MAX_ETUDE:
        print(f"avertissement : {analyse.name} fait {len(lignes)} lignes, plus de {LIGNES_MAX_ETUDE} lignes pour "
              "une étude : renvoyer le détail en annexe (<slug>-annexes.md)", file=sys.stderr)
    trouvees = [(cle, n) for n, ligne in enumerate(lignes, 1) for cle, m in controles if m.search(ligne)]
    if not trouvees:
        print(f"verifier : aucune valeur du foyer dans {analyse.name} ({len(controles)} valeurs contrôlées)")
        return 0
    for cle, n in trouvees:
        print(f"valeur du foyer : {cle} → ligne {n}")
    print(f"verifier : {len(trouvees)} occurrence(s) ; écrire « voir foyer.json », sans la valeur")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthèse de la sortie du moteur immo ; contrôle d'une analyse.")
    parser.add_argument("--sortie", help="JSON imprimé par engine/scripts/immo_moteur.py (requis sans --verifier)")
    parser.add_argument("--verifier", help="analyse .md ou livrable .html où aucune valeur du foyer ne doit figurer")
    parser.add_argument("--foyer", help="foyer.json lu par --verifier (défaut : immo-data/foyer.json)")
    args = parser.parse_args(argv)
    if not args.sortie and not args.verifier:
        print("erreur : --sortie requis (ou --verifier seul, pour une étude sans moteur)", file=sys.stderr)
        return 2
    try:
        sortie = json.loads(Path(args.sortie).read_text(encoding="utf-8")) if args.sortie else {}
        if args.verifier:
            return verifier(sortie, Path(args.verifier), args.foyer)
        texte = "\n".join(synthese(sortie, Path(args.sortie).name))
    except CleAbsente as exc:
        print(f"erreur : clé attendue absente de la sortie du moteur : {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f"erreur : {type(exc).__name__} : {exc}", file=sys.stderr)
        return 2
    print(texte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
