"""cache_dir'deki sahne ve kompozit GeoTIFF'lerini okuma/yazma."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
from affine import Affine


def raw_dir(cache: Path, aoi: str, year: int) -> Path:
    """Ham sahnelerin klasörü: <cache>/<aoi>/raw/<yıl>/."""
    return cache / aoi / "raw" / str(year)


def raw10_dir(cache: Path, aoi: str, year: int) -> Path:
    """Doku için 10 m ham sahneler (B08 + SCL): <cache>/<aoi>/raw10m/<yıl>/."""
    return cache / aoi / "raw10m" / str(year)


def indices_dir(cache: Path, aoi: str, season: str) -> Path:
    """İndeks GeoTIFF'leri: <cache>/<aoi>/indices/<mevsim>/."""
    return cache / aoi / "indices" / season


def change_dir(cache: Path, aoi: str, season: str) -> Path:
    """Değişim çıktıları: <cache>/<aoi>/change/<mevsim>/."""
    return cache / aoi / "change" / season


def composite_dir(cache: Path, aoi: str, season: str) -> Path:
    """Kompozitlerin klasörü: <cache>/<aoi>/composite/<mevsim>/."""
    return cache / aoi / "composite" / season


def preview_dir(cache: Path, aoi: str) -> Path:
    """Gözle kontrol PNG'lerinin klasörü: <cache>/<aoi>/preview/."""
    return cache / aoi / "preview"


def _transform(ds: xr.Dataset) -> Affine:
    x, y = ds["x"].values, ds["y"].values
    rx, ry = float(x[1] - x[0]), float(y[1] - y[0])
    return Affine(rx, 0.0, float(x[0]) - rx / 2, 0.0, ry, float(y[0]) - ry / 2)


def write_dataset(ds: xr.Dataset, path: Path, crs: str, nodata: float | int | None = None) -> Path:
    """(y, x) Dataset'i çok bantlı GeoTIFF olarak yazar; bant adları ve attrs etiket olarak saklanır."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(ds.data_vars)
    data = np.stack([ds[n].values for n in names])
    profile = dict(
        driver="GTiff", width=data.shape[2], height=data.shape[1], count=len(names),
        dtype=data.dtype, crs=crs, transform=_transform(ds), compress="deflate",
        tiled=True, blockxsize=256, blockysize=256, nodata=nodata,
    )
    tmp = path.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(data)
        for i, n in enumerate(names, start=1):
            dst.set_band_description(i, n)
        dst.update_tags(**{k: str(v) for k, v in ds.attrs.items()})
    tmp.replace(path)  # yarım kalan indirme önbellekte geçerli sayılmasın
    return path


def read_dataset(path: Path) -> xr.Dataset:
    """write_dataset ile yazılmış GeoTIFF'i (y, x) Dataset olarak okur."""
    with rasterio.open(path) as src:
        data = src.read()
        t = src.transform
        names = list(src.descriptions)
        tags = src.tags()
        crs = src.crs.to_string()
    h, w = data.shape[1:]
    x = t.c + t.a * (np.arange(w) + 0.5)
    y = t.f + t.e * (np.arange(h) + 0.5)
    ds = xr.Dataset({n: (("y", "x"), data[i]) for i, n in enumerate(names)}, coords={"y": y, "x": x})
    ds.attrs.update(tags)
    ds.attrs["crs"] = crs
    return ds
