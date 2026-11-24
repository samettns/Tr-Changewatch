"""E1–E5 deney kaydı: her deneyin varyantları, hangi çıktıdan okunduğu ve nasıl üretildiği.

Etiketler varken her hazır varyantın haritası test noktalarında değerlendirilir; yoksa kuru çalıştırma
hangi varyantın hazır/eksik/henüz uygulanmamış olduğunu gösterir.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Variant:
    """Bir deney kolu."""

    name: str
    season: str | None          # None: henüz uygulanmadı
    method_dir: str | None      # change/<season>/<method_dir>/changes.geojson
    produce: str                # üretmek için komut ya da eksik olan uygulama

    def path(self, cache_root: Path, aoi: str) -> Path | None:
        if self.season is None or self.method_dir is None:
            return None
        return cache_root / aoi / "change" / self.season / self.method_dir / "changes.geojson"


NOT_IMPL = "henüz uygulanmadı"

EXPERIMENTS: dict[str, tuple[str, list[Variant]]] = {
    "E1": ("Tek sahne ↔ medyan kompozit ↔ kompozit + kalıcılık (ardışık çift) ↔ kırılma noktası", [
        Variant("tek_sahne", None, None, f"{NOT_IMPL}: tek sahne çifti üzerinde aday üretimi"),
        Variant("kompozit_kaliciliksiz", None, None,
                f"{NOT_IMPL}: pairs yöntemini classify.drop_non_persistent=false ile ayrı klasöre yazma"),
        Variant("kompozit_kalicilik", "summer", "pairs", "changewatch detect --aoi {aoi} --method pairs"),
        Variant("kirilma", "summer", "breakpoint", "changewatch detect --aoi {aoi}"),
    ]),
    "E2": ("Mevsim penceresi: Mayıs–Haziran ↔ Temmuz–Eylül (kırılma yöntemi)", [
        Variant("yaz", "summer", "breakpoint", "changewatch detect --aoi {aoi}"),
        Variant("ilkbahar", "spring", "breakpoint",
                "changewatch fetch/composite --aoi {aoi} --season spring; changewatch detect --aoi {aoi} --season spring"),
    ]),
    "E3": ("Harmonizasyon açık ↔ kapalı (2021→2023)", [
        Variant("acik", "summer", "breakpoint", "changewatch detect --aoi {aoi}"),
        Variant("kapali", None, None, f"{NOT_IMPL}: composite için harmonizasyonu kapatan seçenek + ayrı çıktı"),
    ]),
    "E4": ("Eski NDBI/BSI artışı kuralı ↔ doku + kalıcılık kuralı", [
        Variant("doku_kalicilik", "summer", "breakpoint", "changewatch detect --aoi {aoi}"),
        Variant("ndbi_bsi", None, None, f"{NOT_IMPL}: kırılma parçalarını eski NDBI/BSI yön koşuluyla sınıflama"),
    ]),
    "E5": ("Doku ham ↔ yıllık normalize doku", [
        Variant("ham", "summer", "breakpoint", "changewatch detect --aoi {aoi}"),
        Variant("normalize", None, None, f"{NOT_IMPL}: dokuyu yılın kırılmasız piksellerinin medyanına bölme"),
    ]),
}


def status(v: Variant, cache_root: Path, aois: list[str]) -> str:
    """'hazır' | 'eksik' | 'henüz uygulanmadı'."""
    if v.season is None:
        return NOT_IMPL
    paths = [v.path(cache_root, a) for a in aois]
    return "hazır" if all(p is not None and p.exists() for p in paths) else "eksik"
