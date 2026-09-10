"""
Retrait des fixtures autour d'un DUT mesure, et traitement par lot.

    mesure = fixture_in ** DUT ** fixture_out
    DUT    = fixture_in.inv ** mesure ** fixture_out.inv

``fixture_in`` a son port 1 cote VNA et son port 2 cote DUT ;
``fixture_out`` a son port 1 cote DUT et son port 2 cote VNA (port-swap),
comme les deux demi-fixtures retournees par ``afr.thru.split_2x_thru``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import skrf as rf

from . import io as afr_io
from .models import BatchItem

log = logging.getLogger(__name__)


def align_to(fixture: rf.Network, target: rf.Network) -> rf.Network:
    """Fixture reechantillonne sur la grille de frequence de ``target``."""

    if np.array_equal(fixture.f, target.f):
        return fixture

    f_lo, f_hi = float(target.f[0]), float(target.f[-1])
    if f_lo < fixture.f[0] - 1e-6 or f_hi > fixture.f[-1] + 1e-6:
        raise ValueError(
            "La bande du DUT ({:.3f}-{:.3f} GHz) depasse celle du fixture "
            "({:.3f}-{:.3f} GHz).".format(f_lo / 1e9, f_hi / 1e9,
                                        fixture.f[0] / 1e9, fixture.f[-1] / 1e9)
        )

    log.info("Interpolation du fixture %s sur la grille du DUT", fixture.name)
    return fixture.interpolate(target.frequency)


def condition_number(fixture: rf.Network) -> float:
    """Conditionnement maximal des matrices ABCD (alerte si tres grand)."""

    return float(np.max(np.linalg.cond(fixture.a)))


def remove_fixtures(dut: rf.Network,
                    fixture_in: Optional[rf.Network] = None,
                    fixture_out: Optional[rf.Network] = None,
                    warn_condition: float = 1e6) -> rf.Network:
    """DUT de-embedde. Un fixture ``None`` n'est pas retire."""

    if dut.nports != 2:
        raise ValueError(
            f"Le de-embedding gere les DUT a 2 ports ({dut.nports} trouves)."
        )

    result = dut.copy()

    if fixture_in is not None:
        fin = align_to(fixture_in, dut)
        cond = condition_number(fin)
        if cond > warn_condition:
            log.warning("Fixture IN mal conditionne (cond max = %.2e)", cond)
        result = fin.inv ** result

    if fixture_out is not None:
        fout = align_to(fixture_out, dut)
        cond = condition_number(fout)
        if cond > warn_condition:
            log.warning("Fixture OUT mal conditionne (cond max = %.2e)", cond)
        result = result ** fout.inv

    result.name = f"{dut.name}_DEEMBEDDED" if dut.name else "DEEMBEDDED"
    return result


def embed_fixtures(dut: rf.Network, fixture_in: rf.Network,
                   fixture_out: rf.Network) -> rf.Network:
    """Operation inverse (utile pour les tests et les controles)."""

    return fixture_in ** dut ** fixture_out


def batch_deembed(input_dir, output_dir, pattern: str = "*.s2p",
                  fixture_in: Optional[rf.Network] = None,
                  fixture_out: Optional[rf.Network] = None,
                  form: str = "db", suffix: str = "_DEEMBEDDED",
                  files: Optional[Iterable[Path]] = None) -> List[BatchItem]:
    """
    De-embedde tous les fichiers ``pattern`` de ``input_dir`` vers
    ``output_dir``. Retourne un ``BatchItem`` par fichier, meme en cas
    d'echec (le lot continue).
    """

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    if files is None:
        if not input_dir.is_dir():
            raise NotADirectoryError(input_dir)
        files = sorted(input_dir.glob(pattern))

    if fixture_in is None and fixture_out is None:
        raise ValueError("Aucun fixture a retirer : calculez d'abord les fixtures.")

    output_dir.mkdir(parents=True, exist_ok=True)
    items: List[BatchItem] = []

    for source in files:
        source = Path(source)
        try:
            dut = afr_io.load_network(source, expected_ports=2)
            dut.name = source.stem
            result = remove_fixtures(dut, fixture_in, fixture_out)
            output = afr_io.write_network(result, output_dir / f"{source.stem}{suffix}", form)
            items.append(BatchItem(source, output, True, "OK"))
        except Exception as error:
            log.exception("Echec sur %s", source)
            items.append(BatchItem(source, None, False, str(error)))

    return items
