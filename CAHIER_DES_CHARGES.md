# Cahier des charges — Refonte de l'outil AFR (Automatic Fixture Removal)

Version 0.1 — proposition à valider avant le démarrage des travaux.

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
2. **« TDD » de chaque ligne** : voir la question ouverte § 6.1. Deux lectures possibles, les deux sont proposées.
3. **Code propre et modulaire** : séparation calcul / interface / fichiers, tests automatiques, journalisation.
4. **Améliorations** : méthodes de calcul plus robustes, validations, multiport.

## 4. Méthodes de calcul proposées

Notations : fixture = 2 ports, port 1 côté VNA, port 2 côté DUT. Γ_L = +1 (OPEN), −1 (SHORT).
Mesure 1 port du fixture terminé par un standard :

    Γ_mes = S11 + S21² · Γ_L / (1 − S22 · Γ_L)

### 4.1 Un seul standard (OPEN ou SHORT) — méthode actuelle corrigée

- Grille uniforme partant de DC, fenêtre de Kaiser, réponse impulsionnelle par `irfft`.
- Réflexion proche (fenêtre symétrique autour de t = 0) → S11.
- Réflexion lointaine (fenêtre adaptative autour de t = 2τ) → Γ_far.
- S21 = sqrt(Γ_far / Γ_L · (1 − S11²)), branche choisie pour que la phase tende vers 0 à DC.
- Hypothèse forcée : S22 = S11, S12 = S21 (fixture symétrique et réciproque).

Limites : S22 n'est pas mesurable avec un seul standard ; la réponse en bord de bande est amplifiée par la division par la fenêtre.

### 4.2 OPEN + SHORT combinés (recommandé quand les deux sont mesurés)

Avec les deux mesures, l'hypothèse S22 = S11 disparaît :

    Γ_o − Γ_s = 2 · S21² / (1 − S22²)
    Γ_o + Γ_s = 2 · S11 + 2 · S21² · S22 / (1 − S22²)

Algorithme :

1. `M = (Γ_o + Γ_s)/2`, `D = (Γ_o − Γ_s)/2`.
2. S11 = partie proche (t ≈ 0) de `M`, obtenue par fenêtrage temporel.
3. S22 = (M − S11) / D (partie lointaine, lissée).
4. S21² = D · (1 − S22²), puis racine carrée continue (branche DC).
5. Contrôle : reconstruire Γ_o et Γ_s avec le modèle et afficher le résidu en dB.

Résultat : fixture complet (S11, S21, S22) sans hypothèse de symétrie, et une mesure de cohérence OPEN/SHORT.
Un standard LOAD optionnel (si disponible) permettrait un « OSL » complet et supprimerait tout fenêtrage.

### 4.3 2x-thru (fixture A + B)

- Remplacer la fenêtre fixe de 15 échantillons par la même chaîne temporelle que § 4.1 (grille DC, fenêtre adaptative centrée sur le pic).
- Conserver la relation `S21_half² = S21_2x · (1 − S11_half²)` (déjà utilisée) avec la même racine carrée continue.
- **Option de référence** : scikit-rf implémente l'IEEE P370 (`skrf.calibration.IEEEP370_SE_NZC_2xThru` et `IEEEP370_SE_ZC_2xThru`, cette dernière corrige l'impédance à partir du DUT fixturé). Proposition : l'ajouter comme méthode sélectionnable et l'utiliser comme référence pour valider notre découpage maison.
- Fixtures A ≠ B : combiner le 2x-thru avec les réflexions (OPEN/SHORT B) pour ne plus supposer B = port-swap de A.

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

### 4.7 Mode mixte (si « TDD » = paramètres différentiels Tdd)

Pour un fixture 4 ports (paire différentielle) : conversion single-ended → mixed-mode avec `Network.se2gmm`, extraction de Sdd11, Sdd21 (souvent notés Tdd11, Tdd21), Scc et Sdc. Délai et impédance différentiels (Zdiff) dérivés de Sdd. Voir question § 6.1.

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

## 6. Questions à valider avant démarrage

1. **Signification de « TDD »** : (a) délai de propagation de chaque ligne/port (TTD, ps) — déjà partiellement affiché ; ou (b) paramètres différentiels Tdd11/Tdd21 pour paires différentielles (4 ports). Proposition : livrer (a) dans le lot 2, (b) dans le lot 4. Merci de confirmer.
2. **Interface** : conserver Tkinter (pas de dépendance supplémentaire) ou passer à une autre bibliothèque ? Proposition : conserver Tkinter, seule la structure change.
3. **Pages 4 et 6** (pilotage VNA, batch) : hors périmètre pour l'instant, ou implémenter le batch « fichiers » (dossier de mesures DUT → dossier de résultats) ? Proposition : batch fichiers dans le lot 4, VNA hors périmètre.
4. **Multiport** : nombre de ports cible (4 ? 8 ?) et priorité par rapport au 2 ports.
5. **Compatibilité** : versions Python et scikit-rf utilisées sur le poste de mesure (l'IEEE P370 demande scikit-rf ≥ 0.29).
6. **Données réelles** : peut-on disposer d'un jeu de mesures (2x-thru, open, short, DUT) pour la validation, en plus des fixtures synthétiques ?

## 7. Plan de travail par lots

| Lot | Contenu | Dépend de |
|---|---|---|
| 0 | Filet de sécurité : fixtures synthétiques, tests de non-régression sur le code actuel, `requirements.txt`, `logging` | — |
| 1 | Extraction du noyau `afr/` sans changer les résultats (fonctions pures, suppression des doublons et du code mort) | 0 |
| 2 | OPEN + SHORT combinés (§4.2), délai de ligne (§4.5), impédance TDR (§4.6), affichage des contrôles qualité | 1 |
| 3 | Découpage de l'interface en `gui/` (pages, widgets, fenêtre de tracé), remplacement des `print` | 1 |
| 4 | Améliorations : IEEE P370, de-embedding scikit-rf et multiport, mode mixte (§4.7), batch fichiers | 2, 3 |
| 5 | Documentation utilisateur, README, exemple de bout en bout | 4 |

Chaque lot est livré sur la branche avec ses tests ; les lots 2 et 3 peuvent être menés en parallèle.

## 8. Critères d'acceptation

- Sur une ligne synthétique (55 Ω, 300 ps, pertes √f) : erreur S21 < 0,2 dB et < 3° sur 0,5 – 15 GHz, délai à ± 5 ps, impédance à ± 1 Ω, pour OPEN seul, SHORT seul et OPEN + SHORT.
- Sur un DUT synthétique connu : de-embedding retrouve le DUT à < 0,1 dB / 2° sur la bande utile.
- Aucun `print` dans le flux nominal ; les avertissements sont visibles dans l'interface.
- `python -m pytest` passe sans interface graphique.
- Les résultats de l'ancien script sont reproduits par le lot 1 à la précision numérique près (non-régression).
