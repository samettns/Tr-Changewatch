"""Yıllık su maskesi (MNDWI > sabit eşik, ≥ min alan su kütleleri), su alanı serisi, su kazanımı/kaybı."""

from __future__ import annotations

import warnings
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, binary_fill_holes, label

from changewatch.change import otsu_threshold


def raw_water(mndwi: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    """Ham su (MNDWI > eşik) ve geçerli maskeler (T, H, W) ya da (H, W). NaN → geçersiz, su değil."""
    valid = np.isfinite(mndwi)
    return valid & (np.nan_to_num(mndwi, nan=-np.inf) > threshold), valid


def water_bodies(water: np.ndarray, min_px: int, connectivity: int = 2, fill_holes: bool = True) -> np.ndarray:
    """Yalnızca alanı ≥ min_px olan bağlı su kütleleri (çatı, sera, gölcük gibi küçük parçalar elenir).

    fill_holes: kütlenin iç delikleri (göl içinde MNDWI'yi düşüren renk/bulanıklık değişimi) su sayılır;
    böylece göl içi renk değişimi kazanım/kayıp ya da "kıyı" üretmez. (T, H, W) verilirse her yıl ayrı işlenir.
    """
    if water.ndim == 3:
        return np.stack([water_bodies(w, min_px, connectivity, fill_holes) for w in water])
    structure = np.ones((3, 3), int) if connectivity == 2 else None
    lab, n = label(water, structure=structure)
    if n == 0:
        return np.zeros_like(water, bool)
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_px
    keep[0] = False
    out = keep[lab]
    return binary_fill_holes(out) if fill_holes else out


def shoreline(body: np.ndarray, n_px: int) -> np.ndarray:
    """Su kütlesi sınırına ≤ n_px piksel uzaklıktaki pikseller (iç ve dış bant). (T, H, W) de olabilir."""
    if body.ndim == 3:
        return np.stack([shoreline(b, n_px) for b in body])
    if n_px <= 0 or not body.any():
        return np.zeros_like(body, bool)
    s = np.ones((3, 3), bool)
    return binary_dilation(body, s, iterations=n_px) & ~binary_erosion(body, s, iterations=n_px, border_value=1)


def shoreline_at_break(shore: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Pikselin kendi kırılmasında kırılma öncesi yıl (b−1) veya kırılma yılında (b) kıyı şeridinde mi?"""
    out = np.zeros(index.shape, bool)
    for i in np.unique(index[index > 0]):
        i = int(i)
        sel = index == i
        out[sel] = (shore[i - 1] | shore[i])[sel]
    return out


def otsu_diagnostic(mndwi: np.ndarray, region: np.ndarray, bins: int = 256) -> list[float | None]:
    """Yalnızca tanı amaçlı: her yılın AOI içi MNDWI Otsu eşiği (kuralda kullanılmaz)."""
    out = []
    for t in range(mndwi.shape[0]):
        try:
            out.append(otsu_threshold(mndwi[t], region, bins))
        except ValueError:
            out.append(None)
    return out


def water_area_series(water: np.ndarray, valid: np.ndarray, region: np.ndarray, px_ha: float) -> list[dict]:
    """Yıl başına su alanı (ha) ve AOI içinde geçersiz piksel oranı."""
    return [{"su_ha": round(float((water[t] & region).sum()) * px_ha, 1),
             "gecersiz_orani": round(float((~valid[t] & region).sum() / region.sum()), 4)}
            for t in range(water.shape[0])]


def segment_water_state(water: np.ndarray, valid: np.ndarray, index: np.ndarray,
                        majority: float) -> tuple[np.ndarray, np.ndarray]:
    """Kırılma öncesi/sonrası yılların çoğunluğunda su var mı? (önce, sonra) bool (H, W)."""
    before = np.zeros(water.shape[1:], bool)
    after = np.zeros_like(before)
    w = water.astype("float32")
    w[~valid] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i in np.unique(index[index > 0]):
            i = int(i)
            sel = index == i
            before[sel] = (np.nanmean(w[:i], axis=0) > majority)[sel]
            after[sel] = (np.nanmean(w[i:], axis=0) > majority)[sel]
    return before, after


def wetland_pixels(ndvi_before: np.ndarray, ndvi_after: np.ndarray, mndwi_before: np.ndarray,
                   mndwi_after: np.ndarray, threshold: float, settings: dict[str, Any]) -> np.ndarray:
    """Kıyı/sazlık: kırılmanın iki yanından birinde NDVI yüksek ve MNDWI eşiğe yakın."""
    w = settings["water"]
    nmin, margin = float(w["wetland_ndvi_min"]), float(w["wetland_mndwi_margin"])
    with np.errstate(invalid="ignore"):
        side = lambda nd, mn: (nd > nmin) & (np.abs(mn - threshold) < margin)  # noqa: E731
        return side(ndvi_before, mndwi_before) | side(ndvi_after, mndwi_after)


def classify_water_piece(gain_share: float, loss_share: float, wetland_share: float, n_after: int,
                         settings: dict[str, Any]) -> dict[str, str]:
    """Su parçası: sulak_alan_belirsiz | su_kazanimi | su_kaybi; güven/durum kırılma sonrası yıl sayısına göre."""
    bp = settings["breakpoint"]
    if wetland_share >= float(settings["water"]["wetland_min_share"]):
        tur = "sulak_alan_belirsiz"
    else:
        tur = "su_kazanimi" if gain_share >= loss_share else "su_kaybi"
    if n_after < int(bp["after_years_medium"]):
        return {"tur": tur, "guven": "dusuk", "durum": "izlemede"}
    if tur == "sulak_alan_belirsiz":
        guven = "dusuk"
    elif n_after >= int(bp["after_years_high"]):
        guven = "yuksek"
    else:
        guven = "orta"
    return {"tur": tur, "guven": guven, "durum": "kalici"}


def mmu_px(mmu_ha: float, res_m: float) -> int:
    """ha → piksel (yukarı yuvarlanır)."""
    return int(np.ceil(mmu_ha * 10_000 / (res_m * res_m) - 1e-9))


def min_body_px(settings: dict[str, Any]) -> int:
    """Su kütlesi alt sınırı (piksel)."""
    return mmu_px(float(settings["water"]["min_body_ha"]), float(settings["grid"]["resolution_m"]))


