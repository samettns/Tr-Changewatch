"""CVA büyüklüğü ve doku farkı üzerinde Otsu eşiği ile değişim adayları."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import xarray as xr
from skimage.filters import threshold_otsu


@dataclass
class Candidates:
    """Aday maskesi ve onu üreten büyüklükler/eşikler."""

    cva: np.ndarray            # CVA büyüklüğü (yansıtım)
    dtexture: np.ndarray       # |doku_b - doku_a| (aday üretimi)
    dtexture_signed: np.ndarray  # doku_b - doku_a (yapılaşma kuralı işaretli artışı kullanır)
    cva_threshold: float
    texture_threshold: float
    cva_flag: np.ndarray       # bool
    texture_flag: np.ndarray   # bool
    mask: np.ndarray           # bool, birleşik ham aday


def cva_magnitude(a: xr.Dataset, b: xr.Dataset, bands: list[str], scale: float) -> np.ndarray:
    """İki kompozit arasındaki spektral değişim vektörünün büyüklüğü (yansıtım biriminde)."""
    diff = np.stack([(b[n].values - a[n].values) / scale for n in bands])
    return np.sqrt(np.sum(diff * diff, axis=0)).astype("float32")


def otsu_threshold(values: np.ndarray, region: np.ndarray | None = None, bins: int = 256) -> float:
    """Bölge içindeki sonlu değerlerden Otsu eşiği; değerler sabitse +inf (hiçbir şey aday olmaz)."""
    v = values if region is None else values[region]
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise ValueError("Otsu için bölgede sonlu değer yok.")
    if np.ptp(v) == 0:
        return float("inf")
    return float(threshold_otsu(v, nbins=bins))


def change_candidates(
    comp_a: xr.Dataset,
    comp_b: xr.Dataset,
    tex_a: np.ndarray,
    tex_b: np.ndarray,
    settings: dict[str, Any],
    region: np.ndarray | None = None,
) -> Candidates:
    """CVA ve doku farkını ayrı ayrı Otsu ile eşikler, settings'e göre birleştirir (or/and)."""
    cfg = settings["change"]
    scale = float(settings["stac"]["reflectance_scale"])
    bins = int(cfg["otsu_bins"])
    cva = cva_magnitude(comp_a, comp_b, list(cfg["cva_bands"]), scale)
    dtex_signed = (tex_b - tex_a).astype("float32")
    dtex = np.abs(dtex_signed)
    t_cva = otsu_threshold(cva, region, bins)
    t_tex = otsu_threshold(dtex, region, bins)
    with np.errstate(invalid="ignore"):
        f_cva = np.nan_to_num(cva, nan=-1) > t_cva
        f_tex = np.nan_to_num(dtex, nan=-1) > t_tex
    combine = cfg["combine"]
    if combine == "or":
        mask = f_cva | f_tex
    elif combine == "and":
        mask = f_cva & f_tex
    else:
        raise ValueError(f"change.combine 'or' veya 'and' olmalı, '{combine}' verildi.")
    if region is not None:
        mask &= region
    return Candidates(cva, dtex, dtex_signed, t_cva, t_tex, f_cva, f_tex, mask)
