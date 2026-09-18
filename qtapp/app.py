"""Point d'entree Qt : application, style, fenetre principale."""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("afr.app")

STYLE = """
QWidget { font-size: 12px; }
QGroupBox {
    border: 1px solid #cfcfcf;
    border-radius: 4px;
    margin-top: 12px;
    padding: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    font-weight: 600;
}
QPushButton { padding: 4px 10px; }
QPushButton:checked { font-weight: 700; }
"""


def main(argv=None) -> int:
    """Lance l'interface. Retourne le code de sortie du programme."""

    argv = sys.argv if argv is None else argv

    # pyqtgraph choisit sa liaison Qt a l'import : la fixer evite qu'il aille
    # chercher un PyQt5 residuel et entre en conflit avec PySide6.
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

    from PySide6.QtWidgets import QApplication

    from .mainwindow import MainWindow

    application = QApplication.instance() or QApplication(argv)
    application.setApplicationName("AFR")
    application.setStyleSheet(STYLE)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return application.exec()
