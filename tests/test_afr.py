"""
Tests du noyau AFR sur des fixtures synthetiques.

Fixture de reference : ligne de transmission Zc = 55 ohm, delai 300 ps,
pertes ~ sqrt(f) (1 dB a 10 GHz), entre deux ports 50 ohm.

Lancer :  python -m pytest tests -q
(numpy, scipy, scikit-rf installes ; aucune fenetre Tk n'est ouverte)
"""

import numpy as np
import pytest
import skrf as rf

from afr import deembed, metrics, reflect, thru
from afr import signal as afr_signal
from afr.signal import complex_sqrt_continuous, dc_uniform_grid

FREQ = np.arange(10e6, 20e9 + 1, 10e6)
ZC = 55.0
DELAY = 300e-12
BAND = (FREQ >= 1e9) & (FREQ <= 15e9)


def synthetic_line(freq=FREQ, zc=ZC, delay=DELAY, loss_db_10ghz=1.0, z0=50.0):
    w = 2 * np.pi * freq
    alpha = (loss_db_10ghz / 8.686) * np.sqrt(np.maximum(freq, 1.0) / 10e9)
    gamma_l = alpha + 1j * w * delay

    abcd = np.zeros((len(freq), 2, 2), dtype=complex)
    abcd[:, 0, 0] = np.cosh(gamma_l)
    abcd[:, 0, 1] = zc * np.sinh(gamma_l)
    abcd[:, 1, 0] = np.sinh(gamma_l) / zc
    abcd[:, 1, 1] = np.cosh(gamma_l)

    s = rf.a2s(abcd, z0=z0)
    return rf.Network(frequency=rf.Frequency.from_f(freq, unit="hz"), s=s, z0=z0)


def one_port(net, gamma_load):
    s11, s21, s12, s22 = net.s[:, 0, 0], net.s[:, 1, 0], net.s[:, 0, 1], net.s[:, 1, 1]
    return s11 + s21 * s12 * gamma_load / (1.0 - s22 * gamma_load)


def errors(est, ref):
    mag = 20 * np.log10(np.abs(est[BAND])) - 20 * np.log10(np.abs(ref[BAND]))
    phase = np.degrees(np.angle(est[BAND] * np.conj(ref[BAND])))
    return float(np.max(np.abs(mag))), float(np.max(np.abs(phase)))


@pytest.fixture(scope="module")
def line():
    return synthetic_line()


# ---------------------------------------------------------------------------
# signal
# ---------------------------------------------------------------------------

def test_dc_grid_starts_at_zero_and_keeps_band():
    fu, xu = dc_uniform_grid(FREQ, np.exp(-2j * np.pi * FREQ * DELAY), "Akima")
    assert fu[0] == 0.0
    assert abs(fu[-1] - FREQ[-1]) < 1e-3
    assert np.all(np.isfinite(xu))
    assert np.imag(xu[0]) == 0.0


def test_extend_spectrum_continues_line_response(line):
    from afr.signal import extend_spectrum

    fu, xu = dc_uniform_grid(FREQ, line.s[:, 1, 0])
    f_ext, x_ext = extend_spectrum(fu, xu, fraction=0.25)
    n = len(fu)
    assert len(f_ext) > n
    assert np.allclose(f_ext[:n], fu) and np.allclose(x_ext[:n], xu)
    # module borne et phase qui continue de tourner au meme rythme
    assert np.all(np.abs(x_ext[n:]) <= np.max(np.abs(xu)) + 1e-12)
    step = np.diff(np.unwrap(np.angle(x_ext)))
    assert abs(np.mean(step[n:]) - np.mean(step[n - 50:n])) < 0.05 * abs(np.mean(step[n - 50:n]))


