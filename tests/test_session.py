"""
Chaine complete de la session AFR, sans interface.

Le jeu de validation du depot (lignes A et B de longueurs differentes autour
d'un DUT connu) sert de reference : la session doit extraire les deux
fixtures a partir des OPEN / SHORT, puis retrouver le DUT dans la mesure
brute.

    python -m pytest tests/test_session.py -q
"""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("skrf")

from afr import io as afr_io                      # noqa: E402
from qtapp.session import AfrSession               # noqa: E402

VALIDATION = Path(__file__).resolve().parent.parent / "validation"
BAND = (1e9, 40e9)


@pytest.fixture
def session(tmp_path):
    if not (VALIDATION / "OPEN_A.s1p").is_file():
        pytest.skip("jeu de validation absent")

    work = AfrSession(output_dir=tmp_path)
    work.config.use_2x_thru = False
    work.config.use_open_a = True
    work.config.use_short_a = True
    work.config.use_open_b = True
    work.config.use_short_b = True

    for key in ("OPEN_A", "SHORT_A", "OPEN_B", "SHORT_B"):
        work.load_standard(key, VALIDATION / f"{key}.s1p")

    return work


def worst_db(estimated, reference):
    band = (reference.f >= BAND[0]) & (reference.f <= BAND[1])
    return float(np.max(np.abs(
        20 * np.log10(np.abs(estimated.s[band, 1, 0]))
        - 20 * np.log10(np.abs(reference.s[band, 1, 0])))))


def test_required_standards_follow_the_configuration(session):
    keys = [key for key, _ in session.required_standards()]
    assert keys == ["OPEN_A", "SHORT_A", "OPEN_B", "SHORT_B"]
    assert session.missing_standards() == []


def test_load_standard_rejects_a_wrong_port_count(session):
    with pytest.raises(ValueError):
        session.load_standard("OPEN_A", VALIDATION / "RAW_MEASUREMENT.s2p")


def test_calculate_extracts_both_fixtures(session):
    report = session.calculate()

    assert report.ok, report.text()
    assert session.fixture_a_network is not None
    assert session.fixture_b_network is not None
    assert "OPEN/SHORT des deux cotes" in session.assembly_label()

    reference_a = afr_io.load_network(VALIDATION / "FIXTURE_A_reference.s2p", 2)
    assert worst_db(session.fixture_a_network, reference_a) < 0.3

    # Chaque extraction a produit un fichier exploitable dans un simulateur.
    for key in ("REFLECT_A", "REFLECT_B"):
        assert Path(session.converted_files[key]).is_file()


def test_deembedding_recovers_the_reference_dut(session):
    session.calculate()

    report = session.deembed(VALIDATION / "RAW_MEASUREMENT.s2p")
    assert report.ok, report.text()

    reference = afr_io.load_network(VALIDATION / "DUT_reference.s2p", 2)
    assert worst_db(session.deembedded_network, reference) < 0.3

    # Les deux courbes de la comparaison avant / apres sont disponibles.
    sources = session.plot_sources()
    assert any("measured" in name for name in sources)
    assert any("de-embedded" in name for name in sources)


def test_every_extraction_model_runs(session):
    from afr import reflect

    for model in reflect.MODELS:
        fresh = AfrSession(output_dir=session.output_dir)
        fresh.config = session.config
        fresh.standard_files = dict(session.standard_files)
        fresh.extraction.model = model

        report = fresh.calculate()
        assert report.ok, f"{model} : {report.text()}"
        assert fresh.fixture_a_network is not None
