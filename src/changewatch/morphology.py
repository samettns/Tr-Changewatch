"""Açma/kapama ve minimum haritalama birimi (MMU) filtresi."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from skimage.morphology import closing, disk, opening, remove_small_objects


def mmu_pixels(settings: dict[str, Any]) -> int:
    """MMU'nun piksel karşılığı (yukarı yuvarlanır): 0,5 ha / 400 m² = 12,5 → 13."""
    res = float(settings["grid"]["resolution_m"])
    return math.ceil(float(settings["morphology"]["mmu_ha"]) * 10_000 / (res * res) - 1e-9)


def open_close(mask: np.ndarray, settings: dict[str, Any]) -> np.ndarray:
    """Önce açma (gürültü), sonra kapama (boşluk). Yarıçap 0 ise adım atlanır."""
    m = settings["morphology"]
    out = mask.astype(bool)
    if int(m["open_radius_px"]) > 0:
        out = opening(out, disk(int(m["open_radius_px"])))
    if int(m["close_radius_px"]) > 0:
        out = closing(out, disk(int(m["close_radius_px"])))
    return out


def apply_mmu(mask: np.ndarray, settings: dict[str, Any]) -> np.ndarray:
    """MMU'dan küçük bağlı bileşenleri atar."""
    conn = int(settings["morphology"]["connectivity"])
    return remove_small_objects(mask.astype(bool), max_size=mmu_pixels(settings) - 1, connectivity=conn)


def clean_mask(mask: np.ndarray, settings: dict[str, Any]) -> np.ndarray:
    """Açma/kapama + MMU."""
    return apply_mmu(open_close(mask, settings), settings)
