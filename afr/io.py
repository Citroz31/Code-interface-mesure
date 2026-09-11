"""Lecture et ecriture des fichiers Touchstone."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import skrf as rf

log = logging.getLogger(__name__)

EXPORT_FORMS = ("db", "ma", "ri")


def detect_touchstone_format(path) -> str:
    """Format des donnees declare dans l'entete (# ... RI / MA / DB)."""

    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip().upper()
            if not line.startswith("#"):
                continue
            padded = f" {line} "
            for fmt in ("RI", "MA", "DB"):
                if f" {fmt} " in padded:
                    return fmt
    return "UNKNOWN"


def load_network(path, expected_ports: int | None = None) -> rf.Network:
    """
    Charge un fichier Touchstone et verifie :
    nombre de ports attendu, valeurs finies, frequence croissante.
    """

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    network = rf.Network(str(path))

    if expected_ports is not None and network.nports != expected_ports:
        raise ValueError(
            f"{path.name} : {network.nports} port(s), {expected_ports} attendu(s)."
        )

    f = np.asarray(network.f, dtype=float)
    if len(f) < 3:
        raise ValueError(f"{path.name} : moins de 3 points de frequence.")
    if np.any(np.diff(f) <= 0):
        raise ValueError(f"{path.name} : frequences non strictement croissantes.")
    if not np.all(np.isfinite(network.s)):
        raise ValueError(f"{path.name} : valeurs non finies dans les parametres S.")

    return network


def reference_impedance(network: rf.Network) -> float:
    """Impedance de reference (reelle) du fichier, 50 ohm par defaut."""

    try:
        return float(np.real(np.asarray(network.z0).flat[0]))
    except Exception:
        return 50.0


def write_network(network: rf.Network, base_path, form: str = "db") -> Path:
    """
    Ecrit ``network`` en Touchstone ; ``base_path`` est sans extension.
    Retourne le chemin complet du fichier ecrit.
    """

    base_path = Path(base_path)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    form = str(form).lower()
    if form not in EXPORT_FORMS:
        form = "db"

    network.write_touchstone(str(base_path), form=form)
    output = Path(f"{base_path}.s{network.nports}p")
    log.info("Fichier ecrit : %s", output)
    return output
