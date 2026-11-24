"""water.py testleri (sentetik MNDWI/NDVI serileri)."""

import copy

import numpy as np
import pytest

from changewatch.breakpoint import detect_breaks
from changewatch.config import load_settings
from changewatch.water import (annual_thresholds, classify_water_piece, segment_water_state, water_area_series,
                               water_masks, wetland_pixels)

S = load_settings()
YEARS = list(range(2017, 2027))


def _mndwi(seed=0, lake_shift=0.0):
    rng = np.random.default_rng(seed)
    T, H, W = 10, 30, 30
    m = -0.4 + rng.normal(0, 0.03, (T, H, W))          # kara
    m[:, 0:12, :] = 0.5 + rng.normal(0, 0.03, (T, 12, W)) + lake_shift   # göl
    m[4:, 12:16, 0:10] = 0.5 + rng.normal(0, 0.03, (6, 4, 10))          # 2021'den itibaren su kazanımı
    m[5:, 0:4, 20:30] = -0.4 + rng.normal(0, 0.03, (5, 4, 10))          # 2022'den itibaren su kaybı
    return m


def test_otsu_thresholds_stable_used_per_year():
    m = _mndwi()
    th = annual_thresholds(m, np.ones((30, 30), bool), S)
    assert th.mode == "otsu" and th.otsu_range < 0.15
    # Otsu iki tepeyi ayırır; tepeler çok iyi ayrık olduğunda plato oluşur ve eşik kara tepesine yakın düşer
    # Bilinen davranış: skimage platodaki İLK maksimumu seçer → eşik kara tepesinin kenarına düşer ve
    # bin yuvarlamasıyla karanın en uç birkaç pikseli su sayılabilir (karar listesinde).
    for t, v in enumerate(th.used):
        land = np.concatenate([m[t, 16:, :].ravel(), m[t, 12:16, 10:].ravel()])
        assert (land > v).mean() < 0.01 and (m[t, 4:12, :] > v).all()


def test_unstable_thresholds_fall_back_to_fixed():
    m = _mndwi()
    m[3] += 0.6                                         # bir yıl tümüyle kaymış (ör. radyometrik sorun)
    th = annual_thresholds(m, np.ones((30, 30), bool), S)
    assert th.mode == "sabit" and th.used == [0.0] * 10 and th.otsu_range > 0.15


def test_water_masks_and_area_series():
    m = _mndwi()
    m[0, 29, 29] = np.nan
    water, valid = water_masks(m, [0.0] * 10)
    assert not valid[0, 29, 29] and not water[0, 29, 29]
    s = water_area_series(water, valid, np.ones((30, 30), bool), 0.04)
    assert s[0]["su_ha"] == pytest.approx(12 * 30 * 0.04)                     # yalnızca göl
    assert s[-1]["su_ha"] == pytest.approx((12 * 30 + 4 * 10 - 4 * 10) * 0.04)  # kazanım ve kayıp dengede


def test_breaks_on_mndwi_give_gain_and_loss():
    m = _mndwi()
    water, valid = water_masks(m, [0.0] * 10)
    r = detect_breaks(m[:, None], YEARS, S, np.ones((30, 30), bool), n_spec=1, min_after=2)
    before, after = segment_water_state(water, valid, r.index, 0.5)
    gain, loss = ~before & after, before & ~after
    cand = r.candidate & (gain | loss)                  # su katmanı: kırılma + su durumu değişimi
    assert (cand & gain)[12:16, 0:10].all() and (r.year[12:16, 0:10] == 2021).all()
    assert (cand & loss)[0:4, 20:30].all() and (r.year[0:4, 20:30] == 2022).all()
    # Tek değişkende gürültü kuyruğu ağır: kırılma adayı tek başına sabit piksellerin bir kısmını işaretler,
    # özgüllüğü su durumu değişimi sağlar.
    assert not cand[4:12, :].any()                      # sabit göl
    assert not cand[20:30, 12:30].any()                 # sabit kara


def test_wetland_pixels():
    nd_b = np.array([0.5, 0.5, 0.1])
    mn_b = np.array([0.05, 0.40, 0.05])
    z = np.zeros(3)
    out = wetland_pixels(nd_b, z, mn_b, z - 1, 0.0, S)
    assert out.tolist() == [True, False, False]         # yeşil + eşiğe yakın → sazlık; açık su / çıplak değil


@pytest.mark.parametrize("g, l, w, n, tur, guven", [
    (0.9, 0.0, 0.1, 5, "su_kazanimi", "yuksek"),
    (0.0, 0.8, 0.0, 2, "su_kaybi", "orta"),
    (0.9, 0.0, 0.7, 5, "sulak_alan_belirsiz", "dusuk"),
])
def test_classify_water_piece(g, l, w, n, tur, guven):
    assert classify_water_piece(g, l, w, n, S) == {"tur": tur, "guven": guven, "durum": "kalici"}
