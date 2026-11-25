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
    from changewatch.experiments import read_predictions, unique_variants, write_predictions

    assert set(EXPERIMENTS) == {"E1", "E2", "E3", "E4", "E5"}
    e2 = dict((v.name, v) for v in EXPERIMENTS["E2"][1])
    assert status(e2["yaz"], tmp_path, ["incek"]) == "eksik"
    f = tmp_path / "incek" / "change" / "summer" / "breakpoint" / "changes.geojson"
    f.parent.mkdir(parents=True)
    f.write_text("{}", encoding="utf-8")
    assert status(e2["yaz"], tmp_path, ["incek"]) == "hazır"
    # aynı çıktıyı paylaşan varyantlar bir kez üretilir; ilkbahar --build kapsamında değil
    u = unique_variants()
    assert ("summer", "breakpoint") in u and ("spring", "breakpoint") not in u
    assert len(u) == 7
    p = write_predictions([{"nokta_id": "P001", "aoi": "incek", "deney": "E1", "varyant": "kirilma",
                            "tahmin_tur": "degisim_yok", "tahmin_yil": ""}], tmp_path / "p.csv")
    assert read_predictions(p) == {("E1", "kirilma"): {"P001": ("degisim_yok", None)}}


def test_ndbi_built_rule():
    from changewatch.classify import classify_break_piece
    from changewatch.config import load_settings

    s = load_settings()
    ev = dict(mndwi_once=-0.4, mndwi_sonra=-0.35, doku_artisi=0.03, dNDVI=-0.05, dNDBI=-0.04, dBSI=-0.03,
              sonrasi_yil_sayisi=5)
    th = {"texture": 0.01, "ndvi": -0.08}
    assert classify_break_piece(ev, th, s)["tur"] == "yapilasma_olasi"            # doku kuralı
    assert classify_break_piece(ev, th, s, built_rule="ndbi")["tur"] == "belirsiz"  # NDBI düşüyor (İncek bulgusu)
    ev2 = {**ev, "dNDBI": 0.05, "dBSI": 0.04, "doku_artisi": 0.0}
    assert classify_break_piece(ev2, th, s, built_rule="ndbi")["tur"] == "yapilasma_olasi"


# ---------------------------------------------------------------- Faz 3 raporlama

from changewatch.validate import (binary_metrics, error_kind, error_summary, olofsson,  # noqa: E402
                                  rank_disagreements, water_census)


def _rec(i, ref, pred, stratum, area, aoi="a"):
    return {"nokta_id": f"P{i:03d}", "ref": ref, "pred": pred, "stratum": stratum, "stratum_area_ha": area,
            "aoi": aoi}


def test_olofsson_single_point_stratum_does_not_crash_and_is_flagged():
    recs = [_rec(1, NO_CHANGE, NO_CHANGE, NO_CHANGE, 900), _rec(2, "yapilasma_olasi", NO_CHANGE, NO_CHANGE, 900),
            _rec(3, "yapilasma_olasi", "yapilasma_olasi", "yapilasma_olasi", 90),
            _rec(4, NO_CHANGE, "yapilasma_olasi", "yapilasma_olasi", 90),
            _rec(5, NO_CHANGE, "su_kazanimi", "su_kazanimi", 10)]
    o = olofsson(recs, {NO_CHANGE: 900, "yapilasma_olasi": 90, "su_kazanimi": 10})
    assert o["varyans_disi_tabakalar"] == {"su_kazanimi": 1}
    assert o["genel_dogruluk_ga"] is not None
    assert o["siniflar"]["su_kazanimi"]["kullanici_ga"] is None
    # yapılaşma alanı: 900·½ + 90·½ = 495 ha
    assert o["siniflar"]["yapilasma_olasi"]["kestirilen_alan_ha"] == pytest.approx(495, abs=0.1)


def test_binary_metrics_counts_any_change_type_as_change():
    recs = [{"ref": "yapilasma_olasi", "pred": "belirsiz"}, {"ref": "diger", "pred": NO_CHANGE},
            {"ref": NO_CHANGE, "pred": "bitki_kaybi"}, {"ref": NO_CHANGE, "pred": NO_CHANGE}]
    b = binary_metrics(recs)
    assert b["karisiklik"] == [[1, 1], [1, 1]]
    assert b["kesinlik"] == 0.5 and b["duyarlilik"] == 0.5 and b["dogruluk"] == 0.5
    assert "ikili" in metrics([{**r, "ref_year": None, "pred_year": None} for r in recs])


def test_water_census_counts_per_type_and_unsure():
    pts = [{"nokta_id": "S1", "tahmin_tur": "su_kazanimi", "alan_ha": 0.5},
           {"nokta_id": "S2", "tahmin_tur": "su_kazanimi", "alan_ha": 0.3},
           {"nokta_id": "S3", "tahmin_tur": "su_kaybi", "alan_ha": 0.2}]
    lab = [{"nokta_id": "S1", "gercek_degisim": "evet", "gercek_tur": "su_kazanimi"},
           {"nokta_id": "S2", "gercek_degisim": "hayir", "gercek_tur": ""},
           {"nokta_id": "S3", "gercek_degisim": "emin_degilim", "gercek_tur": ""}]
    c = water_census(pts, lab)
    assert c["turler"]["su_kazanimi"]["etiketli"] == 2 and c["turler"]["su_kazanimi"]["dogru"] == 1
    assert c["turler"]["su_kazanimi"]["degisim_yok"] == 1
    assert c["turler"]["su_kaybi"]["emin_degilim"] == 1 and c["turler"]["su_kaybi"].get("etiketli", 0) == 0
    assert c["toplam"]["poligon"] == 3


def test_error_kind_and_summary():
    assert error_kind(NO_CHANGE, "belirsiz") == "yanlis_alarm"
    assert error_kind("yapilasma_olasi", NO_CHANGE) == "kacirma"
    assert error_kind("diger", "yapilasma_olasi") == "tur_hatasi"
    recs = [_rec(1, NO_CHANGE, "belirsiz", "belirsiz", 10), _rec(2, NO_CHANGE, "belirsiz", "belirsiz", 10),
            _rec(3, "x", "x", "x", 1)]
    assert error_summary(recs) == [("yanlis_alarm", NO_CHANGE, "belirsiz", 2)]


def test_rank_disagreements_one_per_binary_group_then_by_represented_area():
    recs = ([_rec(i, "yapilasma_olasi", NO_CHANGE, NO_CHANGE, 1000, aoi="ab"[i % 2]) for i in range(5)]
            + [_rec(10 + i, NO_CHANGE, NO_CHANGE, NO_CHANGE, 1000) for i in range(5)]          # kaçırma 100 ha/nokta
            + [_rec(20 + i, NO_CHANGE, "bitki_kaybi", "bitki_kaybi", 20) for i in range(4)]  # yanlış alarm 5 ha
            + [_rec(30, "diger", "yapilasma_olasi", "yapilasma_olasi", 50)])                 # tür hatası
    top = rank_disagreements(recs, 4)
    kinds = [r["hata"] for r in top]
    assert kinds.count("yanlis_alarm") == 1                 # her ikili grup en az bir
    assert kinds.count("kacirma") == 3                      # kalan yerler temsil edilen alana göre
    assert "tur_hatasi" not in kinds                        # ikili hatalar tükenmeden gelmez
    assert {r["aoi"] for r in top if r["hata"] == "kacirma"} == {"a", "b"}   # eşit ağırlıkta AOI'ler sırayla
    assert len(rank_disagreements(recs, 50)) == 10          # tüm ayrışmalar
