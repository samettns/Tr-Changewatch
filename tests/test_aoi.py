"""aoi.py testleri (ağa çıkmaz, fixture kullanır)."""

from pathlib import Path

import geopandas as gpd
import pytest

from changewatch.aoi import check_aois, load_aois
from changewatch.config import load_settings

FIXTURE = Path(__file__).parent / "fixtures" / "aois_sample.geojson"


@pytest.fixture(scope="module")
def reports():
    return {r.name: r for r in check_aois(load_aois(FIXTURE), load_settings())}


def test_small_aoi_area_and_no_warnings(reports):
    r = reports["kucuk_incek"]
    # 0.05° x 0.04° @ 39.8°K ≈ 4.28 km x 4.45 km ≈ 19 km²
    assert 17 < r.area_km2 < 21
    assert r.bounds == pytest.approx((32.70, 39.78, 32.75, 39.82))
    assert r.warnings == []


def test_large_aoi_warns(reports):
    r = reports["buyuk_ankara"]
    assert r.area_km2 > 100
    assert any("km²" in w for w in r.warnings)


def test_outside_ankara_warns(reports):
    assert any("Ankara" in w for w in reports["istanbul_disarida"].warnings)


def test_missing_name_warns(reports):
    unnamed = [r for n, r in reports.items() if n.startswith("<adsız")]
    assert len(unnamed) == 1 and any("name" in w for w in unnamed[0].warnings)


def test_empty_template_returns_no_reports(tmp_path):
    p = tmp_path / "bos.geojson"
    p.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    assert check_aois(load_aois(p), load_settings()) == []


def test_empty_geodataframe():
    assert check_aois(gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), load_settings()) == []
