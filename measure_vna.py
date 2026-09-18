"""
Ancien script de mesure VNA, laisse vide.

Ce fichier est vide : ce n'est PAS le point d'entree de l'application.
L'executer ne fait rien et n'affiche aucune erreur, ce qui donne
l'impression que l'application ne se lance pas.

Pour lancer l'interface AFR :

    Windows          : double-clic sur lancer_afr.bat
    Tous systemes    : python run_afr.py
    Verification     : python run_afr.py --check
"""

import sys

if __name__ == "__main__":
    print(__doc__)

    if sys.platform == "win32":
        try:
            input("Appuyez sur Entree pour fermer cette fenetre...")
        except Exception:
            pass

    raise SystemExit(1)
