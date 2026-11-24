"""Komut satırı arayüzü: changewatch <komut>."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from changewatch import __version__
from changewatch.config import ConfigError, load_settings, require_cache_dir, resolve_path

log = logging.getLogger("changewatch")


# ---------------------------------------------------------------- yardımcılar

def parse_years(tokens: list[str] | None, settings: dict[str, Any]) -> list[int]:
    """'2017 2024' veya '2017-2026' biçimini yıl listesine çevirir; boşsa settings'teki aralık."""
    if not tokens:
        y = settings["years"]
        return list(range(int(y["start"]), int(y["end"]) + 1))
    years: set[int] = set()
    for tok in tokens:
        for part in tok.split(","):
            if "-" in part:
                a, b = (int(v) for v in part.split("-", 1))
                years.update(range(a, b + 1))
            elif part:
                years.add(int(part))
    return sorted(years)


def get_aoi(settings: dict[str, Any], name: str):
    """Adı verilen AOI'nin WGS84 geometrisini döndürür."""
    from changewatch.aoi import load_aois

    gdf = load_aois(resolve_path(settings, settings["paths"]["aois"]))
    match = gdf[gdf["name"] == name] if "name" in gdf.columns else gdf.iloc[0:0]
    if match.empty:
        names = ", ".join(map(str, gdf.get("name", []))) or "(yok)"
        raise ConfigError(f"AOI bulunamadı: '{name}'. Mevcut AOI'ler: {names}")
    return match.geometry.iloc[0]


