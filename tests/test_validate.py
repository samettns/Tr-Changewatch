"""validate.py ve experiments.py testleri (sentetik; ağa çıkmaz)."""

import numpy as np
import pytest
from shapely.geometry import box

from changewatch.experiments import EXPERIMENTS, status
from changewatch.validate import (NO_CHANGE, allocate, filled_labels, lookup_predictions, metrics, read_labels,
                                  reference_class, sample_pixels, summary_counts, write_label_template)


def test_allocate_fixed_no_change_min_and_proportional():
    px = {NO_CHANGE: 100_000, "yapilasma_olasi": 9000, "belirsiz": 1000, "bitki_kaybi": 500, "su_kaybi": 8}
    a = allocate(px, total=280, no_change_n=100, min_per=20)
    assert a[NO_CHANGE] == 100
    assert a["su_kaybi"] == 8                          # pikselden fazla verilmez
    assert a["bitki_kaybi"] >= 20 and a["belirsiz"] >= 20
    assert a["yapilasma_olasi"] > a["belirsiz"]        # kalan alanla orantılı
    assert sum(a.values()) == 280


def test_sample_pixels_reproducible_and_calibration_share():
    sm = np.full((50, 50), NO_CHANGE, dtype=object)
    sm[:10, :10] = "yapilasma_olasi"
    sm[45:, :] = ""
    alloc = {NO_CHANGE: 40, "yapilasma_olasi": 30}
    a = sample_pixels({"incek": sm}, alloc, seed=1, calibration_share=0.3)
    b = sample_pixels({"incek": sm}, alloc, seed=1, calibration_share=0.3)
    assert [(p["row"], p["col"]) for p in a] == [(p["row"], p["col"]) for p in b]
    assert len({(p["row"], p["col"]) for p in a}) == 70
    assert all(sm[p["row"], p["col"]] == p["tabaka"] for p in a)
    c = summary_counts(a)
    assert c["yapilasma_olasi"]["kalibrasyon"] == 9 and c[NO_CHANGE]["kalibrasyon"] == 12
    assert [p["nokta_id"] for p in a][:2] == ["P001", "P002"]


