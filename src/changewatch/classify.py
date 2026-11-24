"""Değişim türü, güven düzeyi ve kalıcılık kuralı."""

from __future__ import annotations

from typing import Any

import numpy as np


def pixel_persistence(
    cva_flag: np.ndarray,
    texture_flag: np.ndarray,
    dtex_signed_ab: np.ndarray,
    cva_a_next: np.ndarray,
    dtex_signed_a_next: np.ndarray,
    cva_threshold: float,
    texture_threshold: float,
) -> np.ndarray:
    """(y-1 → y) değişimi y+1'de sürüyor mu? Piksel bazında, aynı çiftin eşikleriyle.

    CVA ile işaretli piksel: y+1 hâlâ y-1'den farklı (CVA(y-1 → y+1) > eşik).
    Doku ile işaretli piksel: y-1 → y+1 doku farkı aynı yönde ve |fark| > eşik.
    Nadas gibi geri dönen değişimler bu testi geçemez.
    """
    with np.errstate(invalid="ignore"):
        p_cva = cva_flag & (np.nan_to_num(cva_a_next, nan=-1) > cva_threshold)
        same_sign = np.sign(dtex_signed_ab) == np.sign(dtex_signed_a_next)
        p_tex = texture_flag & same_sign & (np.nan_to_num(np.abs(dtex_signed_a_next), nan=-1) > texture_threshold)
    return p_cva | p_tex


def signal_source(cva_share: float, texture_share: float, min_share: float) -> str:
    """Parçanın hangi sinyalden geldiği: 'cva', 'doku' ya da 'ikisi'."""
    has_cva, has_tex = cva_share >= min_share, texture_share >= min_share
    if has_cva and has_tex:
        return "ikisi"
    if has_tex:
        return "doku"
    if has_cva:
        return "cva"
    return "doku" if texture_share > cva_share else "cva"  # ikisi de zayıfsa baskın olan


def _median(a: np.ndarray) -> float | None:
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else None


def piece_evidence(sel: np.ndarray, layers: dict[str, np.ndarray | None], thresholds: dict[str, float],
                   settings: dict[str, Any]) -> dict[str, Any]:
    """Bir parçanın (sel: bool maske) kanıt alanları. layers'ta y+1 katmanları None olabilir (son yıl)."""
    min_obs = int(settings["composite"]["min_valid_obs"])
    n = int(sel.sum())
    cva_share = float(layers["cva_flag"][sel].mean())
    tex_share = float(layers["texture_flag"][sel].mean())
    dtex = layers["dtex_signed"][sel]
    inc_share = float(np.mean(np.nan_to_num(dtex, nan=-np.inf) > thresholds["texture"]))
    ev: dict[str, Any] = {
        "piksel": n,
        "sinyal": signal_source(cva_share, tex_share, float(settings["change"]["signal_min_share"])),
        "cva_payi": round(cva_share, 3),
        "doku_payi": round(tex_share, 3),
        "dNDVI": _median(layers["dNDVI"][sel]),
        "dNDBI": _median(layers["dNDBI"][sel]),
        "dBSI": _median(layers["dBSI"][sel]),
        "dMNDWI": _median(layers["dMNDWI"][sel]),
        "doku_artisi": _median(dtex),
        "doku_artisi_payi": round(inc_share, 3),
        "mndwi_sonra": _median(layers["MNDWI_b"][sel]),
        "gecerli_gozlem_sayisi": round(float(layers["valid_obs_b"][sel].mean()), 1),
        "dusuk_gozlem": {
            "ort_gozlem": round(float(layers["valid_obs_a"][sel].mean()), 1),
            "dusuk_piksel_orani": round(float((layers["valid_obs_a"][sel] < min_obs).mean()), 3),
        },
    }
    if layers.get("persistent") is not None:
        share = float(layers["persistent"][sel].mean())
        ev["kalicilik_payi"] = round(share, 3)
        ev["kalici_mi"] = share >= float(settings["classify"]["persistence_min_share"])
        ev["mndwi_sonraki"] = _median(layers["MNDWI_next"][sel])
        ev["dNDVI_sonraki"] = _median(layers["dNDVI_next"][sel])
    else:
        ev["kalicilik_payi"] = None
        ev["kalici_mi"] = None
        ev["mndwi_sonraki"] = None
        ev["dNDVI_sonraki"] = None
    return ev


