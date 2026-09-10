import os
import shutil
import tkinter as tk

from pathlib import Path
from dataclasses import dataclass, asdict
from tkinter import ttk, messagebox, filedialog, simpledialog

import numpy as np
import skrf as rf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scipy.linalg import sqrtm, logm, expm
from scipy.signal import (savgol_filter,medfilt,butter,filtfilt,firwin, wiener)
from scipy.ndimage import gaussian_filter1d
import pywt
from skrf.vectorFitting import VectorFitting

from scipy.interpolate import (interp1d,PchipInterpolator,CubicSpline,Akima1DInterpolator)


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


        # self.rf_output_dir = str(Path.cwd() / "Results")
        # self.rf_output_dir = str(Path.cwd() / "Results")

        self.rf_output_dir = tk.StringVar(value=str(Path.cwd()/ "Results"))


        # Path(self.rf_output_dir).mkdir(
        #     parents=True,
        #     exist_ok=True
        # )

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

            print(
                f"Sauvegarde : {base_name}"
            )

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


    def frequency_to_time(self, x):
    
            full = np.concatenate(
                [
                    x,
                    np.conjugate(x[1:][::-1])
                ]
            )
    
            xt = np.fft.ifft(full)
    
            return xt
    def gate_response(self, x, peak, width):
    
            xt = self.frequency_to_time(x)
    
            gate = np.zeros(len(xt))
    
            start = max(
                0,
                peak - width
            )
    
            stop = min(
                len(xt),
                peak + width
            )
    
            gate[start:stop] = np.hanning(
                stop - start
            )
    
            xt_gate = xt * gate
    
            xf = np.fft.fft(
                xt_gate
            )
    
            return xf[:len(x)]
    
    def uniform_grid_with_dc(self, f, x):

        use_interp = True

        if hasattr(self, "enable_interpolation"):
            use_interp = self.enable_interpolation.get()

        if not use_interp:
            return f, x

        f = np.asarray(f, dtype=float)
        x = np.asarray(x, dtype=complex)

        df = np.median(np.diff(f))

        # Grille uniforme 0, df, 2df, ... jusqu'a f[-1] (sans depasser
        # d'un pas complet comme le faisait np.arange(0, f[-1] + df, df)).
        n_points = int(round(f[-1] / df))

        fu = np.arange(n_points + 1) * df

        xu = self.interpolate_complex_data(
            f,
            x,
            fu
        )

        # Pas d'extrapolation en dehors de la bande mesuree : on prolonge
        # par la valeur mesuree la plus proche. Evite les NaN d'Akima et
        # les divergences des splines sous f[0] et au dessus de f[-1].
        xu = np.where(fu < f[0], x[0], xu)
        xu = np.where(fu > f[-1], x[-1], xu)

        xu[0] = np.real(xu[0])

        return fu, xu
        
    def to_time_domain(self, fu, X):
    
            N = len(fu)
    
            w = np.kaiser(
                2*N-1,
                4.5
            )[N-1:]
    
            nfft = 8 * 2**int(
                np.ceil(
                    np.log2(
                        2*(N-1)
                    )
                )
            )
    
            h = np.fft.irfft(
                X*w,
                n=nfft
            )
    
            df = fu[1] - fu[0]
    
            dt = 1.0/(nfft*df)
    
            t = np.arange(nfft)*dt
    
            return t, h, w, nfft
    
    def raised_cosine_gate(
            self,
            t,
            t1,
            t2,
            edge
        ):
    
            g = np.zeros_like(t)
    
            g[(t>=t1)&(t<=t2)] = 1.0
    
            r = (t>=t1-edge)&(t<t1)
    
            g[r] = 0.5*(
                1
                -
                np.cos(
                    np.pi*
                    (t[r]-(t1-edge))
                    /edge
                )
            )
    
            r = (t>t2)&(t<=t2+edge)
    
            g[r] = 0.5*(
                1
                +
                np.cos(
                    np.pi*
                    (t[r]-t2)
                    /edge
                )
            )
    
            return g
    
    def gate_to_freq(
            self,
            h,
            gate,
            w,
            nfft,
            nf
        ):
    
            Y = np.fft.rfft(
                h*gate,
                n=nfft
            )[:nf]
    
            return Y / np.maximum(
                w,
                0.05
            )
    
    def complex_sqrt_half_phase(
            self,
            G,
            f=None
        ):
            """
            Racine carree complexe "continue" : module = sqrt(|G|),
            phase = phase deroulee de G divisee par 2.

            La racine carree a deux branches (+/- ). Si la grille de
            frequence f est fournie, la branche est choisie pour que la
            phase de G extrapolee a DC soit ~0 (modulo 2*pi), c'est a dire
            sqrt(G) reelle positive a basse frequence, ce qui est le cas
            d'un S21 de fixture passif. Sans cela, un point DC bruite ou de
            mauvais signe decale toute la phase de S21 de +/-90 degres.
            """

            mag = np.sqrt(
                np.abs(G)
            )

            phase = np.unwrap(
                np.angle(G)
            )

            if f is not None and len(f) >= 3:

                f = np.asarray(f, dtype=float)

                n_fit = max(
                    3,
                    int(0.05 * len(f))
                )

                slope, intercept = np.polyfit(
                    f[:n_fit],
                    phase[:n_fit],
                    1
                )

                phase = phase - 2.0*np.pi*np.round(
                    intercept / (2.0*np.pi)
                )

            return mag * np.exp(
                1j*phase/2.0
            )

    def reflect_coefficient(self, reflect_type=None, filename=None):
        """
        Coefficient de reflexion ideal du standard 1 port :
        +1 pour un OPEN, -1 pour un SHORT.

        reflect_type peut etre "OPEN", "SHORT" ou une cle du type
        "OPEN_A" / "SHORT_B". A defaut, le nom du fichier est analyse.
        """

        label = ""

        if reflect_type is not None:
            label = str(reflect_type).upper()

        if "SHORT" not in label and "OPEN" not in label and filename:
            label = Path(filename).name.upper()

        if "SHORT" in label:
            return -1.0

        if "OPEN" in label:
            return 1.0

        print(
            "Standard de reflexion inconnu -> OPEN suppose (Gamma_L = +1)"
        )

        return 1.0

    def build_afr_s2p_from_s1p(self, filename, reflect_type=None):
        """
        Construit le S2P d'un fixture a partir d'une mesure 1 port du
        fixture termine par un OPEN ou un SHORT (methode AFR).

        Modele (Gamma_L = +1 OPEN, -1 SHORT) :

            Gamma_mes(f) = S11 + S21^2 * Gamma_L / (1 - S22 * Gamma_L)

        Dans le domaine temporel :
          - la reflexion proche (t ~ 0) donne S11 ;
          - la reflexion lointaine (t ~ 2*tau) vaut, au premier ordre,
            (1 - S11^2) * Gamma_L * exp(-2j*beta*l) = S21^2 * Gamma_L / (1 - S11^2)
            (meme relation que pour le 2x-thru : s21_2x * (1 - s11_half^2)).

        D'ou :  S21 = sqrt( Gamma_far / Gamma_L * (1 - S11^2) )

        Corrections apportees par rapport a la version precedente :
          - prise en compte du signe du standard (SHORT = -1) : sinon la
            phase de S21 est fausse de 90 degres pour le SHORT ;
          - fenetre temporelle de S11 symetrique autour de t = 0 : la
            partie a temps negatif (repliee en fin de fenetre) etait perdue,
            S11 etait sous-estime et deforme ;
          - choix de la branche de la racine carree (phase -> 0 a DC) ;
          - terme (1 - S11^2) coherent avec build_half_thru ;
          - impedance caracteristique de type TDR calculee a partir de la
            reflexion proche (Re(Z11) du reseau ouvert n'a pas de sens) ;
          - Z0 du fichier d'origine conserve dans le reseau construit.
        """

        print("FILE =", filename)

        ntwk = rf.Network(filename)

        if ntwk.nports != 1:
            raise ValueError(
                f"{Path(filename).name} n'est pas un fichier S1P "
                f"(nombre de ports = {ntwk.nports})"
            )

        freq = ntwk.frequency.f

        try:
            z0_ref = float(
                np.real(
                    np.asarray(ntwk.z0).flat[0]
                )
            )
        except Exception:
            z0_ref = 50.0

        gamma_l = self.reflect_coefficient(
            reflect_type,
            filename
        )

        gamma_meas = ntwk.s[:,0,0]
        gamma_meas = self.apply_filter(gamma_meas, freq)

        use_interp = True

        if hasattr(self, "enable_interpolation"):
            use_interp = self.enable_interpolation.get()

        if use_interp:

            fu, Xo = self.uniform_grid_with_dc(
                freq,
                gamma_meas
            )

        else:

            # Le fenetrage temporel (irfft) exige une grille uniforme
            # partant de DC : interpolation lineaire minimale si
            # l'utilisateur a desactive l'interpolation.
            df = np.median(np.diff(freq))

            fu = np.arange(
                int(round(freq[-1] / df)) + 1
            ) * df

            Xo = (
                np.interp(fu, freq, np.real(gamma_meas))
                +
                1j*np.interp(fu, freq, np.imag(gamma_meas))
            )

            Xo[0] = np.real(Xo[0])

        print("================================")
        print("AFR FREQUENCY CHECK")
        print("================================")

        print("Standard =", "SHORT" if gamma_l < 0 else "OPEN",
              "(Gamma_L =", gamma_l, ")")

        print("Interpolation =", use_interp)

        print("Freq min =", freq[0]/1e9, "GHz")
        print("Freq max =", freq[-1]/1e9, "GHz")

        print("FU min =", fu[0]/1e9, "GHz")
        print("FU max =", fu[-1]/1e9, "GHz")

        t, ho, w, nfft = self.to_time_domain(
            fu,
            Xo
        )

        bw = fu[-1]

        tres = 1.0 / bw

        span = 1.0 / (
            fu[1]
            -
            fu[0]
        )

        # Axe temporel "centre" : les echantillons t > span/2 correspondent
        # aux temps negatifs (repliement circulaire de l'irfft).
        t_sym = np.where(
            t > span/2,
            t - span,
            t
        )

        # ------------------------------------------------------------
        # Recherche de la reflexion lointaine (bout du fixture)
        # ------------------------------------------------------------

        m = np.abs(ho).copy()

        m[t < 3*tres] = 0

        m[t > span/2] = 0

        peak_index = int(np.argmax(m))

        gate_center = t[peak_index]

        gate_half = min(
            max(
                7*tres,
                0.15*gate_center
            ),
            0.6*gate_center
        )

        edge = tres

        tau = gate_center / 2.0

        print(
            "AFR Delay (pic temporel) =",
            tau*1e12,
            "ps"
        )

        # ------------------------------------------------------------
        # Fenetres temporelles
        # ------------------------------------------------------------

        # Reflexion lointaine : S21^2 * Gamma_L
        g21 = self.raised_cosine_gate(
            t,
            gate_center-gate_half,
            gate_center+gate_half,
            edge
        )

        t_split = max(
            2*tres,
            0.5*(
                gate_center-gate_half
            )
        )

        # Reflexion proche : S11, fenetre symetrique autour de t = 0
        # (inclut la partie a temps negatif repliee en fin de vecteur).
        g11 = self.raised_cosine_gate(
            t_sym,
            -t_split,
            t_split,
            edge
        )

        nf = len(fu)

        Go = self.gate_to_freq(
            ho,
            g21,
            w,
            nfft,
            nf
        )

        S11u = self.gate_to_freq(
            ho,
            g11,
            w,
            nfft,
            nf
        )

        # ------------------------------------------------------------
        # S21 = sqrt( Gamma_far / Gamma_L * (1 - S11^2) )
        # ------------------------------------------------------------

        S21sq = (Go / gamma_l) * (1.0 - S11u*S11u)

        S21sq = np.where(
            np.abs(S21sq) < 1e-20,
            1e-20 + 0j,
            S21sq
        )

        S21u = self.complex_sqrt_half_phase(
            S21sq,
            fu
        )

        # Verification de la racine
        print(
            "Erreur max racine =",
            np.max(np.abs(S21u*S21u - S21sq))
        )

        # ------------------------------------------------------------
        # Retour sur la grille de frequence d'origine
        # ------------------------------------------------------------

        def samp(Y):

            return (
                np.interp(
                    freq,
                    fu,
                    np.real(Y)
                )
                +
                1j*np.interp(
                    freq,
                    fu,
                    np.imag(Y)
                )
            )

        s11 = samp(S11u)

        s21 = samp(S21u)

        # Fixture suppose reciproque et symetrique (une seule mesure
        # 1 port ne permet pas de separer S22 de S11).
        s22 = s11.copy()

        s12 = s21.copy()

        s = np.zeros(
            (
                len(freq),
                2,
                2
            ),
            dtype=complex
        )

        s[:,0,0] = s11
        s[:,1,1] = s22
        s[:,1,0] = s21
        s[:,0,1] = s12

        net = rf.Network(
            frequency=ntwk.frequency,
            s=s,
            z0=z0_ref
        )

        k_print = min(100, len(freq) - 1)

        print(
            f"S21 @{k_print} =",
            s[k_print,1,0]
        )

        # ------------------------------------------------------------
        # Impedance caracteristique (type TDR) a partir de la reflexion
        # proche : Z = Z0 (1 + S11) / (1 - S11)
        # ------------------------------------------------------------

        z_near = self.s11_to_z(
            s11,
            z0_ref
        )

        z_mean = float(
            np.mean(
                np.real(z_near)
            )
        )

        # ------------------------------------------------------------
        # Delai de propagation : pente de la phase de S21
        # (coherent avec build_half_thru), en ps
        # ------------------------------------------------------------

        phase_s21 = np.unwrap(
            np.angle(S21u)
        )

        slope = np.polyfit(
            fu,
            phase_s21,
            1
        )[0]

        delay = -slope / (2.0*np.pi) * 1e12

        if not np.isfinite(delay) or delay <= 0:
            delay = tau * 1e12

        print("AFR Impedance =", z_mean, "Ohm")
        print("AFR Delay =", delay, "ps")

        return net, z_mean, delay


    def detect_touchstone_format(self, filename):
        with open(
            filename,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as touchstone_file:

            for line in touchstone_file:
                line = line.strip().upper()

                if not line.startswith("#"):
                    continue

                if " RI " in f" {line} ":
                    return "RI"

                if " MA " in f" {line} ":
                    return "MA"

                if " DB " in f" {line} ":
                    return "DB"

        return "UNKNOWN"

    def apply_filter(self, signal, frequency=None):

        if not self.enable_filter.get():
            return signal

        method = self.filter_method.get()

        # =====================================
        # NONE
        # =====================================

        if method == "None":
            return signal

        # =====================================
        # Savitzky-Golay
        # =====================================

        elif method == "Savitzky-Golay":

            real = savgol_filter(
                np.real(signal),
                self.filter_window.get(),
                self.filter_order.get()
            )

            imag = savgol_filter(
                np.imag(signal),
                self.filter_window.get(),
                self.filter_order.get()
            )

            return real + 1j*imag

        # =====================================
        # Gaussian
        # =====================================

        elif method == "Gaussian":

            real = gaussian_filter1d(
                np.real(signal),
                self.filter_sigma.get()
            )

            imag = gaussian_filter1d(
                np.imag(signal),
                self.filter_sigma.get()
            )

            return real + 1j*imag

        # =====================================
        # Median
        # =====================================

        elif method == "Median":

            real = medfilt(
                np.real(signal),
                self.filter_window.get()
            )

            imag = medfilt(
                np.imag(signal),
                self.filter_window.get()
            )

            return real + 1j*imag

        # =====================================
        # Moving Average
        # =====================================

        elif method == "Moving Average":

            w = self.filter_window.get()

            kernel = np.ones(w) / w

            real = np.convolve(
                np.real(signal),
                kernel,
                mode="same"
            )

            imag = np.convolve(
                np.imag(signal),
                kernel,
                mode="same"
            )

            return real + 1j*imag

        # =====================================
        # Butterworth
        # =====================================

        elif method == "Butterworth":

            b, a = butter(
                4,
                self.filter_cutoff.get()
            )

            real = filtfilt(
                b,
                a,
                np.real(signal)
            )

            imag = filtfilt(
                b,
                a,
                np.imag(signal)
            )

            return real + 1j*imag

        # =====================================
        # FIR Low Pass
        # =====================================

        elif method == "FIR Low Pass":

            b = firwin(
                31,
                self.filter_cutoff.get()
            )

            real = filtfilt(
                b,
                [1.0],
                np.real(signal)
            )

            imag = filtfilt(
                b,
                [1.0],
                np.imag(signal)
            )

            return real + 1j*imag

        # =====================================
        # Wiener
        # =====================================

        elif method == "Wiener":

            real = wiener(
                np.real(signal),
                self.filter_window.get()
            )

            imag = wiener(
                np.imag(signal),
                self.filter_window.get()
            )

            return real + 1j*imag

        # =====================================
        # Wavelet
        # =====================================

        elif method == "Wavelet":

            coeffs_r = pywt.wavedec(
                np.real(signal),
                "db4"
            )

            coeffs_i = pywt.wavedec(
                np.imag(signal),
                "db4"
            )

            coeffs_r[1:] = [
                np.zeros_like(c)
                for c in coeffs_r[1:]
            ]

            coeffs_i[1:] = [
                np.zeros_like(c)
                for c in coeffs_i[1:]
            ]

            real = pywt.waverec(
                coeffs_r,
                "db4"
            )

            imag = pywt.waverec(
                coeffs_i,
                "db4"
            )

            return (
                real[:len(signal)]
                +
                1j*imag[:len(signal)]
            )

        # =====================================
        # Phase Only
        # =====================================

        elif method == "Phase Only":

            mag = np.abs(signal)

            phase = np.unwrap(
                np.angle(signal)
            )

            phase = savgol_filter(
                phase,
                self.filter_window.get(),
                self.filter_order.get()
            )

            return mag * np.exp(
                1j*phase
            )

        # =====================================
        # Vector Fitting
        # =====================================

        elif method == "Vector Fitting":

            try:

                if frequency is None:
                    return signal

                freq_obj = rf.Frequency.from_f(
                    frequency,
                    unit="hz"
                )

                s = np.zeros(
                    (
                        len(signal),
                        1,
                        1
                    ),
                    dtype=complex
                )

                s[:,0,0] = signal

                net = rf.Network(
                    frequency=freq_obj,
                    s=s
                )

                vf = VectorFitting(net)

                vf.vector_fit()

                net_fit = vf.get_model_response(
                    0,
                    0
                )

                return net_fit

            except Exception as e:

                print(
                    "Vector fitting failed:",
                    e
                )

                return signal

        return signal

    # ======================================
    # Half Thru
    # ======================================
    def build_half_thru(self, thru_file,source_key="THRU_LINE1"):

        thru = rf.Network(thru_file)

        print("THRU START =", thru.frequency.f[0]/1e9)
        print("THRU STOP  =", thru.frequency.f[-1]/1e9)

        DEBUG_PLOT = False

 

        fmt = self.detect_touchstone_format(
            thru_file
        )

        print(
            f"Format détecté : {fmt}"
        )

       

        print("================================")
        # print("ENTER build_half_thru")
        print("FILE =", thru_file)
        print("================================")


        print("================================")
        print("FREQUENCY RANGE")
        print("================================")
        print("Start =", thru.frequency.f[0]/1e9, "GHz")
        print("Stop  =", thru.frequency.f[-1]/1e9, "GHz")
        print("Points =", len(thru.frequency.f))

        freq = thru.frequency
        freq_hz = freq.f

        s11 = thru.s[:,0,0]
        s21 = thru.s[:,1,0]
        s12 = thru.s[:,0,1]
        s22 = thru.s[:,1,1]

        s11 = self.apply_filter(s11,freq_hz)
        s21 = self.apply_filter(s21,freq_hz)
        s12 = self.apply_filter(s12,freq_hz)
        s22 = self.apply_filter(s22,freq_hz)
        # if self.enable_interpolation.get():

        #     freq_uniform, s21 = self.uniform_grid_with_dc(freq_hz,s21)
        #     _, s11 = self.uniform_grid_with_dc(freq_hz,s11)
        #     _, s12 = self.uniform_grid_with_dc(freq_hz,s12)
        #     _, s22 = self.uniform_grid_with_dc(freq_hz,s22)
        # freq_hz = freq_uniform
        freq_hz = freq.f
        self.validate_network(
            thru.s
        )


        if thru.nports != 2:
            print(
                f"Erreur : fichier {thru_file} n'est pas un S2P "
                f"(nombre de ports = {thru.nports})"
            )
            return


        print("Nombre de ports :", thru.nports)
        print("Shape S :", thru.s.shape)
        print("Shape A :", thru.a.shape)
        

        sym_error = np.max(
            np.abs(
                thru.s[:,0,0]
                -
                thru.s[:,1,1]
            )
        )




        # ======================================
        # Analyse temporelle S21
        # ======================================

        s21_window = s21 * np.hanning(len(s21))

        h = np.fft.ifft(s21_window)
        if self.DEBUG_PLOT:

            plt.figure()
            plt.plot(np.abs(h))
            plt.title("Impulse Response S21")
            plt.xlabel("Time Index")
            plt.ylabel("Amplitude")
            plt.grid(True)
            # plt.show()
        
            plt.show()

        peak = np.argmax(np.abs(h))

        print("Peak =", peak)
        print("Nb points =", len(h))

        phase = np.unwrap(np.angle(s21))

        # freq_hz = freq.f

        tau = -np.gradient(
            phase,
            2*np.pi*freq_hz
        )

        tau_mean = np.mean(tau)

        if self.DEBUG_PLOT:
    
            plt.figure()

            plt.plot(freq_hz/1e9, tau*1e12)

            plt.title("Group Delay")

            plt.xlabel("GHz")

            plt.ylabel("ps")

            plt.grid(True)

    
            plt.show()



        print("Delay total =", tau_mean * 1e12, "ps")

        tau_half = tau_mean / 2

        print("Half delay =", tau_half * 1e12, "ps")


        print("AFR-LIKE EXTRACTION")

    
        print("AFR-LIKE EXTRACTION")

        # ==========================
        # HALF S11
        # ==========================

        s11 = thru.s[:,0,0]

        xt11 = self.frequency_to_time(
            s11
        )

        peak11 = np.argmax(
            np.abs(xt11)
        )

        print("Peak S11 =", peak11)

        s11_half = self.gate_response(
            s11,
            peak11,
            15
        )

        # ==========================
        # HALF S22
        # ==========================

        s22 = thru.s[:,1,1]

        xt22 = self.frequency_to_time(
            s22
        )

        peak22 = np.argmax(
            np.abs(xt22)
        )

        print("Peak S22 =", peak22)

        s22_half = self.gate_response(
            s22,
            peak22,
            15
        
        )

        s21_2x = thru.s[:,1,0]



        rad = s21_2x * (
            1.0
            -
            s11_half*s11_half
        )
        rad = np.where(
            np.abs(rad) < 1e-20,
            1e-20 + 0j,
            rad
        )

        # s21_half = np.sqrt(rad)

        mag = np.sqrt(
            np.abs(rad)
        )

        phase_half = 0.5 * np.unwrap(
            np.angle(rad)
        )

        s21_half = (
            mag
            *
            np.exp(
                1j * phase_half
            )
        )


        check = s21_half * s21_half

    

        if self.DEBUG_PLOT:
            plt.figure()
            
            plt.plot(
                freq_hz/1e9,
                20*np.log10(np.abs(rad)),
                label="Original"
            )

            plt.plot(
                freq_hz/1e9,
                20*np.log10(np.abs(check)),
                '--',
                label="Half × Half"
            )

            plt.legend()
            plt.grid(True)

           
            plt.show()


        print(
            "Erreur max racine =",
            np.max(np.abs(check - rad))
        )



        if self.DEBUG_PLOT:
            plt.figure()
   

            plt.plot(
                freq_hz/1e9,
                np.angle(s21_half, deg=True),
                label="Phase HALF brute"
            )

            plt.grid(True)
            plt.legend()
            # plt.show()

        
            plt.show()
        if self.DEBUG_PLOT:
            plt.figure()

            plt.plot(
            freq_hz/1e9,
            np.unwrap(
                np.angle(s21_half)
            ) * 180/np.pi,
            label="Phase HALF unwrap"
        )

            plt.grid(True)
            plt.legend()
            plt.show()
       


        if self.DEBUG_PLOT:
            plt.figure()

            plt.plot(
                freq_hz/1e9,
                np.unwrap(np.angle(rad))*180/np.pi,
                label="rad"
            )

            plt.plot(
            freq_hz/1e9,
            np.unwrap(np.angle(s21_half))*180/np.pi,
            label="sqrt(rad)"
        )

            plt.legend()
            plt.grid(True)
            plt.show()



        half_s = np.zeros_like(
            thru.s
        )

        # half_s[:,0,0] = s11_half


        if self.DEBUG_PLOT:
            plt.figure()

            plt.plot(
                freq_hz/1e9,
                20*np.log10(
                    np.maximum(
                        np.abs(s11),
                        1e-15
                    )
                ),
                label="THRU S11"
            )

            plt.plot(
                freq_hz/1e9,
                20*np.log10(
                    np.maximum(
                        np.abs(s11_half),
                        1e-15
                    )
                ),
                label="HALF S11"
            )

            plt.legend()
            plt.grid(True)
            plt.title("S11 THRU vs HALF")
            plt.show()

        # half_s[:,1,1] = s11_half

        half_s[:,0,0] = s11_half
        half_s[:,1,1] = s22_half


        half_s[:,1,0] = s21_half
        half_s[:,0,1] = s21_half

        print("CHECK HALF REFLECTIONS")

        print(
            "Max |S11_half-S22_half| =",
            np.max(
                np.abs(
                    s11_half - s22_half
                )
            )
        )

        half_network = thru.copy()

        half_network.s = half_s


        cont = self.continuity_metric(
            half_network.s
        )

        print(
            "CONTINUITY =",
            cont
        )

        half_abcd = half_network.a

        max_error = 0

        for k in range(len(freq)):

            reconstructed = (
                half_abcd[k]
                @
                half_abcd[k]
            )

            err = np.max(
                np.abs(
                    reconstructed
                    -
                    thru.a[k]
                )
            )

            max_error = max(
                max_error,
                err
            )

        print(
            "MAX HALF×HALF ERROR =",
            max_error
        )
                



       
        # =================================
        # Reconstruction THRU
        # =================================

        thru_rebuilt = thru.copy()

        rebuilt_abcd = np.zeros_like(thru.a)

        for k in range(len(freq)):

            rebuilt_abcd[k] = (
                half_abcd[k]
                @
                half_abcd[k]
            )

        thru_rebuilt.a = rebuilt_abcd

        print("================================")
        print("THRU RECONSTRUCTION TEST")
        print("================================")

        print(
            "Max Reconstruction Error =",
            np.max(
                np.abs(
                    thru_rebuilt.s
                    -
                    thru.s
                )
            )
        )


        if self.DEBUG_PLOT:
            plt.figure()

            plt.plot(
                freq.f/1e9,
                20*np.log10(
                    np.abs(
                        thru.s[:,1,0]
                    )
                ),
                label="Original THRU"
            )

            plt.plot(
                freq.f/1e9,
                20*np.log10(
                    np.abs(
                        thru_rebuilt.s[:,1,0]
                    )
                ),
                '--',
                label="HALF x HALF"
            )

            plt.legend()
            plt.grid(True)
            plt.title("THRU Reconstruction Check")
            plt.xlabel("Frequency (GHz)")
            plt.ylabel("S21 (dB)")
            plt.show()



        print("================================")
        print("VERIFICATION HALF THRU")
        print("================================")

        print("ABCD THRU")
        print(thru.a[0])

        print("ABCD HALF")
        print(half_abcd[0])

        print("DIFFERENCE MAX")
        print(np.max(np.abs(thru.a[0] - half_abcd[0])))

        test = half_abcd[0] @ half_abcd[0]

        print("ERREUR RECONSTRUCTION")
        print(np.max(np.abs(test - thru.a[0])))

    
        # half_network = half_network.copy()

        # half_network.a = half_abcd

        # half_network = thru.copy()

        # half_network.a = half_abcd
        zin = half_network.z[:,0,0]
        zout = half_network.z[:,1,1]

        z1 = np.mean(np.real(zin))
        z2 = np.mean(np.real(zout))

        phase = np.unwrap(
            np.angle(
                half_network.s[:,1,0]
            )
        )

        print("================================")
        print("GRADIENT CHECK")
        print("================================")
        print("len(phase)   =", len(phase))
        print("len(freq_hz) =", len(freq_hz))


        
        freq_delay = thru.frequency.f

        delay = (
            np.mean(
                -np.gradient(
                    phase,
                    2*np.pi*freq_delay
                )
            ) * 1e12
        ) 

        information = {
            "z1": z1,
            "z2": z2,
            "delay1": delay,
            "delay2": delay
        }

        check = np.zeros_like(thru.a)

        for k in range(len(freq)):

            check[k] = (
                half_network.a[k]
                @
                np.linalg.inv(
                    half_network.a[k]
                )
            )

        net_check = thru.copy()
        net_check.a = check

        if self.DEBUG_PLOT:                  

            plt.figure()

            plt.plot(
                freq.f/1e9,
                20*np.log10(
                    np.abs(net_check.s[:,1,0])
                )
            )

            plt.grid(True)
            plt.title("HALF x INV(HALF)")
            plt.show()

       

        print("THRU ABCD ")
        print(thru.a[0])

        print("HALF ABCD ")
        print(half_network.a[0])

        print("S THRU")
        print(thru.s[0])

        print("S HALF")
        print(half_network.s[0])

        max_error = 0

        for k in range(len(freq)):

            reconstructed = (
                half_abcd[k]
                @
                half_abcd[k]
            )

            error = np.max(
                np.abs(
                    reconstructed
                    -
                    thru.a[k]
                )
            )

            max_error = max(max_error, error)

            print(
                f"Erreur reconstruction {k} = {error:.3e}"
            )

        print("================================")
        print("MAX RECONSTRUCTION ERROR =", max_error)
        print("================================")

                    
        # Vérification de passivité

        for k in range(len(freq)):

            eig = np.linalg.eigvals(
                half_network.s[k].conj().T
                @
                half_network.s[k]
            )

            if np.max(np.real(eig)) > 1.05:

                print(
                    f"Attention : réseau potentiellement non passif "
                    f"à la fréquence {freq.f[k]/1e9:.3f} GHz"
                )


        print("THRU original")
        print(thru.s[0])

        print("HALF THRU")
        print(half_network.s[0])
        # name = Path(thru_file).stem(
        #     thru_file
        # ).split(".")[0]
        name = Path(thru_file).stem



        print("ABCD THRU")
        print(thru.a[0])

        print("ABCD HALF")
        print(half_abcd[0])

        print("Différence")
        print(np.max(np.abs(thru.a[0] - half_abcd[0])))

        print("S THRU AVANT EXPORT")
        print(thru.s[0])

        print("S HALF AVANT EXPORT")
        print(half_network.s[0])



        half_transpose = half_network.copy()

        S = half_network.s.copy()

        Sswap = np.zeros_like(S)

        Sswap[:,0,0] = S[:,1,1]
        Sswap[:,1,1] = S[:,0,0]
        Sswap[:,0,1] = S[:,1,0]
        Sswap[:,1,0] = S[:,0,1]

        half_transpose.s = Sswap

 


        # half_transpose = half_network.copy()

        # abcd_out = np.zeros_like(
        #     half_network.a
        # )

        # for k in range(len(freq)):

        #     A = half_network.a[k]

        #     abcd_out[k] = np.array([
        #         [A[1,1], A[0,1]],
        #         [A[1,0], A[0,0]]
        #     ])

        # half_transpose.a = abcd_out

        print("================================")
        print("HALF OUT = PORT SWAP")
        print("================================")

        print("ABCD HALF IN")
        print(half_network.a[0])

        print("ABCD HALF OUT")
        print(half_transpose.a[0])

    
        print("HALF IN S")
        print(half_network.s[0])

        print("HALF OUT S")
        print(half_transpose.s[0])


        half_file_in = os.path.join(
            self.rf_output_dir.get(),
            f"{source_key}_HALF_IN"
        )

        half_file_out = os.path.join(
            self.rf_output_dir.get(),
            f"{source_key}_HALF_OUT"
        )

        print("ARRIVE A LA SAUVEGARDE HALF IN")
        print(half_file_in)

        print("ARRIVE A LA SAUVEGARDE HALF OUT")
        print(half_file_out)


        # sauvegarde côté entrée
        half_network.write_touchstone(
            half_file_in,
            form=self.export_format.get()
        )

        # sauvegarde côté sortie
        half_transpose.write_touchstone(
            half_file_out,
            form=self.export_format.get()
        )

        # self.files["HALF_THRU_IN"] = half_file_in + ".s2p"
        # self.files["HALF_THRU_OUT"] = half_file_out + ".s2p"

        self.converted_files[f"{source_key}_IN"] = half_file_in + ".s2p"

        self.converted_files[f"{source_key}_OUT"] = half_file_out + ".s2p"



        self.half_thru_file_in = half_file_in + ".s2p"
        self.half_thru_file_out = half_file_out + ".s2p"

        self.converted_files[
            f"{source_key}_IN"
        ] = half_file_in + ".s2p"

        self.converted_files[
            f"{source_key}_OUT"
        ] = half_file_out + ".s2p"




        print("HALF INPUT  :", self.half_thru_file_in)
        print("HALF OUTPUT :", self.half_thru_file_out)


        # print(
        #     f"HALF_{name}.s2p sauvegardé dans {self.rf_output_dir.get}"
        # )
        print(
            f"HALF_{name}.s2p sauvegardé dans "
            f"{self.rf_output_dir.get()}"
        )

        print("HALF THRU exporté")
        # print("THRU_LINE1 remplacé par :")
        # print(self.files["THRU_LINE1"])
        print("THRU source :", source_key)
        print("Fichier chargé :", self.standard_files[source_key])

        




        return (
            half_network,
            half_transpose,
            information
        )


        

    def continuity_metric(self, S):
    
            if len(S) < 2:
                return 0
    
            d = np.linalg.norm(
                np.diff(
                    S,
                    axis=0
                ).reshape(
                    len(S)-1,
                    -1
                ),
                axis=1
            )
    
            n = np.maximum(
                np.linalg.norm(
                    S[:-1].reshape(
                        len(S)-1,
                        -1
                    ),
                    axis=1
                ),
                1e-15
            )
    
            return np.max(d/n)
    
    def max_singular_value(self,S):
    
            m = 0.0
    
            for sample in S:
    
                m = max(
                    m,
                    float(
                        np.max(
                            np.linalg.svd(
                                sample,
                                compute_uv=False
                            )
                        )
                    )
                )
    
            return m
    def validate_network(self, S):
    
            sym = np.max(
                np.abs(
                    S[:,0,0]
                    -
                    S[:,1,1]
                )
            )
    
            rec = np.max(
                np.abs(
                    S[:,0,1]
                    -
                    S[:,1,0]
                )
            )
    
            sigma = self.max_singular_value(S)
    
            print("Symmetry Error =", sym)
            print("Reciprocity Error =", rec)
            print("Max Singular Value =", sigma)
    
            if sigma > 1.0:
    
                print(
                    "WARNING : réseau potentiellement non passif"
                )
    def extract_ttd(self, s21, freq):

        s21_window = s21 * np.hanning(len(s21))

        h = np.fft.ifft(s21_window)

        peak = np.argmax(np.abs(h))

        df = freq[1] - freq[0]

        dt = 1/(len(freq)*df)

        delay = peak*dt

        return delay

    def extract_average_z(self, net):

        zin = net.z[:,0,0]

        return np.mean(
                np.real(zin)
            )    

 # ======================================
# Final Deembedding
# ======================================

    def remove_fixture( self, dut_file, fixture_in, fixture_out):

        dut = rf.Network(dut_file)

        result_abcd = np.zeros_like(dut.a)

        for k in range(len(dut.frequency)):

            cond_in = np.linalg.cond(
                fixture_in.a[k]
            )

            cond_out = np.linalg.cond(
                fixture_out.a[k]

            )

            cond = max(cond_in, cond_out)
            

            if cond > 50:
                print(
                    f"Conditionnement = {cond:.2e} "
                    f"à {dut.frequency.f[k]/1e9:.3f} GHz"
                )

            cond_in = np.linalg.cond(
                fixture_in.a[k]
            )

            cond_out = np.linalg.cond(
                fixture_out.a[k]
)

            print(
                f"{dut.frequency.f[k]/1e9:.3f} GHz  ->  Cond = {cond:.2e}"
            )

            cond_in = np.linalg.cond(
                fixture_in.a[k]
            )

            cond_out = np.linalg.cond(
                fixture_out.a[k]
            )

            if cond_in > 100:

                print(
                    f"WARNING Fixture IN "
                    f"{dut.frequency.f[k]/1e9:.3f} GHz "
                    f"Cond={cond_in:.2e}"
                )

            if cond_out > 100:

                print(
                    f"WARNING Fixture OUT "
                    f"{dut.frequency.f[k]/1e9:.3f} GHz "
                    f"Cond={cond_out:.2e}"
                )


            fixture_in_inv = np.linalg.inv(
                fixture_in.a[k]
            )

            fixture_out_inv = np.linalg.inv(
                fixture_out.a[k]
            )
            if np.linalg.cond(fixture_in.a[k]) > 1e8:
                fixture_in_inv = np.linalg.pinv(
                    fixture_in.a[k]
                )
            else:
                fixture_in_inv = np.linalg.inv(
                    fixture_in.a[k]
                )

            if np.linalg.cond(fixture_out.a[k]) > 1e8:
                fixture_out_inv = np.linalg.pinv(
                    fixture_out.a[k]
                )
            else:
                fixture_out_inv = np.linalg.inv(
                    fixture_out.a[k]
                )

            result_abcd[k] = (
                fixture_in_inv
                @ dut.a[k]
                @ fixture_out_inv
            )

            # fixture_in_inv = np.linalg.inv(
            #     fixture_in.a[k]
            # )

            # fixture_out_inv = np.linalg.inv(
            #     fixture_out.a[k]
            # )

            result_abcd[k] = (
                fixture_in_inv
                @ dut.a[k]
                @ fixture_out_inv
            )


            if k == 100:

                dut_reconstructed = (
                fixture_in.a[k]
                @ result_abcd[k]
                @ fixture_out.a[k]
)

                err = np.max(
                    np.abs(
                        dut_reconstructed
                        -
                        dut.a[k]
                    )
                )

                print("RECONSTRUCTION ERROR =", err)

        result = dut.copy()

        result.a = result_abcd

        if self.DEBUG_PLOT:

            plt.figure()

            plt.plot(
                dut.frequency.f/1e9,
                20*np.log10(np.abs(dut.s[:,1,0])),
                label="Measured DUT"
            )

            plt.plot(
                result.frequency.f/1e9,
                20*np.log10(np.abs(result.s[:,1,0])),
                label="Deembedded DUT"
            )

            plt.legend()

            plt.grid(True)

            plt.show()
        return result

    def s11_to_z(self, s11, z0):
        denominator = 1.0 - s11

        denominator = np.where(
            np.abs(denominator) < EPS,
            EPS + 0j,
            denominator
        )

        return z0 * (1.0 + s11) / denominator


    def z_to_s11(self, impedance, z0):
        denominator = impedance + z0

        denominator = np.where(
            np.abs(denominator) < EPS,
            EPS + 0j,
            denominator
        )

        return (
            impedance - z0
        ) / denominator
        

        


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
        # ttk.Checkbutton(self.reflect_b_frame, text="Open", variable=self.open_b).grid(row=0, column=0, sticky="w")
        # ttk.Checkbutton(self.reflect_b_frame, text="Short", variable=self.short_b).grid(row=1, column=0, sticky="w")


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
        print("plot_thru =", self.plot_thru.get())
        print("standard_files =", self.standard_files)

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

        # if reflect_selected:
            # self.use_2x_thru.set(False)
            # self.use_second_2x.set(False)
        if reflect_selected:
            print("Reflect standard selected")

        self._store_page2()
        self.update_standard_summary()


    def on_2x_thru_changed(self):
        """
        Lorsqu'un 2X Thru est sélectionné,
        les standards Open et Short sont désélectionnés.
        """
        print("SEARCHING THRU_LINE1")
        print(self.standard_files.get("THRU_LINE1"))

        print("SEARCHING THRU_LINE2")
        print(self.standard_files.get("THRU_LINE2"))


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
            print("CHK_2X destroyed")
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
        # for widget in [self.chk_second, self.diag_second, self.chk_dut, self.diag_dut,
        #                self.reflect_a_frame, self.reflect_b_frame]:
        #     widget.grid_forget()

        # for widget in [
        #     self.chk_second,
        #     self.diag_second,
        #     self.chk_dut,
        #     self.diag_dut,
        #     self.reflect_a_frame,
        #     self.reflect_b_frame
        # ]:

        #     try:

        #         if widget.winfo_exists():

        #             widget.grid_forget()

        #     except Exception:

        #         pass
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
        # self.use_2x_thru.set(True)
        # self.chk_2x.configure(state="disabled")
        print("CHK_2X =", self.chk_2x)
        print("EXIST =", self.chk_2x.winfo_exists())
        # self.chk_2x.configure(state="normal")

        if (
            hasattr(self, "chk_2x")
            and self.chk_2x.winfo_exists()
        ):
            self.chk_2x.configure(state="normal")

        # if different:
        if special_asymmetric_case:
            # Two independent symmetric characterization boards.
            self.diag_2x.draw_thru_aa()
            # self.use_second_2x.set(True)
            # self.chk_second.configure(state="disabled")
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

        # for widget in self.standard_area.winfo_children():
        #     widget.destroy()
        # for widget in self.standard_area.winfo_children():

        #     if getattr(widget, "_dynamic_widget", False):
        #         widget.destroy()
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
        print("validate_page2 called")

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

    # def _selected_standard_rows(self):
    #     rows = []
    #     defs = [("2x_thru", "2X Thru", self.use_2x_thru),
    #             ("second_2x_thru", "Second 2X Thru", self.use_second_2x),
    #             ("fixtured_dut", "Fixtured DUT", self.use_fixtured_dut),
    #             ("open_a", "Open Fixture A", self.open_a), ("short_a", "Short Fixture A", self.short_a),
    #             ("open_b", "Open Fixture B", self.open_b), ("short_b", "Short Fixture B", self.short_b)]
        # return [(key, label) for key, label, var in defs if var.get()]

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
        # self.impedance_result = tk.StringVar(value="Fixture A ZA: -- Ohms       Fixture B ZB: -- Ohms")
        # self.length_result = tk.StringVar(value="Fixture A: -- ns + Fixture B: -- ns = -- ns")
        self.result_frame = ttk.Frame(calc)
        self.result_frame.pack(fill="x")

       
        self.port_result_rows = {}



        # ttk.Label(calc, textvariable=self.impedance_result, font=("Segoe UI",11,"bold")).pack(anchor="w", padx=18, pady=3)
        ttk.Label(calc, text="Length").pack(anchor="w")
        # ttk.Label(calc, textvariable=self.length_result, font=("Segoe UI",11,"bold")).pack(anchor="w", padx=18, pady=3)
        td=ttk.LabelFrame(self.page3,text="Time Domain Settings",style="Section.TLabelframe",padding=12); td.pack(fill="x")
        self.step_rise=tk.DoubleVar(value=17.9880)
        self.enable_interpolation = tk.BooleanVar(value=True)
        self.interpolation_method = tk.StringVar(value="Linear")
        self.enable_filter = tk.BooleanVar(value=False)
        self.filter_method = tk.StringVar(value="Phase Only")
        r=ttk.Frame(td); r.pack(anchor="w"); ttk.Label(r,text="Step Rise Time:").pack(side="left")
        ttk.Entry(r,textvariable=self.step_rise,width=10).pack(side="left",padx=5); ttk.Label(r,text="ps").pack(side="left")
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
        # ttk.Checkbutton(interp_frame,text="Enable Frequency Interpolation",variable=self.enable_interpolation).pack(side="left")
        ttk.Label(interp_frame,text="Method:").pack(side="left", padx=(20,5))
        ttk.Combobox(interp_frame,textvariable=self.interpolation_method,values=["Linear","PCHIP","Cubic Spline","Akima"],state="readonly",width=16).pack(side="left")
        ttk.Checkbutton(td,text="Enable Frequency Interpolation",variable=self.enable_interpolation).pack(anchor="w", pady=5)
        ttk.Button(td,text="Calculate Fixture Characteristics",command=self.calculate_characteristics).pack(anchor="w",pady=8)
        # plot_button_frame = ttk.Frame(td),plot_button_frame.pack(fill="x",pady=(5, 0))
        plot_button_frame = ttk.Frame(td)
        plot_button_frame.pack(fill="x",pady=(5, 0))



        ttk.Button(
            plot_button_frame,
            text="Plot S-Parameters...",
            command=self.open_plot_window
        ).pack(side="left")

    def interpolate_complex_data(self,f,x,fu):
        if len(f) < 5:

            return (np.interp(fu, f, np.real(x))+1j*np.interp(fu, f, np.imag(x)))
        method = self.interpolation_method.get()
        print("Original Points =",len(f))

        print(
            "Interpolated Points =",
            len(fu)
        )
        xr = np.real(x)
        xi = np.imag(x)
        if method == "Linear":
            xr_new = np.interp(fu,f,xr)
            xi_new = np.interp(fu,f,xi)
        elif method == "PCHIP":
            xr_new = PchipInterpolator(f,xr)(fu)
            xi_new = PchipInterpolator(f,xi)(fu)
        elif method == "Cubic Spline":
            xr_new = CubicSpline(f,xr)(fu)
            xi_new = CubicSpline(f,xi)(fu)
        elif method == "Akima":
            xr_new = Akima1DInterpolator(f,xr)(fu)
            xi_new = Akima1DInterpolator(f,xi)(fu)
        else:
            xr_new = np.interp(fu,f,xr)
            xi_new = np.interp(fu,f,xi)
        return xr_new + 1j * xi_new
    def create_port_result_row(self, port):
        if port in self.port_result_rows:
            return
        row = len(self.port_result_rows)
        z_var = tk.StringVar(value=f"Port {port} Z = --")
        d_var = tk.StringVar(value=f"Port {port} TTD = --")

        ttk.Label(
            self.result_frame,
            textvariable=z_var
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=10
        )

        ttk.Label(
            self.result_frame,
            textvariable=d_var
        ).grid(
            row=row,
            column=1,
            sticky="w",
            padx=10
        )

        self.port_result_rows[port] = (
            z_var,
            d_var
        )

    
    def open_plot_window(self):
        """
        Ouvre une nouvelle fenêtre contenant :
        - la sélection des fichiers à afficher ;
        - la sélection des paramètres S ;
        - le format amplitude/phase ;
        - le graphique Matplotlib.
        """

        if self.plot_window is not None:
            try:
                if self.plot_window.winfo_exists():
                    self.plot_window.lift()
                    self.plot_window.focus_force()
                    return
            except tk.TclError:
                self.plot_window = None

        self.plot_window = tk.Toplevel(self)
        self.plot_window.title("AFR S-Parameter Plot")
        self.plot_window.geometry("1350x850")
        self.plot_window.minsize(1000, 700)
        self.plot_window.configure(background=APP_BG)

        self.plot_window.protocol(
                "WM_DELETE_WINDOW",
                self.close_plot_window
            )

        controls = ttk.Frame(
                self.plot_window,
                padding=10
            )

        controls.pack(
                side="left",
                fill="y"
            )

        graph_frame = ttk.Frame(
                self.plot_window,
                padding=5
            )

        graph_frame.pack(
                side="right",
                fill="both"
                ,expand=True
            )

        # ============================================================
        # Sources à tracer
        # ============================================================

        source_frame = ttk.LabelFrame(controls,text="Plot Sources",style="Section.TLabelframe",padding=10)
        source_frame.pack(fill="x",pady=(0, 10))

        self.plot_sources = {}
        # =========================
        # THRU (2xThru originaux)
        # =========================

        for key in sorted(
            getattr(
                self,
                "fixture_pairs",
                {}
            ).keys()
        ):

            var = tk.BooleanVar(value=False)

            self.plot_sources[key] = var

            ttk.Checkbutton(
                source_frame,
                text=key,
                variable=var
            ).pack(anchor="w")


        # =========================
        # HALF (résultats extraits)
        # =========================

        for key in sorted(
            getattr(
                self,
                "half_networks",
                {}
            ).keys()
        ):

            var = tk.BooleanVar(value=False)

            self.plot_sources[key] = var

            ttk.Checkbutton(
                source_frame,
                text=key,
                variable=var
            ).pack(anchor="w")


        print("HALF NETWORKS")
        print("HALF NETWORKS AVAILABLE")
        
        print(self.half_networks.keys())
        print("HALF NETWORKS =", self.half_networks)
        print("FIXTURE PAIRS =", self.fixture_pairs)


        print("FIXTURE PAIRS")
        print(self.fixture_pairs.keys())
        # ============================================================
        # Paramètres S
        # ============================================================

        parameter_frame = ttk.LabelFrame(
            controls,
            text="S-Parameters",
            style="Section.TLabelframe",
            padding=10
        )
        parameter_frame.pack(
            fill="x",
            pady=(0, 10)
        )

        ttk.Checkbutton(
            parameter_frame,
            text="S11",
            variable=self.plot_s11
        ).pack(anchor="w", pady=2)

        ttk.Checkbutton(
            parameter_frame,
            text="S12",
            variable=self.plot_s12
        ).pack(anchor="w", pady=2)

        ttk.Checkbutton(
            parameter_frame,
            text="S21",
            variable=self.plot_s21
        ).pack(anchor="w", pady=2)

        ttk.Checkbutton(
            parameter_frame,
            text="S22",
            variable=self.plot_s22
        ).pack(anchor="w", pady=2)

        # ============================================================
        # Format amplitude et phase
        # ============================================================

        format_frame = ttk.LabelFrame(
            controls,
            text="Plot Format",
            style="Section.TLabelframe",
            padding=10
        )
        format_frame.pack(
            fill="x",
            pady=(0, 10)
        )

        ttk.Radiobutton(
            format_frame,
            text="Amplitude dB + Phase degrees",
            value="db_phase",
            variable=self.plot_format
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            format_frame,
            text="Magnitude + Phase radians",
            value="mag_phase",
            variable=self.plot_format
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            format_frame,
            text="Real + Imaginary",
            value="real_imag",
            variable=self.plot_format
        ).pack(anchor="w", pady=2)

        # ============================================================
        # Boutons
        # ============================================================

        ttk.Button(
            controls,
            text="Update Plot",
            command=self.update_plot_window
        ).pack(
            fill="x",
            pady=(5, 3)
        )

        ttk.Button(
            controls,
            text="Select All S-Parameters",
            command=self.select_all_sparameters
        ).pack(
            fill="x",
            pady=3
        )

        ttk.Button(
            controls,
            text="Clear Plot Selection",
            command=self.clear_plot_selection
        ).pack(
            fill="x",
            pady=3
        )

        ttk.Button(
            controls,
            text="Close",
            command=self.close_plot_window
        ).pack(
            fill="x",
            pady=(15, 3)
        )

        # ============================================================
        # Figure Matplotlib intégrée dans Tkinter
        # ============================================================

        self.plot_figure = Figure(
            figsize=(12, 7),
            dpi=100
        )

        self.plot_canvas = FigureCanvasTkAgg(
            self.plot_figure,
            master=graph_frame
        )

        self.plot_canvas.get_tk_widget().pack(
            fill="both",
            expand=True
        )

        self.update_plot_window()

    def close_plot_window(self):
        """Ferme et réinitialise la fenêtre de graphique."""

        if self.plot_window is not None:
            try:
                self.plot_window.destroy()
            except tk.TclError:
                pass

        self.plot_window = None
        self.plot_canvas = None

    def select_all_sparameters(self):
        """Sélectionne tous les paramètres S."""

        self.plot_s11.set(True)
        self.plot_s12.set(True)
        self.plot_s21.set(True)
        self.plot_s22.set(True)
        self.update_plot_window()
    def clear_plot_selection(self):

        for var in self.plot_sources.values():
            var.set(False)

        self.update_plot_window()


    def get_selected_plot_networks(self):
        """
        Retourne la liste des réseaux sélectionnés.

        Chaque élément retourné est :
            (nom_affiché, réseau_skrf)
        """
        print()
        print("======================")
        print("PLOT SOURCES")
        print("======================")

        for name, var in self.plot_sources.items():

            print(
                name,
                "=",
                var.get()
            )
        print("======================")
        print("PLOT STATUS")
        print("======================")
        print("plot_open =", self.plot_open.get())

        print("THRU =", self.plot_thru.get())
        print("HALF A =", self.plot_half_a.get())
        print("HALF B =", self.plot_half_b.get())
        print("plot_thru =", self.plot_thru.get())
        print("standard_files =", self.standard_files)
        print("plot_half_a =", self.plot_half_a.get())
        print("plot_half_b =", self.plot_half_b.get())

        print("fixture_a_network =", self.fixture_a_network)
        print("fixture_b_network =", self.fixture_b_network)
        # print("OPEN KEY =", key, converted)
        for key, converted in self.converted_open_files.items():

            print(
                "OPEN KEY =",
                key,
                converted
            )

        networks = []
            # ============================================================
            # 2X Thru mesuré
            # ============================================================
        for key, var in self.plot_sources.items():

            if not var.get():
                continue
            if key.startswith("THRU_"):

                filename = self.standard_files.get(key)

                if filename:
                    
                    print("ADDING THRU", key)
                    networks.append(
                        (
                            key,
                            rf.Network(filename)
                        )
                    )
            # elif key.startswith("HALF_"):
            elif (
                    key.endswith("_IN")
                    or
                    key.endswith("_OUT")
                ):

                net = self.half_networks.get(key)

                if net is not None:

                    networks.append(
                        (
                            key,
                            net
                        )
                    )
                
    
                    plot_ports = getattr(
                        self,
                        "plot_port_names",
                        {}
                    )

                    p1, p2 = plot_ports.get(
                        "THRU_LINE1",
                        (1,2)
                    )

                label_a = f"Half Fixture A (THRU {p1}-{p2})"
                label_b = f"Half Fixture B (THRU {p1}-{p2})"

           
        # ============================================================
        # Open mesuré et converti
        # ============================================================
        # self.plot_open = tk.BooleanVar(value=False)

        if self.plot_open.get():

            for key in ("OPEN_A","OPEN_B"):

        # for key in ("OPEN_A","OPEN_B"):
            

                net = self.converted_networks.get(key)

                converted = self.converted_open_files.get(key)

                if net is not None:

                    networks.append(
                        (
                            key,
                            net
                        )
                    )
                    converted = self.converted_open_files.get(key)

                elif (
                    isinstance(converted, str)
                    and
                    Path(converted).is_file()
                ):

                    networks.append(
                        (
                            key,
                            rf.Network(converted)
                        )
                    )

            # ============================================================
            # Short mesuré et converti
            # ============================================================

            # converted = self.converted_short_files.get(key)
            converted = None
            if self.plot_short.get():
                for key, label in (
                    ("SHORT_A", "Short Fixture A measured"),
                    ("SHORT_B", "Short Fixture B measured"),
                ):
                    converted = self.converted_short_files.get(key)
                    filename = self.standard_files.get(key)

                    if filename:
                        try:
                            networks.append(
                                (
                                    label,
                                    rf.Network(filename)
                                )
                            )
                        except Exception as error:
                            print(
                                f"Unable to load {key}: {error}"
                            )

                    # converted = self.converted_files.get(key)
                    net = self.converted_networks.get(key)

                    if net is not None:

                        networks.append(
                            (
                                key,
                                net
                            )
                        )

                    if isinstance(converted, rf.Network):
                        networks.append(
                            (
                                label.replace(
                                    "measured",
                                    "converted"
                                ),
                                converted
                            )
                        )
                        converted = self.converted_open_files.get(key)

                    elif isinstance(converted, str):
                        if Path(converted).is_file():
                            networks.append(
                                (
                                    label.replace(
                                        "measured",
                                        "converted"
                                    ),
                                    rf.Network(converted)
                                )
                                )
                            print("================================")
                            print("NETWORKS AVAILABLE FOR PLOT")
                            print("================================")

                            for name, net in networks:
                                print(name, net.nports, net.frequency.npoints)

                                print("================================")
                                print("NETWORKS SENT TO PLOT")
                                print("================================")

                                for name, net in networks:
                                    print(name)
        # --------------------------------------------------
        # Remove duplicates
        # --------------------------------------------------

        unique = {}

        for name, net in networks:
            unique[name] = net

        networks = list(unique.items())

        print("FINAL NETWORKS")

        for name, _ in networks:
            print(name)

        return networks

            #         # --------------------------------------------------
            #         # Remove duplicates
            #         # --------------------------------------------------
            # unique = {}

            # for name, net in networks:
            #     unique[name] = net

            # networks = list(unique.items())

            # print("FINAL NETWORKS")

            # for name, _ in networks:
            #     print(name)

            #     print("================================")
            #     print("NETWORKS SENT TO PLOT")
            #     print("================================")

            #     for name, net in networks:
            #         print(name)

            #     print("FINAL NETWORK CONTENT")

            #     for name, net in networks:
            #         print(" -> ", name)
            #         print("RETURNING NETWORKS")
            # print(networks)

            # return networks

            # return networks


    def get_selected_sparameters(self):
        """Retourne les paramètres S sélectionnés."""
        
        parameters = []

        if not self.get_selected_plot_networks():
            return parameters

        # network = self.get_selected_plot_networks()[0][1]

        # print("NETWORK USED FOR PARAMETER LIST")
        # print(network)
        # print("NPORTS =", network.nports)

        # for i in range(network.nports):

        #     for j in range(network.nports):

        #         parameters.append(
        #             (
        #                 f"S{i+1}{j+1}",
        #                 i,
        #                 j
        #             )
        #         )
        max_ports = 1

        for _, net in self.get_selected_plot_networks():

            max_ports = max(
                max_ports,
                net.nports
            )

        parameters = []

        for name, var in self.sparam_vars.items():

            if var.get():

                i = int(name[1]) - 1
                j = int(name[2]) - 1

                parameters.append(
                    (
                        name,
                        i,
                        j
                    )
                )

        return parameters

    


    def update_plot_window(self):
        
        """Met à jour le graphique selon les sélections."""

        print("================================")
        print("UPDATE PLOT")
        print("================================")

        nets = self.get_selected_plot_networks()

        if nets is None:
            print("ERROR : get_selected_plot_networks returned None")
            return

        # nets = self.collect_networks()

        print("NETS TYPE =", type(nets))
        print("NETS VALUE =", nets)

        print("NETWORKS =", len(nets))

        for name, net in nets:
            print(name, net.nports)

        if not hasattr(self, "plot_figure"):
            return

        self.plot_figure.clear()

        networks = self.get_selected_plot_networks()
        print("NB NETWORKS =", len(networks))

        parameters = self.get_selected_sparameters()

        if not networks:
            axis = self.plot_figure.add_subplot(111)

            axis.text(
                0.5,
                0.5,
                "No plot source is currently available.\n"
                "Load and calculate the selected standards first.",
                horizontalalignment="center",
                verticalalignment="center",
                transform=axis.transAxes
            )

            axis.set_axis_off()

            if self.plot_canvas is not None:
                self.plot_canvas.draw_idle()

            return

        if not parameters:
            axis = self.plot_figure.add_subplot(111)

            axis.text(
                0.5,
                0.5,
                "Select at least one S-parameter.",
                horizontalalignment="center",
                verticalalignment="center",
                transform=axis.transAxes
            )

            axis.set_axis_off()

            if self.plot_canvas is not None:
                self.plot_canvas.draw_idle()

            return

        plot_format = self.plot_format.get()
        column_count = len(parameters)

        axes_top = []
        axes_bottom = []

        for column_index in range(column_count):
            top_axis = self.plot_figure.add_subplot(
                2,
                column_count,
                column_index + 1
            )

            bottom_axis = self.plot_figure.add_subplot(
                2,
                column_count,
                column_count + column_index + 1
            )

            axes_top.append(top_axis)
            axes_bottom.append(bottom_axis)

        for label, network in networks:
            frequency_ghz = (
                network.frequency.f / 1e9
            )

            for column_index, (
                parameter_name,
                row_index,
                port_index
            ) in enumerate(parameters):

                if (
                    row_index >= network.nports
                    or port_index >= network.nports
                ):
                    continue

                s_parameter = network.s[
                    :,
                    row_index,
                    port_index
                ]

                magnitude = np.abs(s_parameter)

                if plot_format == "db_phase":
                    top_values = 20.0 * np.log10(
                        np.maximum(
                            magnitude,
                            1e-15
                        )
                    )

                    unwrapped_phase = np.unwrap(
                        np.angle(s_parameter)
                    )

                    bottom_values = np.rad2deg(
                        unwrapped_phase
                    )

                    top_ylabel = "Amplitude (dB)"
                    bottom_ylabel = "Phase (degrees)"

                elif plot_format == "mag_phase":
                    top_values = magnitude

                    bottom_values = np.unwrap(
                        np.angle(s_parameter)
                    )

                    top_ylabel = "Magnitude"
                    bottom_ylabel = "Phase (radians)"

                else:
                    top_values = np.real(
                        s_parameter
                    )

                    bottom_values = np.imag(
                        s_parameter
                    )

                    top_ylabel = "Real"
                    bottom_ylabel = "Imaginary"

                axes_top[column_index].plot(
                    frequency_ghz,
                    top_values,
                    label=label
                )

                axes_bottom[column_index].plot(
                    frequency_ghz,
                    bottom_values,
                    label=label
                )

                axes_top[column_index].set_title(
                    parameter_name
                )

                axes_top[column_index].set_ylabel(
                    top_ylabel
                )

                axes_bottom[column_index].set_ylabel(
                    bottom_ylabel
                )

                axes_bottom[column_index].set_xlabel(
                    "Frequency (GHz)"
                )

        for axis in axes_top + axes_bottom:
            axis.grid(True)

            handles, labels = (
                axis.get_legend_handles_labels()
            )

            if handles:
                axis.legend(
                    fontsize=8
                )

        self.plot_figure.tight_layout()

        if self.plot_canvas is not None:
            self.plot_canvas.draw_idle()


            


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

    # def load_standard(self,key):
    #     from tkinter import filedialog
    #     f=filedialog.askopenfilename(filetypes=[("Touchstone","*.s1p *.s2p *.s4p"),("All files","*.*")])
    #     if f: self.standard_file_vars[key].set(f); self.status.set(f"Loaded: {f}")
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


    def load_s2p(self, path):
        path = Path(path)

        if not path.is_file():
            raise FileNotFoundError(path)

        network = rf.Network(str(path))

        if network.nports != 2:
            raise ValueError(
                f"{path.name} is not a 2-port Touchstone file."
            )

        frequency = np.asarray(
            network.f,
            dtype=float
        )

        s_parameters = np.asarray(
            network.s,
            dtype=complex
        )

        self.check_frequency_grid(frequency)

        self.check_finite_complex(
            s_parameters,
            "S2P"
        )

        try:
            z0 = float(
                np.real(
                    np.asarray(network.z0).flat[0]
                )
            )
        except Exception:
            z0 = 50.0

        return frequency, s_parameters, z0


    def load_s1p(self, path):
        path = Path(path)

        if not path.is_file():
            raise FileNotFoundError(path)

        network = rf.Network(str(path))

        if network.nports != 1:
            raise ValueError(
                f"{path.name} is not a 1-port Touchstone file."
            )

        frequency = np.asarray(
            network.f,
            dtype=float
        )

        s11 = np.asarray(
            network.s[:, 0, 0],
            dtype=complex
        )

        self.check_frequency_grid(frequency)

        self.check_finite_complex(
            s11,
            "S1P"
        )

        try:
            z0 = float(
                np.real(
                    np.asarray(network.z0).flat[0]
                )
            )
        except Exception:
            z0 = 50.0

        return frequency, s11, z0




    

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


        print("================================")
        print("STANDARD FILES")
        print("================================")

        for k,v in self.standard_files.items():
            print(k,"=>",v)

        print("================================")
        print("CONFIG")
        print("================================")

        print("use_2x_thru =", self.config_data.use_2x_thru)
        print("use_second_2x_thru =", self.config_data.use_second_2x_thru)
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

            print("================================")
            print("STANDARD FILES")
            print("================================")
            print(self.standard_files)

            print("================================")
            print("SELECTED ROWS")
            print("================================")
            print(self._selected_standard_rows())


            for key in self.standard_files:

                if key.startswith("THRU_"):

                    self.calculate_thru_fixture(key)


            self.calculate_reflection_fixtures()
            self.update_fixture_result_labels()
            print("STEP 1 OK")

            self.extraction_done = True
            print("STEP 2 OK")

            self.status.set(
                "Fixture characteristics calculated successfully."
            )
            print("STEP 3 OK")
            print()
            print("====================")
            print("CONVERTED OPEN FILES")
            print("====================")

            print(
                getattr(
                    self,
                    "converted_open_files",
                    {}
                )
            )

            print(self.converted_open_files)

            print()
            print("====================")
            print("CONVERTED NETWORKS")
            print("====================")

            print(self.converted_networks.keys())

            print()
            print("=====================")
            print("HALF NETWORKS CHECK")
            print("=====================")
            self.fixture_pairs.keys()
            self.half_networks.keys()
            

            print(self.half_networks.keys())

            print()
            print("=====================")
            print("FIXTURE PAIRS CHECK")
            print("=====================")

            print(self.fixture_pairs.keys())

            print("================================")
            print("SELECTED STANDARDS")
            print("================================")
            print("use_2x_thru =", self.config_data.use_2x_thru)
            print("use_second_2x_thru =", self.config_data.use_second_2x_thru)

        except Exception as error:
            messagebox.showerror(
                "AFR calculation error",
                str(error)
            )
            print("PORT RESULT ROWS =")
            print(self.port_result_rows)

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

        print("FIXTURE A =", self.fixture_a_network)
        print("FIXTURE B =", self.fixture_b_network)


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

        # else:
        #             return
        print("DISPLAY PORTS =", p1, p2)
        self.create_port_result_row(p1)
        self.create_port_result_row(p2)

        
                

        z_var, d_var = self.port_result_rows[p1]

        z_var.set(
            f"Port {p1} Z = {information['z1']:.2f} Ohm"
        )

        d_var.set(
            f"Port {p1} TTD = {information['delay1']:.2f} ps"
        )

        z_var, d_var = self.port_result_rows[p2]

        z_var.set(
            f"Port {p2} Z = {information['z2']:.2f} Ohm"
        )

        d_var.set(
            f"Port {p2} TTD = {information['delay2']:.2f} ps"
        )
                

    def calculate_reflection_fixtures(self):

       

        reflection_keys = []

        for key in self.standard_files:

            if key.startswith("OPEN_"):
                reflection_keys.append(key)

            elif key.startswith("SHORT_"):
                reflection_keys.append(key)

        for key in reflection_keys:

            if key not in self.standard_files:
                continue

            # La cle (OPEN_A, SHORT_B, ...) fixe le signe du standard
            # (Gamma_L = +1 pour OPEN, -1 pour SHORT).
            network, impedance, delay = (
                self.build_afr_s2p_from_s1p(
                    self.standard_files[key],
                    reflect_type=key
                )
            )

    

            # self.converted_files[key] = network
            self.converted_networks[key] = network
            # self.converted_networks[key] = net

            self.half_networks[f"{key}_HALF"] = network

            self.extracted_info[key] = {
                "z": impedance,
                "delay": delay,
            }


            output_base = (
                Path(self.rf_output_dir.get())
                / f"{key}_CONVERTED"
            )
            converted_path = str(output_base) + ".s2p"
            
            self.converted_files[key] = converted_path
            if key.startswith("OPEN_"):
                self.converted_open_files[key] = converted_path

            if key.startswith("SHORT_"):
                self.converted_short_files[key] = converted_path

            network.write_touchstone(
                str(output_base),
                form=self.export_format.get()
            )
            print("================================")
            print("OPEN/SHORT CONVERTED FILES")
            print("================================")
    
            for k,v in self.converted_files.items():
                print(k, "=>", v)

            

            # output_base = Path(
            #     self.rf_output_dir
            # ) / f"{key}_CONVERTED"

            # network.write_touchstone(
            #     str(output_base),
            #     form=self.export_format.get()
            # )
    def update_fixture_result_labels(self):
        fixture_a_values = []
        fixture_b_values = []
        

        for key in ("OPEN_A", "SHORT_A"):
            data = self.extracted_info.get(key)

            if data:
                fixture_a_values.append(data)

        for key in ("OPEN_B", "SHORT_B"):
            data = self.extracted_info.get(key)

            if data:
                fixture_b_values.append(data)


        thru_keys = [
            k
            for k in self.extracted_info
            if k.startswith("THRU_")
        ]

        if len(thru_keys) > 0:
            thru_1 = self.extracted_info[thru_keys[0]]
        else:
            thru_1 = None

        if len(thru_keys) > 1:
            thru_2 = self.extracted_info[thru_keys[1]]
        else:
            thru_2 = None




        if fixture_a_values:
            za = np.mean([
                value["z"]
                for value in fixture_a_values
            ])

            delay_a = np.mean([
                value["delay"]
                for value in fixture_a_values
            ])

        elif thru_1:
            za = thru_1["z1"]
            delay_a = thru_1["delay1"]

        else:
            za = None
            delay_a = None

        if fixture_b_values:
            zb = np.mean([
                value["z"]
                for value in fixture_b_values
            ])

            delay_b = np.mean([
                value["delay"]
                for value in fixture_b_values
            ])

        elif thru_2:
            zb = thru_2["z2"]
            delay_b = thru_2["delay2"]

        elif thru_1:
            zb = thru_1["z2"]
            delay_b = thru_1["delay2"]

        else:
            zb = None
            delay_b = None

        za_text = (
            f"{za:.2f} Ohms"
            if za is not None
            else "-- Ohms"
        )

        zb_text = (
            f"{zb:.2f} Ohms"
            if zb is not None
            else "-- Ohms"
        )

        delay_a_text = (
            f"{delay_a:.2f} ps"
            if delay_a is not None
            else "-- ps"
        )

        delay_b_text = (
            f"{delay_b:.2f} ps"
            if delay_b is not None
            else "-- ps"
        )

        # self.impedance_result.set(
        #     f"Fixture A ZA: {za_text}       "
        #     f"Fixture B ZB: {zb_text}"
        # )

        # self.length_result.set(
        #     f"Fixture A delay: {delay_a_text}       "
        #     f"Fixture B delay: {delay_b_text}"
        # )
        # self.impedance_result.set(
        #     f"ZA = {za:.2f} Ohm    |    ZB = {zb:.2f} Ohm"
        # )

        za_value = "--" if za is None else f"{za:.2f}"
        zb_value = "--" if zb is None else f"{zb:.2f}"

        # self.impedance_result.set(
        #     f"ZA = {za_value} Ohm | ZB = {zb_value} Ohm"
        # )

        print("delay_a =", delay_a)
        print("delay_b =", delay_b)
        print("type delay_a =", type(delay_a))
        print("type delay_b =", type(delay_b))

        if delay_a is None:
            delay_a_text = "--"
        else:
            delay_a_text = f"{delay_a:.2f}"

        if delay_b is None:
            delay_b_text = "--"
        else:
            delay_b_text = f"{delay_b:.2f}"

        # self.length_result.set(
        #     f"TTD_A = {delay_a_text} ps | TTD_B = {delay_b_text} ps"
        # )
        print("LABEL UPDATE FINISHED")

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
        from pathlib import Path
        ttk.Label(self.page5,text="Save Fixture",style="PageTitle.TLabel").pack(anchor="w",pady=(0,10))
        f=ttk.LabelFrame(self.page5,text="File format",style="Section.TLabelframe",padding=12); f.pack(fill="x")
        self.save_format=tk.StringVar(value="touchstone")
        for text,val in [("Touchstone","touchstone"),("Touchstone 2","touchstone2"),("Citifile","citifile")]: ttk.Radiobutton(f,text=text,value=val,variable=self.save_format).pack(anchor="w")
        self.make4=tk.BooleanVar(); ttk.Checkbutton(f,text="Make 4 ports file from 2 ports data",variable=self.make4).pack(anchor="w")
        p=ttk.LabelFrame(self.page5,text="Port assignment",style="Section.TLabelframe",padding=12); p.pack(fill="x",pady=10)
        self.port_format=tk.StringVar(value="vna")
        for text,val in [("PLTS Format","plts"),("VNA Format","vna"),("ADS Format","ads")]: ttk.Radiobutton(p,text=text,value=val,variable=self.port_format).pack(anchor="w")
        o=ttk.LabelFrame(self.page5,text="Output",style="Section.TLabelframe",padding=12); o.pack(fill="x")
        # self.output_dir=tk.StringVar(value=self.rf_output_dir); 
        self.base_name=tk.StringVar(value="HALF")
        ttk.Label(o,text="Directory:").grid(row=0,column=0,sticky="w"); ttk.Entry(o,textvariable=self.rf_output_dir).grid(row=0,column=1,sticky="ew",padx=5)
        ttk.Button(o,text="Browse...",command=self.choose_output).grid(row=0,column=2)
        ttk.Label(o,text="Base file name:").grid(row=1,column=0,sticky="w",pady=5); ttk.Entry(o,textvariable=self.base_name).grid(row=1,column=1,sticky="ew",padx=5)
        ttk.Button(o,text="Save Fixture Files",command=self.save_fixtures).grid(row=2,column=1,pady=10); o.columnconfigure(1,weight=1)

    def choose_output(self):
        from tkinter import filedialog
        d=filedialog.askdirectory()
        if d: self.rf_output_dir.set(d)

    # def save_fixtures(self):
    #     from pathlib import Path
    #     d=Path(self.rf_output_dir.get()); d.mkdir(parents=True,exist_ok=True); base=self.base_name.get().strip()
    #     if not base: messagebox.showwarning("Missing name","Enter a base file name."); return
    #     ext={"touchstone":".s2p","touchstone2":".ts","citifile":".cti"}[self.save_format.get()]
    #     for n in (1,2): (d/f"{base}{n}{ext}").write_text("! AFR placeholder - RF backend not connected\n",encoding="utf-8")
    #     messagebox.showinfo("Saved",f"Prototype fixture files saved in {d}")


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
        from tkinter import filedialog
        d=filedialog.askdirectory()
        if d: var.set(d)

    def run_batch(self):
        from pathlib import Path
        d=Path(self.batch_in.get())
        if not d.is_dir(): messagebox.showwarning("Invalid folder","Choose a valid input directory."); return
        files=sorted(d.glob(self.batch_pattern.get())); self.batch_log.config(state="normal"); self.batch_log.delete("1.0","end")
        self.batch_log.insert("end",f"Found {len(files)} file(s).\n"+"\n".join(x.name for x in files)+"\n\nRF processing backend not connected.\n"); self.batch_log.config(state="disabled")

 
    def request_page(self, target_page):
        """Control navigation through the page tabs."""
        try:
            print("REQUEST PAGE =", target_page)
        except Exception as e:
            print(e)

        print("REQUEST PAGE =", target_page)

        if hasattr(self, "chk_2x"):
            try:
                print("CHK_2X EXISTS =", self.chk_2x.winfo_exists())
            except:
                print("CHK_2X ERROR")

        
        

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
            print("BEFORE SYNC")

            self.synchronize_page2_from_page1()
            print("AFTER SYNC")

        # A direct jump from Page 1 to Page 3, 4, 5 or 6
        # must also validate Page 2.

        if target_page >= 2:

            self.synchronize_page2_from_page1()

            if not self.validate_page2():
                self.show_page(1)
                return

            self.show_page(target_page)
            return

        # cas page 0 -> page 1
        self.show_page(target_page)


        # if target_page >= 2:
        #     print("BEFORE SYNC")
        #     self.synchronize_page2_from_page1()
        #     print("AFTER SYNC")

        #     if not self.validate_page2():
        #         self.show_page(1)
        #         return
        #     print("BEFORE SYNC")

        #     self.show_page(target_page)
        #     print("AFTER SYNC")

    def show_page(self, page_index):
        if page_index < 0 or page_index > 5:
            return

        # if page_index == 1:
        #     try:
        #         if self.z0_mode.get() == "fixed":
        #             if self.z0_value.get() <= 0:
        #                 messagebox.showwarning(
        #                     "Invalid Z0",
        #                     "Calibration Reference Z0 must be positive."
        #                 )
        #                 return
        #     except tk.TclError:
        #         messagebox.showwarning(
        #             "Invalid Z0",
        #             "Calibration Reference Z0 must be a numeric value."
        #         )
        #         return
        #     print("BEFORE SYNC")

        #     self.synchronize_page2_from_page1()
            # print("AFTER SYNC")

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
    AFRWizardComplete().mainloop()
