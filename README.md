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

### Deuxieme methode : modele de ligne ajuste (jusqu'a 1 THz)

Page 3, bouton « Line-model fit ». Apres la meme inversion exacte, le residu
`P^2` (l'aller-retour de la ligne) n'est plus garde point par point mais
ajuste aux moindres carres par un modele de ligne :

    -ln|P^2|  = 2 (a sqrt(f) + b f)          effet de peau + pertes dielectriques
    -arg(P^2) = 2 c sqrt(f) + 4 pi f tau     dispersion + delai

Les deux ajustements sont lineaires : pas d'optimiseur, pas de probleme de
convergence, et le bruit de mesure est moyenne sur toute la bande au lieu
d'etre transporte tel quel dans le S2P. La phase du modele etant analytique,
la racine `P = sqrt(P^2)` n'a plus d'ambiguite de branche.

**Quand l'utiliser.** |S21| est entierement porte par l'echo a `t = 2 tau`,
dont le niveau vaut le double des pertes de la ligne en dB. Vers 1 THz cet
echo approche le plancher de bruit du VNA : le fenetrage seul y laisse
plusieurs dB d'erreur, l'ajustement reste sous 0.25 dB. Sur une bande propre
et etroite, les deux methodes coincident (ecart < 0.05 dB).

Mesures synthetiques bruitees a -40 dB (`validation/thz/`, ligne 55 ohm,
300 ps, 2 dB a 10 GHz) — erreur maximale sur |S21| :

| Bande | standards | fenetrage (exact) | modele de ligne |
|---|---|---|---|
| WR-1.0, 750 GHz - 1.1 THz | OPEN seul | 8.50 dB | **0.23 dB** |
| WR-1.0, 750 GHz - 1.1 THz | SHORT seul | 5.77 dB | **0.14 dB** |
| WR-1.0, 750 GHz - 1.1 THz | OPEN + SHORT | 3.57 dB | **0.22 dB** |
| 10 MHz - 1 THz | OPEN + SHORT | 4.24 dB | **0.19 dB** |

Le delai est retrouve a 0.5 ps pres dans tous les cas.

**Limites.** Le modele impose sa forme : ligne uniforme et transition
d'entree constante sur la bande (G1 est ramene a sa mediane). Sur un fixture
a plusieurs discontinuites fortes, il faut rester sur le modele exact ou
passer au 2x-thru. Et quand l'echo est completement noye (rapport echo/bruit
tres faible), aucune methode ne le fait ressortir : voir ci-dessous.

### Plage dynamique : l'indicateur echo / bruit

Chaque extraction reporte `echo_snr_db` : le rapport entre le pic de l'echo
aller-retour et le plancher de bruit estime hors fenetre. En dessous de
35 dB, un avertissement signale que |S21| devient incertain — cas courant
au-dela de 500 GHz. Remedes, dans l'ordre : moyennage ou bande FI plus
etroite au VNA, fixture plus court, modele de ligne ajuste.

## Interface adaptative

La fenetre suit la taille que vous lui donnez, sans que rien ne disparaisse :

- **chaque page defile** (`gui/scrollable.py`, `ScrollableFrame`) : les barres
  verticale et horizontale n'apparaissent que si le contenu deborde, et la
  molette agit sur la page sous le pointeur ;
- **la barre d'onglets se replie** : les six onglets passent sur deux ou trois
  lignes au lieu de sortir de l'ecran ;
- **la page 1 empile ses deux colonnes** en dessous de 780 pixels de large ;
- **les textes longs se replient** au lieu d'elargir la fenetre ;
- **le pied de page** garde Back, Next et Exit visibles, le message d'etat
  absorbant la place restante.

La taille minimale est passee de 1040 x 700 a 560 x 420 : en dessous, tout
reste atteignable par defilement.

Ce qui s'adapte, page par page :

| Page | Adaptation |
|---|---|
| 1. Describe Fixture | deux colonnes empilees sous 780 px, schema du DUT redimensionne |
| 2. Specify Standards | schemas des standards redimensionnes, colonnes ponderees, resume replie |
| 3. Measure Standards | table de fichiers etiree, ligne lissage / passivite repliable, resultats sur colonnes ponderees |
| 4. Remove Fixture | cases entree / sortie repliables, chemin de mesure etire, compte rendu pleine largeur |
| 5. Save Fixture | cadres pleine largeur, chemin de sortie etire |
| 6. Batch Process | dossiers etires, journal pleine largeur |

