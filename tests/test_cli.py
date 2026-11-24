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


def test_check_aois_empty_template(capsys):
    assert main(["check-aois"]) == 0
    assert "AOI bulunamadı" in capsys.readouterr().out


def test_check_aois_missing_file(tmp_path, capsys):
    assert main(["check-aois", "--aois", str(tmp_path / "yok.geojson")]) == 2
    assert "HATA" in capsys.readouterr().err
