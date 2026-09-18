"""
Etat et logique de l'AFR, sans aucune dependance a l'interface.

Toute la chaine de calcul vit ici : chargement des standards, extraction des
fixtures (S1P OPEN / SHORT ou 2x-thru), assemblage entree / sortie, retrait
des fixtures autour d'un DUT, traitement par lot. L'interface Qt ne fait
qu'appeler ces methodes et afficher ce qu'elles retournent.

Separer ainsi permet de tester le calcul sans ouvrir de fenetre, et de
changer d'interface sans toucher au calcul.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import skrf as rf

from afr import deembed as afr_deembed
from afr import io as afr_io
from afr import metrics as afr_metrics
from afr import reflect as afr_reflect
from afr import signal as afr_signal
from afr import thru as afr_thru

log = logging.getLogger("afr.session")

RAW_LABEL = "DUT measured (fixtures included)"
DEEMBEDDED_LABEL = "DUT de-embedded (fixtures removed)"

# Standards a deux ports ; les autres sont des mesures 1 port.
TWO_PORT_KEYS = ("THRU_", "ASYM_DUT", "FIXTURED_DUT", "DUT")

STANDARD_LABELS = {
    "THRU_LINE1": "2x-thru",
    "THRU_LINE2": "Second 2x-thru",
    "ASYM_DUT": "Fixtured DUT (line A + DUT + line B)",
    "OPEN_A": "Open, fixture A",
    "SHORT_A": "Short, fixture A",
    "OPEN_B": "Open, fixture B",
    "SHORT_B": "Short, fixture B",
}


@dataclass
class Configuration:
    """Choix de la page 1 (ce que l'on mesure et comment)."""

    input_mode: str = "single_ended"          # single_ended | mixed_mode
    measurement_mode: str = "2_ports"         # 2_ports | multiport
    multiport_count: int = 4
    reference_z0_mode: str = "fixed"          # fixed | from_file
    reference_z0_ohm: float = 50.0
    set_system_z0: bool = False
    correct_match_ab: bool = False
    correct_length_ab: bool = False
    band_limited: bool = False
    characterization_fixture_different: bool = False

    # Page 2 : quels standards sont fournis
    use_2x_thru: bool = True
    use_second_2x_thru: bool = False
    use_fixtured_dut: bool = False
    use_open_a: bool = False
    use_short_a: bool = False
    use_open_b: bool = False
    use_short_b: bool = False
    thru_length_mode: str = "known"           # known | estimated
    known_thru_length_ns: float = 0.0


@dataclass
class Extraction:
    """Reglages de la page 3 (comment on extrait)."""

    model: str = "single_discontinuity"       # voir afr.reflect.MODELS
    reflect_usage: str = "auto"               # auto | open | short | combined
    interp_method: str = "Linear"
    enable_interpolation: bool = True
    smooth_points: int = 0
    enforce_passivity: bool = True
    eps_r_eff: float = 1.0

    enable_filter: bool = False
    filter_method: str = "Savitzky-Golay"
    filter_window: int = 11
    filter_order: int = 3
    filter_sigma: float = 2.0
    filter_cutoff: float = 0.2

    export_format: str = "db"                 # db | ma | ri


@dataclass
class Report:
    """Resultat d'une operation : lignes a afficher, avertissements, etat."""

    ok: bool = True
    title: str = ""
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def text(self) -> str:
        body = "\n".join(self.lines)
        if self.warnings:
            body += "\n\nAvertissements :\n" + "\n".join(f"  - {w}" for w in self.warnings)
        return body


class AfrSession:
    """Session de travail complete : etat + operations."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.config = Configuration()
        self.extraction = Extraction()

        self.output_dir = Path(output_dir or (Path.cwd() / "Results"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.standard_files: dict[str, str] = {}

        self.fixture_results: dict = {}        # cle -> FixtureResult
        self.extracted_info: dict = {}         # cle -> dict affichable
        self.converted_files: dict = {}
        self.thru_networks: dict = {}
        self.fixture_pairs: dict = {}
        self.networks: dict = {}               # tout ce qui est tracable

        self.fixture_a_network = None
        self.fixture_b_network = None
        self.fixture_assembly: dict = {}

        self.raw_measurement = None
        self.deembedded_network = None

        self.warnings: list[str] = []
        self.extraction_done = False

    # ------------------------------------------------------------------
    # Reglages
    # ------------------------------------------------------------------

    def extraction_options(self) -> dict:
        """Options communes passees a ``afr.reflect``."""

        return dict(
            interp_method=self.interpolation_name(),
            smooth_points=max(0, int(self.extraction.smooth_points)),
            enforce_passivity=bool(self.extraction.enforce_passivity),
            model=self.extraction.model,
        )

    def interpolation_name(self) -> str:
        if not self.extraction.enable_interpolation:
            return "Linear"
        return self.extraction.interp_method or "Linear"

    def eps_r_value(self) -> float:
        value = float(self.extraction.eps_r_eff or 1.0)
        return value if value > 0 else 1.0

    def filter_settings(self) -> Optional[dict]:
        if not self.extraction.enable_filter:
            return None

        return dict(
            method=self.extraction.filter_method,
            window=int(self.extraction.filter_window),
            order=int(self.extraction.filter_order),
            sigma=float(self.extraction.filter_sigma),
            cutoff=float(self.extraction.filter_cutoff),
        )

    def apply_filter(self, signal, frequency=None):
        settings = self.filter_settings()
        if settings is None:
            return np.asarray(signal, dtype=complex)
        return afr_signal.filter_complex(signal, frequency=frequency, **settings)

    # ------------------------------------------------------------------
    # Avertissements
    # ------------------------------------------------------------------

    def add_warning(self, message: str):
        log.warning(message)
        if message not in self.warnings:
            self.warnings.append(message)

    def clear_warnings(self):
        self.warnings = []

    # ------------------------------------------------------------------
    # Standards
    # ------------------------------------------------------------------

    @staticmethod
    def expected_port_count(key: str) -> int:
        return 2 if str(key).startswith(TWO_PORT_KEYS) else 1

    def required_standards(self) -> list:
        """(cle, libelle) des fichiers a fournir, d'apres la page 2."""

        wanted = [
            ("THRU_LINE1", self.config.use_2x_thru),
            ("THRU_LINE2", self.config.use_second_2x_thru),
            ("ASYM_DUT", self.config.use_fixtured_dut),
            ("OPEN_A", self.config.use_open_a),
            ("SHORT_A", self.config.use_short_a),
            ("OPEN_B", self.config.use_open_b),
            ("SHORT_B", self.config.use_short_b),
        ]
        return [(key, STANDARD_LABELS[key]) for key, used in wanted if used]

    def missing_standards(self) -> list:
        return [label for key, label in self.required_standards()
                if key not in self.standard_files]

    def load_standard(self, key: str, path) -> rf.Network:
        """
        Enregistre un fichier de standard apres verification du nombre de
        ports. Leve ValueError si le fichier ne convient pas.
        """

        path = str(path)
        network = afr_io.load_network(path, expected_ports=None)

        expected = self.expected_port_count(key)
        if network.nports != expected:
            raise ValueError(
                f"{STANDARD_LABELS.get(key, key)} attend un fichier a {expected} port(s) ; "
                f"celui-ci en contient {network.nports}."
            )

        self.standard_files[key] = path
        self.networks[key] = network
        return network

    def forget_standard(self, key: str):
        self.standard_files.pop(key, None)
        self.networks.pop(key, None)

    # ------------------------------------------------------------------
    # Extraction : S1P -> S2P
    # ------------------------------------------------------------------

    def fixture_from_s1p(self, filename, reflect_type=None):
        network = afr_io.load_network(filename, expected_ports=1)
        freq = network.f
        gamma = self.apply_filter(network.s[:, 0, 0], freq)

        result = afr_reflect.fixture_from_reflect(
            freq, gamma, reflect_type or filename,
            z0=afr_io.reference_impedance(network),
            **self.extraction_options(),
        )
        result.with_length(self.eps_r_value())
        self.collect_quality(reflect_type or Path(filename).stem, result)
        return result

    def fixture_from_open_short(self, open_file, short_file):
        n_open = afr_io.load_network(open_file, expected_ports=1)
        n_short = afr_io.load_network(short_file, expected_ports=1)

        if len(n_open.f) != len(n_short.f) or not np.allclose(n_open.f, n_short.f):
            n_short = n_short.interpolate(n_open.frequency)

        freq = n_open.f
        result = afr_reflect.fixture_from_open_short(
            freq,
            self.apply_filter(n_open.s[:, 0, 0], freq),
            self.apply_filter(n_short.s[:, 0, 0], freq),
            z0=afr_io.reference_impedance(n_open),
            **self.extraction_options(),
        )
        result.with_length(self.eps_r_value())
        self.collect_quality(f"{Path(open_file).stem} + {Path(short_file).stem}", result)
        return result

    def collect_quality(self, label: str, result):
        """Transforme le rapport de qualite en avertissements lisibles."""

        quality = result.quality

        for key in ("fit_warning", "dynamic_range_warning", "warning"):
            if quality.get(key):
                self.add_warning(f"{label} : {quality[key]}")

        if quality.get("measured_over_unit"):
            self.add_warning(
                f"{label} : {quality['measured_over_unit']} point(s) mesures avec "
                f"|Gamma| > 1. La mesure n'est pas passive : verifier la calibration."
            )

        if quality.get("clamped_propagation"):
            self.add_warning(
                f"{label} : {quality['clamped_propagation']} point(s) de propagation "
                f"ramenes a 1 (standard imparfait ou bande trop etroite)."
            )

        if quality.get("clamped_points"):
            self.add_warning(f"{label} : {quality['clamped_points']} point(s) ramenes "
                             f"a la limite passive.")

        if not quality.get("passive", True):
            self.add_warning(f"{label} : reseau non passif (valeur singuliere max "
                             f"{quality.get('max_singular_value', 0):.3f}).")

    def reflect_usage_order(self, side: str):
        orders = {
            "auto": (f"REFLECT_{side}", f"OPEN_{side}", f"SHORT_{side}"),
            "combined": (f"REFLECT_{side}",),
            "open": (f"OPEN_{side}",),
            "short": (f"SHORT_{side}",),
        }
        return orders.get(self.extraction.reflect_usage, orders["auto"])

    def reflect_fixture_network(self, side: str):
        for key in self.reflect_usage_order(side):
            result = self.fixture_results.get(key)
            if result is not None:
                return key, result.network
        return None, None

    def calculate_reflection_fixtures(self):
        """OPEN et / ou SHORT -> fixture de chaque cote."""

        keys = [k for k in self.standard_files if k.startswith(("OPEN_", "SHORT_"))]
        usage = self.extraction.reflect_usage
        wanted = {
            "auto": ("OPEN_", "SHORT_"),
            "combined": ("OPEN_", "SHORT_"),
            "open": ("OPEN_",),
            "short": ("SHORT_",),
        }.get(usage, ("OPEN_", "SHORT_"))

        form = self.extraction.export_format

        for key in keys:
            if not key.startswith(wanted):
                continue

            result = self.fixture_from_s1p(self.standard_files[key], reflect_type=key)

            self.fixture_results[key] = result
            self.extracted_info[key] = result.as_info()
            self.networks[f"{key} (extracted)"] = result.network
            self.converted_files[key] = str(
                afr_io.write_network(result.network, self.output_dir / f"{key}_CONVERTED", form)
            )

        if usage not in ("auto", "combined"):
            return

        for side in sorted({key.split("_", 1)[1] for key in keys}):
            open_key, short_key = f"OPEN_{side}", f"SHORT_{side}"

            if open_key not in self.standard_files or short_key not in self.standard_files:
                if usage == "combined":
                    self.add_warning(
                        f"Cote {side} : mode OPEN + SHORT demande mais un seul des deux "
                        f"standards est charge. Choisir OPEN seul ou SHORT seul."
                    )
                continue

            try:
                result = self.fixture_from_open_short(
                    self.standard_files[open_key], self.standard_files[short_key]
                )
            except Exception as error:
                self.add_warning(f"Combinaison OPEN/SHORT {side} impossible : {error}")
                continue

            combined = f"REFLECT_{side}"
            self.fixture_results[combined] = result
            self.extracted_info[combined] = result.as_info()
            self.networks[f"{combined} (extracted)"] = result.network
            self.converted_files[combined] = str(
                afr_io.write_network(result.network,
                                     self.output_dir / f"{combined}_CONVERTED", form)
            )

            gap = result.quality.get("open_short_mag_db")
            if gap is not None and gap > 1.0:
                self.add_warning(
                    f"Cote {side} : les extractions OPEN et SHORT different de "
                    f"{gap:.2f} dB. Verifier les standards ou n'en utiliser qu'un seul."
                )

    # ------------------------------------------------------------------
    # Extraction : 2x-thru
    # ------------------------------------------------------------------

    def calculate_thru_fixture(self, key: str):
        thru = afr_io.load_network(self.standard_files[key], expected_ports=2)
        freq = thru.f

        filtered = thru.copy()
        s = filtered.s.copy()
        for i in range(2):
            for j in range(2):
                s[:, i, j] = self.apply_filter(s[:, i, j], freq)
        filtered.s = s

        self.thru_networks[key] = filtered
        self.networks[key] = filtered

        half_in, half_out, information = afr_thru.split_2x_thru(
            filtered, self.interpolation_name()
        )

        if information["quality"].get("warning"):
            self.add_warning(f"{key} : {information['quality']['warning']}")

        information["length1"] = afr_metrics.physical_length(
            information["delay1"] * 1e-12, self.eps_r_value()) * 1e3
        information["length2"] = information["length1"]

        form = self.extraction.export_format
        self.converted_files[f"{key}_IN"] = str(
            afr_io.write_network(half_in, self.output_dir / f"{key}_HALF_IN", form))
        self.converted_files[f"{key}_OUT"] = str(
            afr_io.write_network(half_out, self.output_dir / f"{key}_HALF_OUT", form))

        self.fixture_pairs[key] = {"in": half_in, "out": half_out}
        self.networks[f"{key} half IN"] = half_in
        self.networks[f"{key} half OUT"] = half_out
        self.extracted_info[key] = dict(information)

        return half_in, half_out, information

    # ------------------------------------------------------------------
    # Assemblage entree / sortie
    # ------------------------------------------------------------------

    def assemble_fixtures(self):
        key_a, net_a = self.reflect_fixture_network("A")
        key_b, net_b = self.reflect_fixture_network("B")

        fixture_in = net_a
        fixture_out = afr_thru.as_output_fixture(net_b) if net_b is not None else None

        thru_keys = sorted(self.thru_networks)
        thru = self.thru_networks.get(thru_keys[0]) if thru_keys else None

        # Deux 2x-thru distincts : chacun caracterise un cote, meme si les
        # deux lignes n'ont pas la meme longueur.
        if len(thru_keys) >= 2:
            first = self.fixture_pairs.get(thru_keys[0], {})
            second = self.fixture_pairs.get(thru_keys[1], {})

            if fixture_in is None and first.get("in") is not None:
                fixture_in = first["in"]
            if fixture_out is None and second.get("out") is not None:
                fixture_out = second["out"]

            thru = None

        if fixture_in is None and fixture_out is None and thru is None:
            return

        fixture_in, fixture_out, info = afr_thru.complete_pair(
            thru=thru, fixture_in=fixture_in, fixture_out=fixture_out,
            interp_method=self.interpolation_name(),
        )

        self.fixture_a_network = fixture_in
        self.fixture_b_network = fixture_out
        self.fixture_assembly = info

        self.networks["Fixture A (input)"] = fixture_in
        self.networks["Fixture B (output)"] = fixture_out

        both_from_thrus = len(thru_keys) >= 2 and key_a is None and key_b is None
        info["sources"] = {
            "reflect_both_sides": (
                f"{thru_keys[0]} pour l'entree et {thru_keys[1]} pour la sortie"
                if both_from_thrus else
                f"OPEN/SHORT des deux cotes ({key_a}, {key_b})"),
            "reflect_in_plus_thru": f"{key_a} + 2x-thru (sortie deduite exactement)",
            "reflect_out_plus_thru": f"{key_b} + 2x-thru (entree deduite exactement)",
            "thru_symmetric_split": "2x-thru seul (moities supposees identiques)",
            "reflect_in_mirrored": f"{key_a} seul (sortie supposee identique)",
            "reflect_out_mirrored": f"{key_b} seul (entree supposee identique)",
        }.get(info["method"], info["method"])

        if info.get("warning"):
            self.add_warning(info["warning"])

        residual = info.get("residual")
        if residual and residual["thru_s21_db"] > 0.5:
            self.add_warning(
                f"La cascade des deux fixtures s'ecarte du 2x-thru mesure de "
                f"{residual['thru_s21_db']:.2f} dB sur S21. Verifier les standards."
            )

        self.check_fixtured_dut()

    def assembly_label(self) -> str:
        if not self.fixture_assembly:
            return "aucun fixture calcule"
        return self.fixture_assembly.get("sources",
                                         self.fixture_assembly.get("method", "inconnue"))

    def check_fixtured_dut(self):
        """Controle optionnel : le DUT monte entre les deux lignes."""

        path = next((self.standard_files[k] for k in ("ASYM_DUT", "FIXTURED_DUT", "DUT")
                     if k in self.standard_files), None)

        if path is None or self.fixture_a_network is None or self.fixture_b_network is None:
            return

        try:
            measured = afr_io.load_network(path, expected_ports=2)
            report = afr_thru.check_fixtured_dut(
                measured, self.fixture_a_network, self.fixture_b_network)
        except Exception as error:
            self.add_warning(f"Controle sur le DUT fixture impossible : {error}")
            return

        self.networks["Fixtured DUT de-embedded"] = report["network"]

        if not report["passive"]:
            self.add_warning(
                f"Le DUT de-embedde n'est pas passif (valeur singuliere max "
                f"{report['max_singular_value']:.3f}) : fixtures probablement surestimes."
            )

    # ------------------------------------------------------------------
    # Operation complete de la page 3
    # ------------------------------------------------------------------

    def calculate(self) -> Report:
        """Extraction complete : 2x-thru, reflexions, puis assemblage."""

        report = Report(title="Extraction des fixtures")

        missing = self.missing_standards()
        if missing:
            report.ok = False
            report.lines.append("Fichiers manquants :")
            report.lines += [f"  - {label}" for label in missing]
            return report

        self.clear_warnings()
        self.fixture_results.clear()
        self.fixture_pairs.clear()
        self.thru_networks.clear()

        for key in list(self.standard_files):
            if key.startswith("THRU_"):
                half_in, half_out, information = self.calculate_thru_fixture(key)
                report.lines.append(
                    f"{key:11s} TTD total {information['delay_total_ps']:7.1f} ps, "
                    f"demi {information['delay1']:6.1f} ps, "
                    f"Z1 {information['z1']:5.1f} ohm, Z2 {information['z2']:5.1f} ohm, "
                    f"longueur {information['length1']:.2f} mm"
                )

        self.calculate_reflection_fixtures()

        for key, result in sorted(self.fixture_results.items()):
            report.lines.append(
                f"{key:11s} Z {result.impedance_ohm:5.1f} ohm, "
                f"TTD {result.delay_ps:6.1f} ps, "
                f"longueur {(result.length_mm or 0.0):.2f} mm, "
                f"modele {result.quality.get('model')}, "
                f"echo/bruit {result.quality.get('echo_snr_db', float('nan')):.0f} dB"
            )

        try:
            self.assemble_fixtures()
        except Exception as error:
            self.add_warning(f"Assemblage des fixtures impossible : {error}")

        if self.fixture_a_network is None and self.fixture_b_network is None:
            report.ok = False
            report.lines.append("Aucun fixture n'a pu etre construit.")
        else:
            self.extraction_done = True
            report.lines.append("")
            report.lines.append(f"Assemblage : {self.assembly_label()}")

        report.warnings = list(self.warnings)
        return report

    # ------------------------------------------------------------------
    # Page 4 : retrait des fixtures
    # ------------------------------------------------------------------

    @staticmethod
    def identity_network(reference):
        s = np.zeros((len(reference.f), 2, 2), dtype=complex)
        s[:, 1, 0] = 1.0
        s[:, 0, 1] = 1.0
        return rf.Network(frequency=reference.frequency, s=s, z0=reference.z0)

    def load_raw_measurement(self, path) -> rf.Network:
        measured = afr_io.load_network(str(path), expected_ports=2)
        measured.name = Path(path).stem
        self.raw_measurement = measured
        self.networks[RAW_LABEL] = measured
        return measured

    def deembed(self, path=None, use_input=True, use_output=True) -> Report:
        """Retire les fixtures d'une mesure brute ligne A + DUT + ligne B."""

        report = Report(title="De-embedding")

        measured = self.load_raw_measurement(path) if path else self.raw_measurement
        if measured is None:
            report.ok = False
            report.lines.append("Aucune mesure brute chargee.")
            return report

        fixture_in = self.fixture_a_network if use_input else None
        fixture_out = self.fixture_b_network if use_output else None

        if fixture_in is None and fixture_out is None:
            report.ok = False
            report.lines.append(
                "Aucun fixture a retirer : lancer l'extraction (page 3) et cocher "
                "au moins un cote."
            )
            return report

        dut = afr_deembed.remove_fixtures(measured, fixture_in, fixture_out)
        stem = measured.name or "DUT"
        output = afr_io.write_network(
            dut, self.output_dir / f"{stem}_DEEMBEDDED", self.extraction.export_format)

        self.deembedded_network = dut
        self.networks[DEEMBEDDED_LABEL] = dut

        quality = afr_metrics.quality_report(dut.s)
        rebuilt = afr_deembed.embed_fixtures(
            dut,
            fixture_in if fixture_in is not None else self.identity_network(measured),
            fixture_out if fixture_out is not None else self.identity_network(measured),
        )
        reconstruction = float(np.max(np.abs(rebuilt.s - measured.s)))

        gain = (20 * np.log10(np.maximum(np.abs(dut.s[:, 1, 0]), 1e-15))
                - 20 * np.log10(np.maximum(np.abs(measured.s[:, 1, 0]), 1e-15)))

        report.lines += [
            f"Bande                    : {measured.f[0] / 1e9:.3f} - "
            f"{measured.f[-1] / 1e9:.3f} GHz, {len(measured.f)} points",
            f"Fixtures                 : {self.assembly_label()}",
            f"Cotes retires            : "
            f"{'entree' if fixture_in is not None else '-'} / "
            f"{'sortie' if fixture_out is not None else '-'}",
            "",
            f"Perte d'insertion rendue : {np.mean(gain):+.2f} dB en moyenne, "
            f"{np.max(gain):+.2f} dB au plus",
            f"DUT passif               : {quality['passive']} "
            f"(valeur singuliere max {quality['max_singular_value']:.4f})",
            f"Erreur de reciprocite    : {quality['reciprocity_error']:.2e}",
            f"Residu de re-embedding   : {reconstruction:.2e} (doit etre du bruit numerique)",
            "",
            f"Enregistre dans : {output}",
        ]

        if not quality["passive"]:
            self.add_warning("DUT de-embedde non passif : fixtures surestimes.")
            report.warnings.append(
                "Le DUT de-embedde n'est pas passif : trop de pertes ont ete retirees. "
                "Verifier la qualite d'extraction en page 3 avant d'utiliser ce fichier."
            )

        return report

    # ------------------------------------------------------------------
    # Page 5 : enregistrement / page 6 : lot
    # ------------------------------------------------------------------

    def save_fixtures(self, base_name: str) -> Report:
        report = Report(title="Enregistrement des fixtures")

        if not base_name.strip():
            report.ok = False
            report.lines.append("Indiquer un nom de base.")
            return report

        if self.fixture_a_network is None or self.fixture_b_network is None:
            report.ok = False
            report.lines.append("Calculer les fixtures (page 3) avant d'enregistrer.")
            return report

        form = self.extraction.export_format
        if form not in {"db", "ma", "ri"}:
            form = "db"

        base = base_name.strip()
        path_a = afr_io.write_network(self.fixture_a_network,
                                      self.output_dir / f"{base}_Fixture_A", form)
        path_b = afr_io.write_network(self.fixture_b_network,
                                      self.output_dir / f"{base}_Fixture_B", form)

        report.lines += [f"Fixture A : {path_a}", f"Fixture B : {path_b}"]
        return report

    def run_batch(self, input_dir, output_dir=None, pattern="*.s2p",
                  use_input=True, use_output=True) -> Report:
        report = Report(title="Traitement par lot")

        input_dir = Path(input_dir)
        if not input_dir.is_dir():
            report.ok = False
            report.lines.append("Dossier d'entree invalide.")
            return report

        fixture_in = self.fixture_a_network if use_input else None
        fixture_out = self.fixture_b_network if use_output else None

        if fixture_in is None and fixture_out is None:
            report.ok = False
            report.lines.append("Calculer les fixtures (page 3) avant de lancer un lot.")
            return report

        output_dir = Path(output_dir) if output_dir else input_dir / "deembedded"

        items = afr_deembed.batch_deembed(
            input_dir, output_dir, pattern or "*.s2p",
            fixture_in, fixture_out, form=self.extraction.export_format)

        report.lines.append(f"{len(items)} fichier(s) trouve(s). Sortie : {output_dir}")
        report.lines.append("")

        for item in items:
            if item.ok:
                report.lines.append(f"[OK ] {item.source.name} -> {item.output.name}")
            else:
                report.lines.append(f"[ERR] {item.source.name} : {item.message}")

        failed = sum(1 for item in items if not item.ok)
        report.lines.append("")
        report.lines.append(f"Termine : {len(items) - failed} traite(s), {failed} en echec.")
        report.ok = failed == 0
        return report

    # ------------------------------------------------------------------

    def plot_sources(self) -> dict:
        """Tous les reseaux tracables, du plus utile au plus accessoire."""

        return {name: network for name, network in self.networks.items()
                if network is not None}

    def configuration_lines(self) -> list:
        return [f"{key} : {value}" for key, value in asdict(self.config).items()]
