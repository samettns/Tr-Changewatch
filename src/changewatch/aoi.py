"""AOI okuma ve check-aois kontrolleri (alan, sınırlar, Ankara kutusu)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


@dataclass
class AoiReport:
    """Tek bir AOI için kontrol sonucu."""

    name: str
    area_km2: float
    bounds: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat
    warnings: list[str] = field(default_factory=list)


def load_aois(path: Path | str) -> gpd.GeoDataFrame:
    """AOI GeoJSON'unu WGS84 olarak okur."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"AOI dosyası bulunamadı: {path}")
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs("EPSG:4326")


def check_aois(gdf: gpd.GeoDataFrame, settings: dict[str, Any]) -> list[AoiReport]:
    """Her AOI için alan (km², proje CRS'inde) ve sınırları hesaplar, uyarıları ekler."""
    if gdf.empty:
        return []
    checks = settings["aoi_checks"]
    max_km2 = float(checks["max_aoi_km2"])
    bb = checks["ankara_bbox"]
    ankara = box(bb["min_lon"], bb["min_lat"], bb["max_lon"], bb["max_lat"])
    areas = gdf.geometry.to_crs(settings["grid"]["crs"]).area / 1e6

    reports: list[AoiReport] = []
    for i, (idx, row) in enumerate(gdf.iterrows(), start=1):
        name = row.get("name") if "name" in gdf.columns else None
        if pd.isna(name) or not str(name).strip():  # eksik alan NaN olarak gelir
            name = None
        geom = row.geometry
        empty = geom is None or geom.is_empty
        rep = AoiReport(
            name=str(name) if name else f"<adsız #{i}>",
            area_km2=0.0 if empty else float(areas.loc[idx]),
            bounds=(float("nan"),) * 4 if empty else tuple(float(v) for v in geom.bounds),
        )
        if not name:
            rep.warnings.append("'name' özelliği yok; geojson'da properties.name ekleyin.")
        if empty:
            rep.warnings.append("Geometri boş.")
            reports.append(rep)
            continue
        if not geom.is_valid:
            rep.warnings.append("Geometri geçersiz (kendini kesen poligon olabilir).")
        if rep.area_km2 > max_km2:
            rep.warnings.append(f"Alan {rep.area_km2:.1f} km² > {max_km2:g} km² sınırı.")
        if not ankara.contains(geom):
            rep.warnings.append("AOI kaba Ankara sınır kutusunun dışına taşıyor.")
        reports.append(rep)
    return reports
