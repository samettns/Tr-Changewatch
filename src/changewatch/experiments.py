"""E1–E5 deney kaydı: her deneyin varyantları, hangi çıktıdan okunduğu ve hangi komutlarla üretildiği.

`changewatch experiments --build` hazır olmayan varyantları üretir ve her varyantın örnekleme noktalarındaki
tahminini validation/experiment_predictions.csv'ye yazar; etiketler gelince `changewatch experiments` hepsini
test noktalarında tek seferde değerlendirir.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Variant:
    """Bir deney kolu: change/<season>/<method_dir>/changes.geojson ve onu üreten CLI adımları."""

    name: str
    season: str | None
    method_dir: str | None
    steps: tuple[tuple[str, ...], ...] = field(default_factory=tuple)   # "{aoi}" yer tutuculu argv listeleri
    note: str = ""

    def path(self, cache_root: Path, aoi: str) -> Path | None:
        if self.season is None or self.method_dir is None:
            return None
        return cache_root / aoi / "change" / self.season / self.method_dir / "changes.geojson"


BASE = Variant("kirilma", "summer", "breakpoint", (("detect", "--aoi", "{aoi}"),))
PAIRS = (("detect", "--aoi", "{aoi}", "--method", "pairs"),)

EXPERIMENTS: dict[str, tuple[str, list[Variant]]] = {
    "E1": ("Tek sahne ↔ medyan kompozit ↔ kompozit + kalıcılık (ardışık çift) ↔ kırılma noktası", [
        Variant("tek_sahne", "summer_tek", "pairs_kaliciliksiz", (
            ("composite", "--aoi", "{aoi}", "--season", "summer_tek", "--single-scene"),
            ("detect", "--aoi", "{aoi}", "--season", "summer_tek", "--method", "pairs", "--no-persistence",
             "--out-name", "pairs_kaliciliksiz")),
            "yıl başına AOI geçerli piksel oranı en yüksek tek çekim; ardışık çift, kalıcılık yok"),
        Variant("kompozit_kaliciliksiz", "summer", "pairs_kaliciliksiz", (
            ("detect", "--aoi", "{aoi}", "--method", "pairs", "--no-persistence", "--out-name",
             "pairs_kaliciliksiz"),), "medyan kompozit; ardışık çift, kalıcılık yok"),
        Variant("kompozit_kalicilik", "summer", "pairs", PAIRS, "medyan kompozit; ardışık çift + kalıcılık"),
        BASE,
    ]),
    "E2": ("Mevsim penceresi: Mayıs–Haziran ↔ Temmuz–Eylül (kırılma yöntemi)", [
        Variant("yaz", "summer", "breakpoint", BASE.steps),
        Variant("ilkbahar", "spring", "breakpoint", (
            ("fetch", "--aoi", "{aoi}", "--season", "spring"),
            ("composite", "--aoi", "{aoi}", "--season", "spring"),
            ("detect", "--aoi", "{aoi}", "--season", "spring")),
            "v2'ye ertelendi (ayrı indirme gerektirir); --build kapsamında değil"),
    ]),
    "E3": ("Harmonizasyon açık ↔ kapalı", [
        Variant("acik", "summer", "breakpoint", BASE.steps),
        Variant("kapali", "summer_harmkapali", "breakpoint", (
            ("composite", "--aoi", "{aoi}", "--season", "summer_harmkapali", "--no-harmonize"),
            ("detect", "--aoi", "{aoi}", "--season", "summer_harmkapali"))),
    ]),
    "E4": ("Eski NDBI/BSI artışı kuralı ↔ doku + kalıcılık kuralı", [
        Variant("doku_kalicilik", "summer", "breakpoint", BASE.steps),
        Variant("ndbi_bsi", "summer", "breakpoint_ndbi", (
            ("detect", "--aoi", "{aoi}", "--built-rule", "ndbi", "--out-name", "breakpoint_ndbi"),),
            "yapılaşma = dNDBI > 0, dBSI > 0, dNDVI < 0 (doku gerekmez)"),
    ]),
    "E5": ("Doku ham ↔ yıllık normalize doku", [
        Variant("ham", "summer", "breakpoint", BASE.steps),
        Variant("normalize", "summer", "breakpoint_dokunorm", (
            ("detect", "--aoi", "{aoi}", "--texture-norm", "--out-name", "breakpoint_dokunorm"),)),
    ]),
}

NOT_BUILT_BY_DEFAULT = {("E2", "ilkbahar")}
PRED_FIELDS = ["nokta_id", "aoi", "deney", "varyant", "tahmin_tur", "tahmin_yil"]


def status(v: Variant, cache_root: Path, aois: list[str]) -> str:
    """'hazır' | 'eksik'."""
    paths = [v.path(cache_root, a) for a in aois]
    return "hazır" if all(p is not None and p.exists() for p in paths) else "eksik"


def unique_variants() -> dict[tuple[str, str], Variant]:
    """(season, method_dir) → varyant (aynı çıktıyı paylaşan varyantlar bir kez üretilir)."""
    out: dict[tuple[str, str], Variant] = {}
    for code, (_, vs) in EXPERIMENTS.items():
        for v in vs:
            if (code, v.name) in NOT_BUILT_BY_DEFAULT:
                continue
            out.setdefault((v.season, v.method_dir), v)
    return out


def write_predictions(rows: list[dict], path: Path) -> Path:
    """Varyant tahminlerini CSV'ye yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRED_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def read_predictions(path: Path) -> dict[tuple[str, str], dict[str, tuple[str, int | None]]]:
    """(deney, varyant) → nokta_id → (tür, yıl)."""
    out: dict[tuple[str, str], dict[str, tuple[str, int | None]]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault((r["deney"], r["varyant"]), {})[r["nokta_id"]] = (
                r["tahmin_tur"], int(r["tahmin_yil"]) if r["tahmin_yil"] else None)
    return out
