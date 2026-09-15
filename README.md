# Code-interface-mesure — Automatic Fixture Removal (AFR)

Outil de retrait de fixtures (de-embedding) pour mesures VNA : extraction des
fixtures A et B a partir d'un 2x-thru et/ou de standards OPEN / SHORT, puis
retrait des fixtures autour du DUT.

## Installation

```
python -m venv .venv
.venv\Scripts\activate          (Windows)   |   source .venv/bin/activate (Linux/macOS)
pip install -r requirements.txt
```

## Lancement

```
python matrice_et_branche.py
```

## Tests (sans interface graphique)

```
python -m pytest tests -q
```

Les tests utilisent des fixtures synthetiques (ligne 55 ohm, 300 ps) : voir
`tests/test_afr.py` pour les tolerances.

## Structure

```
afr/                 noyau de calcul (numpy / scikit-rf), sans Tkinter
  io.py              lecture / ecriture Touchstone
  signal.py          filtrage, interpolation, fenetrage temporel
  metrics.py         delai (TTD), longueur, impedance TDR, passivite
  reflect.py         S1P OPEN / SHORT -> S2P (modele a une discontinuite)
  thru.py            decoupage du 2x-thru
  deembed.py         retrait des fixtures, traitement par lot
  models.py          FixtureResult, BatchItem
gui/plot_window.py   fenetre de trace (sources, S-parametres, formats, zoom)
matrice_et_branche.py  interface Tkinter (6 pages)
validation/          jeu de validation synthetique (S1P, references, S2P extraits)
tests/               tests pytest
CAHIER_DES_CHARGES.md  specification de la refonte
```

## Methode d'extraction S1P -> S2P

Le fixture est modelise par une transition d'entree (coefficient G1) suivie
d'une ligne. La mesure 1 port s'inverse alors exactement :

    P^2 * Gamma_L = (Gamma_mesure - G1) / (1 - G1 * Gamma_mesure)

Les reflexions multiples a l'interieur du fixture sont donc prises en compte,
et le residu ne contient plus qu'un seul echo. Avec OPEN **et** SHORT, G1 est
resolu algebriquement, sans aucun fenetrage : c'est la methode la plus precise.

L'ancienne formule du premier ordre reste disponible en page 3 (bouton
« First order ») pour comparaison.

## Standards de reflexion : OPEN, SHORT, ou les deux

OPEN et SHORT s'utilisent independamment. Le choix se fait en page 3 :

| Mode | Comportement |
|---|---|
| Automatique (defaut) | combine OPEN + SHORT quand les deux fichiers d'un cote sont charges, sinon utilise celui qui est disponible |
| OPEN only | ignore les fichiers SHORT |
| SHORT only | ignore les fichiers OPEN |
| OPEN + SHORT only | exige les deux, avertit si un seul est charge |

Les extractions individuelles sont toujours calculees et exportees
(`OPEN_A_CONVERTED.s2p`, `SHORT_A_CONVERTED.s2p`) ; la combinaison ajoute
`REFLECT_A_CONVERTED.s2p`. Quand les deux existent, l'ecart entre les deux
extractions est mesure : au-dela de 1 dB un avertissement invite a verifier
les standards ou a n'en garder qu'un.

## Fixture court, bande etroite : preferer OPEN + SHORT

Le fenetrage temporel ne separe la reflexion d'entree de celle du bout de
ligne que si la resolution temporelle (1 / bande mesuree) est nettement plus
courte que l'aller-retour dans le fixture (2 x TTD). Sinon les deux fenetres
se recouvrent, la reflexion d'entree est surestimee et l'impedance avec elle.

Avec OPEN **et** SHORT du meme cote, la reflexion d'entree est resolue
algebriquement, sans aucun fenetrage : le probleme disparait. Mesure
synthetique d'un fixture de 70 ps sur 2 - 20 GHz (resolution 56 ps pour un
aller-retour de 140 ps, donc recouvrement) :

| Methode | reflexion d'entree (attendu 0.048) | Z (attendu 55) | erreur S21 |
|---|---|---|---|
| OPEN seul | 0.096 | 52.2 ohm | 1.15 dB |
| OPEN + SHORT | 0.048 | 55.0 ohm | 0.57 dB |

Elargir la bande a 1 - 40 GHz supprime le recouvrement et ramene l'ecart de
l'OPEN seul a 0.33 dB.

## Lignes d'entree et de sortie de longueurs differentes

La cascade utilisee est `mesure = fixture_entree ** DUT ** fixture_sortie`.
Aucune symetrie n'est supposee : l'outil choisit la voie la plus rigoureuse
parmi celles que les standards charges autorisent.

| Standards disponibles | Voie utilisee | Hypothese |
|---|---|---|
| OPEN / SHORT des deux cotes | chaque cote extrait directement | aucune |
| Deux 2x-thru (A + A', puis B' + B) | un cote par 2x-thru | chaque 2x-thru est symetrique |
| OPEN / SHORT d'un cote + 2x-thru | l'autre cote par cascade inverse `B = A^-1 ** thru` | aucune, c'est exact |
| 2x-thru seul | decoupage en deux moities identiques | les deux lignes sont identiques |
| OPEN / SHORT d'un seul cote | l'autre cote est le miroir | les deux lignes sont identiques |

Les deux dernieres lignes declenchent un avertissement : ce sont les seules
qui supposent la symetrie. Pour des longueurs differentes, mesurer un OPEN ou
un SHORT sur au moins un des deux cotes suffit a lever l'hypothese.

Des que le 2x-thru est charge, la cascade des deux fixtures extraits est
comparee a la mesure : un ecart superieur a 0,5 dB sur S21 est signale.

## Mesure du DUT monte entre les deux lignes

Le standard « Fixtured DUT » sert de controle. Apres extraction, le DUT est
de-embedde et l'outil verifie qu'il reste passif et que la remise en cascade
redonne la mesure. Un DUT de-embedde non passif signale des fixtures
surestimes. Le resultat est disponible dans la fenetre de trace sous le nom
`DUT_DEEMBEDDED`.

## Mesures en bande et bord de bande

- Une mesure qui ne commence pas pres de DC (extenseur millimetrique, guide
  d'onde) bascule automatiquement en traitement passe-bande : aucune
  extrapolation vers les basses frequences n'est inventee.
- Le spectre est prolonge de 25 % au-dela de f_max (et sous f_min en
  passe-bande) et seul ce prolongement est attenue : les resultats restent
  exploitables jusqu'a la derniere frequence mesuree.
- Des avertissements signalent un pas de frequence trop grand (repliement),
  un fixture trop court pour la bande (fenetres qui se chevauchent), une
  mesure d'entree elle-meme non passive (|Gamma| > 1, defaut de calibration)
  et les points ramenes a la limite passive.
- Sans continu dans la bande, l'impedance ne vient plus de la reponse en
  echelon (non definie) mais de la reflexion proche, Z = Z0 (1 + G1)/(1 - G1).
  Elle est donc affichee au lieu d'un tiret.

## Longueur de ligne

Page 3, champ « Effective εr » : la longueur affichee vaut
`c · TTD / sqrt(εr_eff)`. Avec εr_eff = 1 on obtient la longueur electrique
dans le vide ; renseigner la permittivite effective de la ligne (par exemple
~2,1 pour un cable PTFE, ~3 pour un microruban FR4) pour la longueur physique.
