"""Aylık izleme: son 3 ay ile önceki yılın aynı 3 ayı (mevsimsel hizalı) → ön uyarı poligonları.

Önbelleğe yazmaz (CI'da cache_dir yoktur): sahneler bellekte işlenir. Kapsama eşik altındaysa analiz atlanır.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Callable, Sequence, TypeVar

import numpy as np
import xarray as xr

log = logging.getLogger(__name__)
T = TypeVar("T")


def monitor_periods(today: date, months: int) -> tuple[tuple[date, date], tuple[date, date]]:
    """Son `months` tam ay (bu ay hariç) ve önceki yılın aynı ayları: ((başlangıç, bitiş), (başlangıç, bitiş))."""
    end = today.replace(day=1) - timedelta(days=1)                  # geçen ayın son günü
    y, m = end.year, end.month - months + 1
    while m < 1:
        m, y = m + 12, y - 1
    start = date(y, m, 1)

    def prev_year(d: date) -> date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:                                           # 29 Şubat
            return d.replace(year=d.year - 1, day=28)

    return (start, end), (prev_year(start), prev_year(end))


def is_retryable(exc: BaseException) -> bool:
    """Planetary Computer / HTTP geçici hataları: 429, 5xx, zaman aşımı, bağlantı kopması."""
    msg = f"{type(exc).__name__} {exc}".lower()
    keys = ("429", "too many requests", "rate limit", "500", "502", "503", "504", "timeout", "timed out",
            "connection", "temporarily")
    return any(k in msg for k in keys)


def with_retry(fn: Callable[[], T], tries: int, base_s: float, sleep: Callable[[float], None] = time.sleep,
               retry_if: Callable[[BaseException], bool] = is_retryable) -> T:
    """fn'i geçici hatalarda üstel bekleme ile (base, 2·base, 4·base …) en çok `tries` kez dener."""
    for k in range(tries):
        try:
            return fn()
        except Exception as e:                                       # noqa: BLE001
            if k == tries - 1 or not retry_if(e):
                raise
            wait = base_s * 2 ** k
            log.warning("geçici hata (%s); %.0f s sonra yeniden denenecek (%d/%d)", e, wait, k + 1, tries - 1)
            sleep(wait)
    raise RuntimeError("ulaşılamaz")


def coverage(valid_a: np.ndarray, valid_b: np.ndarray, region: np.ndarray) -> float:
    """AOI içinde iki dönemde de geçerli kompozit değeri olan piksel oranı."""
    n = int(region.sum())
    return float((valid_a & valid_b & region).sum() / n) if n else 0.0


def change_z(comp_a: xr.Dataset, comp_b: xr.Dataset, bands: Sequence[str], region: np.ndarray,
             scale: float) -> np.ndarray:
    """Yansıtım vektörleri arasındaki CVA büyüklüğünün AOI içi sağlam z-skoru: (CVA − medyan) / (1,4826·MAD)."""
    a = np.stack([comp_a[b].values for b in bands]) / scale
    b = np.stack([comp_b[b].values for b in bands]) / scale
    return robust_z(np.sqrt(np.sum((b - a) ** 2, axis=0)), region)


def robust_z(arr: np.ndarray, region: np.ndarray) -> np.ndarray:
    """AOI içi sağlam z-skoru: (x − medyan) / (1,4826·MAD)."""
    vals = arr[region & np.isfinite(arr)]
    if vals.size == 0:
        return np.full(arr.shape, np.nan, "float32")
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) * 1.4826 or 1e-9
    return ((arr - med) / mad).astype("float32")


def warning_mask(z: np.ndarray, z_tex: np.ndarray, d_ndvi: np.ndarray, region: np.ndarray, k: float, k_tex: float,
                 max_ndvi_gain: float) -> np.ndarray:
    """Ön uyarı adayı: spektral değişim (z > k) VE doku artışı (z_doku > k_doku) VE yeşillenme değil.

    Doku koşulu yıllık yapılaşma kuralıyla aynı kanıttır; sürülen/hasat edilen tarlalar doku kazanmaz.
    """
    with np.errstate(invalid="ignore"):
        return region & np.isfinite(z) & (z > k) & (z_tex > k_tex) & ~(d_ndvi > max_ndvi_gain)


def period_composite(items: Sequence[Any], geobox: Any, region_wgs84: Any, settings: dict[str, Any],
                     load: Callable[[Any], xr.Dataset], load10: Callable[[Any], xr.Dataset]) -> xr.Dataset | None:
    """Dönemin sahnelerinden (harmonize + SCL maskesi + çekim birleştirme + geçerlilik elemesi) medyan kompozit.

    TEXTURE: kompozite alınan çekimlerin 10 m B08'inden sahne bazında yerel std → 20 m → medyan (yıllık hatla aynı).
    """
    from changewatch.composite import acquisition_key, fuse_acquisitions, median_composite
    from changewatch.harmonize import harmonize_scene
    from changewatch.indices import texture
    from changewatch.mask import aoi_raster_mask, apply_mask, valid_fraction

    mon = settings["monitor"]
    masked, region = [], None
    for it in items:
        ds = load(it)
        if region is None:
            region = aoi_raster_mask(region_wgs84, ds, settings["grid"]["crs"])
        masked.append(apply_mask(harmonize_scene(ds, settings), settings))
    kept = [m for m in fuse_acquisitions(masked)
            if valid_fraction(m["valid"].values, region) >= float(settings["mask"]["min_valid_fraction"])]
    log.info("  %d öğe → %d çekim kompozite alındı", len(items), len(kept))
    if not kept:
        return None
    cs = {**settings, "composite": {**settings["composite"], "min_valid_obs": int(mon["min_valid_obs"])}}
    comp = median_composite(kept, cs)
    keys = {acquisition_key(m) for m in kept}
    m10 = [m for m in fuse_acquisitions([apply_mask(harmonize_scene(load10(it), settings), settings) for it in items])
           if acquisition_key(m) in keys]
    tband, scale = settings["texture"]["band"], float(settings["stac"]["reflectance_scale"])
    tex = []
    for m in m10:
        t = texture(m[tband].values / scale, settings, float(settings["grid"]["resolution_m"]))
        tex.append(xr.Dataset({"TEXTURE": (("y", "x"), t), "valid": (("y", "x"), ~np.isnan(t))},
                              coords={"y": comp["y"], "x": comp["x"]}))
    comp["TEXTURE"] = median_composite(tex, cs)["TEXTURE"] if tex else (("y", "x"), np.full(comp["valid_obs"].shape, np.nan))
    return comp


