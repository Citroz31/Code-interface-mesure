"""
S1P -> S2P : extraction d'un fixture a partir de sa mesure 1 port terminee
par un OPEN ou un SHORT.

Modele physique (une discontinuite)
-----------------------------------
Le fixture est vu comme une transition d'entree de coefficient de reflexion
G1 suivie d'une propagation aller P = exp(-gamma * l) :

    S11 = G1 (1 - P^2) / (1 - G1^2 P^2)
    S21 = (1 - G1^2) P / (1 - G1^2 P^2)

Termine par un standard de coefficient GL (+1 OPEN, -1 SHORT), il mesure

    Gamma = G1 + (1 - G1^2) P^2 GL / (1 + G1 P^2 GL)

Cette relation s'inverse exactement (transformation de Moebius) :

    P^2 GL = (Gamma - G1) / (1 - G1 Gamma)                         (1)

Retirer la transition d'entree ne demande donc aucune approximation : les
reflexions multiples a l'interieur du fixture sont prises en compte, et le
residu (1) ne contient plus qu'un seul echo, a t = 2 tau, que l'on peut
fenetrer sans rien perdre du signal utile.

Determination de G1
-------------------
* Un seul standard : G1 est la reflexion proche, obtenue en fenetrant la
  reponse impulsionnelle autour de t = 0.
* OPEN et SHORT : P^2 est commun aux deux mesures et GL change de signe, donc
  (1) donne directement G1 sans aucun fenetrage, par la racine de module < 1 de

    (Go + Gs) G1^2 - 2 (1 + Go Gs) G1 + (Go + Gs) = 0                (2)

  C'est la methode la plus precise : S11 et S21 sont exacts sur un fixture
  conforme au modele.

Limites : le modele suppose une seule discontinuite dominante (connecteur ou
transition d'entree) suivie d'une ligne uniforme, et un fixture symetrique
(S22 = S11) et reciproque (S12 = S21). Un fixture a plusieurs discontinuites
fortes demande le 2x-thru.
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
MODELS = ("single_discontinuity", "first_order")


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


def _safe(x, floor: float = 1e-12):
    x = np.asarray(x, dtype=complex)
    return np.where(np.abs(x) < floor, floor + 0j, x)


# ---------------------------------------------------------------------------
# Domaine temporel : choix du mode et fenetres
# ---------------------------------------------------------------------------

def prepare(f, gamma, interp_method: str = "Linear"):
    """
    Grille uniforme + reponse impulsionnelle, en choisissant le mode :
    lowpass (grille depuis DC) si la mesure commence assez bas, bandpass
    (enveloppe complexe, sans hypothese sur les basses frequences) sinon.
    """

    f = np.asarray(f, dtype=float)
    if f[0] <= sig.LOWPASS_MAX_START * f[-1]:
        fu, X = sig.dc_uniform_grid(f, gamma, interp_method)
        return fu, sig.to_time_domain(fu, X, mode="lowpass")

    fu, X = sig.uniform_grid(f, gamma, interp_method)
    return fu, sig.to_time_domain(fu, X, mode="bandpass")


def _sqrt(x, fu, td: sig.TimeDomain, t_far: float):
    """Racine continue ; en passe-bande la branche est ancree sur le delai du pic."""

    if td.mode == "bandpass":
        return sig.complex_sqrt_continuous(x, fu, anchor_delay=t_far / 2.0)
    return sig.complex_sqrt_continuous(x, fu)


def _gates(td: sig.TimeDomain, t_far: float):
    """
    Fenetres proche (autour de t = 0) et lointaine (autour de t_far).

    Les deux fenetres ne doivent pas se recouvrir : sur un fixture court
    devant la resolution temporelle (1 / bande), les demi-largeurs sont
    reduites et un avertissement est emis.
    """

    gate_half = min(max(7 * td.tres, 0.15 * t_far), 0.6 * t_far)
    t_split = max(2 * td.tres, 0.5 * (t_far - gate_half))

    quality = dict(gate_center_ps=t_far * 1e12,
                   time_span_ps=td.span * 1e12,
                   time_resolution_ps=td.tres * 1e12)

    overlap = t_split - (t_far - gate_half)
    if overlap > 0:
        # On partage l'ecart disponible : moitie pour chaque fenetre.
        shrink = 0.5 * overlap + 0.02 * t_far
        gate_half = max(gate_half - shrink, 0.2 * t_far)
        t_split = max(t_split - shrink, 0.1 * t_far)
        message = (
            f"Fixture court devant la resolution temporelle "
            f"({td.tres * 1e12:.1f} ps pour un aller-retour de {t_far * 1e12:.1f} ps) : "
            f"fenetres proche et lointaine reduites. Elargir la bande de mesure "
            f"pour separer les deux reflexions."
        )
        log.warning(message)
        quality["warning"] = message

    quality["gate_half_ps"] = gate_half * 1e12
    quality["near_split_ps"] = t_split * 1e12

    span_warning = sig.check_time_span(td, t_far + gate_half)
    if span_warning:
        quality["warning"] = span_warning

    return sig.gate_near(td, t_split), sig.gate_around(td, t_far, gate_half), quality


# ---------------------------------------------------------------------------
# Modele a une discontinuite
# ---------------------------------------------------------------------------

def deembed_input(gamma, g1):
    """
    Retire la transition d'entree : retourne ``P^2 * GL`` d'apres (1).
    Exact, toutes reflexions multiples comprises.
    """

    gamma = np.asarray(gamma, dtype=complex)
    g1 = np.asarray(g1, dtype=complex)
    return (gamma - g1) / _safe(1.0 - g1 * gamma)


def gamma1_from_open_short(gamma_open, gamma_short):
    """
    Coefficient de reflexion de la transition d'entree resolu d'apres (2),
    sans aucun fenetrage. La racine retenue est celle de module < 1.
    """

    o = np.asarray(gamma_open, dtype=complex)
    s = np.asarray(gamma_short, dtype=complex)

    total = o + s
    product = o * s

    disc = np.sqrt((1.0 + product) ** 2 - total ** 2)
    denominator = _safe(total)

    r1 = ((1.0 + product) + disc) / denominator
    r2 = ((1.0 + product) - disc) / denominator

    g1 = np.where(np.abs(r1) <= np.abs(r2), r1, r2)

    # total ~ 0 : fixture parfaitement adapte a l'entree
    return np.where(np.abs(total) < 1e-9, 0.0 + 0j, g1)


def network_from_model(g1, propagation):
    """S11 et S21 du fixture a partir de G1 et de la propagation aller P."""

    g1 = np.asarray(g1, dtype=complex)
    p = np.asarray(propagation, dtype=complex)

    denominator = _safe(1.0 - g1 * g1 * p * p)
    s11 = g1 * (1.0 - p * p) / denominator
    s21 = (1.0 - g1 * g1) * p / denominator
    return s11, s21


def _gate_echo(fu, x, t_far: float, td_ref: sig.TimeDomain, half_fraction: float = 0.6):
    """
    Fenetre le residu (1) autour de son unique echo a ``t_far``. Large par
    construction : le residu ne contient plus de reflexions multiples, la
    fenetre ne sert qu'a rejeter le bruit hors de la zone utile.
    """

    td = sig.to_time_domain(fu, x, mode=td_ref.mode)

    half = max(7 * td.tres, half_fraction * t_far)
    return sig.gate_to_freq(td, sig.gate_around(td, t_far, half))


# ---------------------------------------------------------------------------
# Assemblage du resultat
# ---------------------------------------------------------------------------

def _finish(f, fu, s11u, s21u, gamma_for_tdr, z0, method, quality, interp_method,
            smooth_points: int = 0, enforce_passivity: bool = True):
    s11 = sig.resample(f, fu, s11u)
    s21 = sig.resample(f, fu, s21u)

    if smooth_points and smooth_points > 2:
        s21 = sig.smooth_db_phase(s21, smooth_points)
        s11 = sig.smooth_db_phase(s11, smooth_points)
        quality["smooth_points"] = int(smooth_points)

    if enforce_passivity:
        s21, clamped = sig.clamp_passive(s21, s11)
        quality["clamped_points"] = clamped
        if clamped:
            log.warning("%d point(s) de |S21| au-dessus de la limite passive ramenes "
                        "a cette limite (bruit ou fenetre trop etroite).", clamped)

    network = two_port(f, s11, s21, s21, s11, z0)

    delay = metrics.delay_from_phase(fu, s21u)
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


# ---------------------------------------------------------------------------
# Extraction a partir d'un seul standard
# ---------------------------------------------------------------------------

def fixture_from_reflect(f, gamma, load="OPEN", z0: float = 50.0,
                         interp_method: str = "Linear", smooth_points: int = 0,
                         enforce_passivity: bool = True,
                         model: str = "single_discontinuity") -> FixtureResult:
    """
    Fixture 2 ports a partir d'une seule mesure 1 port (OPEN ou SHORT).

    ``load``             : 'OPEN' / 'SHORT' (ou une cle / un nom de fichier).
    ``model``            : 'single_discontinuity' (defaut, exact apres G1) ou
                           'first_order' (ancienne formule, reflexions
                           multiples negligees).
    ``smooth_points``    : lissage Savitzky-Golay (dB et phase), 0 = aucun.
    ``enforce_passivity``: borne |S21| a la limite passive.
    """

    if model not in MODELS:
        raise ValueError(f"Modele inconnu : {model!r} (attendu : {MODELS})")

    gl = gamma_load(load)
    f = np.asarray(f, dtype=float)
    gamma = np.asarray(gamma, dtype=complex)

    fu, td = prepare(f, gamma, interp_method)
    gamma_u = sig.resample(fu, f, gamma)

    t_far = sig.find_peak(td)
    g_near, g_far, quality = _gates(td, t_far)
    quality["mode"] = td.mode
    quality["model"] = model
    quality["load"] = "SHORT" if gl < 0 else "OPEN"

    g1 = sig.gate_to_freq(td, g_near)

    if model == "single_discontinuity":
        # Transition d'entree retiree exactement, puis fenetrage de l'echo unique
        residual = deembed_input(gamma_u, g1) / gl
        p_squared = _gate_echo(fu, residual, t_far, td)
        propagation = _sqrt(_safe(p_squared, TINY), fu, td, t_far)
        s11u, s21u = network_from_model(g1, propagation)
        quality["model_residual"] = float(
            np.max(np.abs(propagation * propagation - p_squared))
        )
    else:
        far = sig.gate_to_freq(td, g_far)
        s21_squared = _safe((far / gl) * (1.0 - g1 * g1), TINY)
        s21u = _sqrt(s21_squared, fu, td, t_far)
        s11u = g1
        quality["sqrt_residual"] = float(np.max(np.abs(s21u * s21u - s21_squared)))

    method = ("reflect_short" if gl < 0 else "reflect_open") + (
        "" if model == "single_discontinuity" else "_first_order")

    return _finish(f, fu, s11u, s21u, gamma, z0, method, quality, interp_method,
                   smooth_points, enforce_passivity)


# ---------------------------------------------------------------------------
# Extraction a partir des deux standards
# ---------------------------------------------------------------------------

def fixture_from_open_short(f, gamma_open, gamma_short, z0: float = 50.0,
                            interp_method: str = "Linear", smooth_points: int = 0,
                            enforce_passivity: bool = True,
                            model: str = "single_discontinuity") -> FixtureResult:
    """
    Fixture 2 ports a partir des mesures OPEN et SHORT du meme fixture.

    Avec le modele 'single_discontinuity', G1 est resolu algebriquement par
    (2) : aucun fenetrage n'intervient dans la determination de S11, et S21
    decoule de la transformation exacte (1). C'est la methode la plus
    precise des trois (OPEN seul, SHORT seul, OPEN + SHORT).
    """

    if model not in MODELS:
        raise ValueError(f"Modele inconnu : {model!r} (attendu : {MODELS})")

    f = np.asarray(f, dtype=float)
    gamma_open = np.asarray(gamma_open, dtype=complex)
    gamma_short = np.asarray(gamma_short, dtype=complex)

    if gamma_open.shape != gamma_short.shape:
        raise ValueError("OPEN et SHORT doivent partager la meme grille de frequence.")

    if model == "first_order":
        return _open_short_first_order(f, gamma_open, gamma_short, z0, interp_method,
                                       smooth_points, enforce_passivity)

    fu, td_open = prepare(f, gamma_open, interp_method)

    open_u = sig.resample(fu, f, gamma_open)
    short_u = sig.resample(fu, f, gamma_short)

    g1 = gamma1_from_open_short(open_u, short_u)

    # P^2 : moyenne des deux mesures deja corrigees du signe du standard
    p_squared_raw = 0.5 * (deembed_input(open_u, g1) - deembed_input(short_u, g1))

    td_p = sig.to_time_domain(fu, p_squared_raw, mode=td_open.mode)
    t_far = sig.find_peak(td_p)
    _, _, quality = _gates(td_p, t_far)

    p_squared = _gate_echo(fu, p_squared_raw, t_far, td_p)
    propagation = _sqrt(_safe(p_squared, TINY), fu, td_p, t_far)
    s11u, s21u = network_from_model(g1, propagation)

    quality["mode"] = td_p.mode
    quality["model"] = model
    quality["load"] = "OPEN+SHORT"
    quality["model_residual"] = float(np.max(np.abs(propagation * propagation - p_squared)))

    _open_short_consistency(f, gamma_open, gamma_short, z0, interp_method, quality)

    return _finish(f, fu, s11u, s21u, 0.5 * (gamma_open + gamma_short), z0,
                   "reflect_open_short", quality, interp_method,
                   smooth_points, enforce_passivity)


def _open_short_first_order(f, gamma_open, gamma_short, z0, interp_method,
                            smooth_points, enforce_passivity) -> FixtureResult:
    """Ancienne methode : demi-somme / demi-difference fenetrees."""

    mean = 0.5 * (gamma_open + gamma_short)
    difference = 0.5 * (gamma_open - gamma_short)

    fu, td_mean = prepare(f, mean, interp_method)
    _, td_diff = prepare(f, difference, interp_method)

    t_far = sig.find_peak(td_diff)
    g_near, g_far, quality = _gates(td_diff, t_far)

    s11u = sig.gate_to_freq(td_mean, g_near)
    far = sig.gate_to_freq(td_diff, g_far)

    s21_squared = _safe(far * (1.0 - s11u * s11u), TINY)
    s21u = _sqrt(s21_squared, fu, td_diff, t_far)

    quality["mode"] = td_diff.mode
    quality["model"] = "first_order"
    quality["load"] = "OPEN+SHORT"
    quality["sqrt_residual"] = float(np.max(np.abs(s21u * s21u - s21_squared)))

    _open_short_consistency(f, gamma_open, gamma_short, z0, interp_method, quality)

    return _finish(f, fu, s11u, s21u, mean, z0, "reflect_open_short_first_order",
                   quality, interp_method, smooth_points, enforce_passivity)


def _open_short_consistency(f, gamma_open, gamma_short, z0, interp_method, quality):
    """Ecart entre les S21 obtenus avec l'OPEN seul et avec le SHORT seul."""

    try:
        r_open = fixture_from_reflect(f, gamma_open, "OPEN", z0, interp_method,
                                      enforce_passivity=False)
        r_short = fixture_from_reflect(f, gamma_short, "SHORT", z0, interp_method,
                                       enforce_passivity=False)
        so = r_open.network.s[:, 1, 0]
        ss = r_short.network.s[:, 1, 0]

        span = f[-1] - f[0]
        band = (f >= f[0] + 0.1 * span) & (f <= f[0] + 0.6 * span)
        ratio = so[band] / _safe(ss[band], TINY)

        quality["open_short_mag_db"] = float(np.mean(np.abs(20 * np.log10(np.abs(ratio)))))
        quality["open_short_phase_deg"] = float(np.mean(np.abs(np.degrees(np.angle(ratio)))))
        quality["delay_open_ps"] = r_open.delay_ps
        quality["delay_short_ps"] = r_short.delay_ps
    except Exception as error:  # pragma: no cover - controle optionnel
        log.warning("Controle OPEN/SHORT impossible : %s", error)
