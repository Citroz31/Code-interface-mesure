"""
Vue graphique interactive (pyqtgraph).

Ce que l'on peut faire sans relancer le trace :

* zoom molette, zoom par rectangle, deplacement a la souris, retour vue
  complete, verrouillage d'un axe ;
* curseur reticule qui affiche la frequence et la valeur de chaque courbe ;
* marqueurs facon VNA, avec l'ecart entre les deux derniers (delta) ;
* changement de format (dB, phase, ROS, reel/imaginaire, Smith, temporel),
  axe des frequences lineaire ou logarithmique ;
* choix des sources et des parametres S, extinction d'une courbe en cliquant
  sur sa legende ;
* export en PNG et en CSV.
"""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from . import traces as tr

log = logging.getLogger("afr.plot")

# Couleurs lisibles sur fond clair, distinguables aussi en niveaux de gris.
PALETTE = ["#1f6f8b", "#b0651a", "#3f7a3f", "#8b2f5e", "#5a5ab0",
           "#a08010", "#2f7f7f", "#7a3f2f"]

DEFAULT_PARAMETERS = ("S11", "S21")


class ClickableSample(pg.graphicsItems.LegendItem.ItemSample):
    """Element de legende qui allume / eteint sa courbe au clic."""

    def mouseClickEvent(self, event):
        visible = not self.item.isVisible()
        self.item.setVisible(visible)
        self.setOpacity(1.0 if visible else 0.35)
        event.accept()


