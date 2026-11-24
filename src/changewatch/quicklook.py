"""Kompozit ve değişim önizleme PNG'leri."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import xarray as xr  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402


def rgb_array(ds: xr.Dataset, settings: dict[str, Any]) -> np.ndarray:
    """Doğal renk (y, x, 4) RGBA dizisi; sabit yansıtım aralığı, NaN saydam."""
    q = settings["quicklook"]
    rgb = np.stack([ds[b].values for b in q["rgb_bands"]], axis=-1) / float(q["reflectance_scale"])
    lo, hi = float(q["rgb_min"]), float(q["rgb_max"])
    rgb = np.clip((rgb - lo) / (hi - lo), 0, 1) ** (1.0 / float(q["gamma"]))
    nan = np.isnan(rgb).any(axis=-1)
    rgba = np.dstack([np.nan_to_num(rgb), (~nan).astype(float)])
    return rgba


def save_rgb_png(ds: xr.Dataset, path: Path, settings: dict[str, Any]) -> Path:
    """Doğal renk kompoziti piksel başına bir piksel olacak şekilde PNG'ye yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(path, rgb_array(ds, settings))
    return path


def save_valid_obs_png(ds: xr.Dataset, path: Path, settings: dict[str, Any], title: str = "") -> Path:
    """Piksel bazında geçerli gözlem sayısı haritası; min_valid_obs altı ayrı renkte."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = ds["valid_obs"].values
    min_obs = int(settings["composite"]["min_valid_obs"])
    vmax = max(int(count.max()), min_obs + 1)
    bounds = np.arange(-0.5, vmax + 1.5)
    base = plt.get_cmap("viridis", vmax + 1)(np.arange(vmax + 1))
    base[:min_obs] = [0.85, 0.1, 0.1, 1.0]  # yetersiz gözlem: kırmızı
    cmap = ListedColormap(base)

    h, w = count.shape
    dpi = int(settings["quicklook"]["dpi"])
    fig, ax = plt.subplots(figsize=(w / dpi * 1.5 + 1.5, h / dpi * 1.5 + 0.6), dpi=dpi)
    im = ax.imshow(count, cmap=cmap, norm=BoundaryNorm(bounds, cmap.N), interpolation="nearest")
    ax.set_axis_off()
    pct_low = 100 * float((count < min_obs).mean())
    ax.set_title(f"{title}\ngeçerli gözlem: min {count.min()}, medyan {int(np.median(count))}, "
                 f"maks {count.max()} | <{min_obs}: %{pct_low:.2f}", fontsize=9)
    cb = fig.colorbar(im, ax=ax, ticks=range(0, vmax + 1, max(1, (vmax + 1) // 10)), shrink=0.8)
    cb.set_label("geçerli gözlem sayısı (kırmızı: kompozit dışı)")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
