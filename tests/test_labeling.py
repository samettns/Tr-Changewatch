"""labeling.py yardımcı fonksiyon testleri (arayüz test edilmez; ağa çıkmaz)."""

import numpy as np
from shapely.geometry import Polygon, box

from changewatch.labeling import (chip_token, maps_url, normalize_entry, read_label_rows, shuffled_order,
                                  validate_entry, water_validation_points, write_label_rows, year_for_key)
from changewatch.validate import filled_labels, metrics, read_labels, unsure_labels

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
    write_label_rows(p, rows)
    again = read_label_rows(p, ids, {})
    assert again["P001"]["gercek_tur"] == "yapilasma_olasi" and again["P001"]["not"] == "şantiye"
    assert not (tmp_path / "labels.tmp").exists()


def test_write_keeps_rows_outside_set(tmp_path):
    """Yalnızca test noktaları etiketlenirken kalibrasyon satırları ve eski etiketler korunur."""
    p = tmp_path / "labels.csv"
    p.write_text("nokta_id,aoi,gercek_degisim,gercek_tur,gercek_yil,not\n"
                 "P001,incek,,,,\nP002,incek,hayir,diger,2017,\nP003,golbasi,evet,bitki_kaybi,2019,x\n",
                 encoding="utf-8")
    rows = read_label_rows(p, ["P001", "P003"], {})          # P002 sette değil (kalibrasyon)
    rows["P001"].update(normalize_entry({"gercek_degisim": "evet"}))
    write_label_rows(p, rows)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[1:] == ["P001,incek,evet,yapilasma_olasi,bilinmiyor,", "P002,incek,hayir,diger,2017,",
                         "P003,golbasi,evet,bitki_kaybi,2019,x"]


def test_validate_and_normalize_entry():
    assert validate_entry({}) is not None
    assert validate_entry({"gercek_degisim": "hayir"}) is None
    assert validate_entry({"gercek_degisim": "emin_degilim"}) is None
    assert validate_entry({"gercek_degisim": "evet", "gercek_tur": "diger"}) is None      # yıl isteğe bağlı
    assert normalize_entry({"gercek_degisim": "evet"}) == {"gercek_degisim": "evet", "gercek_tur": "yapilasma_olasi",
                                                           "gercek_yil": "bilinmiyor"}
    assert normalize_entry({"gercek_degisim": "evet", "gercek_tur": "bitki_kaybi", "gercek_yil": "2021"})[
        "gercek_tur"] == "bitki_kaybi"
    u = normalize_entry({"gercek_degisim": "emin_degilim", "gercek_tur": "diger", "gercek_yil": "2020"})
    assert u["gercek_tur"] == "" and u["gercek_yil"] == ""


def test_unsure_excluded_from_metrics_and_counted(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text("nokta_id,aoi,gercek_degisim,gercek_tur,gercek_yil,not\n"
                 "P001,a,evet,yapilasma_olasi,bilinmiyor,\nP002,a,emin_degilim,,,\nP003,a,,,,\n", encoding="utf-8")
    rows = read_labels(p)
    assert [r["nokta_id"] for r in filled_labels(rows)] == ["P001"]
    assert [r["nokta_id"] for r in unsure_labels(rows)] == ["P002"]


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
    assert u == "https://maps.google.com/?q=39.800000,32.800000&t=k&z=18"


def test_metrics_ignore_unknown_year():
    recs = [{"ref": "yapilasma_olasi", "pred": "yapilasma_olasi", "pred_year": 2021, "ref_year": "bilinmiyor"},
            {"ref": "yapilasma_olasi", "pred": "yapilasma_olasi", "pred_year": 2021, "ref_year": "2021"}]
    m = metrics(recs)
    assert m["yil"]["degisim_yakalanan_n"] == 1 and m["yil"]["tam_isabet"] == 1.0
    assert np.isclose(m["genel_dogruluk"], 1.0)


def test_label_chip_png(tmp_path):
    """Etiket çipi (yatay): solda iki büyük kare yan yana, sağda 2 × 5 şerit; 1920 × 1080 ekrana sığar."""
    import xarray as xr
    from PIL import Image

    from changewatch.quicklook import save_label_chip_png

    settings = {"grid": {"resolution_m": 20},
                "stac": {"reflectance_scale": 10000},
                "quicklook": {"rgb_bands": ["B04", "B03", "B02"], "rgb_min": 0.0, "rgb_max": 0.3, "gamma": 1.0},
                "validation": {"chip_px": 41, "label_big_px": 330, "label_strip_upscale": 3, "label_ring_m": 100,
                               "label_scalebar_m": 200}}
    rng = np.random.default_rng(0)
    seq = [(y, xr.Dataset({b: (("y", "x"), rng.uniform(0, 3000, (60, 60))) for b in ("B04", "B03", "B02")}))
           for y in YEARS]
    out = save_label_chip_png(seq, 30, 30, tmp_path / "c.png", settings)
    w, h = Image.open(out).size
    assert w >= 2 * 328 + 5 * 123 and h >= 328 and w <= 1800 and h <= 450
