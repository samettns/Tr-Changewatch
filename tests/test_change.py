"""change.py ve morphology.py testleri (sentetik diziler)."""

import copy

import numpy as np
import pytest
import xarray as xr

from changewatch.change import change_candidates, cva_magnitude, otsu_threshold
from changewatch.config import load_settings
from changewatch.morphology import apply_mmu, clean_mask, mmu_pixels, open_close

S = load_settings()
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]


def _comp(val: np.ndarray) -> xr.Dataset:
    return xr.Dataset({b: (("y", "x"), val.astype("float32")) for b in BANDS})


def test_cva_magnitude():
    a, b = _comp(np.zeros((1, 1))), _comp(np.full((1, 1), 1000.0))
    # 6 bantta 0,1 yansıtım farkı → sqrt(6 * 0,01)
    assert cva_magnitude(a, b, BANDS, 10000)[0, 0] == pytest.approx(np.sqrt(0.06))


def test_otsu_separates_bimodal_and_ignores_nan():
    v = np.concatenate([np.full(900, 0.02), np.full(100, 0.30), [np.nan] * 5])
    t = otsu_threshold(v)
    assert 0.02 < t < 0.30
    assert otsu_threshold(np.full(10, 0.1)) == float("inf")   # değişim yok → aday yok
    with pytest.raises(ValueError):
        otsu_threshold(np.full(10, np.nan))


def _scene_pair():
    rng = np.random.default_rng(1)
    base = rng.normal(2000, 20, (40, 40))
    after = base.copy()
    after[5:15, 5:15] += 1500          # spektral değişim bloğu
    tex_a = rng.normal(0.01, 0.001, (40, 40))
    tex_b = tex_a.copy()
    tex_b[25:35, 25:35] += 0.05        # yalnızca doku değişimi bloğu
    return _comp(base), _comp(after), tex_a, tex_b


def test_candidates_or_combines_both_signals():
    a, b, ta, tb = _scene_pair()
    c = change_candidates(a, b, ta, tb, S)
    assert c.cva_flag[5:15, 5:15].all() and c.texture_flag[25:35, 25:35].all()
    assert c.mask[5:15, 5:15].all() and c.mask[25:35, 25:35].all()
    assert c.mask.sum() == 200


def test_candidates_and_and_region():
    a, b, ta, tb = _scene_pair()
    s = copy.deepcopy(S)
    s["change"]["combine"] = "and"
    assert change_candidates(a, b, ta, tb, s).mask.sum() == 0
    region = np.zeros((40, 40), bool)
    region[:20] = True
    assert change_candidates(a, b, ta, tb, S, region).mask[20:].sum() == 0


def test_nan_is_never_candidate():
    a, b, ta, tb = _scene_pair()
    tb[0, 0] = np.nan
    b["B04"].values[1, 1] = np.nan
    c = change_candidates(a, b, ta, tb, S)
    assert not c.mask[0, 0] and not c.mask[1, 1]


def test_mmu_pixels_matches_spec():
    assert mmu_pixels(S) == 13  # 0,5 ha / 400 m² = 12,5 → 13


def test_apply_mmu_keeps_13_drops_12():
    m = np.zeros((20, 20), bool)
    m[0, 0:13] = True      # 13 piksel: kalır
    m[5, 0:12] = True      # 12 piksel: atılır
    out = apply_mmu(m, S)
    assert out[0].sum() == 13 and out[5].sum() == 0


def test_mmu_uses_8_connectivity():
    m = np.zeros((20, 20), bool)
    idx = np.arange(13)
    m[idx, idx] = True     # köşegen 13 piksel: 8-komşulukta tek nesne
    assert apply_mmu(m, S).sum() == 13


def test_open_close_removes_speckle_fills_hole():
    m = np.zeros((20, 20), bool)
    m[2, 2] = True                     # tekil gürültü
    m[8:16, 8:16] = True
    m[11, 11] = False                  # tek pikselli boşluk
    out = open_close(m, S)
    assert not out[2, 2] and out[11, 11]
    assert clean_mask(m, S)[8:16, 8:16].sum() >= 40