class PlotView(QWidget):
    """Graphe interactif complet : panneau de reglages + trace."""

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)

        self.sources: dict = {}          # etiquette -> reseau
        self.curves: list = []           # (PlotDataItem, Trace)
        self.markers: list = []          # InfiniteLine posees
        self._smith_items: list = []     # cercles de l'abaque, quand il est actif
        self.compact = compact

        self._build()
        self._connect()
        self.refresh()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self):
        pg.setConfigOptions(antialias=True)

        self.plot_widget = pg.PlotWidget(background="w")
        self.plot = self.plot_widget.getPlotItem()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("bottom", "Frequency", units="GHz")
        self.plot.setLabel("left", "Magnitude (dB)")
        self.plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)

        try:
            self.legend = self.plot.addLegend(offset=(-10, 10),
                                              sampleType=ClickableSample)
        except TypeError:          # pyqtgraph ancien : legende non cliquable
            self.legend = self.plot.addLegend(offset=(-10, 10))

        self.readout = QLabel("Deplacer la souris sur le graphe pour lire les valeurs.")
        self.readout.setWordWrap(True)
        self.readout.setStyleSheet("color:#333; font-family: monospace;")

        self.source_list = QListWidget()
        self.source_list.setSelectionMode(QListWidget.NoSelection)
        self.source_list.setMinimumWidth(190)

        self.parameter_boxes = {}
        parameters = QGroupBox("Parametres S")
        parameter_layout = QGridLayout(parameters)
        for index, name in enumerate(tr.PARAMETERS):
            box = QCheckBox(name)
            box.setChecked(name in DEFAULT_PARAMETERS)
            self.parameter_boxes[name] = box
            parameter_layout.addWidget(box, index // 2, index % 2)

        self.format_box = QComboBox()
        for fmt in tr.FORMATS:
            self.format_box.addItem(fmt.title, fmt.key)

        self.log_x = QCheckBox("Axe frequence logarithmique")
        self.auto_scale = QCheckBox("Ajuster l'echelle a chaque trace")
        self.auto_scale.setChecked(True)

        self.marker_mode = QCheckBox("Poser un marqueur au clic")
        self.rect_zoom = QCheckBox("Zoom par rectangle")
        self.lock_y = QCheckBox("Verrouiller l'axe vertical")

        self.button_full = QPushButton("Vue complete")
        self.button_clear_markers = QPushButton("Effacer les marqueurs")
        self.button_png = QPushButton("Exporter PNG")
        self.button_csv = QPushButton("Exporter CSV")

        # --- disposition ------------------------------------------------
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(6, 6, 6, 6)

        sources_box = QGroupBox("Courbes disponibles")
        sources_layout = QVBoxLayout(sources_box)
        sources_layout.addWidget(self.source_list)

        display_box = QGroupBox("Affichage")
        display_layout = QVBoxLayout(display_box)
        display_layout.addWidget(QLabel("Format :"))
        display_layout.addWidget(self.format_box)
        display_layout.addWidget(self.log_x)
        display_layout.addWidget(self.auto_scale)

        tools_box = QGroupBox("Outils")
        tools_layout = QVBoxLayout(tools_box)
        for widget in (self.rect_zoom, self.lock_y, self.marker_mode,
                       self.button_full, self.button_clear_markers):
            tools_layout.addWidget(widget)

        export_row = QHBoxLayout()
        export_row.addWidget(self.button_png)
        export_row.addWidget(self.button_csv)
        tools_layout.addLayout(export_row)

        controls_layout.addWidget(sources_box, 2)
        controls_layout.addWidget(parameters)
        controls_layout.addWidget(display_box)
        controls_layout.addWidget(tools_box)
        controls_layout.addStretch(1)

        graph = QWidget()
        graph_layout = QVBoxLayout(graph)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.addWidget(self.plot_widget, 1)
        graph_layout.addWidget(self.readout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(graph)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        if self.compact:
            controls.setMaximumWidth(230)

        # --- curseur reticule -------------------------------------------
        pen = pg.mkPen("#999", width=1, style=Qt.DashLine)
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        for line in (self.v_line, self.h_line):
            line.setZValue(10)
            self.plot.addItem(line, ignoreBounds=True)

    def _connect(self):
        self.source_list.itemChanged.connect(lambda *_: self.refresh())
        for box in self.parameter_boxes.values():
            box.stateChanged.connect(lambda *_: self.refresh())

        self.format_box.currentIndexChanged.connect(lambda *_: self.refresh())
        self.log_x.stateChanged.connect(lambda *_: self.refresh())

        self.rect_zoom.stateChanged.connect(self._update_mouse_mode)
        self.lock_y.stateChanged.connect(self._update_mouse_mode)

        self.button_full.clicked.connect(self.view_all)
        self.button_clear_markers.clicked.connect(self.clear_markers)
        self.button_png.clicked.connect(self.export_png)
        self.button_csv.clicked.connect(self.export_csv)

        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def set_sources(self, mapping: dict, keep_selection: bool = True):
        """Remplace la liste des reseaux tracables."""

        selected = set(self.selected_labels()) if keep_selection else set()
        self.sources = dict(mapping)

        self.source_list.blockSignals(True)
        self.source_list.clear()

        for label in self.sources:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if label in selected else Qt.Unchecked)
            self.source_list.addItem(item)

        # Premiere fois : montrer quelque chose plutot qu'un graphe vide.
        if not selected and self.source_list.count():
            self.source_list.item(0).setCheckState(Qt.Checked)

        self.source_list.blockSignals(False)
        self.refresh()

    def selected_labels(self) -> list:
        return [self.source_list.item(row).text()
                for row in range(self.source_list.count())
                if self.source_list.item(row).checkState() == Qt.Checked]

    def select_only(self, labels, parameters=None, format_key=None):
        """Selection dirigee, utilisee apres un calcul."""

        wanted = set(labels)
        self.source_list.blockSignals(True)
        for row in range(self.source_list.count()):
            item = self.source_list.item(row)
            item.setCheckState(Qt.Checked if item.text() in wanted else Qt.Unchecked)
        self.source_list.blockSignals(False)

        if parameters:
            for name, box in self.parameter_boxes.items():
                box.blockSignals(True)
                box.setChecked(name in parameters)
                box.blockSignals(False)

        if format_key:
            index = self.format_box.findData(format_key)
            if index >= 0:
                self.format_box.blockSignals(True)
                self.format_box.setCurrentIndex(index)
                self.format_box.blockSignals(False)

        self.refresh()

    def selected_parameters(self) -> list:
        return [name for name, box in self.parameter_boxes.items() if box.isChecked()]

    def format_key(self) -> str:
        return self.format_box.currentData() or "db"

    # ------------------------------------------------------------------
    # Trace
    # ------------------------------------------------------------------

    def refresh(self, *_):
        """Reconstruit toutes les courbes a partir de la selection."""

        for curve, _ in self.curves:
            self.plot.removeItem(curve)
        self.curves = []

        if self.legend is not None:
            self.legend.clear()

        networks = [(label, self.sources[label]) for label in self.selected_labels()
                    if label in self.sources]
        parameters = self.selected_parameters()
        key = self.format_key()

        if not networks or not parameters:
            self.plot.setTitle("Choisir au moins une courbe et un parametre S")
            self._draw_smith_grid(False)
            return

        try:
            built = tr.build_traces(networks, parameters, key)
        except Exception as error:
            log.exception("Construction des courbes impossible")
            self.plot.setTitle(f"Trace impossible : {error}")
            return

        fmt = tr.FORMAT_BY_KEY.get(key, tr.FORMAT_BY_KEY["db"])
        self.plot.setTitle(fmt.title)

        self._draw_smith_grid(key == "smith")

        log_x = bool(self.log_x.isChecked()) and fmt.log_x_allowed
        self.plot.setLogMode(x=log_x, y=False)
        self.plot.getViewBox().setAspectLocked(fmt.equal_aspect)

        for index, trace in enumerate(built):
            pen = pg.mkPen(PALETTE[index % len(PALETTE)], width=1.6)
            x = np.asarray(trace.x, dtype=float)
            y = np.asarray(trace.y, dtype=float)

            # En echelle log, les abscisses nulles ou negatives n'existent pas.
            if log_x:
                keep = x > 0
                x, y = x[keep], y[keep]

            curve = self.plot.plot(x, y, pen=pen, name=trace.label,
                                   antialias=True, autoDownsample=True,
                                   clipToView=True)
            self.curves.append((curve, trace))

        if built:
            self.plot.setLabel("bottom", built[0].x_label)
            self.plot.setLabel("left", built[0].y_label)

        if self.auto_scale.isChecked():
            self.view_all()

    def _draw_smith_grid(self, enabled: bool):
        """Cercles de l'abaque de Smith, uniquement dans ce format."""

        for item in self._smith_items:
            self.plot.removeItem(item)
        self._smith_items = []

        if not enabled:
            return

        pen = pg.mkPen("#c8c8c8", width=1)
        angle = np.linspace(0, 2 * np.pi, 361)

        # Cercles a resistance constante r : centre r/(1+r), rayon 1/(1+r).
        for r in (0.0, 0.2, 0.5, 1.0, 2.0, 5.0):
            centre, radius = r / (1 + r), 1 / (1 + r)
            item = self.plot.plot(centre + radius * np.cos(angle),
                                  radius * np.sin(angle), pen=pen)
            self._smith_items.append(item)

        # Arcs a reactance constante x : centre (1, 1/x), rayon 1/|x|.
        for x in (0.2, 0.5, 1.0, 2.0, 5.0):
            for sign in (1, -1):
                radius = 1.0 / x
                circle_x = 1.0 + radius * np.cos(angle)
                circle_y = sign * radius + radius * np.sin(angle)
                inside = circle_x ** 2 + circle_y ** 2 <= 1.0
                if inside.any():
                    item = self.plot.plot(circle_x[inside], circle_y[inside], pen=pen)
                    self._smith_items.append(item)

        for item in self._smith_items:
            item.setZValue(-10)

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def _update_mouse_mode(self, *_):
        view = self.plot.getViewBox()
        view.setMouseMode(pg.ViewBox.RectMode if self.rect_zoom.isChecked()
                          else pg.ViewBox.PanMode)
        view.setMouseEnabled(x=True, y=not self.lock_y.isChecked())

    def view_all(self, *_):
        self.plot.enableAutoRange()
        self.plot.autoRange()

    def _on_mouse_moved(self, position):
        if not self.plot.sceneBoundingRect().contains(position):
            return

        point = self.plot.getViewBox().mapSceneToView(position)
        x = float(point.x())
        if self.plot.getAxis("bottom").logMode:
            x = 10.0 ** x

        self.v_line.setPos(point.x())
        self.h_line.setPos(point.y())

        self.readout.setText(self._readout_text(x))

    def _readout_text(self, x: float) -> str:
        parts = [f"x = {x:.6g}"]

        for curve, trace in self.curves:
            if not curve.isVisible() or len(trace.x) == 0:
                continue
            value = float(np.interp(x, trace.x, trace.y,
                                    left=float("nan"), right=float("nan")))
            if np.isfinite(value):
                parts.append(f"{trace.label} = {value:.4g}")

        if len(self.markers) >= 2:
            first, second = self.markers[-2].value(), self.markers[-1].value()
            parts.append(f"delta marqueurs = {second - first:+.6g}")

        return "   |   ".join(parts)

    def _on_mouse_clicked(self, event):
        if not self.marker_mode.isChecked():
            return

        position = event.scenePos()
        if not self.plot.sceneBoundingRect().contains(position):
            return

        point = self.plot.getViewBox().mapSceneToView(position)
        self.add_marker(float(point.x()))
        event.accept()

    def add_marker(self, x: float):
        """Marqueur vertical deplacable, etiquete avec sa position."""

        line = pg.InfiniteLine(
            pos=x, angle=90, movable=True,
            pen=pg.mkPen("#b0651a", width=1.4, style=Qt.DashDotLine),
            label=f"M{len(self.markers) + 1} : {{value:.4g}}",
            labelOpts={"position": 0.92, "color": "#b0651a",
                       "movable": True, "fill": (255, 255, 255, 180)},
        )
        line.sigPositionChanged.connect(lambda *_: self.readout.setText(
            self._readout_text(line.value())))

        self.plot.addItem(line)
        self.markers.append(line)

        if len(self.markers) >= 2:
            first, second = self.markers[-2].value(), self.markers[-1].value()
            log.info("Marqueurs : %.6g et %.6g, delta %.6g", first, second, second - first)

    def clear_markers(self, *_):
        for line in self.markers:
            self.plot.removeItem(line)
        self.markers = []
        self.readout.setText("Marqueurs effaces.")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_png(self, *_):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le graphe", "graphe.png",
                                              "Image PNG (*.png)")
        if not path:
            return

        try:
            from pyqtgraph.exporters import ImageExporter

            exporter = ImageExporter(self.plot)
            exporter.parameters()["width"] = 1600
            exporter.export(path)
            self.readout.setText(f"Graphe enregistre : {path}")
        except Exception as error:
            log.exception("Export PNG impossible")
            self.readout.setText(f"Export PNG impossible : {error}")

    def export_csv(self, *_):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les donnees", "courbes.csv",
                                              "Fichier CSV (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as handle:
                tr.to_csv([trace for curve, trace in self.curves if curve.isVisible()],
                          handle)
            self.readout.setText(f"Donnees enregistrees : {path}")
        except Exception as error:
            log.exception("Export CSV impossible")
            self.readout.setText(f"Export CSV impossible : {error}")
