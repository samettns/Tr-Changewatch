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
UNSURE = "emin_degilim"  # gercek_degisim: etiketleyici karar veremedi → metriklerden çıkarılır, ayrı sayılır


# ---------------------------------------------------------------- örnekleme

def allocate(stratum_px: dict[str, int], total: int, no_change_n: int, min_per: int,
             min_px_for_min: int = 0) -> dict[str, int]:
    """Nokta dağıtımı: degisim_yok sabit; kalan, değişim tabakalarına alanla orantılı.

    Tabaka başına en az min_per kuralı yalnızca alanı ≥ min_px_for_min piksel olan tabakalara uygulanır;
    küçük tabakalar yalnızca orantılı paylarını alır (0 olabilir). Hiçbir tabakaya piksel sayısından fazla
    nokta verilmez.
    """
    alloc = {NO_CHANGE: min(no_change_n, stratum_px.get(NO_CHANGE, 0))}
    change = {k: v for k, v in stratum_px.items() if k != NO_CHANGE and v > 0}
    rest = max(total - alloc[NO_CHANGE], 0)
    base = {k: (min(min_per, v) if v >= min_px_for_min else 0) for k, v in change.items()}
    left = rest - sum(base.values())
    if left > 0 and change:
        tot = sum(change.values())
        extra = {k: left * v / tot for k, v in change.items()}
        for k in change:
            base[k] = min(change[k], base[k] + int(math.floor(extra[k])))
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
                  calibration_share: float, polygon_maps: dict[str, np.ndarray] | None = None,
                  max_per_polygon: int = 0, min_dist_px: float = 0.0) -> list[dict[str, Any]]:
    """Her tabakadan (tüm AOI'ler birlikte) eşit olasılıklı piksel seçer; tabaka içinde kalibrasyon payını işaretler.

    stratum_maps: "<aoi>" → (H, W) tabaka adı dizisi ('' = örnekleme dışı).
    polygon_maps: "<aoi>" → (H, W) poligon kimliği (0 = poligon yok); max_per_polygon > 0 ise poligon başına üst sınır.
    min_dist_px > 0 ise aynı AOI'deki noktalar arası en az bu kadar piksel (tüm tabakalar birlikte).
    Kısıtlar yüzünden tabaka dolmazsa daha az nokta döner.
    """
    rng = np.random.default_rng(seed)
    pool: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for aoi, smap in stratum_maps.items():
        for s in np.unique(smap):
            if not s:
                continue
            rr, cc = np.nonzero(smap == s)
            pool[str(s)].extend((aoi, int(r), int(c)) for r, c in zip(rr, cc))
    accepted: dict[str, list[tuple[int, int]]] = defaultdict(list)
    per_poly: Counter = Counter()
    points = []
    # küçük tabakalar önce: kısıtlar büyük tabakaları değil, zaten az pikseli olanları zorlar
    for s in sorted(alloc, key=lambda k: (len(pool.get(k, [])), k)):
        cand = pool.get(s, [])
        want = min(alloc[s], len(cand))
        chosen = []
        for i in rng.permutation(len(cand)):
            if len(chosen) >= want:
                break
            aoi, r, c = cand[i]
            pid = int(polygon_maps[aoi][r, c]) if polygon_maps and aoi in polygon_maps else 0
            if max_per_polygon and pid and per_poly[(aoi, pid)] >= max_per_polygon:
                continue
            if min_dist_px and any((r - rr) ** 2 + (c - cc) ** 2 < min_dist_px ** 2 for rr, cc in accepted[aoi]):
                continue
            chosen.append((aoi, r, c))
            accepted[aoi].append((r, c))
            if pid:
                per_poly[(aoi, pid)] += 1
        n = len(chosen)
        n_cal = int(round(n * calibration_share))
        roles = np.array(["kalibrasyon"] * n_cal + ["test"] * (n - n_cal))
        rng.shuffle(roles)
        for j, (aoi, r, c) in enumerate(sorted(chosen)):
            points.append({"aoi": aoi, "tabaka": s, "row": r, "col": c, "rol": str(roles[j]),
                           "tabaka_piksel": len(cand), "istenen": alloc[s]})
    points.sort(key=lambda p: (p["tabaka"] == NO_CHANGE, p["tabaka"], p["aoi"], p["row"], p["col"]))
    for k, p in enumerate(points, start=1):
        p["nokta_id"] = f"P{k:03d}"
    return points


def write_label_template(points: Sequence[dict], path: Path, force: bool = False) -> Path:
    """Boş labels.csv şablonu (nokta_id ve aoi dolu). Dolu etiket varsa force olmadan üzerine yazmaz."""
    if path.exists() and not force and any(r.get("gercek_degisim") for r in read_labels(path)):
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
    """Kesin etiketli satırlar (gercek_degisim girilmiş ve 'emin_degilim' değil)."""
    return [r for r in rows if r.get("gercek_degisim") and r["gercek_degisim"].lower() != UNSURE]


