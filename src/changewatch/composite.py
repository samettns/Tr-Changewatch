"""Mevsimsel piksel bazlı medyan kompozit."""

from __future__ import annotations

import warnings
from typing import Any, Sequence

import numpy as np
import xarray as xr


def median_composite(scenes: Sequence[xr.Dataset], settings: dict[str, Any]) -> xr.Dataset:
    """Maskelenmiş (NaN'lı) sahnelerden piksel bazlı medyan üretir.

    'valid_obs' piksel başına geçerli gözlem sayısıdır; min_valid_obs altındaki pikseller NaN olur.
    Girdi sahneleri aynı ızgarada olmalı ve 'valid' değişkeni taşımalıdır.
    """
    if not scenes:
        raise ValueError("Kompozit için en az bir sahne gerekli.")
    min_obs = int(settings["composite"]["min_valid_obs"])
    bands = [n for n in scenes[0].data_vars if n != "valid"]
    valid = np.stack([s["valid"].values for s in scenes])
    count = valid.sum(axis=0).astype("uint16")
    enough = count >= min_obs

    out = xr.Dataset(coords={"y": scenes[0]["y"], "x": scenes[0]["x"]})
    for b in bands:
        stack = np.stack([s[b].values for s in scenes]).astype("float32")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # tamamen NaN pikseller
            med = np.nanmedian(stack, axis=0)
        out[b] = (("y", "x"), np.where(enough, med, np.nan).astype("float32"))
    out["valid_obs"] = (("y", "x"), count)
    out.attrs.update(n_scenes=len(scenes), min_valid_obs=min_obs)
    return out
