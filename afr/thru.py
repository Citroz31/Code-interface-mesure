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


# ---------------------------------------------------------------------------
# Fixtures asymetriques (deux lignes de longueurs differentes)
# ---------------------------------------------------------------------------
#
# Convention de cascade utilisee partout dans le paquet :
#
#     mesure = fixture_in ** DUT ** fixture_out
#     2x-thru = fixture_in ** fixture_out
#
#   fixture_in  : port 1 cote VNA,  port 2 cote DUT
#   fixture_out : port 1 cote DUT,  port 2 cote VNA
#
# Une mesure de reflexion (OPEN / SHORT) est toujours orientee "VNA vers DUT".
# Pour servir de fixture de sortie elle doit donc etre retournee : c'est le
# role de ``as_output_fixture``.

def as_output_fixture(network: rf.Network) -> rf.Network:
    """Oriente un fixture extrait par reflexion pour le cote sortie."""

    return port_swap(network)


def fixture_out_from_thru(thru: rf.Network, fixture_in: rf.Network) -> rf.Network:
    """
    Fixture de sortie deduit d'un 2x-thru et du fixture d'entree :

        B = A^-1 ** thru

    Exact, sans hypothese de symetrie : c'est la voie a utiliser quand les
    deux lignes n'ont pas la meme longueur et qu'un seul cote a ete
    caracterise par OPEN / SHORT.
    """

    a = _align(fixture_in, thru)
    out = a.inv ** thru
    out.name = "FIXTURE_OUT"
    return out


def fixture_in_from_thru(thru: rf.Network, fixture_out: rf.Network) -> rf.Network:
    """Fixture d'entree deduit d'un 2x-thru et du fixture de sortie : A = thru ** B^-1."""

    b = _align(fixture_out, thru)
    out = thru ** b.inv
    out.name = "FIXTURE_IN"
    return out


def _align(fixture: rf.Network, target: rf.Network) -> rf.Network:
    if np.array_equal(fixture.f, target.f):
        return fixture
    return fixture.interpolate(target.frequency)


def pair_residual(thru: rf.Network, fixture_in: rf.Network,
                  fixture_out: rf.Network) -> dict:
    """
    Compare ``fixture_in ** fixture_out`` au 2x-thru mesure.

    C'est le controle central du cas asymetrique : si les deux fixtures sont
    corrects, leur cascade redonne le 2x-thru. Retourne les ecarts maximaux
    sur S21 (dB et degres) et sur S11.
    """

    rebuilt = _align(fixture_in, thru) ** _align(fixture_out, thru)

    e21, r21 = rebuilt.s[:, 1, 0], thru.s[:, 1, 0]
    mag = float(np.max(np.abs(
        20 * np.log10(np.maximum(np.abs(e21), 1e-15))
        - 20 * np.log10(np.maximum(np.abs(r21), 1e-15))
    )))
    phase = float(np.max(np.abs(np.degrees(np.angle(e21 * np.conj(r21))))))
    s11 = float(np.max(np.abs(rebuilt.s[:, 0, 0] - thru.s[:, 0, 0])))

    report = {"thru_s21_db": mag, "thru_s21_deg": phase, "thru_s11": s11}
    log.info("Controle 2x-thru : S21 %.3f dB / %.2f deg, S11 %.4f", mag, phase, s11)
    return report


def complete_pair(thru: rf.Network = None, fixture_in: rf.Network = None,
                  fixture_out: rf.Network = None, interp_method: str = "Linear"):
    """
    Construit la paire (fixture_in, fixture_out) selon les standards presents.

    Ordre de preference, du plus rigoureux au plus hypothetique :

    1. les deux cotes caracterises par OPEN / SHORT  -> aucune hypothese ;
    2. un cote caracterise + 2x-thru                 -> l'autre par cascade
                                                        inverse, exact ;
    3. 2x-thru seul                                  -> decoupage en deux
                                                        moities identiques,
                                                        valable seulement si
                                                        les deux lignes sont
                                                        symetriques.

    Retourne ``(fixture_in, fixture_out, info)`` ou ``info['method']`` nomme
    la voie utilisee et ``info`` porte le controle ``pair_residual`` des que
    le 2x-thru est disponible.
    """

    info = {}

    if fixture_in is not None and fixture_out is not None:
        info["method"] = "reflect_both_sides"

    elif fixture_in is not None and thru is not None:
        fixture_out = fixture_out_from_thru(thru, fixture_in)
        info["method"] = "reflect_in_plus_thru"

    elif fixture_out is not None and thru is not None:
        fixture_in = fixture_in_from_thru(thru, fixture_out)
        info["method"] = "reflect_out_plus_thru"

    elif thru is not None:
        fixture_in, fixture_out, thru_info = split_2x_thru(thru, interp_method)
        info["method"] = "thru_symmetric_split"
        info["thru"] = thru_info
        info["warning"] = (
            "2x-thru seul : les deux moities sont supposees identiques. "
            "Si les lignes d'entree et de sortie n'ont pas la meme longueur, "
            "mesurer un OPEN ou un SHORT sur au moins un des deux cotes."
        )
        log.warning(info["warning"])

    elif fixture_in is not None:
        fixture_out = as_output_fixture(fixture_in)
        info["method"] = "reflect_in_mirrored"
        info["warning"] = (
            "Un seul cote caracterise et pas de 2x-thru : le fixture de sortie "
            "est le miroir du fixture d'entree (hypothese de symetrie)."
        )
        log.warning(info["warning"])

    elif fixture_out is not None:
        fixture_in = as_output_fixture(fixture_out)
        info["method"] = "reflect_out_mirrored"
        info["warning"] = (
            "Un seul cote caracterise et pas de 2x-thru : le fixture d'entree "
            "est le miroir du fixture de sortie (hypothese de symetrie)."
        )
        log.warning(info["warning"])

    else:
        raise ValueError(
            "Aucun standard exploitable : charger un 2x-thru et/ou un OPEN / SHORT."
        )

    if thru is not None:
        info["residual"] = pair_residual(thru, fixture_in, fixture_out)

    return fixture_in, fixture_out, info


def check_fixtured_dut(measured: rf.Network, fixture_in: rf.Network,
                       fixture_out: rf.Network) -> dict:
    """
    Controle de l'extraction sur une mesure de DUT fixture (DUT monte entre
    les deux lignes). Le DUT de-embedde doit rester passif et reciproque :
    une valeur singuliere superieure a 1 signale des fixtures surestimes.
    """

    from . import deembed as _deembed

    dut = _deembed.remove_fixtures(measured, fixture_in, fixture_out)
    report = metrics.quality_report(dut.s)

    rebuilt = _align(fixture_in, measured) ** dut ** _align(fixture_out, measured)
    report["reconstruction"] = float(np.max(np.abs(rebuilt.s - measured.s)))
    report["network"] = dut

    if not report["passive"]:
        log.warning("DUT de-embedde non passif (valeur singuliere max %.3f) : "
                    "les fixtures extraits sont probablement surestimes.",
                    report["max_singular_value"])

    return report
