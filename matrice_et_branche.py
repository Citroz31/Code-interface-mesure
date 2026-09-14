import os
import logging
import shutil
import tkinter as tk

from pathlib import Path
from dataclasses import dataclass, asdict
from tkinter import ttk, messagebox, filedialog, simpledialog

import numpy as np
import skrf as rf
from afr import deembed as afr_deembed
from afr import io as afr_io
from afr import metrics as afr_metrics
from afr import reflect as afr_reflect
from afr import signal as afr_signal
from afr import thru as afr_thru
from gui.plot_window import PlotWindow

log = logging.getLogger("afr.gui")

EPS = 1e-12
APP_BG = "#e6e6e6"
PANEL_BG = "#e6e6e6"
CANVAS_BG = "#e6e6e6"
BORDER_COLOR = "#b5b5b5"


@dataclass
class AFRConfiguration:
    input_mode: str = "single_ended"
    measurement_mode: str = "2_ports"
    multiport_count: int = 4
    use_thrus: bool = False
    reference_z0_mode: str = "fixed"
    reference_z0_ohm: float = 50.0
    set_system_z0: bool = False
    correct_match_ab: bool = False
    correct_length_ab: bool = False
    band_limited: bool = False
    characterization_fixture_different: bool = False

    use_2x_thru: bool = True
    use_second_2x_thru: bool = False
    use_fixtured_dut: bool = False
    use_open_a: bool = False
    use_short_a: bool = False
    use_open_b: bool = False
    use_short_b: bool = False
    thru_length_mode: str = "known"
    known_thru_length_ns: float = 0.0


class FixtureDiagram(tk.Canvas):
    """Small AFR block diagram with a homogeneous grey background."""

    COLORS = {
        "a": "#4f81bd",
        "b": "#55a6b1",
        "dut": "#7f8c8d",
        "port": "#5f9f45",
        "text": "white",
    }

    def __init__(self, parent, width=390, height=90, **kwargs):
        background = kwargs.pop("background", CANVAS_BG)

        super().__init__(
            parent,
            width=width,
            height=height,
            background=background,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            takefocus=False,
            **kwargs
        )

    def _connector(self, x1, y1, x2, y2, color):
        """Draw an RF connector on the diagram."""

        self.create_rectangle(x1, y1, x2, y2, fill=color, outline=color, width=0 )

    def _block(self, x1, y1, x2, y2, text, color):
        """Draw a fixture or DUT block."""

        self.create_rectangle( x1, y1, x2, y2, fill=color, outline=color, width=1)

        self.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=text,
            fill=self.COLORS["text"],
            font=("Segoe UI", 9, "bold")
        )

    def draw_dut_chain(self):
        """Draw Fixture A + DUT + Fixture B."""

        self.delete("all")

        y1 = 25
        y2 = 65

        self._connector(
            15,
            41,
            35,
            49,
            self.COLORS["a"]
        )

        self._block(
            35,
            y1,
            135,
            y2,
            "Fixture A",
            self.COLORS["a"]
        )

        self._block(
            135,
            y1,
            235,
            y2,
            "DUT",
            self.COLORS["dut"]
        )

        self._block(
            235,
            y1,
            335,
            y2,
            "Fixture B",
            self.COLORS["b"]
        )

        self._connector(
            335,
            41,
            360,
            49,
            self.COLORS["port"]
        )

    def draw_thru_ab(self):
        """Draw the standard Fixture A + Fixture B."""

        self.delete("all")

        y1 = 25
        y2 = 65

        self._connector(
            25,
            41,
            48,
            49,
            self.COLORS["a"]
        )

        self._block(
            48,
            y1,
            170,
            y2,
            "Fixture A",
            self.COLORS["a"]
        )

        self._block(
            170,
            y1,
            292,
            y2,
            "Fixture B",
            self.COLORS["b"]
        )

        self._connector(
            292,
            41,
            318,
            49,
            self.COLORS["port"]
        )

    def draw_thru_aa(self):
        """Draw the standard Fixture A + Fixture A'."""

        self.delete("all")

        y1 = 25
        y2 = 65

        self._connector(
            25,
            41,
            48,
            49,
            self.COLORS["a"]
        )

        self._block(
            48,
            y1,
            170,
            y2,
            "Fixture A",
            self.COLORS["a"]
        )

        self._block(
            170,
            y1,
            292,
            y2,
            "Fixture A'",
            self.COLORS["a"]
        )

        self._connector(
            292,
            41,
            318,
            49,
            self.COLORS["port"]
        )

    def draw_thru_bb(self):
        """Draw the standard Fixture B' + Fixture B."""

        self.delete("all")

        y1 = 25
        y2 = 65

        self._connector(
            25,
            41,
            48,
            49,
            self.COLORS["b"]
        )

        self._block(
            48,
            y1,
            170,
            y2,
            "Fixture B'",
            self.COLORS["b"]
        )

        self._block(
            170,
            y1,
            292,
            y2,
            "Fixture B",
            self.COLORS["b"]
        )

        self._connector(
            292,
            41,
            318,
            49,
            self.COLORS["port"]
        )

    def draw_reflect(self, fixture):
        """Draw an Open or Short standard connected to Fixture A or B."""

        self.delete("all")

        fixture_key = fixture.lower()
        color = self.COLORS[fixture_key]

        self._block(
            60,
            25,
            185,
            65,
            f"Fixture {fixture}",
            color
        )

        self._connector(
            185,
            41,
            212,
            49,
            self.COLORS["port"]
        )


