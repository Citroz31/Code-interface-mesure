"""
Fenetre de trace des parametres S (Tkinter + matplotlib).

La fenetre ne connait pas l'application : elle recoit une fonction
``sources_provider`` qui retourne la liste des reseaux disponibles sous la
forme ``[(label, skrf.Network), ...]`` et la rappelle a chaque
rafraichissement. Les reseaux 1 port ne tracent que S11.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

log = logging.getLogger("afr.gui.plot")

PARAMETERS = ("S11", "S12", "S21", "S22")

FORMATS = (
    ("db_phase", "Amplitude (dB) + Phase (deg)"),
    ("db_delay", "Amplitude (dB) + Group delay (ps)"),
    ("mag_phase", "Magnitude + Phase (rad)"),
    ("real_imag", "Real + Imaginary"),
)


class PlotWindow(tk.Toplevel):
    """Fenetre independante : sources, parametres, format, figure."""

    def __init__(self, master, sources_provider, on_close=None, background=None):
        super().__init__(master)

        self.sources_provider = sources_provider
        self.on_close = on_close

        self.title("AFR S-Parameter Plot")
        self.geometry("1350x850")
        self.minsize(1000, 650)
        if background:
            self.configure(background=background)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.sources = {}          # label -> (BooleanVar, Network)
        self.param_vars = {
            name: tk.BooleanVar(value=name in ("S11", "S21")) for name in PARAMETERS
        }
        self.format_var = tk.StringVar(value="db_phase")

        self._build_controls()
        self._build_figure()

        self.refresh_sources()
        self.update_plot()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_controls(self):
        controls = ttk.Frame(self, padding=10)
        controls.pack(side="left", fill="y")

        # Sources (zone defilante : jusqu'a plusieurs dizaines d'entrees)
        source_box = ttk.LabelFrame(controls, text="Plot Sources", padding=6)
        source_box.pack(fill="both", expand=True, pady=(0, 10))

        canvas = tk.Canvas(source_box, width=300, height=320, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(source_box, orient="vertical", command=canvas.yview)
        self.source_frame = ttk.Frame(canvas)
        self.source_frame.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.source_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Button(controls, text="Refresh sources", command=self.refresh_sources).pack(
            fill="x", pady=(0, 10)
        )

        # Parametres S
        parameter_box = ttk.LabelFrame(controls, text="S-Parameters", padding=6)
        parameter_box.pack(fill="x", pady=(0, 10))
        for name in PARAMETERS:
            ttk.Checkbutton(parameter_box, text=name, variable=self.param_vars[name]).pack(
                anchor="w", pady=1
            )

        # Format
        format_box = ttk.LabelFrame(controls, text="Plot Format", padding=6)
        format_box.pack(fill="x", pady=(0, 10))
        for value, text in FORMATS:
            ttk.Radiobutton(format_box, text=text, value=value, variable=self.format_var).pack(
                anchor="w", pady=1
            )

        # Boutons
        ttk.Button(controls, text="Update Plot", command=self.update_plot).pack(fill="x", pady=(5, 3))
        ttk.Button(controls, text="Select all sources", command=lambda: self._set_sources(True)).pack(fill="x", pady=3)
        ttk.Button(controls, text="Clear sources", command=lambda: self._set_sources(False)).pack(fill="x", pady=3)
        ttk.Button(controls, text="Close", command=self.close).pack(fill="x", pady=(15, 3))

    def _build_figure(self):
        graph = ttk.Frame(self, padding=5)
        graph.pack(side="right", fill="both", expand=True)

        self.figure = Figure(figsize=(11, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=graph)

        toolbar = NavigationToolbar2Tk(self.canvas, graph, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")

        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def refresh_sources(self):
        """Relit la liste des reseaux et reconstruit les cases a cocher."""

        previous = {label: var.get() for label, (var, _net) in self.sources.items()}

        for child in self.source_frame.winfo_children():
            child.destroy()
        self.sources = {}

        try:
            items = list(self.sources_provider())
        except Exception as error:
            log.exception("Lecture des sources impossible")
            items = []
            ttk.Label(self.source_frame, text=f"Error: {error}", wraplength=280).pack(anchor="w")

        if not items:
            ttk.Label(
                self.source_frame,
                text="No network available yet.\nLoad and calculate the standards first.",
            ).pack(anchor="w")

        for label, network in items:
            var = tk.BooleanVar(value=previous.get(label, False))
            self.sources[label] = (var, network)
            text = f"{label}  [{network.nports}p, {len(network.f)} pts]"
            ttk.Checkbutton(self.source_frame, text=text, variable=var).pack(anchor="w")

    def _set_sources(self, state: bool):
        for var, _net in self.sources.values():
            var.set(state)
        self.update_plot()

    def selected_networks(self):
        return [(label, net) for label, (var, net) in self.sources.items() if var.get()]

    def selected_parameters(self):
        return [
            (name, int(name[1]) - 1, int(name[2]) - 1)
            for name in PARAMETERS
            if self.param_vars[name].get()
        ]

    # ------------------------------------------------------------------
    # Trace
    # ------------------------------------------------------------------

    def _message(self, text):
        self.figure.clear()
        axis = self.figure.add_subplot(111)
        axis.text(0.5, 0.5, text, ha="center", va="center", transform=axis.transAxes)
        axis.set_axis_off()
        self.canvas.draw_idle()

    @staticmethod
    def _curves(fmt, f_hz, s):
        magnitude = np.abs(s)
        db = 20.0 * np.log10(np.maximum(magnitude, 1e-15))
        phase = np.unwrap(np.angle(s))

        if fmt == "db_phase":
            return db, np.degrees(phase), "Amplitude (dB)", "Phase (deg)"
        if fmt == "db_delay":
            delay_ps = -np.gradient(phase, 2.0 * np.pi * f_hz) * 1e12
            return db, delay_ps, "Amplitude (dB)", "Group delay (ps)"
        if fmt == "mag_phase":
            return magnitude, phase, "Magnitude", "Phase (rad)"
        return np.real(s), np.imag(s), "Real", "Imaginary"

    def update_plot(self):
        networks = self.selected_networks()
        parameters = self.selected_parameters()

        if not networks:
            self._message("Select at least one source on the left.")
            return
        if not parameters:
            self._message("Select at least one S-parameter.")
            return

        fmt = self.format_var.get()
        self.figure.clear()

        columns = len(parameters)
        axes_top, axes_bottom = [], []
        for column in range(columns):
            top = self.figure.add_subplot(2, columns, column + 1)
            bottom = self.figure.add_subplot(2, columns, columns + column + 1, sharex=top)
            axes_top.append(top)
            axes_bottom.append(bottom)

        drawn = 0
        for label, network in networks:
            f_hz = np.asarray(network.f, dtype=float)
            f_ghz = f_hz / 1e9

            for column, (name, i, j) in enumerate(parameters):
                if i >= network.nports or j >= network.nports:
                    continue
                try:
                    s = network.s[:, i, j]
                    top_values, bottom_values, top_label, bottom_label = self._curves(fmt, f_hz, s)
                except Exception as error:
                    log.warning("Trace impossible pour %s %s : %s", label, name, error)
                    continue

                axes_top[column].plot(f_ghz, top_values, label=label, linewidth=1.2)
                axes_bottom[column].plot(f_ghz, bottom_values, label=label, linewidth=1.2)
                axes_top[column].set_title(name)
                axes_top[column].set_ylabel(top_label)
                axes_bottom[column].set_ylabel(bottom_label)
                axes_bottom[column].set_xlabel("Frequency (GHz)")
                drawn += 1

        if drawn == 0:
            self._message("Nothing to draw: the selected parameters do not exist\n"
                          "for the selected networks (1-port files only have S11).")
            return

        for axis in axes_top + axes_bottom:
            axis.grid(True, alpha=0.4)
            if axis.get_legend_handles_labels()[0]:
                axis.legend(fontsize=8)

        try:
            self.figure.tight_layout()
        except Exception:
            pass
        self.canvas.draw_idle()

    # ------------------------------------------------------------------

    def close(self):
        try:
            self.destroy()
        finally:
            if self.on_close is not None:
                self.on_close()
