import tkinter as tk
from tkinter import filedialog, Menu, ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np
import csv
from function import load_s2p

class S2PViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Interface de Mesure")
        self.root.geometry("1100x850")

        self.network = None
        self.canvas = None
        self.hover_annotation = None
        self.x_data = None
        self.y_data = None

        self.freq_min = tk.DoubleVar()
        self.freq_max = tk.DoubleVar()
        self.y_min = tk.DoubleVar()
        self.y_max = tk.DoubleVar()

        self.setup_menu()

        self.main_frame = tk.Frame(root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.plot_control_frame = tk.Frame(self.main_frame)
        self.plot_control_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.control_bar = tk.Frame(self.plot_control_frame)
        self.control_bar.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.trace_var = tk.StringVar(value="S11")
        self.trace_box = ttk.Combobox(self.control_bar, textvariable=self.trace_var, state="readonly",
                                      values=["S11", "S12", "S21", "S22"])
        self.trace_box.pack(side=tk.LEFT, padx=5)
        self.trace_box.bind("<<ComboboxSelected>>", lambda e: self.update_plot(reset_range=True))

        self.display_var = tk.StringVar(value="Amplitude (dB)")
        self.display_box = ttk.Combobox(self.control_bar, textvariable=self.display_var, state="readonly",
                                        values=["Amplitude (dB)", "Phase (deg)"])
        self.display_box.pack(side=tk.LEFT, padx=5)
        self.display_box.bind("<<ComboboxSelected>>", lambda e: self.update_plot(reset_range=True))

        self.export_button = tk.Button(self.control_bar, text="💾 Export", command=self.export_csv)
        self.export_button.pack(side=tk.RIGHT, padx=10)

        self.canvas_frame = tk.Frame(self.plot_control_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.slider_frame = tk.Frame(self.plot_control_frame)
        self.slider_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)

        # Sliders double (Fréquence) sur une ligne
        freq_frame = tk.Frame(self.slider_frame)
        freq_frame.pack(fill=tk.X)
        tk.Label(freq_frame, text="Fréq min (GHz)").pack(side=tk.LEFT)
        self.freq_slider_min = tk.Scale(freq_frame, variable=self.freq_min, orient=tk.HORIZONTAL, resolution=0.01,
                                        length=400, command=lambda x: self.update_plot())
        self.freq_slider_min.pack(side=tk.LEFT, padx=5)
        tk.Label(freq_frame, text="Fréq max (GHz)").pack(side=tk.LEFT)
        self.freq_slider_max = tk.Scale(freq_frame, variable=self.freq_max, orient=tk.HORIZONTAL, resolution=0.01,
                                        length=400, command=lambda x: self.update_plot())
        self.freq_slider_max.pack(side=tk.LEFT, padx=5)

        # Sliders double (Amplitude/Phase) sur une ligne
        y_frame = tk.Frame(self.slider_frame)
        y_frame.pack(fill=tk.X)
        tk.Label(y_frame, text="Y min").pack(side=tk.LEFT)
        self.y_slider_min = tk.Scale(y_frame, variable=self.y_min, orient=tk.HORIZONTAL, resolution=1,
                                     length=400, command=lambda x: self.update_plot())
        self.y_slider_min.pack(side=tk.LEFT, padx=5)
        tk.Label(y_frame, text="Y max").pack(side=tk.LEFT)
        self.y_slider_max = tk.Scale(y_frame, variable=self.y_max, orient=tk.HORIZONTAL, resolution=1,
                                     length=400, command=lambda x: self.update_plot())
        self.y_slider_max.pack(side=tk.LEFT, padx=5)

        self.button_frame = tk.Frame(self.main_frame)
        self.button_frame.pack(side=tk.RIGHT, fill=tk.Y)

        for label in ["FREQ", "Gen S2P", "CAL", "MEAS", "APP"]:
            tk.Button(self.button_frame, text=label, height=2, width=10).pack(pady=5)

    def setup_menu(self):
        menu_bar = Menu(self.root)
        file_menu = Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Open", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menu_bar)

    def open_file(self):
        filepath = filedialog.askopenfilename(
            title="Choisir un fichier .s2p",
            filetypes=[("Touchstone files", "*.s2p"), ("All files", "*.*")]
        )
        if filepath:
            self.network = load_s2p(filepath)
            if self.network:
                self.set_slider_ranges()
                self.update_plot()

    def set_slider_ranges(self):
        freqs_ghz = self.network.f / 1e9
        self.freq_slider_min.config(from_=freqs_ghz.min(), to=freqs_ghz.max())
        self.freq_slider_max.config(from_=freqs_ghz.min(), to=freqs_ghz.max())
        self.freq_min.set(freqs_ghz.min())
        self.freq_max.set(freqs_ghz.max())

        trace = self.trace_var.get()
        m, n = int(trace[1]) - 1, int(trace[2]) - 1
        s_param = self.network.s[:, m, n]
        mode = self.display_var.get()

        if mode == "Amplitude (dB)":
            y_data = 20 * np.log10(np.abs(s_param))
        else:
            y_data = np.angle(s_param, deg=True)

        y_min, y_max = np.min(y_data), np.max(y_data)
        margin = 0.1 * (y_max - y_min)
        self.y_slider_min.config(from_=y_min - margin, to=y_max + margin)
        self.y_slider_max.config(from_=y_min - margin, to=y_max + margin)
        self.y_min.set(y_min - margin)
        self.y_max.set(y_max + margin)

    def export_csv(self):
        if not self.network:
            return

        mode = self.display_var.get()
        freqs = self.network.f / 1e9  # GHz
        s_params = self.network.s  # shape: (freqs, 2, 2)

        if mode == "Amplitude (dB)":
            s11 = 20 * np.log10(np.abs(s_params[:, 0, 0]))
            s12 = 20 * np.log10(np.abs(s_params[:, 0, 1]))
            s21 = 20 * np.log10(np.abs(s_params[:, 1, 0]))
            s22 = 20 * np.log10(np.abs(s_params[:, 1, 1]))
            headers = ["Fréquence (GHz)", "S11 (dB)", "S12 (dB)", "S21 (dB)", "S22 (dB)"]
        else:
            s11 = np.angle(s_params[:, 0, 0], deg=True)
            s12 = np.angle(s_params[:, 0, 1], deg=True)
            s21 = np.angle(s_params[:, 1, 0], deg=True)
            s22 = np.angle(s_params[:, 1, 1], deg=True)
            headers = ["Fréquence (GHz)", "S11 (deg)", "S12 (deg)", "S21 (deg)", "S22 (deg)"]

        filepath = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV files", "*.csv")],
                                                title="Exporter les données")
        if not filepath:
            return

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            for i in range(len(freqs)):
                writer.writerow([f"{freqs[i]:.6f}", f"{s11[i]:.4f}", f"{s12[i]:.4f}",
                                 f"{s21[i]:.4f}", f"{s22[i]:.4f}"])

    def update_plot(self, event=None, reset_range=False):
        if not self.network:
            return

        if reset_range:
            self.set_slider_ranges()

        for widget in self.canvas_frame.winfo_children():
            widget.destroy()

        fig, ax = plt.subplots(figsize=(6, 4), dpi=100)

        trace = self.trace_var.get()
        m, n = int(trace[1]) - 1, int(trace[2]) - 1
        freqs = self.network.f
        s_param = self.network.s[:, m, n]
        mode = self.display_var.get()

        if mode == "Amplitude (dB)":
            y_data = 20 * np.log10(np.abs(s_param))
            ax.set_ylabel(f"|{trace}| (dB)")
        else:
            y_data = np.angle(s_param, deg=True)
            ax.set_ylabel(f"Phase {trace} (deg)")

        x_data = freqs / 1e9  # GHz
        self.x_data = freqs  # Hz pour survol/export
        self.y_data = y_data

        mask = (x_data >= self.freq_min.get()) & (x_data <= self.freq_max.get())
        x_plot = x_data[mask]
        y_plot = y_data[mask]

        ax.plot(x_plot, y_plot, label=trace)
        ax.set_xlim(self.freq_min.get(), self.freq_max.get())
        ax.set_ylim(self.y_min.get(), self.y_max.get())
        ax.set_xlabel("Fréquence (GHz)")
        ax.set_title(f"{trace} - {mode}")
        ax.grid(True)
        ax.legend()

        self.canvas = FigureCanvasTkAgg(fig, master=self.canvas_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        plt.close(fig)  # <- empêche l'accumulation de figures en mémoire

        self.hover_annotation = ax.annotate("", xy=(0, 0), xytext=(15, 15), textcoords="offset points",
                                            bbox=dict(boxstyle="round", fc="w"),
                                            arrowprops=dict(arrowstyle="->"))
        self.hover_annotation.set_visible(False)

        def on_motion(event):
            if event.inaxes != ax:
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
                return

            x = event.xdata
            idx = np.abs(x_data - x).argmin()
            x_val = x_data[idx]
            y_val = y_data[idx]
            self.hover_annotation.xy = (x_val, y_val)
            self.hover_annotation.set_text(f"{x_val:.3f} GHz\\n{y_val:.2f}")
            self.hover_annotation.set_visible(True)
            self.canvas.draw_idle()

        self.canvas.mpl_connect("motion_notify_event", on_motion)

if __name__ == "__main__":
    root = tk.Tk()
    app = S2PViewerApp(root)
    root.mainloop()