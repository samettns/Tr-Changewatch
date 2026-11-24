"""breakpoint.py ve kırılma parçası sınıflandırması testleri (sentetik seriler)."""

import numpy as np
import pytest

from changewatch.breakpoint import (detect_breaks, mode_filter_years, noise_levels, segment_medians,
                                    segment_step)
from changewatch.classify import classify_break_piece
from changewatch.config import load_settings

S = load_settings()
YEARS = list(range(2017, 2027))


def _stack(seed=0):
    rng = np.random.default_rng(seed)
    T, F, H, W = 10, 6, 30, 30
    x = 0.20 + rng.normal(0, 0.006, (T, F, H, W))
    x[4:, :, 2:8, 2:8] += 0.08                       # A: 2021'de kalıcı basamak (yapılaşma gibi)
    sign = np.where(np.arange(T) % 2 == 0, 1.0, -1.0)
    x[:, :, 12:18, 12:18] += 0.07 * sign[:, None, None, None]  # B: her yıl değişen tarla (rotasyon)
    x[:, :, 22:28, 22:28] = 0.20 + rng.normal(0, 1e-5, (T, F, 6, 6))
    x[6:, :, 22:28, 22:28] += 0.004                  # C: çok sabit pikselde minik basamak
    x[9:, :, 2:8, 22:28] += 0.10                     # D: son yılda kırılma (izlemede)
    return x


def test_detects_persistent_step_with_correct_year():
    r = detect_breaks(_stack(), YEARS, S)
    assert r.candidate[2:8, 2:8].all()
    assert (r.year[2:8, 2:8] == 2021).all()
    assert (r.n_after[2:8, 2:8] == 6).all()


def test_rotating_field_not_detected():
    r = detect_breaks(_stack(), YEARS, S)
    assert not r.candidate[12:18, 12:18].any()


def test_noise_floor_prevents_score_explosion_on_very_stable_pixels():
    r = detect_breaks(_stack(), YEARS, S)
    assert np.nanmedian(r.spread[22:28, 22:28]) < 0.1 * r.noise   # bölge çok sabit…
    assert not r.candidate[22:28, 22:28].any()                     # …ama taban skoru patlatmıyor


def test_sigma_matches_pixel_noise_not_inflated_by_rotation():
    r = detect_breaks(_stack(), YEARS, S)
    # sentetik gürültü σ=0.006 → |sapma| medyanı ≈ 0.004; kırılma uydurması (her piksel sapmayı en aza
    # indiren b'yi seçer, 1 yıllık parçanın sapması 0) σ'yı biraz iyimser yapar (~0.0027).
    # Asıl kontrol: rotasyon bloğu (±0.07) σ'yı şişirmiyor.
    assert np.all((r.sigma > 0.002) & (r.sigma < 0.005))


def test_texture_only_step_needs_texture_in_vector():
    rng = np.random.default_rng(3)
    x = _stack()
    tex = 0.02 + rng.normal(0, 0.002, (10, 1, 30, 30))
    tex[5:, 0, 2:8, 12:18] += 0.03                   # yalnızca doku basamağı (2022), spektrum sabit
    with_tex = detect_breaks(np.concatenate([x, tex], axis=1), YEARS, S)
    without = detect_breaks(x, YEARS, S)
    assert with_tex.candidate[2:8, 12:18].all() and (with_tex.year[2:8, 12:18] == 2022).all()
    assert not without.candidate[2:8, 12:18].any()


def test_noise_levels_first_pass_and_errors():
    x = _stack()
    region = np.ones((30, 30), bool)
    assert noise_levels(x, None, region).shape == (6,)
    with pytest.raises(ValueError):
        noise_levels(np.zeros((10, 1, 3, 3)), None, np.ones((3, 3), bool))


def test_last_year_break_only_in_monitor_pass():
    x = _stack()
    main = detect_breaks(x, YEARS, S)                       # min_after = 2 (kalıcı katman)
    # Bilinen sınırlama: son yıl sıçraması b=2025'te yarım basamak gösterir (sonrası = {2025, 2026}
    # medyanı); birkaç piksel kalıcı katmanda 2025 kırılması olarak geçebilir (MMU tekilleri atar).
    assert main.candidate[2:8, 22:28].mean() < 0.2
    assert main.year.max() <= 2025
    mon = detect_breaks(x, YEARS, S, min_after=1)           # izleme geçişi
    assert mon.candidate[2:8, 22:28].all()
    assert (mon.year[2:8, 22:28] == 2026).all() and (mon.n_after[2:8, 22:28] == 1).all()


