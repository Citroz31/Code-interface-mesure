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

## Chaine complete : ligne A + DUT + ligne B

Le dossier contient aussi de quoi verifier le de-embedding de bout en bout,
avec deux lignes **de longueurs differentes** :

| Element | Zc | TTD | Pertes |
|---|---|---|---|
| Ligne A (entree) | 55 ohm | 300 ps | 1.0 dB a 10 GHz |
| DUT | 62 ohm | 80 ps | 0.4 dB a 10 GHz |
| Ligne B (sortie) | 48 ohm | 120 ps | 0.6 dB a 10 GHz |

| Fichier | Contenu |
|---|---|
| `RAW_MEASUREMENT.s2p` | la mesure brute : ligne A + DUT + ligne B |
| `DUT_reference.s2p` | le DUT seul, reference exacte |
| `OPEN_B.s1p`, `SHORT_B.s1p` | standards du cote sortie |
| `FIXTURE_B_reference.s2p` | ligne B exacte |
| `DUT_deembedded.s2p` | resultat du de-embedding (ecrit par le script) |

Resultat obtenu, fixtures **extraits** de leurs propres standards (pas les
references), bande 1 - 40 GHz :

| Fixtures utilises | erreur S21 | erreur de phase | ecart sur S11 |
|---|---|---|---|
| exacts | 0.0000 dB | 0.000 deg | 0.0000 |
| extraits des OPEN / SHORT | 0.0410 dB | 0.002 deg | 0.0007 |

La correction retire 2.18 dB de perte d'insertion en moyenne, 3.24 dB au plus.

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

## Jeu submillimetrique : `thz/` (jusqu'a 1 THz)

Le sous-dossier `thz/` couvre les bandes ou l'echo aller-retour approche le
plancher de bruit du VNA. Meme ligne que ci-dessus, mais plus dissipative
(2 dB a 10 GHz, soit 20 dB a 1 THz en aller simple, donc un echo a -40 dB), et
les mesures 1 port portent un bruit gaussien de -40 dB.

| Fichier | Contenu |
|---|---|
| `generate_thz.py` | genere tout le jeu, sans aucune dependance (Python standard seul) |
| `OPEN_WR1.s1p`, `SHORT_WR1.s1p` | bande WR-1.0 : 750 GHz - 1.1 THz, pas 250 MHz, 1401 points, bruit -40 dB |
| `OPEN_BROADBAND.s1p`, `SHORT_BROADBAND.s1p` | 10 MHz - 1 THz d'un seul tenant, pas 500 MHz, 2001 points |
| `FIXTURE_WR1_reference.s2p`, `FIXTURE_BROADBAND_reference.s2p` | references exactes, sans bruit |
| `run_validation_thz.py` | extrait avec les deux modeles, ecrit les S2P et affiche le tableau d'ecarts |

Erreur maximale sur |S21| (bords de bande ecartes de 5 %) :

| Bande | standards | `single_discontinuity` | `line_fit` |
|---|---|---|---|
| WR-1.0 | OPEN seul | 8.50 dB | **0.23 dB** |
| WR-1.0 | SHORT seul | 5.77 dB | **0.14 dB** |
| WR-1.0 | OPEN + SHORT | 3.57 dB | **0.22 dB** |
| 10 MHz - 1 THz | OPEN seul | 6.20 dB | **0.19 dB** |
| 10 MHz - 1 THz | SHORT seul | 6.21 dB | **0.19 dB** |
| 10 MHz - 1 THz | OPEN + SHORT | 4.24 dB | **0.19 dB** |

Le delai est retrouve entre 299.5 et 300.4 ps dans tous les cas (reference
300 ps), et l'ecart sur |S11| tombe a 0.0002 - 0.001 avec le modele de ligne.

Ce qu'il faut en retenir :

- le fenetrage n'est pas faux, il est **limite par la plage dynamique** :
  sans bruit, il reste a 0.03 dB a 1 THz. C'est le bruit du VNA, transporte
  point par point dans le S2P, qui coute les dB ;
- le modele de ligne moyenne ce bruit sur toute la bande et redonne un S2P
  exploitable ;
- quand l'echo est completement noye, aucune des deux methodes ne le
  restitue. C'est le role de l'indicateur `echo_snr_db` (avertissement en
  dessous de 35 dB) : mieux vaut signaler la mesure que livrer un S2P faux.

## Relancer

```
pip install -r requirements.txt
python validation/run_validation.py
python validation/thz/run_validation_thz.py
```
