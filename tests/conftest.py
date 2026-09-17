"""
Rend le depot importable par les tests, quel que soit le repertoire courant
et la facon d'appeler pytest (``pytest``, ``python -m pytest``, IDE).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
