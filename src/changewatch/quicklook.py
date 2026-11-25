"""Kompozit ve değişim önizleme PNG'leri."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects  # noqa: E402
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


def save_category_map_png(background: xr.Dataset, categories: np.ndarray, colors: dict[int, Any],
                          names: dict[int, str], path: Path, settings: dict[str, Any], title: str = "",
                          light: np.ndarray | None = None) -> Path:
    """Soluk gri zemin üzerinde kategorik harita (0 = boş). light: True pikseller açık tonla çizilir."""
    from matplotlib.colors import to_rgb
    from matplotlib.patches import Patch

    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = rgb_array(background, settings)
    gray = rgba[..., :3].mean(axis=-1, keepdims=True)
    img = 0.55 + 0.4 * np.repeat(gray, 3, axis=-1)
    for k, col in colors.items():
        sel = categories == k
        c = np.array(to_rgb(col))
        img[sel] = c
        if light is not None:
            img[sel & light] = 0.45 * c + 0.55
    h, w = categories.shape
    dpi = int(settings["quicklook"]["dpi"])
    fig, ax = plt.subplots(figsize=(w / dpi * 2.0 + 2.6, h / dpi * 2.0 + 0.6), dpi=dpi)
    ax.imshow(np.clip(img, 0, 1), interpolation="nearest")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    handles = [Patch(color=colors[k], label=names[k]) for k in colors if (categories == k).any()]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8, frameon=False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
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


def save_boundary_panel_png(before: xr.Dataset, after: xr.Dataset, mask: np.ndarray, path: Path,
                            settings: dict[str, Any], labels: tuple[str, str], title: str = "") -> Path:
    """İki doğal renk görüntü yan yana; maske sınırları ikisinin üzerine de çizilir (gözle kontrol)."""
    from skimage.segmentation import find_boundaries

    path.parent.mkdir(parents=True, exist_ok=True)
    k = int(settings["quicklook"]["overlay_upscale"])
    up = lambda a: np.repeat(np.repeat(a, k, axis=0), k, axis=1)  # noqa: E731
    edge = find_boundaries(up(mask.astype("uint8")), mode="inner")
    color = np.array(settings["quicklook"]["boundary_color"], dtype=float)
    panels = []
    for ds in (before, after):
        rgba = rgb_array(ds, settings)
        rgb = up(rgba[..., :3] * rgba[..., 3:4])
        rgb[edge] = color
        panels.append(np.clip(rgb, 0, 1))
    h, w = panels[0].shape[:2]
    dpi = int(settings["quicklook"]["dpi"])
    fig, ax = plt.subplots(1, 2, figsize=(2 * w / dpi + 0.4, h / dpi + 0.7), dpi=dpi)
    for a, img, lab in zip(ax, panels, labels):
        a.imshow(img, interpolation="nearest")
        a.set_title(lab, fontsize=10)
        a.set_axis_off()
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def save_series_png(years: list[int], series: list[dict[str, Any]], path: Path, settings: dict[str, Any],
                    title: str, ylabel: str, note: str = "") -> Path:
    """Yıllık çizgi grafiği, tek eksen. series: [{"label", "values", "style": "solid"|"dashed"}].

    Birincil seri (ilk) series_color ile düz; diğerleri gri kesikli. ≥ 2 seride lejant + son noktada doğrudan etiket.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    q = settings["quicklook"]
    ink, muted = "#1f2328", "#6e7781"
    fig, ax = plt.subplots(figsize=(7.5, 3.8), dpi=int(q["dpi"]) * 1.5)
    allv = [v for s in series for v in s["values"]]
    for i, s in enumerate(series):
        primary = i == 0
        color = q["series_color"] if primary else "#8c959f"
        ax.plot(years, s["values"], color=color, lw=2, ls="-" if s.get("style", "solid") == "solid" else "--",
                marker="o" if primary else None, ms=6, mec="white", mew=1.5, zorder=3 if primary else 2,
                label=s["label"])
        if len(series) > 1:
            ax.annotate(f"{s['values'][-1]:.0f}", (years[-1], s["values"][-1]), textcoords="offset points",
                        xytext=(6, 0), va="center", fontsize=8, color=ink)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d0d7de")
    ax.grid(axis="y", color="#eaeef2", lw=0.8, zorder=0)
    ax.tick_params(colors=muted, labelsize=8)
    ax.set_xticks(years)
    lo, hi = min(allv), max(allv)
    pad = max((hi - lo) * 0.12, hi * 0.02, 1)
    ax.set_ylim(max(0, lo - pad), hi + pad)
    ax.set_xlim(years[0] - 0.4, years[-1] + 0.9)
    ax.set_ylabel(ylabel, color=muted, fontsize=8)
    ax.set_title(title, color=ink, fontsize=10, loc="left")
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=ink)
    else:
        vals = series[0]["values"]
        for i in {int(np.argmin(vals)), int(np.argmax(vals))}:
            ax.annotate(f"{vals[i]:.0f}", (years[i], vals[i]), textcoords="offset points",
                        xytext=(0, 8 if vals[i] == max(vals) else -14), ha="center", fontsize=8, color=ink)
    if note:
        fig.text(0.01, 0.01, note, fontsize=7, color=muted)
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return path


