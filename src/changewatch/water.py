"""Yıllık su maskesi (MNDWI + Otsu), su alanı serisi ve su kazanımı/kaybı kırılmaları."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from changewatch.change import otsu_threshold


@dataclass
class WaterThresholds:
    """Yıllık eşikler ve hangi yöntemin kullanıldığı."""

    otsu: list[float]          # her yılın Otsu eşiği
    used: list[float]          # maskede kullanılan eşik (Otsu ya da sabit)
    mode: str                  # "otsu" | "sabit"
    otsu_range: float          # max − min Otsu eşiği


def annual_thresholds(mndwi: np.ndarray, region: np.ndarray, settings: dict[str, Any]) -> WaterThresholds:
    """Her yıl için MNDWI Otsu eşiği; yıllar arası aralık max_threshold_range'i aşarsa hepsi sabit eşik."""
    w = settings["water"]
    otsu = [otsu_threshold(mndwi[t], region, int(w["otsu_bins"])) for t in range(mndwi.shape[0])]
    rng = float(max(otsu) - min(otsu))
    if rng > float(w["max_threshold_range"]):
        return WaterThresholds(otsu, [float(w["fixed_threshold"])] * len(otsu), "sabit", rng)
    return WaterThresholds(otsu, otsu, "otsu", rng)


def water_masks(mndwi: np.ndarray, thresholds: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """(su, geçerli) maskeleri (T, H, W). NaN → geçersiz (su sayılmaz)."""
    valid = np.isfinite(mndwi)
    thr = np.asarray(thresholds, dtype="float32")[:, None, None]
    water = valid & (np.nan_to_num(mndwi, nan=-np.inf) > thr)
    return water, valid


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
    """Su parçası: sulak_alan_belirsiz | su_kazanimi | su_kaybi; güven kırılma sonrası yıl sayısına göre."""
    bp = settings["breakpoint"]
    if wetland_share >= float(settings["water"]["wetland_min_share"]):
        tur = "sulak_alan_belirsiz"
    else:
        tur = "su_kazanimi" if gain_share >= loss_share else "su_kaybi"
    if tur == "sulak_alan_belirsiz":
        guven = "dusuk"
    elif n_after >= int(bp["after_years_high"]):
        guven = "yuksek"
    else:
        guven = "orta"
    return {"tur": tur, "guven": guven, "durum": "kalici"}
