"""Fenetre principale : navigation entre les six pages, journal, etat."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QDockWidget, QHBoxLayout, QLabel,
                               QListWidget, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .pages import PAGES
from .session import AfrSession

log = logging.getLogger("afr.window")


class MainWindow(QMainWindow):
    """Assistant en six etapes, chaque page dans une pile."""

    def __init__(self, session: AfrSession = None):
        super().__init__()

        self.session = session or AfrSession()

        self.setWindowTitle("AFR - Automatic Fixture Removal")
        self.resize(1400, 880)

        self.stack = QStackedWidget()
        self.pages = []
        self.tabs = []

        # Tant que les six pages ne sont pas construites, une page ne doit pas
        # pouvoir en solliciter une autre : elle n'existe peut-etre pas encore.
        self._ready = False

        self._build_navigation()
        self._build_pages()
        self._build_warnings_dock()

        self.status_label = QLabel("Pret.")
        self.statusBar().addWidget(self.status_label, 1)

        self._ready = True

        self.show_page(0)
        self.place_on_screen()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_navigation(self):
        self.tab_bar = QWidget()
        tab_layout = QHBoxLayout(self.tab_bar)
        tab_layout.setContentsMargins(8, 6, 8, 0)
        tab_layout.setSpacing(4)

        for index, page_class in enumerate(PAGES):
            button = QPushButton(page_class.title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, i=index: self.show_page(i))
            tab_layout.addWidget(button)
            self.tabs.append(button)

        tab_layout.addStretch(1)

        self.previous_button = QPushButton("< Precedent")
        self.next_button = QPushButton("Suivant >")
        self.previous_button.clicked.connect(lambda: self.show_page(self.current - 1))
        self.next_button.clicked.connect(lambda: self.show_page(self.current + 1))

        tab_layout.addWidget(self.previous_button)
        tab_layout.addWidget(self.next_button)

    def _build_pages(self):
        for page_class in PAGES:
            page = page_class(self)
            self.pages.append(page)
            self.stack.addWidget(page)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tab_bar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.current = 0

    def _build_warnings_dock(self):
        self.warning_list = QListWidget()
        self.warning_list.setWordWrap(True)

        dock = QDockWidget("Avertissements", self)
        dock.setWidget(self.warning_list)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        dock.hide()
        self.warning_dock = dock

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def show_page(self, index: int):
        index = max(0, min(index, len(self.pages) - 1))
        self.current = index

        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.tabs):
            button.setChecked(position == index)

        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self.pages) - 1)

        page = self.pages[index]
        try:
            page.on_enter()
        except Exception:
            log.exception("Entree dans la page %s impossible", page.title)

    def place_on_screen(self):
        """
        Fenetre centree et bornee a l'ecran : elle ne peut pas s'ouvrir plus
        grande que l'affichage ni hors champ.
        """

        try:
            available = QGuiApplication.primaryScreen().availableGeometry()
            width = min(self.width(), available.width() - 60)
            height = min(self.height(), available.height() - 80)
            self.resize(width, height)
            self.move(available.center().x() - width // 2,
                      available.center().y() - height // 2)
        except Exception:
            log.warning("Placement de la fenetre impossible", exc_info=True)

    # ------------------------------------------------------------------
    # Services offerts aux pages
    # ------------------------------------------------------------------

    def status(self, message: str):
        self.status_label.setText(message)
        log.info(message)

    def busy(self, active: bool):
        if active:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.status("Calcul en cours...")
        else:
            QApplication.restoreOverrideCursor()
        QApplication.processEvents()

    def refresh_sources(self):
        """Met a jour la liste des courbes disponibles dans chaque graphe."""

        if not self._ready:
            return

        sources = self.session.plot_sources()
        for page in self.pages:
            if page.plot is not None:
                page.plot.set_sources(sources)

    def standards_changed(self):
        """La page 2 a change : la page 3 refait ses lignes de fichiers."""

        if not self._ready:
            return

        for page in self.pages:
            page.standards_changed()

    def set_warnings(self, warnings):
        self.warning_list.clear()
        for message in warnings:
            self.warning_list.addItem(message)

        if warnings:
            self.warning_dock.show()
        else:
            self.warning_dock.hide()

    def closeEvent(self, event):
        if self.session.extraction_done and self.session.deembedded_network is None:
            answer = QMessageBox.question(
                self, "Quitter",
                "Des fixtures ont ete extraits mais aucun de-embedding n'a ete "
                "lance. Quitter quand meme ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.No:
                event.ignore()
                return
        event.accept()