def unsure_labels(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """'emin_degilim' işaretli satırlar (metriklere katılmaz)."""
    return [r for r in rows if (r.get("gercek_degisim") or "").lower() == UNSURE]


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


def parse_year(v: Any) -> int | None:
    """'2021' → 2021; boş/'bilinmiyor' → None."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """records: {ref, pred, pred_year, ref_year}. Genel, sınıf bazlı ve yıl bazlı metrikler.

    ref_year 'bilinmiyor' ise yıl isabetine katılmaz.
    """
    records = [{**r, "ref_year": parse_year(r.get("ref_year")), "pred_year": parse_year(r.get("pred_year"))}
               for r in records]
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
        "ikili": binary_metrics(records),
        "yil": {
            "degisim_yakalanan_n": len(both),
            "tam_isabet": sum(int(r["ref_year"]) == int(r["pred_year"]) for r in both) / len(both) if both else None,
            "pm1_isabet": sum(abs(int(r["ref_year"]) - int(r["pred_year"])) <= 1 for r in both) / len(both)
            if both else None,
            "tahmin_yilina_gore": by_year,
        },
    }


def olofsson(records: Sequence[dict[str, Any]], stratum_area_ha: dict[str, float],
             z: float = 1.96) -> dict[str, Any]:
    """Olofsson vd. (2014) alan ağırlıklı doğruluk ve alan kestirimi (± z·SE güven aralığı, ha).

    records: {"stratum": harita sınıfı = örnekleme tabakası, "ref": referans sınıf}.
    stratum_area_ha: tabaka (harita sınıfı) alanları. Tabaka içi n < 2 ise o terimin varyansı hesaplanamaz.
    """
    strata = [s for s in stratum_area_ha if any(r["stratum"] == s for r in records)]
    if not strata:
        return {}
    A = float(sum(stratum_area_ha[s] for s in strata))
    classes = sorted({r["ref"] for r in records} | set(strata), key=lambda c: (c == NO_CHANGE, c))
    n_i = {s: sum(r["stratum"] == s for r in records) for s in strata}
    n_ij = {(s, j): sum(r["stratum"] == s and r["ref"] == j for r in records) for s in strata for j in classes}
    W = {s: stratum_area_ha[s] / A for s in strata}
    p = {(s, j): W[s] * n_ij[(s, j)] / n_i[s] for s in strata for j in classes}
    pj = {j: sum(p[(s, j)] for s in strata) for j in classes}

    no_var = sorted(s for s in strata if n_i[s] < 2)

    def var_term(s, j):
        # n < 2 olan tabakanın varyansı tahmin edilemez: 0 alınır ve 'varyans_disi_tabakalar'da raporlanır
        q = n_ij[(s, j)] / n_i[s]
        return q * (1 - q) / (n_i[s] - 1) if n_i[s] > 1 else 0.0

    oa = sum(p[(c, c)] for c in strata if c in classes)
    v_oa = [W[s] ** 2 * var_term(s, s) for s in strata]
    out: dict[str, Any] = {
        "toplam_alan_ha": round(A, 1),
        "genel_dogruluk": oa,
        "genel_dogruluk_ga": z * float(np.sqrt(sum(v_oa))),
        "varyans_disi_tabakalar": {s: n_i[s] for s in no_var},
        "siniflar": {},
    }
    for j in classes:
        ua = n_ij[(j, j)] / n_i[j] if j in strata else None
        ua_ci = z * float(np.sqrt(var_term(j, j))) if j in strata and n_i[j] > 1 else None
        terms = [W[s] ** 2 * var_term(s, j) for s in strata]
        area_se = None if None in terms else float(np.sqrt(sum(terms)))
        pa = p[(j, j)] / pj[j] if j in strata and pj[j] > 0 else None
        pa_ci = None
        if pa is not None:
            N = {s: stratum_area_ha[s] for s in strata}
            Nj_hat = sum(N[s] * n_ij[(s, j)] / n_i[s] for s in strata)
            t1 = N[j] ** 2 * (1 - pa) ** 2 * (var_term(j, j) or 0.0)
            t2 = pa ** 2 * sum(N[s] ** 2 * (var_term(s, j) or 0.0) for s in strata if s != j)
            pa_ci = z * float(np.sqrt((t1 + t2) / Nj_hat ** 2)) if Nj_hat > 0 else None
        out["siniflar"][j] = {
            "harita_alani_ha": round(stratum_area_ha.get(j, 0.0), 1),
            "kestirilen_alan_ha": round(A * pj[j], 1),
            "alan_ga_ha": None if area_se is None else round(z * A * area_se, 1),
            "kullanici_dogrulugu": ua, "kullanici_ga": ua_ci,
            "uretici_dogrulugu": pa, "uretici_ga": pa_ci,
        }
    return out


def binary_metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Değişim / değişim yok (2 × 2): tahminde degisim_yok dışındaki her tür 'değişim' sayılır.

    karisiklik: [[ref değişim → tahmin değişim, → yok], [ref yok → değişim, → yok]].
    """
    tp = sum(r["ref"] != NO_CHANGE and r["pred"] != NO_CHANGE for r in records)
    fn = sum(r["ref"] != NO_CHANGE and r["pred"] == NO_CHANGE for r in records)
    fp = sum(r["ref"] == NO_CHANGE and r["pred"] != NO_CHANGE for r in records)
    tn = sum(r["ref"] == NO_CHANGE and r["pred"] == NO_CHANGE for r in records)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    n = tp + fn + fp + tn
    return {"karisiklik": [[tp, fn], [fp, tn]], "kesinlik": prec, "duyarlilik": rec, "f1": f1,
            "dogruluk": (tp + tn) / n if n else None, "n": n}


def water_census(points: Sequence[dict[str, Any]], labels: Sequence[dict[str, str]]) -> dict[str, Any]:
    """Su doğrulama seti (sayım): her tahmin türü için etiketli/doğru/yanlış alarm sayısı.

    Doğru = referans sınıf tahmin türüyle aynı. 'emin_degilim' ayrı sayılır. Alan ağırlıklı kestirime katılmaz.
    """
    lab = {r["nokta_id"]: r for r in labels}
    by: dict[str, Counter] = defaultdict(Counter)
    rows = []
    for p in points:
        r = lab.get(p["nokta_id"])
        t = by[p["tahmin_tur"]]
        t["poligon"] += 1
        t["alan_ha"] += float(p.get("alan_ha") or 0)
        if not r or not r.get("gercek_degisim"):
            t["etiketsiz"] += 1
            continue
        if r["gercek_degisim"].lower() == UNSURE:
            t["emin_degilim"] += 1
            continue
        ref = reference_class(r)
        t["etiketli"] += 1
        t["dogru"] += ref == p["tahmin_tur"]
        t["degisim_yok"] += ref == NO_CHANGE
        rows.append({"nokta_id": p["nokta_id"], "tahmin": p["tahmin_tur"], "ref": ref,
                     "tahmin_yil": p.get("tahmin_yil"), "katman": p.get("katman")})
    tot = Counter()
    for c in by.values():
        tot.update(c)
    return {"turler": {k: dict(v) for k, v in sorted(by.items())}, "toplam": dict(tot), "noktalar": rows}


def error_kind(ref: str, pred: str) -> str:
    """Ayrışma türü: 'yanlis_alarm' (ref yok, tahmin değişim), 'kacirma' (ref değişim, tahmin yok), 'tur_hatasi'."""
    if ref == NO_CHANGE and pred != NO_CHANGE:
        return "yanlis_alarm"
    if ref != NO_CHANGE and pred == NO_CHANGE:
        return "kacirma"
    return "tur_hatasi"


def rank_disagreements(records: Sequence[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Etiketle tahminin ayrıştığı noktalardan en önemli n tanesi.

    Nokta ağırlığı = temsil ettiği alan (tabaka alanı / tabakadaki etiketli nokta; Olofsson ağırlığı).
    Ayrışmalar (ref, tahmin) gruplarına ayrılır; grup önemi = ağırlıklar toplamı (haritanın o hata yüzünden
    yanlış gösterdiği kestirilen alan). Önce her değişim/değişim yok grubu (yanlış alarm, kaçırma) birer nokta
    alır; kalan yerler D'Hondt ile grup önemine orantılı dağıtılır. Tür hataları (ikisi de değişim diyor) ancak
    bu gruplar tükenince gelir. Grup içinde ağırlık büyükten küçüğe, eşitlikte AOI'ler sırayla.
    """
    n_s = Counter(r["stratum"] for r in records)
    bad = [{**r, "agirlik_ha": float(r["stratum_area_ha"]) / n_s[r["stratum"]],
            "hata": error_kind(r["ref"], r["pred"])} for r in records if r["ref"] != r["pred"]]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in bad:
        groups[(r["ref"], r["pred"])].append(r)
    for k, g in groups.items():
        rank: Counter = Counter()
        g.sort(key=lambda r: (-r["agirlik_ha"], r["aoi"], r["nokta_id"]))
        for r in g:                                  # aynı ağırlıkta AOI'ler sırayla gelsin
            r["_sira"] = rank[(r["agirlik_ha"], r["aoi"])]
            rank[(r["agirlik_ha"], r["aoi"])] += 1
        g.sort(key=lambda r: (-r["agirlik_ha"], r["_sira"], r["aoi"], r["nokta_id"]))
    imp = {k: sum(r["agirlik_ha"] for r in g) for k, g in groups.items()}
    taken: Counter = Counter()
    out: list[dict] = []
    for tier in (False, True):                       # önce ikili hatalar, sonra tür hataları
        keys = sorted((k for k in groups if (groups[k][0]["hata"] == "tur_hatasi") == tier),
                      key=lambda k: (-imp[k], k))
        for k in keys:                               # her gruptan bir nokta
            if len(out) < n:
                out.append(groups[k][0])
                taken[k] = 1
        while len(out) < n:
            avail = [k for k in keys if taken[k] < len(groups[k])]
            if not avail:
                break
            k = max(avail, key=lambda k: (imp[k] / (taken[k] + 1), k))
            out.append(groups[k][taken[k]])
            taken[k] += 1
    for r in out:
        r.pop("_sira", None)
    pos = {k: i for i, k in enumerate(sorted(groups, key=lambda k: (groups[k][0]["hata"] == "tur_hatasi",
                                                                    -imp[k], k)))}
    return sorted(out, key=lambda r: (pos[(r["ref"], r["pred"])], -r["agirlik_ha"]))


def error_summary(records: Sequence[dict[str, Any]]) -> list[tuple[str, str, str, int]]:
    """Tüm ayrışmaların (hata türü, ref, tahmin, sayı) listesi, çoktan aza."""
    c = Counter((error_kind(r["ref"], r["pred"]), r["ref"], r["pred"]) for r in records if r["ref"] != r["pred"])
    return [(h, a, b, k) for (h, a, b), k in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]


def format_olofsson(rep: dict[str, Any]) -> str:
    """Olofsson sonuçlarını markdown olarak biçimlendirir."""
    if not rep:
        return "Olofsson: hesaplanacak tabaka yok."
    pct = lambda v, ci=None: "-" if v is None else (f"%{100 * v:.0f}" + ("" if ci is None else f" ± {100 * ci:.0f}"))  # noqa: E731
    lines = [f"Alan ağırlıklı (Olofsson) genel doğruluk: {pct(rep['genel_dogruluk'], rep['genel_dogruluk_ga'])} "
             f"(toplam alan {rep['toplam_alan_ha']:.0f} ha, %95 GA)", "",
             "| sınıf | harita alanı (ha) | kestirilen alan (ha) ± %95 GA | kullanıcı d. | üretici d. |",
             "|---|---|---|---|---|"]
    for c, v in rep["siniflar"].items():
        ci = "" if v["alan_ga_ha"] is None else f" ± {v['alan_ga_ha']:.0f}"
        lines.append(f"| {c} | {v['harita_alani_ha']:.0f} | {v['kestirilen_alan_ha']:.0f}{ci} | "
                     f"{pct(v['kullanici_dogrulugu'], v['kullanici_ga'])} | "
                     f"{pct(v['uretici_dogrulugu'], v['uretici_ga'])} |")
    if rep.get("varyans_disi_tabakalar"):
        lines += ["", "Not: n < 2 olan tabakaların varyans terimi 0 alındı (GA'lar bu tabakalar için eksik): "
                  + ", ".join(f"{s} (n = {k})" for s, k in rep["varyans_disi_tabakalar"].items())]
    return "\n".join(lines)


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
    b = rep.get("ikili")
    if b:
        (tp, fn), (fp, tn) = b["karisiklik"]
        lines += ["", "Değişim / değişim yok (satır = referans, sütun = tahmin)", "",
                  "| ref \\ tahmin | değişim | değişim yok |", "|---|---|---|",
                  f"| değişim | {tp} | {fn} |", f"| değişim yok | {fp} | {tn} |", "",
                  f"Değişim kesinliği {pct(b['kesinlik'])}, duyarlılığı {pct(b['duyarlilik'])}, F1 {pct(b['f1'])}, "
                  f"ikili doğruluk {pct(b['dogruluk'])}"]
    bm = rep["sinif_metrikleri"].get("yapilasma_olasi")
    if bm:
        lines += ["", f"**Yapılaşma:** kesinlik (kullanıcı d.) {pct(bm['kullanici_dogrulugu'])} "
                      f"({bm['tahmin_n']} tahmin), duyarlılık (üretici d.) {pct(bm['uretici_dogrulugu'])} "
                      f"({bm['referans_n']} referans), F1 {pct(bm['f1'])}"]
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
