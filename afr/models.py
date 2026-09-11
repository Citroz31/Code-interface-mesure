"""Resultats types retournes par le noyau de calcul."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import skrf as rf

from .metrics import physical_length


@dataclass
class FixtureResult:
    """Fixture extrait (2 ports) et ses caracteristiques."""

    network: rf.Network
    impedance_ohm: float
    delay_ps: float
    method: str
    quality: dict = field(default_factory=dict)
    length_mm: Optional[float] = None

    def with_length(self, eps_r_eff: float = 1.0) -> "FixtureResult":
        """Renseigne la longueur physique a partir du delai et de eps_r effectif."""

        self.length_mm = physical_length(self.delay_ps * 1e-12, eps_r_eff) * 1e3
        return self

    def as_info(self) -> dict:
        """Dictionnaire simple pour l'affichage / l'export JSON."""

        return {
            "method": self.method,
            "z": float(self.impedance_ohm),
            "delay": float(self.delay_ps),
            "length_mm": None if self.length_mm is None else float(self.length_mm),
            "quality": {k: (float(v) if hasattr(v, "__float__") else v)
                        for k, v in self.quality.items()},
        }


@dataclass
class BatchItem:
    """Resultat du traitement d'un fichier dans un lot."""

    source: Path
    output: Optional[Path]
    ok: bool
    message: str = ""
