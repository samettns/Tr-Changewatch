"""water.py testleri (sentetik MNDWI/NDVI serileri)."""

import numpy as np
import pytest

from changewatch.breakpoint import detect_breaks
from changewatch.config import load_settings
from changewatch.water import (classify_water_piece, raw_water, segment_water_state, shoreline,
                               shoreline_at_break, water_area_series, water_bodies, wetland_pixels)

S = load_settings()
YEARS = list(range(2017, 2027))


def _mndwi(seed=0):
    rng = np.random.default_rng(seed)
    T, H, W = 10, 40, 40
    m = -0.4 + rng.normal(0, 0.03, (T, H, W))                       # kara
    m[:, 0:15, :] = 0.5 + rng.normal(0, 0.03, (T, 15, W))           # göl (15 × 40 = 600 px = 24 ha)
    m[4:, 15:17, 0:20] = 0.5 + rng.normal(0, 0.03, (6, 2, 20))      # 2021'den itibaren kıyıda su kazanımı
    m[5:, 0:2, 30:40] = -0.4 + rng.normal(0, 0.03, (5, 2, 10))      # 2022'den itibaren kıyıda su kaybı
    m[4:, 6:9, 10:20] = -0.05 + rng.normal(0, 0.01, (6, 3, 10))     # göl içinde renk değişimi (kıyıdan uzak)
    m[:, 30:32, 30:32] = 0.4                                         # çatı/sera: küçük parça (4 px)
    return m


def test_water_bodies_drop_small_patches():
    raw, valid = raw_water(_mndwi(), 0.0)
    body = water_bodies(raw, min_px=125, connectivity=2)            # 5 ha = 125 px
    assert raw[:, 30:32, 30:32].all() and not body[:, 30:32, 30:32].any()
    assert body[0, 5, 5]


def test_shoreline_band():
    b = np.zeros((20, 20), bool)
    b[:10] = True
    sh = shoreline(b, 3)
    assert sh[7:13, 5].all() and not sh[3, 5] and not sh[16, 5]


def test_area_series_old_vs_new():
    raw, valid = raw_water(_mndwi(), 0.0)
    body = water_bodies(raw, 125, 2)
    reg = np.ones((40, 40), bool)
    old, new = water_area_series(raw, valid, reg, 0.04), water_area_series(body, valid, reg, 0.04)
    assert old[0]["su_ha"] - new[0]["su_ha"] == pytest.approx(4 * 0.04, abs=0.1)    # çatı farkı (0,1 ha yuvarlama)


def test_gain_loss_on_shore_but_not_lake_interior():
    m = _mndwi()
    raw, valid = raw_water(m, 0.0)
    body = water_bodies(raw, 125, 2)
    shore = shoreline(body, 3)
    r = detect_breaks(m[:, None], YEARS, S, np.ones((40, 40), bool), n_spec=1, min_after=2)
    before, after = segment_water_state(body, valid, r.index, 0.5)
    gain, loss = ~before & after, before & ~after
    cand = r.candidate & (gain | loss) & shoreline_at_break(shore, r.index)
    assert (cand & gain)[15:17, 0:20].all() and (r.year[15:17, 0:20] == 2021).all()
    assert (cand & loss)[0:2, 30:40].all() and (r.year[0:2, 30:40] == 2022).all()
    assert not cand[6:9, 10:20].any()                                # göl içi renk değişimi kazanım/kayıp değil
    assert not cand[25:40, :].any() and not cand[30:32, 30:32].any()


def test_wetland_pixels():
    nd_b = np.array([0.5, 0.5, 0.1])
    mn_b = np.array([0.05, 0.40, 0.05])
    z = np.zeros(3)
    assert wetland_pixels(nd_b, z, mn_b, z - 1, 0.0, S).tolist() == [True, False, False]


@pytest.mark.parametrize("g, l, w, n, expected", [
    (0.9, 0.0, 0.1, 5, ("su_kazanimi", "yuksek", "kalici")),
    (0.0, 0.8, 0.0, 2, ("su_kaybi", "orta", "kalici")),
    (0.9, 0.0, 0.7, 5, ("sulak_alan_belirsiz", "dusuk", "kalici")),
    (0.9, 0.0, 0.0, 1, ("su_kazanimi", "dusuk", "izlemede")),
])
def test_classify_water_piece(g, l, w, n, expected):
    r = classify_water_piece(g, l, w, n, S)
    assert (r["tur"], r["guven"], r["durum"]) == expected
