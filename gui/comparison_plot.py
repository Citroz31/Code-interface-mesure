"""
Graphe de comparaison avant / apres de-embedding, integre dans une page.

Affiche cote a cote la transmission et la reflexion de la mesure brute
(ligne A + DUT + ligne B) et du DUT seul obtenu apres retrait des fixtures.
La figure suit la largeur de son conteneur.
"""

from __future__ import annotations

import logging

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from tkinter import ttk

log = logging.getLogger("afr.gui.comparison")

RAW_STYLE = dict(color="#b0651a", linewidth=1.4, linestyle="--")
DEEMBEDDED_STYLE = dict(color="#1f6f8b", linewidth=1.6)


def _db(values):
    return 20.0 * np.log10(np.maximum(np.abs(values), 1e-15))


class ComparisonPlot(ttk.Frame):
    """
    Deux vues cote a cote : transmission a gauche, reflexion a droite.

    ``show`` trace la mesure brute et le resultat corrige ; ``clear`` remet
    le message d'attente.
    """

    def __init__(self, parent, height: int = 320, **kwargs):
        super().__init__(parent, height=height, **kwargs)

        # Hauteur imposee, largeur libre : la figure suit la page.
        self.pack_propagate(False)

        self.figure = Figure(figsize=(7.0, height / 100.0), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.clear()

    # ------------------------------------------------------------------

    def clear(self, message: str = None):
        """Etat d'attente, avant toute correction."""

        message = message or ("Load a raw measurement and press "
                              "'Remove Fixture and save'.\n"
                              "The DUT with and without the lines will appear here.")

        self.figure.clear()
        axis = self.figure.add_subplot(111)
        axis.text(0.5, 0.5, message, ha="center", va="center",
                  transform=axis.transAxes, color="0.35")
        axis.set_axis_off()
        self._draw()

    def show(self, raw, deembedded, raw_label="Measured: line A + DUT + line B",
             deembedded_label="De-embedded: DUT only"):
        """
        Trace les deux reseaux.

        ``raw``        : mesure brute, 2 ports.
        ``deembedded`` : DUT seul apres retrait des fixtures.
        """

        try:
            self.figure.clear()
            transmission = self.figure.add_subplot(1, 2, 1)
            reflection = self.figure.add_subplot(1, 2, 2)

            for network, label, style in (
                (raw, raw_label, RAW_STYLE),
                (deembedded, deembedded_label, DEEMBEDDED_STYLE),
            ):
                ghz = np.asarray(network.f, dtype=float) / 1e9
                transmission.plot(ghz, _db(network.s[:, 1, 0]), label=label, **style)
                reflection.plot(ghz, _db(network.s[:, 0, 0]), label=label, **style)

            transmission.set_title("Transmission |S21|", fontsize=10)
            transmission.set_ylabel("dB")
            reflection.set_title("Reflection |S11|", fontsize=10)
            reflection.set_ylabel("dB")

            for axis in (transmission, reflection):
                axis.set_xlabel("Frequency (GHz)")
                axis.grid(True, alpha=0.4)
                axis.legend(fontsize=7, loc="best")

            # Ecart moyen de transmission : ce que les lignes retiraient.
            try:
                gain = _db(deembedded.s[:, 1, 0]) - _db(raw.s[:, 1, 0])
                transmission.set_title(
                    f"Transmission |S21|  (+{np.mean(gain):.2f} dB recovered)",
                    fontsize=10,
                )
            except Exception:
                pass

            try:
                self.figure.tight_layout()
            except Exception:
                pass

            self._draw()

        except Exception as error:
            log.exception("Trace de comparaison impossible")
            self.clear(f"Cannot plot the comparison:\n{error}")

    # ------------------------------------------------------------------

    def _draw(self):
        try:
            self.canvas.draw_idle()
        except Exception:  # pragma: no cover - dependant du backend
            log.warning("Rafraichissement du graphe impossible")
