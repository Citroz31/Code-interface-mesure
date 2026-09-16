"""
Generation du jeu de validation submillimetrique (jusqu'a 1 THz).

    python validation/thz/generate_thz.py          (depuis la racine du depot)

Script volontairement sans dependance (Python standard seul) : il peut etre
relance ailleurs pour regenerer exactement les memes fichiers, ou modifie pour
produire un autre fixture.

Modele : ligne de transmission uniforme entre deux ports 50 ohm,

    alpha(f) = (perte_dB_a_10GHz / 8.686) * sqrt(f / 10 GHz)     [Np]
    gamma(f) = alpha(f) + j 2 pi f tau

Les mesures 1 port OPEN et SHORT recoivent un bruit gaussien complexe de
niveau ``NOISE_DB`` (plancher typique d'un VNA a extenseurs millimetriques),
tire avec une graine fixe : c'est ce bruit, et non le modele, qui limite
l'extraction au-dela de 500 GHz.
"""

import cmath
import math
import os
import random

Z0 = 50.0
NOISE_DB = -40.0          # plancher de bruit des mesures 1 port
SEED = 2024

HERE = os.path.dirname(os.path.abspath(__file__))

# Fixture commun aux deux bandes : ligne longue et tres dissipative a 1 THz.
ZC = 55.0                 # ohm
TAU = 300e-12             # s, delai aller
LOSS_DB_10GHZ = 2.0       # dB de perte totale a 10 GHz, variation en sqrt(f)
EPS_R_EFF = 3.0

CASES = [
    # nom, f_start, f_stop, pas
    ("WR1", 750e9, 1100e9, 250e6),          # bande WR-1.0 (750 GHz - 1.1 THz)
    ("BROADBAND", 10e6, 1000e9, 500e6),     # 10 MHz - 1 THz d'un seul tenant
]


def line_abcd(f, zc=ZC, tau=TAU, loss=LOSS_DB_10GHZ):
    alpha = (loss / 8.686) * math.sqrt(max(f, 1.0) / 10e9)
    gamma = complex(alpha, 2 * math.pi * f * tau)
    ch, sh = cmath.cosh(gamma), cmath.sinh(gamma)
    return ch, zc * sh, sh / zc, ch


def abcd_to_s(a, b, c, d, z0=Z0):
    den = a + b / z0 + c * z0 + d
    return ((a + b / z0 - c * z0 - d) / den,
            2.0 / den,
            2.0 * (a * d - b * c) / den,
            (-a + b / z0 - c * z0 + d) / den)


def one_port(s, gamma_load):
    s11, s21, s12, s22 = s
    return s11 + s21 * s12 * gamma_load / (1.0 - s22 * gamma_load)


def add_noise(values, level_db, rng):
    sigma = 10.0 ** (level_db / 20.0) / math.sqrt(2.0)
    return [v + complex(rng.gauss(0.0, sigma), rng.gauss(0.0, sigma)) for v in values]


def write_s1p(path, freq, gamma, comment):
    with open(path, "w", encoding="ascii") as handle:
        handle.write(f"! {comment}\n! Frequency(Hz) Re(S11) Im(S11)\n# Hz S RI R 50\n")
        for f, g in zip(freq, gamma):
            handle.write(f"{f:.6e} {g.real:.9e} {g.imag:.9e}\n")


def write_s2p(path, freq, s, comment):
    with open(path, "w", encoding="ascii") as handle:
        handle.write(f"! {comment}\n! Frequency(Hz) S11 S21 S12 S22 (Re Im)\n"
                     f"# Hz S RI R 50\n")
        for f, (s11, s21, s12, s22) in zip(freq, s):
            handle.write(f"{f:.6e} {s11.real:.9e} {s11.imag:.9e} "
                         f"{s21.real:.9e} {s21.imag:.9e} "
                         f"{s12.real:.9e} {s12.imag:.9e} "
                         f"{s22.real:.9e} {s22.imag:.9e}\n")


def main():
    rng = random.Random(SEED)
    length_mm = 299792458.0 * TAU / math.sqrt(EPS_R_EFF) * 1e3

    description = (f"ligne Zc={ZC:.0f} ohm, delai={TAU * 1e12:.0f} ps, pertes "
                   f"{LOSS_DB_10GHZ:.1f} dB @10 GHz (~sqrt(f)), eps_r_eff={EPS_R_EFF:.1f} "
                   f"-> {length_mm:.2f} mm, Z0=50 ohm")

    for name, f_start, f_stop, step in CASES:
        count = int(round((f_stop - f_start) / step)) + 1
        freq = [f_start + k * step for k in range(count)]
        fixture = [abcd_to_s(*line_abcd(f)) for f in freq]

        gamma_open = add_noise([one_port(s, +1.0) for s in fixture], NOISE_DB, rng)
        gamma_short = add_noise([one_port(s, -1.0) for s in fixture], NOISE_DB, rng)

        band = (f"{f_start / 1e9:.3f} - {f_stop / 1e9:.0f} GHz, pas {step / 1e6:.0f} MHz, "
                f"{count} points, bruit {NOISE_DB:.0f} dB")

        write_s1p(os.path.join(HERE, f"OPEN_{name}.s1p"), freq, gamma_open,
                  f"Fixture THz termine par un OPEN ideal : {description} ; {band}")
        write_s1p(os.path.join(HERE, f"SHORT_{name}.s1p"), freq, gamma_short,
                  f"Fixture THz termine par un SHORT ideal : {description} ; {band}")
        write_s2p(os.path.join(HERE, f"FIXTURE_{name}_reference.s2p"), freq, fixture,
                  f"Reference exacte (sans bruit) : {description} ; {band}")

        one_way = 20 * math.log10(abs(fixture[-1][1]))
        print(f"{name:10s} {count:5d} points, {band}, "
              f"|S21| a f_max {one_way:6.1f} dB -> echo a {2 * one_way:6.1f} dB")


if __name__ == "__main__":
    main()
