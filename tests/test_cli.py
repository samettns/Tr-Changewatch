"""cli.py testleri."""

from pathlib import Path

import pytest

from changewatch.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "aois_sample.geojson"


def test_help(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "check-aois" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "check-aois" in capsys.readouterr().out


def test_check_aois_prints_reports(capsys):
    assert main(["check-aois", "--aois", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "kucuk_incek" in out and "km²" in out and "UYARI" in out
    assert "4 AOI kontrol edildi" in out


def test_check_aois_empty_template(tmp_path, capsys):
    p = tmp_path / "bos.geojson"
    p.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    assert main(["check-aois", "--aois", str(p)]) == 0
    assert "AOI bulunamadı" in capsys.readouterr().out


def test_check_aois_missing_file(tmp_path, capsys):
    assert main(["check-aois", "--aois", str(tmp_path / "yok.geojson")]) == 2
    assert "HATA" in capsys.readouterr().err


def test_parse_years():
    from changewatch.cli import parse_years
    from changewatch.config import load_settings

    s = load_settings()
    assert parse_years(["2017", "2024"], s) == [2017, 2024]
    assert parse_years(["2019-2021", "2024"], s) == [2019, 2020, 2021, 2024]
    assert parse_years(None, s) == list(range(2017, 2027))


def test_unknown_aoi_gives_clear_error(capsys):
    assert main(["scenes", "--aoi", "yok"]) == 2
    err = capsys.readouterr().err
    assert "AOI bulunamadı" in err and "incek" in err


def test_test_aoi_sets_are_separate_and_all_test():
    """Test AOI örneklemesi ayrı dosyalara yazar, kalibrasyon payı yok; etiketleme setleri ayrışık."""
    from changewatch.cli import build_parser
    from changewatch.config import load_settings

    s = load_settings()
    tv, p = s["test_validation"], s["paths"]
    assert tv["calibration_share"] == 0
    assert tv["seed"] != s["validation"]["seed"]
    assert set(tv["aois"]).isdisjoint(s["validation"]["aois"])
    assert p["test_aoi_points"] != p["validation_points"] and p["test_aoi_labels"] != p["validation_labels"]
    a = build_parser().parse_args(["sample", "--set", "test_aoi"])
    assert a.set == "test_aoi"
    assert build_parser().parse_args(["label", "--set", "test_aoi"]).set == "test_aoi"
