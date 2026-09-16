# Cahier des charges — Refonte de l'outil AFR (Automatic Fixture Removal)

Version 0.4 — lots 0 à 3 livrés ; extraction S1P exacte, mesures en bande, fixtures dissymétriques.

## 1. Contexte

Le script `matrice_et_branche.py` (≈ 5 000 lignes) est un assistant Tkinter en 6 pages qui reproduit
le flux Keysight AFR : description du fixture, choix des standards, mesure des standards
(2x-thru, open, short), extraction des fixtures A et B, de-embedding du DUT, sauvegarde.

La première correction (branche `claude/s2p-s1p-calculation-1e3gwd`) a porté sur
`build_afr_s2p_from_s1p` : signe du SHORT, fenêtre de S11, branche de la racine carrée,
impédance, délai. Le présent document propose la suite : traitement complet OPEN/SHORT,
calcul du délai (« TDD ») de chaque ligne, refonte modulaire et pistes d'amélioration.

## 2. État des lieux du code actuel

Constats utiles pour dimensionner la refonte :

| Sujet | Constat |
|---|---|
| Structure | Une seule classe `AFRWizardComplete(tk.Tk)` mélange interface, calcul RF, fichiers et tracés. Impossible à tester sans ouvrir une fenêtre. |
| Traces | Plusieurs centaines de `print(...)` de debug dans le flux nominal, blocs `if self.DEBUG_PLOT` avec `plt.show()` bloquants. |
| Duplication | Deux chaînes temporelles coexistent : `frequency_to_time`/`gate_response` (fenêtre fixe de 15 échantillons, sans grille DC) pour le 2x-thru, et `to_time_domain`/`gate_to_freq` (fenêtre adaptative, grille DC, Kaiser) pour le S1P. Le conditionnement des matrices ABCD est calculé trois fois par point dans `remove_fixture`. |
| Code mort | `extract_ttd`, `extract_average_z`, `continuity_metric` peu ou pas utilisés ; nombreux blocs commentés ; `load_s1p`/`load_s2p` doublonnent `rf.Network`. |
| Physique | `build_half_thru` : S11 et S22 obtenus par une fenêtre fixe de 15 points quelle que soit la bande ; impédance = moyenne de Re(Z11) (≈ 0 pour une ligne, sans signification) ; délai = moyenne du retard de groupe sur toute la bande, bruit compris. |
| Fixture B | En mode « open/short A seulement », le fixture B est le port-swap du demi-thru ; les résultats OPEN_B/SHORT_B ne sont pas combinés avec le 2x-thru. |
| Pages 4 et 6 | « Apply Correction » et « Batch Process » sont des maquettes (message d'information, pas de traitement). |
| Multiport | Les clés `OPEN_Pn`, `SHORT_Pn`, `THRU_p_q` existent côté interface, mais l'extraction ne gère que le cas 2 ports. |
| Dépendances | numpy, scipy, scikit-rf, pywt, matplotlib ; aucune liste de dépendances ni test dans le dépôt (le dépôt GitHub contient des fichiers vides). |

## 3. Objectifs demandés

1. **SHORT S1P → S2P** : traitement explicite du SHORT (fait en partie : signe Γ = −1). À compléter par la combinaison OPEN + SHORT quand les deux existent (§ 4.2).
2. **« TDD » de chaque ligne** : délai de propagation (TTD) et longueur physique déduite via ε_r effectif (décision § 6).
3. **Code propre et modulaire** : séparation calcul / interface / fichiers, tests automatiques, journalisation.
4. **Améliorations** : méthodes de calcul plus robustes, validations, multiport.

## 4. Méthodes de calcul proposées

Notations : fixture = 2 ports, port 1 côté VNA, port 2 côté DUT. Γ_L = +1 (OPEN), −1 (SHORT).
Mesure 1 port du fixture terminé par un standard :

    Γ_mes = S11 + S21² · Γ_L / (1 − S22 · Γ_L)

### 4.1 Modèle retenu : une discontinuité (exact)

Le fixture est vu comme une transition d'entrée de coefficient Γ₁ suivie d'une propagation aller P :

    S11 = Γ₁ (1 − P²) / (1 − Γ₁² P²)
    S21 = (1 − Γ₁²) P / (1 − Γ₁² P²)

Terminé par un standard Γ_L, il mesure Γ = Γ₁ + (1 − Γ₁²) P² Γ_L / (1 + Γ₁ P² Γ_L), relation qui s'inverse **exactement** :

    P² Γ_L = (Γ_mes − Γ₁) / (1 − Γ₁ Γ_mes)        (1)

Retirer la transition d'entrée ne demande donc aucune approximation : les réflexions multiples internes sont prises en compte, et le résidu (1) ne contient plus qu'un seul écho, à t = 2τ, que l'on peut fenêtrer sans rien perdre du signal utile.

- **Un seul standard** : Γ₁ est la réflexion proche, obtenue en fenêtrant autour de t = 0.
- **OPEN et SHORT** : P² est commun aux deux mesures et Γ_L change de signe, donc (1) donne Γ₁ sans aucun fenêtrage, par la racine de module < 1 de

      (Γ_o + Γ_s) Γ₁² − 2 (1 + Γ_o Γ_s) Γ₁ + (Γ_o + Γ_s) = 0        (2)

  C'est la méthode la plus précise. Sur une ligne synthétique, S11 et S21 sont exacts.

### 4.1 bis Deuxième méthode : modèle de ligne ajusté (`line_fit`)

Le résidu (1) est l'aller-retour P² d'une ligne. Il est ajusté aux moindres carrés par

    −ln|P²|  = 2 (a √f + b f)          effet de peau + pertes diélectriques
    −arg(P²) = 2 c √f + 4 π f τ        dispersion + délai

Deux moindres carrés **linéaires** (module, puis phase déroulée) : aucun optimiseur, aucune divergence possible, et le bruit est moyenné sur toute la bande. La phase du modèle étant analytique, la racine P = √(P²) n'a plus d'ambiguïté de branche.

Intérêt : |S21| est porté par l'écho à t = 2τ, dont le niveau vaut le double des pertes en dB. Entre 500 GHz et 1 THz cet écho frôle le plancher de bruit du VNA ; le fenêtrage y laisse 3 à 8 dB d'erreur, l'ajustement reste sous 0,25 dB (jeu `validation/thz/`). Contrepartie : le modèle impose une ligne uniforme et une transition d'entrée constante sur la bande (Γ₁ ramené à sa médiane).

Diagnostic associé : `echo_snr_db`, rapport entre le pic de l'écho et le plancher de bruit hors fenêtre. En dessous de 35 dB, l'extraction est signalée comme incertaine — quand l'écho est totalement noyé, aucune méthode ne le restitue et il faut le dire plutôt que de livrer un S2P faux.

### 4.2 Ancienne formule du premier ordre (conservée pour comparaison)

S21² = Γ_far / Γ_L · (1 − S11²) à partir de la réflexion lointaine fenêtrée. Elle néglige les réflexions multiples : sur un fixture court et désadapté (100 Ω, 20 ps, 200 GHz) l'erreur atteint 3,4 dB contre 0,25 dB pour le modèle exact. Elle reste sélectionnable en page 3.

### 4.2 bis Mesures en bande

Une mesure qui ne commence pas près de DC (extenseur millimétrique, guide d'onde) est traitée en passe-bande : grille uniforme depuis f_min, enveloppe complexe, extrapolation des deux côtés de la bande, branche de la racine carrée ancrée sur le délai du pic. Forcer le traitement passe-bas sur une telle mesure coûtait jusqu'à 3 dB d'erreur.

### 4.3 2x-thru (fixture A + B)

- Remplacer la fenêtre fixe de 15 échantillons par la même chaîne temporelle que § 4.1 (grille DC, fenêtre adaptative centrée sur le pic).
- Conserver la relation `S21_half² = S21_2x · (1 − S11_half²)` (déjà utilisée) avec la même racine carrée continue.
- **Option de référence** : scikit-rf implémente l'IEEE P370 (`skrf.calibration.IEEEP370_SE_NZC_2xThru` et `IEEEP370_SE_ZC_2xThru`, cette dernière corrige l'impédance à partir du DUT fixturé). Proposition : l'ajouter comme méthode sélectionnable et l'utiliser comme référence pour valider notre découpage maison.
- Fixtures A ≠ B : combiner le 2x-thru avec les réflexions (OPEN/SHORT B) pour ne plus supposer B = port-swap de A.

### 4.3 bis Fixtures dissymétriques (longueurs différentes)

Cascade de référence : `mesure = fixture_entrée ** DUT ** fixture_sortie`, et `2x-thru = fixture_entrée ** fixture_sortie`.

Un 2x-thru dissymétrique **n'est pas séparable** à lui seul : le découpage en deux moitiés identiques suppose la symétrie. Les voies rigoureuses, par ordre de préférence, sont implémentées dans `afr/thru.py` (`complete_pair`) :

1. **OPEN / SHORT des deux côtés** : chaque fixture est extrait directement, aucune hypothèse.
2. **Deux 2x-thru** (A + A' puis B' + B) : chacun est symétrique et caractérise un côté.
3. **OPEN / SHORT d'un côté + 2x-thru** : l'autre côté par cascade inverse, `B = A⁻¹ ** thru`, exact.
4. **2x-thru seul** ou **un seul côté mesuré** : symétrie supposée, avertissement émis.

Contrôles associés : `pair_residual` compare `A ** B` au 2x-thru mesuré (écart sur S21 en dB et en degrés) ; `check_fixtured_dut` de-embedde la mesure du DUT fixturé et vérifie sa passivité, un résultat non passif signalant des fixtures surestimés.

### 4.4 De-embedding

- Remplacer la boucle ABCD par les opérateurs scikit-rf (`fixture_a.inv ** dut ** fixture_b.inv`), plus lisible et gérant le multiport.
- Conserver le contrôle de conditionnement, mais une seule fois par fréquence et journalisé (pas de `print` par point).
- Contrôle de causalité/passivité du résultat.

### 4.5 Délai de ligne (TTD, « time delay »)

Trois estimateurs, tous disponibles, un affiché par défaut :

1. **Pente de phase** de S21 (régression linéaire sur une bande choisie, par défaut 10 % – 60 % de f_max) → délai moyen, insensible au bruit HF. Défaut proposé.
2. **Retard de groupe** −dφ/dω lissé, médiane sur la bande → sensible à la dispersion, utile pour l'affichage en fonction de la fréquence.
3. **Pic temporel** de la réponse impulsionnelle avec interpolation parabolique → indépendant de la phase, sert de contrôle.

Sortie : délai en ps, longueur électrique, longueur physique si ε_r effectif renseigné.

### 4.6 Impédance

- Profil TDR : Z(t) = Z0 · (1 + ρ(t)) / (1 − ρ(t)) à partir de la réponse en échelon (intégrale de la réponse impulsionnelle fenêtrée). Affichage de Z le long du fixture et valeur au milieu de la ligne.
- Valeur scalaire = médiane de Z(t) sur la zone [0,2τ · 0,8τ] plutôt qu'une moyenne fréquentielle.

### 4.7 Mode mixte — hors périmètre (décision § 6)

Conservé pour mémoire. Pour un fixture 4 ports (paire différentielle) : conversion single-ended → mixed-mode avec `Network.se2gmm`, extraction de Sdd11, Sdd21 (souvent notés Tdd11, Tdd21), Scc et Sdc. Délai et impédance différentiels (Zdiff) dérivés de Sdd.

### 4.8 Contrôles qualité (communs)

Passivité (valeur singulière max ≤ 1), réciprocité, résidu de reconstruction, cohérence OPEN/SHORT, avertissements affichés dans l'interface (pas seulement en console).

## 5. Architecture modulaire proposée

```
afr/                      noyau de calcul, sans Tkinter, testable
  __init__.py
  config.py               AFRConfiguration (dataclass) + validation des règles page 1/2
  io.py                   lecture/écriture Touchstone, détection de format, grille de fréquence
  signal.py               filtrage, interpolation, grille DC, fenêtres, aller-retour temps/fréquence
  reflect.py              S1P → S2P : un standard (§4.1), OPEN+SHORT (§4.2)
  thru.py                 découpage 2x-thru (maison + IEEE P370)
  deembed.py              retrait des fixtures, multiport
  metrics.py              délai, impédance, mode mixte, passivité, réciprocité
  models.py               résultats typés : FixtureResult(network, z, delay, quality, method)
gui/
  app.py                  fenêtre principale, navigation
  pages/page1_fixture.py … page6_batch.py
  widgets/diagram.py      FixtureDiagram
  plot_window.py          tracés matplotlib
main.py                   point d'entrée
tests/
  test_reflect.py, test_thru.py, test_deembed.py   fixtures synthétiques (ligne, ligne + discontinuité)
requirements.txt, README.md
```

Règles :

- Le noyau `afr/` ne connaît ni Tkinter ni `messagebox` ; il retourne des objets et lève des exceptions typées.
- `logging` remplace `print` ; les tracés de debug sortent dans une fenêtre dédiée, jamais `plt.show()` bloquant.
- Toute méthode de calcul est une fonction pure (entrées → sorties), les paramètres (fenêtres, bandes) sont des arguments avec valeurs par défaut.
- Les résultats sont horodatés et exportés dans un dossier par session (`Results/<date>/`), avec un fichier récapitulatif (JSON) des délais, impédances et avertissements.

## 6. Décisions validées

| Point | Décision |
|---|---|
| « TDD » | Délai de propagation de la ligne (TTD, ps). Un champ « Effective εr » (page 3) et un label « Length » par ligne donnent la longueur physique `c · TTD / √εr_eff`. Le mode mixte (Tdd21) est retiré du périmètre. |
| Interface | Tkinter conservé : aucune dépendance nouvelle sur le poste de mesure, et le noyau `afr/` est indépendant de l'interface (un passage à Qt resterait possible sans toucher aux calculs). |
| Batch (page 6) | Batch « fichiers » : dossier d'entrée de mesures DUT (motif `*.s2p`), dossier de sortie, application des fixtures A/B calculées en page 3 et cochées en page 4, un fichier `<nom>_DEEMBEDDED.s2p` par mesure, journal des succès/échecs. Le pilotage direct du VNA (page 4, SCPI) reste hors périmètre. |
| Multiport | Nombre de ports dynamique, limité à 32 (déjà borné dans l'interface). L'extraction reste 2 ports par paire dans un premier temps ; le multiport complet est planifié en lot 4. |
| Compatibilité | Versions minimales fixées dans `requirements.txt` : Python ≥ 3.9, numpy ≥ 1.24, scipy ≥ 1.10, scikit-rf ≥ 0.29 (nécessaire pour l'IEEE P370 en lot 4). À vérifier sur le poste de mesure avec `python --version` et `pip show scikit-rf`. |
| Validation | Sur données réelles par le client après livraison de l'extraction ; fixtures synthétiques et tests automatiques côté développement. |

## 7. Plan de travail par lots

| Lot | Contenu | Dépend de |
|---|---|---|
| 0 | Filet de sécurité : fixtures synthétiques, tests automatiques, `requirements.txt`, `logging` — **livré** | — |
| 1 | Extraction du noyau `afr/` (fonctions pures, suppression des doublons et du code mort ; le fichier interface passe de 5 190 à 3 190 lignes) — **livré** | 0 |
| 2 | OPEN + SHORT combinés (§4.2), délai de ligne et longueur (§4.5), impédance TDR (§4.6), batch fichiers (page 6) — **livré**, contrôles qualité affichés dans le journal (interface en lot 3) | 1 |
| 3 | Fenêtre de tracé séparée (`gui/plot_window.py`), suppression des `print`, affichage des avertissements en page 3 — **livré** | 1 |
| 4 | Améliorations : IEEE P370, multiport (≤ 32 ports), profil TDR tracé | 2, 3 |
| 5 | Documentation utilisateur, README, exemple de bout en bout | 4 |

Chaque lot est livré sur la branche avec ses tests ; les lots 2 et 3 peuvent être menés en parallèle.

## 8. Critères d'acceptation

- Sur une ligne synthétique (55 Ω, 300 ps, pertes √f) : erreur S21 < 0,2 dB et < 3° sur 0,5 – 15 GHz, délai à ± 5 ps, impédance à ± 1 Ω, pour OPEN seul, SHORT seul et OPEN + SHORT.
- Sur un DUT synthétique connu : de-embedding retrouve le DUT à < 0,1 dB / 2° sur la bande utile.
- Aucun `print` dans le flux nominal ; les avertissements sont visibles dans l'interface.
- `python -m pytest` passe sans interface graphique.
- Les résultats de l'ancien script ne sont pas reproduits à l'identique (fenêtrage du 2x-thru et impédance corrigés) ; la référence est le fixture synthétique et la validation sur données réelles.
