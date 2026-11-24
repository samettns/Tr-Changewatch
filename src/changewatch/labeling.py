"""Kör etiketleme: zaman serisi çipleri, su doğrulama seti ve tkinter etiketleme arayüzü.

Arayüz sistemin tahminini, tabakayı, AOI'yi ve nokta kimliğini göstermez; çip dosya adları rastgele
belirteçtir. Tek soru: E evet (tür varsayılan yapılaşma) / H hayır / U emin değilim; yıl isteğe bağlı.
Her girişten sonra etiket CSV'si atomik olarak yeniden yazılır; setin dışındaki satırlar (ör. kalibrasyon) korunur.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import webbrowser
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from changewatch.validate import LABEL_FIELDS, UNSURE

TYPES = [  # (tuş, kod, ekran adı)
    ("y", "yapilasma_olasi", "yapılaşma"),
    ("b", "bitki_kaybi", "bitki kaybı"),
    ("k", "su_kazanimi", "su kazanımı"),
    ("l", "su_kaybi", "su kaybı"),
    ("d", "diger", "diğer"),
]
UNKNOWN_YEAR = "bilinmiyor"
DEFAULT_TYPE = "yapilasma_olasi"
QUESTION = "Bu noktada 2017'den bugüne yeni bina, şantiye veya yol yapıldı mı?"
ANSWERS = ("evet", "hayir", UNSURE)


def chip_token(salt: str, point_id: str) -> str:
    """Çip dosya adı: tahmin/tabaka/AOI/kimlik içermeyen kararlı rastgele belirteç."""
    return hashlib.sha1(f"{salt}:{point_id}".encode()).hexdigest()[:12]


def year_for_key(key: str, years: Sequence[int]) -> str | None:
    """Rakam tuşu → yılın son hanesi eşleşen yıl (8 → 2018, 0 → 2020, 6 → 2026); x/? → bilinmiyor."""
    if key in ("x", "question", "?"):
        return UNKNOWN_YEAR
    if len(key) == 1 and key.isdigit():
        for y in years:
            if y % 10 == int(key):
                return str(y)
    return None


def shuffled_order(ids: Sequence[str], seed: int) -> list[str]:
    """Sabit seed ile karışık sıra (tabakaya göre dizilmiş kimlikler sırayı ele vermesin)."""
    ids = list(ids)
    perm = np.random.default_rng(seed).permutation(len(ids))
    return [ids[i] for i in perm]


def read_label_rows(path: Path, ids: Sequence[str], aoi_of: dict[str, str]) -> dict[str, dict[str, str]]:
    """Etiket CSV'sini okur: dosyadaki tüm satırlar (sırası korunur) + dosyada olmayan set noktaları (boş)."""
    rows: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("nokta_id"):
                    rows[r["nokta_id"]] = {k: (r.get(k) or "").strip() for k in LABEL_FIELDS}
    for i in ids:
        rows.setdefault(i, {"nokta_id": i, "aoi": aoi_of.get(i, ""), "gercek_degisim": "", "gercek_tur": "",
                            "gercek_yil": "", "not": ""})
    return rows


