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

## Mesures en bande et bord de bande

- Une mesure qui ne commence pas pres de DC (extenseur millimetrique, guide
  d'onde) bascule automatiquement en traitement passe-bande : aucune
  extrapolation vers les basses frequences n'est inventee.
- Le spectre est prolonge de 25 % au-dela de f_max (et sous f_min en
  passe-bande) et seul ce prolongement est attenue : les resultats restent
  exploitables jusqu'a la derniere frequence mesuree.
- Des avertissements signalent un pas de frequence trop grand (repliement),
  un fixture trop court pour la bande (fenetres qui se chevauchent) et les
  points ramenes a la limite passive.

## Longueur de ligne

Page 3, champ « Effective εr » : la longueur affichee vaut
`c · TTD / sqrt(εr_eff)`. Avec εr_eff = 1 on obtient la longueur electrique
dans le vide ; renseigner la permittivite effective de la ligne (par exemple
~2,1 pour un cable PTFE, ~3 pour un microruban FR4) pour la longueur physique.
