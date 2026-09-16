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

Deuxieme methode : modele de ligne ajuste ('line_fit')
-----------------------------------------------------
Le residu (1) est l'aller-retour P^2 d'une ligne. Plutot que de le garder
point par point, on l'ajuste au sens des moindres carres par le modele

    -ln|P^2|  = 2 (a sqrt(f) + b f)          effet de peau + pertes dielectriques
    -arg(P^2) = 2 c sqrt(f) + 4 pi f tau     dispersion + delai

Les deux ajustements sont lineaires en leurs coefficients : pas d'optimiseur,
pas de probleme de convergence, et le bruit de mesure est moyenne sur tous les
points de la bande au lieu d'etre transporte tel quel dans le S2P. La phase du
modele etant analytique et continue, la racine P = sqrt(P^2) n'a plus aucune
ambiguite de branche.

C'est la methode a utiliser en bande millimetrique et submillimetrique
(140 GHz - 1 THz), ou l'echo aller-retour approche le plancher de bruit du
VNA : le fenetrage seul y laisse plusieurs dB d'erreur la ou l'ajustement
reste sous 0.1 dB. En contrepartie elle impose la forme du modele : ligne
uniforme et transition d'entree constante sur la bande (G1 pris egal a sa
mediane). Sur une bande etroite et propre, les deux methodes coincident.

Limites : le modele suppose une seule discontinuite dominante (connecteur ou
transition d'entree) suivie d'une ligne uniforme, et un fixture symetrique
(S22 = S11) et reciproque (S12 = S21). Un fixture a plusieurs discontinuites
fortes demande le 2x-thru.

Plage dynamique : |S21| est deduit de l'echo a t = 2 tau, dont le niveau vaut
le carre de la transmission. Quand cet echo passe sous le plancher de bruit
(voir ``echo_snr_db`` dans le rapport de qualite), aucune des deux methodes ne
peut le restituer ; l'extraction est alors signalee comme incertaine.
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
MODELS = ("single_discontinuity", "line_fit", "first_order")

# Suffixe ajoute au nom de methode selon le modele employe.
METHOD_SUFFIX = {"single_discontinuity": "", "line_fit": "_line_fit",
                 "first_order": "_first_order"}

# En dessous de ce rapport echo / bruit (dB), |S21| n'est plus fiable.
ECHO_SNR_WARNING_DB = 35.0


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
            f"les fenetres proche et lointaine se recouvrent et ont ete reduites. "
            f"La reflexion d'entree est alors surestimee, donc l'impedance aussi. "
            f"Deux remedes : mesurer OPEN et SHORT du meme cote (la reflexion "
            f"d'entree est alors resolue algebriquement, sans fenetrage), ou "
            f"elargir la bande de mesure."
        )
        log.warning(message)
        quality["warning"] = message

    quality["gate_half_ps"] = gate_half * 1e12
    quality["near_split_ps"] = t_split * 1e12

    snr = sig.echo_snr(td, t_far, gate_half)
    quality["echo_snr_db"] = snr
    if snr < ECHO_SNR_WARNING_DB:
        message = (
            f"Echo aller-retour a seulement {snr:.0f} dB au-dessus du plancher "
            f"de bruit (repere de confiance : {ECHO_SNR_WARNING_DB:.0f} dB). "
            f"|S21| est entierement porte par cet echo, dont le niveau vaut le "
            f"double des pertes de la ligne en dB : sous cette limite "
            f"l'extraction devient incertaine, cas frequent au-dela de 500 GHz. "
            f"Remedes : moyennage ou bande FI plus etroite au VNA, fixture plus "
            f"court, ou modele 'line_fit' qui moyenne le bruit sur toute la bande."
        )
        log.warning(message)
        quality["dynamic_range_warning"] = message

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
# Deuxieme methode : modele de ligne ajuste aux moindres carres
# ---------------------------------------------------------------------------

LINE_FIT_MIN_POINTS = 8


