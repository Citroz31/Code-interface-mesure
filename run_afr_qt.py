#!/usr/bin/env python3
"""
Lanceur de la version Qt de l'AFR (PySide6 + pyqtgraph).

    python run_afr_qt.py            lance l'interface Qt
    python run_afr_qt.py --check    verifie seulement l'installation

Meme principe que ``run_afr.py`` (version Tkinter) : l'installation est
verifiee avant de demarrer, et toute erreur part dans ``afr_error.log``
plutot que de fermer la fenetre sans rien dire.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_afr                                          # noqa: E402

# Memes exigences que la version Tkinter, moins Tk, plus Qt.
REQUIRED = [
    ("numpy", "numpy", None),
    ("scipy", "scipy", None),
    ("skrf", "scikit-rf", None),
    ("PySide6", "PySide6", "interface graphique Qt"),
    ("pyqtgraph", "pyqtgraph", "graphes interactifs"),
]

PROJECT_FILES = ["qtapp", "afr", "requirements.txt"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Le controle de run_afr.py sert tel quel : seules les listes changent.
    run_afr.REQUIRED = REQUIRED
    run_afr.PROJECT_FILES = PROJECT_FILES
    run_afr.OPTIONAL = [("matplotlib", "matplotlib",
                         "seulement pour l'ancienne interface Tkinter")]

    if "--check" in argv or "-c" in argv:
        return 0 if run_afr.check() else 1

    if not run_afr.check(verbose=False):
        run_afr.pause_if_needed()
        return 1

    import logging

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    print("Demarrage de l'interface AFR (Qt)")
    print(f"  interpreteur    : {sys.executable}")
    print(f"  dossier         : {HERE}")
    print("  construction de la fenetre...")

    try:
        from qtapp.app import main as qt_main

        code = qt_main()
        print("Fenetre fermee : arret normal.")
        return code
    except Exception as error:
        run_afr.report_crash(error)
        run_afr.pause_if_needed()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
