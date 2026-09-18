"""
Conversion des parametres S en courbes tracables, selon le format choisi.

Aucun code d'interface ici : une courbe est un ``Trace`` (x, y, etiquettes).
La vue graphique se contente de les dessiner, ce qui permet de changer de
format sans retoucher le trace, et de tester les conversions sans fenetre.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from afr import reflect as afr_reflect

# Parametres S disponibles : nom -> (ligne, colonne)
PARAMETERS = {
    "S11": (0, 0),
    "S21": (1, 0),
    "S12": (0, 1),
    "S22": (1, 1),
}

REFLECTION_PARAMETERS = ("S11", "S22")


@dataclass
class Trace:
    """Une courbe prete a dessiner."""

    x: np.ndarray
    y: np.ndarray
    label: str
    x_label: str = "Frequency (GHz)"
    y_label: str = "dB"
    log_x_allowed: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class Format:
    """Un mode d'affichage : comment convertir, et comment nommer les axes."""

    key: str
    title: str
    y_label: str
    log_x_allowed: bool = True
    equal_aspect: bool = False


FORMATS = [
    Format("db", "Magnitude (dB)", "Magnitude (dB)"),
    Format("phase", "Phase (deg)", "Phase (deg)"),
    Format("phase_unwrapped", "Phase deroulee (deg)", "Phase (deg)"),
    Format("group_delay", "Temps de propagation de groupe", "Group delay (ns)"),
    Format("vswr", "ROS (VSWR)", "VSWR"),
    Format("real", "Partie reelle", "Re{S}"),
    Format("imag", "Partie imaginaire", "Im{S}"),
    Format("real_imag", "Reel et imaginaire", "S"),
    Format("smith", "Abaque de Smith", "Im{S}", log_x_allowed=False, equal_aspect=True),
    Format("impulse", "Reponse impulsionnelle", "|h(t)|", log_x_allowed=False),
    Format("step", "Reponse en echelon (TDR)", "Impedance (ohm)", log_x_allowed=False),
]

FORMAT_BY_KEY = {fmt.key: fmt for fmt in FORMATS}


def _db(values) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(values), 1e-15))


def group_delay(freq, values) -> np.ndarray:
    """-d(phase)/d(omega), en nanosecondes."""

    phase = np.unwrap(np.angle(values))
    return -np.gradient(phase, 2 * np.pi * np.asarray(freq, dtype=float)) * 1e9


def vswr(values) -> np.ndarray:
    magnitude = np.clip(np.abs(values), 0.0, 0.999999)
    return (1.0 + magnitude) / (1.0 - magnitude)


def impulse_and_step(freq, values):
    """
    Reponse impulsionnelle et reponse en echelon, avec le meme traitement
    que l'extraction (grille uniforme, passe-bas ou passe-bande selon la
    bande mesuree). L'echelon n'existe qu'en presence du continu.
    """

    _, td = afr_reflect.prepare(np.asarray(freq, dtype=float),
                                np.asarray(values, dtype=complex))

    keep = td.t <= td.span / 2
    time_ps = td.t[keep] * 1e12
    impulse = np.abs(td.h[keep])

    step = None
    if td.mode == "lowpass":
        order = np.argsort(td.t_sym, kind="stable")
        cumulative = np.cumsum(np.real(td.h[order]))
        sorted_time = td.t_sym[order]
        positive = sorted_time >= 0.0
        step = (sorted_time[positive] * 1e12,
                np.clip(cumulative[positive], -0.999, 0.999))

    return time_ps, impulse, step, td


def build_traces(networks, parameters, format_key: str, z0: float = 50.0) -> list:
    """
    ``networks``   : liste de (etiquette, reseau scikit-rf).
    ``parameters`` : noms de parametres, par exemple ('S11', 'S21').
    Retourne la liste des ``Trace`` a dessiner.
    """

    fmt = FORMAT_BY_KEY.get(format_key, FORMAT_BY_KEY["db"])
    traces = []

    for label, network in networks:
        if network is None:
            continue

        freq = np.asarray(network.f, dtype=float)
        ghz = freq / 1e9

        for name in parameters:
            row, column = PARAMETERS.get(name, (0, 0))
            if row >= network.nports or column >= network.nports:
                continue

            values = network.s[:, row, column]
            title = f"{label} {name}"

            if format_key == "db":
                traces.append(Trace(ghz, _db(values), title, y_label=fmt.y_label))

            elif format_key == "phase":
                traces.append(Trace(ghz, np.degrees(np.angle(values)), title,
                                    y_label=fmt.y_label))

            elif format_key == "phase_unwrapped":
                traces.append(Trace(ghz, np.degrees(np.unwrap(np.angle(values))), title,
                                    y_label=fmt.y_label))

            elif format_key == "group_delay":
                traces.append(Trace(ghz, group_delay(freq, values), title,
                                    y_label=fmt.y_label))

            elif format_key == "vswr":
                if name not in REFLECTION_PARAMETERS:
                    continue
                traces.append(Trace(ghz, vswr(values), title, y_label=fmt.y_label))

            elif format_key == "real":
                traces.append(Trace(ghz, np.real(values), title, y_label=fmt.y_label))

            elif format_key == "imag":
                traces.append(Trace(ghz, np.imag(values), title, y_label=fmt.y_label))

            elif format_key == "real_imag":
                traces.append(Trace(ghz, np.real(values), f"{title} Re", y_label=fmt.y_label))
                traces.append(Trace(ghz, np.imag(values), f"{title} Im", y_label=fmt.y_label))

            elif format_key == "smith":
                traces.append(Trace(np.real(values), np.imag(values), title,
                                    x_label="Re{S}", y_label="Im{S}",
                                    log_x_allowed=False,
                                    extra={"frequency_ghz": ghz}))

            elif format_key in ("impulse", "step"):
                try:
                    time_ps, impulse, step, _ = impulse_and_step(freq, values)
                except Exception:
                    continue

                if format_key == "impulse":
                    traces.append(Trace(time_ps, impulse, title,
                                        x_label="Time (ps)", y_label="|h(t)|",
                                        log_x_allowed=False))
                elif step is not None:
                    step_time, rho = step
                    impedance = z0 * (1.0 + rho) / (1.0 - rho)
                    traces.append(Trace(step_time, impedance, title,
                                        x_label="Time (ps)", y_label="Impedance (ohm)",
                                        log_x_allowed=False))

    return traces


def difference(first: Trace, second: Trace) -> Trace:
    """
    Ecart entre deux courbes, sur la grille de la premiere. Sert a comparer
    une extraction a sa reference sans quitter le graphe.
    """

    y = np.interp(first.x, second.x, second.y)
    return Trace(first.x, first.y - y, f"{first.label} - {second.label}",
                 x_label=first.x_label, y_label=f"delta {first.y_label}")


def to_csv(traces, handle):
    """Exporte les courbes en CSV : une paire de colonnes par courbe."""

    if not traces:
        handle.write("")
        return

    header = []
    for trace in traces:
        header += [f"{trace.label} [{trace.x_label}]", f"{trace.label} [{trace.y_label}]"]
    handle.write(",".join(header) + "\n")

    longest = max(len(trace.x) for trace in traces)
    for index in range(longest):
        row = []
        for trace in traces:
            if index < len(trace.x):
                row += [f"{trace.x[index]:.9g}", f"{trace.y[index]:.9g}"]
            else:
                row += ["", ""]
        handle.write(",".join(row) + "\n")