Les schemas de fixture (`FixtureDiagram`) sont dessines dans un repere de
reference puis mis a l'echelle de leur taille reelle : ils suivent la largeur
de leur colonne au lieu d'imposer un defilement horizontal.

## Retirer les fixtures d'une mesure brute (page 4)

La page 4 corrige une mesure brute `ligne A + DUT + ligne B` :

1. calculer les fixtures en page 3 (OPEN et/ou SHORT, 2x-thru) ;
2. page 4, choisir le fichier `.s2p` de la mesure brute ;
3. cocher les cotes a retirer, puis « Remove Fixture and save ».

Le calcul applique `DUT = fixture_A^-1 ** mesure ** fixture_B^-1`. Le compte
rendu affiche la voie d'assemblage retenue, la perte d'insertion recuperee,
la passivite du DUT corrige et le residu de remise en cascade, qui doit
rester au niveau du bruit numerique. Le fichier corrige est ecrit dans le
dossier de sortie et devient tracable sous le nom `DUT_DEEMBEDDED`.

Un DUT corrige **non passif** signale des fixtures surestimes : trop de
pertes ont ete retirees. Dans ce cas, verifier d'abord l'indicateur
d'ajustement en page 3.

### Voir le DUT avec et sans de-embedding

Le graphe apparait **directement dans la page 4**, sous les boutons : la
transmission a gauche, la reflexion a droite, la mesure brute en trait
tiretee et le DUT seul en trait plein. Le titre de la vue transmission
rappelle le gain d'insertion moyen recupere.

La mesure brute est tracable des sa selection, avant meme la correction :
choisir le fichier suffit pour la voir dans la fenetre de trace.

Sur le jeu de validation (ligne A 300 ps, DUT 80 ps, ligne B 120 ps) le
graphe montre :

| Frequence | brut, lignes comprises | DUT seul | recupere |
|---|---|---|---|
| 1 GHz | -0.67 dB | -0.18 dB | +0.50 dB |
| 10 GHz | -2.23 dB | -0.57 dB | +1.65 dB |
| 20 GHz | -2.92 dB | -0.64 dB | +2.28 dB |
| 40 GHz | -4.20 dB | -0.97 dB | +3.24 dB |

Pour aller plus loin, deux boutons ouvrent la fenetre complete :



| Bouton | Ce qu'il montre |
|---|---|
| Plot before / after | la mesure brute et le DUT corrige superposes, S11 et S21 |
| Plot what the fixtures added | l'ecart entre les deux : gain d'insertion recupere en haut, rotation de phase enlevee en bas |

Les deux courbes restent disponibles dans la fenetre de trace sous les noms
« DUT measured (fixtures included) » et « DUT de-embedded (fixtures removed) »,
avec tous les formats habituels, domaine temporel compris.

Le format « Difference vs the first selected source » est general : il compare
n'importe quelles courbes cochees a la premiere d'entre elles.

## Indicateur de confiance : l'ajustement du modele

Apres extraction, l'outil reconstruit la mesure 1 port a partir du fixture
obtenu et la compare a la mesure reelle. L'ecart quadratique moyen
(`fit_rms`) dit si le modele a une discontinuite convient a votre fixture :

| Valeur | Lecture |
|---|---|
| < 0.02 | le modele decrit bien le fixture, extraction fiable |
| 0.02 a 0.05 | acceptable, verifier le resultat |
| > 0.05 | avertissement : plusieurs discontinuites fortes, standard imparfait ou bande insuffisante. Preferer le 2x-thru |

La valeur est affichee a cote de Z et du TTD, et journalisee avec son niveau
relatif en dB.

## Vue temporelle (fenetre de trace)

Le format « Time domain: impulse + step (TDR) » montre la reponse
impulsionnelle avec les deux fenetres en surimpression, et le profil
d'impedance quand le continu est present. C'est le moyen direct de voir si
les deux reflexions sont separables : si la zone verte (fenetre proche)
deborde sur la zone orange (fenetre lointaine), un titre rouge le signale.

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
