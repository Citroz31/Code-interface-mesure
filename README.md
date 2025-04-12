# Interface de Mesure - S-Parameter Viewer

Ce projet est une interface graphique interactive développée en **Python** avec **Tkinter**, permettant de charger, visualiser, explorer et exporter des fichiers S-Parameter (`.s2p`) au format Touchstone.

---

## Fonctionnalités

- **Chargement de fichiers `.s2p`** via le menu `File > Open`
- **Affichage dynamique** des courbes `S11`, `S12`, `S21`, `S22`
- Sélection entre :
  - **Amplitude (dB)**
  - **Phase (deg)**
- **Survol interactif** : montre les valeurs (x,y) au point le plus proche du curseur
- **Export CSV** via un bouton dédié
- **Sliders doubles** (`RangeSlider`) pour :
  - Filtrer la **plage de fréquences**
  - Ajuster la **plage verticale (Amplitude ou Phase)**
- Interface modulaire prête à accueillir des fonctions de calibration, mesure, simulation, etc.

---

## Dépendances

Installer les modules nécessaires via `pip` :

```bash
pip install matplotlib numpy scikit-rf ttkwidgets