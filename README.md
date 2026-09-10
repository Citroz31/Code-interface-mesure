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
  reflect.py         S1P OPEN / SHORT -> S2P du fixture (seul ou combines)
  thru.py            decoupage du 2x-thru
  deembed.py         retrait des fixtures, traitement par lot
  models.py          FixtureResult, BatchItem
matrice_et_branche.py  interface Tkinter (6 pages)
tests/               tests pytest
CAHIER_DES_CHARGES.md  specification de la refonte
```

## Longueur de ligne

Page 3, champ « Effective εr » : la longueur affichee vaut
`c · TTD / sqrt(εr_eff)`. Avec εr_eff = 1 on obtient la longueur electrique
dans le vide ; renseigner la permittivite effective de la ligne (par exemple
~2,1 pour un cable PTFE, ~3 pour un microruban FR4) pour la longueur physique.
