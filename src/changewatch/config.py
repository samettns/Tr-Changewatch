"""settings.yaml yükleme ve cache_dir kontrolü."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"


class ConfigError(RuntimeError):
    """Ayar dosyası veya ayarlarda gösterilen yollar geçersiz."""


def load_settings(path: Path | str | None = None) -> dict[str, Any]:
    """settings.yaml dosyasını okuyup sözlük döndürür."""
    path = Path(path) if path else DEFAULT_SETTINGS
    if not path.is_file():
        raise ConfigError(f"Ayar dosyası bulunamadı: {path}")
    with path.open(encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    settings["_root"] = path.resolve().parent.parent
    return settings


def resolve_path(settings: dict[str, Any], value: str) -> Path:
    """Göreli yolları proje köküne göre çözer."""
    p = Path(value)
    return p if p.is_absolute() else Path(settings["_root"]) / p


def require_cache_dir(settings: dict[str, Any]) -> Path:
    """cache_dir'i döndürür; klasör yoksa anlaşılır bir hata verir (oluşturmaz)."""
    raw = settings.get("paths", {}).get("cache_dir")
    if not raw:
        raise ConfigError("settings.yaml içinde paths.cache_dir tanımlı değil.")
    cache = Path(raw)
    if not cache.is_dir():
        raise ConfigError(
            f"Önbellek klasörü bulunamadı: {cache}\n"
            "Harici SSD takılı mı? Takılıysa klasörü oluşturun "
            f"(ör. mkdir \"{cache}\") veya settings.yaml'daki paths.cache_dir değerini düzeltin."
        )
    return cache
