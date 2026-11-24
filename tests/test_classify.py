"""classify.py ve vectorize.py testleri (sentetik)."""

import copy
import json

import numpy as np
import pytest
from affine import Affine

from changewatch.classify import classify_piece, pixel_persistence, piece_evidence, signal_source
from changewatch.config import load_settings
from changewatch.vectorize import label_pieces, piece_geometries, write_geojson

S = load_settings()


# --- kalıcılık

def test_persistence_rejects_fallow_reversal_keeps_construction():
    cva_flag = np.array([True, True, False])
    tex_flag = np.array([False, False, True])
    dtex_ab = np.array([0.0, 0.0, 0.05])
    # 0: tarla nadas → y+1'de eski hâline döndü (CVA küçük); 1: kalıcı spektral değişim;
    # 2: doku artışı y+1'de de aynı yönde
    cva_an = np.array([0.02, 0.30, 0.0])
    dtex_an = np.array([0.0, 0.0, 0.06])
    out = pixel_persistence(cva_flag, tex_flag, dtex_ab, cva_an, dtex_an, 0.15, 0.025)
    assert out.tolist() == [False, True, True]


def test_persistence_texture_sign_must_agree_and_nan_is_false():
    out = pixel_persistence(np.array([False, True]), np.array([True, False]), np.array([0.05, 0.0]),
                            np.array([0.0, np.nan]), np.array([-0.06, 0.0]), 0.15, 0.025)
    assert out.tolist() == [False, False]


def test_signal_source():
    assert signal_source(0.9, 0.5, 0.2) == "ikisi"
    assert signal_source(0.9, 0.1, 0.2) == "cva"
    assert signal_source(0.05, 0.6, 0.2) == "doku"
    assert signal_source(0.1, 0.15, 0.2) == "doku"


# --- tür / güven

def _ev(**kw):
    ev = dict(kalici_mi=True, mndwi_sonra=-0.4, mndwi_sonraki=-0.4, doku_artisi_payi=0.8,
              dNDVI=-0.05, dNDVI_sonraki=-0.05)
    ev.update(kw)
    return ev


def test_construction_persistent_is_high_confidence():
    assert classify_piece(_ev(), S) == {"tur": "yapilasma_olasi", "guven": "yuksek", "durum": "kalici"}


def test_last_year_is_monitoring_medium_confidence():
    r = classify_piece(_ev(kalici_mi=None, mndwi_sonraki=None, dNDVI_sonraki=None), S)
    assert r == {"tur": "yapilasma_olasi", "guven": "orta", "durum": "izlemede"}


def test_non_persistent_dropped_or_kept_as_temporary():
    assert classify_piece(_ev(kalici_mi=False), S) is None
    s = copy.deepcopy(S)
    s["classify"]["drop_non_persistent"] = False
    assert classify_piece(_ev(kalici_mi=False), s)["durum"] == "gecici"


def test_water_requires_next_year_above_threshold():
    assert classify_piece(_ev(mndwi_sonra=0.2, mndwi_sonraki=0.3), S)["tur"] == "su_degisimi"
    # sonraki yılda su yok → su sayılmaz; doku artışı varsa da su olduğu için yapılaşma değil
    assert classify_piece(_ev(mndwi_sonra=0.2, mndwi_sonraki=-0.3), S)["tur"] == "belirsiz"


def test_vegetation_loss_needs_persistent_ndvi_drop_and_no_texture_increase():
    ev = _ev(doku_artisi_payi=0.1, dNDVI=-0.25, dNDVI_sonraki=-0.2)
    assert classify_piece(ev, S) == {"tur": "bitki_kaybi", "guven": "yuksek", "durum": "kalici"}
    assert classify_piece(_ev(doku_artisi_payi=0.1, dNDVI=-0.25, dNDVI_sonraki=0.0), S)["tur"] == "belirsiz"


def test_ndbi_is_not_a_condition():
    # NDBI düşse de (İncek bulgusu) doku artışı + kalıcılık yapılaşma için yeterli
    assert classify_piece(_ev(dNDBI=-0.04), S)["tur"] == "yapilasma_olasi"


def test_undetermined_is_low_confidence():
    r = classify_piece(_ev(doku_artisi_payi=0.1, dNDVI=0.0), S)
    assert r == {"tur": "belirsiz", "guven": "dusuk", "durum": "kalici"}


# --- kanıt alanları

def test_piece_evidence_fields():
    sel = np.array([[True, True], [True, False]])
    one = np.ones((2, 2), "float32")
    layers = {
        "cva_flag": np.array([[1, 1, ], [0, 0]], bool), "texture_flag": np.array([[0, 1], [1, 0]], bool),
        "dtex_signed": np.array([[0.05, 0.05], [0.0, 0.0]], "float32"),
        "dNDVI": -0.1 * one, "dNDBI": -0.04 * one, "dBSI": -0.03 * one, "dMNDWI": 0.1 * one,
        "MNDWI_b": -0.3 * one, "valid_obs_b": 12 * one, "valid_obs_a": np.array([[2, 14], [14, 0]], "float32"),
        "persistent": np.array([[1, 1], [0, 0]], bool), "MNDWI_next": -0.3 * one, "dNDVI_next": -0.1 * one,
    }
    ev = piece_evidence(sel, layers, {"texture": 0.025}, S)
    assert ev["piksel"] == 3 and ev["sinyal"] == "ikisi"
    assert ev["doku_artisi_payi"] == pytest.approx(0.667, abs=1e-3)
    assert ev["kalici_mi"] is True and ev["kalicilik_payi"] == pytest.approx(0.667, abs=1e-3)
    assert ev["dusuk_gozlem"] == {"ort_gozlem": 10.0, "dusuk_piksel_orani": pytest.approx(0.333, abs=1e-3)}
    assert ev["dNDBI"] == pytest.approx(-0.04)


# --- vektörleştirme

def test_label_and_geojson(tmp_path):
    m = np.zeros((10, 10), bool)
    m[1:4, 1:4] = True
    m[6:9, 6:9] = True
    m[4, 4] = True  # köşegenle 1. parçaya bağlı (8-komşuluk)
    labels, n = label_pieces(m, 2)
    assert n == 2
    t = Affine(20, 0, 500_000, 0, -20, 4_400_000)
    geoms = piece_geometries(labels, t, "EPSG:32636", 2)
    assert set(geoms) == {1, 2}
    lon, lat = geoms[2].centroid.coords[0]
    assert 32 < lon < 34 and 39 < lat < 40.5
    p = write_geojson([(geoms[1], {"tur": "belirsiz", "x": np.float32(np.nan), "k": np.bool_(True)})],
                      tmp_path / "c.geojson")
    fc = json.loads(p.read_text(encoding="utf-8"))
    assert fc["features"][0]["properties"] == {"tur": "belirsiz", "x": None, "k": True}
