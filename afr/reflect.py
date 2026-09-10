"""
S1P -> S2P : extraction d'un fixture a partir de sa mesure 1 port terminee
par un OPEN ou un SHORT.

Modele (Gamma_L = +1 OPEN, -1 SHORT) :

    Gamma_mes = S11 + S21^2 * Gamma_L / (1 - S22 * Gamma_L)

Dans le domaine temporel :
  - la reflexion proche (t ~ 0) donne S11 ;
  - la reflexion lointaine (t ~ 2 tau) vaut, au premier ordre,
    (1 - S11^2) * Gamma_L * P^2 avec P = propagation aller.
    Comme S21 (premier passage) = (1 - S11^2) * P, on a

        S21^2 = Gamma_far / Gamma_L * (1 - S11^2)

    C'est la relation utilisee pour le 2x-thru (s21_2x * (1 - s11_half^2)).

Limite : une mesure OPEN/SHORT ne permet pas d'identifier S22 (cote DUT)
independamment ; le fixture est suppose symetrique (S22 = S11) et
reciproque (S12 = S21). Avec OPEN et SHORT, la demi-somme et la
demi-difference des deux mesures separent proprement S11 et S21^2 et
fournissent un controle de coherence.
"""

from __future__ import annotations

import logging

import numpy as np
import skrf as rf

from . import metrics
from . import signal as sig
from .models import FixtureResult

log = logging.getLogger(__name__)

TINY = 1e-20


def gamma_load(kind) -> float:
    """+1 pour un OPEN, -1 pour un SHORT ; ``kind`` = 'OPEN', 'SHORT_A', chemin..."""

    label = str(kind).upper()
    if "SHORT" in label:
        return -1.0
    if "OPEN" in label:
        return 1.0
    raise ValueError(f"Standard de reflexion inconnu : {kind!r} (OPEN ou SHORT attendu)")