def test_band_edge_is_usable_up_to_fmax():
    """Bande large (10 MHz - 120 GHz) : l'erreur en bord de bande reste bornee."""

    freq = np.arange(10e6, 120e9 + 1, 20e6)
    line = synthetic_line(freq=freq, delay=150e-12, loss_db_10ghz=0.5)
    result = reflect.fixture_from_reflect(freq, one_port(line, +1.0), "OPEN")
    est, ref = result.network.s[:, 1, 0], line.s[:, 1, 0]

    edge = freq >= 110e9
    mag_err = 20 * np.log10(np.abs(est[edge])) - 20 * np.log10(np.abs(ref[edge]))
    phase_err = np.degrees(np.angle(est[edge] * np.conj(ref[edge])))
    assert np.max(np.abs(mag_err)) < 1.0, f"bord de bande : {np.max(np.abs(mag_err)):.2f} dB"
    assert np.max(np.abs(phase_err)) < 8.0
    assert result.quality["mode"] == "lowpass"

    mid = (freq >= 5e9) & (freq <= 100e9)
    mag_err = 20 * np.log10(np.abs(est[mid])) - 20 * np.log10(np.abs(ref[mid]))
    assert np.max(np.abs(mag_err)) < 0.3


def test_coarse_frequency_step_is_flagged():
    """Fixture trop long pour le pas de frequence : avertissement dans quality."""

    freq = np.arange(100e6, 20e9 + 1, 100e6)          # span = 10 ns
    line = synthetic_line(freq=freq, delay=2.0e-9)     # aller-retour 4 ns + fenetre > 0.4 span
    result = reflect.fixture_from_reflect(freq, one_port(line, +1.0), "OPEN")
    assert "warning" in result.quality


def test_sqrt_continuous_recovers_propagation_term():
    p = np.exp(-2j * np.pi * FREQ * DELAY)
    root = complex_sqrt_continuous(p * p, FREQ)
    assert np.max(np.abs(root - p)) < 1e-6
    # phase continue : pas de saut entre points voisins
    assert np.max(np.abs(np.diff(np.angle(root * np.conj(p))))) < 1e-6


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_delay_and_length(line):
    tau = metrics.delay_from_phase(FREQ, line.s[:, 1, 0])
    assert abs(tau - DELAY) < 5e-12
    assert abs(metrics.physical_length(DELAY, 1.0) - 0.08994) < 1e-4
    assert abs(metrics.physical_length(DELAY, 4.0) - 0.04497) < 1e-4


def test_tdr_impedance_of_open_line(line):
    z = metrics.tdr_impedance(FREQ, one_port(line, +1.0), DELAY)
    assert abs(z - ZC) < 2.0


# ---------------------------------------------------------------------------
# reflect
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("load, gamma_load", [("OPEN_A", 1.0), ("SHORT_A", -1.0)])
def test_fixture_from_single_reflect(line, load, gamma_load):
    result = reflect.fixture_from_reflect(FREQ, one_port(line, gamma_load), load)
    mag, phase = errors(result.network.s[:, 1, 0], line.s[:, 1, 0])
    assert mag < 0.3, f"{load}: {mag:.3f} dB"
    assert phase < 3.0, f"{load}: {phase:.2f} deg"
    assert abs(result.delay_ps - DELAY * 1e12) < 5.0
    assert abs(result.impedance_ohm - ZC) < 2.0
    assert result.quality["passive"]


def test_fixture_from_open_short(line):
    result = reflect.fixture_from_open_short(
        FREQ, one_port(line, +1.0), one_port(line, -1.0)
    )
    mag, phase = errors(result.network.s[:, 1, 0], line.s[:, 1, 0])
    assert mag < 0.3
    assert phase < 3.0
    assert abs(result.delay_ps - DELAY * 1e12) < 5.0
    assert result.quality["open_short_mag_db"] < 0.3
    assert result.quality["model"] == "single_discontinuity"
    assert result.length_mm is None
    result.with_length(1.0)
    assert abs(result.length_mm - 89.94) < 0.5