def fit_line_model(f, p_squared, band=None) -> dict:
    """
    Ajuste l'aller-retour P^2 par le modele de ligne (voir l'en-tete) :

        -ln|P^2|  = alpha_root sqrt(f) + alpha_linear f + log_offset
        -arg(P^2) = phase_root sqrt(f) + phase_linear f + phase_offset

    Deux moindres carres lineaires independants (module puis phase deroulee).
    Retourne les six coefficients et le delai aller ``delay_s`` = phase_linear
    / (4 pi) : le facteur 4 pi vient de l'aller-retour, ou la phase vaut
    -2 * 2 pi f tau.

    ``band`` = (f_min, f_max) restreint l'ajustement aux frequences reellement
    mesurees : en mode passe-bas la grille descend jusqu'a DC, et les points
    ajoutes sous la premiere frequence mesuree sont extrapoles, donc a exclure.
    Le deroulement de la phase, lui, se fait sur toute la grille pour rester
    continu.
    """

    f = np.asarray(f, dtype=float)
    p2 = np.asarray(p_squared, dtype=complex)

    usable = np.isfinite(p2) & (np.abs(p2) > 0.0)
    if band is not None:
        usable &= (f >= band[0]) & (f <= band[1])
    if np.count_nonzero(usable) < LINE_FIT_MIN_POINTS:
        raise ValueError("Trop peu de points exploitables pour ajuster le modele de ligne "
                         f"({np.count_nonzero(usable)} < {LINE_FIT_MIN_POINTS}).")

    root = np.sqrt(np.maximum(f, 0.0))
    basis = np.column_stack([root, f, np.ones_like(f)])

    attenuation = -np.log(np.maximum(np.abs(p2), TINY))
    # Deroulement sur toute la bande avant selection : les sauts de 2 pi se
    # suivent de proche en proche.
    phase = -np.unwrap(np.angle(p2))

    alpha_root, alpha_linear, log_offset = np.linalg.lstsq(
        basis[usable], attenuation[usable], rcond=None)[0]
    phase_root, phase_linear, phase_offset = np.linalg.lstsq(
        basis[usable], phase[usable], rcond=None)[0]

    return {
        "alpha_root": float(alpha_root),
        "alpha_linear": float(alpha_linear),
        "log_offset": float(log_offset),
        "phase_root": float(phase_root),
        "phase_linear": float(phase_linear),
        "phase_offset": float(phase_offset),
        "delay_s": float(phase_linear / (4.0 * np.pi)),
    }


def _line_model(f, coefficients: dict, scale: float) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    root = np.sqrt(np.maximum(f, 0.0))

    attenuation = (coefficients["alpha_root"] * root
                   + coefficients["alpha_linear"] * f
                   + coefficients["log_offset"])
    phase = (coefficients["phase_root"] * root
             + coefficients["phase_linear"] * f
             + coefficients["phase_offset"])

    return np.exp(-scale * attenuation) * np.exp(-1j * scale * phase)


def line_model_p_squared(f, coefficients: dict) -> np.ndarray:
    """Aller-retour P^2 reconstruit par le modele ajuste."""

    return _line_model(f, coefficients, 1.0)


def line_model_propagation(f, coefficients: dict) -> np.ndarray:
    """
    Propagation aller P = sqrt(P^2) issue du modele.

    La phase du modele est analytique et continue : la diviser par deux suffit,
    sans deroulement ni ancrage de branche, contrairement a la racine d'un P^2
    mesure.
    """

    return _line_model(f, coefficients, 0.5)


def _median_constant(values) -> np.ndarray:
    """Valeur mediane (partie reelle et imaginaire) repetee sur toute la bande."""

    values = np.asarray(values, dtype=complex)
    median = complex(float(np.median(values.real)), float(np.median(values.imag)))
    return np.full(values.shape, median, dtype=complex)


def line_fit_propagation(fu, p_squared, g1, quality: dict, band=None):
    """
    Applique le modele de ligne : G1 constant (mediane) et P analytique.

    Le modele suppose la transition d'entree stable sur la bande ; sa mediane
    est prise plutot que sa moyenne pour resister aux points bruites.
    ``band`` : bande reellement mesuree, voir ``fit_line_model``.
    """

    coefficients = fit_line_model(fu, p_squared, band)
    propagation = line_model_propagation(fu, coefficients)
    fitted = line_model_p_squared(fu, coefficients)

    p_squared = np.asarray(p_squared, dtype=complex)

    # Ecart modele / mesure, sur la bande mesuree uniquement.
    fu = np.asarray(fu, dtype=float)
    inside = np.ones(fu.shape, dtype=bool) if band is None else \
        ((fu >= band[0]) & (fu <= band[1]))

    level = float(np.sqrt(np.mean(np.abs(p_squared[inside]) ** 2)))
    residual = float(np.sqrt(np.mean(np.abs(p_squared[inside] - fitted[inside]) ** 2)))

    quality["line_fit"] = coefficients
    quality["line_fit_delay_ps"] = coefficients["delay_s"] * 1e12
    quality["line_fit_residual"] = residual
    quality["line_fit_residual_db"] = float(
        20 * np.log10(max(residual, 1e-15) / max(level, 1e-15)))

    g1_constant = _median_constant(g1)
    if len(g1_constant):
        median = complex(g1_constant[0])
        quality["gamma1_median_mag"] = float(abs(median))
        quality["gamma1_median_deg"] = float(np.degrees(np.angle(median)))

    return g1_constant, propagation


