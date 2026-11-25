"""Web haritası için hafif çıktılar: sadeleştirilmiş değişim GeoJSON'u, stats.json, önizleme PNG'leri."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import mapping

PUBLIC_CORE = ("tur", "degisim_yili", "onceki_yil", "alan_ha", "guven", "durum", "katman")


def public_feature(geom_utm: Any, props: dict[str, Any], crs: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Tek poligonu sadeleştirip WGS84'e çevirir; yalnızca çekirdek + kanıt alanlarını tutar."""
    p = settings["publish"]
    g = geom_utm.simplify(float(p["simplify_m"]), preserve_topology=True)
    if g.is_empty:
        g = geom_utm
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    g = shapely.transform(g, lambda x, y: to_wgs(x, y), interleaved=False)
    g = shapely.set_precision(g, 10 ** -int(p["coord_decimals"]))
    out = {"id": props.get("id")}
    out.update({k: props[k] for k in PUBLIC_CORE if k in props})
    out["kanit"] = {k: props[k] for k in p["evidence_props"] if k in props}
    return {"type": "Feature", "properties": out, "geometry": mapping(g)}


def public_layer(features: Iterable[tuple[Any, dict[str, Any]]], crs: str, settings: dict[str, Any]
                 ) -> dict[str, Any]:
    """Yayınlanan türlerdeki poligonlardan FeatureCollection (su türleri ve diğerleri düşer)."""
    types = set(settings["publish"]["types"])
    feats = [public_feature(g, pr, crs, settings) for g, pr in features if pr.get("tur") in types]
    feats.sort(key=lambda f: (f["properties"].get("degisim_yili") or 0, f["properties"].get("id") or ""))
    return {"type": "FeatureCollection", "features": feats}


def type_year_ha(features: Iterable[tuple[Any, dict[str, Any]]], types: Sequence[str]) -> dict[str, dict[str, float]]:
    """tür → {yıl: ha} (poligonların alan_ha alanından; sadeleştirmeden önce)."""
    out: dict[str, dict[str, float]] = {t: {} for t in types}
    for _, pr in features:
        t = pr.get("tur")
        if t not in out:
            continue
        y = str(int(pr["degisim_yili"]))
        out[t][y] = round(out[t].get(y, 0.0) + float(pr.get("alan_ha", 0.0)), 2)
    return {t: dict(sorted(v.items())) for t, v in out.items()}


def warp_rgba(rgba: np.ndarray, transform: Any, src_crs: str, dst_crs: str) -> tuple[np.ndarray, list[list[float]]]:
    """(H, W, 4) RGBA'yı dst_crs'e en yakın komşuyla yeniden örnekler; Leaflet sınırları [[güney, batı], [kuzey, doğu]]."""
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    h, w = rgba.shape[:2]
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    dt, dw, dh = calculate_default_transform(src_crs, dst_crs, w, h, left=left, bottom=bottom, right=right, top=top)
    out = np.zeros((4, dh, dw), dtype="float32")
    for i in range(4):
        reproject(rgba[..., i].astype("float32"), out[i], src_transform=transform, src_crs=src_crs,
                  dst_transform=dt, dst_crs=dst_crs, resampling=Resampling.nearest, src_nodata=None, dst_nodata=0)
    to_ll = Transformer.from_crs(dst_crs, "EPSG:4326", always_xy=True).transform
    (x0, y1), (x1, y0) = dt * (0, 0), dt * (dw, dh)
    w_lon, s_lat = to_ll(x0, y0)
    e_lon, n_lat = to_ll(x1, y1)
    return np.moveaxis(out, 0, -1), [[round(s_lat, 6), round(w_lon, 6)], [round(n_lat, 6), round(e_lon, 6)]]


def png_bytes(rgba: np.ndarray, colors: int) -> bytes:
    """RGBA (0–1) → paletli PNG baytları (saydamlık korunur)."""
    from PIL import Image

    arr = (np.clip(rgba, 0, 1) * 255).round().astype("uint8")
    img = Image.fromarray(arr, "RGBA").quantize(colors=int(colors), method=Image.Quantize.FASTOCTREE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def check_budget(root: Path, max_total_mb: float, max_png_kb: float) -> dict[str, Any]:
    """docs/data boyut bütçesi: toplam ve PNG başına sınır. İhlaller listelenir."""
    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    big = [str(p.relative_to(root)) for p in files if p.suffix.lower() == ".png" and p.stat().st_size > max_png_kb * 1024]
    return {"toplam_mb": round(total / 2**20, 2), "dosya": len(files), "buyuk_png": big,
            "ok": total <= max_total_mb * 2**20 and not big}


def _pick(rep: dict[str, Any]) -> dict[str, Any]:
    """validate grubundan sayfada gösterilen metrikler."""
    y = rep["sinif_metrikleri"].get("yapilasma_olasi", {})
    b, o = rep["ikili"], rep.get("olofsson") or {}
    oy = (o.get("siniflar") or {}).get("yapilasma_olasi", {})
    return {"n": rep["n"], "degisim_kesinlik": b["kesinlik"], "degisim_duyarlilik": b["duyarlilik"],
            "yapilasma_kesinlik": y.get("kullanici_dogrulugu"), "yapilasma_duyarlilik": y.get("uretici_dogrulugu"),
            "yapilasma_f1": y.get("f1"), "olofsson_genel": o.get("genel_dogruluk"),
            "olofsson_genel_ga": o.get("genel_dogruluk_ga"), "yapilasma_harita_ha": oy.get("harita_alani_ha"),
            "yapilasma_kestirim_ha": oy.get("kestirilen_alan_ha"), "yapilasma_kestirim_ga_ha": oy.get("alan_ga_ha"),
            "yil_tam": rep["yil"]["tam_isabet"], "yil_pm1": rep["yil"]["pm1_isabet"],
            "yil_n": rep["yil"]["degisim_yakalanan_n"]}


def accuracy_summary(dev: dict[str, Any] | None, test: dict[str, Any] | None,
                     unsure: dict[str, int] | None = None) -> dict[str, Any]:
    """Geliştirme (metrics_test.json) ve test AOI (metrics_test_aoi.json) gruplarının özeti."""
    out: dict[str, Any] = {"gelistirme": {}, "test_aoi": {}}
    for key, m in (("gelistirme", dev), ("test_aoi", test)):
        for name, rep in ((m or {}).get("gruplar") or {}).items():
            d = _pick(rep)
            name = name.replace(" + ", "+")
            if unsure and name in unsure:
                d["emin_degilim"] = unsure[name]
            out[key][name] = d
    return out


def write_json(path: Path, obj: Any) -> Path:
    """Küçük, okunabilir JSON (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path