def test_single_discontinuity_beats_first_order_on_mismatch():
    """Fixture court et desadapte : le modele exact doit nettement l'emporter."""

    freq = np.arange(10e6, 200e9 + 1, 50e6)
    line = synthetic_line(freq=freq, zc=100.0, delay=20e-12, loss_db_10ghz=2.0)
    gamma = one_port(line, +1.0)

    exact = reflect.fixture_from_reflect(freq, gamma, "OPEN")
    first = reflect.fixture_from_reflect(freq, gamma, "OPEN", model="first_order")

    band = freq >= 4e9
    ref = line.s[band, 1, 0]

    def worst(result):
        est = result.network.s[band, 1, 0]
        return float(np.max(np.abs(20 * np.log10(np.abs(est)) - 20 * np.log10(np.abs(ref)))))

    assert worst(exact) < 0.6
    assert worst(exact) < 0.3 * worst(first)
    assert exact.quality["model"] == "single_discontinuity"


def test_gamma1_from_open_short_is_exact():
    """Sur une ligne, G1 resolu algebriquement vaut (Zc - Z0) / (Zc + Z0)."""

    freq = np.arange(1e9, 50e9 + 1, 100e6)
    line = synthetic_line(freq=freq, zc=ZC, delay=DELAY, loss_db_10ghz=0.0)
    g1 = reflect.gamma1_from_open_short(one_port(line, +1.0), one_port(line, -1.0))

    expected = (ZC - 50.0) / (ZC + 50.0)
    assert np.max(np.abs(g1 - expected)) < 1e-6


def test_deembed_input_inverts_the_model():
    """La transformation de Moebius redonne exactement P^2."""

    freq = np.arange(1e9, 50e9 + 1, 100e6)
    g1 = 0.2 + 0.05j
    p2 = np.exp(-2j * np.pi * freq * DELAY) ** 2 * 0.8

    for gl in (1.0, -1.0):
        gamma = g1 + (1 - g1 ** 2) * p2 * gl / (1 + g1 * p2 * gl)
        assert np.max(np.abs(reflect.deembed_input(gamma, g1) / gl - p2)) < 1e-9


def test_bandpass_mode_on_banded_measurement():
    """Mesure d'extenseur 140-220 GHz : aucune extrapolation vers DC."""

    freq = np.arange(140e9, 220e9 + 1, 100e6)
    line = synthetic_line(freq=freq, delay=300e-12, loss_db_10ghz=2.0)
    result = reflect.fixture_from_reflect(freq, one_port(line, +1.0), "OPEN")

    assert result.quality["mode"] == "bandpass"
    est, ref = result.network.s[:, 1, 0], line.s[:, 1, 0]
    mag = np.max(np.abs(20 * np.log10(np.abs(est)) - 20 * np.log10(np.abs(ref))))
    assert mag < 0.5, f"{mag:.2f} dB"
    assert abs(result.delay_ps - 300.0) < 5.0
    # pas de continu : l'impedance vient de la reflexion proche, pas de la TDR
    assert result.quality["impedance_source"] == "gamma1"
    assert abs(result.impedance_ohm - ZC) < 3.0


def test_passivity_clamp_uses_singular_values():
    """Le critere est max(|a+b|, |a-b|) <= 1, pas |a|^2 + |b|^2 <= 1."""

    s11 = np.array([0.30 + 0j, 0.10 + 0.20j, 0.05 + 0j])
    s21 = np.array([0.95 + 0j, 1.20 - 0.30j, 0.40 + 0j])

    clamped, count = afr_signal.clamp_passive(s21, s11)
    assert count == 2                       # le troisieme point est deja passif

    for a, b in zip(s11, clamped):
        assert max(abs(a + b), abs(a - b)) <= 1.0 + 1e-9

    # la phase est conservee, seul le module est reduit
    assert abs(np.angle(clamped[1]) - np.angle(s21[1])) < 1e-12
    # l'ancien critere |a|^2 + |b|^2 <= 1 aurait laisse passer le premier point
    assert abs(s11[0]) ** 2 + abs(s21[0]) ** 2 < 1.0
    assert abs(clamped[0]) < abs(s21[0])


