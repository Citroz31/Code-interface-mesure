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

Modele a une discontinuite (defaut), bande 1 - 40 GHz :

| Extraction | erreur S21 | erreur de phase S21 | ecart sur S11 | TTD |
|---|---|---|---|---|
| OPEN seul | 0.023 dB | 0.04 deg | 0.0075 | 300.0 ps |
| SHORT seul | 0.034 dB | 0.04 deg | 0.0074 | 300.0 ps |
| OPEN + SHORT | 0.028 dB | 0.00 deg | 0.0003 | 300.0 ps |

Reference : TTD = 300 ps, Z = 55 ohm. L'ancien modele du premier ordre
donnait un ecart |S11| de 0.044 sur les trois methodes : la difference tient
a l'onde stationnaire, desormais reconstruite.

## Ce qu'il faut attendre dans le simulateur

- `|S21|` et la phase de S21 des fichiers extraits se superposent a la
  reference sur toute la bande (ecart < 0.05 dB).
- `S11` extrait reproduit maintenant l'ondulation de l'onde stationnaire de
  la reference, et non plus une valeur constante : avec OPEN + SHORT l'ecart
  tombe a 0.0003 en lineaire. Le modele a une discontinuite reconstruit les
  reflexions multiples a l'interieur du fixture.
- Sur une mesure reelle, la comparaison la plus parlante reste : DUT
  de-embedde avec le fixture extrait contre DUT de-embedde avec le fixture
  de reference.

## Cas limites couverts par les tests

| Situation | Comportement |
|---|---|
| Mesure en bande (extenseur mmW, sans DC) | bascule automatique en mode passe-bande, aucune extrapolation vers DC |
| Fixture court devant 1 / bande | fenetres proche et lointaine reduites, avertissement |
| Pas de frequence trop grand | avertissement de repliement temporel, pas de frequence a viser |
| Bruit qui pousse le module de S21 au-dessus de 1 | ramene a la limite passive, nombre de points signale |

## Relancer

```
pip install -r requirements.txt
python validation/run_validation.py
```
