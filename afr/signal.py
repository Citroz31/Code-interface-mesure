"""
Traitement du signal : filtrage, interpolation, aller-retour temps <-> frequence.

Toutes les fonctions sont pures (entrees -> sorties) et travaillent sur des
tableaux numpy complexes (parametres S en fonction de la frequence).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import Akima1DInterpolator, CubicSpline, PchipInterpolator
from scipy.ndimage import gaussian_filter1d
from scipy.signal import butter, filtfilt, firwin, medfilt, savgol_filter, wiener

log = logging.getLogger(__name__)

INTERPOLATION_METHODS = ("Linear", "PCHIP", "Cubic Spline", "Akima")

# Une mesure dont la premiere frequence depasse cette fraction de f_max est
# traitee en passe-bande (pas d'extrapolation vers DC).
LOWPASS_MAX_START = 0.05

FILTER_METHODS = (
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
    "Vector Fitting",
)


# ---------------------------------------------------------------------------
# Filtrage
# ---------------------------------------------------------------------------

def _odd_window(window: int, n: int) -> int:
    """Fenetre impaire, au moins 3, au plus n (ou n-1 si n est pair)."""

    window = int(max(3, window))
    if window % 2 == 0:
        window += 1
    limit = n if n % 2 == 1 else n - 1
    return max(3, min(window, limit))


def _real_imag(func, x: np.ndarray) -> np.ndarray:
    return func(np.real(x)) + 1j * func(np.imag(x))


def filter_complex(
    x,
    method: str = "None",
    *,
    window: int = 11,
    order: int = 3,
    sigma: float = 2.0,
    cutoff: float = 0.10,
    frequency=None,
) -> np.ndarray:
    """
    Applique un lissage a un parametre S complexe.

    ``method`` est l'un de ``FILTER_METHODS``. Les methodes reelles sont
    appliquees separement aux parties reelle et imaginaire, sauf
    "Phase Only" (lissage de la phase deroulee) et "Vector Fitting"
    (modele rationnel scikit-rf, necessite ``frequency``).
    """

    x = np.asarray(x, dtype=complex)
    n = len(x)

    if method in (None, "None") or n < 5:
        return x

    if method == "Savitzky-Golay":
        w = _odd_window(window, n)
        o = int(min(max(order, 1), w - 1))
        return _real_imag(lambda v: savgol_filter(v, w, o), x)

    if method == "Gaussian":
        return _real_imag(lambda v: gaussian_filter1d(v, float(sigma)), x)

    if method == "Median":
        w = _odd_window(window, n)
        return _real_imag(lambda v: medfilt(v, w), x)

    if method == "Moving Average":
        w = int(max(1, min(window, n)))
        kernel = np.ones(w) / w
        return _real_imag(lambda v: np.convolve(v, kernel, mode="same"), x)

    if method == "Butterworth":
        b, a = butter(4, float(np.clip(cutoff, 1e-3, 0.999)))
        if n <= 3 * max(len(a), len(b)):
            return x
        return _real_imag(lambda v: filtfilt(b, a, v), x)

    if method == "FIR Low Pass":
        taps = min(31, n // 4 * 2 - 1)
        if taps < 3:
            return x
        b = firwin(taps, float(np.clip(cutoff, 1e-3, 0.999)))
        return _real_imag(lambda v: filtfilt(b, [1.0], v), x)

    if method == "Wiener":
        w = _odd_window(window, n)
        return _real_imag(lambda v: wiener(v, w), x)

    if method == "Wavelet":
        try:
            import pywt
        except ImportError:
            log.warning("pywt absent : filtre Wavelet ignore")
            return x

        def _wave(v):
            coeffs = pywt.wavedec(v, "db4")
            coeffs[1:] = [np.zeros_like(c) for c in coeffs[1:]]
            return pywt.waverec(coeffs, "db4")[:n]

        return _real_imag(_wave, x)

    if method == "Phase Only":
        w = _odd_window(window, n)
        o = int(min(max(order, 1), w - 1))
        mag = np.abs(x)
        phase = savgol_filter(np.unwrap(np.angle(x)), w, o)
        return mag * np.exp(1j * phase)

    if method == "Vector Fitting":
        if frequency is None:
            return x
        try:
            import skrf as rf
            from skrf.vectorFitting import VectorFitting

            net = rf.Network(
                frequency=rf.Frequency.from_f(np.asarray(frequency, float), unit="hz"),
                s=x.reshape(-1, 1, 1),
            )
            vf = VectorFitting(net)
            vf.vector_fit()
            return np.asarray(vf.get_model_response(0, 0), dtype=complex)
        except Exception as error:  # pragma: no cover - depend de skrf
            log.warning("Vector fitting impossible : %s", error)
            return x

    log.warning("Methode de filtrage inconnue : %s", method)
    return x


# ---------------------------------------------------------------------------
# Interpolation et grille uniforme partant de DC
# ---------------------------------------------------------------------------

def interpolate_complex(f, x, fu, method: str = "Linear") -> np.ndarray:
    """
    Interpole ``x(f)`` sur la grille ``fu``.

    Aucune extrapolation : en dehors de [f[0], f[-1]] la valeur mesuree la
    plus proche est prolongee (evite les NaN d'Akima et les divergences des
    splines).
    """

    f = np.asarray(f, dtype=float)
    x = np.asarray(x, dtype=complex)
    fu = np.asarray(fu, dtype=float)

    xr, xi = np.real(x), np.imag(x)

    if method == "PCHIP" and len(f) >= 2:
        out = PchipInterpolator(f, xr)(fu) + 1j * PchipInterpolator(f, xi)(fu)
    elif method == "Cubic Spline" and len(f) >= 2:
        out = CubicSpline(f, xr)(fu) + 1j * CubicSpline(f, xi)(fu)
    elif method == "Akima" and len(f) >= 3:
        out = Akima1DInterpolator(f, xr)(fu) + 1j * Akima1DInterpolator(f, xi)(fu)
    else:
        out = np.interp(fu, f, xr) + 1j * np.interp(fu, f, xi)

    out = np.asarray(out, dtype=complex)
    out = np.where(fu < f[0], x[0], out)
    out = np.where(fu > f[-1], x[-1], out)
    out = np.where(np.isfinite(out), out, 0.0)
    return out


def dc_uniform_grid(f, x, method: str = "Linear"):
    """
    Reechantillonne ``x(f)`` sur une grille uniforme 0, df, 2df, ..., ~f[-1].

    Le pas ``df`` est la mediane des pas mesures. Le point DC est force reel
    (condition d'une reponse temporelle reelle).
    """

    f = np.asarray(f, dtype=float)
    x = np.asarray(x, dtype=complex)

    df = float(np.median(np.diff(f)))
    n_points = int(round(f[-1] / df))
    fu = np.arange(n_points + 1) * df

    xu = interpolate_complex(f, x, fu, method)
    xu[0] = np.real(xu[0])
    return fu, xu


def uniform_grid(f, x, method: str = "Linear"):
    """
    Reechantillonne ``x(f)`` sur une grille uniforme f[0], f[0]+df, ... ~f[-1]
    (sans descendre a DC : mode passe-bande).
    """

    f = np.asarray(f, dtype=float)
    x = np.asarray(x, dtype=complex)

    df = float(np.median(np.diff(f)))
    n_points = int(round((f[-1] - f[0]) / df))
    fu = f[0] + np.arange(n_points + 1) * df

    return fu, interpolate_complex(f, x, fu, method)


def resample(f, fu, y) -> np.ndarray:
    """Retour (lineaire) d'une grille uniforme ``fu`` vers la grille ``f``."""

    y = np.asarray(y, dtype=complex)
    return np.interp(f, fu, np.real(y)) + 1j * np.interp(f, fu, np.imag(y))


# ---------------------------------------------------------------------------
# Domaine temporel
# ---------------------------------------------------------------------------

@dataclass
class TimeDomain:
    """Reponse impulsionnelle d'un parametre S sur grille uniforme depuis DC."""

    f: np.ndarray        # grille de frequence reelle (0 .. f_max)
    f_ext: np.ndarray    # grille etendue utilisee pour la transformee
    t: np.ndarray        # axe temporel 0 .. span
    t_sym: np.ndarray    # axe centre : t > span/2 devient t - span (temps negatifs)
    h: np.ndarray        # reponse impulsionnelle reelle
    window: np.ndarray   # fenetre appliquee avant irfft (= 1 sur la bande reelle)
    nfft: int
    n_real: int          # nombre de points de la bande reelle
    tres: float          # resolution temporelle ~ 1 / bande
    span: float          # 1 / df : duree sans repliement
    dt: float
    mode: str = "lowpass"   # "lowpass" (grille depuis DC, h reel) ou "bandpass" (enveloppe complexe)
    k0: int = 0             # indice du premier point reel dans la grille etendue


def extend_spectrum_down(fu, X, fraction: float = 0.25, fit_fraction: float = 0.15):
    """
    Prolonge ``X(fu)`` en dessous de f[0] (mode passe-bande), symetrique de
    ``extend_spectrum`` : tendance du module (dB) et de la phase sur les
    premiers ``fit_fraction`` de la bande. Ne descend jamais sous 0 Hz.
    Retourne ``(f_ext, X_ext)`` avec f_ext croissante, ou des tableaux vides.
    """

    fu = np.asarray(fu, dtype=float)
    X = np.asarray(X, dtype=complex)
    n = len(fu)
    df = fu[1] - fu[0]

    n_ext = int(round(fraction * (n - 1)))
    n_ext = min(n_ext, int(np.floor(fu[0] / df)) - 1)
    if n_ext < 2 or n < 8:
        return np.zeros(0), np.zeros(0, dtype=complex)

    n_fit = int(min(n, max(4, round(fit_fraction * n))))
    f_fit = fu[:n_fit]
    phase = np.unwrap(np.angle(X[:n_fit]))
    mag_db = 20.0 * np.log10(np.maximum(np.abs(X[:n_fit]), 1e-12))

    slope_p, icpt_p = np.polyfit(f_fit, phase, 1)
    slope_m, icpt_m = np.polyfit(f_fit, mag_db, 1)

    f_new = fu[0] - df * np.arange(n_ext, 0, -1)
    mag_new = 10.0 ** ((icpt_m + slope_m * f_new) / 20.0)
    mag_new = np.minimum(mag_new, np.max(np.abs(X[:n_fit])))
    phase_new = icpt_p + slope_p * f_new

    return f_new, mag_new * np.exp(1j * phase_new)


def extend_spectrum(fu, X, fraction: float = 0.25, fit_fraction: float = 0.15):
    """
    Prolonge ``X(fu)`` au-dela de f_max sur ``fraction`` de la bande.

    Le module (en dB) et la phase deroulee sont extrapoles lineairement a
    partir de leur tendance sur les derniers ``fit_fraction`` de la bande
    (une ligne : module decroissant, phase lineaire). Le module extrapole
    est borne par le module mesure en fin de bande.

    Retourne ``(f_ext, X_ext)`` ; ``fraction <= 0`` retourne les entrees.
    """

    fu = np.asarray(fu, dtype=float)
    X = np.asarray(X, dtype=complex)
    n = len(fu)

    n_ext = int(round(fraction * (n - 1)))
    if n_ext < 2 or n < 8:
        return fu, X

    df = fu[1] - fu[0]
    n_fit = int(min(n, max(4, round(fit_fraction * n))))

    f_fit = fu[-n_fit:]
    phase = np.unwrap(np.angle(X))[-n_fit:]
    mag_db = 20.0 * np.log10(np.maximum(np.abs(X[-n_fit:]), 1e-12))

    slope_p, icpt_p = np.polyfit(f_fit, phase, 1)
    slope_m, icpt_m = np.polyfit(f_fit, mag_db, 1)

    f_new = fu[-1] + df * np.arange(1, n_ext + 1)
    mag_new = 10.0 ** ((icpt_m + slope_m * f_new) / 20.0)
    mag_new = np.minimum(mag_new, np.max(np.abs(X[-n_fit:])))
    phase_new = icpt_p + slope_p * f_new

    X_new = mag_new * np.exp(1j * phase_new)
    return np.concatenate([fu, f_new]), np.concatenate([X, X_new])


def to_time_domain(fu, X, extend: float = 0.25, oversample: int = 8,
                   fit_fraction: float = 0.15, mode: str = "auto") -> TimeDomain:
    """
    Reponse impulsionnelle de ``X(fu)`` sur grille uniforme.

    mode "lowpass"  : la grille part de DC (``dc_uniform_grid``), h est reel
                      (irfft). Meilleure resolution, permet la TDR.
    mode "bandpass" : la grille commence a f[0] > 0 (``uniform_grid``), h est
                      l'enveloppe complexe (ifft). Aucune hypothese sur les
                      basses frequences : indispensable pour une mesure en
                      bande (extenseur mmW, guide d'onde).
    mode "auto"     : lowpass si fu[0] == 0, bandpass sinon.

    Dans les deux cas le spectre est prolonge par extrapolation de ``extend``
    au-dela de f_max (et en dessous de f[0] en passe-bande), et seules les
    parties prolongees sont attenuees par un flanc en cosinus : la bande
    reelle est transformee sans ponderation ni compensation.
    """

    fu = np.asarray(fu, dtype=float)
    X = np.asarray(X, dtype=complex)
    n_real = len(fu)
    df = fu[1] - fu[0]

    if mode == "auto":
        mode = "lowpass" if fu[0] == 0.0 else "bandpass"

    f_up, X_up = extend_spectrum(fu, X, extend, fit_fraction)

    if mode == "lowpass":
        f_ext, X_ext, k0 = f_up, X_up, 0
    else:
        f_dn, X_dn = extend_spectrum_down(fu, X, extend, fit_fraction)
        f_ext = np.concatenate([f_dn, f_up])
        X_ext = np.concatenate([X_dn, X_up])
        k0 = len(f_dn)

    n = len(f_ext)
    n_up = n - k0 - n_real

    window = np.ones(n)
    if n_up > 0:
        k = np.arange(1, n_up + 1)
        window[k0 + n_real:] = 0.5 * (1.0 + np.cos(np.pi * k / n_up))
    if k0 > 0:
        j = np.arange(1, k0 + 1)
        window[:k0] = 0.5 * (1.0 - np.cos(np.pi * j / (k0 + 1)))

    if mode == "lowpass":
        nfft = int(oversample * 2 ** int(np.ceil(np.log2(max(2 * (n - 1), 2)))))
        h = np.fft.irfft(X_ext * window, n=nfft)
        tres = 1.0 / fu[-1]
    else:
        nfft = int(oversample * 2 ** int(np.ceil(np.log2(max(n, 2)))))
        h = np.fft.ifft(X_ext * window, n=nfft)
        tres = 1.0 / (fu[-1] - fu[0])

    dt = 1.0 / (nfft * df)
    t = np.arange(nfft) * dt
    span = 1.0 / df
    t_sym = np.where(t > span / 2, t - span, t)

    return TimeDomain(
        f=fu, f_ext=f_ext, t=t, t_sym=t_sym, h=h, window=window, nfft=nfft,
        n_real=n_real, tres=tres, span=span, dt=dt, mode=mode, k0=k0,
    )


def check_time_span(td: TimeDomain, t_event: float, fraction: float = 0.4):
    """
    Avertissement si un evenement temporel ``t_event`` (s) est trop proche
    de la limite de repliement span/2 : le pas de frequence est alors trop
    grand pour la longueur du fixture. Retourne None ou un message.
    """

    limit = fraction * td.span
    if t_event <= limit:
        return None

    df = td.f[1] - td.f[0]
    df_needed = fraction / t_event
    message = (
        f"Evenement a {t_event * 1e12:.0f} ps pour une duree sans repliement de "
        f"{td.span * 1e12:.0f} ps : pas de frequence trop grand ({df / 1e6:.1f} MHz), "
        f"viser {df_needed / 1e6:.1f} MHz ou moins."
    )
    log.warning(message)
    return message


def raised_cosine_gate(t, t1: float, t2: float, edge: float) -> np.ndarray:
    """Fenetre = 1 sur [t1, t2], flancs en cosinus sureleve de largeur ``edge``."""

    t = np.asarray(t, dtype=float)
    g = np.zeros_like(t)
    edge = max(float(edge), 1e-30)

    g[(t >= t1) & (t <= t2)] = 1.0

    r = (t >= t1 - edge) & (t < t1)
    g[r] = 0.5 * (1 - np.cos(np.pi * (t[r] - (t1 - edge)) / edge))

    r = (t > t2) & (t <= t2 + edge)
    g[r] = 0.5 * (1 + np.cos(np.pi * (t[r] - t2) / edge))

    return g


def gate_near(td: TimeDomain, t_split: float, edge: float | None = None) -> np.ndarray:
    """Fenetre symetrique autour de t = 0 (reflexion proche), largeur ± t_split."""

    edge = td.tres if edge is None else edge
    return raised_cosine_gate(td.t_sym, -t_split, t_split, edge)


def gate_around(td: TimeDomain, center: float, half_width: float,
                edge: float | None = None) -> np.ndarray:
    """Fenetre centree sur ``center`` (temps positifs), demi-largeur ``half_width``."""

    edge = td.tres if edge is None else edge
    return raised_cosine_gate(td.t, center - half_width, center + half_width, edge)


def gate_to_freq(td: TimeDomain, gate) -> np.ndarray:
    """Retour en frequence de ``h * gate`` sur la bande reelle (grille ``td.f``)."""

    return np.fft.fft(td.h * gate)[td.k0: td.k0 + td.n_real]


def find_peak(td: TimeDomain, t_min: float | None = None,
              t_max: float | None = None) -> float:
    """
    Instant du maximum de |h| dans [t_min, t_max] (defaut : [3 tres, span/2]),
    affine par interpolation parabolique.
    """

    t_min = 3 * td.tres if t_min is None else t_min
    t_max = td.span / 2 if t_max is None else t_max

    m = np.abs(td.h).astype(float)
    m[td.t < t_min] = 0.0
    m[td.t > t_max] = 0.0

    idx = int(np.argmax(m))
    if m[idx] <= 0:
        return t_min

    if 0 < idx < len(m) - 1:
        y0, y1, y2 = m[idx - 1], m[idx], m[idx + 1]
        denom = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        delta = float(np.clip(delta, -1.0, 1.0))
        return float(td.t[idx] + delta * td.dt)

    return float(td.t[idx])


# ---------------------------------------------------------------------------
# Racine carree complexe continue
# ---------------------------------------------------------------------------

def complex_sqrt_continuous(G, f=None, dc_fraction: float = 0.05,
                            anchor_delay: float | None = None) -> np.ndarray:
    """
    sqrt(G) avec phase deroulee (continue en frequence).

    Choix de la branche (sqrt a deux solutions, +/-) :
      - ``anchor_delay`` donne (s) : la phase de sqrt(G) au premier point
        est amenee au plus pres de -2 pi f[0] anchor_delay. A utiliser en
        passe-bande, ou DC n'est pas dans la bande.
      - sinon, si ``f`` est fournie : la phase de G extrapolee a DC est
        ramenee a ~0 modulo 2 pi (sqrt(G) reelle positive a basse
        frequence, comme le S21 d'un fixture passif).
    """

    G = np.asarray(G, dtype=complex)
    mag = np.sqrt(np.abs(G))
    phase = np.unwrap(np.angle(G))

    if f is not None and len(G) >= 3:
        f = np.asarray(f, dtype=float)
        if anchor_delay is not None:
            target = -2.0 * np.pi * f[0] * float(anchor_delay)
            k = np.round((phase[0] - 2.0 * target) / (2.0 * np.pi))
        else:
            n_fit = max(3, int(dc_fraction * len(f)))
            _, intercept = np.polyfit(f[:n_fit], phase[:n_fit], 1)
            k = np.round(intercept / (2.0 * np.pi))
        phase = phase - 2.0 * np.pi * k

    return mag * np.exp(1j * phase / 2.0)


# ---------------------------------------------------------------------------
# Post-traitement du S21 extrait
# ---------------------------------------------------------------------------

def smooth_db_phase(s, window: int, order: int = 3) -> np.ndarray:
    """
    Lissage Savitzky-Golay du module (dB) et de la phase deroulee d'un
    parametre S. Contrairement a un lissage de Re/Im, la rotation rapide
    de la phase n'est pas ecrasee. ``window`` <= 2 : aucun lissage.
    """

    s = np.asarray(s, dtype=complex)
    n = len(s)
    if window is None or window <= 2 or n < 7:
        return s

    w = _odd_window(window, n)
    o = int(min(max(order, 1), w - 1))

    db = savgol_filter(20.0 * np.log10(np.maximum(np.abs(s), 1e-15)), w, o)
    phase = savgol_filter(np.unwrap(np.angle(s)), w, o)
    return 10.0 ** (db / 20.0) * np.exp(1j * phase)


def clamp_unit(x, limit: float = 1.0):
    """
    Borne le module de ``x`` a ``limit`` en conservant la phase.
    Retourne ``(x_borne, nombre de points modifies)``.
    """

    x = np.asarray(x, dtype=complex)
    mag = np.abs(x)
    over = mag > limit

    if not np.any(over):
        return x, 0

    out = x.copy()
    out[over] = x[over] / np.maximum(mag[over], 1e-30) * limit
    return out, int(np.count_nonzero(over))


def clamp_passive(s21, s11=None):
    """
    Rend passif un 2 ports symetrique reciproque S = [[a, b], [b, a]], en
    reduisant si necessaire le module de b = S21 et en conservant sa phase.

    Une telle matrice est normale : ses valeurs singulieres valent |a + b| et
    |a - b|. La passivite s'ecrit donc

        |a + b| <= 1  et  |a - b| <= 1

    et non |a|^2 + |b|^2 <= 1, qui est la norme d'une colonne et ne suffit
    pas (a = 0.30, b = 0.95 passe ce dernier test mais donne |a + b| = 1.25).

    On cherche le plus grand facteur k de [0, 1] tel que ``a +/- k b`` reste
    dans le disque unite. Chaque condition est un trinome en k :

        k^2 |b|^2 +/- 2 k Re(a conj(b)) + |a|^2 - 1 <= 0

    Retourne ``(s21_borne, nombre de points modifies)``.
    """

    b = np.asarray(s21, dtype=complex)

    if s11 is None:
        return clamp_unit(b)

    a = np.asarray(s11, dtype=complex)

    quad = np.abs(b) ** 2
    const = np.abs(a) ** 2 - 1.0
    cross = np.real(a * np.conj(b))

    factor = np.ones(len(b))

    for sign in (+1.0, -1.0):
        linear = sign * cross
        disc = linear ** 2 - quad * const           # >= 0 des que |a| <= 1
        disc = np.maximum(disc, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            root = (-linear + np.sqrt(disc)) / quad

        # |b| nul : aucune contrainte sur k
        root = np.where(quad > 1e-30, root, 1.0)
        factor = np.minimum(factor, np.maximum(root, 0.0))

    # |S11| deja au-dela de 1 : le probleme vient de la reflexion, pas de S21
    factor = np.where(np.abs(a) >= 1.0, 0.0, factor)
    factor = np.clip(factor, 0.0, 1.0)

    changed = int(np.count_nonzero(factor < 1.0 - 1e-12))
    return b * factor, changed