def test_clamp_unit_and_smoothing():
    bounded, count = afr_signal.clamp_unit(np.array([1.4 + 0j, 0.9 + 0j, 1.01 + 0j]))
    assert count == 2
    assert np.all(np.abs(bounded) <= 1.0 + 1e-12)
    assert abs(np.angle(bounded[0])) < 1e-12

    freq = np.arange(1e9, 20e9 + 1, 50e6)
    smooth = afr_signal.smooth_db_phase(np.exp(-2j * np.pi * freq * DELAY), 21)
    assert np.max(np.abs(np.abs(smooth) - 1.0)) < 1e-6


def test_gate_overlap_is_flagged():
    """Fixture trop court pour la bande : chevauchement des fenetres signale."""

    freq = np.arange(10e6, 40e9 + 1, 20e6)
    line = synthetic_line(freq=freq, delay=5e-12, loss_db_10ghz=1.0)
    result = reflect.fixture_from_reflect(freq, one_port(line, +1.0), "OPEN")
    assert "warning" in result.quality


def test_gamma_load_labels():
    assert reflect.gamma_load("OPEN_B") == 1.0
    assert reflect.gamma_load("c:/mesures/short_a.s1p") == -1.0
    with pytest.raises(ValueError):
        reflect.gamma_load("LOAD")


# ---------------------------------------------------------------------------
# thru
# ---------------------------------------------------------------------------

def test_split_2x_thru(line):
    two_x = line ** line
    half_in, half_out, info = thru.split_2x_thru(two_x)
    mag, phase = errors(half_in.s[:, 1, 0], line.s[:, 1, 0])
    assert mag < 0.3
    assert phase < 3.0
    assert abs(info["delay1"] - DELAY * 1e12) < 5.0
    assert abs(info["delay_total_ps"] - 2 * DELAY * 1e12) < 10.0
    assert abs(info["z1"] - ZC) < 2.0
    # port-swap : S11 de out = S22 de in
    assert np.allclose(half_out.s[:, 0, 0], half_in.s[:, 1, 1])


def test_model_fit_detects_a_fixture_the_model_cannot_describe():
    """
    L'indicateur d'ajustement doit rester tres bon sur une ligne simple et se
    degrader nettement sur un fixture a deux discontinuites fortes.
    """

    simple = synthetic_line(zc=55.0, delay=300e-12, loss_db_10ghz=1.0)
    good = reflect.fixture_from_reflect(FREQ, one_port(simple, +1.0), "OPEN")
    assert good.quality["fit_rms"] < 0.02
    assert "fit_warning" not in good.quality

    # deux tronçons tres desadaptes en serie : le modele a une seule
    # discontinuite ne peut pas decrire ce fixture
    first = synthetic_line(zc=90.0, delay=150e-12, loss_db_10ghz=0.5)
    second = synthetic_line(zc=25.0, delay=150e-12, loss_db_10ghz=0.5)
    hard = first ** second

    bad = reflect.fixture_from_reflect(FREQ, one_port(hard, +1.0), "OPEN")
    assert bad.quality["fit_rms"] > good.quality["fit_rms"]


def test_predict_reflect_round_trip(line):
    """Le modele applique au fixture de reference redonne la mesure 1 port."""

    for gl in (1.0, -1.0):
        assert np.max(np.abs(reflect.predict_reflect(line, gl) - one_port(line, gl))) < 1e-12


# ---------------------------------------------------------------------------
# chaine complete : ligne A + DUT + ligne B
# ---------------------------------------------------------------------------

