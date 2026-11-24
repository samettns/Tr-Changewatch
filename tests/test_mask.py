"""mask.py testleri."""

import numpy as np
import xarray as xr

from changewatch.config import load_settings
from changewatch.mask import apply_mask, valid_fraction, valid_mask

S = load_settings()


def test_masked_classes_match_spec():
    scl = np.arange(12)
    # spec: 0, 1, 3, 8, 9, 10, 11 maskelenir
    assert valid_mask(scl, S).tolist() == [False, False, True, False, True, True, True, True,
                                           False, False, False, False]


def test_apply_mask_sets_nan_and_drops_scl():
    ds = xr.Dataset({
        "B04": (("y", "x"), np.array([[100, 200], [300, 400]], dtype="uint16")),
        "SCL": (("y", "x"), np.array([[4, 9], [3, 5]], dtype="uint16")),
    })
    out = apply_mask(ds, S)
    assert "SCL" not in out and out["B04"].dtype == np.float32
    np.testing.assert_array_equal(np.isnan(out["B04"].values), [[False, True], [True, False]])
    assert out["valid"].values.tolist() == [[True, False], [False, True]]


def test_valid_fraction_inside_aoi_only():
    valid = np.array([[True, False], [False, False]])
    aoi = np.array([[True, True], [False, False]])
    assert valid_fraction(valid, aoi) == 0.5
    assert valid_fraction(valid) == 0.25
    assert valid_fraction(valid, np.zeros_like(valid)) == 0.0


def test_nan_scl_or_band_is_invalid():
    """Kare ayak izi dışında float dosyada SCL ve bantlar NaN gelebilir (Gölbaşı 36SVJ)."""
    ds = xr.Dataset({
        "B04": (("y", "x"), np.array([[100.0, np.nan], [300.0, 400.0]], dtype="float32")),
        "SCL": (("y", "x"), np.array([[4.0, 4.0], [np.nan, 5.0]], dtype="float32")),
    })
    out = apply_mask(ds, S)
    assert out["valid"].values.tolist() == [[True, False], [False, True]]
    assert not valid_mask(np.array([np.nan]), S)[0]