def save_mask_pair_png(ds_a: xr.Dataset, ds_b: xr.Dataset, mask_a: np.ndarray, mask_b: np.ndarray, path: Path,
                       settings: dict[str, Any], labels: tuple[str, str], title: str = "") -> Path:
    """İki yılın maskesi, kendi doğal renk görüntüleri üzerinde yan yana (yarı saydam)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    q = settings["quicklook"]
    color = np.array(matplotlib.colors.to_rgb(q["series_color"]))
    k = int(q["overlay_upscale"])
    px_ha = float(settings["grid"]["resolution_m"]) ** 2 / 10_000
    imgs = []
    for ds, m in ((ds_a, mask_a), (ds_b, mask_b)):
        rgba = rgb_array(ds, settings)
        rgb = rgba[..., :3] * rgba[..., 3:4]
        rgb[m] = 0.35 * rgb[m] + 0.65 * color
        imgs.append(np.clip(np.repeat(np.repeat(rgb, k, axis=0), k, axis=1), 0, 1))
    h, w = imgs[0].shape[:2]
    dpi = int(q["dpi"])
    fig, ax = plt.subplots(1, 2, figsize=(2 * w / dpi + 0.4, h / dpi + 0.7), dpi=dpi)
    for a, img, lab, m in zip(ax, imgs, labels, (mask_a, mask_b)):
        a.imshow(img, interpolation="nearest")
        a.set_title(f"{lab}: su {m.sum() * px_ha:.0f} ha", fontsize=10)
        a.set_axis_off()
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def save_chip_png(before: xr.Dataset, after: xr.Dataset, row: int, col: int, path: Path,
                  settings: dict[str, Any], labels: tuple[str, str], title: str = "") -> Path:
    """Etiketleme çipi: noktanın çevresi, önceki ve sonraki yıl yan yana; nokta merkezde işaretli."""
    path.parent.mkdir(parents=True, exist_ok=True)
    v = settings["validation"]
    half = int(v["chip_px"]) // 2
    k = int(v["chip_upscale"])
    res = float(settings["grid"]["resolution_m"])
    imgs = []
    for ds in (before, after):
        rgba = rgb_array(ds, settings)
        rgb = rgba[..., :3] * rgba[..., 3:4]
        h, w = rgb.shape[:2]
        pad = np.zeros((h + 2 * half, w + 2 * half, 3))
        pad[half:half + h, half:half + w] = rgb
        crop = pad[row:row + 2 * half + 1, col:col + 2 * half + 1]
        imgs.append(np.repeat(np.repeat(crop, k, axis=0), k, axis=1))
    size = imgs[0].shape[0]
    c = half * k + k / 2 - 0.5
    fig, ax = plt.subplots(1, 2, figsize=(2 * size / 100 + 0.3, size / 100 + 0.55), dpi=100)
    for a, img, lab in zip(ax, imgs, labels):
        a.imshow(np.clip(img, 0, 1), interpolation="nearest")
        a.add_patch(matplotlib.patches.Rectangle((half * k - 0.5, half * k - 0.5), k, k, fill=False,
                                                 ec="yellow", lw=1.2))
        a.add_patch(matplotlib.patches.Circle((c, c), 3 * k, fill=False, ec="yellow", lw=0.8, ls="--"))
        a.set_title(lab, fontsize=9)
        a.set_axis_off()
    fig.suptitle(f"{title}  ·  {int((2 * half + 1) * res)} m kare", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chip_crop(ds: xr.Dataset, row: int, col: int, half: int, settings: dict[str, Any]) -> np.ndarray:
    """(row, col) merkezli (2·half+1)² doğal renk kesit; AOI dışı siyah."""
    rgba = rgb_array(ds, settings)
    rgb = rgba[..., :3] * rgba[..., 3:4]
    h, w = rgb.shape[:2]
    pad = np.zeros((h + 2 * half, w + 2 * half, 3))
    pad[half:half + h, half:half + w] = rgb
    return pad[row:row + 2 * half + 1, col:col + 2 * half + 1]


def _draw_cross(ax: Any, c: float, k: int, lw: float) -> None:
    """Merkez piksel görünsün diye ortası boş kırmızı artı (siyah kenarlı)."""
    import matplotlib.patheffects as pe

    eff = [pe.Stroke(linewidth=lw + 2, foreground="black"), pe.Normal()]
    for a0, a1 in ((c - 3.5 * k, c - 0.9 * k), (c + 0.9 * k, c + 3.5 * k)):
        ax.plot([a0, a1], [c, c], color="red", lw=lw, solid_capstyle="butt", path_effects=eff)
        ax.plot([c, c], [a0, a1], color="red", lw=lw, solid_capstyle="butt", path_effects=eff)


def save_label_chip_png(composites: list[tuple[int, xr.Dataset]], row: int, col: int, path: Path,
                        settings: dict[str, Any], ncols: int = 5) -> Path:
    """Kör etiketleme çipi (yatay). Solda ilk ve son yıl büyük, yan yana (en yakın komşu), kırmızı artı + yarıçap
    halkası + ölçek çubuğu; sağda tüm yıllar şeridi (2 × 5, aynı artı). Yalnızca yıl yazılır: tahmin, tabaka, AOI,
    kimlik yok."""
    path.parent.mkdir(parents=True, exist_ok=True)
    v = settings["validation"]
    res = float(settings["grid"]["resolution_m"])
    half = int(v["chip_px"]) // 2
    side = 2 * half + 1
    kb = max(1, round(int(v["label_big_px"]) / side))
    ks = int(v["label_strip_upscale"])
    big, small = side * kb, side * ks
    m, gap, sgap, lab, sep = 10, 16, 6, 22, 28
    nrows = int(np.ceil(len(composites) / ncols))
    W = m + 2 * big + gap + sep + ncols * small + (ncols - 1) * sgap + m
    H = m + max(lab + big, nrows * (lab + small)) + m
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)

    def axes(x: float, y: float, s: int) -> Any:
        ax = fig.add_axes([x / W, 1 - (y + s) / H, s / W, s / H])
        ax.set_axis_off()
        return ax

    crops = {yy: _chip_crop(ds, row, col, half, settings) for yy, ds in composites}
    up = lambda a, k: np.clip(np.repeat(np.repeat(a, k, axis=0), k, axis=1), 0, 1)  # noqa: E731
    x0 = m
    for i, yy in enumerate((composites[0][0], composites[-1][0])):
        x = x0 + i * (big + gap)
        fig.text((x + big / 2) / W, 1 - (m + lab - 4) / H, str(yy), ha="center", va="bottom", fontsize=13,
                 fontweight="bold")
        ax = axes(x, m + lab, big)
        ax.imshow(up(crops[yy], kb), interpolation="nearest")
        c = half * kb + kb / 2 - 0.5
        ax.add_patch(matplotlib.patches.Circle((c, c), float(v["label_ring_m"]) / res * kb, fill=False,
                                               ec="red", lw=1.6))
        _draw_cross(ax, c, kb, 2.5)
        bar = float(v["label_scalebar_m"]) / res * kb
        bx, by = 12, big - 16
        ax.add_patch(matplotlib.patches.Rectangle((bx, by), bar, 6, fc="white", ec="black", lw=1))
        ax.text(bx + bar / 2, by - 4, f"{float(v['label_scalebar_m']):g} m", color="white", ha="center",
                va="bottom", fontsize=9, fontweight="bold",
                path_effects=[matplotlib.patheffects.withStroke(linewidth=2.5, foreground="black")])
        ax.set_xlim(-0.5, big - 0.5)
        ax.set_ylim(big - 0.5, -0.5)
    xs = m + 2 * big + gap + sep
    y0 = m
    for idx, (yy, _) in enumerate(composites):
        r, cc = divmod(idx, ncols)
        x, y = xs + cc * (small + sgap), y0 + r * (lab + small)
        fig.text((x + small / 2) / W, 1 - (y + lab - 3) / H, str(yy), ha="center", va="bottom", fontsize=10)
        ax = axes(x, y + lab, small)
        ax.imshow(up(crops[yy], ks), interpolation="nearest")
        _draw_cross(ax, half * ks + ks / 2 - 0.5, ks, 1.6)
        ax.set_xlim(-0.5, small - 0.5)
        ax.set_ylim(small - 0.5, -0.5)
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


ERR_PRED_COLOR = "#f47230"   # tahmin edilen kırılma yılı çerçevesi
ERR_REF_COLOR = "#257de0"    # etiketteki değişim yılı çerçevesi


def save_error_panel_png(items: list[dict[str, Any]], path: Path, settings: dict[str, Any],
                         half: int = 12, k: int = 3) -> Path:
    """Etiketle tahminin ayrıştığı noktalar: her satırda kimlik/etiket/tahmin ve tüm yılların kesiti.

    items: {nokta_id, aoi, ref, pred, ref_year, pred_year, hata, agirlik_ha, not, seq=[(yıl, ds)], row, col}.
    Tahmin yılı turuncu, etiket yılı mavi çerçeve; ikisi de altına yazılır (renk tek başına taşımaz).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    side = (2 * half + 1) * k
    n_y = max(len(it["seq"]) for it in items)
    m, txt, gap, lab, foot, rgap = 10, 300, 4, 18, 16, 10
    W = m + txt + n_y * side + (n_y - 1) * gap + m
    rh = lab + side + foot
    head = 26
    H = m + head + len(items) * (rh + rgap) + m
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor("white")
    fig.text(m / W, 1 - (m + 4) / H,
             f"Etiket ↔ tahmin ayrışmaları (test noktaları). Kesit {(2 * half + 1) * float(settings['grid']['resolution_m']):.0f} m; "
             "çerçeve: turuncu = tahmin edilen kırılma yılı, mavi = etiketteki yıl.",
             ha="left", va="top", fontsize=10, color="#191919")
    up = lambda a: np.clip(np.repeat(np.repeat(a, k, axis=0), k, axis=1), 0, 1)  # noqa: E731
    for i, it in enumerate(items):
        y0 = m + head + i * (rh + rgap)
        ry, py = it.get("ref_year"), it.get("pred_year")
        lines = [f"{i + 1}. {it['nokta_id']} · {it['aoi']} · {it['hata'].replace('_', ' ')}",
                 f"etiket: {it['ref']} ({ry or 'yıl yok'})",
                 f"tahmin: {it['pred']} ({py or '-'})",
                 f"temsil ettiği alan ≈ {it['agirlik_ha']:.0f} ha"]
        if it.get("not"):
            lines.append(f"not: {str(it['not'])[:40]}")
        fig.text(m / W, 1 - (y0 + lab) / H, "\n".join(lines), ha="left", va="top", fontsize=9, color="#191919",
                 linespacing=1.4)
        for j, (yy, ds) in enumerate(it["seq"]):
            x = m + txt + j * (side + gap)
            fig.text((x + side / 2) / W, 1 - (y0 + lab - 3) / H, str(yy), ha="center", va="bottom", fontsize=9,
                     color="#666666")
            ax = fig.add_axes([x / W, 1 - (y0 + lab + side) / H, side / W, side / H])
            ax.set_xticks([])
            ax.set_yticks([])
            ax.imshow(up(_chip_crop(ds, it["row"], it["col"], half, settings)), interpolation="nearest")
            _draw_cross(ax, half * k + k / 2 - 0.5, k, 1.4)
            tags = []
            col = None
            if py is not None and int(py) == yy:
                tags.append("tahmin")
                col = ERR_PRED_COLOR
            if ry is not None and str(ry).isdigit() and int(ry) == yy:
                tags.append("etiket")
                col = ERR_REF_COLOR if col is None else "#6a4ce2"
            for sp in ax.spines.values():
                sp.set_visible(col is not None)
                if col:
                    sp.set_edgecolor(col)
                    sp.set_linewidth(3)
            if tags:
                fig.text((x + side / 2) / W, 1 - (y0 + lab + side + 2) / H, " + ".join(tags), ha="center",
                         va="top", fontsize=8, color="#191919")
            ax.set_xlim(-0.5, side - 0.5)
            ax.set_ylim(side - 0.5, -0.5)
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


