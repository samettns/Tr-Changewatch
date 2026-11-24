"""cache.py testleri: GeoTIFF yaz/oku gidiş-dönüşü."""

import numpy as np
import xarray as xr

from changewatch.cache import read_dataset, write_dataset


def _ds():
    y = 4_400_010.0 - 20 * np.arange(3)
    x = 500_010.0 + 20 * np.arange(4)
    b = np.arange(12, dtype="uint16").reshape(3, 4)
    ds = xr.Dataset({"B04": (("y", "x"), b), "SCL": (("y", "x"), b % 11)}, coords={"y": y, "x": x})
    ds.attrs.update(item_id="S2X", processing_baseline="05.10")
    return ds


def test_roundtrip(tmp_path):
    src = _ds()
    p = write_dataset(src, tmp_path / "a" / "s.tif", "EPSG:32636", nodata=0)
    out = read_dataset(p)
    assert list(out.data_vars) == ["B04", "SCL"]
    np.testing.assert_array_equal(out["B04"].values, src["B04"].values)
    np.testing.assert_allclose(out["x"].values, src["x"].values)
    np.testing.assert_allclose(out["y"].values, src["y"].values)
    assert out.attrs["processing_baseline"] == "05.10"
    assert out.attrs["crs"] == "EPSG:32636"
    assert not list((tmp_path / "a").glob("*.part.tif"))