def test_component_signal_spectral_texture_both():
    rng = np.random.default_rng(5)
    x = _stack()                                            # A bloğu: yalnızca spektral basamak (2021)
    tex = 0.02 + rng.normal(0, 0.002, (10, 1, 30, 30))
    tex[5:, 0, 12:18, 2:8] += 0.03                          # yalnızca doku (2022)
    tex[4:, 0, 2:8, 2:8] += 0.03                            # A bloğuna doku da ekle → ikisi
    xs = x.copy()
    xs[5:, :, 22:28, 2:8] += 0.08                           # E: yalnızca spektral (2022)
    r = detect_breaks(np.concatenate([xs, tex], axis=1), YEARS, S, n_spec=6)
    assert (r.signal[2:8, 2:8] == 3).mean() > 0.9           # ikisi
    assert (r.signal[12:18, 2:8] == 2).mean() > 0.9         # doku
    assert (r.signal[22:28, 2:8] == 1).mean() > 0.9         # spektral


def test_background_mostly_clean():
    r = detect_breaks(_stack(), YEARS, S)
    bg = np.ones((30, 30), bool)
    for sl in [(slice(2, 8), slice(2, 8)), (slice(12, 18), slice(12, 18)), (slice(22, 28), slice(22, 28)),
               (slice(2, 8), slice(22, 28))]:
        bg[sl] = False
    assert r.candidate[bg].mean() < 0.02


def test_nan_years_tolerated():
    x = _stack()
    x[3, :, 2:8, 2:8] = np.nan                     # kırılma öncesi bir yıl eksik
    r = detect_breaks(x, YEARS, S)
    assert r.candidate[2:8, 2:8].all() and (r.year[2:8, 2:8] == 2021).all()


def test_segment_step_and_medians():
    s = np.zeros((10, 2, 2), "float32")
    s[4:] = 0.05
    idx = np.full((2, 2), 4, "int16")
    idx[1, 1] = -1
    st = segment_step(s, idx)
    assert st[0, 0] == pytest.approx(0.05) and np.isnan(st[1, 1])
    b, a = segment_medians(s, idx)
    assert b[0, 0] == 0 and a[0, 0] == pytest.approx(0.05)


def test_mode_filter_smooths_isolated_year():
    year = np.full((5, 5), 2020, "int16")
    year[2, 2] = 2023
    mask = np.ones((5, 5), bool)
    out = mode_filter_years(year, mask, 3)
    assert out[2, 2] == 2020 and (out[~mask] == 0).all()
    mask[0, 0] = False
    assert mode_filter_years(year, mask, 3)[0, 0] == 0


# --- tür / güven

TH = {"texture": 0.01, "ndvi": -0.08}


def _ev(**kw):
    ev = dict(mndwi_once=-0.4, mndwi_sonra=-0.35, doku_artisi=0.03, dNDVI=-0.05, sonrasi_yil_sayisi=5)
    ev.update(kw)
    return ev


@pytest.mark.parametrize("kw, tur, guven, durum", [
    ({}, "yapilasma_olasi", "yuksek", "kalici"),
    ({"sonrasi_yil_sayisi": 2}, "yapilasma_olasi", "orta", "kalici"),
    ({"sonrasi_yil_sayisi": 1}, "yapilasma_olasi", "dusuk", "izlemede"),
    ({"doku_artisi": 0.0, "dNDVI": -0.2}, "bitki_kaybi", "yuksek", "kalici"),
    ({"mndwi_sonra": 0.2}, "su_degisimi", "yuksek", "kalici"),
    ({"doku_artisi": 0.0, "dNDVI": 0.0}, "belirsiz", "dusuk", "kalici"),
])
def test_classify_break_piece(kw, tur, guven, durum):
    assert classify_break_piece(_ev(**kw), TH, S) == {"tur": tur, "guven": guven, "durum": durum}
