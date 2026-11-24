"""labeling.py yardımcı fonksiyon testleri (arayüz test edilmez; ağa çıkmaz)."""

import numpy as np
from shapely.geometry import Polygon, box

from changewatch.labeling import (chip_token, maps_url, read_label_rows, shuffled_order, validate_entry,
                                  water_validation_points, write_label_rows, year_for_key)
from changewatch.validate import metrics

YEARS = list(range(2017, 2027))


def test_chip_token_is_blind_and_stable():
    t = chip_token("tuz", "P001")
    assert t == chip_token("tuz", "P001") and len(t) == 12
    assert "P001" not in t and t != chip_token("tuz", "P002")


def test_year_keys():
    assert year_for_key("8", YEARS) == "2018"
    assert year_for_key("0", YEARS) == "2020"
    assert year_for_key("6", YEARS) == "2026"
    assert year_for_key("7", YEARS) == "2017"
    assert year_for_key("x", YEARS) == "bilinmiyor"
    assert year_for_key("a", YEARS) is None


def test_shuffled_order_deterministic_permutation():
    ids = [f"P{i:03d}" for i in range(1, 51)]
    a, b = shuffled_order(ids, 7), shuffled_order(ids, 7)
    assert a == b and sorted(a) == ids and a != ids


def test_label_rows_roundtrip_and_resume(tmp_path):
    p = tmp_path / "labels.csv"
    ids = ["P001", "P002"]
    rows = read_label_rows(p, ids, {"P001": "incek", "P002": "golbasi"})
    assert rows["P002"]["aoi"] == "golbasi" and rows["P001"]["gercek_degisim"] == ""
    rows["P001"].update(gercek_degisim="evet", gercek_tur="yapilasma_olasi", gercek_yil="2021", **{"not": "şantiye"})
    write_label_rows(p, rows, ids)
    again = read_label_rows(p, ids, {})
    assert again["P001"]["gercek_tur"] == "yapilasma_olasi" and again["P001"]["not"] == "şantiye"
    assert not (tmp_path / "labels.tmp").exists()


def test_validate_entry():
    assert validate_entry({}) is not None
    assert validate_entry({"gercek_degisim": "hayir"}) is None
    assert validate_entry({"gercek_degisim": "evet", "gercek_tur": "diger"}) is not None   # yıl eksik
    assert validate_entry({"gercek_degisim": "evet", "gercek_tur": "diger", "gercek_yil": "bilinmiyor"}) is None


def test_water_points_inside_polygons():
    ring = Polygon([(0, 0), (10, 0), (10, 1), (1, 1), (1, 10), (0, 10)])          # L biçimi: merkez dışarıda
    feats = {"kalici": [(ring, {"id": "a", "tur": "su_kazanimi", "degisim_yili": 2021, "alan_ha": 1.0}),
                        (box(20, 20, 21, 21), {"id": "b", "tur": "yapilasma_olasi", "degisim_yili": 2021,
                                               "alan_ha": 1.0})],
             "izleme": [(box(30, 30, 31, 31), {"id": "c", "tur": "su_kaybi", "degisim_yili": 2026, "alan_ha": 0.2})]}
    pts = water_validation_points(feats, "golbasi")
    assert [p["kaynak_id"] for p in pts] == ["a", "c"] and [p["nokta_id"] for p in pts] == ["S01", "S02"]
    from shapely.geometry import Point
    assert ring.contains(Point(pts[0]["lon"], pts[0]["lat"]))


def test_maps_url_satellite():
    u = maps_url(39.8, 32.8)
    assert "39.800000,32.800000" in u and "!1e3" in u


def test_metrics_ignore_unknown_year():
    recs = [{"ref": "yapilasma_olasi", "pred": "yapilasma_olasi", "pred_year": 2021, "ref_year": "bilinmiyor"},
            {"ref": "yapilasma_olasi", "pred": "yapilasma_olasi", "pred_year": 2021, "ref_year": "2021"}]
    m = metrics(recs)
    assert m["yil"]["degisim_yakalanan_n"] == 1 and m["yil"]["tam_isabet"] == 1.0
    assert np.isclose(m["genel_dogruluk"], 1.0)
