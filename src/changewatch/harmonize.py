"""Processing baseline >= 04.00 sahneler için radyometrik offset düzeltmesi."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import numpy as np
import xarray as xr

from changewatch.stac import baseline_key

log = logging.getLogger(__name__)


def needs_offset(baseline: str | None, acquired: datetime | date, settings: dict[str, Any]) -> bool:
    """Offset gerekip gerekmediğini döndürür.

    Karar s2:processing_baseline'a göre verilir; alan yoksa tarihe göre verilir ve uyarı loglanır.
    """
    cfg = settings["harmonize"]
    if baseline:
        return baseline_key(baseline) >= baseline_key(cfg["min_baseline"])
    cutoff = date.fromisoformat(cfg["fallback_date"])
    day = acquired.date() if isinstance(acquired, datetime) else acquired
    decision = day >= cutoff
    log.warning(
        "s2:processing_baseline yok (%s); tarihe göre karar verildi: offset %s",
        day.isoformat(), "uygulanıyor" if decision else "uygulanmıyor",
    )
    return decision


def apply_offset(ds: xr.Dataset, settings: dict[str, Any]) -> xr.Dataset:
    """Yansıtım bantlarından offset'i düşer (alt sınır 0); SCL'ye dokunmaz."""
    off = int(settings["harmonize"]["offset_dn"])
    scl = settings["stac"]["scl_band"]
    out = ds.copy()
    for name in ds.data_vars:
        if name == scl:
            continue
        v = ds[name].values
        out[name] = (ds[name].dims, (np.clip(v, off, None) - off).astype(v.dtype))
    return out


def harmonize_scene(ds: xr.Dataset, settings: dict[str, Any]) -> xr.Dataset:
    """Sahnenin attrs'indeki baseline ve tarihe bakarak gerekiyorsa offset uygular."""
    acquired = datetime.fromisoformat(ds.attrs["acquired"])
    out = apply_offset(ds, settings) if needs_offset(
        ds.attrs.get("processing_baseline") or None, acquired, settings
    ) else ds.copy()
    out.attrs["harmonized"] = "1"
    return out
