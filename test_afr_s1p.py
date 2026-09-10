"""
Validation de build_afr_s2p_from_s1p sur un fixture synthetique.

Un fixture = ligne de transmission (Zc = 55 ohm, 300 ps, pertes en sqrt(f))
entre deux ports 50 ohm. On simule la mesure 1 port du fixture termine par
un OPEN puis par un SHORT, on reconstruit le S2P avec la methode AFR et on
compare au S2P exact de la ligne.

Usage :  python test_afr_s1p.py
(numpy, scipy, scikit-rf et pywt doivent etre installes, comme pour
 matrice_et_branche.py ; aucune fenetre Tk n'est ouverte)
"""

import os
import tempfile

import numpy as np
import skrf as rf

import matrice_et_branche as mb


class FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class AFRStub:
    """Expose les methodes de calcul sans instancier la fenetre Tk."""

    enable_filter = FakeVar(False)
    filter_method = FakeVar("None")
    enable_interpolation = FakeVar(True)
    interpolation_method = FakeVar("Linear")


for _name in (
    "uniform_grid_with_dc",
    "interpolate_complex_data",
    "to_time_domain",
    "raised_cosine_gate",
    "gate_to_freq",
    "complex_sqrt_half_phase",
    "reflect_coefficient",
    "build_afr_s2p_from_s1p",
    "apply_filter",
    "s11_to_z",
):
    setattr(AFRStub, _name, getattr(mb.AFRWizardComplete, _name))


def synthetic_line(freq, zc=55.0, delay=300e-12, loss_db_at_10ghz=1.0, z0=50.0):
    """S2P exact d'une ligne Zc, delai `delay`, pertes ~ sqrt(f)."""

    w = 2 * np.pi * freq
    alpha = (loss_db_at_10ghz / 8.686) * np.sqrt(np.maximum(freq, 1.0) / 10e9)
    gamma_l = alpha + 1j * w * delay

    a = np.cosh(gamma_l)
    b = zc * np.sinh(gamma_l)
    c = np.sinh(gamma_l) / zc
    d = a

    abcd = np.zeros((len(freq), 2, 2), dtype=complex)
    abcd[:, 0, 0] = a
    abcd[:, 0, 1] = b
    abcd[:, 1, 0] = c
    abcd[:, 1, 1] = d

    s = rf.a2s(abcd, z0=z0)
    return rf.Network(frequency=rf.Frequency.from_f(freq, unit="hz"), s=s, z0=z0)


def one_port_measurement(net, gamma_load):
    s11 = net.s[:, 0, 0]
    s21 = net.s[:, 1, 0]
    s12 = net.s[:, 0, 1]
    s22 = net.s[:, 1, 1]
    return s11 + s21 * s12 * gamma_load / (1.0 - s22 * gamma_load)


def write_s1p(path, freq, gamma, z0=50.0):
    s = gamma.reshape(-1, 1, 1)
    net = rf.Network(frequency=rf.Frequency.from_f(freq, unit="hz"), s=s, z0=z0)
    net.write_touchstone(os.path.splitext(path)[0])


def compare(name, est, ref, freq, fmin=0.5e9, fmax=15e9):
    band = (freq >= fmin) & (freq <= fmax)
    mag_err = 20 * np.log10(np.abs(est[band])) - 20 * np.log10(np.abs(ref[band]))
    phase_err = np.degrees(np.angle(est[band] * np.conj(ref[band])))
    print(
        f"{name}: |dB| max = {np.max(np.abs(mag_err)):.3f} dB, "
        f"phase max = {np.max(np.abs(phase_err)):.2f} deg "
        f"(bande {fmin/1e9:.1f}-{fmax/1e9:.1f} GHz)"
    )
    return np.max(np.abs(mag_err)), np.max(np.abs(phase_err))


def main():
    freq = np.arange(10e6, 20e9 + 1, 10e6)

    fixture = synthetic_line(freq)
    s21_ref = fixture.s[:, 1, 0]

    stub = AFRStub()

    ok = True

    with tempfile.TemporaryDirectory() as tmp:

        for label, gamma_load in (("OPEN_A", 1.0), ("SHORT_A", -1.0)):

            path = os.path.join(tmp, f"{label}.s1p")
            write_s1p(path, freq, one_port_measurement(fixture, gamma_load))

            net, z_mean, delay_ps = stub.build_afr_s2p_from_s1p(
                path,
                reflect_type=label
            )

            print("================================")
            print(label)
            print("================================")

            mag_err, phase_err = compare(
                f"{label} S21",
                net.s[:, 1, 0],
                s21_ref,
                freq
            )

            print(f"{label} Z = {z_mean:.2f} ohm (attendu ~55)")
            print(f"{label} delay = {delay_ps:.1f} ps (attendu ~300)")

            if mag_err > 0.5 or phase_err > 5.0:
                ok = False
            if abs(z_mean - 55.0) > 3.0:
                ok = False
            if abs(delay_ps - 300.0) > 10.0:
                ok = False

    print("================================")
    print("RESULT :", "OK" if ok else "FAILED")
    print("================================")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
