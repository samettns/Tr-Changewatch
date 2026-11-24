"""indices.py testleri (sentetik diziler)."""

import numpy as np
import pytest
import xarray as xr

from changewatch.config import load_settings
from changewatch.indices import block_mean, local_std, normalized_difference, spectral_indices, texture

S = load_settings()


def test_normalized_difference_and_zero_denominator():
    out = normalized_difference(np.array([3000, 0]), np.array([1000, 0]))
    assert out[0] == pytest.approx(0.5) and np.isnan(out[1])


def test_spectral_indices_known_values():
    v = {"B02": 1000, "B03": 1500, "B04": 1000, "B08": 3000, "B11": 2000}
    comp = xr.Dataset({k: (("y", "x"), np.full((1, 1), val, "float32")) for k, val in v.items()},
                      coords={"y": [0.0], "x": [0.0]})
    ix = spectral_indices(comp)
    assert ix["NDVI"].item() == pytest.approx((3000 - 1000) / 4000)
    assert ix["NDBI"].item() == pytest.approx((2000 - 3000) / 5000)
    assert ix["MNDWI"].item() == pytest.approx((1500 - 2000) / 3500)
    assert ix["BSI"].item() == pytest.approx((3000 - 4000) / 7000)


def test_local_std_constant_is_zero_and_checkerboard_positive():
    assert np.nanmax(local_std(np.full((6, 6), 0.2), 3, 0.5)) == pytest.approx(0, abs=1e-6)
    cb = (np.indices((6, 6)).sum(0) % 2).astype(float)  # 0/1 dama tahtası
    assert local_std(cb, 3, 0.5)[2:4, 2:4].min() > 0.45


def test_local_std_nan_handling():
    a = np.full((5, 5), 0.1)
    a[2, 2] = np.nan
    out = local_std(a, 3, 0.5)
    assert np.isnan(out[2, 2])            # geçersiz piksel geçersiz kalır
    assert out[1, 1] == pytest.approx(0)  # komşusundaki NaN sonucu bozmaz


def test_block_mean_shape_and_nan():
    a = np.arange(16, dtype=float).reshape(4, 4)
    a[0, 0] = np.nan
    out = block_mean(a, 2)
    assert out.shape == (2, 2)
    assert out[0, 0] == pytest.approx((1 + 4 + 5) / 3)
    with pytest.raises(ValueError):
        block_mean(np.zeros((3, 4)), 2)


def test_texture_returns_work_grid():
    rng = np.random.default_rng(0)
    out = texture(rng.random((8, 10)).astype("float32"), S, work_res_m=20)
    assert out.shape == (4, 5)


def test_local_std_strict_excludes_windows_with_masked_pixel():
    a = np.full((7, 7), 0.1)
    a[3, 3] = np.nan
    out = local_std(a, 3, 1.0)
    assert np.isnan(out[2:5, 2:5]).all()       # NaN'ı içeren tüm 3x3 pencereler dışlandı
    assert out[0, 0] == pytest.approx(0)       # uzaktaki pencereler geçerli


def test_per_scene_texture_median_avoids_mixing_edges():
    """Kompozit üzerinde std, komşu pikseller farklı sahnelerden gelince sahte kenar üretir;
    sahne bazında std + medyan üretmez."""
    from changewatch.composite import median_composite

    h, w = 8, 8
    scenes, b08s = [], []
    for level, masked_half in ((0.10, "right"), (0.30, "left"), (0.10, "right"), (0.30, "left"),
                               (0.20, None)):
        a = np.full((h, w), level)
        if masked_half == "right":
            a[:, w // 2:] = np.nan
        elif masked_half == "left":
            a[:, : w // 2] = np.nan
        b08s.append(a)
    # eski yöntem: önce medyan kompozit, sonra std → ortada sahte kenar
    stack = np.stack(b08s)
    old = texture(np.nanmedian(stack, axis=0), S, work_res_m=20)
    # yeni yöntem: sahne bazında std, sonra medyan
    for a in b08s:
        t = texture(a, S, work_res_m=20)
        scenes.append(xr.Dataset({"TEXTURE": (("y", "x"), t), "valid": (("y", "x"), ~np.isnan(t))},
                                 coords={"y": np.arange(h // 2), "x": np.arange(w // 2)}))
    new = median_composite(scenes, S)["TEXTURE"].values
    assert np.nanmax(old) > 0.04                       # yapay kenar
    assert np.nanmax(new) == pytest.approx(0, abs=1e-6)  # homojen yüzey: doku yok
