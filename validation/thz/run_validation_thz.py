"""
Validation submillimetrique : les deux methodes d'extraction jusqu'a 1 THz.

    python validation/thz/run_validation_thz.py      (depuis la racine du depot)

Pour chaque bande (WR-1.0 750 GHz - 1.1 THz, puis 10 MHz - 1 THz d'un seul
tenant) et chaque jeu de standards (OPEN seul, SHORT seul, OPEN + SHORT), le
script extrait le S2P avec les deux modeles :

    single_discontinuity : exact, mais |S21| est porte par l'echo fenetre,
                           donc par le rapport signal / bruit a cet instant ;
    line_fit             : le meme echo est ajuste par un modele de ligne,
                           ce qui moyenne le bruit sur toute la bande.

Les S2P extraits sont ecrits a cote des fichiers sources : ils se comparent
directement a FIXTURE_*_reference.s2p dans un simulateur.

Les fichiers sources sont produits par ``generate_thz.py`` (Python standard,
sans dependance) ; ils portent un bruit de mesure de -40 dB, representatif
d'un VNA a extenseurs dans ces bandes.
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from afr import io as afr_io          # noqa: E402
from afr import reflect               # noqa: E402

REFERENCE = {"zc": 55.0, "delay_ps": 300.0, "eps_r_eff": 3.0}

CASES = [
    ("WR1", "WR-1.0  750 GHz - 1.1 THz"),
    ("BROADBAND", "10 MHz - 1 THz"),
]

MODELS = ("single_discontinuity", "line_fit")

# Tolerances : le modele de ligne doit rester sous 0.5 dB malgre le bruit.
TOLERANCE_DB = 0.5
TOLERANCE_DEG = 5.0


def band_mask(f, margin=0.05):
    """Bande utile : on ecarte 5 % a chaque bord, ou le fenetrage est aveugle."""

    span = f[-1] - f[0]
    return (f >= f[0] + margin * span) & (f <= f[-1] - margin * span)


def compare(estimated, reference):
    f = reference.f
    band = band_mask(f)

    est, ref = estimated.s[band, 1, 0], reference.s[band, 1, 0]
    magnitude = float(np.max(np.abs(20 * np.log10(np.abs(est))
                                    - 20 * np.log10(np.abs(ref)))))
    phase = float(np.max(np.abs(np.degrees(np.angle(est * np.conj(ref))))))
    s11 = float(np.max(np.abs(np.abs(estimated.s[band, 0, 0])
                              - np.abs(reference.s[band, 0, 0]))))
    return magnitude, phase, s11


def extract(f, gamma_open, gamma_short, standards, model):
    if standards == "OPEN seul":
        return reflect.fixture_from_reflect(f, gamma_open, "OPEN", model=model)
    if standards == "SHORT seul":
        return reflect.fixture_from_reflect(f, gamma_short, "SHORT", model=model)
    return reflect.fixture_from_open_short(f, gamma_open, gamma_short, model=model)


def run_case(name, title):
    reference = afr_io.load_network(HERE / f"FIXTURE_{name}_reference.s2p", 2)
    gamma_open = afr_io.load_network(HERE / f"OPEN_{name}.s1p", 1).s[:, 0, 0]
    gamma_short = afr_io.load_network(HERE / f"SHORT_{name}.s1p", 1).s[:, 0, 0]
    f = reference.f

    print("=" * 100)
    print(f"{title}   ({len(f)} points, {f[0] / 1e9:.3f} - {f[-1] / 1e9:.0f} GHz)")
    print("=" * 100)

    ok = True
    for standards in ("OPEN seul", "SHORT seul", "OPEN+SHORT"):
        for model in MODELS:
            result = extract(f, gamma_open, gamma_short, standards, model)
            result.with_length(REFERENCE["eps_r_eff"])

            magnitude, phase, s11 = compare(result.network, reference)
            snr = result.quality.get("echo_snr_db", float("nan"))

            print(f"{standards:11s} {model:20s} |S21| {magnitude:7.3f} dB   "
                  f"phase {phase:6.2f} deg   |S11| {s11:.4f}   "
                  f"TTD {result.delay_ps:6.1f} ps   echo/bruit {snr:5.1f} dB")

            if result.quality.get("dynamic_range_warning") and model == MODELS[0]:
                print(f"{'':32s} plage dynamique limitee : l'echo est proche du bruit")

            afr_io.write_network(
                result.network,
                HERE / f"FIXTURE_{name}_{standards.split()[0].replace('+', '_')}_{model}",
                "ri",
            )

            if model == "line_fit":
                ok &= magnitude < TOLERANCE_DB and phase < TOLERANCE_DEG

    print()
    return ok


def main():
    ok = True
    for name, title in CASES:
        if not (HERE / f"FIXTURE_{name}_reference.s2p").is_file():
            print(f"Fichiers {name} absents : lancer d'abord generate_thz.py")
            return 1
        ok &= run_case(name, title)

    print("Reference : Zc = 55 ohm, TTD = 300 ps, pertes 2 dB @10 GHz (~sqrt(f)).")
    print("Attendu : 'single_discontinuity' derive de plusieurs dB des que l'echo")
    print("approche le plancher de bruit ; 'line_fit' reste sous "
          f"{TOLERANCE_DB} dB sur les deux bandes.")
    print("RESULTAT :", "OK" if ok else "ECARTS AU-DELA DES TOLERANCES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
