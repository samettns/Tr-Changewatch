"""evaluate.py testleri (sentetik geometriler; ağa çıkmaz)."""

import json

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box

from changewatch.evaluate import consistency, load_features, markdown_type_year, method_summary, type_year_table

X0, Y0 = 500_000.0, 4_400_000.0  # UTM 36N


def _feat(x0, y0, size, tur, yil):
    g = box(X0 + x0, Y0 - y0 - size, X0 + x0 + size, Y0 - y0)
    return g, {"tur": tur, "degisim_yili": yil, "alan_ha": g.area / 10_000}


FEATS = [_feat(0, 0, 100, "yapilasma_olasi", 2020),      # 1 ha
         _feat(50, 0, 100, "belirsiz", 2021),            # 1 ha, yarısı ilkiyle örtüşüyor
         _feat(400, 400, 200, "yapilasma_olasi", 2026)]  # 4 ha


def test_type_year_table_and_markdown():
    tab = type_year_table(FEATS, [2020, 2021, 2026])
    assert tab["yapilasma_olasi"] == {2020: 1.0, 2021: 0.0, 2026: 4.0}
    md = markdown_type_year(tab, [2020, 2021, 2026])
    assert "| yapilasma_olasi | 1 | 0 | 4 | 5 |" in md and "| toplam | 1 | 1 | 4 | 6 |" in md


def test_method_summary_footprint_and_region():
    reg = {"kuzey": box(X0, Y0 - 100, X0 + 1000, Y0)}
    s = method_summary(FEATS, reg)
    assert s["yapilasma_ha"] == 5.0 and s["tum_turler_ha"] == 6.0
    assert s["ayak_izi_ha"] == 5.5                         # örtüşme bir kez sayılır
    assert s["bolgeler"]["kuzey"]["ayak_izi_ha"] == 1.5
    assert s["bolgeler"]["kuzey"]["yapilasma_ha"] == 1.0


def test_consistency_overlap():
    t = Affine(20, 0, X0, 0, -20, Y0)
    direct = np.zeros((50, 50), bool)
    direct[0:5, 0:5] = True                                # 1 ha, yıl 2020 yapılaşmasıyla aynı yer
    direct[30:35, 30:35] = True                            # 1 ha, yöntem yakalamamış
    c = consistency(direct, FEATS, 2017, 2024, t, 0.04)
    assert c["yontem_yapilasma_ha"] == 1.0 and c["dogrudan_ha"] == 2.0
    assert c["yontemin_dogrudan_icindeki_payi"] == 1.0
    assert c["dogrudanin_kapsanan_payi"] == pytest.approx(0.5)


def test_load_features_projects_to_crs(tmp_path):
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"tur": "belirsiz"},
          "geometry": {"type": "Polygon", "coordinates": [[[32.70, 39.80], [32.71, 39.80], [32.71, 39.81],
                                                           [32.70, 39.81], [32.70, 39.80]]]}}]}
    p = tmp_path / "c.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")
    (g, props), = load_features(p, "EPSG:32636")
    assert 450_000 < g.centroid.x < 500_000 and 90 < g.area / 10_000 < 100   # 33°D merkez meridyeninin batısı; ~0.01° × 0.01° ≈ 95 ha
