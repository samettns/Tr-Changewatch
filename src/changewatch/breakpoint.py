"""Piksel bazında zaman serisi kırılma noktası (LandTrendr/BFAST'ın basitleştirilmiş hâli).

Değişkenler (bantlar + doku) kendi gürültü düzeylerine bölünerek z-ölçeklenir; basamak ve parça içi
yayılım bu ortak uzayda Öklid uzaklığıdır. Gürültü düzeyi referans piksel seçilmeden, tüm piksellerin
seçilen kırılmaya göre parça içi sapmalarının medyanıdır (sabit iki geçiş).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass
class BreakResult:
    """Her piksel için en iyi kırılma ve AOI düzeyindeki gürültü/eşikler."""

    year: np.ndarray            # int16; kırılma yılı (aday olmasa da en iyi b), 0 = hesaplanamadı
    index: np.ndarray           # en iyi b'nin yıl dizisindeki indeksi (-1 = yok)
    score: np.ndarray           # basamak_z / max(yayılım_z, gürültü_z)
    step: np.ndarray            # z-ölçekli basamak büyüklüğü
    spread: np.ndarray          # z-ölçekli parça içi ortalama sapma
    n_after: np.ndarray         # kırılma sonrası yıl sayısı
    candidate: np.ndarray       # bool
    sigma: np.ndarray           # (F,) değişken başına gürültü düzeyi (özgün birimlerde)
    noise: float                # z-uzayında tipik parça içi sapma (pikseller medyanı)
    step_threshold: float       # step_k × noise
    signal: np.ndarray          # uint8: 0 yok, 1 spektral, 2 doku, 3 ikisi (bileşen anlamlılığı)
    spectral_sig: np.ndarray    # bool: spektral bileşen kendi gürültüsüne göre anlamlı
    texture_sig: np.ndarray     # bool: doku bileşeni kendi gürültüsüne göre anlamlı

SIGNAL_NAMES = {1: "spektral", 2: "doku", 3: "ikisi"}


def _nanmedian(a: np.ndarray, axis: int | tuple | None) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(a, axis=axis)


def _norm(a: np.ndarray, axis: int) -> np.ndarray:
    """NaN bileşenleri yok sayan Öklid normu; tüm bileşenler NaN ise NaN."""
    sq = np.nansum(a * a, axis=axis)
    return np.where(np.isnan(a).all(axis=axis), np.nan, np.sqrt(sq))


def _segments(stack: np.ndarray, i: int) -> tuple[np.ndarray, np.ndarray]:
    """Öncesi [:i] ve sonrası [i:] parça medyanları: (F, H, W) ikilisi."""
    return _nanmedian(stack[:i], 0), _nanmedian(stack[i:], 0)


def _residuals(stack: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Her pikselin kendi kırılmasına göre |x_t − parça medyanı| (T, F, H, W); kırılmasız piksel NaN."""
    res = np.full(stack.shape, np.nan, "float32")
    for i in np.unique(index[index > 0]):
        i = int(i)
        sel = index == i
        mb, ma = _segments(stack, i)
        res[:i, :, sel] = np.abs(stack[:i] - mb)[:, :, sel]
        res[i:, :, sel] = np.abs(stack[i:] - ma)[:, :, sel]
    return res


def noise_levels(stack: np.ndarray, index: np.ndarray | None, region: np.ndarray) -> np.ndarray:
    """Değişken başına gürültü: bölgedeki tüm piksel-yıl parça içi mutlak sapmalarının medyanı.

    index None ise kırılma varsayılmaz (serinin tamamının medyanına sapma) – ilk geçiş.
    Not: kırılma uydurması sapmayı en aza indirdiği için σ gerçek gürültüden biraz küçüktür (sentetik
    testte ~%30); skor ve basamak eşiği aynı ölçeği kullandığından bu orantılı bir kaymadır.
    """
    if index is None:
        res = np.abs(stack - _nanmedian(stack, 0))
    else:
        res = _residuals(stack, index)
    sig = np.array([_nanmedian(res[:, f][:, region], None) for f in range(stack.shape[1])], "float64")
    if not np.all(np.isfinite(sig) & (sig > 0)):
        raise ValueError(f"Gürültü düzeyi hesaplanamadı: {sig}")
    return sig


