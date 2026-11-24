"""Değişim rasterinin GeoJSON poligonlara dönüştürülmesi."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.features import shapes
from scipy.ndimage import label
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


def label_pieces(mask: np.ndarray, connectivity: int) -> tuple[np.ndarray, int]:
    """Bağlı bileşen etiketleri (1..n); connectivity 2 = 8-komşuluk."""
    structure = np.ones((3, 3), int) if connectivity == 2 else None
    labels, n = label(mask, structure=structure)
    return labels.astype("int32"), int(n)


def grid_transform(x: np.ndarray, y: np.ndarray) -> Affine:
    """Piksel merkezi koordinatlarından affine dönüşüm."""
    rx, ry = float(x[1] - x[0]), float(y[1] - y[0])
    return Affine(rx, 0.0, float(x[0]) - rx / 2, 0.0, ry, float(y[0]) - ry / 2)


def piece_geometries(labels: np.ndarray, transform: Affine, crs: str, connectivity: int) -> dict[int, Any]:
    """Etiket → WGS84 (EPSG:4326) shapely geometrisi."""
    conn = 8 if connectivity == 2 else 4
    parts: dict[int, list] = {}
    for geom, val in shapes(labels, mask=labels > 0, transform=transform, connectivity=conn):
        parts.setdefault(int(val), []).append(shape(geom))
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    return {k: shapely.transform(unary_union(v), lambda x, y: to_wgs(x, y), interleaved=False)
            for k, v in parts.items()}


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def write_geojson(features: list[tuple[Any, dict[str, Any]]], path: Path, precision: int = 6) -> Path:
    """(geometri, özellikler) listesini GeoJSON FeatureCollection olarak yazar (WGS84)."""
    from shapely import set_precision

    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": _clean(props),
             "geometry": mapping(set_precision(geom, 10 ** -precision))}
            for geom, props in features
        ],
    }
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return path
