#!/usr/bin/env python3
"""
Lanceur de l'application AFR.

    python run_afr.py            lance l'interface
    python run_afr.py --check    verifie seulement l'installation
    python run_afr.py --selftest verifie l'installation puis le calcul,
                                 sur une ligne synthetique, sans interface

A utiliser de preference a ``python matrice_et_branche.py`` : ce lanceur
verifie d'abord Python, les fichiers du projet et les bibliotheques
necessaires, explique en clair ce qui manque, et si l'application s'arrete
sur une erreur il ecrit la trace complete dans ``afr_error.log`` au lieu de
fermer la fenetre sans rien dire.
"""

import importlib
import platform
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_FILE = HERE / "afr_error.log"

MINIMUM_PYTHON = (3, 9)

# (module a importer, nom du paquet a installer, remarque)
REQUIRED = [
    ("tkinter", None,
     "fourni avec Python. Windows/macOS : reinstaller Python en cochant "
     "'tcl/tk and IDLE'. Linux : sudo apt install python3-tk"),
    ("numpy", "numpy", None),
    ("scipy", "scipy", None),
    ("skrf", "scikit-rf", None),
    ("matplotlib", "matplotlib", None),
]

OPTIONAL = [
    ("pywt", "PyWavelets", "seulement pour le filtre 'Wavelet' de la page 3"),
]

# Fichiers et dossiers qui doivent accompagner ce lanceur.
PROJECT_FILES = ["matrice_et_branche.py", "afr", "gui", "requirements.txt"]


def python_report():
    """(ok, lignes) : version de Python et emplacement de l'interpreteur."""

    ok = sys.version_info >= MINIMUM_PYTHON
    lines = [
        f"Python            : {platform.python_version()} "
        f"({'OK' if ok else 'TROP ANCIEN, il faut ' + '.'.join(map(str, MINIMUM_PYTHON)) + ' ou plus'})",
        f"Interpreteur      : {sys.executable}",
        f"Systeme           : {platform.platform()}",
        f"Dossier du projet : {HERE}",
    ]
    return ok, lines


def files_report():
    """(ok, lignes, manquants) : le projet est-il complet a cote du lanceur ?"""

    missing = [name for name in PROJECT_FILES if not (HERE / name).exists()]
    if missing:
        lines = ["Fichiers du projet : INCOMPLET, il manque " + ", ".join(missing)]
    else:
        lines = ["Fichiers du projet : complets"]
    return not missing, lines, missing


def modules_report():
    """(ok, lignes, paquets_manquants) pour les bibliotheques necessaires."""

    lines = []
    missing = []

    for module, package, note in REQUIRED:
        try:
            imported = importlib.import_module(module)
            version = getattr(imported, "__version__", "")
            lines.append(f"  {module:<12} OK {version}")
        except Exception as error:
            lines.append(f"  {module:<12} ABSENT ({error.__class__.__name__})"
                         + (f" - {note}" if note else ""))
            if package:
                missing.append(package)

    for module, package, note in OPTIONAL:
        try:
            importlib.import_module(module)
            lines.append(f"  {module:<12} OK (optionnel)")
        except Exception:
            lines.append(f"  {module:<12} absent (optionnel : {note})")

    return not missing, lines, missing


def install_hint(missing):
    """Commande exacte a copier-coller pour installer ce qui manque."""

    # Le chemin complet de l'interpreteur evite d'installer dans un autre
    # Python que celui qui lancera l'application.
    return f'"{sys.executable}" -m pip install ' + " ".join(missing)


def check(verbose=True):
    """Controle complet. Retourne True si l'application peut demarrer."""

    python_ok, lines = python_report()
    files_ok, file_lines, _ = files_report()
    modules_ok, module_lines, missing = modules_report()

    if verbose:
        print("=" * 72)
        print("Verification de l'installation AFR")
        print("=" * 72)
        for line in lines + file_lines:
            print(line)
        print("Bibliotheques :")
        for line in module_lines:
            print(line)
        print("=" * 72)

    if not python_ok:
        print("Python est trop ancien : installer Python "
              f"{'.'.join(map(str, MINIMUM_PYTHON))} ou plus recent "
              "(https://www.python.org/downloads/).")

    if not files_ok:
        print("Le dossier du projet est incomplet : reextraire l'archive en "
              "entier, en gardant les sous-dossiers afr/ et gui/ a cote de "
              "matrice_et_branche.py.")

    if missing:
        print("Bibliotheques manquantes : " + ", ".join(missing))
        print("Installation :")
        print("    " + install_hint(missing))
        print("ou, pour tout installer d'un coup :")
        print(f'    "{sys.executable}" -m pip install -r requirements.txt')

    ok = python_ok and files_ok and modules_ok
    if verbose and ok:
        print("Tout est en place : l'application peut demarrer.")
    return ok