def classify_piece(ev: dict[str, Any], settings: dict[str, Any]) -> dict[str, str] | None:
    """Kanıtlardan tür, güven ve durum. Kalıcı olmayan parça için (ayar açıksa) None döner."""
    c = settings["classify"]
    last_year = ev["kalici_mi"] is None
    if not last_year and not ev["kalici_mi"] and c["drop_non_persistent"]:
        return None

    w = float(c["water_mndwi_threshold"])
    mndwi = ev["mndwi_sonra"]
    is_water_now = mndwi is not None and mndwi > w
    water_persists = last_year or (ev["mndwi_sonraki"] is not None and ev["mndwi_sonraki"] > w)
    tex_up = ev["doku_artisi_payi"] >= float(c["texture_increase_min_share"])
    drop = float(c["ndvi_drop"])
    ndvi_down = ev["dNDVI"] is not None and ev["dNDVI"] < -drop
    ndvi_down_persists = last_year or (ev["dNDVI_sonraki"] is not None and ev["dNDVI_sonraki"] < -drop)

    if is_water_now and water_persists:
        tur = "su_degisimi"
    elif tex_up and not is_water_now:
        tur = "yapilasma_olasi"
    elif ndvi_down and ndvi_down_persists and not tex_up:
        tur = "bitki_kaybi"
    else:
        tur = "belirsiz"

    if tur == "belirsiz":
        guven = "dusuk"
    elif last_year:
        guven = "orta"
    else:
        guven = "yuksek"
    durum = "izlemede" if last_year else ("kalici" if ev["kalici_mi"] else "gecici")
    return {"tur": tur, "guven": guven, "durum": durum}


# ---------------------------------------------------------------- kırılma noktası yöntemi

def break_piece_evidence(sel: np.ndarray, layers: dict[str, np.ndarray], thresholds: dict[str, float],
                         settings: dict[str, Any]) -> dict[str, Any]:
    """Kırılma yöntemi parçasının kanıt alanları (parça medyanları)."""
    min_obs = int(settings["composite"]["min_valid_obs"])
    from changewatch.breakpoint import SIGNAL_NAMES

    tex_up = np.nan_to_num(layers["tex_step"][sel], nan=-np.inf) > thresholds["texture"]
    codes = layers["signal"][sel]
    counts = np.bincount(codes, minlength=4)[1:]
    n_after = int(np.median(layers["n_after"][sel]))
    return {
        "piksel": int(sel.sum()),
        "sinyal": SIGNAL_NAMES[int(np.argmax(counts)) + 1],
        "spektral_payi": round(float(layers["spectral_sig"][sel].mean()), 3),
        "doku_payi": round(float(layers["texture_sig"][sel].mean()), 3),
        "skor": _median(layers["score"][sel]),
        "basamak": _median(layers["step"][sel]),
        "sonrasi_yil_sayisi": n_after,
        "yil_payi": round(float(layers["year_agree"][sel].mean()), 3),
        "dNDVI": _median(layers["ndvi_step"][sel]),
        "dNDBI": _median(layers["ndbi_step"][sel]),
        "dBSI": _median(layers["bsi_step"][sel]),
        "dMNDWI": _median(layers["mndwi_step"][sel]),
        "doku_artisi": _median(layers["tex_step"][sel]),
        "doku_artisi_payi": round(float(tex_up.mean()), 3),
        "mndwi_once": _median(layers["mndwi_before"][sel]),
        "mndwi_sonra": _median(layers["mndwi_after"][sel]),
        "kalici_mi": None if n_after < int(settings["breakpoint"]["after_years_medium"]) else True,
        "gecerli_gozlem_sayisi": round(float(np.nanmean(layers["valid_obs_b"][sel])), 1),
        "dusuk_gozlem": {
            "ort_gozlem": round(float(np.nanmean(layers["valid_obs_a"][sel])), 1),
            "dusuk_piksel_orani": round(float((layers["valid_obs_a"][sel] < min_obs).mean()), 3),
        },
    }


def classify_break_piece(ev: dict[str, Any], thresholds: dict[str, float],
                         settings: dict[str, Any]) -> dict[str, str]:
    """Kırılma parçası: tür (parça medyanlarıyla) + kırılma sonrası yıl sayısına göre güven/durum."""
    w = float(settings["classify"]["water_mndwi_threshold"])
    bp = settings["breakpoint"]
    before, after = ev["mndwi_once"], ev["mndwi_sonra"]
    tex_up = ev["doku_artisi"] is not None and ev["doku_artisi"] > thresholds["texture"]
    ndvi_down = ev["dNDVI"] is not None and ev["dNDVI"] < thresholds["ndvi"]
    if after is not None and before is not None and after > w >= before:
        tur = "belirsiz"  # su geçişi su katmanında (water.py) sınıflanır; burada yapılaşma/bitki sayılmaz
    elif tex_up:
        tur = "yapilasma_olasi"
    elif ndvi_down:
        tur = "bitki_kaybi"
    else:
        tur = "belirsiz"

    n_after = ev["sonrasi_yil_sayisi"]
    if n_after < int(bp["after_years_medium"]):
        guven, durum = "dusuk", "izlemede"
    elif n_after < int(bp["after_years_high"]):
        guven, durum = "orta", "kalici"
    else:
        guven, durum = "yuksek", "kalici"
    if tur == "belirsiz":
        guven = "dusuk"
    return {"tur": tur, "guven": guven, "durum": durum}