def run_aoi(aoi: str, geom: Any, settings: dict[str, Any], today: date,
            client: Any | None = None) -> tuple[list[tuple[Any, dict]], dict[str, Any]]:
    """Bir AOI için aylık izleme: (poligonlar [WGS84], aylik_izleme özeti)."""
    from changewatch.indices import spectral_indices
    from changewatch.mask import aoi_raster_mask
    from changewatch.morphology import clean_mask
    from changewatch.stac import aoi_geobox, dedupe_items, filter_acquisitions, fine_geobox, load_item, search_items
    from changewatch.vectorize import grid_transform, label_pieces, piece_geometries

    mon = settings["monitor"]
    tries, base = int(mon["retry_tries"]), float(mon["retry_base_s"])
    (s1, e1), (s0, e0) = monitor_periods(today, int(mon["months"]))
    summary: dict[str, Any] = {"calisma_tarihi": today.isoformat(), "donem": [s1.isoformat(), e1.isoformat()],
                               "karsilastirma": [s0.isoformat(), e0.isoformat()],
                               "kapsama_esigi": float(mon["min_coverage"]), "z_esigi": float(mon["z_k"]),
                               "doku_z_esigi": float(mon["texture_z_k"])}
    gbox = aoi_geobox(geom, settings)
    gbox10 = fine_geobox(gbox, float(settings["texture"]["resolution_m"]))
    st = settings["stac"]
    comps = []
    for start, end in ((s0, e0), (s1, e1)):
        found = with_retry(lambda: search_items(geom.bounds, start, end, settings, client=client), tries, base)
        items = dedupe_items(filter_acquisitions(found, float(settings["stac"]["max_cloud_cover"])))
        log.info("%s %s–%s: %d öğe", aoi, start, end, len(items))
        comps.append(period_composite(
            items, gbox, geom, settings,
            lambda it: with_retry(lambda: load_item(it, gbox, settings), tries, base),
            lambda it: with_retry(lambda: load_item(it, gbox10, settings, bands=st["bands_10m"],
                                                    resampling=st["resampling_10m"]), tries, base)))
    if any(c is None for c in comps):
        summary.update(durum="atlandi", kapsama=0.0, neden="dönemlerden birinde kullanılabilir sahne yok")
        return [], summary
    a, b = comps
    crs = settings["grid"]["crs"]
    region = aoi_raster_mask(geom, a, crs)
    bands = list(mon["bands"])
    va = np.isfinite(np.stack([a[x].values for x in bands])).all(axis=0)
    vb = np.isfinite(np.stack([b[x].values for x in bands])).all(axis=0)
    cov = coverage(va, vb, region)
    summary["kapsama"] = round(cov, 3)
    if cov < float(mon["min_coverage"]):
        summary.update(durum="atlandi", neden=f"kapsama %{100 * cov:.0f} < %{100 * float(mon['min_coverage']):.0f}")
        log.warning("%s: %s; analiz atlandı", aoi, summary["neden"])
        return [], summary
    scale = float(settings["stac"]["reflectance_scale"])
    z = change_z(a, b, bands, region & va & vb, scale)
    d_ndvi = spectral_indices(b)["NDVI"].values - spectral_indices(a)["NDVI"].values
    z_tex = robust_z(b["TEXTURE"].values - a["TEXTURE"].values, region & va & vb)
    mask = clean_mask(warning_mask(z, z_tex, d_ndvi, region, float(mon["z_k"]), float(mon["texture_z_k"]),
                                   float(mon["max_ndvi_gain"])), settings)
    conn = int(settings["morphology"]["connectivity"])
    labels, n = label_pieces(mask, conn)
    geoms = piece_geometries(labels, grid_transform(a["x"].values, a["y"].values), crs, conn)
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    feats = []
    for k in range(1, n + 1):
        sel = labels == k
        feats.append((geoms[k], {
            "id": f"{aoi}-izleme-{s1:%Y%m}-{k:04d}", "aoi": aoi, "tur": "on_uyari", "durum": "on_uyari",
            "donem": summary["donem"], "karsilastirma": summary["karsilastirma"],
            "alan_ha": round(float(sel.sum()) * px_ha, 2),
            "kanit": {"cva_z": round(float(np.nanmedian(z[sel])), 2),
                      "doku_z": round(float(np.nanmedian(z_tex[sel])), 2),
                      "dNDVI": round(float(np.nanmedian(d_ndvi[sel])), 3)}}))
    summary.update(durum="tamam", poligon=len(feats), alan_ha=round(sum(f[1]["alan_ha"] for f in feats), 1))
    return feats, summary
