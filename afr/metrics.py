"""
Caracteristiques d'un fixture : delai, longueur, impedance TDR, qualite.
"""

from __future__ import annotations

import numpy as np

from . import signal as sig

C0 = 299_792_458.0   # m/s
EPS = 1e-12


# ---------------------------------------------------------------------------
# Delai de propagation (TDD / TTD)
# ---------------------------------------------------------------------------

def _band_mask(f, band):
    f = np.asarray(f, dtype=float)
    lo, hi = band
    span = f[-1] - f[0]
    mask = (f >= f[0] + lo * span) & (f <= f[0] + hi * span)
    if mask.sum() < 3:
        mask = np.ones_like(f, dtype=bool)
    return mask


def delay_from_phase(f, s21, band=(0.10, 0.60)) -> float:
    """
    Delai (s) = - pente de la phase deroulee de S21 / (2 pi), par regression
    lineaire sur ``band`` (fractions de la bande mesuree f[0] .. f[-1]). Estimateur par defaut :
    robuste au bruit haute frequence.
    """

    f = np.asarray(f, dtype=float)
    phase = np.unwrap(np.angle(np.asarray(s21, dtype=complex)))
    mask = _band_mask(f, band)
    slope = np.polyfit(f[mask], phase[mask], 1)[0]
    return float(-slope / (2.0 * np.pi))


def group_delay(f, s21) -> np.ndarray:
    """Retard de groupe (s) en fonction de la frequence."""

    f = np.asarray(f, dtype=float)
    phase = np.unwrap(np.angle(np.asarray(s21, dtype=complex)))
    return -np.gradient(phase, 2.0 * np.pi * f)


def delay_from_group(f, s21, band=(0.10, 0.60)) -> float:
    """Mediane du retard de groupe sur ``band`` (s)."""

    mask = _band_mask(f, band)
    return float(np.median(group_delay(f, s21)[mask]))


def delay_from_peak(f, s21, interp_method: str = "Linear") -> float:
    """Instant du pic de la reponse impulsionnelle de S21 (s), controle."""

    fu, xu = sig.dc_uniform_grid(f, s21, interp_method)
    td = sig.to_time_domain(fu, xu)
    return sig.find_peak(td, t_min=0.0)


def physical_length(delay_s: float, eps_r_eff: float = 1.0) -> float:
    """Longueur physique (m) = c * delai / sqrt(eps_r effectif)."""

    eps_r_eff = float(eps_r_eff) if eps_r_eff and eps_r_eff > 0 else 1.0
    return C0 * float(delay_s) / np.sqrt(eps_r_eff)


# ---------------------------------------------------------------------------
# Impedance
# ---------------------------------------------------------------------------

def impedance_from_reflection(gamma, z0: float = 50.0) -> np.ndarray:
    """Z = Z0 (1 + Gamma) / (1 - Gamma), avec garde-fou pres de Gamma = 1."""

    gamma = np.asarray(gamma, dtype=complex)
    denominator = 1.0 - gamma
    denominator = np.where(np.abs(denominator) < EPS, EPS + 0j, denominator)
    return z0 * (1.0 + gamma) / denominator


def impedance_from_gamma1(g1, z0: float = 50.0, band=(0.0, 1.0)) -> float:
    """
    Impedance caracteristique deduite de la reflexion proche G1 :

        Z = Z0 (1 + G1) / (1 - G1)

    Mediane de la partie reelle sur la portion ``band`` de la bande. Ne
    demande pas le continu : c'est l'estimateur utilise pour une mesure en
    bande, ou la reponse en echelon (TDR) n'est pas definie.
    """

    g1 = np.asarray(g1, dtype=complex)
    n = len(g1)
    lo = int(band[0] * (n - 1))
    hi = int(band[1] * (n - 1)) + 1

    window = g1[lo:hi]
    if len(window) < 3:
        window = g1

    z = impedance_from_reflection(window, z0)
    return float(np.median(np.real(z)))


def tdr_profile(f, gamma, z0: float = 50.0, interp_method: str = "Linear"):
    """
    Profil d'impedance TDR : reponse en echelon (integrale de la reponse
    impulsionnelle de Gamma) convertie en Z(t). L'axe ``t`` est le temps
    aller-retour ; seule la moitie sans repliement est retournee.
    """

    f = np.asarray(f, dtype=float)
    if f[0] > sig.LOWPASS_MAX_START * f[-1]:
        # Pas de DC dans la bande : la reponse en echelon n'est pas definie.
        return None, None

    fu, xu = sig.dc_uniform_grid(f, gamma, interp_method)
    td = sig.to_time_domain(fu, xu, mode="lowpass")

    # La reponse en echelon integre h depuis les temps negatifs : la moitie
    # de l'impulsion proche (t ~ 0) est repliee en fin de vecteur (t > span/2)
    # et serait perdue en integrant depuis t = 0.
    order = np.argsort(td.t_sym, kind="stable")
    t_sorted = td.t_sym[order]
    step = np.cumsum(td.h[order])

    keep = t_sorted >= 0.0
    step = np.clip(step[keep], -0.999, 0.999)

    z_t = z0 * (1.0 + step) / (1.0 - step)
    return t_sorted[keep], z_t


def tdr_impedance(f, gamma, delay_s: float, z0: float = 50.0,
                  band=(0.30, 0.70), interp_method: str = "Linear") -> float:
    """
    Impedance caracteristique (ohm) = mediane du profil TDR sur la portion
    ``band`` de l'aller-retour [0, 2 * delai] du fixture.
    """

    t, z_t = tdr_profile(f, gamma, z0, interp_method)
    if t is None:
        return float("nan")
    round_trip = 2.0 * float(delay_s)

    mask = (t >= band[0] * round_trip) & (t <= band[1] * round_trip)
    if mask.sum() < 3:
        tres = 1.0 / float(np.asarray(f, dtype=float)[-1])
        mask = (t >= 2 * tres) & (t <= max(4 * tres, round_trip))
    if mask.sum() == 0:
        mask = np.ones_like(t, dtype=bool)

    return float(np.median(np.real(z_t[mask])))


# ---------------------------------------------------------------------------
# Qualite d'un reseau
# ---------------------------------------------------------------------------

def max_singular_value(s) -> float:
    """Plus grande valeur singuliere de S sur toute la bande (passivite <= 1)."""

    s = np.asarray(s, dtype=complex)
    return float(np.max(np.linalg.svd(s, compute_uv=False)))


def reciprocity_error(s) -> float:
    s = np.asarray(s, dtype=complex)
    return float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])))


def symmetry_error(s) -> float:
    s = np.asarray(s, dtype=complex)
    return float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1])))


def quality_report(s) -> dict:
    """Indicateurs de qualite d'un reseau 2 ports (S de forme (n, 2, 2))."""

    s = np.asarray(s, dtype=complex)
    sigma = max_singular_value(s)
    return {
        "max_singular_value": sigma,
        "passive": bool(sigma <= 1.0 + 1e-6),
        "reciprocity_error": reciprocity_error(s),
        "symmetry_error": symmetry_error(s),
    }