# ---------------------------------------------------------------------------
# Qualite d'ajustement : le fixture extrait explique-t-il la mesure ?
# ---------------------------------------------------------------------------

FIT_WARNING_LEVEL = 0.05


def predict_reflect(network: rf.Network, gl: float) -> np.ndarray:
    """
    Reflexion que produirait le fixture extrait, termine par le standard GL :

        Gamma = S11 + S21 S12 GL / (1 - S22 GL)
    """

    s11 = network.s[:, 0, 0]
    s21 = network.s[:, 1, 0]
    s12 = network.s[:, 0, 1]
    s22 = network.s[:, 1, 1]

    return s11 + s21 * s12 * gl / _safe(1.0 - s22 * gl)


def model_fit(gamma_measured, network: rf.Network, gl: float) -> dict:
    """
    Compare la mesure a ce que predit le fixture extrait.

    C'est l'indicateur de confiance : le modele suppose une seule
    discontinuite dominante suivie d'une ligne uniforme. Sur un fixture reel
    qui en compte plusieurs (connecteur, transition, via), l'ecart grandit et
    l'extraction n'est plus fiable. Un ecart quadratique moyen inferieur a
    quelques pourcents indique un modele adapte.

    Retourne ``fit_rms``, ``fit_max`` (module de l'ecart, lineaire) et
    ``fit_rms_db`` (ecart rapporte au niveau moyen de la mesure).
    """

    measured = np.asarray(gamma_measured, dtype=complex)
    predicted = predict_reflect(network, gl)

    error = predicted - measured
    rms = float(np.sqrt(np.mean(np.abs(error) ** 2)))
    level = float(np.sqrt(np.mean(np.abs(measured) ** 2)))

    report = {
        "fit_rms": rms,
        "fit_max": float(np.max(np.abs(error))),
        "fit_rms_db": float(20 * np.log10(max(rms, 1e-15) / max(level, 1e-15))),
    }

    if rms > FIT_WARNING_LEVEL:
        report["fit_warning"] = (
            f"Le fixture extrait ne reproduit la mesure qu'a {rms:.3f} pres "
            f"(ecart quadratique moyen, {report['fit_rms_db']:.1f} dB sous le "
            f"niveau du signal). Le modele a une discontinuite decrit mal ce "
            f"fixture : plusieurs discontinuites fortes, standard imparfait ou "
            f"bande insuffisante. Preferer le 2x-thru si vous en avez un."
        )
        log.warning(report["fit_warning"])

    return report


# ---------------------------------------------------------------------------
# Assemblage du resultat
# ---------------------------------------------------------------------------

def constrain_physical(g1, propagation, quality):
    """
    Contraint le modele a rester physique avant d'en deduire S11 et S21 :
    un fixture passif a |G1| <= 1 (reflexion) et |P| <= 1 (propagation).

    Sans cette borne, un G1 entache d'erreur de fenetre combine a un P
    legerement superieur a 1 fait diverger S21 = (1 - G1^2) P / (1 - G1^2 P^2)
    bien au-dela de la limite passive.
    """

    g1, over_g1 = sig.clamp_unit(g1, 1.0 - 1e-9)
    propagation, over_p = sig.clamp_unit(propagation, 1.0)

    quality["clamped_gamma1"] = over_g1
    quality["clamped_propagation"] = over_p

    if over_p:
        log.warning("%d point(s) de propagation au-dessus de 1 (fixture actif) "
                    "ramenes a 1 : verifier le standard et la calibration.", over_p)

    return g1, propagation