class AFRWizardComplete(tk.Tk):
    def __init__(self):
        super().__init__()
        self.configure(background=APP_BG)
        self.title("Automatic Fixture Removal - AFR Pages 1 and 2")
        self.geometry("1180x760")
        self.minsize(1040, 700)
        self.config_data = AFRConfiguration()
        self.current_page = 0
        # ============================================================
        # Données et résultats RF
        # ============================================================

        self.DEBUG_PLOT = False
        self.extraction_done = False

        self.standard_files = {}
        self.converted_files = {}
        self.converted_networks = {}
        self.open_s2p_files = {}
        self.short_s2p_files = {}
        self.extracted_info = {}
        self.plot_port_names = {}
        self.fixture_results = {}
        self.port_impedance_labels = {}
        self.port_delay_labels = {}

        self.fixture_a_network = None
        self.fixture_b_network = None
        self.deembedded_network = None
        self.half_networks = {}
        self.converted_open_files = {}
        self.converted_short_files = {}
        self.converted_load_files = {}

        self.plot_sources = {}

        self.fixture_pairs = {}

        self.plot_port_names = {}

        self.half_thru_file_in = None
        self.half_thru_file_out = None
        self.converted_networks = {}

        self.rf_output_dir = tk.StringVar(value=str(Path.cwd()/ "Results"))

        Path(self.rf_output_dir.get()).mkdir(
            parents=True,
            exist_ok=True
        )

        self.export_format = tk.StringVar(value="db")

        self.plot_s11 = tk.BooleanVar(value=True)
        self.plot_s12 = tk.BooleanVar(value=True)
        self.plot_s21 = tk.BooleanVar(value=True)
        self.plot_s22 = tk.BooleanVar(value=True)
        self.sparam_vars = {
            "S11": self.plot_s11,
            "S12": self.plot_s12,
            "S21": self.plot_s21,
            "S22": self.plot_s22,
        }

        self.plot_loaded = tk.BooleanVar(value=True)
        self.plot_converted = tk.BooleanVar(value=False)
        self.plot_half_in = tk.BooleanVar(value=False)
        self.plot_half_out = tk.BooleanVar(value=False)

        # Format d'affichage du graphique
        self.plot_format = tk.StringVar(value="db_phase")
        # ==================================================
        # Filtering
        # ==================================================

        self.enable_filter = tk.BooleanVar(value=False)
        self.warnings = []

        self.filter_method = tk.StringVar(value="Savitzky-Golay")
        self.filter_window = tk.IntVar(value=11)
        self.filter_order = tk.IntVar(value=3)
        self.filter_sigma = tk.DoubleVar(value=2.0)
        self.filter_cutoff = tk.DoubleVar(value=0.10)

        # Sources à afficher
        self.plot_thru = tk.BooleanVar(value=False)
        self.plot_half_a = tk.BooleanVar(value=False)
        self.plot_half_b = tk.BooleanVar(value=False)
        self.plot_open = tk.BooleanVar(value=False)
        self.plot_short = tk.BooleanVar(value=False)

        # Fenêtre et Canvas du graphique
        self.plot_window = None
        self.plot_canvas = None

        self._style()
        self._header()
        self.container = ttk.Frame(self, padding=12)
        self.container.pack(fill="both", expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        self.pages = [ttk.Frame(self.container) for _ in range(6)]
        for page in self.pages:
            page.grid(row=0, column=0, sticky="nsew")
        self.page1, self.page2, self.page3, self.page4, self.page5, self.page6 = self.pages
        self._build_page1()
        self._build_page2()
        self._build_page3()
        self._build_page4()
        self._build_page5()
        self._build_page6()
        self._footer()
        self.show_page(0)

    def save_network(
            self,
            network,
            default_name="RESULT"
        ):
        try:
            output_file = filedialog.asksaveasfilename(
                title="Save Touchstone File",
                defaultextension=".s2p",
                initialfile=f"{default_name}.s2p",
                filetypes=[
                    ("Touchstone Files", "*.s1p *.s2p *.s4p *.s6p"),
                    ("All Files", "*.*")
                ]
            )

            if not output_file:
                return

            base_name = os.path.splitext(
                output_file
            )[0]

            network.write_touchstone(
                base_name
            )

            messagebox.showinfo(
                "Save",
                f"File saved successfully:\n{output_file}"
            )

        except Exception as e:
            import traceback

            traceback.print_exc()

            messagebox.showerror(
                "Save Error",
                str(e)
            )

    def _style(self):
        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=APP_BG,
            font=("Segoe UI", 9)
        )

        style.configure(
            "TFrame",
            background=APP_BG
        )

        style.configure(
            "TLabel",
            background=APP_BG
        )

        style.configure(
            "TLabelframe",
            background=PANEL_BG,
            bordercolor=BORDER_COLOR,
            relief="groove"
        )

        style.configure(
            "TLabelframe.Label",
            background=PANEL_BG,
            foreground="black"
        )

        style.configure(
            "TRadiobutton",
            background=PANEL_BG
        )

        style.map(
            "TRadiobutton",
            background=[
                ("active", PANEL_BG),
                ("selected", PANEL_BG)
            ]
        )

        style.configure(
            "TCheckbutton",
            background=PANEL_BG
        )

        style.map(
            "TCheckbutton",
            background=[
                ("active", PANEL_BG),
                ("selected", PANEL_BG),
                ("disabled", PANEL_BG)
            ]
        )

        style.configure(
            "PageTitle.TLabel",
            background=APP_BG,
            font=("Segoe UI", 16, "bold")
        )

        style.configure(
            "Section.TLabelframe",
            background=PANEL_BG
        )

        style.configure(
            "Section.TLabelframe.Label",
            background=PANEL_BG,
            foreground="black",
            font=("Segoe UI", 10, "bold")
        )

        style.configure(
            "TabActive.TButton",
            font=("Segoe UI", 9, "bold")
        )

    def _header(self):
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        titles = ["1. Describe Fixture", "2. Specify Standards", "3. Measure Standards",
                  "4. Remove Fixture", "5. Save Fixture", "6. Batch Process"]
        self.tab_buttons = []
        for i, title in enumerate(titles):
            b = ttk.Button(bar, text=title, command=lambda n=i: self.request_page(n))
            b.pack(side="left", padx=2)
            self.tab_buttons.append(b)
        ttk.Separator(self).pack(fill="x")

    def _footer(self):
        ttk.Separator(self).pack(fill="x")
        foot = ttk.Frame(self, padding=10)
        foot.pack(fill="x")
        ttk.Button(foot, text="User Preset...", command=self.show_configuration).pack(side="left")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(foot, textvariable=self.status).pack(side="left", padx=15)
        ttk.Button(foot, text="Exit", command=self.destroy).pack(side="right", padx=5)
        self.next_btn = ttk.Button(foot, text="Next", command=self.next_page)
        self.next_btn.pack(side="right", padx=5)
        self.back_btn = ttk.Button(foot, text="Back", command=self.previous_page)
        self.back_btn.pack(side="right", padx=5)

    # ======================================================================
    # Pont vers le noyau de calcul (paquet afr/)
    # ======================================================================

    def filter_settings(self):
        """Parametres de filtrage choisis dans l'interface (None si desactive)."""

        if not self.enable_filter.get():
            return None

        return dict(
            method=self.filter_method.get(),
            window=self.filter_window.get(),
            order=self.filter_order.get(),
            sigma=self.filter_sigma.get(),
            cutoff=self.filter_cutoff.get(),
        )

    def apply_filter(self, signal, frequency=None):
        settings = self.filter_settings()

        if settings is None:
            return np.asarray(signal, dtype=complex)

        return afr_signal.filter_complex(signal, frequency=frequency, **settings)

    def interpolation_name(self):
        """Methode d'interpolation de la grille temporelle ('Linear' si desactivee)."""

        enable = getattr(self, "enable_interpolation", None)

        if enable is None or not enable.get():
            return "Linear"

        return self.interpolation_method.get()

    def eps_r_value(self):
        """Permittivite effective saisie (1.0 par defaut ou si invalide)."""

        try:
            value = float(self.eps_r_eff.get())
        except (tk.TclError, ValueError, AttributeError):
            value = 1.0

        return value if value > 0 else 1.0

    def extraction_options(self):
        """Options d'extraction communes aux methodes S1P et 2x-thru."""

        try:
            smooth = int(self.smooth_points.get())
        except (tk.TclError, ValueError, AttributeError):
            smooth = 0

        return dict(
            interp_method=self.interpolation_name(),
            smooth_points=max(0, smooth),
            enforce_passivity=bool(self.enforce_passivity.get()),
            model=self.extraction_model.get(),
        )

    def report_quality(self, label, result):
        """Journalise les indicateurs de qualite et affiche les avertissements."""

        quality = result.quality

        log.info("%s : mode %s, modele %s, passif %s, |S|max %.4f",
                 label, quality.get("mode"), quality.get("model"),
                 quality.get("passive"), quality.get("max_singular_value", float("nan")))

        clamped = quality.get("clamped_points", 0)
        if clamped:
            self.add_warning(f"{label} : {clamped} point(s) de |S21| au-dessus de la "
                             f"limite passive ont ete ramenes a cette limite.")

        if quality.get("warning"):
            self.add_warning(f"{label} : {quality['warning']}")

        if not quality.get("passive", True):
            self.add_warning(f"{label} : reseau non passif "
                             f"(valeur singuliere max {quality.get('max_singular_value', 0):.3f}).")

    def add_warning(self, message):
        """Empile un avertissement et le montre dans la zone de resultats."""

        self.warnings.append(message)
        log.warning(message)

        if hasattr(self, "warning_text"):
            self.warning_text.config(state="normal")
            self.warning_text.insert("end", message + "\n")
            self.warning_text.see("end")
            self.warning_text.config(state="disabled")

    def clear_warnings(self):
        self.warnings = []

        if hasattr(self, "warning_text"):
            self.warning_text.config(state="normal")
            self.warning_text.delete("1.0", "end")
            self.warning_text.config(state="disabled")

    def build_afr_s2p_from_s1p(self, filename, reflect_type=None):
        """
        S2P d'un fixture a partir d'un S1P OPEN ou SHORT (voir afr.reflect).
        Retourne un afr.FixtureResult (reseau, impedance, delai, longueur).
        """

        ntwk = afr_io.load_network(filename, expected_ports=1)
        freq = ntwk.f
        gamma = self.apply_filter(ntwk.s[:, 0, 0], freq)

        result = afr_reflect.fixture_from_reflect(
            freq,
            gamma,
            reflect_type or filename,
            z0=afr_io.reference_impedance(ntwk),
            **self.extraction_options(),
        )
        result.with_length(self.eps_r_value())

        label = reflect_type or Path(filename).stem
        log.info(
            "%s : Z = %.1f ohm, TTD = %.1f ps, longueur = %.2f mm",
            label, result.impedance_ohm, result.delay_ps, result.length_mm,
        )
        self.report_quality(label, result)
        return result

    def build_open_short_fixture(self, open_file, short_file):
        """Fixture extrait des mesures OPEN et SHORT combinees (afr.reflect)."""

        n_open = afr_io.load_network(open_file, expected_ports=1)
        n_short = afr_io.load_network(short_file, expected_ports=1)

        if len(n_open.f) != len(n_short.f) or not np.allclose(n_open.f, n_short.f):
            n_short = n_short.interpolate(n_open.frequency)

        freq = n_open.f

        result = afr_reflect.fixture_from_open_short(
            freq,
            self.apply_filter(n_open.s[:, 0, 0], freq),
            self.apply_filter(n_short.s[:, 0, 0], freq),
            z0=afr_io.reference_impedance(n_open),
            **self.extraction_options(),
        )
        self.report_quality(f"{Path(open_file).stem} + {Path(short_file).stem}", result)
        return result.with_length(self.eps_r_value())

    def build_half_thru(self, thru_file, source_key="THRU_LINE1"):
        """
        Decoupe un 2x-thru en deux demi-fixtures (afr.thru) et les exporte.
        Retourne (half_in, half_out, information).
        """

        thru = afr_io.load_network(thru_file, expected_ports=2)
        freq = thru.f

        filtered = thru.copy()
        s = filtered.s.copy()
        for i in range(2):
            for j in range(2):
                s[:, i, j] = self.apply_filter(s[:, i, j], freq)
        filtered.s = s

        half_in, half_out, information = afr_thru.split_2x_thru(
            filtered,
            self.interpolation_name(),
        )

        for key, value in information["quality"].items():
            if key == "warning":
                self.add_warning(f"{source_key} : {value}")

        length_mm = afr_metrics.physical_length(
            information["delay1"] * 1e-12,
            self.eps_r_value(),
        ) * 1e3
        information["length1"] = length_mm
        information["length2"] = length_mm

        output_dir = Path(self.rf_output_dir.get())
        form = self.export_format.get()

        self.half_thru_file_in = str(
            afr_io.write_network(half_in, output_dir / f"{source_key}_HALF_IN", form)
        )
        self.half_thru_file_out = str(
            afr_io.write_network(half_out, output_dir / f"{source_key}_HALF_OUT", form)
        )

        self.converted_files[f"{source_key}_IN"] = self.half_thru_file_in
        self.converted_files[f"{source_key}_OUT"] = self.half_thru_file_out

        log.info(
            "%s : TTD total = %.1f ps, demi = %.1f ps, Z1 = %.1f ohm, Z2 = %.1f ohm",
            source_key, information["delay_total_ps"], information["delay1"],
            information["z1"], information["z2"],
        )
        return half_in, half_out, information

    def remove_fixture(self, dut_file, fixture_in, fixture_out):
        """DUT de-embedde (afr.deembed)."""

        dut = afr_io.load_network(dut_file, expected_ports=2)
        dut.name = Path(dut_file).stem
        return afr_deembed.remove_fixtures(dut, fixture_in, fixture_out)

    def reflect_fixture_network(self, side):
        """Reseau du fixture 'side' (A/B) issu des reflexions, le meilleur disponible."""

        for key in (f"REFLECT_{side}", f"OPEN_{side}", f"SHORT_{side}"):
            result = self.fixture_results.get(key)
            if result is not None:
                return result.network

        return None

    # ======================================================================
    # Lignes de resultats (Z, TTD, longueur)
    # ======================================================================

    @staticmethod
    def row_name(port):
        return port if isinstance(port, str) else f"Port {port}"

    def create_port_result_row(self, port):
        if port in self.port_result_rows:
            return

        name = self.row_name(port)
        row = len(self.port_result_rows)

        z_var = tk.StringVar(value=f"{name} Z = --")
        d_var = tk.StringVar(value=f"{name} TTD = --")
        l_var = tk.StringVar(value=f"{name} Length = --")

        for column, var in enumerate((z_var, d_var, l_var)):
            ttk.Label(self.result_frame, textvariable=var).grid(
                row=row, column=column, sticky="w", padx=10
            )

        self.port_result_rows[port] = (z_var, d_var, l_var)

    def set_result_row(self, port, impedance, delay_ps, source=None):
        """Met a jour Z, TTD et longueur d'une ligne de resultats."""

        self.create_port_result_row(port)
        z_var, d_var, _ = self.port_result_rows[port]
        name = self.row_name(port)
        suffix = f"  [{source}]" if source else ""

        if impedance is None or not np.isfinite(impedance):
            z_var.set(f"{name} Z = --  (pas de continu dans la bande)")
        else:
            z_var.set(f"{name} Z = {impedance:.2f} Ohm")
        d_var.set(f"{name} TTD = {delay_ps:.2f} ps{suffix}")

        self.row_delays[port] = delay_ps
        self.refresh_length_labels()

    def refresh_length_labels(self):
        """Recalcule les longueurs affichees (appele quand eps_r change)."""

        eps = self.eps_r_value()

        for port, delay_ps in getattr(self, "row_delays", {}).items():
            rows = self.port_result_rows.get(port)
            if rows is None or delay_ps is None:
                continue

            length_mm = afr_metrics.physical_length(delay_ps * 1e-12, eps) * 1e3
            rows[2].set(f"{self.row_name(port)} Length = {length_mm:.2f} mm (εr = {eps:g})")

    def calculate_reflection_fixtures(self):
        """OPEN / SHORT -> fixtures, puis combinaison OPEN + SHORT par cote."""

        reflection_keys = [
            key for key in self.standard_files
            if key.startswith(("OPEN_", "SHORT_"))
        ]

        output_dir = Path(self.rf_output_dir.get())
        form = self.export_format.get()

        for key in reflection_keys:
            result = self.build_afr_s2p_from_s1p(self.standard_files[key], reflect_type=key)

            self.fixture_results[key] = result
            self.converted_networks[key] = result.network
            self.half_networks[f"{key}_HALF"] = result.network
            self.extracted_info[key] = result.as_info()

            converted_path = str(
                afr_io.write_network(result.network, output_dir / f"{key}_CONVERTED", form)
            )
            self.converted_files[key] = converted_path

            if key.startswith("OPEN_"):
                self.converted_open_files[key] = converted_path
            else:
                self.converted_short_files[key] = converted_path

        # OPEN + SHORT du meme fixture : extraction combinee
        sides = sorted({key.split("_", 1)[1] for key in reflection_keys})

        for side in sides:
            open_key, short_key = f"OPEN_{side}", f"SHORT_{side}"

            if open_key not in self.standard_files or short_key not in self.standard_files:
                continue

            combined_key = f"REFLECT_{side}"

            try:
                result = self.build_open_short_fixture(
                    self.standard_files[open_key],
                    self.standard_files[short_key],
                )
            except Exception as error:
                log.warning("Combinaison OPEN/SHORT %s impossible : %s", side, error)
                continue

            self.fixture_results[combined_key] = result
            self.converted_networks[combined_key] = result.network
            self.half_networks[f"{combined_key}_HALF"] = result.network
            self.extracted_info[combined_key] = result.as_info()
            self.converted_files[combined_key] = str(
                afr_io.write_network(result.network, output_dir / f"{combined_key}_CONVERTED", form)
            )

            quality = result.quality
            log.info(
                "OPEN/SHORT %s : ecart S21 open/short = %.2f dB / %.1f deg",
                side,
                quality.get("open_short_mag_db", float("nan")),
                quality.get("open_short_phase_deg", float("nan")),
            )

        # Sans 2x-thru, les fixtures A / B viennent des reflexions
        if self.fixture_a_network is None:
            self.fixture_a_network = self.reflect_fixture_network("A")

        if self.fixture_b_network is None:
            net_b = self.reflect_fixture_network("B")
            self.fixture_b_network = afr_thru.port_swap(net_b) if net_b is not None else None

    def update_fixture_result_labels(self):
        """Lignes 'Fixture A / B' : Z, TTD et longueur issus des reflexions."""

        for side in ("A", "B"):
            for key in (f"REFLECT_{side}", f"OPEN_{side}", f"SHORT_{side}"):
                info = self.extracted_info.get(key)

                if info and "z" in info:
                    self.set_result_row(f"Fixture {side}", info["z"], info["delay"], key)
                    break

        self.refresh_length_labels()

    def run_batch(self):
        """Page 6 : de-embedding de tous les fichiers DUT d'un dossier."""

        input_dir = Path(self.batch_in.get().strip())

        if not input_dir.is_dir():
            messagebox.showwarning("Invalid folder", "Choose a valid input directory.")
            return

        output_text = self.batch_out.get().strip()
        output_dir = Path(output_text) if output_text else input_dir / "deembedded"

        fixture_in = self.fixture_a_network if self.apply_a.get() else None
        fixture_out = self.fixture_b_network if self.apply_b.get() else None

        if fixture_in is None and fixture_out is None:
            messagebox.showwarning(
                "Fixtures unavailable",
                "Calculate the fixture characteristics (page 3) and select "
                "Apply Fixture A / B (page 4) before running a batch.",
            )
            return

        try:
            items = afr_deembed.batch_deembed(
                input_dir,
                output_dir,
                self.batch_pattern.get().strip() or "*.s2p",
                fixture_in,
                fixture_out,
                form=self.export_format.get(),
            )
        except Exception as error:
            messagebox.showerror("Batch error", str(error))
            return

        lines = [f"Found {len(items)} file(s). Output directory: {output_dir}", ""]

        for item in items:
            if item.ok:
                lines.append(f"[OK ] {item.source.name} -> {item.output.name}")
            else:
                lines.append(f"[ERR] {item.source.name} : {item.message}")

        failed = sum(1 for item in items if not item.ok)
        lines.append("")
        lines.append(f"Done: {len(items) - failed} processed, {failed} failed.")

        self.batch_log.config(state="normal")
        self.batch_log.delete("1.0", "end")
        self.batch_log.insert("end", "\n".join(lines) + "\n")
        self.batch_log.config(state="disabled")

        self.status.set(f"Batch finished: {len(items) - failed} file(s) de-embedded.")

    def _build_page1(self):
        ttk.Label(self.page1, text="This 6 step wizard characterizes and removes the fixture effects from your measurements",
                  style="PageTitle.TLabel").pack(anchor="w", pady=(0, 10))
        body = ttk.Frame(self.page1)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 20))
        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True)

        fixture_box = ttk.LabelFrame(left, text="My fixture inputs are", style="Section.TLabelframe", padding=10)
        fixture_box.pack(fill="x", pady=4)
        self.input_mode = tk.StringVar(value="single_ended")
        ttk.Radiobutton(fixture_box, text="Single Ended", value="single_ended", variable=self.input_mode,
                        command=self.page1_changed).pack(anchor="w")
        ttk.Radiobutton(fixture_box, text="Differential", value="differential", variable=self.input_mode,
                        command=self.page1_changed).pack(anchor="w")

        measure_box = ttk.LabelFrame(left, text="My measurement is", style="Section.TLabelframe", padding=10)
        measure_box.pack(fill="x", pady=4)
        self.measurement_mode = tk.StringVar(value="2_ports")
        ttk.Radiobutton(measure_box, text="1 Port", value="1_port", variable=self.measurement_mode,
                        command=self.page1_changed).pack(anchor="w")
        ttk.Radiobutton(measure_box, text="2 Ports", value="2_ports", variable=self.measurement_mode,
                        command=self.page1_changed).pack(anchor="w")
        mp = ttk.Frame(measure_box)
        mp.pack(anchor="w")
        ttk.Radiobutton(mp, text="Multiport", value="multiport", variable=self.measurement_mode,
                        command=self.page1_changed).pack(side="left")
        self.multiport_count = tk.IntVar(value=4)
        self.multiport_spin = ttk.Spinbox(mp, from_=3, to=32, width=5, textvariable=self.multiport_count,
                                          command=self.page1_changed)
        self.multiport_spin.pack(side="left", padx=6)
        self.use_thrus = tk.BooleanVar(value=False)
        self.use_thrus_check = ttk.Checkbutton(mp, text="Use THRUs", variable=self.use_thrus,
                                                command=self.page1_changed)
        self.use_thrus_check.pack(side="left")

        advanced = ttk.LabelFrame(left, text="Advanced Settings", style="Section.TLabelframe", padding=10)
        advanced.pack(fill="x", pady=8)
        ttk.Label(advanced, text="After fixture removal set Calibration Reference Z0 to:").pack(anchor="w")
        self.z0_mode = tk.StringVar(value="fixed")
        ttk.Radiobutton(advanced, text='"System Z0"', value="system", variable=self.z0_mode,
                        command=self.page1_changed).pack(anchor="w")
        ttk.Radiobutton(advanced, text="Measured Fixture Z0", value="measured", variable=self.z0_mode,
                        command=self.page1_changed).pack(anchor="w")
        zrow = ttk.Frame(advanced)
        zrow.pack(anchor="w")
        ttk.Radiobutton(zrow, value="fixed", variable=self.z0_mode, command=self.page1_changed).pack(side="left")
        self.z0_value = tk.DoubleVar(value=50.0)
        ttk.Entry(zrow, width=8, textvariable=self.z0_value).pack(side="left")
        ttk.Label(zrow, text="Ohms").pack(side="left", padx=5)

        self.set_system_z0 = tk.BooleanVar(value=False)
        self.correct_match = tk.BooleanVar(value=False)
        self.correct_length = tk.BooleanVar(value=False)
        self.band_limited = tk.BooleanVar(value=False)
        self.char_fixture_different = tk.BooleanVar(value=False)
        items = [
            ("Set 'System Z0' to Calibration Reference Z0", self.set_system_z0),
            ("I want to correct for Fixture Match A != B", self.correct_match),
            ("I want to correct for Fixture Length A != B", self.correct_length),
            ("My fixture is band limited (use Bandpass time domain mode)", self.band_limited),
            ("My characterization fixture != DUT measurement fixture", self.char_fixture_different),
        ]
        for text, var in items:
            ttk.Checkbutton(advanced, text=text, variable=var, command=self.page1_changed).pack(anchor="w", pady=2)

        self.main_diagram = FixtureDiagram(right, width=430, height=100)
        self.main_diagram.pack(pady=(30, 5))
        self.main_diagram.draw_dut_chain()
        ttk.Label(right, text="Current Fixture and DUT Assumptions", font=("Segoe UI", 10, "bold")).pack()
        self.assumptions = tk.StringVar()
        ttk.Label(right, textvariable=self.assumptions, justify="left", font=("Segoe UI", 11)).pack(pady=7)
        self.page1_changed()

    def _build_page2(self):
        ttk.Label(self.page2, text="For my calibration standards I have:",
                  font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 8))
        self.standard_area = ttk.LabelFrame(self.page2, text="Required and optional standards",
                                             style="Section.TLabelframe", padding=12)
        self.standard_area.pack(fill="x")
        self.standard_area.columnconfigure(1, weight=1)
        self.standard_area.columnconfigure(3, weight=1)

        self.use_2x_thru = tk.BooleanVar(value=True)
        self.use_second_2x = tk.BooleanVar(value=False)
        self.use_fixtured_dut = tk.BooleanVar(value=False)
        self.open_a = tk.BooleanVar(value=False)
        self.short_a = tk.BooleanVar(value=False)
        self.open_b = tk.BooleanVar(value=False)
        self.short_b = tk.BooleanVar(value=False)

        self.chk_2x = ttk.Checkbutton(self.standard_area, text="2X Thru", variable=self.use_2x_thru,command=self.on_2x_thru_changed)
        self.chk_2x.grid(row=0, column=0, sticky="w", pady=5)
        self.diag_2x = FixtureDiagram(self.standard_area, width=340, height=82)
        self.diag_2x.grid(row=0, column=1, sticky="w")

        self.chk_second = ttk.Checkbutton(self.standard_area, text="Second 2X Thru", variable=self.use_second_2x,command=self.on_second_2x_thru_changed)
        self.diag_second = FixtureDiagram(self.standard_area, width=340, height=82)

        self.chk_dut = ttk.Checkbutton(self.standard_area, text="Fixtured DUT", variable=self.use_fixtured_dut,command=self._store_page2)
        self.diag_dut = FixtureDiagram(self.standard_area, width=340, height=82)
        self.diag_dut.draw_dut_chain()

        self.reflect_a_frame = ttk.Frame(self.standard_area)
        self.open_a_check = ttk.Checkbutton(self.reflect_a_frame, text="Open", variable=self.open_a,command=self.on_reflect_changed)
        self.open_a_check.grid(row=0, column=0, sticky="w")
        self.short_a_check = ttk.Checkbutton(self.reflect_a_frame, text="Short", variable=self.short_a,command=self.on_reflect_changed)
        self.short_a_check.grid(row=1, column=0, sticky="w")
        self.diag_reflect_a = FixtureDiagram(self.reflect_a_frame, width=230, height=82)
        self.diag_reflect_a.grid(row=0, column=1, rowspan=2)
        self.diag_reflect_a.draw_reflect("A")

        self.reflect_b_frame = ttk.Frame(self.standard_area)

        self.open_b_check = ttk.Checkbutton(self.reflect_b_frame,text="Open",variable=self.open_b,command=self.on_reflect_changed)
        self.open_b_check.grid(row=0,column=0,sticky="w")

        self.short_b_check = ttk.Checkbutton(self.reflect_b_frame,text="Short",variable=self.short_b,command=self.on_reflect_changed)
        self.short_b_check.grid(row=1,column=0,sticky="w")
        self.diag_reflect_b = FixtureDiagram(self.reflect_b_frame, width=230, height=82)
        self.diag_reflect_b.grid(row=0, column=1, rowspan=2)
        self.diag_reflect_b.draw_reflect("B")

        advanced = ttk.LabelFrame(self.page2, text="Advanced Settings", style="Section.TLabelframe", padding=12)
        advanced.pack(fill="x", pady=14)
        ttk.Label(advanced, text="My thru fixture has:").pack(anchor="w")
        self.thru_mode = tk.StringVar(value="known")
        r = ttk.Frame(advanced)
        r.pack(anchor="w", pady=3)
        ttk.Radiobutton(r, text="Known thru length =", value="known", variable=self.thru_mode,command=self._store_page2).pack(side="left")
        self.thru_length = tk.DoubleVar(value=0.0)
        ttk.Entry(r, width=8, textvariable=self.thru_length).pack(side="left", padx=4)
        ttk.Label(r, text="ns").pack(side="left")
        ttk.Radiobutton(advanced, text="Unknown thru length computed using reflects.", value="reflects",
                        variable=self.thru_mode,command=self._store_page2).pack(anchor="w", pady=3)
        ttk.Radiobutton(advanced, text="Unknown thru length computed using fixtured DUT measurements.", value="dut",
                        variable=self.thru_mode,command=self._store_page2).pack(anchor="w", pady=3)

        self.rule_summary = tk.StringVar()
        ttk.Label(self.page2, textvariable=self.rule_summary, foreground="#364f6b",
                  font=("Segoe UI", 10, "bold"), wraplength=1050).pack(anchor="w", pady=5)

    def on_second_2x_thru_changed(self):
        """
        Désélectionne Open et Short lorsque le deuxième
        standard 2X Thru est sélectionné.
        """

        if self.use_second_2x.get():
            self.open_a.set(False)
            self.short_a.set(False)
            self.open_b.set(False)
            self.short_b.set(False)

        self._store_page2()
        self.update_standard_summary()

    def on_reflect_changed(self):
        """
        Désélectionne les standards Thru lorsqu'un standard
        Open ou Short est sélectionné.
        """

        reflect_selected = any([
            self.open_a.get(),
            self.short_a.get(),
            self.open_b.get(),
            self.short_b.get(),
        ])

        self._store_page2()
        self.update_standard_summary()

    def on_2x_thru_changed(self):
        """
        Lorsqu'un 2X Thru est sélectionné,
        les standards Open et Short sont désélectionnés.
        """

        if self.use_2x_thru.get():
            self.open_a.set(False)
            self.short_a.set(False)
            self.open_b.set(False)
            self.short_b.set(False)

        self._store_page2()
        self.update_standard_summary()

    def update_standard_summary(self):
        """Mise à jour du texte affiché sous les standards."""

        if self.use_2x_thru.get():
            self.rule_summary.set(
                "2X Thru selected. Open and Short standards are not used."
            )

        elif any([
            self.open_a.get(),
            self.short_a.get(),
            self.open_b.get(),
            self.short_b.get(),
        ]):
            selected = []

            if self.open_a.get():
                selected.append("Open Fixture A")

            if self.short_a.get():
                selected.append("Short Fixture A")

            if self.open_b.get():
                selected.append("Open Fixture B")

            if self.short_b.get():
                selected.append("Short Fixture B")

            self.rule_summary.set(
                "Reflection standards selected: "
                + ", ".join(selected)
                + ". The 2X Thru standard is disabled."
            )

        else:
            self.rule_summary.set(
                "Select either a 2X Thru standard or one or more "
                "Open/Short reflection standards."
            )

    def page1_changed(self):
        multi = self.measurement_mode.get() == "multiport"
        self.multiport_spin.configure(state="normal" if multi else "disabled")
        self.use_thrus_check.configure(state="normal" if multi else "disabled")

        match_text = "A != B" if self.correct_match.get() else "A = B"
        length_text = "A != B" if self.correct_length.get() else "A = B"
        if self.z0_mode.get() == "fixed":
            z0 = f"{self.z0_value.get():g} Ohms"
        elif self.z0_mode.get() == "measured":
            z0 = "Measured Fixture Z0"
        else:
            z0 = "System Z0"
        self.assumptions.set(
            f"Fixture Match: {match_text}\n"
            f"Fixture Length: {length_text}\n"
            f"DUT Z0 will be converted to {z0}"
        )
        self._store_page1()

    def _store_page1(self):
        c = self.config_data
        c.input_mode = self.input_mode.get()
        c.measurement_mode = self.measurement_mode.get()
        c.multiport_count = self.multiport_count.get()
        c.use_thrus = self.use_thrus.get()
        c.reference_z0_mode = self.z0_mode.get()
        c.reference_z0_ohm = self.z0_value.get()
        c.set_system_z0 = self.set_system_z0.get()
        c.correct_match_ab = self.correct_match.get()
        c.correct_length_ab = self.correct_length.get()
        c.band_limited = self.band_limited.get()
        c.characterization_fixture_different = self.char_fixture_different.get()

    def safe_grid_forget(self, widget):
        try:
            if widget is not None:
                if widget.winfo_exists():
                    widget.grid_forget()

        except Exception:
            pass

    def synchronize_page2_from_page1(self):
        """Central dependency function between Describe Fixture and Specify Standards."""

        if not hasattr(self, "chk_2x"):
            return

        if not self.chk_2x.winfo_exists():
            return

        if self.measurement_mode.get() == "multiport":
            self.build_multiport_standards()
            return
        self._store_page1()
        different = self.char_fixture_different.get()
        unequal_length = self.correct_length.get()
        unequal_match = self.correct_match.get()
        special_asymmetric_case = different and unequal_match

        # Clear dynamic widgets before placing the correct configuration.

        for widget in [
            self.chk_second,
            self.diag_second,
            self.chk_dut,
            self.diag_dut,
            self.reflect_a_frame,
            self.reflect_b_frame
        ]:
            self.safe_grid_forget(widget)

        # 2X Thru remains required in all supplied cases.

        if (
            hasattr(self, "chk_2x")
            and self.chk_2x.winfo_exists()
        ):
            self.chk_2x.configure(state="normal")

        if special_asymmetric_case:
            # Two independent symmetric characterization boards.
            self.diag_2x.draw_thru_aa()
            self.chk_second.configure(state="normal")
            self.chk_second.grid(row=1, column=0, sticky="w", pady=5)
            self.diag_second.draw_thru_bb()
            self.diag_second.grid(row=1, column=1, sticky="w")

            self.chk_dut.configure(state="normal")
            self.chk_dut.grid(row=2, column=0, sticky="w", pady=5)
            self.diag_dut.grid(row=2, column=1, sticky="w")

            self.reflect_a_frame.grid(row=0, column=2, sticky="w", padx=(20, 0))
            self.reflect_b_frame.grid(row=1, column=2, sticky="w", padx=(20, 0))
            self.rule_summary.set(
                "Characterization fixture differs from the DUT measurement fixture: "
                "2X Thru A+A' and Second 2X Thru B'+B are required. "
                "The Fixtured DUT measurement is also mandatory."
            )
        else:
            self.diag_2x.draw_thru_ab()
            self.chk_2x.configure(state="normal")
            self.use_second_2x.set(False)
            self.chk_second.configure(state="normal")
            self.use_fixtured_dut.set(False)
            self.chk_dut.configure(state="normal")

            self.reflect_a_frame.grid(row=0, column=2, sticky="w", padx=(20, 0))
            if unequal_length or unequal_match:
                self.reflect_b_frame.grid(row=1, column=2, sticky="w", padx=(20, 0))
                reason = "length" if unequal_length and not unequal_match else "match/length"
                self.rule_summary.set(
                    f"Fixture A and Fixture B have different {reason}: "
                    "one 2X Thru is used and Open/Short standards are available for both fixtures."
                )
            else:
                self.open_b.set(False)
                self.short_b.set(False)
                self.rule_summary.set(
                    "Default case: one 2X Thru A+B is required. "
                    "Open/Short standards are available only for Fixture A."
                )

        self._store_page2()

    def build_multiport_standards(self):
        for widget in self.standard_area.winfo_children():
            widget.grid_forget()

        n = self.multiport_count.get()

        self.multiport_thrus = []

        row = 0

        for port in range(1, n + 1):
            open_var = tk.BooleanVar()
            short_var = tk.BooleanVar()

            setattr(
                self,
                f"open_p{port}",
                open_var
            )

            setattr(
                self,
                f"short_p{port}",
                short_var
            )

            ttk.Checkbutton(
                self.standard_area,
                text=f"Open Port {port}",
                variable=open_var
            ).grid(
                row=row,
                column=0,
                sticky="w"
            )

            ttk.Checkbutton(
                self.standard_area,
                text=f"Short Port {port}",
                variable=short_var
            ).grid(
                row=row,
                column=1,
                sticky="w"
            )

            row += 1

        # -------------------------
        # THRU seulement après
        # -------------------------

        for p1 in range(1, n, 2):
            p2 = p1 + 1

            var = tk.BooleanVar(value=True)

            key = f"THRU_{p1}_{p2}"

            label = f"Thru {p1}-{p2}"

            self.multiport_thrus.append(
                (key, var, label)
            )

            ttk.Checkbutton(
                self.standard_area,
                text=label,
                variable=var
            ).grid(
                row=row,
                column=0,
                sticky="w"
            )

            row += 1

    def _store_page2(self):
        c = self.config_data

        c.use_2x_thru = self.use_2x_thru.get()
        c.use_second_2x_thru = self.use_second_2x.get()
        c.use_fixtured_dut = self.use_fixtured_dut.get()

        c.use_open_a = self.open_a.get()
        c.use_short_a = self.short_a.get()
        c.use_open_b = self.open_b.get()
        c.use_short_b = self.short_b.get()

        c.thru_length_mode = self.thru_mode.get()

        try:
            c.known_thru_length_ns = float(
                self.thru_length.get()
            )
        except (tk.TclError, ValueError):
            c.known_thru_length_ns = 0.0

    def validate_page2(self):
        """Validate the calibration standards selected on Page 2."""

        mode = self.thru_mode.get()

        thru_selected = (
            self.use_2x_thru.get()
            or self.use_second_2x.get()
        )

        reflect_selected = any([
            self.open_a.get(),
            self.short_a.get(),
            self.open_b.get(),
            self.short_b.get(),
        ])

        if not thru_selected and not reflect_selected:
            messagebox.showwarning(
                "No calibration standard selected",
                "Select at least one 2X Thru standard or "
                "one Open/Short reflection standard."
            )
            return False

        if mode == "known":
            if thru_selected:
                try:
                    length_ns = float(
                        self.thru_length.get()
                    )
                except (tk.TclError, ValueError):
                    messagebox.showwarning(
                        "Invalid thru length",
                        "The known thru length must be a numeric value."
                    )
                    return False

                if length_ns < 0:
                    messagebox.showwarning(
                        "Invalid thru length",
                        "The known thru length cannot be negative."
                    )
                    return False

        elif mode == "reflects":
            fixture_a_reflect = (
                self.open_a.get()
                or self.short_a.get()
            )

            fixture_b_required = (
                self.correct_match.get()
                or self.correct_length.get()
                or self.char_fixture_different.get()
            )

            fixture_b_reflect = (
                self.open_b.get()
                or self.short_b.get()
            )

            if not fixture_a_reflect:
                messagebox.showwarning(
                    "Missing Fixture A reflect",
                    "Select Open or Short for Fixture A."
                )
                return False

            if fixture_b_required and not fixture_b_reflect:
                messagebox.showwarning(
                    "Missing Fixture B reflect",
                    "Select Open or Short for Fixture B."
                )
                return False

        elif mode == "dut":
            if not self.use_fixtured_dut.get():
                messagebox.showwarning(
                    "Fixtured DUT required",
                    "The Fixtured DUT standard must be selected when "
                    "the thru length is computed using DUT measurements."
                )
                return False

        else:
            messagebox.showwarning(
                "Invalid length mode",
                "Select a valid method for determining the thru length."
            )
            return False

        self._store_page2()
        return True

    def is_multiport(self):
        return (
            self.measurement_mode.get() == "multiport"
        )

    def _selected_standard_rows(self):
        rows = []

        if self.is_multiport():
            n = self.multiport_count.get()

            for port in range(1, n + 1):
                if getattr(
                    self,
                    f"open_p{port}",
                    None
                ) and getattr(
                    self,
                    f"open_p{port}"
                ).get():
                    rows.append(
                        (
                            f"OPEN_P{port}",
                            f"Open Port {port}"
                        )
                    )

                if getattr(
                    self,
                    f"short_p{port}",
                    None
                ) and getattr(
                    self,
                    f"short_p{port}"
                ).get():
                    rows.append(
                        (
                            f"SHORT_P{port}",
                            f"Short Port {port}"
                        )
                    )

            for thru in getattr(
                self,
                "multiport_thrus",
                []
            ):
                key,var,label = thru

                if var.get():
                    rows.append(
                        (
                            key,
                            label
                        )
                    )

            return rows

        definitions = [
            ("THRU_LINE1","2X Thru",self.use_2x_thru),
            ("THRU_LINE2","Second 2X Thru",self.use_second_2x),
            ("ASYM_DUT","Fixtured DUT",self.use_fixtured_dut),
            ("OPEN_A","Open Fixture A",self.open_a),
            ("SHORT_A","Short Fixture A",self.short_a),
            ("OPEN_B","Open Fixture B",self.open_b),
            ("SHORT_B","Short Fixture B",self.short_b),
        ]

        return [
            (key,label)
            for key,label,var in definitions
            if var.get()
        ]

    def _build_page3(self):
        ttk.Label(self.page3, text="Measure or Load Calibration Standards", style="PageTitle.TLabel").pack(anchor="w", pady=(0,10))
        self.files_box = ttk.LabelFrame(self.page3, text="Calibration standard files", style="Section.TLabelframe", padding=12)
        self.files_box.pack(fill="x")
        self.standard_file_vars = {}
        self._refresh_page3_rows()
        calc = ttk.LabelFrame(self.page3, text="Calculated Fixture Characteristics", style="Section.TLabelframe", padding=12)
        calc.pack(fill="x", pady=12)
        self.result_frame = ttk.Frame(calc)
        self.result_frame.pack(fill="x")

        self.port_result_rows = {}
        self.row_delays = {}

        warning_box = ttk.LabelFrame(calc, text="Warnings", padding=6)
        warning_box.pack(fill="x", pady=(8, 0))
        self.warning_text = tk.Text(warning_box, height=4, state="disabled", wrap="word")
        self.warning_text.pack(fill="x")

        ttk.Label(calc, text="Length").pack(anchor="w")
        td=ttk.LabelFrame(self.page3,text="Time Domain Settings",style="Section.TLabelframe",padding=12); td.pack(fill="x")
        self.step_rise=tk.DoubleVar(value=17.9880)
        self.enable_interpolation = tk.BooleanVar(value=True)
        self.interpolation_method = tk.StringVar(value="Linear")
        self.enable_filter = tk.BooleanVar(value=False)
        self.filter_method = tk.StringVar(value="Phase Only")
        r=ttk.Frame(td); r.pack(anchor="w"); ttk.Label(r,text="Step Rise Time:").pack(side="left")
        ttk.Entry(r,textvariable=self.step_rise,width=10).pack(side="left",padx=5); ttk.Label(r,text="ps").pack(side="left")
        self.extraction_model = tk.StringVar(value="single_discontinuity")
        self.smooth_points = tk.IntVar(value=0)
        self.enforce_passivity = tk.BooleanVar(value=True)

        model_frame = ttk.LabelFrame(td, text="Extraction model", padding=8)
        model_frame.pack(fill="x", pady=(6, 4))
        ttk.Radiobutton(
            model_frame,
            text="Single discontinuity (exact, recommended)",
            value="single_discontinuity",
            variable=self.extraction_model,
        ).pack(anchor="w")
        ttk.Radiobutton(
            model_frame,
            text="First order (legacy, multiple reflections neglected)",
            value="first_order",
            variable=self.extraction_model,
        ).pack(anchor="w")

        row_opt = ttk.Frame(model_frame)
        row_opt.pack(anchor="w", pady=(6, 0))
        ttk.Label(row_opt, text="Smoothing (points, 0 = none):").pack(side="left")
        ttk.Spinbox(row_opt, from_=0, to=201, increment=2, width=6,
                    textvariable=self.smooth_points).pack(side="left", padx=5)
        ttk.Checkbutton(row_opt, text="Enforce passivity (|S21| <= 1)",
                        variable=self.enforce_passivity).pack(side="left", padx=15)

        self.eps_r_eff = tk.DoubleVar(value=1.0)
        self.eps_r_eff.trace_add("write", lambda *_: self.refresh_length_labels())
        r_eps = ttk.Frame(td); r_eps.pack(anchor="w", pady=(4, 0))
        ttk.Label(r_eps, text="Effective \u03b5r (line length = c \u00b7 TTD / \u221a\u03b5r):").pack(side="left")
        ttk.Entry(r_eps, textvariable=self.eps_r_eff, width=10).pack(side="left", padx=5)
        # ==================================================
        # Filtering
        # ==================================================

        filter_frame = ttk.LabelFrame(td,text="Signal Filtering",padding=10)
        filter_frame.pack(fill="x",pady=8)
        ttk.Checkbutton(filter_frame,text="Enable S-Parameter Filtering",variable=self.enable_filter).grid(row=0,column=0,sticky="w")
        ttk.Label(filter_frame,text="Filter Type:").grid(row=1,column=0,sticky="w")
        ttk.Combobox(filter_frame,textvariable=self.filter_method,state="readonly",width=25,
            values=[
                "None",
                "Savitzky-Golay",
                "Gaussian",
                "Median",
                "Moving Average",
                "Butterworth",
                "FIR Low Pass",
                "Wiener",
                "Wavelet",
                "Phase Only",
                "Vector Fitting"
            ]
        ).grid(row=1,column=1,padx=5)

        interp_frame = ttk.Frame(td)
        interp_frame.pack(anchor="w", pady=5)
        ttk.Label(interp_frame,text="Method:").pack(side="left", padx=(20,5))
        ttk.Combobox(interp_frame,textvariable=self.interpolation_method,values=["Linear","PCHIP","Cubic Spline","Akima"],state="readonly",width=16).pack(side="left")
        ttk.Checkbutton(td,text="Enable Frequency Interpolation",variable=self.enable_interpolation).pack(anchor="w", pady=5)
        ttk.Button(td,text="Calculate Fixture Characteristics",command=self.calculate_characteristics).pack(anchor="w",pady=8)
        plot_button_frame = ttk.Frame(td)
        plot_button_frame.pack(fill="x",pady=(5, 0))

        ttk.Button(
            plot_button_frame,
            text="Plot S-Parameters...",
            command=self.open_plot_window
        ).pack(side="left")

    # ======================================================================
    # Fenetre de trace (gui/plot_window.py)
    # ======================================================================

    def open_plot_window(self):
        """Ouvre (ou ramene au premier plan) la fenetre de trace."""

        if self.plot_window is not None:
            try:
                if self.plot_window.winfo_exists():
                    self.plot_window.refresh_sources()
                    self.plot_window.lift()
                    self.plot_window.focus_force()
                    return
            except tk.TclError:
                pass
            self.plot_window = None

        self.plot_window = PlotWindow(
            self,
            self.available_plot_networks,
            on_close=self._plot_window_closed,
            background=APP_BG,
        )

    def _plot_window_closed(self):
        self.plot_window = None

    def available_plot_networks(self):
        """
        Reseaux tracables : standards mesures (fichiers charges) puis
        fixtures extraits (demi-thru, OPEN / SHORT convertis, OPEN+SHORT).
        """

        items = []
        cache = getattr(self, "_measured_cache", None)
        if cache is None:
            cache = self._measured_cache = {}

        for key, path in self.standard_files.items():
            try:
                network = cache.get(path)
                if network is None:
                    network = cache[path] = afr_io.load_network(path)
                items.append((f"{key} (measured)", network))
            except Exception as error:
                log.warning("Fichier %s illisible : %s", path, error)

        for key, network in self.half_networks.items():
            if network is None:
                continue
            if key.endswith("_IN"):
                label = f"{key[:-3]} fixture A (half IN)"
            elif key.endswith("_OUT"):
                label = f"{key[:-4]} fixture B (half OUT)"
            elif key.endswith("_HALF"):
                base = key[:-5]
                label = f"{base} (fixture)" if not base.startswith("REFLECT_") else f"OPEN+SHORT {base[8:]} (fixture)"
            else:
                label = key
            items.append((label, network))

        return items

    def _refresh_page3_rows(self):
        if not hasattr(self, "files_box"): return
        for w in self.files_box.winfo_children(): w.destroy()
        rows=self._selected_standard_rows()
        if not rows: ttk.Label(self.files_box,text="No standard selected on page 2.").pack(anchor="w"); return
        for i,(key,label) in enumerate(rows):
            ttk.Label(self.files_box,text=label,width=20).grid(row=i,column=0,sticky="w",pady=4)
            var=self.standard_file_vars.setdefault(key,tk.StringVar())
            ttk.Entry(self.files_box,textvariable=var,width=75).grid(row=i,column=1,sticky="ew",padx=5)
            ttk.Button(self.files_box,text="Load...",command=lambda k=key:self.load_standard(k)).grid(row=i,column=2,padx=3)
            ttk.Button(self.files_box,text="Measure",command=lambda k=key:self.measure_standard(k)).grid(row=i,column=3,padx=3)
        self.files_box.columnconfigure(1,weight=1)

    def expected_port_count(self, key):
        if key.startswith("OPEN_"):
                return 1

        if key.startswith("SHORT_"):
            return 1

        if key.startswith("THRU_"):
            return 2

        if key == "ASYM_DUT":
            if self.is_multiport():
                return self.multiport_count.get()

            return 2

        return None

    def check_frequency_grid(self, frequency):
        frequency = np.asarray(
            frequency,
            dtype=float
        )

        if frequency.ndim != 1:
            raise ValueError(
                "The frequency grid must be one-dimensional."
            )

        if len(frequency) < 2:
            raise ValueError(
                "The Touchstone file must contain at least two points."
            )

        if not np.all(np.isfinite(frequency)):
            raise ValueError(
                "The frequency grid contains invalid values."
            )

        if np.any(np.diff(frequency) <= 0):
            raise ValueError(
                "Frequency values must be strictly increasing."
            )

    def check_finite_complex(self, values, name):
        values = np.asarray(values)

        if not np.all(np.isfinite(values.real)):
            raise ValueError(
                f"{name} contains invalid real values."
            )

        if not np.all(np.isfinite(values.imag)):
            raise ValueError(
                f"{name} contains invalid imaginary values."
            )

    def load_standard(self, key):
        filename = filedialog.askopenfilename(
            title=f"Load {key}",
            filetypes=[
                (
                    "Touchstone Files",
                    "*.s1p *.s2p *.s3p *.s4p"
                ),
                (
                    "All files",
                    "*.*"
                ),
            ]
        )

        if not filename:
            return

        try:
            network = rf.Network(filename)
        except Exception as error:
            messagebox.showerror(
                "Invalid Touchstone file",
                f"Unable to load the selected file:\n\n{error}"
            )
            return

        expected_ports = self.expected_port_count(key)

        if expected_ports is not None:
            if network.nports != expected_ports:
                messagebox.showerror(
                    "Invalid number of ports",
                    f"{key} requires a {expected_ports}-port file.\n"
                    f"The selected file contains {network.nports} port(s)."
                )
                return

        self.standard_files[key] = filename
        self.standard_file_vars[key].set(filename)

        self.status.set(
            f"{key} loaded: {Path(filename).name}"
        )

    def measure_standard(self,key):
        messagebox.showinfo("VNA measurement",f"Connect the VNA acquisition command for: {key}")

    def calculate_characteristics(self):
        log.info("Standards charges : %s", ", ".join(self.standard_files))

        try:
            self._store_page2()

            required_rows = self._selected_standard_rows()

            missing_files = [
                label
                for key, label in required_rows
                if key not in self.standard_files
            ]

            if missing_files:
                messagebox.showwarning(
                    "Missing calibration standards",
                    "Load the following files first:\n\n"
                    + "\n".join(missing_files)
                )
                return

            for key in self.standard_files:
                if key.startswith("THRU_"):
                    self.calculate_thru_fixture(key)

            self._measured_cache = {}
            self.clear_warnings()
            self.calculate_reflection_fixtures()
            self.update_fixture_result_labels()

            self.extraction_done = True

            self.status.set(
                "Fixture characteristics calculated successfully."
            )

            self.fixture_pairs.keys()
            self.half_networks.keys()

        except Exception as error:
            messagebox.showerror(
                "AFR calculation error",
                str(error)
            )

            raise

    def calculate_thru_fixture(self, key):
        if key not in self.standard_files:
            raise FileNotFoundError(
                f"{key} has not been loaded."
            )

        thru_file = self.standard_files[key]

        fixture_in, fixture_out, information = (
            self.build_half_thru(
                thru_file,
                key
            )
        )
        self.fixture_a_network = fixture_in
        self.fixture_b_network = fixture_out

        if not hasattr(self, "fixture_pairs"):
            self.fixture_pairs = {}
            self.plot_port_names = {}

        self.fixture_pairs[key] = {
            "in": fixture_in,
            "out": fixture_out
        }

        p1, p2 = self.plot_port_names.get(
            key,
            (1, 2)
        )

        self.half_networks[f"{key}_IN"] = fixture_in
        self.half_networks[f"{key}_OUT"] = fixture_out

        ports = self.plot_port_names.get(key)

        if ports is None:
            parts = key.split("_")

            if len(parts) == 3:
                p1 = int(parts[1])
                p2 = int(parts[2])

                ports = (p1, p2)

            else:
                ports = (1, 2)

        p1, p2 = ports

        self.create_port_result_row(p1)
        self.create_port_result_row(p2)

        self.set_result_row(p1, information["z1"], information["delay1"], key)
        self.set_result_row(p2, information["z2"], information["delay2"], key)
        self.extracted_info[key] = dict(information)

    def _build_page4(self):
        ttk.Label(self.page4,text="Select ports and channels to be corrected",style="PageTitle.TLabel").pack(anchor="w",pady=(0,10))
        ports=ttk.LabelFrame(self.page4,text="Ports",style="Section.TLabelframe",padding=12); ports.pack(fill="x")
        self.apply_a=tk.BooleanVar(value=True); self.apply_b=tk.BooleanVar(value=True)
        self.vna_a=tk.IntVar(value=1); self.vna_b=tk.IntVar(value=2)
        ttk.Checkbutton(ports,text="Apply Fixture A",variable=self.apply_a).grid(row=0,column=0,padx=5)
        ttk.Label(ports,text="VNA Port").grid(row=0,column=1); ttk.Spinbox(ports,from_=1,to=32,width=5,textvariable=self.vna_a).grid(row=0,column=2)
        ttk.Label(ports,text="Fixture A  |  DUT  |  Fixture B",foreground="#4f81bd",font=("Segoe UI",12,"bold")).grid(row=0,column=3,padx=45)
        ttk.Checkbutton(ports,text="Apply Fixture B",variable=self.apply_b).grid(row=0,column=4,padx=5)
        ttk.Label(ports,text="VNA Port").grid(row=0,column=5); ttk.Spinbox(ports,from_=1,to=32,width=5,textvariable=self.vna_b).grid(row=0,column=6)
        box=ttk.LabelFrame(self.page4,text="Channels",style="Section.TLabelframe",padding=12); box.pack(fill="both",expand=True,pady=12)
        self.channel_vars=[]
        for i,t in enumerate(["Standard","Noise Figure","Standard","Swept IMD","Gain Compression","Standard"],1):
            v=tk.BooleanVar(); self.channel_vars.append(v); ttk.Checkbutton(box,text=f"Channel {i}   {t}",variable=v).pack(anchor="w",pady=2)
        self.correction_method=tk.StringVar(value="enable_deembedding")
        ttk.Radiobutton(box,text="Turn on fixturing/de-embedding for channels",value="enable_deembedding",variable=self.correction_method).pack(anchor="w",pady=(12,2))
        ttk.Radiobutton(box,text="Modify the calset(s) used on channels",value="modify_calset",variable=self.correction_method).pack(anchor="w")
        self.extrapolate=tk.BooleanVar(); self.compensate_power=tk.BooleanVar()
        ttk.Checkbutton(box,text="Enable Extrapolation",variable=self.extrapolate).pack(anchor="w",pady=(10,0))
        ttk.Checkbutton(box,text="Compensate for power",variable=self.compensate_power).pack(anchor="w")
        a=ttk.Frame(self.page4); a.pack(fill="x")
        ttk.Button(a,text="Apply Correction",command=self.apply_correction).pack(side="left",fill="x",expand=True,padx=(0,5))
        ttk.Button(a,text="Undo Correction",command=lambda:self.status.set("Correction undone")).pack(side="left",fill="x",expand=True,padx=(5,0))

    def apply_correction(self):
        selected=[i+1 for i,v in enumerate(self.channel_vars) if v.get()]
        if not selected: messagebox.showwarning("No channel","Select at least one channel."); return
        messagebox.showinfo("Correction",f"Channels selected: {selected}\nConnect this command to the VNA/de-embedding backend.")

    def _build_page5(self):
        ttk.Label(self.page5,text="Save Fixture",style="PageTitle.TLabel").pack(anchor="w",pady=(0,10))
        f=ttk.LabelFrame(self.page5,text="File format",style="Section.TLabelframe",padding=12); f.pack(fill="x")
        self.save_format=tk.StringVar(value="touchstone")
        for text,val in [("Touchstone","touchstone"),("Touchstone 2","touchstone2"),("Citifile","citifile")]: ttk.Radiobutton(f,text=text,value=val,variable=self.save_format).pack(anchor="w")
        self.make4=tk.BooleanVar(); ttk.Checkbutton(f,text="Make 4 ports file from 2 ports data",variable=self.make4).pack(anchor="w")
        p=ttk.LabelFrame(self.page5,text="Port assignment",style="Section.TLabelframe",padding=12); p.pack(fill="x",pady=10)
        self.port_format=tk.StringVar(value="vna")
        for text,val in [("PLTS Format","plts"),("VNA Format","vna"),("ADS Format","ads")]: ttk.Radiobutton(p,text=text,value=val,variable=self.port_format).pack(anchor="w")
        o=ttk.LabelFrame(self.page5,text="Output",style="Section.TLabelframe",padding=12); o.pack(fill="x")
        self.base_name=tk.StringVar(value="HALF")
        ttk.Label(o,text="Directory:").grid(row=0,column=0,sticky="w"); ttk.Entry(o,textvariable=self.rf_output_dir).grid(row=0,column=1,sticky="ew",padx=5)
        ttk.Button(o,text="Browse...",command=self.choose_output).grid(row=0,column=2)
        ttk.Label(o,text="Base file name:").grid(row=1,column=0,sticky="w",pady=5); ttk.Entry(o,textvariable=self.base_name).grid(row=1,column=1,sticky="ew",padx=5)
        ttk.Button(o,text="Save Fixture Files",command=self.save_fixtures).grid(row=2,column=1,pady=10); o.columnconfigure(1,weight=1)

    def choose_output(self):
        d=filedialog.askdirectory()
        if d: self.rf_output_dir.set(d)

    def save_fixtures(self):
        output_directory = Path(
            self.rf_output_dir.get()
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        base_name = self.base_name.get().strip()

        if not base_name:
            messagebox.showwarning(
                "Missing name",
                "Enter a base file name."
            )
            return

        if self.fixture_a_network is None:
            messagebox.showwarning(
                "Fixture A unavailable",
                "Calculate Fixture A before saving."
            )
            return

        if self.fixture_b_network is None:
            messagebox.showwarning(
                "Fixture B unavailable",
                "Calculate Fixture B before saving."
            )
            return

        export_format = self.export_format.get().lower()

        if export_format not in {
            "db",
            "ma",
            "ri",
        }:
            export_format = "db"

        fixture_a_base = (
            output_directory
            / f"{base_name}_Fixture_A"
        )

        fixture_b_base = (
            output_directory
            / f"{base_name}_Fixture_B"
        )

        self.fixture_a_network.write_touchstone(
            str(fixture_a_base),
            form=export_format
        )

        self.fixture_b_network.write_touchstone(
            str(fixture_b_base),
            form=export_format
        )

        messagebox.showinfo(
            "Fixture files saved",
            f"Fixture A:\n{fixture_a_base}.s2p\n\n"
            f"Fixture B:\n{fixture_b_base}.s2p"
        )

    def _build_page6(self):
        ttk.Label(self.page6,text="Batch Process",style="PageTitle.TLabel").pack(anchor="w",pady=(0,10))
        ttk.Label(self.page6,text="Initial batch structure. The detailed Batch Process screenshot was not supplied.",wraplength=900).pack(anchor="w")
        b=ttk.LabelFrame(self.page6,text="Batch configuration",style="Section.TLabelframe",padding=12); b.pack(fill="x",pady=12)
        self.batch_in=tk.StringVar(); self.batch_out=tk.StringVar(); self.batch_pattern=tk.StringVar(value="*.s2p")
        for row,(label,var) in enumerate([("Input directory:",self.batch_in),("Output directory:",self.batch_out)]):
            ttk.Label(b,text=label).grid(row=row,column=0,sticky="w",pady=4); ttk.Entry(b,textvariable=var).grid(row=row,column=1,sticky="ew",padx=5)
            ttk.Button(b,text="Browse...",command=lambda v=var:self.choose_batch_dir(v)).grid(row=row,column=2)
        ttk.Label(b,text="Pattern:").grid(row=2,column=0,sticky="w"); ttk.Entry(b,textvariable=self.batch_pattern,width=20).grid(row=2,column=1,sticky="w",padx=5); b.columnconfigure(1,weight=1)
        ttk.Button(self.page6,text="Run Batch",command=self.run_batch).pack(anchor="w")
        self.batch_log=tk.Text(self.page6,height=18,state="disabled"); self.batch_log.pack(fill="both",expand=True,pady=10)

    def choose_batch_dir(self,var):
        d=filedialog.askdirectory()
        if d: var.set(d)

    def request_page(self, target_page):
        """Control navigation through the page tabs."""
        if target_page == self.current_page:
            return

        if target_page < 0 or target_page > 5:
            return

        # Moving backward does not require validation.
        if target_page < self.current_page:
            self.show_page(target_page)
            return

        # Before leaving Page 1, synchronize Page 2.
        if self.current_page == 0:
            try:
                if (
                    self.z0_mode.get() == "fixed"
                    and float(self.z0_value.get()) <= 0
                ):
                    messagebox.showwarning(
                        "Invalid Z0",
                        "Calibration Reference Z0 must be positive."
                    )
                    return
            except (tk.TclError, ValueError):
                messagebox.showwarning(
                    "Invalid Z0",
                    "Calibration Reference Z0 must be numeric."
                )
                return

            self.synchronize_page2_from_page1()

        # A direct jump from Page 1 to Page 3, 4, 5 or 6
        # must also validate Page 2.

        if target_page >= 2:
            self.synchronize_page2_from_page1()

            if not self.validate_page2():
                self.show_page(1)
                return

            self.show_page(target_page)
            return

        self.show_page(target_page)

    def show_page(self, page_index):
        if page_index < 0 or page_index > 5:
            return

        if page_index == 2:
            if not self.validate_page2():
                return

            self._refresh_page3_rows()

        self.pages[page_index].tkraise()
        self.current_page = page_index

        self.back_btn.configure(
            state="disabled" if page_index == 0 else "normal"
        )

        self.next_btn.configure(
            state="disabled" if page_index == 5 else "normal"
        )

        titles = [
            "1. Describe Fixture",
            "2. Specify Standards",
            "3. Measure Standards",
            "4. Remove Fixture",
            "5. Save Fixture",
            "6. Batch Process",
        ]

        self.status.set(titles[page_index])

        for index, button in enumerate(self.tab_buttons):
            if index == page_index:
                button.configure(style="TabActive.TButton")
            else:
                button.configure(style="TButton")

    def next_page(self):
        self.request_page(self.current_page + 1)

    def previous_page(self):
        self.request_page(self.current_page - 1)

    def show_configuration(self):
        self._store_page1()
        if self.current_page == 1:
            self._store_page2()
        lines = [f"{key}: {value}" for key, value in asdict(self.config_data).items()]
        messagebox.showinfo("Current AFR configuration", "\n".join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    AFRWizardComplete().mainloop()