EXP_BASE_COLOR = "#257de0"   # temel (dondurulmuş) yöntem
EXP_ALT_COLOR = "#f47230"    # alternatif varyant


def save_experiment_chart_png(results: list[dict[str, Any]], path: Path,
                              metrics: tuple[tuple[str, str], ...] = (
                                  ("yanlis_alarm_orani", "Yanlış alarm oranı (düşük iyi)"),
                                  ("degisim_duyarlilik", "Değişim duyarlılığı (yüksek iyi)"),
                                  ("yapilasma_f1", "Yapılaşma F1 (yüksek iyi)"))) -> Path:
    """Deney varyantlarının test noktası metrikleri: metrik başına bir panel (küçük çoklu), yatay çubuk.

    Temel yöntem mavi, alternatif turuncu (lejant + satır etiketinde '(temel)'). E2 (v2) gösterilmez.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in results if r["deney"] != "E2"]
    labels = [f"{r['deney']} · {r['varyant']}" + (" (temel)" if r["temel"] else "") for r in rows]
    ypos, y, prev = [], 0.0, None
    for r in rows:                                   # deneyler arasında boşluk
        if prev is not None and r["deney"] != prev:
            y += 0.6
        ypos.append(y)
        y += 1
        prev = r["deney"]
    fig, axes = plt.subplots(1, len(metrics), figsize=(4.0 * len(metrics) + 2.2, 0.36 * y + 1.4), sharey=True,
                             dpi=100)
    for ax, (key, title) in zip(np.atleast_1d(axes), metrics):
        vals = [r.get(key) for r in rows]
        cols = [EXP_BASE_COLOR if r["temel"] else EXP_ALT_COLOR for r in rows]
        ax.barh(ypos, [0 if v is None else v for v in vals], height=0.72, color=cols, edgecolor="white", lw=2)
        for yy, v in zip(ypos, vals):
            ax.text((v or 0) + 0.015, yy, "-" if v is None else f"%{100 * v:.0f}", va="center", fontsize=8,
                    color="#191919")
        ax.set_xlim(0, 1.12)
        ax.set_title(title, fontsize=10, loc="left", color="#191919")
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_xticklabels(["0", "25", "50", "75", "100"], fontsize=8, color="#666666")
        ax.grid(axis="x", color="#e5e5e5", lw=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color("#bbbbbb")
        ax.tick_params(axis="y", length=0)
    ax0 = np.atleast_1d(axes)[0]
    ax0.set_yticks(ypos)
    ax0.set_yticklabels(labels, fontsize=9, color="#191919")
    ax0.invert_yaxis()
    handles = [matplotlib.patches.Patch(color=EXP_BASE_COLOR, label="temel yöntem (kırılma, doku, harmonize)"),
               matplotlib.patches.Patch(color=EXP_ALT_COLOR, label="alternatif varyant")]
    n = rows[0]["n"] if rows else 0
    fig.legend(handles=handles, loc="upper left", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.01, 1.0))
    fig.text(0.99, 0.995, f"test noktaları, n = {n}, nokta bazlı (%)", ha="right", va="top", fontsize=8,
             color="#666666")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=100, facecolor="white")
    plt.close(fig)
    return path
