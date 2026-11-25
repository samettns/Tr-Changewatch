"""config.py testleri."""

from pathlib import Path

import pytest

from changewatch.config import (CACHE_ENV, PROJECT_ROOT, ConfigError, cache_dir_path, load_settings,
                               require_cache_dir)


def test_default_settings_load():
    s = load_settings()
    assert s["grid"]["crs"] == "EPSG:32636"
    assert s["grid"]["resolution_m"] == 20
    assert s["years"] == {"start": 2017, "end": 2026}


def test_default_cache_dir_is_project_data(monkeypatch):
    monkeypatch.delenv(CACHE_ENV, raising=False)
    s = load_settings()
    assert s["paths"]["cache_dir"] == "./data"
    assert cache_dir_path(s) == (PROJECT_ROOT / "data", False)


def test_env_var_overrides_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(CACHE_ENV, str(tmp_path))
    assert require_cache_dir(load_settings()) == tmp_path


def test_missing_env_cache_dir_gives_clear_error_and_is_not_created(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "yok"))
    with pytest.raises(ConfigError, match="CHANGEWATCH_CACHE"):
        require_cache_dir(load_settings())
    assert not (tmp_path / "yok").exists()  # harici disk takılı değilse klasörü kendiliğinden oluşturmaz


def test_missing_default_cache_dir_is_created_relative_to_root(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(CACHE_ENV, raising=False)
    s = {"_root": tmp_path, "paths": {"cache_dir": "./data"}}
    assert require_cache_dir(s) == tmp_path / "data" and (tmp_path / "data").is_dir()


def test_windows_env_path_not_mangled(monkeypatch):
    # ters bölü + t sekmeye dönüşmemeli; ortam değişkeni olduğu gibi kullanılır
    monkeypatch.setenv(CACHE_ENV, r"D:\tr-changewatch-data")
    assert str(cache_dir_path({})[0]) == r"D:\tr-changewatch-data"


def test_existing_cache_dir_returned(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(CACHE_ENV, raising=False)
    assert require_cache_dir({"paths": {"cache_dir": str(tmp_path)}}) == tmp_path


def test_missing_settings_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "yok.yaml")
