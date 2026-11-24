"""Yöntem karşılaştırması: tür × yıl, yöntemler arası özet ve doğrudan karşılaştırmayla tutarlılık.

Doğrulama noktası kullanmaz; eşik ayarlamaz. Elle seçilen bölgeler koda gömülmez, --region ile verilir.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import shapely
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import shape
from shapely.ops import unary_union

TYPES = ["yapilasma_olasi", "bitki_kaybi", "su_kazanimi", "su_kaybi", "sulak_alan_belirsiz", "su_degisimi",
         "belirsiz"]
BUILT = "yapilasma_olasi"


def load_features(path: Path, crs: str) -> list[tuple[Any, dict[str, Any]]]:
    """GeoJSON (WGS84) özelliklerini proje CRS'ine dönüştürerek okur."""
    to_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(shapely.transform(shape(f["geometry"]), lambda x, y: to_crs(x, y), interleaved=False),
             f["properties"]) for f in fc["features"]]


def type_year_table(features: Sequence[tuple[Any, dict]], years: Sequence[int]) -> dict[str, dict[int, float]]:
    """tür → yıl → ha (alan_ha toplamı)."""
    tab: dict[str, dict[int, float]] = {t: {y: 0.0 for y in years} for t in TYPES}
    for _, p in features:
        if p["degisim_yili"] in tab[p["tur"]]:
            tab[p["tur"]][p["degisim_yili"]] += float(p["alan_ha"])
    return tab


def _ha(geom: Any) -> float:
    return float(geom.area) / 10_000 if geom is not None else 0.0


def method_summary(features: Sequence[tuple[Any, dict]],
                   regions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Toplam yapılaşma, tüm türler (toplam ve ayak izi) ve isteğe bağlı bölgelerdeki ayak izi (ha)."""
    geoms = [g for g, _ in features]
    built = [g for g, p in features if p["tur"] == BUILT]
    out: dict[str, Any] = {
        "yapilasma_ha": round(sum(float(p["alan_ha"]) for _, p in features if p["tur"] == BUILT), 1),
        "tum_turler_ha": round(sum(float(p["alan_ha"]) for _, p in features), 1),
        "ayak_izi_ha": round(_ha(unary_union(geoms)) if geoms else 0.0, 1),
        "bolgeler": {},
    }
    for name, reg in (regions or {}).items():
        out["bolgeler"][name] = {
            "bolge_ha": round(_ha(reg), 1),
            "ayak_izi_ha": round(_ha(unary_union([g.intersection(reg) for g in geoms])) if geoms else 0.0, 1),
            "yapilasma_ha": round(_ha(unary_union([g.intersection(reg) for g in built])) if built else 0.0, 1),
        }
    return out


def direct_built_mask(comp_a, comp_b, tex_a: np.ndarray, tex_b: np.ndarray, settings: dict[str, Any],
                      region: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    """Doğrudan A→B karşılaştırması: Otsu adayı + morfoloji/MMU, doku artışı payı ≥ eşik olan parçalar."""
    from changewatch.change import change_candidates
    from changewatch.morphology import clean_mask
    from changewatch.vectorize import label_pieces

    c = change_candidates(comp_a, comp_b, tex_a, tex_b, settings, region)
    fin = clean_mask(c.mask, settings) & region
    labels, n = label_pieces(fin, int(settings["morphology"]["connectivity"]))
    inc = np.nan_to_num(c.dtexture_signed, nan=-1) > c.texture_threshold
    min_share = float(settings["classify"]["texture_increase_min_share"])
    built = np.zeros_like(fin)
    for k in range(1, n + 1):
        sel = labels == k
        if inc[sel].mean() >= min_share:
            built |= sel
    return built, {"cva_esik": c.cva_threshold, "doku_esik": c.texture_threshold}


def consistency(built_direct: np.ndarray, features: Sequence[tuple[Any, dict]], year_a: int, year_b: int,
                transform: Affine, px_ha: float) -> dict[str, float]:
    """Kırılma/çift yapılaşmasını (year_a < yıl ≤ year_b) doğrudan A→B yapılaşma maskesiyle karşılaştırır."""
    geoms = [g for g, p in features if p["tur"] == BUILT and year_a < p["degisim_yili"] <= year_b]
    m = (rasterize([(g, 1) for g in geoms], out_shape=built_direct.shape, transform=transform).astype(bool)
         if geoms else np.zeros_like(built_direct))
    ov = float((m & built_direct).sum())
    return {
        "yontem_yapilasma_ha": round(sum(float(p["alan_ha"]) for g, p in features
                                         if p["tur"] == BUILT and year_a < p["degisim_yili"] <= year_b), 1),
        "dogrudan_ha": round(float(built_direct.sum()) * px_ha, 1),
        "yontemin_dogrudan_icindeki_payi": round(ov / m.sum(), 3) if m.sum() else None,
        "dogrudanin_kapsanan_payi": round(ov / built_direct.sum(), 3) if built_direct.sum() else None,
    }


def markdown_type_year(tab: dict[str, dict[int, float]], years: Sequence[int]) -> str:
    """tür × yıl tablosu (markdown)."""
    lines = ["| tür | " + " | ".join(map(str, years)) + " | toplam |",
             "|---|" + "---|" * (len(years) + 1)]
    for t in TYPES:
        row = [tab[t][y] for y in years]
        lines.append(f"| {t} | " + " | ".join(f"{v:.0f}" for v in row) + f" | {sum(row):.0f} |")
    tot = [sum(tab[t][y] for t in TYPES) for y in years]
    lines.append("| toplam | " + " | ".join(f"{v:.0f}" for v in tot) + f" | {sum(tot):.0f} |")
    return "\n".join(lines)
