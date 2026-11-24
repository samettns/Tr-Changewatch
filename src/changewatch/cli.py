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
    from changewatch.stac import (aoi_geobox, dedupe_items, fine_geobox, load_item, search_items,
                                  season_dates)

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
        found = search_items(geom.bounds, start, end, settings, max_cloud=max_cloud)
        items = dedupe_items(found)
        log.info("%d: %d öğe (bulut < %%%g), kopya ayıklama sonrası %d", year, len(found), max_cloud,
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
    from changewatch.composite import median_composite
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
        kept, kept_ids, aoi_mask = [], set(), None
        for f in files:
            raw = cache.read_dataset(f)
            if aoi_mask is None:
                aoi_mask = aoi_raster_mask(geom, raw, crs)
            masked = apply_mask(harmonize_scene(raw, settings), settings)
            frac = valid_fraction(masked["valid"].values, aoi_mask)
            if frac < min_frac:
                log.warning("%d: %s kompozite alınmadı (AOI içi geçerli piksel %%%.0f < %%%.0f)",
                            year, raw.attrs["item_id"], 100 * frac, 100 * min_frac)
                continue
            kept.append(masked)
            kept_ids.add(f.name)
        log.info("%d: %d/%d sahne kompozite alındı", year, len(kept), len(files))
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
        files10 = [f for f in sorted(cache.raw10_dir(cache_root, args.aoi, year).glob("*.tif"))
                   if f.name in kept_ids]
        if len(files10) != len(kept_ids):
            log.warning("%d: 10 m katmanında %d/%d sahne var; `changewatch fetch` ile tamamlayın.",
                        year, len(files10), len(kept_ids))
        if files10:
            tband = settings["texture"]["band"]
            scale = float(settings["stac"]["reflectance_scale"])
            work_res = float(settings["grid"]["resolution_m"])
            tex_scenes = []
            for f in files10:
                m10 = apply_mask(harmonize_scene(cache.read_dataset(f), settings), settings)
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


def cmd_detect(args: argparse.Namespace) -> int:
    """İki yıl arasında değişim adayları: CVA + doku farkı (Otsu) → açma/kapama → MMU."""
    import numpy as np
    import xarray as xr

    from changewatch import cache
    from changewatch.change import change_candidates
    from changewatch.mask import aoi_raster_mask
    from changewatch.morphology import apply_mmu, mmu_pixels, open_close
    from changewatch.quicklook import save_change_panel_png, save_overlay_png

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    season = args.season or settings["composite"]["season"]
    crs = settings["grid"]["crs"]
    ya, yb = args.from_year, args.to_year
    cdir = cache.composite_dir(cache_root, args.aoi, season)
    files = [cdir / f"{ya}.tif", cdir / f"{yb}.tif", cdir / f"{ya}_texture.tif", cdir / f"{yb}_texture.tif"]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError("Kompozit eksik; önce `changewatch composite` çalıştırın: " + ", ".join(missing))
    comp_a, comp_b, ta, tb = (cache.read_dataset(f) for f in files)
    region = aoi_raster_mask(geom, comp_a, crs)

    c = change_candidates(comp_a, comp_b, ta["TEXTURE"].values, tb["TEXTURE"].values, settings, region)
    morph = open_close(c.mask, settings) & region
    final = apply_mmu(morph, settings)

    n = int(region.sum())
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    from scipy.ndimage import label

    conn = np.ones((3, 3)) if int(settings["morphology"]["connectivity"]) == 2 else None
    n_obj = label(final, structure=conn)[1]
    log.info("%s %d→%d | Otsu eşikleri: CVA %.4f, |Δdoku| %.4f (birleştirme: %s)", args.aoi, ya, yb,
             c.cva_threshold, c.texture_threshold, settings["change"]["combine"])
    for name, m in (("CVA > eşik", c.cva_flag & region), ("|Δdoku| > eşik", c.texture_flag & region),
                    ("ham aday", c.mask), ("açma/kapama sonrası", morph),
                    (f"MMU ({mmu_pixels(settings)} px) sonrası", final)):
        log.info("  %-22s %6d px  %%%5.2f  %8.1f ha", name, int(m.sum()), 100 * m.sum() / n, m.sum() * px_ha)
    log.info("  bağlı nesne sayısı: %d", n_obj)

    out = xr.Dataset({
        "cva": (("y", "x"), c.cva), "dtexture": (("y", "x"), c.dtexture),
        "cva_flag": (("y", "x"), c.cva_flag.astype("float32")),
        "texture_flag": (("y", "x"), c.texture_flag.astype("float32")),
        "candidate_raw": (("y", "x"), c.mask.astype("float32")),
        "candidate": (("y", "x"), final.astype("float32")),
    }, coords={"y": comp_a["y"], "x": comp_a["x"]})
    out.attrs.update(aoi=args.aoi, from_year=ya, to_year=yb, season=season,
                     cva_threshold=c.cva_threshold, texture_threshold=c.texture_threshold)
    ddir = cache.change_dir(cache_root, args.aoi, season)
    tif = cache.write_dataset(out, ddir / f"{ya}_{yb}_candidates.tif", crs, nodata=np.nan)
    prev = cache.preview_dir(cache_root, args.aoi) / "change"
    ov = save_overlay_png(comp_b, final, prev / f"{ya}_{yb}_{season}_candidates_on_{yb}.png", settings)
    panel = save_change_panel_png(comp_a, comp_b, final, prev / f"{ya}_{yb}_{season}_panel.png", settings,
                                  (str(ya), str(yb)),
                                  f"{args.aoi} {ya}→{yb} aday: {final.sum() * px_ha:.0f} ha, {n_obj} nesne")
    for p in (tif, ov, panel):
        log.info("  çıktı: %s (%s)", p, _human(p.stat().st_size))
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

    d = sub.add_parser("detect", help="İki yıl arası değişim adayları (CVA + doku, Otsu, morfoloji, MMU)")
    d.add_argument("--aoi", required=True, help="AOI adı (aois.geojson'daki name)")
    d.add_argument("--from-year", type=int, required=True, help="önceki yıl (ör. 2017)")
    d.add_argument("--to-year", type=int, required=True, help="sonraki yıl (ör. 2024)")
    d.add_argument("--season", help="settings.yaml'daki pencere adı (varsayılan: composite.season)")
    d.set_defaults(func=cmd_detect)
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
