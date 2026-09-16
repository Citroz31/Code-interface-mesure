"""
Cadres qui s'adaptent a la taille de la fenetre.

``ScrollableFrame`` : conteneur dont le contenu reste accessible quelle que
soit la taille de la fenetre. Le contenu va dans ``.interior`` ; les barres
de defilement n'apparaissent que lorsqu'elles sont necessaires.

``ReflowBar`` : rangee de boutons qui passe a la ligne quand la largeur ne
suffit plus, au lieu de deborder hors de la fenetre.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    """
    Zone defilante verticale et horizontale.

    Le contenu est place dans ``self.interior``. Tant que la fenetre est
    assez grande, ``interior`` occupe toute la largeur disponible et rien ne
    defile. Des qu'elle retrecit sous la largeur minimale du contenu, la
    barre horizontale apparait ; de meme en hauteur.
    """

    def __init__(self, parent, background=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        canvas_options = dict(highlightthickness=0, borderwidth=0, takefocus=False)
        if background:
            canvas_options["background"] = background

        self.canvas = tk.Canvas(self, **canvas_options)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self._vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self._horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self._vertical.set,
                              xscrollcommand=self._horizontal.set)

        self.interior = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self._last_width = -1

        self.interior.bind("<Configure>", self._on_interior_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # La molette ne doit agir que sous le pointeur, pas globalement.
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    # ------------------------------------------------------------------

    def _on_interior_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_width()
        self._update_scrollbars()

    def _on_canvas_configure(self, _event=None):
        self._sync_width()
        self._update_scrollbars()

    def _sync_width(self):
        """
        Le contenu occupe au moins la largeur du canvas : les cadres internes
        s'etirent au lieu de laisser une bande vide. S'il lui en faut plus,
        il garde sa largeur propre et la barre horizontale prend le relais.
        """

        width = max(self.canvas.winfo_width(), self.interior.winfo_reqwidth())

        # Ne reconfigurer que sur un vrai changement : sinon Tk redeclenche
        # <Configure> sur le contenu et la boucle ne s'arrete plus.
        if width != self._last_width:
            self._last_width = width
            self.canvas.itemconfigure(self._window, width=width)

    def _update_scrollbars(self):
        """Affiche chaque barre uniquement si le contenu deborde."""

        needs_vertical = self.interior.winfo_reqheight() > self.canvas.winfo_height()
        needs_horizontal = self.interior.winfo_reqwidth() > self.canvas.winfo_width()

        if needs_vertical:
            self._vertical.grid(row=0, column=1, sticky="ns")
        else:
            self._vertical.grid_remove()
            self.canvas.yview_moveto(0.0)

        if needs_horizontal:
            self._horizontal.grid(row=1, column=0, sticky="ew")
        else:
            self._horizontal.grid_remove()
            self.canvas.xview_moveto(0.0)

    # ------------------------------------------------------------------

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)       # Windows, macOS
        self.canvas.bind_all("<Button-4>", self._on_wheel)         # X11
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        if self.interior.winfo_reqheight() <= self.canvas.winfo_height():
            return

        if getattr(event, "num", None) == 4:
            steps = -1
        elif getattr(event, "num", None) == 5:
            steps = 1
        else:
            steps = -1 if event.delta > 0 else 1

        self.canvas.yview_scroll(steps, "units")


class ReflowBar(ttk.Frame):
    """
    Rangee de widgets qui passe a la ligne quand la largeur manque.

    Utilisee pour les onglets : a pleine largeur ils tiennent sur une ligne,
    et quand la fenetre retrecit ils se repartissent sur deux lignes ou plus
    au lieu de sortir de l'ecran.
    """

    def __init__(self, parent, spacing: int = 4, **kwargs):
        super().__init__(parent, **kwargs)
        self.spacing = spacing
        self.items = []
        self._columns = 0
        self.bind("<Configure>", self._on_configure)

    def add(self, widget):
        self.items.append(widget)
        # Disposition initiale : ne pas attendre le premier <Configure>, qui
        # n'arrive qu'a l'affichage de la fenetre.
        self.after_idle(self._on_configure)
        return widget

    def _on_configure(self, event=None):
        if not self.items:
            return

        available = (event.width if event is not None else 0) or self.winfo_width()
        widest = max(item.winfo_reqwidth() for item in self.items) + 2 * self.spacing

        if available <= 1 or widest <= 1:
            # Widgets pas encore realises : reessayer au prochain tour.
            self.after_idle(self._on_configure)
            return

        columns = max(1, min(len(self.items), available // widest))

        if columns == self._columns:
            return
        self._columns = columns

        for index in range(max(columns, len(self.items))):
            self.columnconfigure(index, weight=0)

        for index, item in enumerate(self.items):
            item.grid(row=index // columns, column=index % columns,
                      padx=self.spacing, pady=2, sticky="ew")

        for index in range(columns):
            self.columnconfigure(index, weight=1)


def wrap_label(label, margin: int = 24):
    """
    Fait suivre la largeur d'un ``ttk.Label`` a celle de son conteneur : le
    texte se replie au lieu d'elargir la fenetre au-dela de l'ecran.
    """

    def _resize(event):
        width = max(event.width - margin, 120)
        label.configure(wraplength=width)

    label.master.bind("<Configure>", _resize, add="+")
    return label


class ResponsiveColumns(ttk.Frame):
    """
    Colonnes cote a cote qui s'empilent quand la largeur manque.

    Au-dessus de ``threshold`` pixels les colonnes sont sur une ligne et se
    partagent la largeur a parts egales. En dessous, elles passent l'une sous
    l'autre : rien n'est comprime ni coupe.
    """

    def __init__(self, parent, threshold: int = 760, gap: int = 16, **kwargs):
        super().__init__(parent, **kwargs)
        self.threshold = threshold
        self.gap = gap
        self.columns = []
        self._stacked = None
        self.bind("<Configure>", self._on_configure)

    def add_column(self) -> ttk.Frame:
        column = ttk.Frame(self)
        self.columns.append(column)
        self.after_idle(self._on_configure)
        return column

    def _on_configure(self, event=None):
        if not self.columns:
            return

        width = (event.width if event is not None else 0) or self.winfo_width()
        if width <= 1:
            self.after_idle(self._on_configure)
            return

        stacked = width < self.threshold
        if stacked == self._stacked:
            return
        self._stacked = stacked

        for index in range(len(self.columns)):
            self.columnconfigure(index, weight=0, minsize=0)
            self.rowconfigure(index, weight=0)

        for index, column in enumerate(self.columns):
            if stacked:
                column.grid(row=index, column=0, sticky="ew",
                            pady=(0 if index == 0 else self.gap, 0), padx=0)
            else:
                column.grid(row=0, column=index, sticky="new",
                            padx=(0 if index == 0 else self.gap, 0), pady=0)

        if stacked:
            self.columnconfigure(0, weight=1)
        else:
            for index in range(len(self.columns)):
                self.columnconfigure(index, weight=1, uniform="cols")
