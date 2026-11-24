"""NDVI, NDBI, MNDWI, BSI ve B08 (10 m) yerel std doku indeksleri."""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr
from scipy.ndimage import uniform_filter


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b); payda 0 ise NaN."""
    a = a.astype("float32")
    b = b.astype("float32")
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / den
    return np.where(den == 0, np.nan, out).astype("float32")


def spectral_indices(comp: xr.Dataset) -> xr.Dataset:
    """20 m kompozitten NDVI, NDBI, MNDWI ve BSI (oran indeksleri; ölçekten bağımsız)."""
    b02, b03, b04 = comp["B02"].values, comp["B03"].values, comp["B04"].values
    b08, b11 = comp["B08"].values, comp["B11"].values
    out = xr.Dataset(coords={"y": comp["y"], "x": comp["x"]})
    out["NDVI"] = (("y", "x"), normalized_difference(b08, b04))
    out["NDBI"] = (("y", "x"), normalized_difference(b11, b08))
    out["MNDWI"] = (("y", "x"), normalized_difference(b03, b11))
    out["BSI"] = (("y", "x"), normalized_difference(b11 + b04, b08 + b02))
    return out


def local_std(arr: np.ndarray, window: int, min_valid: float) -> np.ndarray:
    """NaN'a duyarlı kayan pencere standart sapması; pencerede geçerli oran < min_valid ise NaN."""
    valid = ~np.isnan(arr)
    x = np.where(valid, arr, 0.0).astype("float64")
    w = uniform_filter(valid.astype("float64"), window, mode="reflect")
    with np.errstate(divide="ignore", invalid="ignore"):
        m1 = uniform_filter(x, window, mode="reflect") / w
        m2 = uniform_filter(x * x, window, mode="reflect") / w
        std = np.sqrt(np.clip(m2 - m1 * m1, 0, None))  # w=0 pencereler NaN; aşağıda atılır
    return np.where((w >= min_valid - 1e-6) & valid, std, np.nan).astype("float32")


def block_mean(arr: np.ndarray, k: int) -> np.ndarray:
    """k×k blok ortalaması (NaN'ları yok sayar); ör. 10 m → 20 m için k=2."""
    h, w = arr.shape
    if h % k or w % k:
        raise ValueError(f"Boyut {arr.shape}, {k}'nin katı değil.")
    blocks = arr.reshape(h // k, k, w // k, k)
    with np.errstate(invalid="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(blocks, axis=(1, 3)).astype("float32")


def texture(b08_fine: np.ndarray, settings: dict[str, Any], work_res_m: float) -> np.ndarray:
    """Tek sahnenin maskeli (NaN'lı) 10 m B08 yansıtımında yerel std → çalışma ızgarasına (20 m) blok ortalaması.

    Pencerede geçerli oran min_window_valid altındaysa NaN. Sahneler arası medyan
    composite.median_composite ile alınır.
    """
    t = settings["texture"]
    k = int(round(work_res_m / float(t["resolution_m"])))
    std = local_std(b08_fine, int(t["window_px"]), float(t["min_window_valid"]))
    return block_mean(std, k)