def setup_logging(settings: dict[str, Any] | None = None) -> None:
    """Konsola ve (cache_dir varsa) <cache_dir>/logs/changewatch.log dosyasına log yazar."""
    root = logging.getLogger("changewatch")
    root.setLevel(logging.INFO)
    if not any(type(h) is logging.StreamHandler for h in root.handlers):
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        root.addHandler(h)
    if settings and not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        try:
            logs = require_cache_dir(settings) / "logs"
            logs.mkdir(exist_ok=True)
            fh = logging.FileHandler(logs / "changewatch.log", encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(fh)
        except ConfigError:
            pass


def _human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# ---------------------------------------------------------------- komutlar

def cmd_check_aois(args: argparse.Namespace) -> int:
    """AOI'lerin adını, alanını ve sınırlarını yazdırır; uyarılar AOI'yi engellemez."""
    from changewatch.aoi import check_aois, load_aois

    settings = load_settings(args.config)
    path = resolve_path(settings, args.aois or settings["paths"]["aois"])
    reports = check_aois(load_aois(path), settings)
    if not reports:
        print(f"AOI bulunamadı: {path} (features listesi boş).")
        return 0

    n_warn = 0
    for r in reports:
        lo, la, hi_lo, hi_la = r.bounds
        print(f"{r.name}")
        print(f"  alan    : {r.area_km2:.2f} km²")
        print(f"  sınırlar: boylam {lo:.5f} – {hi_lo:.5f}, enlem {la:.5f} – {hi_la:.5f}")
        for w in r.warnings:
            print(f"  UYARI   : {w}")
        n_warn += len(r.warnings)
    print(f"\n{len(reports)} AOI kontrol edildi, {n_warn} uyarı.")
    return 0


def cmd_scenes(args: argparse.Namespace) -> int:
    """Yıl başına mevsim penceresindeki sahne özetini tablo olarak yazdırır (indirme yok)."""
    from changewatch.stac import scene_info, search_items, season_dates

    settings = load_settings(args.config)
    bbox = get_aoi(settings, args.aoi).bounds
    thr = float(settings["scenes"]["report_cloud_threshold"])
    print(f"AOI: {args.aoi} | mevsim: {args.season or settings['composite']['season']} "
          "| bulut oranı sahne (MGRS karesi) düzeyindedir\n")
    print(f"| Yıl | Sahne (öğe) | Farklı tarih | Bulut <%{thr:g} (öğe) | Bulut <%{thr:g} (tarih) "
          "| Processing baseline (öğe sayısı) | MGRS |")
    print("|---|---|---|---|---|---|---|")
    for year in parse_years(args.years, settings):
        start, end = season_dates(year, settings, args.season)
        infos = [scene_info(i) for i in search_items(bbox, start, end, settings)]
        low = [i for i in infos if i.cloud_cover is not None and i.cloud_cover < thr]
        pb = Counter(i.processing_baseline or "YOK" for i in infos)
        tiles = ",".join(sorted({i.mgrs_tile for i in infos if i.mgrs_tile})) or "-"
        print(f"| {year} | {len(infos)} | {len({i.acquired.date() for i in infos})} | {len(low)} "
              f"| {len({i.acquired.date() for i in low})} "
              f"| {', '.join(f'{k}×{v}' for k, v in sorted(pb.items())) or '-'} | {tiles} |")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """AOI penceresini okuyup ham sahneleri cache_dir'e GeoTIFF olarak kaydeder (önbellekte varsa atlar)."""
    from changewatch import cache
    from changewatch.stac import (aoi_geobox, dedupe_items, filter_acquisitions, fine_geobox, load_item,
                                  search_items, season_dates)

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    gbox = aoi_geobox(geom, settings)
    gbox10 = fine_geobox(gbox, float(settings["texture"]["resolution_m"]))
    cfg = settings["stac"]
    max_cloud = float(settings["stac"]["max_cloud_cover"])
    log.info("AOI %s ızgarası: %s px, %s m, %s", args.aoi, gbox.shape, settings["grid"]["resolution_m"],
             settings["grid"]["crs"])

    total_new = 0
    for year in parse_years(args.years, settings):
        start, end = season_dates(year, settings, args.season)
        found = filter_acquisitions(search_items(geom.bounds, start, end, settings), max_cloud)
        items = dedupe_items(found)
        log.info("%d: %d öğe (çekimin bir karesi bulut < %%%g), kopya ayıklama sonrası %d", year, len(found), max_cloud,
                 len(items))
        layers = [  # (klasör, ızgara, bantlar, örnekleme)
            (cache.raw_dir(cache_root, args.aoi, year), gbox, cfg["bands"], cfg["resampling"]),
            (cache.raw10_dir(cache_root, args.aoi, year), gbox10, cfg["bands_10m"], cfg["resampling_10m"]),
        ]
        for out_dir, gb, bands, resampling in layers:
            new = 0
            for it in items:
                path = out_dir / f"{it.id}.tif"
                if path.exists():
                    continue
                ds = load_item(it, gb, settings, bands=bands, resampling=resampling)
                cache.write_dataset(ds, path, settings["grid"]["crs"], nodata=cfg["nodata"])
                new += path.stat().st_size
                log.info("  indirildi: %s (%s)", path.relative_to(cache_root), _human(path.stat().st_size))
            size = sum(p.stat().st_size for p in out_dir.glob("*.tif")) if out_dir.exists() else 0
            log.info("%d: yeni %s, klasör toplamı %s (%s)", year, _human(new), _human(size), out_dir)
            total_new += new
    log.info("Toplam yeni veri: %s", _human(total_new))
    return 0


def cmd_composite(args: argparse.Namespace) -> int:
    """Önbellekteki sahneleri harmonize + maskeler, düşük geçerlilikli sahneleri eler, medyan kompozit üretir."""
    import numpy as np
    import xarray as xr

    from changewatch import cache
    from changewatch.composite import acquisition_key, fuse_acquisitions, median_composite
    from changewatch.harmonize import harmonize_scene
    from changewatch.indices import texture
    from changewatch.mask import aoi_raster_mask, apply_mask, valid_fraction
    from changewatch.quicklook import save_rgb_png, save_valid_obs_png

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    min_frac = float(settings["mask"]["min_valid_fraction"])
    crs = settings["grid"]["crs"]

    for year in parse_years(args.years, settings):
        files = sorted(cache.raw_dir(cache_root, args.aoi, year).glob("*.tif"))
        if not files:
            log.warning("%d: önbellekte sahne yok; önce `changewatch fetch` çalıştırın.", year)
            continue
        masked_all, aoi_mask = [], None
        for f in files:
            raw = cache.read_dataset(f)
            if aoi_mask is None:
                aoi_mask = aoi_raster_mask(geom, raw, crs)
            masked_all.append(apply_mask(harmonize_scene(raw, settings), settings))
        # Aynı çekimin farklı MGRS kareleri (kare örtüşmesi) tek sahneye birleştirilir
        fused = fuse_acquisitions(masked_all)
        if len(fused) < len(masked_all):
            log.info("%d: %d kare-sahnesi → %d çekim (MGRS kare örtüşmesi birleştirildi)", year,
                     len(masked_all), len(fused))
        kept, kept_keys = [], set()
        for masked in fused:
            frac = valid_fraction(masked["valid"].values, aoi_mask)
            if frac < min_frac:
                log.warning("%d: %s kompozite alınmadı (AOI içi geçerli piksel %%%.0f < %%%.0f)",
                            year, masked.attrs["item_id"], 100 * frac, 100 * min_frac)
                continue
            kept.append(masked)
            kept_keys.add(acquisition_key(masked))
        log.info("%d: %d/%d çekim kompozite alındı", year, len(kept), len(fused))
        if not kept:
            continue
        comp = median_composite(kept, settings)
        comp.attrs.update(aoi=args.aoi, year=year, season=season)

        tif = cache.composite_dir(cache_root, args.aoi, season) / f"{year}.tif"
        cache.write_dataset(comp.astype("float32"), tif, crs, nodata=np.nan)
        prev = cache.preview_dir(cache_root, args.aoi)
        rgb = save_rgb_png(comp, prev / f"{year}_{season}_rgb.png", settings)
        obs = save_valid_obs_png(comp, prev / f"{year}_{season}_valid_obs.png", settings,
                                 f"{args.aoi} {year} ({season}) – {len(kept)} sahne")
        cnt = comp["valid_obs"].values[aoi_mask]
        log.info("%d: geçerli gözlem (AOI içi) min %d / medyan %d / maks %d; <%d olan piksel %%%.2f",
                 year, cnt.min(), int(np.median(cnt)), cnt.max(), settings["composite"]["min_valid_obs"],
                 100 * float((cnt < settings["composite"]["min_valid_obs"]).mean()))
        outputs = [tif, rgb, obs]

        # Doku: her sahnede ayrı (maskeli 10 m B08 → yerel std → 20 m), sonra sahnelerin medyanı.
        # 20 m'de kompozite alınan sahnelerin aynısı kullanılır.
        m10_all = [apply_mask(harmonize_scene(cache.read_dataset(f), settings), settings)
                   for f in sorted(cache.raw10_dir(cache_root, args.aoi, year).glob("*.tif"))]
        fused10 = [m for m in fuse_acquisitions(m10_all) if acquisition_key(m) in kept_keys]
        if len(fused10) != len(kept_keys):
            log.warning("%d: 10 m katmanında %d/%d çekim var; `changewatch fetch` ile tamamlayın.",
                        year, len(fused10), len(kept_keys))
        if fused10:
            tband = settings["texture"]["band"]
            scale = float(settings["stac"]["reflectance_scale"])
            work_res = float(settings["grid"]["resolution_m"])
            tex_scenes = []
            for m10 in fused10:
                tex = texture(m10[tband].values / scale, settings, work_res)
                tex_scenes.append(xr.Dataset({"TEXTURE": (("y", "x"), tex),
                                              "valid": (("y", "x"), ~np.isnan(tex))},
                                             coords={"y": comp["y"], "x": comp["x"]}))
            tcomp = median_composite(tex_scenes, settings)
            tcomp.attrs.update(aoi=args.aoi, year=year, season=season, method="per-scene std, median")
            ttif = cache.composite_dir(cache_root, args.aoi, season) / f"{year}_texture.tif"
            cache.write_dataset(tcomp.astype("float32"), ttif, crs, nodata=np.nan)
            outputs.append(ttif)
        for p in outputs:
            log.info("  çıktı: %s (%s)", p, _human(p.stat().st_size))
    return 0


def cmd_indices(args: argparse.Namespace) -> int:
    """Kompozitlerden NDVI, NDBI, MNDWI, BSI ve 10 m B08 dokusunu hesaplar; GeoTIFF + PNG yazar."""
    import numpy as np

    from changewatch import cache
    from changewatch.indices import spectral_indices
    from changewatch.quicklook import save_index_png

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    cdir = cache.composite_dir(cache_root, args.aoi, season)

    for year in parse_years(args.years, settings):
        f20, ftex = cdir / f"{year}.tif", cdir / f"{year}_texture.tif"
        if not (f20.exists() and ftex.exists()):
            log.warning("%d: kompozit eksik (%s, %s); önce fetch + composite çalıştırın.", year,
                        f20.exists(), ftex.exists())
            continue
        ix = spectral_indices(cache.read_dataset(f20))
        ix["TEXTURE"] = (("y", "x"), cache.read_dataset(ftex)["TEXTURE"].values)
        ix.attrs.update(aoi=args.aoi, year=year, season=season)
        out = cache.indices_dir(cache_root, args.aoi, season) / f"{year}.tif"
        cache.write_dataset(ix, out, crs, nodata=np.nan)
        log.info("%d: indeksler → %s (%s)", year, out, _human(out.stat().st_size))
        prev = cache.preview_dir(cache_root, args.aoi) / "indices"
        for name in ix.data_vars:
            arr = ix[name].values
            p = save_index_png(arr, name, prev / f"{year}_{season}_{name}.png", settings,
                               f"{args.aoi} {year} ({season}) – {name}")
            log.info("  %-7s medyan %.3f  p5 %.3f  p95 %.3f  → %s", name, np.nanmedian(arr),
                     np.nanpercentile(arr, 5), np.nanpercentile(arr, 95), p.name)
    return 0


def _detect_pairs(args: argparse.Namespace) -> int:
    """Ardışık yıl çiftlerinde aday → morfoloji → MMU → kalıcılık → tür/güven → GeoJSON."""
    import numpy as np
    import xarray as xr

    from changewatch import cache
    from changewatch.change import change_candidates, cva_magnitude
    from changewatch.classify import classify_piece, piece_evidence, pixel_persistence
    from changewatch.indices import spectral_indices
    from changewatch.mask import aoi_raster_mask
    from changewatch.morphology import apply_mmu, open_close
    from changewatch.quicklook import save_overlay_png
    from changewatch.vectorize import grid_transform, label_pieces, piece_geometries

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    scale = float(settings["stac"]["reflectance_scale"])
    conn = int(settings["morphology"]["connectivity"])
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    years = parse_years(args.years, settings)
    if len(years) < 2 or any(b - a != 1 for a, b in zip(years, years[1:])):
        raise ConfigError(f"En az iki ardışık yıl gerekli: {years}")

    cdir = cache.composite_dir(cache_root, args.aoi, season)
    missing = [str(f) for y in years for f in (cdir / f"{y}.tif", cdir / f"{y}_texture.tif") if not f.exists()]
    if missing:
        raise FileNotFoundError("Kompozit eksik; önce `changewatch composite` çalıştırın: " + ", ".join(missing))
    comp = {y: cache.read_dataset(cdir / f"{y}.tif") for y in years}
    tex = {y: cache.read_dataset(cdir / f"{y}_texture.tif")["TEXTURE"].values for y in years}
    idx = {y: spectral_indices(comp[y]) for y in years}
    first = comp[years[0]]
    region = aoi_raster_mask(geom, first, crs)
    transform = grid_transform(first["x"].values, first["y"].values)
    ddir = cache.change_dir(cache_root, args.aoi, season) / "pairs"
    prev = cache.preview_dir(cache_root, args.aoi) / "change" / "pairs"

    features: list = []
    rows: list[dict] = []
    type_codes = {"yapilasma_olasi": 1, "bitki_kaybi": 2, "su_degisimi": 3, "belirsiz": 4,
                  "su_kazanimi": 5, "su_kaybi": 6, "sulak_alan_belirsiz": 7}
    type_map = np.zeros(region.shape, "uint8")
    year_map = np.zeros(region.shape, "uint16")
    monitor_px = np.zeros(region.shape, bool)

    for a, b in zip(years, years[1:]):
        nxt = b + 1 if (b + 1) in comp else None
        c = change_candidates(comp[a], comp[b], tex[a], tex[b], settings, region)
        final = apply_mmu(open_close(c.mask, settings) & region, settings)
        layers = {
            "cva_flag": c.cva_flag, "texture_flag": c.texture_flag, "dtex_signed": c.dtexture_signed,
            "dNDVI": idx[b]["NDVI"].values - idx[a]["NDVI"].values,
            "dNDBI": idx[b]["NDBI"].values - idx[a]["NDBI"].values,
            "dBSI": idx[b]["BSI"].values - idx[a]["BSI"].values,
            "dMNDWI": idx[b]["MNDWI"].values - idx[a]["MNDWI"].values,
            "MNDWI_b": idx[b]["MNDWI"].values,
            "valid_obs_a": comp[a]["valid_obs"].values, "valid_obs_b": comp[b]["valid_obs"].values,
            "persistent": None,
        }
        if nxt:
            cva_an = cva_magnitude(comp[a], comp[nxt], list(settings["change"]["cva_bands"]), scale)
            layers["persistent"] = pixel_persistence(c.cva_flag, c.texture_flag, c.dtexture_signed, cva_an,
                                                     tex[nxt] - tex[a], c.cva_threshold, c.texture_threshold)
            layers["MNDWI_next"] = idx[nxt]["MNDWI"].values
            layers["dNDVI_next"] = idx[nxt]["NDVI"].values - idx[a]["NDVI"].values

        labels, n = label_pieces(final, conn)
        geoms = piece_geometries(labels, transform, crs, conn) if n else {}
        kept = np.zeros(region.shape, bool)
        for k in range(1, n + 1):
            sel = labels == k
            ev = piece_evidence(sel, layers, {"texture": c.texture_threshold}, settings)
            cls = classify_piece(ev, settings)
            if cls is None:
                continue
            kept |= sel
            props = {"id": f"{args.aoi}-{b}-{k:04d}", "aoi": args.aoi, "degisim_yili": b, "onceki_yil": a,
                     **cls, "alan_ha": round(ev.pop("piksel") * px_ha, 2), **ev}
            features.append((geoms[k], props))
            type_map[sel] = type_codes[cls["tur"]]
            year_map[sel] = b
            monitor_px[sel] = cls["durum"] == "izlemede"

        ha_before, ha_after = float(final.sum() * px_ha), float(kept.sum() * px_ha)
        rows.append({"cift": f"{a}->{b}", "kalicilik_kontrolu": bool(nxt), "parca": n,
                     "aday_ha": round(ha_before, 1), "kalicilik_sonrasi_ha": round(ha_after, 1),
                     "cva_esik": round(c.cva_threshold, 4), "doku_esik": round(c.texture_threshold, 4)})
        log.info("%d→%d: Otsu CVA %.3f, |Δdoku| %.4f | aday %d parça %.0f ha → %s %.0f ha", a, b,
                 c.cva_threshold, c.texture_threshold, n, ha_before,
                 "kalıcılık sonrası" if nxt else "izlemede (kontrol yok)", ha_after)

        out = xr.Dataset({
            "cva": (("y", "x"), c.cva), "dtexture": (("y", "x"), c.dtexture),
            "dtexture_signed": (("y", "x"), c.dtexture_signed),
            "cva_flag": (("y", "x"), c.cva_flag.astype("float32")),
            "texture_flag": (("y", "x"), c.texture_flag.astype("float32")),
            "candidate_raw": (("y", "x"), c.mask.astype("float32")),
            "candidate": (("y", "x"), final.astype("float32")),
            "kept": (("y", "x"), kept.astype("float32")),
        }, coords={"y": comp[a]["y"], "x": comp[a]["x"]})
        out.attrs.update(aoi=args.aoi, from_year=a, to_year=b, season=season,
                         cva_threshold=c.cva_threshold, texture_threshold=c.texture_threshold)
        cache.write_dataset(out, ddir / f"{a}_{b}_candidates.tif", crs, nodata=np.nan)
        save_overlay_png(comp[b], final, prev / f"{a}_{b}_{season}_candidates_on_{b}.png", settings)

    _write_change_outputs(args.aoi, season, years, features, rows, type_map, year_map, monitor_px,
                          comp[years[-1]], ddir, prev, settings, "ardışık çift")
    return 0


def _write_change_outputs(aoi: str, season: str, years: list[int], features: list, rows: list[dict],
                          type_map, year_map, monitor_px, background, ddir: Path, prev: Path,
                          settings: dict[str, Any], method_label: str,
                          geojson_features: list | None = None) -> None:
    """changes.geojson (geojson_features verilirse yalnızca onlar), stats.json ve tür/yıl haritaları."""
    import json

    import matplotlib

    from changewatch.quicklook import save_category_map_png
    from changewatch.vectorize import write_geojson

    gj = write_geojson(features if geojson_features is None else geojson_features, ddir / "changes.geojson")
    by_type: dict[str, dict[str, float]] = {}
    for _, p in features:
        d = by_type.setdefault(p["tur"], {})
        d[str(p["degisim_yili"])] = round(d.get(str(p["degisim_yili"]), 0.0) + p["alan_ha"], 2)
    stats = {"aoi": aoi, "season": season, "method": method_label, "years": [years[0], years[-1]],
             "rows": rows, "by_type_year_ha": by_type}
    sj = ddir / "stats.json"
    sj.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    colors = {1: "#d7191c", 2: "#fdae61", 3: "#2c7bb6", 4: "#7b3294", 5: "#2c7bb6", 6: "#8c510a",
              7: "#35978f"}
    names = {1: "yapılaşma (olası)", 2: "bitki kaybı", 3: "su değişimi (çift yöntemi)", 4: "belirsiz",
             5: "su kazanımı", 6: "su kaybı", 7: "sulak alan (belirsiz)"}
    m1 = save_category_map_png(background, type_map, colors, names, prev / f"{season}_types.png", settings,
                               f"{aoi} {years[0]}–{years[-1]} ({method_label}): türe göre "
                               f"(açık ton: izlemede, {years[-1]})", light=monitor_px)
    yrs = years[1:]
    cmap = matplotlib.colormaps["viridis"].resampled(len(yrs))
    ycolors = {y: matplotlib.colors.to_hex(cmap(i)) for i, y in enumerate(yrs)}
    m2 = save_category_map_png(background, year_map, ycolors, {y: str(y) for y in yrs},
                               prev / f"{season}_years.png", settings,
                               f"{aoi} ({method_label}): değişim yılına göre")
    for p in (gj, sj, m1, m2):
        log.info("  çıktı: %s (%s)", p, _human(p.stat().st_size))
    log.info("  toplam %d poligon", len(features))


def _water_layer(aoi: str, years: list[int], series: dict, valid_obs, region, transform,
                 settings: dict[str, Any], type_map, year_map, monitor_px):
    """Su katmanları (kalıcı + son yıl izleme): MNDWI kırılması + su kütlesi durumu + kıyı şeridi.

    Dönüş: (kalıcı özellikler, kalıcı maske, satırlar, bilgi, izleme özellikleri, izleme maskesi).
    """
    import numpy as np
    from skimage.morphology import closing, disk

    from changewatch.breakpoint import detect_breaks, mode_filter_years, segment_medians, segment_step
    from changewatch.morphology import remove_small_objects_px
    from changewatch.vectorize import label_pieces, piece_geometries
    from changewatch.water import (classify_water_piece, min_body_px, mmu_px, raw_water, segment_water_state,
                                   shoreline, shoreline_at_break, water_bodies, wetland_pixels)

    w = settings["water"]
    crs = settings["grid"]["crs"]
    conn = int(settings["morphology"]["connectivity"])
    res = float(settings["grid"]["resolution_m"])
    px_ha = res * res / 10_000
    thr = float(w["threshold"])
    codes = {"su_kazanimi": 5, "su_kaybi": 6, "sulak_alan_belirsiz": 7}
    mndwi = series["MNDWI"]
    raw, valid = raw_water(mndwi, thr)
    body = water_bodies(raw, min_body_px(settings), conn)
    shore = shoreline(body, int(w["shore_px"]))
    mmu = mmu_px(float(w["mmu_ha"]), res)
    close_r = int(settings["morphology"]["close_radius_px"])

    def layer(min_after: int, label_name: str, keep_year=None, exclude=None):
        r = detect_breaks(mndwi[:, None], years, settings, region, n_spec=1, min_after=min_after)
        before, after = segment_water_state(body, valid, r.index, float(w["majority"]))
        gain, loss = ~before & after, before & ~after
        at_shore = shoreline_at_break(shore, r.index)
        cand = r.candidate & (gain | loss) & at_shore & region
        if keep_year is not None:
            cand &= r.year == keep_year
        if exclude is not None:
            cand &= ~exclude
        nb, na = segment_medians(series["NDVI"], r.index)
        mb, ma = segment_medians(mndwi, r.index)
        wet = wetland_pixels(nb, na, mb, ma, thr, settings)
        dm = segment_step(mndwi, r.index)
        union = (closing(cand, disk(close_r)) if close_r > 0 else cand) & region
        if exclude is not None:
            union &= ~exclude
        year_s = mode_filter_years(r.year, union, int(settings["breakpoint"]["year_mode_filter_px"]))
        feats, rows, final_all = [], [], np.zeros(region.shape, bool)
        for b in years[1:]:
            final = remove_small_objects_px(union & (year_s == b), mmu, conn)
            if not final.any():
                continue
            final_all |= final
            i = years.index(b)
            labels, n = label_pieces(final, conn)
            geoms = piece_geometries(labels, transform, crs, conn)
            for k in range(1, n + 1):
                sel = labels == k
                n_after = int(np.median(r.n_after[sel]))
                cls = classify_water_piece(float(gain[sel].mean()), float(loss[sel].mean()),
                                           float(wet[sel].mean()), n_after, settings)
                med = lambda a: float(np.nanmedian(a[sel])) if np.isfinite(a[sel]).any() else None  # noqa: E731
                props = {"id": f"{aoi}-su-{b}-{k:04d}", "aoi": aoi, "yontem": "kirilma_su", "katman": label_name,
                         "degisim_yili": b, "onceki_yil": b - 1, **cls,
                         "alan_ha": round(int(sel.sum()) * px_ha, 2), "skor": med(r.score), "basamak": med(r.step),
                         "sonrasi_yil_sayisi": n_after, "dMNDWI": med(dm), "mndwi_once": med(mb),
                         "mndwi_sonra": med(ma), "ndvi_once": med(nb), "ndvi_sonra": med(na),
                         "su_kazanim_payi": round(float(gain[sel].mean()), 3),
                         "su_kayip_payi": round(float(loss[sel].mean()), 3),
                         "sulak_alan_payi": round(float(wet[sel].mean()), 3),
                         "kiyi_payi": round(float(at_shore[sel].mean()), 3), "su_esigi": thr,
                         "gecerli_gozlem_sayisi": round(float(np.nanmean(valid_obs[i][sel])), 1),
                         "dusuk_gozlem": {"ort_gozlem": round(float(np.nanmean(valid_obs[i - 1][sel])), 1),
                                          "dusuk_piksel_orani": round(float((valid_obs[i - 1][sel] < int(
                                              settings["composite"]["min_valid_obs"])).mean()), 3)}}
                feats.append((geoms[k], props))
                type_map[sel] = codes[cls["tur"]]
                year_map[sel] = b
                monitor_px[sel] = cls["durum"] == "izlemede"
            rows.append({"katman": f"su_{label_name}", "kirilma_yili": b, "parca": n,
                         "ha": round(float(final.sum() * px_ha), 1)})
        log.info("  su %s katmanı (min_after=%d): kırılma adayı %.0f ha → durum değişimi + kıyı %.0f ha → "
                 "MMU %.1f ha, %d poligon", label_name, min_after, r.candidate.sum() * px_ha, cand.sum() * px_ha,
                 final_all.sum() * px_ha, len(feats))
        return feats, final_all, rows

    feats, kept, rows = layer(int(w["min_after"]), "kalici")
    m_feats, m_mask, m_rows = layer(int(w["monitor_min_after"]), "izleme", keep_year=years[-1], exclude=kept)
    info = {"katman": "su", "esik": thr, "min_kutle_ha": float(w["min_body_ha"]), "kiyi_px": int(w["shore_px"]),
            "mmu_ha": float(w["mmu_ha"]), "su_kutlesi_ha_ilk_son": [round(float((body[0] & region).sum() * px_ha), 1),
                                                                    round(float((body[-1] & region).sum() * px_ha), 1)]}
    return feats, kept, rows + m_rows, info, m_feats, m_mask


def _detect_breakpoint(args: argparse.Namespace) -> int:
    """Kırılma noktası: kalıcı katman (min_after) + son yıl izleme katmanı → tür/güven → GeoJSON."""
    import numpy as np
    import xarray as xr

    from changewatch import cache
    from changewatch.breakpoint import detect_breaks, mode_filter_years, segment_medians, segment_step, series_noise
    from changewatch.classify import break_piece_evidence, classify_break_piece
    from changewatch.indices import spectral_indices
    from changewatch.mask import aoi_raster_mask
    from changewatch.morphology import apply_mmu, open_close
    from changewatch.quicklook import save_boundary_panel_png
    from changewatch.vectorize import grid_transform, label_pieces, piece_geometries, write_geojson

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    scale = float(settings["stac"]["reflectance_scale"])
    conn = int(settings["morphology"]["connectivity"])
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    bp = settings["breakpoint"]
    years = parse_years(args.years, settings)
    if any(b - a != 1 for a, b in zip(years, years[1:])):
        raise ConfigError(f"Yıllar ardışık olmalı: {years}")

    cdir = cache.composite_dir(cache_root, args.aoi, season)
    missing = [str(f) for y in years for f in (cdir / f"{y}.tif", cdir / f"{y}_texture.tif") if not f.exists()]
    if missing:
        raise FileNotFoundError("Kompozit eksik; önce `changewatch composite` çalıştırın: " + ", ".join(missing))
    comp = {y: cache.read_dataset(cdir / f"{y}.tif") for y in years}
    idx = {y: spectral_indices(comp[y]) for y in years}
    series = {
        "TEXTURE": np.stack([cache.read_dataset(cdir / f"{y}_texture.tif")["TEXTURE"].values for y in years]),
        **{k: np.stack([idx[y][k].values for y in years]) for k in ("NDVI", "NDBI", "BSI", "MNDWI")},
    }
    n_spec = len(bp["bands"])
    var_names = list(bp["bands"]) + (["TEXTURE"] if bp["include_texture"] else [])
    stack = np.stack([np.stack([comp[y][b].values / scale for b in bp["bands"]]
                               + ([series["TEXTURE"][i]] if bp["include_texture"] else []))
                      for i, y in enumerate(years)])
    valid_obs = np.stack([comp[y]["valid_obs"].values for y in years]).astype("float32")
    first = comp[years[0]]
    region = aoi_raster_mask(geom, first, crs)
    transform = grid_transform(first["x"].values, first["y"].values)
    ddir = cache.change_dir(cache_root, args.aoi, season) / "breakpoint"
    prev = cache.preview_dir(cache_root, args.aoi) / "change" / "breakpoint"
    type_codes = {"yapilasma_olasi": 1, "bitki_kaybi": 2, "su_degisimi": 3, "belirsiz": 4,
                  "su_kazanimi": 5, "su_kaybi": 6, "sulak_alan_belirsiz": 7}
    type_map = np.zeros(region.shape, "uint8")
    year_map = np.zeros(region.shape, "uint16")
    monitor_px = np.zeros(region.shape, bool)

    def run_layer(min_after: int, label: str, keep_year=None, exclude=None):
        """Bir katman: kırılma → morfoloji → yıl bazında MMU → parça kanıtı/tür. (özellikler, maske, bilgi)"""
        r = detect_breaks(stack, years, settings, region, n_spec=n_spec, min_after=min_after)
        steps = {k: segment_step(v, r.index) for k, v in series.items()}
        mb, ma = segment_medians(series["MNDWI"], r.index)
        sig_tex = series_noise(series["TEXTURE"], r.index, region)
        sig_ndvi = series_noise(series["NDVI"], r.index, region)
        th = {"texture": float(bp["texture_k"]) * sig_tex, "ndvi": -float(bp["ndvi_k"]) * sig_ndvi}
        cand = r.candidate.copy()
        if keep_year is not None:
            cand &= r.year == keep_year
        if exclude is not None:
            cand &= ~exclude
        union = open_close(cand, settings) & region
        if exclude is not None:
            union &= ~exclude
        year_s = mode_filter_years(r.year, union, int(bp["year_mode_filter_px"]))
        layers = {
            "score": r.score, "step": r.step, "n_after": r.n_after.astype("float32"), "signal": r.signal,
            "spectral_sig": r.spectral_sig, "texture_sig": r.texture_sig,
            "tex_step": steps["TEXTURE"], "ndvi_step": steps["NDVI"], "ndbi_step": steps["NDBI"],
            "bsi_step": steps["BSI"], "mndwi_step": steps["MNDWI"], "mndwi_before": mb, "mndwi_after": ma,
            "year_agree": (r.year == year_s).astype("float32"),
        }
        feats, final_all, rows = [], np.zeros(region.shape, bool), []
        for b in years[1:]:
            final = apply_mmu(union & (year_s == b), settings)
            if not final.any():
                continue
            final_all |= final
            i = years.index(b)
            layers["valid_obs_a"], layers["valid_obs_b"] = valid_obs[i - 1], valid_obs[i]
            labels, n = label_pieces(final, conn)
            geoms = piece_geometries(labels, transform, crs, conn)
            for k in range(1, n + 1):
                sel = labels == k
                ev = break_piece_evidence(sel, layers, th, settings)
                cls = classify_break_piece(ev, th, settings)
                props = {"id": f"{args.aoi}-bp-{b}-{k:04d}", "aoi": args.aoi, "yontem": "kirilma",
                         "katman": label, "degisim_yili": b, "onceki_yil": b - 1, **cls,
                         "alan_ha": round(ev.pop("piksel") * px_ha, 2), **ev}
                feats.append((geoms[k], props))
                type_map[sel] = type_codes[cls["tur"]]
                year_map[sel] = b
                monitor_px[sel] = cls["durum"] == "izlemede"
            rows.append({"katman": label, "kirilma_yili": b, "parca": n, "ha": round(float(final.sum() * px_ha), 1)})
        log.info("  %s katmanı (min_after=%d): σ %s | gürültü_z %.3f, basamak_z eşiği %.3f | doku > %.4f, "
                 "NDVI < %.3f | aday %.0f ha → morfoloji %.0f ha → yıl bazında MMU %.0f ha", label, min_after,
                 ", ".join(f"{nm}={s:.4f}" for nm, s in zip(var_names, r.sigma)), r.noise, r.step_threshold,
                 th["texture"], th["ndvi"], cand.sum() * px_ha, union.sum() * px_ha, final_all.sum() * px_ha)
        info = {"katman": label, "min_after": min_after,
                "sigma": {nm: round(float(s), 5) for nm, s in zip(var_names, r.sigma)},
                "esikler": {"gurultu_z": round(r.noise, 4), "basamak_z": round(r.step_threshold, 4),
                            "skor_k": float(bp["score_k"]), "doku": round(th["texture"], 5),
                            "ndvi": round(th["ndvi"], 4)}}
        return feats, final_all, rows, info, r, year_s, steps

    log.info("%s kırılma %d–%d", args.aoi, years[0], years[-1])
    w_feats, w_mask, w_rows, w_info, wm_feats, wm_mask = _water_layer(
        args.aoi, years, series, valid_obs, region, transform, settings, type_map, year_map, monitor_px)
    feats, kept, rows, info, r, year_s, steps = run_layer(int(bp["min_after"]), "kalici", exclude=w_mask)
    m_feats, m_mask, m_rows, m_info, *_ = run_layer(int(bp["monitor_min_after"]), "izleme",
                                                    keep_year=years[-1], exclude=kept | w_mask | wm_mask)
    m_feats = wm_feats + m_feats
    feats = w_feats + feats
    rows = w_rows + rows

    out = xr.Dataset({
        "year": (("y", "x"), r.year.astype("float32")), "year_smoothed": (("y", "x"), year_s.astype("float32")),
        "score": (("y", "x"), r.score), "step": (("y", "x"), r.step), "spread": (("y", "x"), r.spread),
        "n_after": (("y", "x"), r.n_after.astype("float32")), "signal": (("y", "x"), r.signal.astype("float32")),
        "tex_step": (("y", "x"), steps["TEXTURE"]), "ndvi_step": (("y", "x"), steps["NDVI"]),
        "candidate_raw": (("y", "x"), r.candidate.astype("float32")),
        "candidate": (("y", "x"), kept.astype("float32")),
        "monitor": (("y", "x"), m_mask.astype("float32")),
        "water_change": (("y", "x"), w_mask.astype("float32")),
    }, coords={"y": first["y"], "x": first["x"]})
    out.attrs.update(aoi=args.aoi, years=f"{years[0]}-{years[-1]}", noise_z=r.noise,
                     step_threshold=r.step_threshold)
    cache.write_dataset(out, ddir / "breaks.tif", crs, nodata=np.nan)
    mj = write_geojson(m_feats, ddir / "izleme.geojson")
    log.info("  çıktı: %s (%s, %d poligon)", mj, _human(mj.stat().st_size), len(m_feats))
    _write_change_outputs(args.aoi, season, years, feats + m_feats, rows + m_rows + [w_info, info, m_info],
                          type_map, year_map, monitor_px, comp[years[-1]], ddir, prev, settings, "kırılma",
                          geojson_features=feats)
    a_y, b_y = (args.panel_years or [years[0], 2024 if 2024 in comp else years[-1]])
    built = (type_map == 1) & ~monitor_px
    pnl = save_boundary_panel_png(comp[a_y], comp[b_y], built, prev / f"{season}_built_{a_y}_{b_y}.png",
                                  settings, (str(a_y), str(b_y)),
                                  f"{args.aoi}: yapılaşma (olası) sınırları, kalıcı katman "
                                  f"{years[1]}–{years[-2]} ({built.sum() * px_ha:.0f} ha)")
    log.info("  çıktı: %s (%s)", pnl, _human(pnl.stat().st_size))
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    """Değişim tespiti: --method breakpoint (varsayılan, settings.change_method) veya pairs."""
    method = args.method or load_settings(args.config).get("change_method", "breakpoint")
    if method == "pairs":
        return _detect_pairs(args)
    if method == "breakpoint":
        return _detect_breakpoint(args)
    raise ConfigError(f"Bilinmeyen yöntem: {method} (breakpoint | pairs)")


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Yöntem karşılaştırması: (c) tür × yıl, (d) yöntemler arası, (e) doğrudan A→B ile tutarlılık."""
    import json

    from changewatch import cache
    from changewatch.evaluate import (consistency, direct_built_mask, load_features, markdown_type_year,
                                      method_summary, type_year_table)
    from changewatch.mask import aoi_raster_mask
    from changewatch.vectorize import grid_transform

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    years = parse_years(args.years, settings)
    cdir = cache.change_dir(cache_root, args.aoi, season)
    methods = [m for m in args.methods if (cdir / m / "changes.geojson").exists()]
    if not methods:
        raise FileNotFoundError(f"Değişim çıktısı yok ({cdir}); önce `changewatch detect` çalıştırın.")
    feats = {m: load_features(cdir / m / "changes.geojson", crs) for m in methods}

    regions = {}
    if args.region:
        from changewatch.aoi import load_aois

        gdf = load_aois(args.region).to_crs(crs)
        for i, row in gdf.iterrows():
            regions[str(row["name"]) if "name" in gdf.columns and row["name"] else f"bolge_{i}"] = row.geometry

    report: dict[str, Any] = {"aoi": args.aoi, "season": season, "years": [years[0], years[-1]], "methods": {}}
    for m in methods:
        tab = type_year_table(feats[m], years[1:])
        print(f"\n## (c) {m}: tür × yıl (ha)\n")
        print(markdown_type_year(tab, years[1:]))
        report["methods"][m] = {"tur_yil_ha": {t: {str(y): round(v, 1) for y, v in d.items()} for t, d in tab.items()},
                                "ozet": method_summary(feats[m], regions)}

    print("\n## (d) yöntemler arası özet (ha)\n")
    head = "| yöntem | yapılaşma | tüm türler | ayak izi |" + "".join(
        f" {n}: ayak izi / yapılaşma |" for n in regions)
    print(head)
    print("|---" * (4 + len(regions)) + "|")
    for m in methods:
        s = report["methods"][m]["ozet"]
        print(f"| {m} | {s['yapilasma_ha']:.0f} | {s['tum_turler_ha']:.0f} | {s['ayak_izi_ha']:.0f} |" + "".join(
            f" {b['ayak_izi_ha']:.0f} / {b['yapilasma_ha']:.0f} (bölge {b['bolge_ha']:.0f}) |"
            for b in s["bolgeler"].values()))

    a, b = args.direct_years or (years[0], years[-2])
    comp_dir = cache.composite_dir(cache_root, args.aoi, season)
    comp_a, comp_b = cache.read_dataset(comp_dir / f"{a}.tif"), cache.read_dataset(comp_dir / f"{b}.tif")
    tex_a = cache.read_dataset(comp_dir / f"{a}_texture.tif")["TEXTURE"].values
    tex_b = cache.read_dataset(comp_dir / f"{b}_texture.tif")["TEXTURE"].values
    region = aoi_raster_mask(geom, comp_a, crs)
    direct, th = direct_built_mask(comp_a, comp_b, tex_a, tex_b, settings, region)
    transform = grid_transform(comp_a["x"].values, comp_a["y"].values)
    print(f"\n## (e) tutarlılık: {a + 1}–{b} yapılaşması ↔ doğrudan {a}→{b} doku artışlı aday "
          f"(Otsu CVA {th['cva_esik']:.3f}, doku {th['doku_esik']:.4f})\n")
    print("| yöntem | yöntem yapılaşma (ha) | doğrudan (ha) | yöntemin doğrudan içindeki payı | doğrudanın kapsanan payı |")
    print("|---|---|---|---|---|")
    report["tutarlilik"] = {"yillar": [a, b], "esikler": th}
    pct = lambda v: "-" if v is None else f"%{100 * v:.0f}"  # noqa: E731
    for m in methods:
        c = consistency(direct, feats[m], a, b, transform, px_ha)
        report["tutarlilik"][m] = c
        print(f"| {m} | {c['yontem_yapilasma_ha']:.0f} | {c['dogrudan_ha']:.0f} | "
              f"{pct(c['yontemin_dogrudan_icindeki_payi'])} | {pct(c['dogrudanin_kapsanan_payi'])} |")

    out = cdir / "evaluate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("çıktı: %s", out)
    return 0


def cmd_water(args: argparse.Namespace) -> int:
    """Yıllık su maskesi (MNDWI > sabit eşik, ≥ min alan su kütleleri), su alanı serisi (CSV/JSON + grafik)."""
    import csv
    import json

    import numpy as np
    import xarray as xr

    from changewatch import cache
    from changewatch.indices import spectral_indices
    from changewatch.mask import aoi_raster_mask
    from changewatch.quicklook import save_mask_pair_png, save_series_png
    from changewatch.water import min_body_px, otsu_diagnostic, raw_water, water_area_series, water_bodies

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    w = settings["water"]
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    years = parse_years(args.years, settings)
    cdir = cache.composite_dir(cache_root, args.aoi, season)
    comp = {y: cache.read_dataset(cdir / f"{y}.tif") for y in years}
    mndwi = np.stack([spectral_indices(comp[y])["MNDWI"].values for y in years])
    region = aoi_raster_mask(geom, comp[years[0]], crs)
    raw, valid = raw_water(mndwi, float(w["threshold"]))
    body = water_bodies(raw, min_body_px(settings), int(settings["morphology"]["connectivity"]))
    s_new = water_area_series(body, valid, region, px_ha)
    s_old = water_area_series(raw, valid, region, px_ha)
    otsu = otsu_diagnostic(mndwi, region, int(w["otsu_bins"]))
    rows = [{"yil": y, "su_ha": n["su_ha"], "su_ha_eski_tum_pikseller": o["su_ha"],
             "elenen_kucuk_parca_ha": round(o["su_ha"] - n["su_ha"], 1), "gecersiz_orani": n["gecersiz_orani"],
             "otsu_tani": None if ot is None else round(ot, 4)}
            for y, n, o, ot in zip(years, s_new, s_old, otsu)]
    log.info("%s su: MNDWI > %.2f ve su kütlesi ≥ %.1f ha", args.aoi, float(w["threshold"]), float(w["min_body_ha"]))
    for r in rows:
        log.info("  %d: su %.1f ha (eski %.1f; elenen küçük parça %.1f) | Otsu (tanı) %s", r["yil"], r["su_ha"],
                 r["su_ha_eski_tum_pikseller"], r["elenen_kucuk_parca_ha"], r["otsu_tani"])

    wdir = cache.water_dir(cache_root, args.aoi, season)
    wdir.mkdir(parents=True, exist_ok=True)
    with (wdir / "water_series.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    (wdir / "water_series.json").write_text(json.dumps({"aoi": args.aoi, "season": season, "esik": w["threshold"],
                                                        "min_kutle_ha": w["min_body_ha"], "yillar": rows},
                                                       ensure_ascii=False, indent=2), encoding="utf-8")
    ds = xr.Dataset({str(y): (("y", "x"), np.where(valid[i], body[i], np.nan).astype("float32"))
                     for i, y in enumerate(years)}, coords={"y": comp[years[0]]["y"], "x": comp[years[0]]["x"]})
    cache.write_dataset(ds, wdir / "water_masks.tif", crs, nodata=np.nan)
    prev = cache.preview_dir(cache_root, args.aoi) / "water"
    g = save_series_png(years, [{"label": f"su kütleleri ≥ {float(w['min_body_ha']):g} ha",
                                 "values": [r["su_ha"] for r in rows]},
                                {"label": "eski: MNDWI > 0, tüm pikseller (çatı/sera dahil)",
                                 "values": [r["su_ha_eski_tum_pikseller"] for r in rows], "style": "dashed"}],
                        prev / f"{season}_water_area.png", settings,
                        f"{args.aoi}: yaz kompozitinde su alanı (ha), {years[0]}–{years[-1]}", "su alanı (ha)",
                        f"Su = MNDWI > {float(w['threshold']):g}; yaz penceresi medyan kompoziti; AOI içi.")
    a, b = args.mask_years or (years[0], years[-2])
    ia, ib = years.index(a), years.index(b)
    mp = save_mask_pair_png(comp[a], comp[b], body[ia] & region, body[ib] & region,
                            prev / f"{season}_water_masks_{a}_{b}.png", settings, (str(a), str(b)),
                            f"{args.aoi}: su maskesi (MNDWI > {float(w['threshold']):g}, kütle ≥ "
                            f"{float(w['min_body_ha']):g} ha)")
    for pth in (wdir / "water_series.csv", wdir / "water_masks.tif", g, mp):
        log.info("  çıktı: %s (%s)", pth, _human(pth.stat().st_size))
    return 0


def _aoi_layers(settings: dict[str, Any], cache_root: Path, aoi: str, season: str):
    """Bir AOI'nin kırılma çıktıları: ızgara (breaks.tif), kalıcı ve izleme özellikleri (proje CRS'i)."""
    from changewatch import cache
    from changewatch.evaluate import load_features

    ddir = cache.change_dir(cache_root, aoi, season) / settings["validation"]["method"]
    if not (ddir / "changes.geojson").exists():
        raise FileNotFoundError(f"{ddir / 'changes.geojson'} yok; önce `changewatch detect --aoi {aoi}` çalıştırın.")
    crs = settings["grid"]["crs"]
    grid = cache.read_dataset(ddir / "breaks.tif")
    kept = load_features(ddir / "changes.geojson", crs)
    mon = load_features(ddir / "izleme.geojson", crs) if (ddir / "izleme.geojson").exists() else []
    return grid, kept, mon


def cmd_sample(args: argparse.Namespace) -> int:
    """Tabakalı rastgele örnekleme → validation/points.geojson + labels.csv şablonu + çipler + QGIS yükleyicisi."""
    import json

    import numpy as np
    from pyproj import Transformer
    from rasterio.features import rasterize

    from changewatch import cache
    from changewatch.mask import aoi_raster_mask
    from changewatch.quicklook import save_chip_png
    from changewatch.validate import NO_CHANGE, allocate, sample_pixels, summary_counts, write_label_template
    from changewatch.vectorize import grid_transform

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    v = settings["validation"]
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    aois = args.aois or list(v["aois"])
    years = parse_years(None, settings)
    smaps, feats_ix, grids = {}, {}, {}
    px = Counter()
    for aoi in aois:
        grid, kept, mon = _aoi_layers(settings, cache_root, aoi, season)
        shape = (grid["y"].size, grid["x"].size)
        tr = grid_transform(grid["x"].values, grid["y"].values)
        region = aoi_raster_mask(get_aoi(settings, aoi), grid, crs)
        idx = (rasterize([(g, i + 1) for i, (g, _) in enumerate(kept)], out_shape=shape, transform=tr,
                         dtype="int32") if kept else np.zeros(shape, "int32"))
        mon_m = (rasterize([(g, 1) for g, _ in mon], out_shape=shape, transform=tr).astype(bool)
                 if mon else np.zeros(shape, bool))
        smap = np.full(shape, "", dtype=object)
        for i, (_, p) in enumerate(kept):
            smap[idx == i + 1] = p["tur"]
        smap[region & (idx == 0) & ~mon_m] = NO_CHANGE
        smap[~region] = ""
        smaps[aoi], feats_ix[aoi], grids[aoi] = smap, (idx, kept), grid
        for s, n in zip(*np.unique(smap[smap != ""], return_counts=True)):
            px[str(s)] += int(n)
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    alloc = allocate(dict(px), int(v["total_points"]), int(v["no_change_points"]), int(v["min_per_stratum"]),
                     min_px_for_min=int(round(float(v["min_stratum_area_ha"]) / px_ha)))
    log.info("tabaka piksel sayıları: %s", dict(px))
    log.info("nokta dağıtımı: %s (toplam %d)", alloc, sum(alloc.values()))
    pts = sample_pixels(smaps, alloc, int(v["seed"]), float(v["calibration_share"]),
                        polygon_maps={a: feats_ix[a][0] for a in aois},
                        max_per_polygon=int(v["max_points_per_polygon"]),
                        min_dist_px=float(v["min_point_distance_m"]) / float(settings["grid"]["resolution_m"]))
    for s in alloc:
        got = sum(p["tabaka"] == s for p in pts)
        if got < alloc[s]:
            log.warning("tabaka %s: %d nokta istendi, kısıtlar (poligon başına ≤ %s, aralık ≥ %s m) yüzünden %d",
                        s, alloc[s], v["max_points_per_polygon"], v["min_point_distance_m"], got)

    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    features = []
    for p in pts:
        g = grids[p["aoi"]]
        x, y = float(g["x"].values[p["col"]]), float(g["y"].values[p["row"]])
        idx, kept = feats_ix[p["aoi"]]
        k = int(idx[p["row"], p["col"]])
        pr = kept[k - 1][1] if k else None
        yil = int(pr["degisim_yili"]) if pr else None
        once, sonra = (yil - 1, yil) if yil else (years[0], years[-2])
        lon, lat = to_wgs(x, y)
        props = {"nokta_id": p["nokta_id"], "aoi": p["aoi"], "tabaka": p["tabaka"], "rol": p["rol"],
                 "tahmin_tur": pr["tur"] if pr else NO_CHANGE, "tahmin_yil": yil,
                 "tahmin_guven": pr["guven"] if pr else None, "kaynak_id": pr["id"] if pr else None,
                 "once_yil": once, "sonra_yil": sonra, "x": round(x, 2), "y": round(y, 2), "row": p["row"],
                 "col": p["col"], "tabaka_alan_ha": round(px[p["tabaka"]] * px_ha, 1),
                 "yontem": v["method"], "mevsim": season}
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    out = resolve_path(settings, settings["paths"]["validation_points"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    lab = write_label_template([f["properties"] for f in features],
                               resolve_path(settings, settings["paths"]["validation_labels"]), force=args.force)
    log.info("çıktı: %s (%d nokta), %s", out, len(features), lab)

    chip_dir = cache_root / "validation" / "chips"
    if chip_dir.exists():  # eski örneklemenin çipleri karışmasın
        import shutil

        shutil.rmtree(chip_dir)
    comps: dict[tuple[str, int], Any] = {}
    for f in features:
        p = f["properties"]
        for yy in (p["once_yil"], p["sonra_yil"]):
            if (p["aoi"], yy) not in comps:
                comps[(p["aoi"], yy)] = cache.read_dataset(cache.composite_dir(cache_root, p["aoi"], season)
                                                           / f"{yy}.tif")
        title = (f"{p['nokta_id']} · {p['aoi']} · tahmin: {p['tahmin_tur']}"
                 + (f" ({p['tahmin_yil']})" if p["tahmin_yil"] else "") + f" · {p['rol']}")
        save_chip_png(comps[(p["aoi"], p["once_yil"])], comps[(p["aoi"], p["sonra_yil"])], p["row"], p["col"],
                      chip_dir / f"{p['nokta_id']}.png", settings, (str(p["once_yil"]), str(p["sonra_yil"])), title)
    log.info("çipler: %s (%d)", chip_dir, len(features))
    loader = _write_qgis_loader(settings, cache_root, aois, season, out, years)
    log.info("QGIS: %s", loader)

    print("\n| tabaka | toplam | " + " | ".join(aois) + " | kalibrasyon | test | tabaka alanı (ha) |")
    print("|---|---|" + "---|" * len(aois) + "---|---|---|")
    for s, c in sorted(summary_counts([f["properties"] for f in features]).items(),
                       key=lambda kv: (kv[0] == NO_CHANGE, kv[0])):
        print(f"| {s} | {c['toplam']} | " + " | ".join(str(c.get(a, 0)) for a in aois)
              + f" | {c.get('kalibrasyon', 0)} | {c.get('test', 0)} | {px[s] * px_ha:.0f} |")
    return 0


def _write_qgis_loader(settings: dict[str, Any], cache_root: Path, aois: list[str], season: str, points: Path,
                       years: list[int]) -> Path:
    """QGIS Python konsolunda çalıştırılacak katman yükleyici + düz katman listesi (cache_dir/validation)."""
    from changewatch import cache

    method = settings["validation"]["method"]
    layers: list[tuple[str, str, str]] = [("vector", "doğrulama noktaları", str(points))]
    for aoi in aois:
        ddir = cache.change_dir(cache_root, aoi, season) / method
        layers += [("vector", f"{aoi} değişim (kalıcı)", str(ddir / "changes.geojson")),
                   ("vector", f"{aoi} izleme", str(ddir / "izleme.geojson"))]
        wm = cache.water_dir(cache_root, aoi, season) / "water_masks.tif"
        if wm.exists():
            layers.append(("raster", f"{aoi} su maskeleri", str(wm)))
        for y in reversed(years):
            layers.append(("raster", f"{aoi} {y} kompozit", str(cache.composite_dir(cache_root, aoi, season)
                                                                  / f"{y}.tif")))
    vdir = cache_root / "validation"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "qgis_katmanlar.txt").write_text("\n".join(f"{k}\t{n}\t{p}" for k, n, p in layers), encoding="utf-8")
    rgb = [settings["stac"]["bands"].index(b) + 1 for b in settings["quicklook"]["rgb_bands"]]
    hi = float(settings["quicklook"]["rgb_max"]) * float(settings["stac"]["reflectance_scale"])
    script = f'''# QGIS > Eklentiler > Python Konsolu > Düzenleyici: bu dosyayı açıp çalıştırın.
# Üreten: changewatch sample. Kompozitler doğal renk (bant {rgb}, 0–{hi:.0f}) olarak gösterilir.
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMultiBandColorRenderer, QgsContrastEnhancement

LAYERS = {layers!r}
root = QgsProject.instance().layerTreeRoot()
grp = root.addGroup("TR-ChangeWatch doğrulama")
for kind, name, path in LAYERS:
    lyr = QgsVectorLayer(path, name, "ogr") if kind == "vector" else QgsRasterLayer(path, name)
    if not lyr.isValid():
        print("açılamadı:", path)
        continue
    if kind == "raster" and "kompozit" in name:
        r = QgsMultiBandColorRenderer(lyr.dataProvider(), {rgb[0]}, {rgb[1]}, {rgb[2]})
        for setter in (r.setRedContrastEnhancement, r.setGreenContrastEnhancement, r.setBlueContrastEnhancement):
            ce = QgsContrastEnhancement(lyr.dataProvider().dataType(1))
            ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
            ce.setMinimumValue(0)
            ce.setMaximumValue({hi:.0f})
            setter(ce)
        lyr.setRenderer(r)
    QgsProject.instance().addMapLayer(lyr, False)
    node = grp.addLayer(lyr)
    if kind == "raster" and "kompozit" in name:
        node.setItemVisibilityChecked(False)
print("yüklendi:", len(LAYERS), "katman")
'''
    loader = vdir / "qgis_load_layers.py"
    loader.write_text(script, encoding="utf-8")
    return loader


def _labeled_records(settings: dict[str, Any], role: str, use_current: bool, cache_root: Path | None,
                     season: str) -> tuple[list[dict], int, int]:
    """Etiketli noktaları (ref, pred, yıllar) kayıtlarına çevirir. (kayıtlar, toplam nokta, dolu etiket)."""
    from changewatch.evaluate import load_features
    from changewatch.validate import filled_labels, load_points, lookup_predictions, read_labels, reference_class

    pts = load_points(resolve_path(settings, settings["paths"]["validation_points"]))
    rows = {r["nokta_id"]: r for r in filled_labels(read_labels(resolve_path(settings,
                                                                             settings["paths"]["validation_labels"])))}
    sel = [p for p in pts if p["nokta_id"] in rows and (role == "hepsi" or p["rol"] == role)]
    if use_current and sel:
        from changewatch import cache

        feats = {}
        for aoi in {p["aoi"] for p in sel}:
            pth = cache.change_dir(cache_root, aoi, season) / settings["validation"]["method"] / "changes.geojson"
            feats[aoi] = load_features(pth, settings["grid"]["crs"])
        preds = lookup_predictions(sel, feats)
    else:
        preds = [(p["tahmin_tur"], p["tahmin_yil"]) for p in sel]
    recs = [{"ref": reference_class(rows[p["nokta_id"]]), "pred": pr, "pred_year": py,
             "ref_year": rows[p["nokta_id"]].get("gercek_yil") or None, "aoi": p["aoi"],
             "stratum": p["tabaka"], "stratum_area_ha": p["tabaka_alan_ha"]}
            for p, (pr, py) in zip(sel, preds)]
    return recs, len(pts), len(rows)


def cmd_validate(args: argparse.Namespace) -> int:
    """Etiketlerden karışıklık matrisi, tür bazlı metrikler ve yıl bazlı doğruluk."""
    import json

    from changewatch.validate import format_olofsson, format_report, metrics, olofsson

    settings = load_settings(args.config)
    setup_logging(settings)
    season = args.season or settings["composite"]["season"]
    cache_root = require_cache_dir(settings) if args.map == "current" else None
    recs, n_pts, n_lab = _labeled_records(settings, args.set, args.map == "current", cache_root, season)
    if not n_lab:
        print(f"UYARI: etiket girilmemiş (0/{n_pts} nokta). "
              f"{settings['paths']['validation_labels']} dosyasında gercek_degisim (evet/hayir), gercek_tur, "
              "gercek_yil sütunlarını doldurun; çipler <cache_dir>/validation/chips/ altında.")
        return 0
    if not recs:
        print(f"UYARI: {n_lab} etiket var ama '{args.set}' kümesinde etiketli nokta yok.")
        return 0
    rep = metrics(recs)
    rep["olofsson"] = olofsson(recs, {r["stratum"]: float(r["stratum_area_ha"]) for r in recs})
    rep.update(kume=args.set, harita=args.map, etiketli=n_lab, toplam_nokta=n_pts)
    print(f"## Doğrulama ({args.set} noktaları, harita: {args.map})\n")
    print("### Nokta bazlı\n")
    print(format_report(rep))
    print("\n### Alan ağırlıklı (Olofsson vd. 2014; tabaka = örnekleme anındaki harita sınıfı)\n")
    print(format_olofsson(rep["olofsson"]))
    out = resolve_path(settings, "validation") / f"metrics_{args.set}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log.info("çıktı: %s", out)
    return 0


def cmd_experiments(args: argparse.Namespace) -> int:
    """E1–E5: etiket varsa hazır varyantları test noktalarında değerlendirir; yoksa/--dry-run ise durum tablosu."""
    from changewatch.evaluate import load_features
    from changewatch.experiments import EXPERIMENTS, status
    from changewatch.validate import (filled_labels, load_points, lookup_predictions, metrics, read_labels,
                                      reference_class)

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    aois = args.aois or list(settings["validation"]["aois"])
    labels = filled_labels(read_labels(resolve_path(settings, settings["paths"]["validation_labels"])))
    dry = args.dry_run or not labels
    if dry:
        print("Kuru çalıştırma" + ("" if args.dry_run else " (etiket yok)") +
              f": AOI'ler {', '.join(aois)}. Etiketler gelince her 'hazır' varyantın haritası TEST noktalarında "
              "değerlendirilir (genel doğruluk, yanlış alarm, yapılaşma F1, yıl isabeti).\n")
    print("| deney | varyant | durum | üretim |")
    print("|---|---|---|---|")
    for code, (desc, variants) in EXPERIMENTS.items():
        for v in variants:
            st = status(v, cache_root, aois)
            prod = v.produce.format(aoi="<aoi>") if st != "hazır" else "-"
            print(f"| {code} | {v.name} | {st} | {prod} |")
    if dry:
        return 0

    pts = load_points(resolve_path(settings, settings["paths"]["validation_points"]))
    rows = {r["nokta_id"]: r for r in labels}
    test = [p for p in pts if p["rol"] == "test" and p["nokta_id"] in rows and p["aoi"] in aois]
    pct = lambda x: "-" if x is None else f"%{100 * x:.0f}"  # noqa: E731
    print(f"\n## Test noktalarında sonuçlar (n = {len(test)})\n")
    print("| deney | varyant | genel doğruluk | yanlış alarm | yapılaşma F1 | yıl tam isabet |")
    print("|---|---|---|---|---|---|")
    for code, (desc, variants) in EXPERIMENTS.items():
        for v in variants:
            if status(v, cache_root, aois) != "hazır":
                continue
            feats = {a: load_features(v.path(cache_root, a), settings["grid"]["crs"]) for a in aois}
            preds = lookup_predictions(test, feats)
            recs = [{"ref": reference_class(rows[p["nokta_id"]]), "pred": pr, "pred_year": py,
                     "ref_year": rows[p["nokta_id"]].get("gercek_yil") or None} for p, (pr, py) in zip(test, preds)]
            m = metrics(recs)
            f1 = m["sinif_metrikleri"].get("yapilasma_olasi", {}).get("f1")
            print(f"| {code} | {v.name} | {pct(m['genel_dogruluk'])} | {pct(m['yanlis_alarm_orani'])} | "
                  f"{pct(f1)} | {pct(m['yil']['tam_isabet'])} |")
    return 0


# ---------------------------------------------------------------- ayrıştırıcı

def build_parser() -> argparse.ArgumentParser:
    """Argüman ayrıştırıcısını kurar."""
    p = argparse.ArgumentParser(
        prog="changewatch",
        description="TR-ChangeWatch: Ankara için Sentinel-2 değişim izleme.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="settings.yaml yolu (varsayılan: config/settings.yaml)")
    sub = p.add_subparsers(dest="command", metavar="<komut>")

    c = sub.add_parser("check-aois", help="AOI adlarını, alanlarını ve sınırlarını kontrol et")
    c.add_argument("--aois", help="AOI GeoJSON yolu (varsayılan: settings.yaml'daki paths.aois)")
    c.set_defaults(func=cmd_check_aois)

    def aoi_years(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--aoi", required=True, help="AOI adı (aois.geojson'daki name)")
        sp.add_argument("--years", nargs="+", metavar="YIL",
                        help="ör. 2017 2024 veya 2017-2026 (varsayılan: settings.yaml'daki aralık)")
        sp.add_argument("--season", help="settings.yaml'daki pencere adı (varsayılan: composite.season)")

    s = sub.add_parser("scenes", help="Yıllara göre sahne/bulut/baseline özeti (indirme yok)")
    aoi_years(s)
    s.set_defaults(func=cmd_scenes)

    f = sub.add_parser("fetch", help="AOI penceresini cache_dir'e indir (pencereli okuma)")
    aoi_years(f)
    f.set_defaults(func=cmd_fetch)

    k = sub.add_parser("composite", help="Harmonizasyon + SCL maskesi + medyan kompozit ve önizleme PNG'leri")
    aoi_years(k)
    k.set_defaults(func=cmd_composite)

    i = sub.add_parser("indices", help="NDVI, NDBI, MNDWI, BSI ve doku (GeoTIFF + PNG)")
    aoi_years(i)
    i.set_defaults(func=cmd_indices)

    d = sub.add_parser("detect", help="Ardışık yıllarda değişim: aday, kalıcılık, tür/güven, GeoJSON")
    aoi_years(d)
    d.add_argument("--method", choices=["breakpoint", "pairs"],
                   help="breakpoint: piksel serisinde kırılma; pairs: ardışık yıl çiftleri "
                        "(varsayılan: settings.yaml change_method)")
    d.add_argument("--panel-years", nargs=2, type=int, metavar=("ÖNCE", "SONRA"),
                   help="yapılaşma sınır paneli için iki yıl (varsayılan: ilk yıl ve 2024)")
    d.set_defaults(func=cmd_detect)

    wt = sub.add_parser("water", help="Yıllık su maskesi, su alanı serisi ve grafiği")
    aoi_years(wt)
    wt.add_argument("--mask-years", nargs=2, type=int, metavar=("A", "B"),
                    help="yan yana maske paneli yılları (varsayılan: ilk yıl ve sondan bir önceki)")
    wt.set_defaults(func=cmd_water)

    sm = sub.add_parser("sample", help="Faz 3: tabakalı örnekleme, labels.csv şablonu, çipler, QGIS yükleyici")
    sm.add_argument("--aois", nargs="+", help="örneklenecek AOI'ler (varsayılan: settings validation.aois)")
    sm.add_argument("--season", help="settings.yaml'daki pencere adı (varsayılan: composite.season)")
    sm.add_argument("--force", action="store_true", help="dolu labels.csv'nin üzerine yaz")
    sm.set_defaults(func=cmd_sample)

    va = sub.add_parser("validate", help="Etiketlerden karışıklık matrisi, tür ve yıl bazlı metrikler")
    va.add_argument("--set", choices=["test", "kalibrasyon", "hepsi"], default="test",
                    help="hangi noktalar (varsayılan: test)")
    va.add_argument("--map", choices=["stored", "current"], default="stored",
                    help="stored: örnekleme anındaki tahmin; current: güncel changes.geojson'dan okunur")
    va.add_argument("--season", help="--map current için pencere adı")
    va.set_defaults(func=cmd_validate)

    ex = sub.add_parser("experiments", help="E1–E5 deneylerini etiketlerden üret (etiket yoksa kuru çalıştırma)")
    ex.add_argument("--aois", nargs="+", help="AOI'ler (varsayılan: settings validation.aois)")
    ex.add_argument("--dry-run", action="store_true", help="yalnızca varyant durumlarını göster")
    ex.set_defaults(func=cmd_experiments)

    e = sub.add_parser("evaluate", help="Yöntem karşılaştırması: tür × yıl, yöntemler arası, tutarlılık")
    aoi_years(e)
    e.add_argument("--methods", nargs="+", default=["breakpoint", "pairs"], help="karşılaştırılacak yöntemler")
    e.add_argument("--direct-years", nargs=2, type=int, metavar=("A", "B"),
                   help="tutarlılık için doğrudan A→B karşılaştırması (varsayılan: ilk yıl → sondan bir önceki)")
    e.add_argument("--region", help="isteğe bağlı bölge(ler) GeoJSON'u (properties.name); koda gömülü bölge yok")
    e.set_defaults(func=cmd_evaluate)
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI giriş noktası."""
    for stream in (sys.stdout, sys.stderr):  # pipe/dosyada da Türkçe karakterler bozulmasın
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    setup_logging()
    try:
        return args.func(args)
    except (ConfigError, FileNotFoundError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
