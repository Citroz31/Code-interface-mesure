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
    assert result.quality["open_short_mag_db"] < 0.2
    assert result.length_mm is None
    result.with_length(1.0)
    assert abs(result.length_mm - 89.94) < 0.5


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
