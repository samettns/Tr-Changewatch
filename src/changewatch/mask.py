"""SCL sınıflarına göre bulut/gölge/sirrus/kar/no-data maskesi ve sahne geçerlilik oranı."""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr


def valid_mask(scl: np.ndarray, settings: dict[str, Any]) -> np.ndarray:
    """SCL maskelenen sınıflardan biri değilse True."""
    return ~np.isin(scl, settings["mask"]["scl_masked_classes"])


def apply_mask(ds: xr.Dataset, settings: dict[str, Any]) -> xr.Dataset:
    """Geçersiz pikselleri NaN yapar; yansıtım bantları float32 döner, SCL düşürülür.

    Sonuçta 'valid' (bool) değişkeni de bulunur.
    """
    scl_name = settings["stac"]["scl_band"]
    valid = valid_mask(ds[scl_name].values, settings)
    out = xr.Dataset(coords=ds.coords, attrs=dict(ds.attrs))
    for name in ds.data_vars:
        if name == scl_name:
            continue
        out[name] = (ds[name].dims, np.where(valid, ds[name].values.astype("float32"), np.nan))
    out["valid"] = (ds[scl_name].dims, valid)
    return out


def valid_fraction(valid: np.ndarray, aoi_mask: np.ndarray | None = None) -> float:
    """AOI içindeki (aoi_mask True) geçerli piksel oranı."""
    if aoi_mask is None:
        aoi_mask = np.ones_like(valid, dtype=bool)
    n = int(aoi_mask.sum())
    return float((valid & aoi_mask).sum() / n) if n else 0.0


def aoi_raster_mask(geometry_wgs84: Any, ds: xr.Dataset, crs: str) -> np.ndarray:
    """AOI poligonunun (y, x) ızgarasındaki ikili maskesi (içeride True)."""
    import geopandas as gpd
    from affine import Affine
    from rasterio.features import geometry_mask

    x, y = ds["x"].values, ds["y"].values
    rx, ry = float(x[1] - x[0]), float(y[1] - y[0])
    transform = Affine(rx, 0.0, float(x[0]) - rx / 2, 0.0, ry, float(y[0]) - ry / 2)
    geom = gpd.GeoSeries([geometry_wgs84], crs="EPSG:4326").to_crs(crs).iloc[0]
    return geometry_mask([geom], out_shape=(len(y), len(x)), transform=transform, invert=True)