def write_label_rows(path: Path, rows: dict[str, dict[str, str]]) -> None:
    """Tüm satırları atomik yazar (önce geçici dosya, sonra yer değiştirme)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        w.writeheader()
        for r in rows.values():
            w.writerow({k: r.get(k, "") for k in LABEL_FIELDS})
    os.replace(tmp, path)


def normalize_entry(entry: dict[str, str]) -> dict[str, str]:
    """Kayıt öncesi: evet → tür boşsa yapılaşma, yıl boşsa 'bilinmiyor'; hayır / emin değilim → tür ve yıl boş."""
    e = dict(entry)
    if e.get("gercek_degisim") == "evet":
        e["gercek_tur"] = e.get("gercek_tur") or DEFAULT_TYPE
        e["gercek_yil"] = e.get("gercek_yil") or UNKNOWN_YEAR
    elif e.get("gercek_degisim") in ("hayir", UNSURE):
        e["gercek_tur"] = e["gercek_yil"] = ""
    return e


def validate_entry(entry: dict[str, str]) -> str | None:
    """Tutarlılık: hata mesajı ya da None (yıl isteğe bağlı)."""
    d = entry.get("gercek_degisim")
    if d not in ANSWERS:
        return "Önce cevaplayın: E (evet) / H (hayır) / U (emin değilim)."
    if d == "evet" and not entry.get("gercek_tur"):
        return "Değişim türünü seçin: Y / B / K / L / D."
    return None


def is_labeled(row: dict[str, str]) -> bool:
    return validate_entry(row) is None


def water_validation_points(features_by_layer: dict[str, list[tuple[Any, dict]]], aoi: str) -> list[dict]:
    """Su poligonlarının içinden birer temsilî nokta (WGS84 geometri; poligon kimliği ve katman tutulur)."""
    out = []
    for layer, feats in features_by_layer.items():
        for g, p in feats:
            if p["tur"] not in ("su_kazanimi", "su_kaybi", "sulak_alan_belirsiz"):
                continue
            pt = g.representative_point()
            out.append({"aoi": aoi, "kaynak_id": p["id"], "katman": layer, "tahmin_tur": p["tur"],
                        "tahmin_yil": p["degisim_yili"], "alan_ha": p["alan_ha"], "lon": pt.x, "lat": pt.y})
    out.sort(key=lambda r: r["kaynak_id"])
    for k, r in enumerate(out, start=1):
        r["nokta_id"] = f"S{k:02d}"
    return out


def maps_url(lat: float, lon: float, zoom: int = 18) -> str:
    """Google Haritalar: noktada iğne, uydu görünümü."""
    return f"https://maps.google.com/?q={lat:.6f},{lon:.6f}&t=k&z={zoom}"


def load_label_set(index_path: Path) -> dict[str, Any]:
    """label-prep'in yazdığı set dizini: noktalar (id, aoi, lat, lon, çip), etiket CSV yolu, yıllar, seed, birim."""
    return json.loads(Path(index_path).read_text(encoding="utf-8"))