def two_port(f, s11, s21, s12, s22, z0: float = 50.0) -> rf.Network:
    s = np.zeros((len(f), 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 0, 1] = s12
    s[:, 1, 0] = s21
    s[:, 1, 1] = s22
    return rf.Network(frequency=rf.Frequency.from_f(np.asarray(f, float), unit="hz"),
                      s=s, z0=z0)


def _gates(td: sig.TimeDomain, t_far: float):
    """Fenetres proche (S11) et lointaine (S21^2) a partir du pic lointain."""

    gate_half = min(max(7 * td.tres, 0.15 * t_far), 0.6 * t_far)
    t_split = max(2 * td.tres, 0.5 * (t_far - gate_half))
    g_far = sig.gate_around(td, t_far, gate_half)
    g_near = sig.gate_near(td, t_split)
    return g_near, g_far, dict(gate_center_ps=t_far * 1e12,
                               gate_half_ps=gate_half * 1e12,
                               near_split_ps=t_split * 1e12)


def _finish(f, fu, S11u, S21u, gamma_for_tdr, z0, method, quality, interp_method):
    s11 = sig.resample(f, fu, S11u)
    s21 = sig.resample(f, fu, S21u)

    network = two_port(f, s11, s21, s21, s11, z0)

    delay = metrics.delay_from_phase(fu, S21u)
    if not np.isfinite(delay) or delay <= 0:
        delay = quality["gate_center_ps"] * 1e-12 / 2.0

    impedance = metrics.tdr_impedance(f, gamma_for_tdr, delay, z0,
                                      interp_method=interp_method)

    quality = dict(quality)
    quality["delay_peak_ps"] = quality["gate_center_ps"] / 2.0
    quality.update(metrics.quality_report(network.s))

    return FixtureResult(
        network=network,
        impedance_ohm=impedance,
        delay_ps=delay * 1e12,
        method=method,
        quality=quality,
    )


def fixture_from_reflect(f, gamma, load="OPEN", z0: float = 50.0,
                         interp_method: str = "Linear") -> FixtureResult:
    """
    Fixture 2 ports a partir d'une seule mesure 1 port (OPEN ou SHORT).

    ``load`` : 'OPEN' / 'SHORT' (ou une cle / un nom de fichier les contenant).
    """

    gl = gamma_load(load)
    f = np.asarray(f, dtype=float)
    gamma = np.asarray(gamma, dtype=complex)

    fu, X = sig.dc_uniform_grid(f, gamma, interp_method)
    td = sig.to_time_domain(fu, X)

    t_far = sig.find_peak(td)
    g_near, g_far, quality = _gates(td, t_far)

    G_far = sig.gate_to_freq(td, g_far)
    S11u = sig.gate_to_freq(td, g_near)

    S21sq = (G_far / gl) * (1.0 - S11u * S11u)
    S21sq = np.where(np.abs(S21sq) < TINY, TINY + 0j, S21sq)
    S21u = sig.complex_sqrt_continuous(S21sq, fu)

    quality["sqrt_residual"] = float(np.max(np.abs(S21u * S21u - S21sq)))
    quality["load"] = "SHORT" if gl < 0 else "OPEN"

    method = "reflect_short" if gl < 0 else "reflect_open"
    return _finish(f, fu, S11u, S21u, gamma, z0, method, quality, interp_method)


def fixture_from_open_short(f, gamma_open, gamma_short, z0: float = 50.0,
                            interp_method: str = "Linear") -> FixtureResult:
    """
    Fixture 2 ports a partir des mesures OPEN et SHORT du meme fixture.

        M = (Gamma_o + Gamma_s) / 2  ->  partie proche = S11 (les reflexions
                                          lointaines +/- s'annulent)
        D = (Gamma_o - Gamma_s) / 2  ->  partie lointaine = S21^2 / (1 - S11^2)
                                          (la reflexion proche s'annule)

    Le controle de coherence compare les S21 obtenus separement avec l'OPEN
    et avec le SHORT (ecart moyen en dB et en degres sur la bande utile).
    """

    f = np.asarray(f, dtype=float)
    gamma_open = np.asarray(gamma_open, dtype=complex)
    gamma_short = np.asarray(gamma_short, dtype=complex)

    if gamma_open.shape != gamma_short.shape:
        raise ValueError("OPEN et SHORT doivent partager la meme grille de frequence.")

    M = 0.5 * (gamma_open + gamma_short)
    D = 0.5 * (gamma_open - gamma_short)

    fu, Mu = sig.dc_uniform_grid(f, M, interp_method)
    _, Du = sig.dc_uniform_grid(f, D, interp_method)

    td_M = sig.to_time_domain(fu, Mu)
    td_D = sig.to_time_domain(fu, Du)

    t_far = sig.find_peak(td_D)
    g_near, g_far, quality = _gates(td_D, t_far)

    S11u = sig.gate_to_freq(td_M, g_near)
    D_far = sig.gate_to_freq(td_D, g_far)

    S21sq = D_far * (1.0 - S11u * S11u)
    S21sq = np.where(np.abs(S21sq) < TINY, TINY + 0j, S21sq)
    S21u = sig.complex_sqrt_continuous(S21sq, fu)

    quality["sqrt_residual"] = float(np.max(np.abs(S21u * S21u - S21sq)))
    quality["load"] = "OPEN+SHORT"

    # Coherence OPEN / SHORT : les deux mesures seules doivent donner le meme S21
    try:
        r_open = fixture_from_reflect(f, gamma_open, "OPEN", z0, interp_method)
        r_short = fixture_from_reflect(f, gamma_short, "SHORT", z0, interp_method)
        so = r_open.network.s[:, 1, 0]
        ss = r_short.network.s[:, 1, 0]
        band = (f >= 0.1 * f[-1]) & (f <= 0.6 * f[-1])
        ratio = so[band] / np.where(np.abs(ss[band]) < TINY, TINY, ss[band])
        quality["open_short_mag_db"] = float(np.mean(np.abs(20 * np.log10(np.abs(ratio)))))
        quality["open_short_phase_deg"] = float(np.mean(np.abs(np.degrees(np.angle(ratio)))))
        quality["delay_open_ps"] = r_open.delay_ps
        quality["delay_short_ps"] = r_short.delay_ps
    except Exception as error:  # pragma: no cover - controle optionnel
        log.warning("Controle OPEN/SHORT impossible : %s", error)

    # Impedance TDR sur la demi-somme (reflexion lointaine annulee)
    return _finish(f, fu, S11u, S21u, M, z0, "reflect_open_short", quality, interp_method)
