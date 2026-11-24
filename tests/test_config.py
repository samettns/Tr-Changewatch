"""config.py testleri."""

from pathlib import Path

import pytest

from changewatch.config import ConfigError, load_settings, require_cache_dir


def test_default_settings_load():
    s = load_settings()
    assert s["grid"]["crs"] == "EPSG:32636"
    assert s["grid"]["resolution_m"] == 20
    assert s["years"] == {"start": 2017, "end": 2026}


def test_cache_dir_windows_path_not_mangled():
    # "\t" sekmeye dönüşmemeli (YAML tek tırnak kuralı)
    assert load_settings()["paths"]["cache_dir"] == r"D:\tr-changewatch-data"


def test_missing_cache_dir_gives_clear_error(tmp_path: Path):
    s = {"paths": {"cache_dir": str(tmp_path / "yok")}}
    with pytest.raises(ConfigError, match="Önbellek klasörü bulunamadı"):
        require_cache_dir(s)
    assert not (tmp_path / "yok").exists()  # klasörü kendiliğinden oluşturmaz


def test_existing_cache_dir_returned(tmp_path: Path):
    assert require_cache_dir({"paths": {"cache_dir": str(tmp_path)}}) == tmp_path


def test_missing_settings_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "yok.yaml")
