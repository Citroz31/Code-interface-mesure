"""
Interface Qt de l'outil AFR (PySide6 + pyqtgraph).

Le calcul vit dans ``afr/`` et l'etat dans ``qtapp.session`` : l'interface ne
contient aucune formule, ce qui permet de tester la chaine sans ouvrir de
fenetre.
"""

from .session import AfrSession, Configuration, Extraction, Report  # noqa: F401

__all__ = ["AfrSession", "Configuration", "Extraction", "Report"]
