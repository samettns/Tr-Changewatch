"""settings.yaml yükleme ve önbellek klasörü (cache_dir / CHANGEWATCH_CACHE) çözümleme."""

from __future__ import annotations

import os
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


CACHE_ENV = "CHANGEWATCH_CACHE"


def cache_dir_path(settings: dict[str, Any]) -> tuple[Path, bool]:
    """Önbellek klasörü ve ortam değişkeninden gelip gelmediği.

    Öncelik: CHANGEWATCH_CACHE ortam değişkeni → settings.yaml paths.cache_dir (göreliyse proje köküne göre).
    """
    env = os.environ.get(CACHE_ENV, "").strip()
    if env:
        return Path(env).expanduser(), True
    raw = settings.get("paths", {}).get("cache_dir")
    if not raw:
        raise ConfigError(f"Önbellek klasörü tanımlı değil: {CACHE_ENV} ya da settings.yaml paths.cache_dir.")
    p = Path(raw)
    return (p if p.is_absolute() else Path(settings.get("_root", PROJECT_ROOT)) / p), False


def require_cache_dir(settings: dict[str, Any]) -> Path:
    """Önbellek klasörünü döndürür.

    settings.yaml'daki (varsayılan: proje içi ./data) klasör yoksa oluşturulur. CHANGEWATCH_CACHE ile verilen
    klasör yoksa oluşturulmaz ve anlaşılır bir hata verilir (harici disk takılı olmayabilir).
    """
    cache, from_env = cache_dir_path(settings)
    if cache.is_dir():
        return cache
    if from_env:
        raise ConfigError(
            f"Önbellek klasörü bulunamadı: {cache} ({CACHE_ENV} ortam değişkeninden)\n"
            "Harici disk takılı mı? Takılıysa klasörü oluşturun "
            f"(ör. mkdir \"{cache}\") veya {CACHE_ENV} değişkenini düzeltin/kaldırın."
        )
    cache.mkdir(parents=True, exist_ok=True)
    return cache
