"""Petits widgets communs aux pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QWidget)

TOUCHSTONE_FILTER = "Touchstone (*.s1p *.s2p *.s3p *.s4p);;Tous les fichiers (*)"


class Title(QLabel):
    """Titre de page."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet("font-size: 17px; font-weight: 600; margin-bottom: 4px;")


class Hint(QLabel):
    """Texte d'explication, plus discret que le corps de page."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet("color:#555;")


class FileRow(QWidget):
    """Ligne : libelle, chemin, bouton Parcourir, etat."""

    changed = Signal(str, str)          # cle, chemin

    def __init__(self, key: str, label: str, parent=None, directory: bool = False):
        super().__init__(parent)

        self.key = key
        self.directory = directory

        self.label = QLabel(label)
        self.label.setMinimumWidth(190)

        self.path = QLineEdit()
        self.path.setPlaceholderText("aucun fichier" if not directory else "aucun dossier")
        self.path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.button = QPushButton("Parcourir...")
        self.status = QLabel("")
        self.status.setMinimumWidth(120)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        for widget in (self.label, self.path, self.button, self.status):
            layout.addWidget(widget)

        self.button.clicked.connect(self.browse)
        self.path.editingFinished.connect(
            lambda: self.changed.emit(self.key, self.path.text().strip()))

    def browse(self, *_):
        if self.directory:
            chosen = QFileDialog.getExistingDirectory(self, f"Choisir : {self.label.text()}")
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, f"Charger : {self.label.text()}", "", TOUCHSTONE_FILTER)

        if chosen:
            self.set_path(chosen)
            self.changed.emit(self.key, chosen)

    def set_path(self, path: str):
        self.path.setText(str(path))

    def value(self) -> str:
        return self.path.text().strip()

    def set_status(self, text: str, ok: bool = True):
        self.status.setText(text)
        self.status.setStyleSheet("color:#2f7a2f;" if ok else "color:#a33;")


class Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)


def scrollable(widget: QWidget) -> QWidget:
    """Enveloppe un widget dans une zone defilante (petits ecrans)."""

    from PySide6.QtWidgets import QScrollArea

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


def short_name(path: str) -> str:
    return Path(path).name if path else ""
