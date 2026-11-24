"""harmonize.py testleri: baseline'a göre karar ve alan yoksa tarihe göre yedek karar."""

import logging
from datetime import date, datetime, timezone

import numpy as np
import xarray as xr

from changewatch.config import load_settings
from changewatch.harmonize import apply_offset, harmonize_scene, needs_offset

S = load_settings()


def _scene(pb: str, acquired: str) -> xr.Dataset:
    b = np.array([[0, 800, 1000], [1500, 2773, 11000]], dtype="uint16")
    ds = xr.Dataset({"B04": (("y", "x"), b), "SCL": (("y", "x"), np.full_like(b, 4))})
    ds.attrs.update(processing_baseline=pb, acquired=acquired)
    return ds


# --- 1) baseline alanına göre karar

def test_baseline_decides_offset():
    t = datetime(2018, 7, 1, tzinfo=timezone.utc)  # tarih bilerek eski: karar baseline'dan gelmeli
    assert needs_offset("04.00", t, S)
    assert needs_offset("05.10", t, S)
    assert not needs_offset("03.00", datetime(2023, 7, 1), S)
    assert not needs_offset("02.12", datetime(2023, 7, 1), S)


def test_baseline_scene_offset_applied_and_scl_untouched():
    out = harmonize_scene(_scene("05.11", "2024-07-05T08:36:09+00:00"), S)
    np.testing.assert_array_equal(out["B04"].values, [[0, 0, 0], [500, 1773, 10000]])
    np.testing.assert_array_equal(out["SCL"].values, 4)
    assert out["B04"].dtype == np.uint16


def test_old_baseline_scene_unchanged():
    src = _scene("02.12", "2017-07-06T08:36:01+00:00")
    np.testing.assert_array_equal(harmonize_scene(src, S)["B04"].values, src["B04"].values)


# --- 2) baseline yoksa tarihe göre karar + log uyarısı

def test_missing_baseline_falls_back_to_date_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="changewatch.harmonize"):
        assert needs_offset(None, date(2022, 1, 25), S)        # kesme günü dahil
        assert not needs_offset(None, date(2022, 1, 24), S)
        assert needs_offset("", datetime(2023, 8, 1, tzinfo=timezone.utc), S)
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 3 and all("processing_baseline yok" in r.message for r in warns)


def test_missing_baseline_scene_harmonized_by_date(caplog):
    with caplog.at_level(logging.WARNING, logger="changewatch.harmonize"):
        new = harmonize_scene(_scene("", "2022-08-01T08:36:00+00:00"), S)
        old = harmonize_scene(_scene("", "2021-08-01T08:36:00+00:00"), S)
    assert new["B04"].values[1, 0] == 500
    assert old["B04"].values[1, 0] == 1500
    assert any("tarihe göre" in r.message for r in caplog.records)


def test_apply_offset_clips_at_zero():
    out = apply_offset(_scene("05.10", "2024-01-01T00:00:00"), S)
    assert out["B04"].values.min() == 0
