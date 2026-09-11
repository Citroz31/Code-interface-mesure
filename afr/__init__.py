"""
Noyau de calcul AFR (Automatic Fixture Removal).

Ce paquet ne depend pas de Tkinter : toutes les fonctions prennent des
tableaux numpy ou des reseaux scikit-rf en entree et retournent des objets
(voir ``afr.models``). L'interface graphique se contente de les appeler.

Modules :
    io        lecture / ecriture Touchstone
    signal    filtrage, interpolation, aller-retour temps <-> frequence
    metrics   delai, longueur, impedance TDR, passivite, reciprocite
    reflect   S1P (OPEN / SHORT) -> S2P du fixture
    thru      decoupage du 2x-thru en deux demi-fixtures
    deembed   retrait des fixtures, traitement par lot
    models    resultats types
"""

from . import io, signal, metrics, reflect, thru, deembed, models  # noqa: F401
from .models import FixtureResult, BatchItem  # noqa: F401

__all__ = [
    "io",
    "signal",
    "metrics",
    "reflect",
    "thru",
    "deembed",
    "models",
    "FixtureResult",
    "BatchItem",
]
