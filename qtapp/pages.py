"""
Les six pages de l'assistant AFR, en Qt.

Chaque page ne fait que lire et ecrire dans la session (``qtapp.session``) :
aucune formule ici. Toutes les options de la version Tkinter sont reprises.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton,
                               QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .plotview import PlotView
from .session import DEEMBEDDED_LABEL, RAW_LABEL, STANDARD_LABELS
from .widgets import FileRow, Hint, Separator, Title, scrollable

log = logging.getLogger("afr.pages")


class Page(QWidget):
    """Base commune : acces a la session et a la fenetre principale."""

    title = "Page"

    # Graphe de la page, quand elle en a un. Declare ici pour que la fenetre
    # principale puisse interroger toutes les pages sans test d'existence.
    plot = None

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.session = context.session
        self.build()

    def build(self):                      # pragma: no cover - redefini
        raise NotImplementedError

    def on_enter(self):
        """Appelee a chaque fois que la page devient visible."""

    def standards_changed(self):
        """La liste des standards a change en page 2."""


# ---------------------------------------------------------------------------
# Page 1 : configuration
# ---------------------------------------------------------------------------

class ConfigurationPage(Page):
    title = "1. Configuration"

    def build(self):
        config = self.session.config

        self.input_mode = QComboBox()
        self.input_mode.addItem("Single ended", "single_ended")
        self.input_mode.addItem("Mixed mode (differentiel)", "mixed_mode")

        self.measurement_mode = QComboBox()
        self.measurement_mode.addItem("2 ports", "2_ports")
        self.measurement_mode.addItem("Multiport", "multiport")

        self.multiport_count = QSpinBox()
        self.multiport_count.setRange(2, 32)
        self.multiport_count.setValue(config.multiport_count)

        self.z0_mode = QComboBox()
        self.z0_mode.addItem("Impedance fixe", "fixed")
        self.z0_mode.addItem("Impedance lue dans le fichier", "from_file")

        self.z0_value = QDoubleSpinBox()
        self.z0_value.setRange(1.0, 1000.0)
        self.z0_value.setDecimals(2)
        self.z0_value.setSuffix(" ohm")
        self.z0_value.setValue(config.reference_z0_ohm)

        self.set_system_z0 = QCheckBox("Imposer cette impedance au systeme")
        self.correct_match = QCheckBox("Corriger la desadaptation entre A et B")
        self.correct_length = QCheckBox("Corriger la difference de longueur entre A et B")
        self.band_limited = QCheckBox("Mesure en bande (pas de continu)")
        self.different_fixture = QCheckBox(
            "Le fixture de caracterisation differe du fixture de mesure")

        form = QGroupBox("Mesure")
        form_layout = QFormLayout(form)
        form_layout.addRow("Type d'entree :", self.input_mode)
        form_layout.addRow("Nombre de ports :", self.measurement_mode)
        form_layout.addRow("Ports (multiport) :", self.multiport_count)
        form_layout.addRow("Impedance de reference :", self.z0_mode)
        form_layout.addRow("Valeur :", self.z0_value)

        options = QGroupBox("Options de correction")
        options_layout = QVBoxLayout(options)
        for box in (self.set_system_z0, self.correct_match, self.correct_length,
                    self.band_limited, self.different_fixture):
            options_layout.addWidget(box)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(Title("Assistant de retrait de fixture (AFR)"))
        layout.addWidget(Hint(
            "Six etapes : decrire la mesure, declarer les standards disponibles, "
            "extraire les fixtures, retirer les fixtures d'une mesure brute, "
            "enregistrer, puis traiter un dossier entier. "
            "Les graphes sont interactifs : molette pour zoomer, clic droit glisse "
            "pour un rectangle, marqueurs et export a droite du trace."))
        layout.addWidget(form)
        layout.addWidget(options)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

        for widget in (self.input_mode, self.measurement_mode, self.z0_mode):
            widget.currentIndexChanged.connect(self.store)
        for widget in (self.multiport_count, self.z0_value):
            widget.valueChanged.connect(self.store)
        for box in (self.set_system_z0, self.correct_match, self.correct_length,
                    self.band_limited, self.different_fixture):
            box.stateChanged.connect(self.store)

        self.load()

    def load(self):
        config = self.session.config
        self.input_mode.setCurrentIndex(max(0, self.input_mode.findData(config.input_mode)))
        self.measurement_mode.setCurrentIndex(
            max(0, self.measurement_mode.findData(config.measurement_mode)))
        self.z0_mode.setCurrentIndex(max(0, self.z0_mode.findData(config.reference_z0_mode)))
        self.set_system_z0.setChecked(config.set_system_z0)
        self.correct_match.setChecked(config.correct_match_ab)
        self.correct_length.setChecked(config.correct_length_ab)
        self.band_limited.setChecked(config.band_limited)
        self.different_fixture.setChecked(config.characterization_fixture_different)

    def store(self, *_):
        config = self.session.config
        config.input_mode = self.input_mode.currentData()
        config.measurement_mode = self.measurement_mode.currentData()
        config.multiport_count = self.multiport_count.value()
        config.reference_z0_mode = self.z0_mode.currentData()
        config.reference_z0_ohm = self.z0_value.value()
        config.set_system_z0 = self.set_system_z0.isChecked()
        config.correct_match_ab = self.correct_match.isChecked()
        config.correct_length_ab = self.correct_length.isChecked()
        config.band_limited = self.band_limited.isChecked()
        config.characterization_fixture_different = self.different_fixture.isChecked()

        self.multiport_count.setEnabled(config.measurement_mode == "multiport")
        self.z0_value.setEnabled(config.reference_z0_mode == "fixed")


# ---------------------------------------------------------------------------
# Page 2 : standards disponibles
# ---------------------------------------------------------------------------

class StandardsPage(Page):
    title = "2. Standards"

    def build(self):
        self.boxes = {
            "use_2x_thru": QCheckBox("2x-thru (ligne A + ligne B bout a bout)"),
            "use_second_2x_thru": QCheckBox("Second 2x-thru (caracterise le second cote)"),
            "use_fixtured_dut": QCheckBox("Mesure du DUT monte entre les deux lignes"),
            "use_open_a": QCheckBox("OPEN, cote A (entree)"),
            "use_short_a": QCheckBox("SHORT, cote A (entree)"),
            "use_open_b": QCheckBox("OPEN, cote B (sortie)"),
            "use_short_b": QCheckBox("SHORT, cote B (sortie)"),
        }

        standards = QGroupBox("Ce que j'ai mesure")
        standards_layout = QVBoxLayout(standards)
        for box in self.boxes.values():
            standards_layout.addWidget(box)

        self.thru_mode = QComboBox()
        self.thru_mode.addItem("Longueur du thru connue", "known")
        self.thru_mode.addItem("Longueur estimee par le calcul", "estimated")

        self.thru_length = QDoubleSpinBox()
        self.thru_length.setRange(0.0, 100.0)
        self.thru_length.setDecimals(4)
        self.thru_length.setSuffix(" ns")

        thru_box = QGroupBox("2x-thru")
        thru_layout = QFormLayout(thru_box)
        thru_layout.addRow("Longueur :", self.thru_mode)
        thru_layout.addRow("Valeur :", self.thru_length)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#f4f4f4; padding:8px; border:1px solid #ddd;")

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(Title("Standards disponibles"))
        layout.addWidget(Hint(
            "Cocher uniquement ce qui a ete mesure. OPEN et SHORT s'utilisent "
            "separement ou ensemble. Avec les deux cotes A et B, les lignes "
            "peuvent avoir des longueurs differentes ; avec un seul cote plus un "
            "2x-thru, l'autre cote est deduit exactement."))
        layout.addWidget(standards)
        layout.addWidget(thru_box)
        layout.addWidget(self.summary)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

        for box in self.boxes.values():
            box.stateChanged.connect(self.store)
        self.thru_mode.currentIndexChanged.connect(self.store)
        self.thru_length.valueChanged.connect(self.store)

        self.load()

    def load(self):
        config = self.session.config
        for name, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(getattr(config, name))
            box.blockSignals(False)
        self.thru_mode.setCurrentIndex(max(0, self.thru_mode.findData(config.thru_length_mode)))
        self.thru_length.setValue(config.known_thru_length_ns)
        self.describe()

    def store(self, *_):
        config = self.session.config
        for name, box in self.boxes.items():
            setattr(config, name, box.isChecked())
        config.thru_length_mode = self.thru_mode.currentData()
        config.known_thru_length_ns = self.thru_length.value()
        self.describe()
        self.context.standards_changed()

    def describe(self):
        required = self.session.required_standards()
        if not required:
            self.summary.setText("Aucun standard selectionne : rien ne pourra etre extrait.")
            return

        lines = ["Fichiers a fournir en page 3 :"]
        lines += [f"  - {label}" for _, label in required]

        config = self.session.config
        both_sides = (config.use_open_a or config.use_short_a) and \
                     (config.use_open_b or config.use_short_b)

        if both_sides:
            lines.append("")
            lines.append("Les deux cotes sont mesures : les lignes peuvent etre "
                         "de longueurs differentes, aucune symetrie n'est supposee.")
        elif config.use_2x_thru and config.use_second_2x_thru:
            lines.append("")
            lines.append("Deux 2x-thru : chacun caracterise un cote, les longueurs "
                         "peuvent differer.")
        elif config.use_2x_thru:
            lines.append("")
            lines.append("2x-thru seul : les deux moities sont supposees identiques.")

        self.summary.setText("\n".join(lines))

    def on_enter(self):
        self.load()


# ---------------------------------------------------------------------------
# Page 3 : extraction
# ---------------------------------------------------------------------------

class ExtractionPage(Page):
    title = "3. Extraction"

    def build(self):
        self.rows: dict = {}

        self.files_box = QGroupBox("Fichiers de mesure")
        self.files_layout = QVBoxLayout(self.files_box)

        # --- modele d'extraction ----------------------------------------
        self.model_group = QButtonGroup(self)
        model_box = QGroupBox("Modele d'extraction S1P -> S2P")
        model_layout = QVBoxLayout(model_box)

        for value, text in (
            ("single_discontinuity",
             "Discontinuite unique (exact, recommande)"),
            ("line_fit",
             "Modele de ligne ajuste (moindres carres, jusqu'a 1 THz)"),
            ("first_order",
             "Premier ordre (ancienne formule, reflexions multiples negligees)"),
        ):
            button = QRadioButton(text)
            button.setProperty("value", value)
            self.model_group.addButton(button)
            model_layout.addWidget(button)

        model_layout.addWidget(Hint(
            "Le modele de ligne moyenne le bruit sur toute la bande : a utiliser "
            "des que l'echo aller-retour approche le plancher de bruit, "
            "typiquement au-dela de 100 GHz."))

        # --- standards de reflexion --------------------------------------
        self.usage_group = QButtonGroup(self)
        usage_box = QGroupBox("Standard de reflexion a utiliser")
        usage_layout = QVBoxLayout(usage_box)

        for value, text in (
            ("auto", "Automatique : OPEN + SHORT si les deux sont charges"),
            ("open", "OPEN seul"),
            ("short", "SHORT seul"),
            ("combined", "OPEN + SHORT uniquement (exige les deux)"),
        ):
            button = QRadioButton(text)
            button.setProperty("value", value)
            self.usage_group.addButton(button)
            usage_layout.addWidget(button)

        # --- traitement du signal ----------------------------------------
        self.interpolation = QComboBox()
        self.interpolation.addItems(["Linear", "Akima", "Cubic", "Pchip"])

        self.smoothing = QSpinBox()
        self.smoothing.setRange(0, 201)
        self.smoothing.setSingleStep(2)

        self.passivity = QCheckBox("Imposer la passivite (|S21| <= limite)")
        self.eps_r = QDoubleSpinBox()
        self.eps_r.setRange(1.0, 20.0)
        self.eps_r.setDecimals(3)
        self.eps_r.setSingleStep(0.1)

        self.export_format = QComboBox()
        for value, text in (("db", "dB / angle"), ("ma", "Magnitude / angle"),
                            ("ri", "Reel / imaginaire")):
            self.export_format.addItem(text, value)

        self.output_dir = QLineEdit(str(self.session.output_dir))
        output_button = QPushButton("Parcourir...")
        output_button.clicked.connect(self.choose_output)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir)
        output_row.addWidget(output_button)

        settings_box = QGroupBox("Traitement")
        settings_layout = QFormLayout(settings_box)
        settings_layout.addRow("Interpolation :", self.interpolation)
        settings_layout.addRow("Lissage (points, 0 = aucun) :", self.smoothing)
        settings_layout.addRow("", self.passivity)
        settings_layout.addRow("Epsilon r effectif :", self.eps_r)
        settings_layout.addRow("Format d'export :", self.export_format)
        settings_layout.addRow("Dossier de sortie :", output_row)

        # --- filtrage -----------------------------------------------------
        self.filter_enable = QCheckBox("Filtrer les parametres S avant extraction")
        self.filter_method = QComboBox()
        self.filter_method.addItems([
            "Savitzky-Golay", "Moving Average", "Gaussian", "Median",
            "Butterworth", "FIR", "Wiener", "Wavelet", "Phase Only",
        ])
        self.filter_window = QSpinBox()
        self.filter_window.setRange(3, 501)
        self.filter_order = QSpinBox()
        self.filter_order.setRange(1, 9)
        self.filter_sigma = QDoubleSpinBox()
        self.filter_sigma.setRange(0.1, 50.0)
        self.filter_cutoff = QDoubleSpinBox()
        self.filter_cutoff.setRange(0.01, 0.99)
        self.filter_cutoff.setSingleStep(0.05)

        filter_box = QGroupBox("Filtrage (optionnel)")
        filter_layout = QFormLayout(filter_box)
        filter_layout.addRow(self.filter_enable)
        filter_layout.addRow("Methode :", self.filter_method)
        filter_layout.addRow("Fenetre :", self.filter_window)
        filter_layout.addRow("Ordre :", self.filter_order)
        filter_layout.addRow("Sigma :", self.filter_sigma)
        filter_layout.addRow("Frequence de coupure :", self.filter_cutoff)

        # --- action et resultats ------------------------------------------
        self.calculate_button = QPushButton("Calculer les fixtures")
        self.calculate_button.setStyleSheet("font-weight:600; padding:6px 14px;")
        self.calculate_button.clicked.connect(self.calculate)

        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(
            ["Fixture", "Z (ohm)", "TTD (ps)", "Longueur (mm)", "Modele", "Echo/bruit (dB)"])
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.setMinimumHeight(140)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)

        self.plot = PlotView(compact=True)

        settings = QWidget()
        settings_column = QVBoxLayout(settings)
        settings_column.addWidget(Title("Extraction des fixtures"))
        settings_column.addWidget(self.files_box)
        settings_column.addWidget(model_box)
        settings_column.addWidget(usage_box)
        settings_column.addWidget(settings_box)
        settings_column.addWidget(filter_box)
        settings_column.addWidget(self.calculate_button)
        settings_column.addWidget(QLabel("Resultats :"))
        settings_column.addWidget(self.results)
        settings_column.addWidget(self.log_view)
        settings_column.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scrollable(settings))
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

        for button in self.model_group.buttons() + self.usage_group.buttons():
            button.toggled.connect(self.store)
        self.interpolation.currentIndexChanged.connect(self.store)
        self.smoothing.valueChanged.connect(self.store)
        self.passivity.stateChanged.connect(self.store)
        self.eps_r.valueChanged.connect(self.store)
        self.export_format.currentIndexChanged.connect(self.store)
        self.output_dir.editingFinished.connect(self.store)
        self.filter_enable.stateChanged.connect(self.store)
        self.filter_method.currentIndexChanged.connect(self.store)
        for widget in (self.filter_window, self.filter_order,
                       self.filter_sigma, self.filter_cutoff):
            widget.valueChanged.connect(self.store)

        self.load()
        self.rebuild_file_rows()

    # -- reglages --------------------------------------------------------

    def load(self):
        extraction = self.session.extraction

        for button in self.model_group.buttons():
            button.setChecked(button.property("value") == extraction.model)
        for button in self.usage_group.buttons():
            button.setChecked(button.property("value") == extraction.reflect_usage)

        self.interpolation.setCurrentText(extraction.interp_method)
        self.smoothing.setValue(extraction.smooth_points)
        self.passivity.setChecked(extraction.enforce_passivity)
        self.eps_r.setValue(extraction.eps_r_eff)
        self.export_format.setCurrentIndex(
            max(0, self.export_format.findData(extraction.export_format)))

        self.filter_enable.setChecked(extraction.enable_filter)
        self.filter_method.setCurrentText(extraction.filter_method)
        self.filter_window.setValue(extraction.filter_window)
        self.filter_order.setValue(extraction.filter_order)
        self.filter_sigma.setValue(extraction.filter_sigma)
        self.filter_cutoff.setValue(extraction.filter_cutoff)

    def store(self, *_):
        extraction = self.session.extraction

        checked = self.model_group.checkedButton()
        if checked is not None:
            extraction.model = checked.property("value")

        checked = self.usage_group.checkedButton()
        if checked is not None:
            extraction.reflect_usage = checked.property("value")

        extraction.interp_method = self.interpolation.currentText()
        extraction.smooth_points = self.smoothing.value()
        extraction.enforce_passivity = self.passivity.isChecked()
        extraction.eps_r_eff = self.eps_r.value()
        extraction.export_format = self.export_format.currentData()

        extraction.enable_filter = self.filter_enable.isChecked()
        extraction.filter_method = self.filter_method.currentText()
        extraction.filter_window = self.filter_window.value()
        extraction.filter_order = self.filter_order.value()
        extraction.filter_sigma = self.filter_sigma.value()
        extraction.filter_cutoff = self.filter_cutoff.value()

        directory = self.output_dir.text().strip()
        if directory:
            self.session.output_dir = Path(directory)

    def choose_output(self, *_):
        chosen = QFileDialog.getExistingDirectory(self, "Dossier de sortie",
                                                  str(self.session.output_dir))
        if chosen:
            self.output_dir.setText(chosen)
            self.store()

    # -- fichiers --------------------------------------------------------

    def rebuild_file_rows(self):
        """La liste des fichiers suit les cases cochees en page 2."""

        while self.files_layout.count():
            item = self.files_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.rows = {}
        required = self.session.required_standards()

        if not required:
            self.files_layout.addWidget(Hint("Aucun standard selectionne en page 2."))
            return

        for key, label in required:
            row = FileRow(key, label)
            row.changed.connect(self.file_chosen)
            if key in self.session.standard_files:
                row.set_path(self.session.standard_files[key])
                row.set_status("charge", True)
            self.files_layout.addWidget(row)
            self.rows[key] = row

    def file_chosen(self, key: str, path: str):
        row = self.rows.get(key)
        if not path:
            self.session.forget_standard(key)
            if row:
                row.set_status("", True)
            return

        try:
            network = self.session.load_standard(key, path)
        except Exception as error:
            if row:
                row.set_status("refuse", False)
            QMessageBox.warning(self, "Fichier refuse", str(error))
            return

        if row:
            row.set_status(f"{network.nports} port(s), "
                           f"{len(network.f)} points", True)

        self.context.refresh_sources()
        self.context.status(f"{STANDARD_LABELS.get(key, key)} charge : {Path(path).name}")

    # -- calcul -----------------------------------------------------------

    def calculate(self, *_):
        self.store()
        self.context.busy(True)
        try:
            report = self.session.calculate()
        except Exception as error:
            log.exception("Extraction impossible")
            QMessageBox.critical(self, "Erreur d'extraction", str(error))
            return
        finally:
            self.context.busy(False)

        self.log_view.setPlainText(report.text())
        self.fill_results()
        self.context.refresh_sources()
        self.context.set_warnings(self.session.warnings)

        if report.ok:
            labels = [name for name in self.session.plot_sources()
                      if name.startswith("Fixture ")]
            self.plot.select_only(labels or list(self.session.plot_sources())[:1],
                                  parameters=("S11", "S21"), format_key="db")
            self.context.status(f"Fixtures : {self.session.assembly_label()}")
        else:
            self.context.status("Extraction incomplete : voir le journal.")

    def fill_results(self):
        rows = []

        for key, result in sorted(self.session.fixture_results.items()):
            rows.append((key,
                         f"{result.impedance_ohm:.2f}",
                         f"{result.delay_ps:.1f}",
                         f"{(result.length_mm or 0.0):.2f}",
                         str(result.quality.get("model", "")),
                         f"{result.quality.get('echo_snr_db', float('nan')):.0f}"))

        for key, information in sorted(self.session.extracted_info.items()):
            if key in self.session.fixture_results or "z1" not in information:
                continue
            rows.append((f"{key} (half)",
                         f"{information['z1']:.2f}",
                         f"{information['delay1']:.1f}",
                         f"{information.get('length1', 0.0):.2f}",
                         "2x-thru", "-"))

        self.results.setRowCount(len(rows))
        for index, values in enumerate(rows):
            for column, value in enumerate(values):
                self.results.setItem(index, column, QTableWidgetItem(value))

    def on_enter(self):
        self.rebuild_file_rows()
        self.plot.set_sources(self.session.plot_sources())

    def standards_changed(self):
        self.rebuild_file_rows()


# ---------------------------------------------------------------------------
# Page 4 : retrait des fixtures
# ---------------------------------------------------------------------------

class DeembedPage(Page):
    title = "4. De-embedding"

    def build(self):
        self.raw_row = FileRow("RAW", "Mesure brute (ligne A + DUT + ligne B)")
        self.raw_row.changed.connect(self.raw_chosen)

        self.apply_a = QCheckBox("Retirer le fixture d'entree (ligne A)")
        self.apply_b = QCheckBox("Retirer le fixture de sortie (ligne B)")
        self.apply_a.setChecked(True)
        self.apply_b.setChecked(True)

        self.fixture_text = QLabel("Aucun fixture calcule pour l'instant.")
        self.fixture_text.setWordWrap(True)
        self.fixture_text.setStyleSheet("background:#f4f4f4; padding:8px; border:1px solid #ddd;")

        self.run_button = QPushButton("Retirer les fixtures et enregistrer")
        self.run_button.setStyleSheet("font-weight:600; padding:6px 14px;")
        self.run_button.clicked.connect(self.apply_correction)

        self.compare_button = QPushButton("Comparer avant / apres")
        self.compare_button.clicked.connect(self.show_comparison)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(180)

        self.plot = PlotView(compact=True)

        controls = QWidget()
        column = QVBoxLayout(controls)
        column.addWidget(Title("Retirer les fixtures d'une mesure"))
        column.addWidget(Hint(
            "Le DUT seul s'obtient en retirant la ligne d'entree et la ligne de "
            "sortie de la mesure brute : DUT = A^-1 ** mesure ** B^-1. "
            "Le graphe compare la mesure et le resultat."))
        column.addWidget(self.raw_row)
        column.addWidget(self.apply_a)
        column.addWidget(self.apply_b)
        column.addWidget(self.fixture_text)

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.compare_button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        column.addWidget(Separator())
        column.addWidget(self.report)
        column.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scrollable(controls))
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

    def raw_chosen(self, _key, path):
        if not path:
            return
        try:
            measured = self.session.load_raw_measurement(path)
        except Exception as error:
            self.raw_row.set_status("refuse", False)
            QMessageBox.warning(self, "Fichier refuse", str(error))
            return

        self.raw_row.set_status(f"{len(measured.f)} points", True)
        self.context.refresh_sources()
        self.plot.select_only([RAW_LABEL], parameters=("S11", "S21"))

    def apply_correction(self, *_):
        self.context.busy(True)
        try:
            report = self.session.deembed(use_input=self.apply_a.isChecked(),
                                          use_output=self.apply_b.isChecked())
        except Exception as error:
            log.exception("De-embedding impossible")
            QMessageBox.critical(self, "Erreur de de-embedding", str(error))
            return
        finally:
            self.context.busy(False)

        self.report.setPlainText(report.text())
        self.context.refresh_sources()
        self.context.set_warnings(self.session.warnings)

        if report.ok:
            self.show_comparison()
            self.context.status("De-embedding termine.")

    def show_comparison(self, *_):
        self.plot.select_only([RAW_LABEL, DEEMBEDDED_LABEL],
                              parameters=("S21",), format_key="db")

    def on_enter(self):
        self.plot.set_sources(self.session.plot_sources())
        self.fixture_text.setText(
            f"Fixtures disponibles : {self.session.assembly_label()}\n"
            f"Entree : {'oui' if self.session.fixture_a_network is not None else 'non'} | "
            f"Sortie : {'oui' if self.session.fixture_b_network is not None else 'non'}")


# ---------------------------------------------------------------------------
# Page 5 : enregistrement
# ---------------------------------------------------------------------------

class SavePage(Page):
    title = "5. Enregistrer"

    def build(self):
        self.base_name = QLineEdit("AFR")
        self.format_box = QComboBox()
        for value, text in (("db", "dB / angle"), ("ma", "Magnitude / angle"),
                            ("ri", "Reel / imaginaire")):
            self.format_box.addItem(text, value)

        self.output_dir = QLineEdit(str(self.session.output_dir))
        browse = QPushButton("Parcourir...")
        browse.clicked.connect(self.choose_output)

        directory_row = QHBoxLayout()
        directory_row.addWidget(self.output_dir)
        directory_row.addWidget(browse)

        form = QGroupBox("Fichiers a ecrire")
        form_layout = QFormLayout(form)
        form_layout.addRow("Nom de base :", self.base_name)
        form_layout.addRow("Format :", self.format_box)
        form_layout.addRow("Dossier :", directory_row)

        self.save_button = QPushButton("Enregistrer les fixtures A et B")
        self.save_button.clicked.connect(self.save)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(Title("Enregistrer les fixtures"))
        layout.addWidget(Hint(
            "Les fixtures extraits sont ecrits en Touchstone 2 ports, prets a etre "
            "compares a une reference dans un simulateur."))
        layout.addWidget(form)
        layout.addWidget(self.save_button)
        layout.addWidget(self.log_view)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

    def choose_output(self, *_):
        chosen = QFileDialog.getExistingDirectory(self, "Dossier de sortie",
                                                  str(self.session.output_dir))
        if chosen:
            self.output_dir.setText(chosen)

    def save(self, *_):
        directory = self.output_dir.text().strip()
        if directory:
            self.session.output_dir = Path(directory)
        self.session.extraction.export_format = self.format_box.currentData()

        report = self.session.save_fixtures(self.base_name.text())
        self.log_view.setPlainText(report.text())
        self.context.status("Fixtures enregistres." if report.ok
                            else "Enregistrement impossible.")

    def on_enter(self):
        self.output_dir.setText(str(self.session.output_dir))
        index = self.format_box.findData(self.session.extraction.export_format)
        if index >= 0:
            self.format_box.setCurrentIndex(index)


# ---------------------------------------------------------------------------
# Page 6 : traitement par lot
# ---------------------------------------------------------------------------

class BatchPage(Page):
    title = "6. Lot"

    def build(self):
        self.input_row = FileRow("IN", "Dossier des mesures", directory=True)
        self.output_row = FileRow("OUT", "Dossier de sortie", directory=True)

        self.pattern = QLineEdit("*.s2p")
        self.apply_a = QCheckBox("Retirer le fixture d'entree")
        self.apply_b = QCheckBox("Retirer le fixture de sortie")
        self.apply_a.setChecked(True)
        self.apply_b.setChecked(True)

        form = QGroupBox("Configuration du lot")
        form_layout = QFormLayout(form)
        form_layout.addRow(self.input_row)
        form_layout.addRow(self.output_row)
        form_layout.addRow("Motif :", self.pattern)
        form_layout.addRow(self.apply_a)
        form_layout.addRow(self.apply_b)

        self.run_button = QPushButton("Lancer le lot")
        self.run_button.clicked.connect(self.run)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(240)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(Title("Traitement par lot"))
        layout.addWidget(Hint(
            "Applique les fixtures calcules en page 3 a tous les fichiers d'un "
            "dossier. Le dossier de sortie est cree si besoin."))
        layout.addWidget(form)
        layout.addWidget(self.run_button)
        layout.addWidget(self.log_view)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

    def run(self, *_):
        self.context.busy(True)
        try:
            report = self.session.run_batch(
                self.input_row.value(), self.output_row.value() or None,
                self.pattern.text().strip() or "*.s2p",
                use_input=self.apply_a.isChecked(),
                use_output=self.apply_b.isChecked())
        except Exception as error:
            log.exception("Lot impossible")
            QMessageBox.critical(self, "Erreur de lot", str(error))
            return
        finally:
            self.context.busy(False)

        self.log_view.setPlainText(report.text())
        self.context.status("Lot termine." if report.ok else "Lot termine avec des echecs.")


PAGES = (ConfigurationPage, StandardsPage, ExtractionPage,
         DeembedPage, SavePage, BatchPage)
