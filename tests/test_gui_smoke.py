"""
Verification de lancement de l'interface.

Ce test construit reellement la fenetre principale, visite les six pages,
puis la referme : c'est le controle a lancer en premier quand l'application
ne demarre pas. Il est ignore automatiquement si Tk, une des bibliotheques
de calcul ou un affichage manquent (integration continue sans ecran).

    python -m pytest tests/test_gui_smoke.py -q
"""

import pytest

tk = pytest.importorskip("tkinter", reason="Tk absent (Linux : sudo apt install python3-tk)")
pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("skrf", reason="scikit-rf absent")
pytest.importorskip("matplotlib")


@pytest.fixture
def application():
    """Fenetre principale non affichee, fermee a la fin du test."""

    try:
        probe = tk.Tk()
    except Exception as error:                      # pas d'affichage disponible
        pytest.skip(f"aucun affichage disponible : {error}")
    probe.destroy()

    from matrice_et_branche import AFRWizardComplete

    window = AFRWizardComplete()
    window.withdraw()                               # ne rien afficher a l'ecran
    try:
        yield window
    finally:
        window.destroy()


def test_application_builds_every_page(application):
    assert len(application.page_frames) == 6

    for page in range(6):
        application.show_page(page)

    assert application.current_page == 5


def test_extraction_options_expose_every_model(application):
    from afr import reflect

    options = application.extraction_options()
    assert options["model"] in reflect.MODELS
    assert set(options) >= {"interp_method", "smooth_points",
                            "enforce_passivity", "model"}

    for model in reflect.MODELS:
        application.extraction_model.set(model)
        assert application.extraction_options()["model"] == model


def test_launcher_check_reports_a_complete_installation():
    """Le lanceur doit confirmer l'installation quand les tests s'executent."""

    import run_afr

    assert run_afr.check(verbose=False) is True
