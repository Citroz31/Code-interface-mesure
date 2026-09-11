# Jeu de validation — fixture A synthetique

Ce dossier permet de verifier l'extraction S1P -> S2P sans mesure reelle et
de comparer les resultats dans un simulateur.

## Modele du fixture A (a reconstruire dans le simulateur)

| Parametre | Valeur |
|---|---|
| Type | ligne de transmission uniforme entre deux ports 50 ohm |
| Impedance caracteristique Zc | 55 ohm |
| Delai de propagation (TTD) | 300 ps |
| Pertes | 1 dB a 10 GHz sur toute la ligne, variation en sqrt(f) (alpha = 0.1151 Np * sqrt(f / 10 GHz)) |
| Permittivite effective | 3.0, soit une longueur physique de 51.93 mm (c * 300 ps / sqrt(3)) |
| Bande | 10 MHz a 50 GHz, pas 10 MHz (5000 points), format RI, Z0 = 50 ohm |

Dans ADS : `TLINP` avec Z = 55 ohm, L = 51.93 mm, K = 3.0, A = 0.1151 Np/m
ramene a la longueur (ou attenuation totale 1 dB a 10 GHz), F = 10 GHz,
dependance `sqrt(f)`.

## Fichiers

| Fichier | Contenu |
|---|---|
| `OPEN_A.s1p` | mesure 1 port du fixture termine par un OPEN ideal : Gamma = S11 + S21^2 / (1 - S22) |
| `SHORT_A.s1p` | mesure 1 port du fixture termine par un SHORT ideal : Gamma = S11 - S21^2 / (1 + S22) |
| `FIXTURE_A_reference.s2p` | S2P exact du fixture (reference pour la comparaison) |
| `THRU_2X_reference.s2p` | 2x-thru exact (fixture A + fixture A retourne) |
| `FIXTURE_A_from_OPEN.s2p` | fixture extrait de OPEN_A.s1p seul |
| `FIXTURE_A_from_SHORT.s2p` | fixture extrait de SHORT_A.s1p seul |
| `FIXTURE_A_from_OPEN_SHORT.s2p` | fixture extrait des deux mesures combinees (methode recommandee) |
| `run_validation.py` | regenere les trois S2P extraits avec le noyau `afr/`, ecrit `THRU_2X_half_in.s2p`, affiche les ecarts et trace `validation_plot.png` |

## Resultats obtenus (extraction executee sur ces fichiers)

| Extraction | S21 ecart max 1-40 GHz | S21 ecart max 45-50 GHz | TTD | Z |
|---|---|---|---|---|
| OPEN seul | 0.064 dB / 0.12 deg | 0.041 dB / 0.40 deg | 300.0 ps | 56.8 ohm |
| SHORT seul | 0.064 dB / 0.12 deg | 0.041 dB / 0.40 deg | 300.0 ps | 53.1 ohm |
| OPEN + SHORT | 0.064 dB / 0.12 deg | 0.035 dB / 0.08 deg | 300.0 ps | 54.9 ohm |

Reference : TTD = 300 ps, Z = 55 ohm.

## Ce qu'il faut attendre dans le simulateur

- `|S21|` et la phase de S21 des fichiers extraits se superposent a la
  reference sur toute la bande (ecart < 0.1 dB, < 0.5 deg).
- `S11` extrait est la reflexion proche seule (Gamma_1 = (55 - 50)/(55 + 50)
  = 0.048, soit -26.4 dB, quasi constant). La reference contient en plus
  l'onde stationnaire entre les deux bouts de ligne (ondulation jusqu'a
  -20 dB) : l'ecart sur S11 est attendu, il traduit l'hypothese
  « S22 = S11 » d'une extraction a partir d'un seul cote. Le de-embedding
  reste correct au premier ordre pour un fixture faiblement desadapte.
- Sur une vraie mesure, la comparaison pertinente est : DUT de-embedde avec
  le fixture extrait contre DUT de-embedde avec le fixture de reference.

## Relancer

```
pip install -r requirements.txt
python validation/run_validation.py
```
