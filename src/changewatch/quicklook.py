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
    scale = float(settings["stac"]["reflectance_scale"])
    rgb = np.stack([ds[b].values for b in q["rgb_bands"]], axis=-1) / scale
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


def save_index_png(arr: np.ndarray, name: str, path: Path, settings: dict[str, Any], title: str = "") -> Path:
    """Tek bir indeksi settings'teki sabit renk aralığıyla (yıllar arası karşılaştırılabilir) PNG'ye yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    d = settings["quicklook"]["indices"][name]
    cmap = plt.get_cmap(d["cmap"]).copy()
    cmap.set_bad((0.6, 0.6, 0.6, 1.0))  # NaN: gri
    h, w = arr.shape
    dpi = int(settings["quicklook"]["dpi"])
    fig, ax = plt.subplots(figsize=(w / dpi * 1.5 + 1.5, h / dpi * 1.5 + 0.6), dpi=dpi)
    im = ax.imshow(np.ma.masked_invalid(arr), cmap=cmap, vmin=d["vmin"], vmax=d["vmax"],
                   interpolation="nearest")
    ax.set_axis_off()
    med = float(np.nanmedian(arr)) if np.isfinite(arr).any() else float("nan")
    ax.set_title(f"{title}\nmedyan {med:.3f} | NaN %{100 * float(np.isnan(arr).mean()):.2f}", fontsize=9)
    fig.colorbar(im, ax=ax, shrink=0.8).set_label(name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def overlay_array(ds: xr.Dataset, mask: np.ndarray, settings: dict[str, Any]) -> np.ndarray:
    """Doğal renk görüntü üzerine yarı saydam maske (RGB, 0–1)."""
    q = settings["quicklook"]
    rgba = rgb_array(ds, settings)
    rgb = rgba[..., :3] * rgba[..., 3:4]
    color = np.array(q["overlay_color"], dtype=float)
    a = float(q["overlay_alpha"])
    rgb[mask] = (1 - a) * rgb[mask] + a * color
    k = int(q["overlay_upscale"])
    return np.repeat(np.repeat(rgb, k, axis=0), k, axis=1) if k > 1 else rgb


def save_overlay_png(ds: xr.Dataset, mask: np.ndarray, path: Path, settings: dict[str, Any]) -> Path:
    """Aday maskesini doğal renk görüntünün üzerine yarı saydam çizip PNG'ye yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(path, np.clip(overlay_array(ds, mask, settings), 0, 1))
    return path


def save_change_panel_png(before: xr.Dataset, after: xr.Dataset, mask: np.ndarray, path: Path,
                          settings: dict[str, Any], labels: tuple[str, str], title: str = "") -> Path:
    """Önce | sonra | sonra + aday maskesi yan yana."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = mask.shape
    dpi = int(settings["quicklook"]["dpi"])
    fig, ax = plt.subplots(1, 3, figsize=(3 * w / dpi * 1.6, h / dpi * 1.6 + 0.6), dpi=dpi)
    ax[0].imshow(rgb_array(before, settings), interpolation="nearest")
    ax[1].imshow(rgb_array(after, settings), interpolation="nearest")
    s2 = {**settings, "quicklook": {**settings["quicklook"], "overlay_upscale": 1}}
    ax[2].imshow(np.clip(overlay_array(after, mask, s2), 0, 1), interpolation="nearest")
    for a, lab in zip(ax, (labels[0], labels[1], f"{labels[1]} + aday")):
        a.set_title(lab, fontsize=9)
        a.set_axis_off()
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
