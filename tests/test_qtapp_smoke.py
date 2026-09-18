"""
Verification de lancement de l'interface Qt.

Construit la fenetre, visite les six pages, parcourt tous les formats de
trace, puis referme. Ignore si PySide6, pyqtgraph ou l'affichage manquent.

    python -m pytest tests/test_qtapp_smoke.py -q
"""

import pytest

pytest.importorskip("PySide6", reason="PySide6 absent (pip install PySide6)")
pytest.importorskip("pyqtgraph", reason="pyqtgraph absent (pip install pyqtgraph)")
pytest.importorskip("numpy")
pytest.importorskip("skrf")

from PySide6.QtWidgets import QApplication    # noqa: E402


@pytest.fixture(scope="module")
def application():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as error:                 # pas d'affichage disponible
        pytest.skip(f"aucun affichage disponible : {error}")
    yield app


@pytest.fixture
def window(application):
    from qtapp.mainwindow import MainWindow

    main = MainWindow()
    try:
        yield main
    finally:
        main.close()


def test_window_builds_every_page(window):
    assert len(window.pages) == 6

    for index in range(6):
        window.show_page(index)

    assert window.current == 5


def test_every_extraction_model_is_selectable(window):
    from afr import reflect

    page = window.pages[2]
    values = {button.property("value") for button in page.model_group.buttons()}
    assert values == set(reflect.MODELS)

    for button in page.model_group.buttons():
        button.setChecked(True)
        page.store()
        assert window.session.extraction.model == button.property("value")


def test_plot_switches_between_every_format(window):
    plot = window.pages[2].plot

    for index in range(plot.format_box.count()):
        plot.format_box.setCurrentIndex(index)
        assert plot.format_key()

    plot.add_marker(10.0)
    plot.add_marker(20.0)
    assert "delta" in plot._readout_text(15.0)

    plot.clear_markers()
    assert plot.markers == []