def _best_break(z: np.ndarray, cand_idx: list[int]) -> tuple[np.ndarray, ...]:
    """z-ölçekli yığında (T, F, H, W) toplam sapmayı en aza indiren b ve o b'deki basamak/yayılım."""
    steps, spreads = [], []
    for i in cand_idx:
        mb, ma = _segments(z, i)
        steps.append(_norm(ma - mb, 0))
        dev = np.concatenate([_norm(z[:i] - mb, 1), _norm(z[i:] - ma, 1)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            spreads.append(np.nanmean(dev, axis=0))
    steps, spreads = np.stack(steps), np.stack(spreads)
    ok_b = np.isfinite(steps) & np.isfinite(spreads)
    # Tam eşitlikte (ör. eksik yıl) geç b: degisim_yili = yeni durumun ilk GÖZLENDİĞİ yıl
    cost = np.where(ok_b, spreads, np.inf)[::-1]
    best = (len(cand_idx) - 1) - np.argmin(cost, axis=0)
    take = lambda a: np.take_along_axis(a, best[None], 0)[0]  # noqa: E731
    valid = take(ok_b)
    index = np.where(valid, np.array(cand_idx)[best], -1)
    return index, np.where(valid, take(steps), np.nan), np.where(valid, take(spreads), np.nan), valid


def _segment_diff(stack: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Her pikselin kendi kırılmasında medyan(sonrası) − medyan(öncesi), değişken başına (F, H, W)."""
    out = np.full(stack.shape[1:], np.nan, "float32")
    for i in np.unique(index[index > 0]):
        i = int(i)
        sel = index == i
        mb, ma = _segments(stack, i)
        out[:, sel] = (ma - mb)[:, sel]
    return out


def component_signal(z: np.ndarray, index: np.ndarray, n_spec: int, region: np.ndarray,
                     k: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Basamağın spektral ([:n_spec]) ve doku ([n_spec:]) bileşenlerini kendi gürültüleriyle test eder.

    Bileşen gürültüsü: piksellerin o bileşendeki ortalama parça içi sapmasının medyanı.
    Dönüş: (sinyal kodu, spektral anlamlı, doku anlamlı).
    """
    valid = index > 0
    d = _segment_diff(z, index)
    spec = _norm(d[:n_spec], 0)
    if z.shape[1] == n_spec:
        sig = np.where(valid, 1, 0).astype("uint8")
        return sig, valid & (spec > 0), np.zeros_like(valid)
    tex = _norm(d[n_spec:], 0)
    res = _residuals(z, index)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        spec_spread = np.nanmean(_norm(res[:, :n_spec], 1), axis=0)
        tex_spread = np.nanmean(_norm(res[:, n_spec:], 1), axis=0)
    ref = region & valid
    n_spec_noise = float(_nanmedian(spec_spread[ref], None))
    n_tex_noise = float(_nanmedian(tex_spread[ref], None))
    s_sig = valid & (np.nan_to_num(spec, nan=-1) > k * n_spec_noise)
    t_sig = valid & (np.nan_to_num(tex, nan=-1) > k * n_tex_noise)
    dominant_spec = np.nan_to_num(spec / n_spec_noise, nan=0) >= np.nan_to_num(tex / n_tex_noise, nan=0)
    code = np.where(s_sig & t_sig, 3, np.where(s_sig, 1, np.where(t_sig, 2, np.where(dominant_spec, 1, 2))))
    return np.where(valid, code, 0).astype("uint8"), s_sig, t_sig


def detect_breaks(stack: np.ndarray, years: Sequence[int], settings: dict[str, Any],
                  region: np.ndarray | None = None, n_spec: int | None = None,
                  min_after: int | None = None) -> BreakResult:
    """Yığında (T, F, H, W; özgün birimler) tek basamaklı kırılmayı arar.

    n_spec: ilk n_spec değişken spektral (kalanlar doku); None ise hepsi spektral.
    min_after: settings'teki değeri geçersiz kılar (izleme katmanı için).
    """
    cfg = settings["breakpoint"]
    T = stack.shape[0]
    if region is None:
        region = np.ones(stack.shape[2:], bool)
    m_after = int(cfg["min_after"] if min_after is None else min_after)
    cand_idx = list(range(int(cfg["min_before"]), T - m_after + 1))
    if not cand_idx:
        raise ValueError(f"{T} yıl, min_before/min_after için yetersiz.")

    # 1. geçiş: kırılmasız gürültü → b ; 2. geçiş: o b'ye göre gürültü → b (sabit, yinelemesiz)
    sigma = noise_levels(stack, None, region)
    index, *_ = _best_break(stack / sigma[None, :, None, None], cand_idx)
    sigma = noise_levels(stack, index, region)
    z = stack / sigma[None, :, None, None]
    index, step, spread, valid = _best_break(z, cand_idx)

    noise = float(_nanmedian(spread[region & valid], None))
    step_thr = float(cfg["step_k"]) * noise
    score = step / np.maximum(spread, noise)
    candidate = region & valid & (score > float(cfg["score_k"])) & (step > step_thr)
    yrs = np.asarray(years)
    year = np.where(valid, yrs[np.clip(index, 0, T - 1)], 0).astype("int16")
    n_after = np.where(valid, T - index, 0).astype("int16")
    signal, s_sig, t_sig = component_signal(z, index, stack.shape[1] if n_spec is None else n_spec,
                                            region, float(cfg["step_k"]))
    return BreakResult(year, index.astype("int16"), score.astype("float32"), step.astype("float32"),
                       spread.astype("float32"), n_after, candidate, sigma, noise, step_thr,
                       signal, s_sig, t_sig)


def segment_medians(series: np.ndarray, index: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kırılma öncesi ve sonrası medyanlar (T, H, W) → (H, W), (H, W)."""
    before = np.full(series.shape[1:], np.nan, "float32")
    after = before.copy()
    for i in np.unique(index[index > 0]):
        i = int(i)
        sel = index == i
        before[sel] = _nanmedian(series[:i], 0)[sel]
        after[sel] = _nanmedian(series[i:], 0)[sel]
    return before, after


def segment_step(series: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Tek değişkenli seri (T, H, W): her pikselin kendi kırılmasındaki medyan(sonrası) − medyan(öncesi)."""
    before, after = segment_medians(series, index)
    return after - before


def series_noise(series: np.ndarray, index: np.ndarray, region: np.ndarray) -> float:
    """Tek değişkenli seri için gürültü düzeyi (seçilen kırılmaya göre parça içi sapma medyanı)."""
    return float(noise_levels(series[:, None], index, region)[0])


def mode_filter_years(year: np.ndarray, mask: np.ndarray, size: int) -> np.ndarray:
    """Aday pikseller içinde kırılma yılının size×size mod filtresi (eşitlikte kendi yılı kalır)."""
    if size <= 1:
        return np.where(mask, year, 0)
    r = size // 2
    h, w = year.shape
    y = np.where(mask, year, 0).astype("int32")
    pad = np.pad(y, r)
    windows = np.stack([pad[i:i + h, j:j + w] for i in range(size) for j in range(size)])
    out = y.copy()
    for v in np.unique(y[y > 0]):
        cnt = (windows == v).sum(axis=0)
        best_cnt = (windows == out[None]).sum(axis=0) * (out > 0)
        out = np.where(mask & (cnt > best_cnt), v, out)
    return np.where(mask, out, 0).astype("int16")