def test_full_chain_deembedding(asymmetric):
    """
    Mesure brute ligne A + DUT + ligne B, corrigee avec les fixtures EXTRAITS
    de leurs propres standards OPEN et SHORT. C'est le parcours reel.
    """

    fixture_in, fixture_out, side_b, _ = asymmetric
    dut = synthetic_line(zc=62.0, delay=80e-12, loss_db_10ghz=0.4)
    raw = deembed.embed_fixtures(dut, fixture_in, fixture_out)

    extracted_a = reflect.fixture_from_open_short(
        FREQ, one_port(fixture_in, +1.0), one_port(fixture_in, -1.0)
    ).network
    extracted_b = thru.as_output_fixture(
        reflect.fixture_from_open_short(
            FREQ, one_port(side_b, +1.0), one_port(side_b, -1.0)
        ).network
    )

    recovered = deembed.remove_fixtures(raw, extracted_a, extracted_b)

    band = (FREQ >= 1e9) & (FREQ <= 15e9)
    est, ref = recovered.s[band, 1, 0], dut.s[band, 1, 0]
    mag = np.max(np.abs(20 * np.log10(np.abs(est)) - 20 * np.log10(np.abs(ref))))
    phase = np.max(np.abs(np.degrees(np.angle(est * np.conj(ref)))))

    assert mag < 0.2, f"{mag:.3f} dB"
    assert phase < 1.0
    assert metrics.quality_report(recovered.s)["passive"]

    # la correction doit bien retirer de la perte, pas en ajouter
    gain = 20 * np.log10(np.abs(est)) - 20 * np.log10(np.abs(raw.s[band, 1, 0]))
    assert np.mean(gain) > 0.5


def test_identity_removal_changes_nothing(asymmetric):
    """Ne retirer aucun fixture doit laisser la mesure inchangee."""

    fixture_in, fixture_out, _, _ = asymmetric
    dut = synthetic_line(zc=62.0, delay=80e-12)
    raw = deembed.embed_fixtures(dut, fixture_in, fixture_out)

    assert np.max(np.abs(deembed.remove_fixtures(raw, None, None).s - raw.s)) < 1e-12


# ---------------------------------------------------------------------------
# fixtures asymetriques (deux lignes de longueurs differentes)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def asymmetric():
    """Entree : 55 ohm / 300 ps. Sortie : 48 ohm / 120 ps. Rien de symetrique."""

    fixture_in = synthetic_line(zc=55.0, delay=300e-12, loss_db_10ghz=1.0)
    side_b = synthetic_line(zc=48.0, delay=120e-12, loss_db_10ghz=0.6)
    fixture_out = thru.as_output_fixture(side_b)
    return fixture_in, fixture_out, side_b, fixture_in ** fixture_out


def test_missing_side_is_exact_from_thru(asymmetric):
    fixture_in, fixture_out, _, two_x = asymmetric

    deduced_out = thru.fixture_out_from_thru(two_x, fixture_in)
    assert np.max(np.abs(deduced_out.s - fixture_out.s)) < 1e-9

    deduced_in = thru.fixture_in_from_thru(two_x, fixture_out)
    assert np.max(np.abs(deduced_in.s - fixture_in.s)) < 1e-9


def test_pair_residual_is_zero_for_the_true_pair(asymmetric):
    fixture_in, fixture_out, _, two_x = asymmetric
    report = thru.pair_residual(two_x, fixture_in, fixture_out)
    assert report["thru_s21_db"] < 1e-6
    assert report["thru_s21_deg"] < 1e-6


def test_symmetric_split_is_wrong_on_asymmetric_thru(asymmetric):
    """Le decoupage en deux moities identiques ne convient pas ici."""

    fixture_in, _, _, two_x = asymmetric
    half_in, _, _ = thru.split_2x_thru(two_x)

    band = (FREQ >= 1e9) & (FREQ <= 15e9)
    gap = np.max(np.abs(
        20 * np.log10(np.abs(half_in.s[band, 1, 0]))
        - 20 * np.log10(np.abs(fixture_in.s[band, 1, 0]))
    ))
    assert gap > 1.0, "le cas asymetrique devrait justement etre mal traite ainsi"


