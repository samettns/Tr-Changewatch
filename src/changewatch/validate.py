"""Tabakalı rastgele nokta örneklemesi, etiket okuma ve doğruluk metrikleri.

Tabakalar: kalıcı katmandaki her tür + "degisim_yok" (hiçbir değişim/izleme poligonu dışında kalan AOI pikselleri).
İzleme katmanı (son yıl) doğrulanamadığı için örneklenmez ve "degisim_yok" tabakasından da dışlanır.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np

NO_CHANGE = "degisim_yok"
LABEL_FIELDS = ["nokta_id", "aoi", "gercek_degisim", "gercek_tur", "gercek_yil", "not"]


# ---------------------------------------------------------------- örnekleme

def allocate(stratum_px: dict[str, int], total: int, no_change_n: int, min_per: int) -> dict[str, int]:
    """Nokta dağıtımı: degisim_yok sabit; kalan, değişim tabakalarına alanla orantılı, tabaka başına ≥ min_per.

    Hiçbir tabakaya piksel sayısından fazla nokta verilmez.
    """
    alloc = {NO_CHANGE: min(no_change_n, stratum_px.get(NO_CHANGE, 0))}
    change = {k: v for k, v in stratum_px.items() if k != NO_CHANGE and v > 0}
    rest = max(total - alloc[NO_CHANGE], 0)
    base = {k: min(min_per, v) for k, v in change.items()}
    left = rest - sum(base.values())
    if left > 0 and change:
        tot = sum(change.values())
        extra = {k: left * v / tot for k, v in change.items()}
        for k in change:
            base[k] = min(change[k], base[k] + int(math.floor(extra[k])))
        # yuvarlama artığını en büyük kesirlere dağıt
        rem = rest - sum(base.values())
        for k in sorted(change, key=lambda k: -(extra[k] - math.floor(extra[k]))):
            if rem <= 0:
                break
            if base[k] < change[k]:
                base[k] += 1
                rem -= 1
    alloc.update(base)
    return alloc


def sample_pixels(stratum_maps: dict[str, np.ndarray], alloc: dict[str, int], seed: int,
                  calibration_share: float) -> list[dict[str, Any]]:
    """Her tabakadan (tüm AOI'ler birlikte) eşit olasılıklı piksel seçer; tabaka içinde kalibrasyon payını işaretler.

    stratum_maps: "<aoi>" → (H, W) tabaka adı dizisi ('' = örnekleme dışı).
    """
    rng = np.random.default_rng(seed)
    pool: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for aoi, smap in stratum_maps.items():
        for s in np.unique(smap):
            if not s:
                continue
            rr, cc = np.nonzero(smap == s)
            pool[str(s)].extend((aoi, int(r), int(c)) for r, c in zip(rr, cc))
    points = []
    for s in sorted(alloc):
        cand = pool.get(s, [])
        n = min(alloc[s], len(cand))
        if n == 0:
            continue
        pick = rng.choice(len(cand), n, replace=False)
        n_cal = int(round(n * calibration_share))
        roles = np.array(["kalibrasyon"] * n_cal + ["test"] * (n - n_cal))
        rng.shuffle(roles)
        for j, i in enumerate(sorted(pick)):
            aoi, r, c = cand[i]
            points.append({"aoi": aoi, "tabaka": s, "row": r, "col": c, "rol": str(roles[j]),
                           "tabaka_piksel": len(cand)})
    for k, p in enumerate(points, start=1):
        p["nokta_id"] = f"P{k:03d}"
    return points


def write_label_template(points: Sequence[dict], path: Path, force: bool = False) -> Path:
    """Boş labels.csv şablonu (nokta_id ve aoi dolu). Dolu etiket varsa force olmadan üzerine yazmaz."""
    if path.exists() and not force and any(filled_labels(read_labels(path))):
        raise FileExistsError(f"{path} içinde girilmiş etiketler var; üzerine yazmak için --force.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        w.writeheader()
        for p in points:
            w.writerow({"nokta_id": p["nokta_id"], "aoi": p["aoi"]})
    return path


# ---------------------------------------------------------------- etiketler

def read_labels(path: Path) -> list[dict[str, str]]:
    """labels.csv satırları (yoksa boş liste)."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def filled_labels(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """gercek_degisim alanı girilmiş satırlar."""
    return [r for r in rows if r.get("gercek_degisim")]


def reference_class(row: dict[str, str]) -> str:
    """Etiket satırından referans sınıf: hayir → degisim_yok; evet → gercek_tur."""
    v = row["gercek_degisim"].lower()
    if v in ("hayir", "hayır", "h", "no", "0"):
        return NO_CHANGE
    if v in ("evet", "e", "yes", "1"):
        if not row.get("gercek_tur"):
            raise ValueError(f"{row['nokta_id']}: gercek_degisim=evet ama gercek_tur boş.")
        return row["gercek_tur"]
    raise ValueError(f"{row['nokta_id']}: gercek_degisim 'evet' ya da 'hayir' olmalı, '{row['gercek_degisim']}'.")


# ---------------------------------------------------------------- metrikler

def confusion(ref: Sequence[str], pred: Sequence[str]) -> tuple[list[str], np.ndarray]:
    """Karışıklık matrisi: satır = referans, sütun = tahmin."""
    classes = sorted(set(ref) | set(pred), key=lambda c: (c == NO_CHANGE, c))
    ix = {c: i for i, c in enumerate(classes)}
    m = np.zeros((len(classes), len(classes)), int)
    for r, p in zip(ref, pred):
        m[ix[r], ix[p]] += 1
    return classes, m


def class_metrics(classes: list[str], m: np.ndarray) -> dict[str, dict[str, float | None]]:
    """Kullanıcı doğruluğu (kesinlik), üretici doğruluğu (duyarlılık), F1."""
    out = {}
    for i, c in enumerate(classes):
        col, row, tp = m[:, i].sum(), m[i, :].sum(), m[i, i]
        ua = tp / col if col else None
        pa = tp / row if row else None
        f1 = 2 * ua * pa / (ua + pa) if ua and pa else (0.0 if ua is not None and pa is not None else None)
        out[c] = {"kullanici_dogrulugu": ua, "uretici_dogrulugu": pa, "f1": f1, "referans_n": int(row),
                  "tahmin_n": int(col)}
    return out


def metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """records: {ref, pred, pred_year, ref_year}. Genel, sınıf bazlı ve yıl bazlı metrikler."""
    ref = [r["ref"] for r in records]
    pred = [r["pred"] for r in records]
    classes, m = confusion(ref, pred)
    pred_change = [r for r in records if r["pred"] != NO_CHANGE]
    fa = sum(r["ref"] == NO_CHANGE for r in pred_change)
    both = [r for r in pred_change if r["ref"] != NO_CHANGE and r.get("ref_year") and r.get("pred_year")]
    by_year: dict[int, dict[str, float]] = {}
    for y, grp in sorted(_group(pred_change, "pred_year").items()):
        by_year[int(y)] = {"n": len(grp), "dogruluk": sum(g["ref"] == g["pred"] for g in grp) / len(grp),
                           "yanlis_alarm_orani": sum(g["ref"] == NO_CHANGE for g in grp) / len(grp)}
    return {
        "n": len(records),
        "genel_dogruluk": float(np.trace(m) / m.sum()) if m.sum() else None,
        "yanlis_alarm_orani": fa / len(pred_change) if pred_change else None,
        "siniflar": classes,
        "karisiklik": m.tolist(),
        "sinif_metrikleri": class_metrics(classes, m),
        "yil": {
            "degisim_yakalanan_n": len(both),
            "tam_isabet": sum(int(r["ref_year"]) == int(r["pred_year"]) for r in both) / len(both) if both else None,
            "pm1_isabet": sum(abs(int(r["ref_year"]) - int(r["pred_year"])) <= 1 for r in both) / len(both)
            if both else None,
            "tahmin_yilina_gore": by_year,
        },
    }


def _group(records: Sequence[dict], key: str) -> dict[Any, list[dict]]:
    g: dict[Any, list[dict]] = defaultdict(list)
    for r in records:
        if r.get(key) is not None:
            g[r[key]].append(r)
    return g


def lookup_predictions(points: Sequence[dict[str, Any]], features_by_aoi: dict[str, list[tuple[Any, dict]]]
                       ) -> list[tuple[str, int | None]]:
    """Her nokta için haritadaki tür ve yıl (nokta, poligon içinde değilse degisim_yok).

    Çakışan poligonlarda en geç değişim yılı alınır. Noktalar ve poligonlar aynı CRS'te olmalı.
    """
    from shapely import STRtree
    from shapely.geometry import Point

    trees = {aoi: (STRtree([g for g, _ in f]), f) for aoi, f in features_by_aoi.items() if f}
    out = []
    for p in points:
        best: tuple[str, int | None] = (NO_CHANGE, None)
        if p["aoi"] in trees:
            tree, feats = trees[p["aoi"]]
            pt = Point(p["x"], p["y"])
            hits = [feats[i] for i in tree.query(pt, predicate="intersects")]
            if hits:
                g, pr = max(hits, key=lambda h: h[1]["degisim_yili"])
                best = (pr["tur"], int(pr["degisim_yili"]))
        out.append(best)
    return out


def format_report(rep: dict[str, Any]) -> str:
    """Metrikleri markdown olarak biçimlendirir."""
    pct = lambda v: "-" if v is None else f"%{100 * v:.0f}"  # noqa: E731
    lines = [f"n = {rep['n']} | genel doğruluk {pct(rep['genel_dogruluk'])} | "
             f"yanlış alarm oranı {pct(rep['yanlis_alarm_orani'])}", "",
             "Karışıklık matrisi (satır = referans, sütun = tahmin)", "",
             "| ref \\ tahmin | " + " | ".join(rep["siniflar"]) + " |",
             "|---|" + "---|" * len(rep["siniflar"])]
    for c, row in zip(rep["siniflar"], rep["karisiklik"]):
        lines.append(f"| {c} | " + " | ".join(map(str, row)) + " |")
    lines += ["", "| sınıf | kullanıcı d. | üretici d. | F1 | ref n | tahmin n |", "|---|---|---|---|---|---|"]
    for c, v in rep["sinif_metrikleri"].items():
        lines.append(f"| {c} | {pct(v['kullanici_dogrulugu'])} | {pct(v['uretici_dogrulugu'])} | {pct(v['f1'])} | "
                     f"{v['referans_n']} | {v['tahmin_n']} |")
    y = rep["yil"]
    lines += ["", f"Kırılma yılı isabeti (doğru yakalanan {y['degisim_yakalanan_n']} değişim): tam {pct(y['tam_isabet'])}, "
                  f"±1 yıl {pct(y['pm1_isabet'])}", "", "| tahmin yılı | n | doğruluk | yanlış alarm |",
              "|---|---|---|---|"]
    for yr, v in y["tahmin_yilina_gore"].items():
        lines.append(f"| {yr} | {v['n']} | {pct(v['dogruluk'])} | {pct(v['yanlis_alarm_orani'])} |")
    return "\n".join(lines)


def summary_counts(points: Sequence[dict]) -> dict[str, dict[str, int]]:
    """tabaka → {aoi/rol sayıları}."""
    out: dict[str, Counter] = defaultdict(Counter)
    for p in points:
        out[p["tabaka"]][p["aoi"]] += 1
        out[p["tabaka"]][p["rol"]] += 1
        out[p["tabaka"]]["toplam"] += 1
    return {k: dict(v) for k, v in out.items()}


def load_points(path: Path) -> list[dict[str, Any]]:
    """points.geojson özellikleri (x, y proje CRS'inde özellik olarak tutulur)."""
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [f["properties"] for f in fc["features"]]
