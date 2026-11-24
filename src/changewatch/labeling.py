"""Kör etiketleme: zaman serisi çipleri, su doğrulama seti ve tkinter etiketleme arayüzü.

Arayüz sistemin tahminini, tabakayı, AOI'yi ve nokta kimliğini göstermez; çip dosya adları rastgele
belirteçtir. Her girişten sonra etiket CSV'si atomik olarak yeniden yazılır.
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

from changewatch.validate import LABEL_FIELDS

TYPES = [  # (tuş, kod, ekran adı)
    ("y", "yapilasma_olasi", "yapılaşma"),
    ("b", "bitki_kaybi", "bitki kaybı"),
    ("k", "su_kazanimi", "su kazanımı"),
    ("l", "su_kaybi", "su kaybı"),
    ("d", "diger", "diğer"),
]
UNKNOWN_YEAR = "bilinmiyor"


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
    """Etiket CSV'sini okur; olmayan noktalar boş satırla tamamlanır."""
    rows = {i: {"nokta_id": i, "aoi": aoi_of.get(i, ""), "gercek_degisim": "", "gercek_tur": "", "gercek_yil": "",
                "not": ""} for i in ids}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("nokta_id") in rows:
                    rows[r["nokta_id"]].update({k: (r.get(k) or "").strip() for k in LABEL_FIELDS})
    return rows


def write_label_rows(path: Path, rows: dict[str, dict[str, str]], ids: Sequence[str]) -> None:
    """Etiketleri atomik yazar (önce geçici dosya, sonra yer değiştirme)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        w.writeheader()
        for i in ids:
            w.writerow({k: rows[i].get(k, "") for k in LABEL_FIELDS})
    os.replace(tmp, path)


def validate_entry(entry: dict[str, str]) -> str | None:
    """Kayıttan önce tutarlılık: hata mesajı ya da None."""
    d = entry.get("gercek_degisim")
    if d not in ("evet", "hayir"):
        return "Önce değişim var mı seçin: E (evet) / H (hayır)."
    if d == "evet" and not entry.get("gercek_tur"):
        return "Değişim türünü seçin: Y / B / K / L / D."
    if d == "evet" and not entry.get("gercek_yil"):
        return "İlk görüldüğü yılı seçin: 8 9 0 1 2 3 4 5 6 (yılın son hanesi) ya da X (bilinmiyor)."
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
    """Google Haritalar uydu görünümü."""
    return f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},{zoom}z/data=!3m1!1e3"


def load_label_set(index_path: Path) -> dict[str, Any]:
    """label-prep'in yazdığı set dizini: noktalar (id, aoi, lat, lon, çip), etiket CSV yolu, yıllar, seed."""
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
    labels_path = Path(s["labels"])
    rows = read_label_rows(labels_path, ids, {i: pts[i]["aoi"] for i in ids})
    start = next((k for k, i in enumerate(order) if not is_labeled(rows[i])), 0)

    root = tk.Tk()
    root.title(f"TR-ChangeWatch etiketleme — {s['name']}")
    state = {"pos": start, "entry": {}, "img": None}

    top = tk.Label(root, font=("Segoe UI", 12, "bold"), anchor="w")
    top.pack(fill="x", padx=10, pady=(8, 2))
    canvas = tk.Label(root)
    canvas.pack(padx=10)
    cur = tk.Label(root, font=("Segoe UI", 12), anchor="w", justify="left")
    cur.pack(fill="x", padx=10, pady=4)
    msg = tk.Label(root, font=("Segoe UI", 10), fg="#b35900", anchor="w")
    msg.pack(fill="x", padx=10)
    help_txt = ("E evet · H hayır  |  tür: Y yapılaşma · B bitki kaybı · K su kazanımı · L su kaybı · D diğer  |  "
                "yıl: son hane (8=2018 … 0=2020 … 6=2026) · X bilinmiyor  |  N not  |  "
                "Enter kaydet+sonraki · ←/→ gezin · G Google Haritalar")
    tk.Label(root, text=help_txt, font=("Segoe UI", 9), fg="#555", wraplength=900, justify="left").pack(
        fill="x", padx=10, pady=(0, 4))
    bar = tk.Frame(root)
    bar.pack(pady=(0, 8))

    def labeled_count() -> int:
        return sum(is_labeled(rows[i]) for i in ids)

    def show() -> None:
        pid = order[state["pos"]]
        state["entry"] = {k: rows[pid].get(k, "") for k in ("gercek_degisim", "gercek_tur", "gercek_yil", "not")}
        state["img"] = tk.PhotoImage(file=pts[pid]["chip"])
        canvas.configure(image=state["img"])
        msg.configure(text="")
        refresh()

    def refresh() -> None:
        pos = state["pos"]
        e = state["entry"]
        top.configure(text=f"Etiketlenen: {labeled_count()} / {len(ids)}    ·    nokta {pos + 1} / {len(ids)}"
                           + ("    ·    ✓ kayıtlı" if is_labeled(rows[order[pos]]) else ""))
        tname = {c: n for _, c, n in TYPES}.get(e.get("gercek_tur", ""), "—")
        cur.configure(text=f"Değişim: {e.get('gercek_degisim') or '—'}    Tür: {tname}    "
                           f"İlk görüldüğü yıl: {e.get('gercek_yil') or '—'}    Not: {e.get('not') or '—'}")

    def save_and_next(_=None) -> None:
        e = dict(state["entry"])
        if e.get("gercek_degisim") == "hayir":
            e["gercek_tur"] = e["gercek_yil"] = ""
        err = validate_entry(e)
        if err:
            msg.configure(text=err)
            return
        rows[order[state["pos"]]].update(e)
        write_label_rows(labels_path, rows, ids)
        if labeled_count() == len(ids):
            messagebox.showinfo("Tamamlandı", f"Tüm noktalar etiketlendi. Kaydedildi: {labels_path}")
        move(1)

    def move(step: int) -> None:
        # gezinirken de: tam ve geçerli, kaydedilmemiş giriş kaybolmasın
        e = dict(state["entry"])
        row = rows[order[state["pos"]]]
        if validate_entry(e) is None and any(row.get(k, "") != e.get(k, "") for k in e):
            row.update(e)
            write_label_rows(labels_path, rows, ids)
        state["pos"] = min(max(state["pos"] + step, 0), len(order) - 1)
        show()

    def set_field(k: str, v: str) -> None:
        state["entry"][k] = v
        if k == "gercek_degisim" and v == "hayir":
            state["entry"]["gercek_tur"] = state["entry"]["gercek_yil"] = ""
        if k in ("gercek_tur", "gercek_yil") and not state["entry"].get("gercek_degisim"):
            state["entry"]["gercek_degisim"] = "evet"
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
