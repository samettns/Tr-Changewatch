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
    from changewatch.stac import aoi_geobox, dedupe_items, load_item, search_items, season_dates

    settings = load_settings(args.config)
    cache_root = require_cache_dir(settings)
    setup_logging(settings)
    geom = get_aoi(settings, args.aoi)
    gbox = aoi_geobox(geom, settings)
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
        out_dir = cache.raw_dir(cache_root, args.aoi, year)
        new = 0
        for it in items:
            path = out_dir / f"{it.id}.tif"
            if path.exists():
                continue
            ds = load_item(it, gbox, settings)
            cache.write_dataset(ds, path, settings["grid"]["crs"], nodata=settings["stac"]["nodata"])
            new += path.stat().st_size
            log.info("  indirildi: %s (%s)", it.id, _human(path.stat().st_size))
        size = sum(p.stat().st_size for p in out_dir.glob("*.tif")) if out_dir.exists() else 0
        log.info("%d: yeni %s, klasör toplamı %s (%s)", year, _human(new), _human(size), out_dir)
        total_new += new
    log.info("Toplam yeni veri: %s", _human(total_new))
    return 0


def cmd_composite(args: argparse.Namespace) -> int:
    """Önbellekteki sahneleri harmonize + maskeler, düşük geçerlilikli sahneleri eler, medyan kompozit üretir."""
    import numpy as np

    from changewatch import cache
    from changewatch.composite import median_composite
    from changewatch.harmonize import harmonize_scene
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
        kept, aoi_mask = [], None
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
        for p in (tif, rgb, obs):
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