def test_label_template_protects_filled_labels(tmp_path):
    p = tmp_path / "labels.csv"
    pts = [{"nokta_id": "P001", "aoi": "incek"}, {"nokta_id": "P002", "aoi": "golbasi"}]
    write_label_template(pts, p)
    rows = read_labels(p)
    assert [r["nokta_id"] for r in rows] == ["P001", "P002"] and not filled_labels(rows)
    p.write_text("nokta_id,aoi,gercek_degisim,gercek_tur,gercek_yil,not\nP001,incek,evet,yapilasma_olasi,2021,\n",
                 encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_label_template(pts, p)
    write_label_template(pts, p, force=True)


def test_reference_class():
    assert reference_class({"nokta_id": "P1", "gercek_degisim": "hayir"}) == NO_CHANGE
    assert reference_class({"nokta_id": "P1", "gercek_degisim": "Evet", "gercek_tur": "su_kaybi"}) == "su_kaybi"
    with pytest.raises(ValueError):
        reference_class({"nokta_id": "P1", "gercek_degisim": "evet", "gercek_tur": ""})
    with pytest.raises(ValueError):
        reference_class({"nokta_id": "P1", "gercek_degisim": "belki"})


def test_metrics_confusion_false_alarm_and_year():
    Y, N = "yapilasma_olasi", NO_CHANGE
    recs = [
        {"ref": Y, "pred": Y, "pred_year": 2021, "ref_year": "2021"},
        {"ref": Y, "pred": Y, "pred_year": 2022, "ref_year": "2021"},
        {"ref": N, "pred": Y, "pred_year": 2022, "ref_year": None},   # yanlış alarm
        {"ref": Y, "pred": N, "pred_year": None, "ref_year": "2020"},   # kaçırılan
        {"ref": N, "pred": N, "pred_year": None, "ref_year": None},
    ]
    m = metrics(recs)
    assert m["genel_dogruluk"] == pytest.approx(3 / 5)
    assert m["yanlis_alarm_orani"] == pytest.approx(1 / 3)
    cm = m["sinif_metrikleri"][Y]
    assert cm["kullanici_dogrulugu"] == pytest.approx(2 / 3) and cm["uretici_dogrulugu"] == pytest.approx(2 / 3)
    assert m["yil"]["tam_isabet"] == pytest.approx(0.5) and m["yil"]["pm1_isabet"] == 1.0
    assert m["yil"]["tahmin_yilina_gore"][2022] == {"n": 2, "dogruluk": 0.5, "yanlis_alarm_orani": 0.5}
    assert m["siniflar"][-1] == N


def test_lookup_predictions_latest_year_wins():
    feats = {"incek": [(box(0, 0, 10, 10), {"tur": "belirsiz", "degisim_yili": 2019}),
                       (box(5, 5, 15, 15), {"tur": "yapilasma_olasi", "degisim_yili": 2023})]}
    pts = [{"aoi": "incek", "x": 2, "y": 2}, {"aoi": "incek", "x": 7, "y": 7}, {"aoi": "incek", "x": 50, "y": 50},
           {"aoi": "golbasi", "x": 2, "y": 2}]
    assert lookup_predictions(pts, feats) == [("belirsiz", 2019), ("yapilasma_olasi", 2023), (NO_CHANGE, None),
                                              (NO_CHANGE, None)]


def test_experiment_registry_and_status(tmp_path):
    assert set(EXPERIMENTS) == {"E1", "E2", "E3", "E4", "E5"}
    e2 = dict((v.name, v) for v in EXPERIMENTS["E2"][1])
    assert status(e2["yaz"], tmp_path, ["incek"]) == "eksik"
    f = tmp_path / "incek" / "change" / "summer" / "breakpoint" / "changes.geojson"
    f.parent.mkdir(parents=True)
    f.write_text("{}", encoding="utf-8")
    assert status(e2["yaz"], tmp_path, ["incek"]) == "hazır"
    e5 = dict((v.name, v) for v in EXPERIMENTS["E5"][1])
    assert status(e5["normalize"], tmp_path, ["incek"]) == "henüz uygulanmadı"


def test_allocate_min_only_for_large_strata():
    px = {NO_CHANGE: 100_000, "yapilasma_olasi": 9000, "su_kazanimi": 120, "bitki_kaybi": 2000}
    a = allocate(px, total=280, no_change_n=100, min_per=20, min_px_for_min=500)   # 20 ha = 500 px
    assert a["bitki_kaybi"] >= 20 and a["su_kazanimi"] < 20                     # küçük tabaka yalnızca orantılı
    assert sum(a.values()) == 280


def test_sample_pixels_polygon_cap_and_min_distance():
    sm = np.full((60, 60), NO_CHANGE, dtype=object)
    poly = np.zeros((60, 60), int)
    sm[0:10, 0:10] = "yapilasma_olasi"
    poly[0:10, 0:10] = 1                                   # tek poligon
    pts = sample_pixels({"incek": sm}, {"yapilasma_olasi": 10, NO_CHANGE: 30}, seed=3, calibration_share=0.3,
                        polygon_maps={"incek": poly}, max_per_polygon=3, min_dist_px=3)
    assert sum(p["tabaka"] == "yapilasma_olasi" for p in pts) == 3              # poligon başına ≤ 3
    xy = np.array([(p["row"], p["col"]) for p in pts])
    d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1)) + np.eye(len(xy)) * 99
    assert d.min() >= 3                                                           # ≥ 60 m


def test_olofsson_hand_computed():
    from changewatch.validate import olofsson

    Y, N = "yapilasma_olasi", NO_CHANGE
    recs = ([{"stratum": Y, "ref": Y}] * 3 + [{"stratum": Y, "ref": N}]
            + [{"stratum": N, "ref": N}] * 4 + [{"stratum": N, "ref": Y}])
    o = olofsson(recs, {Y: 10.0, N: 90.0})
    assert o["genel_dogruluk"] == pytest.approx(0.795)
    assert o["genel_dogruluk_ga"] == pytest.approx(1.96 * np.sqrt(0.033025), rel=1e-6)
    y = o["siniflar"][Y]
    assert y["kestirilen_alan_ha"] == pytest.approx(25.5)
    assert y["alan_ga_ha"] == pytest.approx(1.96 * 100 * np.sqrt(0.033025), abs=0.1)
    assert y["kullanici_dogrulugu"] == pytest.approx(0.75)
    assert y["uretici_dogrulugu"] == pytest.approx(0.075 / 0.255)
    assert o["siniflar"][N]["kestirilen_alan_ha"] == pytest.approx(74.5)


def test_olofsson_perfect_map_reproduces_map_areas():
    from changewatch.validate import olofsson

    recs = [{"stratum": "a", "ref": "a"}] * 5 + [{"stratum": NO_CHANGE, "ref": NO_CHANGE}] * 5
    o = olofsson(recs, {"a": 30.0, NO_CHANGE: 70.0})
    assert o["genel_dogruluk"] == 1.0 and o["genel_dogruluk_ga"] == 0.0
    assert o["siniflar"]["a"]["kestirilen_alan_ha"] == 30.0 and o["siniflar"]["a"]["alan_ga_ha"] == 0.0
