"""publish: yayın filtresi, sadeleştirme, tür×yıl tablosu, önizleme yeniden örnekleme, boyut bütçesi."""

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box, shape

from changewatch.publish import (accuracy_summary, check_budget, png_bytes, public_layer, type_year_ha,
                                 warp_rgba)

CRS = "EPSG:32636"
SETTINGS = {"publish": {"types": ["yapilasma_olasi", "bitki_kaybi", "belirsiz"], "simplify_m": 10.0,
                        "coord_decimals": 6, "evidence_props": ["skor", "dNDVI"]}}


def _feat(tur, yil, x0=480_000.0, ha=1.0):
    g = box(x0, 4_400_000, x0 + 100, 4_400_100)
    return g, {"id": f"{tur}-{yil}", "tur": tur, "degisim_yili": yil, "alan_ha": ha, "guven": "orta",
               "durum": "kalici", "katman": "kalici", "skor": 4.2, "dNDVI": -0.1, "basamak": 9.9}


def test_public_layer_drops_water_and_keeps_only_whitelisted_props():
    feats = [_feat("yapilasma_olasi", 2020), _feat("su_kazanimi", 2022), _feat("sulak_alan_belirsiz", 2021),
             _feat("belirsiz", 2026)]
    fc = public_layer(feats, CRS, SETTINGS)
    assert [f["properties"]["tur"] for f in fc["features"]] == ["yapilasma_olasi", "belirsiz"]
    p = fc["features"][0]["properties"]
    assert p["kanit"] == {"skor": 4.2, "dNDVI": -0.1}
    assert "basamak" not in p and "basamak" not in p["kanit"]
    lon, lat = fc["features"][0]["geometry"]["coordinates"][0][0]
    assert 30 < lon < 36 and 39 < lat < 41                     # WGS84
    assert shape(fc["features"][0]["geometry"]).is_valid


def test_type_year_ha_sums_published_types_only():
    feats = [_feat("yapilasma_olasi", 2020, ha=1.5), _feat("yapilasma_olasi", 2020, ha=0.5),
             _feat("yapilasma_olasi", 2023, ha=2.0), _feat("su_kazanimi", 2022, ha=9.0)]
    t = type_year_ha(feats, ["yapilasma_olasi", "bitki_kaybi"])
    assert t == {"yapilasma_olasi": {"2020": 2.0, "2023": 2.0}, "bitki_kaybi": {}}


def test_warp_rgba_to_web_mercator_returns_latlng_bounds_and_keeps_alpha():
    rgba = np.zeros((50, 40, 4), "float32")
    rgba[..., 0] = 1.0
    rgba[10:20, 10:20, 3] = 1.0
    out, bounds = warp_rgba(rgba, Affine(20, 0, 480_000, 0, -20, 4_420_000), CRS, "EPSG:3857")
    (s, w), (n, e) = bounds
    assert s < n and w < e and 39 < s < 41 and 32 < w < 34
    assert 0 < out[..., 3].sum() < out.shape[0] * out.shape[1]
    assert len(png_bytes(out, 16)) > 0


def test_check_budget_flags_large_png(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.png").write_bytes(b"0" * 2048)
    (tmp_path / "a" / "y.json").write_bytes(b"0" * 10)
    assert check_budget(tmp_path, 50, 4)["ok"]
    bad = check_budget(tmp_path, 50, 1)
    assert not bad["ok"] and bad["buyuk_png"] == ["a\\x.png"] or bad["buyuk_png"] == ["a/x.png"]


def test_accuracy_summary_picks_page_metrics():
    rep = {"n": 10, "ikili": {"kesinlik": 0.5, "duyarlilik": 0.8},
           "sinif_metrikleri": {"yapilasma_olasi": {"kullanici_dogrulugu": 0.6, "uretici_dogrulugu": 0.4, "f1": 0.48}},
           "olofsson": {"genel_dogruluk": 0.7, "genel_dogruluk_ga": 0.1,
                        "siniflar": {"yapilasma_olasi": {"harita_alani_ha": 5, "kestirilen_alan_ha": 9,
                                                         "alan_ga_ha": 3}}},
           "yil": {"tam_isabet": 0.5, "pm1_isabet": 0.9, "degisim_yakalanan_n": 4}}
    s = accuracy_summary({"gruplar": {"a + b": rep}}, None, {"a+b": 2})
    d = s["gelistirme"]["a+b"]
    assert d["yapilasma_f1"] == pytest.approx(0.48) and d["emin_degilim"] == 2 and d["yapilasma_kestirim_ha"] == 9
    assert s["test_aoi"] == {}