def test_complete_pair_selects_the_right_route(asymmetric):
    fixture_in, fixture_out, side_b, two_x = asymmetric

    _, _, info = thru.complete_pair(fixture_in=fixture_in, fixture_out=fixture_out)
    assert info["method"] == "reflect_both_sides"

    a, b, info = thru.complete_pair(thru=two_x, fixture_in=fixture_in)
    assert info["method"] == "reflect_in_plus_thru"
    assert np.max(np.abs(b.s - fixture_out.s)) < 1e-9
    assert info["residual"]["thru_s21_db"] < 1e-6

    a, b, info = thru.complete_pair(thru=two_x, fixture_out=fixture_out)
    assert info["method"] == "reflect_out_plus_thru"
    assert np.max(np.abs(a.s - fixture_in.s)) < 1e-9

    _, _, info = thru.complete_pair(thru=two_x)
    assert info["method"] == "thru_symmetric_split"
    assert "warning" in info

    _, _, info = thru.complete_pair(fixture_in=fixture_in)
    assert info["method"] == "reflect_in_mirrored"
    assert "warning" in info

    with pytest.raises(ValueError):
        thru.complete_pair()


def test_asymmetric_extraction_from_open_and_thru(asymmetric):
    """OPEN du seul cote entree + 2x-thru : les deux fixtures sont retrouves."""

    fixture_in, fixture_out, _, two_x = asymmetric

    extracted_in = reflect.fixture_from_reflect(
        FREQ, one_port(fixture_in, +1.0), "OPEN"
    ).network

    a, b, info = thru.complete_pair(thru=two_x, fixture_in=extracted_in)
    assert info["method"] == "reflect_in_plus_thru"

    band = (FREQ >= 1e9) & (FREQ <= 15e9)
    for estimated, reference in ((a, fixture_in), (b, fixture_out)):
        gap = np.max(np.abs(
            20 * np.log10(np.abs(estimated.s[band, 1, 0]))
            - 20 * np.log10(np.abs(reference.s[band, 1, 0]))
        ))
        assert gap < 0.5, f"{gap:.3f} dB"


def test_check_fixtured_dut(asymmetric):
    fixture_in, fixture_out, _, _ = asymmetric
    dut = synthetic_line(zc=62.0, delay=80e-12, loss_db_10ghz=0.4)
    measured = deembed.embed_fixtures(dut, fixture_in, fixture_out)

    report = thru.check_fixtured_dut(measured, fixture_in, fixture_out)
    assert report["passive"]
    assert report["reconstruction"] < 1e-9
    assert np.max(np.abs(report["network"].s - dut.s)) < 1e-9


# ---------------------------------------------------------------------------
# deembed
# ---------------------------------------------------------------------------

def test_remove_fixtures_roundtrip(line):
    dut = synthetic_line(zc=62.0, delay=120e-12, loss_db_10ghz=0.4)
    fixture_out = thru.port_swap(line)
    measured = deembed.embed_fixtures(dut, line, fixture_out)
    recovered = deembed.remove_fixtures(measured, line, fixture_out)
    assert np.max(np.abs(recovered.s - dut.s)) < 1e-6


def test_batch_deembed(tmp_path, line):
    dut = synthetic_line(zc=62.0, delay=120e-12, loss_db_10ghz=0.4)
    fixture_out = thru.port_swap(line)
    measured = deembed.embed_fixtures(dut, line, fixture_out)

    src = tmp_path / "in"
    src.mkdir()
    measured.write_touchstone(str(src / "dut1"))
    (src / "bad.s2p").write_text("! fichier vide\n", encoding="utf-8")

    items = deembed.batch_deembed(src, tmp_path / "out", "*.s2p", line, fixture_out)
    by_name = {item.source.name: item for item in items}
    assert by_name["dut1.s2p"].ok
    assert by_name["dut1.s2p"].output.is_file()
    assert not by_name["bad.s2p"].ok
