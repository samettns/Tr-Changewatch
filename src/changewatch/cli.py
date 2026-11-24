"""Komut satırı arayüzü: changewatch <komut>."""

from __future__ import annotations

import argparse
import sys

from changewatch import __version__
from changewatch.config import ConfigError, load_settings, resolve_path


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
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI giriş noktası."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (ConfigError, FileNotFoundError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
