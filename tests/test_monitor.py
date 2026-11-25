"""monitor: dönemler, 429 yeniden deneme, kapsama, ön uyarı maskesi (ağsız)."""

from datetime import date

import numpy as np
import pytest

from changewatch.monitor import coverage, is_retryable, monitor_periods, robust_z, warning_mask, with_retry


def test_monitor_periods_last_three_full_months_and_previous_year():
    assert monitor_periods(date(2026, 11, 25), 3) == ((date(2026, 8, 1), date(2026, 10, 31)),
                                                      (date(2025, 8, 1), date(2025, 10, 31)))


def test_monitor_periods_wraps_year_and_handles_leap_day():
    cur, prev = monitor_periods(date(2025, 2, 3), 3)
    assert cur == (date(2024, 11, 1), date(2025, 1, 31))
    assert prev == (date(2023, 11, 1), date(2024, 1, 31))
    cur, prev = monitor_periods(date(2024, 3, 10), 1)                  # Şubat 2024: 29 gün
    assert cur == (date(2024, 2, 1), date(2024, 2, 29)) and prev[1] == date(2023, 2, 28)


def test_with_retry_backs_off_on_429_then_succeeds():
    calls, waits = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"

    assert with_retry(fn, tries=5, base_s=10, sleep=waits.append) == "ok"
    assert waits == [10, 20]


def test_with_retry_does_not_retry_permanent_errors_and_gives_up_after_tries():
    waits = []
    with pytest.raises(KeyError):
        with_retry(lambda: {}["x"], tries=5, base_s=1, sleep=waits.append)
    assert waits == []

    def always_503():
        raise OSError("503 Service Unavailable")

    with pytest.raises(OSError):
        with_retry(always_503, tries=3, base_s=1, sleep=waits.append)
    assert waits == [1, 2]
    assert is_retryable(TimeoutError("read timed out")) and not is_retryable(ValueError("bozuk"))


def test_coverage_counts_pixels_valid_in_both_periods_inside_aoi():
    region = np.zeros((4, 4), bool)
    region[:, :2] = True
    a = np.ones((4, 4), bool)
    b = np.ones((4, 4), bool)
    b[0, 0] = False
    assert coverage(a, b, region) == pytest.approx(7 / 8)
    assert coverage(a, b, np.zeros((4, 4), bool)) == 0.0


def test_warning_mask_needs_spectral_change_texture_gain_and_no_greening():
    rng = np.random.default_rng(0)
    region = np.ones((20, 20), bool)
    z = robust_z(rng.normal(size=(20, 20)), region)
    z_tex = robust_z(rng.normal(size=(20, 20)), region)
    d_ndvi = np.zeros((20, 20))
    z[0, 0], z_tex[0, 0] = 10, 10                  # yapılaşma benzeri: ikisi de
    z[1, 1], z_tex[1, 1] = 10, 0                   # yalnızca spektral (tarla sürümü)
    z[2, 2], z_tex[2, 2], d_ndvi[2, 2] = 10, 10, 0.4  # yeşillenme
    m = warning_mask(z, z_tex, d_ndvi, region, 3.0, 3.0, 0.1)
    assert m[0, 0] and not m[1, 1] and not m[2, 2]
    region[0, 0] = False
    assert not warning_mask(z, z_tex, d_ndvi, region, 3.0, 3.0, 0.1)[0, 0]


def test_robust_z_is_scale_free_and_nan_safe():
    x = np.array([[1.0, 2.0, 3.0, np.nan], [2.0, 2.0, 100.0, 2.0]])
    z = robust_z(x, np.ones_like(x, bool))
    assert z[1, 2] > 10 and np.isnan(z[0, 3])
    assert np.isnan(robust_z(x, np.zeros_like(x, bool))).all()