def report_crash(error):
    """Ecrit la trace complete et l'affiche, au lieu d'une fenetre qui se ferme."""

    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    try:
        LOG_FILE.write_text(
            "Erreur au lancement de l'application AFR\n"
            f"Python {platform.python_version()} - {platform.platform()}\n"
            f"Interpreteur : {sys.executable}\n\n{trace}",
            encoding="utf-8",
        )
        written = f"\nTrace complete enregistree dans :\n    {LOG_FILE}"
    except Exception:
        written = ""

    print("\n" + "=" * 72)
    print("L'application s'est arretee sur une erreur :")
    print("=" * 72)
    print(trace)
    print(written)

    # Fenetre d'erreur si Tk fonctionne : utile quand il n'y a pas de console.
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "AFR : erreur au lancement",
            f"{error.__class__.__name__} : {error}\n\n"
            f"Details complets dans :\n{LOG_FILE}",
        )
        root.destroy()
    except Exception:
        pass


def selftest():
    """
    Controle de bout en bout du noyau de calcul, sans interface : une ligne
    synthetique (55 ohm, 300 ps, 1 dB a 10 GHz) est mesuree en OPEN puis
    re-extraite avec chaque modele, et l'ecart avec la reference est affiche.
    """

    import numpy as np
    import skrf as rf

    from afr import reflect

    freq = np.arange(10e6, 20e9 + 1, 20e6)
    zc, delay, loss_db = 55.0, 300e-12, 1.0

    alpha = (loss_db / 8.686) * np.sqrt(np.maximum(freq, 1.0) / 10e9)
    gamma = alpha + 2j * np.pi * freq * delay

    abcd = np.zeros((len(freq), 2, 2), dtype=complex)
    abcd[:, 0, 0] = np.cosh(gamma)
    abcd[:, 0, 1] = zc * np.sinh(gamma)
    abcd[:, 1, 0] = np.sinh(gamma) / zc
    abcd[:, 1, 1] = np.cosh(gamma)
    reference = rf.a2s(abcd, z0=50.0)

    s11, s21 = reference[:, 0, 0], reference[:, 1, 0]
    s12, s22 = reference[:, 0, 1], reference[:, 1, 1]
    measured = s11 + s21 * s12 / (1.0 - s22)          # termine par un OPEN ideal

    band = (freq >= 1e9) & (freq <= 15e9)

    print("=" * 72)
    print("Auto-test du noyau de calcul : ligne 55 ohm, 300 ps, 1 dB a 10 GHz")
    print("=" * 72)

    worst = 0.0
    for model in reflect.MODELS:
        result = reflect.fixture_from_reflect(freq, measured, "OPEN", model=model)
        estimated = result.network.s[band, 1, 0]
        error = float(np.max(np.abs(20 * np.log10(np.abs(estimated))
                                    - 20 * np.log10(np.abs(s21[band])))))
        print(f"  {model:<22} ecart |S21| {error:6.3f} dB   "
              f"TTD {result.delay_ps:6.1f} ps (reference 300.0)   "
              f"Z {result.impedance_ohm:5.1f} ohm (reference 55.0)")
        if model != "first_order":
            worst = max(worst, error)

    ok = worst < 0.3
    print("=" * 72)
    print("Noyau de calcul :", "OK" if ok else f"ECART INATTENDU ({worst:.3f} dB)")
    return ok


def pause_if_needed():
    """
    Sous Windows, un double-clic ferme la console des la fin du script : sans
    cette pause, le message d'erreur disparait avant d'avoir pu etre lu.
    """

    if sys.platform != "win32":
        return

    try:
        input("\nAppuyez sur Entree pour fermer cette fenetre...")
    except Exception:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Permet de lancer le script depuis n'importe quel dossier.
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))

    if "--check" in argv or "-c" in argv:
        return 0 if check() else 1

    if "--selftest" in argv or "-t" in argv:
        if not check():
            pause_if_needed()
            return 1
        print()
        try:
            return 0 if selftest() else 1
        except Exception as error:
            report_crash(error)
            pause_if_needed()
            return 1

    if not check(verbose=False):
        check()                      # deuxieme passage, cette fois affiche
        pause_if_needed()
        return 1

    import logging

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    try:
        from matrice_et_branche import AFRWizardComplete
        AFRWizardComplete().mainloop()
    except Exception as error:
        report_crash(error)
        pause_if_needed()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