def _finish(f, fu, s11u, s21u, gamma_for_tdr, z0, method, quality, interp_method,
            smooth_points: int = 0, enforce_passivity: bool = True, g1=None):
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

    # Sans continu dans la bande, la reponse en echelon n'est pas definie :
    # on se rabat sur la reflexion proche, qui reste disponible.
    if not np.isfinite(impedance) and g1 is not None:
        impedance = metrics.impedance_from_gamma1(g1, z0)
        quality["impedance_source"] = "gamma1"
    else:
        quality["impedance_source"] = "tdr"

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
    ``model``            : 'single_discontinuity' (defaut, exact apres G1),
                           'line_fit' (modele de ligne ajuste aux moindres
                           carres, recommande au-dela de 100 GHz ou des que
                           l'echo approche le plancher de bruit) ou
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

    over_unit = int(np.count_nonzero(np.abs(gamma) > 1.0 + 1e-6))
    if over_unit:
        log.warning("Le fichier mesure contient %d point(s) avec |Gamma| > 1 : "
                    "la mesure elle-meme n'est pas passive (calibration).", over_unit)

    fu, td = prepare(f, gamma, interp_method)
    gamma_u = sig.resample(fu, f, gamma)

    t_far = sig.find_peak(td)
    g_near, g_far, quality = _gates(td, t_far)
    quality["mode"] = td.mode
    quality["model"] = model
    quality["load"] = "SHORT" if gl < 0 else "OPEN"
    quality["measured_over_unit"] = over_unit

    g1 = sig.gate_to_freq(td, g_near)

    if model in ("single_discontinuity", "line_fit"):
        # Transition d'entree retiree exactement, puis exploitation de l'echo unique
        residual = deembed_input(gamma_u, g1) / gl
        p_squared = _gate_echo(fu, residual, t_far, td)

        if model == "line_fit":
            # L'ecart modele / mesure est reporte par line_fit_residual.
            g1, propagation = line_fit_propagation(fu, p_squared, g1, quality,
                                                   band=(f[0], f[-1]))
        else:
            propagation = _sqrt(_safe(p_squared, TINY), fu, td, t_far)
            quality["model_residual"] = float(
                np.max(np.abs(propagation * propagation - p_squared))
            )

        g1, propagation = constrain_physical(g1, propagation, quality)
        s11u, s21u = network_from_model(g1, propagation)
    else:
        far = sig.gate_to_freq(td, g_far)
        s21_squared = _safe((far / gl) * (1.0 - g1 * g1), TINY)
        s21u = _sqrt(s21_squared, fu, td, t_far)
        s11u = g1
        quality["sqrt_residual"] = float(np.max(np.abs(s21u * s21u - s21_squared)))

    method = ("reflect_short" if gl < 0 else "reflect_open") + METHOD_SUFFIX[model]

    result = _finish(f, fu, s11u, s21u, gamma, z0, method, quality, interp_method,
                     smooth_points, enforce_passivity, g1=g1)

    result.quality.update(model_fit(gamma, result.network, gl))
    return result


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

    Avec 'line_fit', ce meme G1 algebrique est ramene a sa mediane et P^2 est
    ajuste par le modele de ligne : c'est la combinaison la plus robuste en
    bande millimetrique, ou les deux mesures moyennent deja le bruit avant
    l'ajustement.
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

    if model == "line_fit":
        g1, propagation = line_fit_propagation(fu, p_squared, g1, quality,
                                               band=(f[0], f[-1]))
    else:
        propagation = _sqrt(_safe(p_squared, TINY), fu, td_p, t_far)
        quality["model_residual"] = float(
            np.max(np.abs(propagation * propagation - p_squared))
        )

    g1, propagation = constrain_physical(g1, propagation, quality)
    s11u, s21u = network_from_model(g1, propagation)

    quality["mode"] = td_p.mode
    quality["model"] = model
    quality["load"] = "OPEN+SHORT"

    _open_short_consistency(f, gamma_open, gamma_short, z0, interp_method, quality)

    result = _finish(f, fu, s11u, s21u, 0.5 * (gamma_open + gamma_short), z0,
                     "reflect_open_short" + METHOD_SUFFIX[model], quality, interp_method,
                     smooth_points, enforce_passivity, g1=g1)

    # Le modele doit expliquer les DEUX mesures : on retient la pire des deux
    fit_open = model_fit(gamma_open, result.network, +1.0)
    fit_short = model_fit(gamma_short, result.network, -1.0)
    result.quality.update(fit_open if fit_open["fit_rms"] >= fit_short["fit_rms"] else fit_short)
    return result


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

    result = _finish(f, fu, s11u, s21u, mean, z0, "reflect_open_short_first_order",
                     quality, interp_method, smooth_points, enforce_passivity, g1=s11u)

    fit_open = model_fit(gamma_open, result.network, +1.0)
    fit_short = model_fit(gamma_short, result.network, -1.0)
    result.quality.update(fit_open if fit_open["fit_rms"] >= fit_short["fit_rms"] else fit_short)
    return result


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