def run_app(index_path: Path) -> None:  # pragma: no cover - arayüz
    """tkinter etiketleme arayüzü."""
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    s = load_label_set(index_path)
    pts = {p["nokta_id"]: p for p in s["points"]}
    ids = [p["nokta_id"] for p in s["points"]]
    order = shuffled_order(ids, int(s["seed"]))
    years = list(s["years"])
    unit = s.get("unit", "nokta")
    labels_path = Path(s["labels"])
    rows = read_label_rows(labels_path, ids, {i: pts[i]["aoi"] for i in ids})
    start = next((k for k, i in enumerate(order) if not is_labeled(rows[i])), 0)
    tname = {c: n for _, c, n in TYPES}
    answer_txt = {"evet": "EVET", "hayir": "HAYIR", UNSURE: "EMİN DEĞİLİM"}
    answer_fg = {"evet": "#b00020", "hayir": "#1a7f37", UNSURE: "#9a6700"}

    root = tk.Tk()
    root.title("TR-ChangeWatch etiketleme")
    state: dict[str, Any] = {"pos": start, "entry": {}, "img": None, "dirty": False}

    top = tk.Label(root, font=("Segoe UI", 11), anchor="w")
    top.pack(fill="x", padx=10, pady=(6, 0))
    tk.Label(root, text=QUESTION, font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x", padx=10, pady=(2, 4))
    canvas = tk.Label(root)
    canvas.pack(padx=10)
    cur = tk.Label(root, font=("Segoe UI", 13, "bold"), anchor="w", justify="left")
    cur.pack(fill="x", padx=10, pady=(4, 0))
    msg = tk.Label(root, font=("Segoe UI", 10), fg="#b35900", anchor="w")
    msg.pack(fill="x", padx=10)
    help_txt = ("E evet · H hayır · U emin değilim   |   başka tür (isteğe bağlı): Y yapılaşma · B bitki kaybı · "
                "K su kazanımı · L su kaybı · D diğer   |   yıl (isteğe bağlı): son hane 8=2018 … 6=2026 · "
                "X bilinmiyor   |   N not · Enter kaydet+sonraki · ←/→ gezin · G Google Haritalar")
    tk.Label(root, text=help_txt, font=("Segoe UI", 9), fg="#555", wraplength=880, justify="left").pack(
        fill="x", padx=10, pady=(0, 4))
    bar = tk.Frame(root)
    bar.pack(pady=(0, 8))

    def counts() -> tuple[int, int]:
        done = [rows[i] for i in ids if is_labeled(rows[i])]
        return len(done), sum(r["gercek_degisim"] == UNSURE for r in done)

    def show() -> None:
        pid = order[state["pos"]]
        state["entry"] = {k: rows[pid].get(k, "") for k in ("gercek_degisim", "gercek_tur", "gercek_yil", "not")}
        state["dirty"] = False
        state["img"] = tk.PhotoImage(file=pts[pid]["chip"])
        canvas.configure(image=state["img"])
        msg.configure(text="")
        refresh()

    def refresh() -> None:
        pos = state["pos"]
        e = state["entry"]
        n, n_u = counts()
        top.configure(text=f"Etiketlenen: {n} / {len(ids)} {unit}" + (f"  (emin değilim: {n_u})" if n_u else "")
                      + f"    ·    sıra {pos + 1} / {len(ids)}"
                      + ("    ·    ✓ kayıtlı" if is_labeled(rows[order[pos]]) else ""))
        d = e.get("gercek_degisim", "")
        txt = f"Cevap: {answer_txt.get(d, '—')}"
        if d == "evet":
            txt += (f"    Tür: {tname.get(e.get('gercek_tur') or DEFAULT_TYPE, '—')}    "
                    f"Yıl: {e.get('gercek_yil') or UNKNOWN_YEAR}")
        if e.get("not"):
            txt += f"    Not: {e['not']}"
        cur.configure(text=txt, fg=answer_fg.get(d, "#1f2328"))

    def commit() -> bool:
        e = normalize_entry(state["entry"])
        err = validate_entry(e)
        if err:
            msg.configure(text=err)
            return False
        rows[order[state["pos"]]].update(e)
        write_label_rows(labels_path, rows)
        return True

    def save_and_next(_=None) -> None:
        if not state["dirty"] and is_labeled(rows[order[state["pos"]]]):
            move(1, save=False)                     # dokunulmamış eski etiket aynen kalır
            return
        if not commit():
            return
        if counts()[0] == len(ids):
            messagebox.showinfo("Tamamlandı", f"Tüm {unit} etiketlendi. Kaydedildi: {labels_path}")
        move(1, save=False)

    def move(step: int, save: bool = True) -> None:
        # gezinirken de: değiştirilmiş ve geçerli giriş kaybolmasın
        if save and state["dirty"] and validate_entry(normalize_entry(state["entry"])) is None:
            commit()
        state["pos"] = min(max(state["pos"] + step, 0), len(order) - 1)
        show()

    def set_field(k: str, v: str) -> None:
        e = state["entry"]
        e[k] = v
        state["dirty"] = True
        if k == "gercek_degisim":
            if v == "evet":
                e["gercek_tur"] = e.get("gercek_tur") or DEFAULT_TYPE
            else:
                e["gercek_tur"] = e["gercek_yil"] = ""
        if k in ("gercek_tur", "gercek_yil") and e.get("gercek_degisim") != "evet":
            e["gercek_degisim"] = "evet"
            e["gercek_tur"] = e.get("gercek_tur") or DEFAULT_TYPE
        refresh()

    def note(_=None) -> None:
        v = simpledialog.askstring("Not", "Not (isteğe bağlı):", initialvalue=state["entry"].get("not", ""),
                                   parent=root)
        if v is not None:
            set_field("not", v.replace("\n", " ").strip())

    def open_maps(_=None) -> None:
        p = pts[order[state["pos"]]]
        webbrowser.open(maps_url(p["lat"], p["lon"]))

    def on_key(ev) -> None:
        k = ev.keysym.lower()
        if k == "e":
            set_field("gercek_degisim", "evet")
        elif k == "h":
            set_field("gercek_degisim", "hayir")
        elif k == "u":
            set_field("gercek_degisim", UNSURE)
        elif k in {t[0] for t in TYPES}:
            set_field("gercek_tur", next(c for key, c, _ in TYPES if key == k))
        elif k == "n":
            note()
        elif k == "g":
            open_maps()
        else:
            y = year_for_key(k if k != "question" else "?", years)
            if y:
                set_field("gercek_yil", y)

    for txt, fn in (("◀ Önceki", lambda: move(-1)), ("Kaydet + sonraki ▶ (Enter)", save_and_next),
                    ("Sonraki ▶", lambda: move(1)), ("Google Haritalar'da aç (G)", open_maps), ("Not (N)", note)):
        tk.Button(bar, text=txt, command=fn).pack(side="left", padx=4)
    root.bind("<Key>", on_key)
    root.bind("<Return>", save_and_next)
    root.bind("<Left>", lambda _: move(-1))
    root.bind("<Right>", lambda _: move(1))
    show()
    root.mainloop()
