"""composite.py ve quicklook.py testleri (sentetik diziler)."""

import numpy as np
import xarray as xr
from PIL import Image

from changewatch.composite import median_composite
from changewatch.config import load_settings
from changewatch.quicklook import save_rgb_png, save_valid_obs_png

S = load_settings()


def _scene(val: float, valid: np.ndarray) -> xr.Dataset:
    arr = np.where(valid, val, np.nan).astype("float32")
    ds = xr.Dataset({b: (("y", "x"), arr) for b in ("B02", "B03", "B04")},
                    coords={"y": [1.0, 0.0], "x": [0.0, 1.0]})
    ds["valid"] = (("y", "x"), valid)
    return ds


def test_median_ignores_masked_and_counts_obs():
    v_all = np.ones((2, 2), bool)
    v_part = np.array([[True, False], [True, True]])
    scenes = [_scene(100, v_all), _scene(200, v_all), _scene(900, v_part), _scene(300, v_all)]
    out = median_composite(scenes, S)
    # (0,0): 100,200,900,300 → 250 ; (0,1): 100,200,300 → 200 (bulutlu 900 dışarıda)
    assert out["B04"].values[0, 0] == 250
    assert out["B04"].values[0, 1] == 200
    assert out["valid_obs"].values.tolist() == [[4, 3], [4, 4]]


def test_below_min_obs_is_nan():
    v = np.array([[True, False], [True, True]])
    scenes = [_scene(100, v), _scene(200, v), _scene(300, np.ones((2, 2), bool))]
    out = median_composite(scenes, S)  # min_valid_obs = 3
    assert np.isnan(out["B04"].values[0, 1]) and out["valid_obs"].values[0, 1] == 1
    assert out["B04"].values[0, 0] == 200


def test_pngs_written(tmp_path):
    v = np.ones((2, 2), bool)
    comp = median_composite([_scene(1000, v)] * 3, S)
    p = save_rgb_png(comp, tmp_path / "rgb.png", S)
    assert Image.open(p).size == (2, 2)
    assert save_valid_obs_png(comp, tmp_path / "obs.png", S, "test").stat().st_size > 0


def test_fuse_acquisitions_merges_tiles_of_same_acquisition():
    from changewatch.composite import fuse_acquisitions

    left = np.array([[True, False], [True, False]])
    right = np.array([[True, True], [False, True]])   # örtüşme: sol sütunun üstü
    a = _scene(100, left)
    b = _scene(200, right)
    c = _scene(300, np.ones((2, 2), bool))
    for ds, iid, t in ((a, "S2A_x_T36TVK", "2024-07-04T08:35:59"), (b, "S2A_x_T36SVJ", "2024-07-04T08:35:59"),
                       (c, "S2B_y_T36TVK", "2024-07-09T08:36:01")):
        ds.attrs.update(item_id=iid, acquired=t)
    out = fuse_acquisitions([a, b, c])
    assert len(out) == 2
    f = out[0]
    assert f["valid"].values.all()
    assert f["B04"].values.tolist() == [[100, 200], [100, 200]]   # örtüşmede ilk kare, boşluk ikinciden
    assert f.attrs["fused_tiles"] == 2
    comp = median_composite(out, S)
    assert comp["valid_obs"].values.tolist() == [[2, 2], [2, 2]]   # 2 çekim; örtüşme iki kez sayılmaz
