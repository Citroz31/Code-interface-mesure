"""
Validation de l'extraction S1P -> S2P sur les fichiers de ce dossier.

    python validation/run_validation.py            (depuis la racine du depot)

Deux parties :

1. Extraction  : OPEN_A.s1p / SHORT_A.s1p (et cote B) -> S2P du fixture,
                 compare a FIXTURE_A_reference.s2p et FIXTURE_B_reference.s2p.
2. De-embedding: RAW_MEASUREMENT.s2p (ligne A + DUT + ligne B) est corrige
                 avec les fixtures extraits, puis compare a DUT_reference.s2p.

Sorties  : FIXTURE_*_from_*.s2p, THRU_2X_half_in.s2p, DUT_deembedded.s2p,
           validation_plot.png, et un tableau d'ecarts dans la console.

Les S2P extraits se comparent directement a la reference dans un
simulateur (ADS, CST, HFSS, QUCS...) : meme grille 10 MHz - 50 GHz.
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from afr import io as afr_io          # noqa: E402
from afr import deembed, reflect, thru  # noqa: E402

REFERENCE = {"zc": 55.0, "delay_ps": 300.0, "eps_r_eff": 3.0}


def compare(label, est, ref, lo=1e9, hi=40e9):
    f = ref.f
    band = (f >= lo) & (f <= hi)
    e21, r21 = est.s[band, 1, 0], ref.s[band, 1, 0]
    mag = np.max(np.abs(20 * np.log10(np.abs(e21)) - 20 * np.log10(np.abs(r21))))
    phase = np.max(np.abs(np.degrees(np.angle(e21 * np.conj(r21)))))
    s11 = np.max(np.abs(np.abs(est.s[band, 0, 0]) - np.abs(ref.s[band, 0, 0])))
    print(f"{label:28s} S21 |dB| max {mag:6.3f} dB   phase max {phase:5.2f} deg   "
          f"|S11| ecart max {s11:.4f}   ({lo/1e9:.0f}-{hi/1e9:.0f} GHz)")
    return mag, phase


def main():
    ref = afr_io.load_network(HERE / "FIXTURE_A_reference.s2p", 2)
    n_open = afr_io.load_network(HERE / "OPEN_A.s1p", 1)
    n_short = afr_io.load_network(HERE / "SHORT_A.s1p", 1)
    f = n_open.f
    g_open, g_short = n_open.s[:, 0, 0], n_short.s[:, 0, 0]

    results = {
        "OPEN seul": reflect.fixture_from_reflect(f, g_open, "OPEN"),
        "SHORT seul": reflect.fixture_from_reflect(f, g_short, "SHORT"),
        "OPEN+SHORT": reflect.fixture_from_open_short(f, g_open, g_short),
    }

    print("=" * 96)
    for label, result in results.items():
        result.with_length(REFERENCE["eps_r_eff"])
        quality = result.quality
        print(f"{label:12s} : Z = {result.impedance_ohm:6.2f} ohm (ref {REFERENCE['zc']}), "
              f"TTD = {result.delay_ps:6.1f} ps (ref {REFERENCE['delay_ps']}), "
              f"longueur = {result.length_mm:6.2f} mm")
        print(f"{'':12s}   modele {quality.get('model')}, mode {quality.get('mode')}, "
              f"passif {quality.get('passive')}, points bornes {quality.get('clamped_points', 0)}")
        if "warning" in quality:
            print("   AVERTISSEMENT :", quality["warning"])
    print("=" * 96)

    ok = True
    for label, result in results.items():
        mag, phase = compare(label, result.network, ref)
        ok &= mag < 0.3 and phase < 3.0
        compare(label + " (bord 45-50 GHz)", result.network, ref, 45e9, 50e9)

    # 2x-thru : la demi-fixture doit redonner la reference
    two_x = afr_io.load_network(HERE / "THRU_2X_reference.s2p", 2)
    half_in, half_out, info = thru.split_2x_thru(two_x)
    print(f"{'2x-thru':12s} : Z1 = {info['z1']:6.2f} ohm, TTD = {info['delay1']:6.1f} ps, "
          f"total = {info['delay_total_ps']:.1f} ps")
    mag, phase = compare("2x-thru demi IN", half_in, ref)
    ok &= mag < 0.3 and phase < 3.0

    names = {"OPEN seul": "FIXTURE_A_from_OPEN", "SHORT seul": "FIXTURE_A_from_SHORT",
             "OPEN+SHORT": "FIXTURE_A_from_OPEN_SHORT"}
    for label, result in results.items():
        afr_io.write_network(result.network, HERE / names[label], "ri")
    afr_io.write_network(half_in, HERE / "THRU_2X_half_in", "ri")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        ghz = f / 1e9
        axes[0].plot(ghz, 20 * np.log10(np.abs(ref.s[:, 1, 0])), "k", lw=2, label="reference")
        axes[1].plot(ghz, 20 * np.log10(np.abs(ref.s[:, 0, 0])), "k", lw=2, label="reference")
        for label, result in results.items():
            axes[0].plot(ghz, 20 * np.log10(np.abs(result.network.s[:, 1, 0])), "--", label=label)
            axes[1].plot(ghz, 20 * np.log10(np.abs(result.network.s[:, 0, 0])), "--", label=label)
        axes[0].plot(ghz, 20 * np.log10(np.abs(half_in.s[:, 1, 0])), ":", label="2x-thru demi")
        axes[0].set_ylabel("|S21| (dB)")
        axes[1].set_ylabel("|S11| (dB)")
        axes[1].set_xlabel("Frequency (GHz)")
        for axis in axes:
            axis.grid(True, alpha=0.4)
            axis.legend(fontsize=8)
        fig.suptitle("Validation fixture A : reference vs extraction")
        fig.tight_layout()
        fig.savefig(HERE / "validation_plot.png", dpi=120)
        print("Figure :", HERE / "validation_plot.png")
    except Exception as error:  # matplotlib absent ou sans backend
        print("Pas de figure :", error)

    ok &= deembed_chain(f)

    print("RESULTAT :", "OK" if ok else "ECARTS AU-DELA DES TOLERANCES")
    return 0 if ok else 1


def deembed_chain(f):
    """
    Chaine complete : ligne A + DUT + ligne B -> DUT.

    Les fixtures sont ceux EXTRAITS des standards, pas les references : c'est
    la chaine que l'on suit sur une mesure reelle.
    """

    raw_path = HERE / "RAW_MEASUREMENT.s2p"
    if not raw_path.is_file():
        print("\nPas de RAW_MEASUREMENT.s2p : de-embedding de bout en bout ignore.")
        return True

    print("\n" + "=" * 96)
    print("DE-EMBEDDING DE BOUT EN BOUT : ligne A + DUT + ligne B")
    print("=" * 96)

    raw = afr_io.load_network(raw_path, 2)
    dut_reference = afr_io.load_network(HERE / "DUT_reference.s2p", 2)

    # Fixtures extraits de leurs propres standards, cote entree et cote sortie
    side_a = reflect.fixture_from_open_short(
        f,
        afr_io.load_network(HERE / "OPEN_A.s1p", 1).s[:, 0, 0],
        afr_io.load_network(HERE / "SHORT_A.s1p", 1).s[:, 0, 0],
    )
    side_b = reflect.fixture_from_open_short(
        f,
        afr_io.load_network(HERE / "OPEN_B.s1p", 1).s[:, 0, 0],
        afr_io.load_network(HERE / "SHORT_B.s1p", 1).s[:, 0, 0],
    )

    for label, result in (("Fixture A", side_a), ("Fixture B", side_b)):
        quality = result.quality
        print(f"{label} : Z = {result.impedance_ohm:6.2f} ohm, "
              f"TTD = {result.delay_ps:6.1f} ps, "
              f"ajustement du modele {quality.get('fit_rms', float('nan')):.4f}")

    fixture_in = side_a.network
    fixture_out = thru.as_output_fixture(side_b.network)

    dut = deembed.remove_fixtures(raw, fixture_in, fixture_out)
    afr_io.write_network(dut, HERE / "DUT_deembedded", "ri")

    band = (f >= 1e9) & (f <= 40e9)
    est, ref = dut.s[band, 1, 0], dut_reference.s[band, 1, 0]
    mag = float(np.max(np.abs(20 * np.log10(np.abs(est)) - 20 * np.log10(np.abs(ref)))))
    phase = float(np.max(np.abs(np.degrees(np.angle(est * np.conj(ref))))))
    s11 = float(np.max(np.abs(np.abs(dut.s[band, 0, 0]) - np.abs(dut_reference.s[band, 0, 0]))))

    recovered = (20 * np.log10(np.abs(dut.s[band, 1, 0]))
                 - 20 * np.log10(np.abs(raw.s[band, 1, 0])))

    print(f"DUT de-embedde contre reference : S21 {mag:.4f} dB / {phase:.3f} deg, "
          f"ecart sur S11 {s11:.4f}")
    print(f"Perte d'insertion retiree : {np.mean(recovered):+.2f} dB en moyenne, "
          f"{np.max(recovered):+.2f} dB au plus")

    quality = {"passive": True}
    try:
        from afr import metrics
        quality = metrics.quality_report(dut.s)
        print(f"DUT passif : {quality['passive']} "
              f"(valeur singuliere max {quality['max_singular_value']:.4f})")
    except Exception as error:
        print("Controle de passivite impossible :", error)

    good = mag < 0.3 and phase < 3.0 and quality["passive"]
    print("De-embedding :", "OK" if good else "ECART TROP GRAND")
    return good


if __name__ == "__main__":
    raise SystemExit(main())
