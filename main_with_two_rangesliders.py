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
        self.trace_box.bind("<<ComboboxSelected>>", self.update_plot)

        self.display_var = tk.StringVar(value="Amplitude (dB)")
        self.display_box = ttk.Combobox(self.control_bar, textvariable=self.display_var, state="readonly",
                                        values=["Amplitude (dB)", "Phase (deg)"])
        self.display_box.pack(side=tk.LEFT, padx=5)
        self.display_box.bind("<<ComboboxSelected>>", self.update_plot)

        self.export_button = tk.Button(self.control_bar, text="💾 Export", command=self.export_csv)
        self.export_button.pack(side=tk.RIGHT, padx=10)

        self.canvas_frame = tk.Frame(self.plot_control_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.slider_frame = tk.Frame(self.plot_control_frame)
        self.slider_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)

        # Sliders classiques Tkinter pour fréquence
        self.freq_slider_min = tk.Scale(self.slider_frame, label="Fréquence min (Hz)", orient=tk.HORIZONTAL,
                                        variable=self.freq_min, command=lambda x: self.update_plot())
        self.freq_slider_min.pack(fill=tk.X)

        self.freq_slider_max = tk.Scale(self.slider_frame, label="Fréquence max (Hz)", orient=tk.HORIZONTAL,
                                        variable=self.freq_max, command=lambda x: self.update_plot())
        self.freq_slider_max.pack(fill=tk.X)

        # Sliders classiques Tkinter pour amplitude / phase
        self.y_slider_min = tk.Scale(self.slider_frame, label="Y min", orient=tk.HORIZONTAL,
                                     variable=self.y_min, command=lambda x: self.update_plot())
        self.y_slider_min.pack(fill=tk.X)

        self.y_slider_max = tk.Scale(self.slider_frame, label="Y max", orient=tk.HORIZONTAL,
                                     variable=self.y_max, command=lambda x: self.update_plot())
        self.y_slider_max.pack(fill=tk.X)

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
        freqs = self.network.f
        self.freq_slider_min.config(from_=freqs.min(), to=freqs.max())
        self.freq_slider_max.config(from_=freqs.min(), to=freqs.max())
        self.freq_min.set(freqs.min())
        self.freq_max.set(freqs.max())

        trace = self.trace_var.get()
        m, n = int(trace[1]) - 1, int(trace[2]) - 1
        s_param = self.network.s[:, m, n]

        if self.display_var.get() == "Amplitude (dB)":
            y_data = 20 * np.log10(np.abs(s_param))
        else:
            y_data = np.angle(s_param, deg=True)

        y_min, y_max = y_data.min(), y_data.max()
        margin = 0.1 * (y_max - y_min)
        self.y_slider_min.config(from_=y_min - margin, to=y_max + margin)
        self.y_slider_max.config(from_=y_min - margin, to=y_max + margin)
        self.y_min.set(y_min - margin)
        self.y_max.set(y_max + margin)

    def export_csv(self):
        if self.x_data is None or self.y_data is None:
            return

        filepath = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV files", "*.csv")],
                                                title="Exporter les données")
        if not filepath:
            return

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Frequency (Hz)", "Value"])
            for x, y in zip(self.x_data, self.y_data):
                writer.writerow([x, y])

    def update_plot(self, event=None):
        if not self.network:
            return

        for widget in self.canvas_frame.winfo_children():
            widget.destroy()

        fig, ax = plt.subplots(figsize=(6, 4), dpi=100)

        trace = self.trace_var.get()
        m, n = int(trace[1]) - 1, int(trace[2]) - 1
        freqs = self.network.f
        s_param = self.network.s[:, m, n]

        if self.display_var.get() == "Amplitude (dB)":
            y_data = 20 * np.log10(np.abs(s_param))
            ax.set_ylabel(f"|{trace}| (dB)")
        else:
            y_data = np.angle(s_param, deg=True)
            ax.set_ylabel(f"Phase {trace} (deg)")

        x_data = freqs
        self.x_data = x_data
        self.y_data = y_data

        mask = (x_data >= self.freq_min.get()) & (x_data <= self.freq_max.get())
        x_plot = x_data[mask]
        y_plot = y_data[mask]

        ax.plot(x_plot, y_plot, label=trace)
        ax.set_xlim(self.freq_min.get(), self.freq_max.get())
        ax.set_ylim(self.y_min.get(), self.y_max.get())
        ax.set_xlabel("Fréquence (Hz)")
        ax.set_title(f"{trace} - {self.display_var.get()}")
        ax.grid(True)
        ax.legend()

        self.canvas = FigureCanvasTkAgg(fig, master=self.canvas_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

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
            self.hover_annotation.set_text(f"{x_val:.2e} Hz\\n{y_val:.2f}")
            self.hover_annotation.set_visible(True)
            self.canvas.draw_idle()

        self.canvas.mpl_connect("motion_notify_event", on_motion)

# Lancement
if __name__ == "__main__":
    root = tk.Tk()
    app = S2PViewerApp(root)
    root.mainloop()