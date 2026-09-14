"""
Decoupage d'un 2x-thru (fixture A + fixture B) en deux demi-fixtures.

Methode temporelle :
  - S11 et S22 du 2x-thru sont fenetres autour de t = 0 (fenetre symetrique)
    pour ne garder que les reflexions internes a chaque demi-fixture ;
  - le delai total est lu sur le pic de la reponse impulsionnelle de S21 ;
  - S21_half = sqrt( S21_2x * (1 - S11_half * S22_half) ), racine continue
    dont la branche est fixee a DC.

Hypothese : le cote DUT de chaque demi-fixture (S22 de A, S11 de B) n'est
pas observable dans un 2x-thru bien raccorde ; il est pris egal a la
reflexion proche du cote oppose (fixture symetrique), comme dans la
version precedente de l'outil.
"""

from __future__ import annotations

import logging

import numpy as np
import skrf as rf

from . import metrics
from . import signal as sig
from .models import FixtureResult
from .reflect import prepare, two_port

log = logging.getLogger(__name__)

TINY = 1e-20


def port_swap(network: rf.Network) -> rf.Network:
    """Copie du reseau avec les ports 1 et 2 echanges."""

    swapped = network.copy()
    s = network.s.copy()
    out = np.zeros_like(s)
    out[:, 0, 0] = s[:, 1, 1]
    out[:, 1, 1] = s[:, 0, 0]
    out[:, 0, 1] = s[:, 1, 0]
    out[:, 1, 0] = s[:, 0, 1]
    swapped.s = out
    return swapped


def split_2x_thru(thru: rf.Network, interp_method: str = "Linear",
                  near_fraction: float = 0.8):
    """
    Decoupe ``thru`` (2 ports) en (demi_in, demi_out, info).

    ``demi_in``  : fixture A, port 1 cote VNA, port 2 cote DUT.
    ``demi_out`` : fixture B, port 1 cote DUT, port 2 cote VNA (port-swap).
    ``info``     : z1, z2 (ohm), delay1, delay2 (ps), delay_total_ps, qualite.
    """

    if thru.nports != 2:
        raise ValueError(f"Le 2x-thru doit avoir 2 ports ({thru.nports} trouves).")

    f = np.asarray(thru.f, dtype=float)
    z0 = float(np.real(np.asarray(thru.z0).flat[0]))

    s11 = thru.s[:, 0, 0]
    s21 = thru.s[:, 1, 0]
    s22 = thru.s[:, 1, 1]

    # Delai total : pic de la reponse impulsionnelle de S21
    fu, td21 = prepare(f, s21, interp_method)
    t_total = sig.find_peak(td21, t_min=0.0)

    # Reflexions proches de chaque cote
    _, td11 = prepare(f, s11, interp_method)
    _, td22 = prepare(f, s22, interp_method)

    t_gate = max(2 * td11.tres, near_fraction * t_total)
    g_near = sig.gate_near(td11, t_gate)

    s11_half = sig.resample(f, fu, sig.gate_to_freq(td11, g_near))
    s22_half = sig.resample(f, fu, sig.gate_to_freq(td22, g_near))

    # Transmission d'une demi-fixture
    rad = s21 * (1.0 - s11_half * s22_half)
    rad = np.where(np.abs(rad) < TINY, TINY + 0j, rad)
    if td21.mode == "bandpass":
        s21_half = sig.complex_sqrt_continuous(rad, f, anchor_delay=t_total / 2.0)
    else:
        s21_half = sig.complex_sqrt_continuous(rad, f)

    half_in = two_port(f, s11_half, s21_half, s21_half, s22_half, z0)
    half_in.name = "HALF_IN"
    half_out = port_swap(half_in)
    half_out.name = "HALF_OUT"

    delay_half = metrics.delay_from_phase(f, s21_half)
    if not np.isfinite(delay_half) or delay_half <= 0:
        delay_half = t_total / 2.0

    z1 = metrics.tdr_impedance(f, s11, delay_half, z0, interp_method=interp_method)
    z2 = metrics.tdr_impedance(f, s22, delay_half, z0, interp_method=interp_method)

    # Controle : demi x demi doit redonner le 2x-thru
    rebuilt = half_in ** half_out
    reconstruction = float(np.max(np.abs(rebuilt.s[:, 1, 0] - s21)))

    quality = {
        "mode": td21.mode,
        "delay_total_ps": t_total * 1e12,
        "near_gate_ps": t_gate * 1e12,
        "time_span_ps": td21.span * 1e12,
        "time_resolution_ps": td21.tres * 1e12,
        "sqrt_residual": float(np.max(np.abs(s21_half * s21_half - rad))),
        "reconstruction_s21": reconstruction,
    }
    warning = sig.check_time_span(td21, t_total + t_gate)
    if warning:
        quality["warning"] = warning
    quality.update(metrics.quality_report(half_in.s))

    info = {
        "z1": z1,
        "z2": z2,
        "delay1": delay_half * 1e12,
        "delay2": delay_half * 1e12,
        "delay_total_ps": t_total * 1e12,
        "quality": quality,
    }

    log.info("2x-thru : delai total %.1f ps, Z1 %.1f ohm, Z2 %.1f ohm, "
             "reconstruction S21 %.2e", t_total * 1e12, z1, z2, reconstruction)

    return half_in, half_out, info


def split_2x_thru_results(thru: rf.Network, interp_method: str = "Linear"):
    """Comme ``split_2x_thru`` mais retourne deux ``FixtureResult``."""

    half_in, half_out, info = split_2x_thru(thru, interp_method)
    q = info["quality"]
    return (
        FixtureResult(half_in, info["z1"], info["delay1"], "thru_split", dict(q)),
        FixtureResult(half_out, info["z2"], info["delay2"], "thru_split", dict(q)),
    )
