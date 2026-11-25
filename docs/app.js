/* TR-ChangeWatch web haritası: statik, sunucusuz (GitHub Pages). Veri: data/index.json, data/<aoi>/... */
"use strict";

const TYPES = {
  yapilasma_olasi: { ad: "Yapılaşma (olası)", renk: "#f47230" },
  bitki_kaybi: { ad: "Bitki kaybı", renk: "#00b894" },
  belirsiz: { ad: "Belirsiz değişim", renk: "#6a4ce2" },
};
const UYARI = { ad: "Aylık ön uyarı", renk: "#dc3c3d" };
const GUVEN = { yuksek: "yüksek", orta: "orta", dusuk: "düşük" };
const KANIT = {
  sinyal: ["Sinyal", (v) => ({ ikisi: "spektral + doku", spektral: "spektral", doku: "doku" }[v] || v)],
  skor: ["Kırılma skoru", (v) => fmt(v, 1)],
  sonrasi_yil_sayisi: ["Kırılmadan sonra gözlenen yıl", (v) => v],
  dNDVI: ["ΔNDVI (bitki)", (v) => sgn(v)],
  dNDBI: ["ΔNDBI", (v) => sgn(v)],
  dBSI: ["ΔBSI (çıplak toprak)", (v) => sgn(v)],
  dMNDWI: ["ΔMNDWI (su)", (v) => sgn(v)],
  doku_artisi: ["Doku artışı", (v) => sgn(v, 4)],
  doku_artisi_payi: ["Doku artan piksel payı", (v) => pct(v)],
  gecerli_gozlem_sayisi: ["Ort. geçerli gözlem", (v) => fmt(v, 1)],
  dusuk_gozlem: ["Düşük gözlem (önceki yıl)", (v) => `ort. ${fmt(v.ort_gozlem, 1)} gözlem; <3 gözlemli piksel ${pct(v.dusuk_piksel_orani)}`],
};

const state = { index: null, aoi: null, stats: null, changes: null, monitor: null, y0: 2018, y1: 2025,
  on: {}, izleme: false, uyari: true, compare: true, swipe: 0.5 };
const layers = {};
let map, base, before, after;

function fmt(v, d = 0) { return v == null ? "–" : Number(v).toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
function pct(v) { return v == null ? "–" : "%" + fmt(100 * v); }
function sgn(v, d = 3) { return v == null ? "–" : (v > 0 ? "+" : "") + fmt(v, d); }
const $ = (s) => document.querySelector(s);
const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });

/* ---------------------------------------------------------------- harita */
function initMap() {
  map = L.map("map", { zoomControl: true, zoomSnap: 0.25, attributionControl: true });
  // açık popup kaydırıcının altında kalmasın
  map.on("popupopen", () => $("#swipe").classList.add("behind"));
  map.on("popupclose", () => $("#swipe").classList.remove("behind"));
  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları' });
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19, attribution: "Uydu: &copy; Esri, Maxar, Earthstar Geographics ve GIS kullanıcı topluluğu" });
  sat.addTo(map);
  base = { "Uydu (Esri)": sat, "Harita (OSM)": osm };
  L.control.layers(base, null, { position: "topright" }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  map.attributionControl.addAttribution("Önizleme: Copernicus Sentinel-2 (değiştirilmiş)");
  for (const p of ["before", "after"]) { map.createPane(p); map.getPane(p).style.zIndex = 250; }
  map.createPane("polys"); map.getPane("polys").style.zIndex = 420;
  ["move", "zoom", "resize", "zoomanim", "viewreset"].forEach((e) => map.on(e, clipPanes));
}

function styleFor(f) {
  const p = f.properties;
  const t = TYPES[p.tur] || { renk: "#888" };
  const iz = p.durum === "izlemede";
  return { pane: "polys", color: iz ? t.renk : "#1b1b1b", weight: iz ? 2 : 0.8, dashArray: iz ? "4 3" : null,
    fillColor: t.renk, fillOpacity: iz ? 0.25 : 0.6, opacity: 1 };
}

function popupHtml(p) {
  const t = TYPES[p.tur] || { ad: p.tur, renk: "#888" };
  const exp = state.index.deneysel_turler.includes(p.tur) ? ' <span class="badge">deneysel</span>' : "";
  const durum = p.durum === "izlemede" ? "izlemede (henüz doğrulanmadı)" : p.durum === "on_uyari" ? "aylık ön uyarı" : "kalıcı";
  const rows = Object.entries(p.kanit || {}).filter(([k]) => KANIT[k])
    .map(([k, v]) => `<tr><td>${KANIT[k][0]}</td><td>${KANIT[k][1](v)}</td></tr>`).join("");
  return `<div class="pop"><h4><span class="swatch" style="background:${t.renk}"></span>${t.ad}${exp}</h4>
    <table>
      <tr><td>Değişim yılı</td><td><strong>${p.degisim_yili}</strong> (${p.onceki_yil ?? p.degisim_yili - 1} → ${p.degisim_yili})</td></tr>
      <tr><td>Alan</td><td>${fmt(p.alan_ha, 2)} ha</td></tr>
      <tr><td>Güven</td><td>${GUVEN[p.guven] || p.guven}</td></tr>
      <tr><td>Durum</td><td>${durum}</td></tr>
    </table>
    ${rows ? `<details open><summary>Kanıtlar</summary><table>${rows}</table></details>` : ""}
    <p class="hint">Güven, kuralın kendi tahminidir; doğruluk için "Yöntem ve doğruluk" paneline bakın.</p></div>`;
}

function monitorPopup(p) {
  const d = (x) => x.split("-").reverse().join(".");
  const k = p.kanit || {};
  return `<div class="pop"><h4><span class="swatch" style="background:${UYARI.renk}"></span>${UYARI.ad} <span class="badge">doğrulanmadı</span></h4>
    <table>
      <tr><td>Dönem</td><td>${d(p.donem[0])} – ${d(p.donem[1])}</td></tr>
      <tr><td>Karşılaştırma</td><td>${d(p.karsilastirma[0])} – ${d(p.karsilastirma[1])}</td></tr>
      <tr><td>Alan</td><td>${fmt(p.alan_ha, 2)} ha</td></tr>
      <tr><td>Spektral değişim (z)</td><td>${fmt(k.cva_z, 1)}</td></tr>
      <tr><td>Doku artışı (z)</td><td>${fmt(k.doku_z, 1)}</td></tr>
      <tr><td>ΔNDVI</td><td>${sgn(k.dNDVI)}</td></tr>
    </table>
    <p class="hint">Son 3 ay ile önceki yılın aynı 3 ayı karşılaştırıldı. Kalibre edilmemiş bir ön uyarıdır; yıllık analizde doğrulanana kadar değişim sayılmaz.</p></div>`;
}

function rebuildPolys() {
  Object.values(layers).forEach((l) => map.removeLayer(l));
  const feats = state.changes.features;
  const keep = (f) => {
    const p = f.properties;
    if (!state.on[p.tur]) return false;
    if (p.durum === "izlemede") return state.izleme;
    return p.degisim_yili >= state.y0 && p.degisim_yili <= state.y1;
  };
  layers.main = L.geoJSON({ type: "FeatureCollection", features: feats.filter(keep) }, {
    style: styleFor, onEachFeature: (f, l) => l.bindPopup(() => popupHtml(f.properties), { maxWidth: 320 }) }).addTo(map);
  if (state.monitor && state.uyari) {
    layers.uyari = L.geoJSON(state.monitor, { style: () => ({ pane: "polys", color: UYARI.renk, weight: 2, dashArray: "2 4", fillOpacity: 0.15, fillColor: UYARI.renk }),
      onEachFeature: (f, l) => l.bindPopup(() => monitorPopup(f.properties), { maxWidth: 320 }) }).addTo(map);
  }
  renderLegend();
}

/* ---------------------------------------------------------------- önce/sonra */
function updateCompare() {
  [before, after].forEach((l) => l && map.removeLayer(l));
  before = after = null;
  const sw = $("#swipe");
  const ql = state.stats.onizleme || {};
  const a = String(state.y0 - 1), b = String(state.y1);
  $("#compare-years").textContent = state.compare
    ? `Sol: ${a} yazı · Sağ: ${b} yazı (Sentinel-2 medyan kompozit, 20 m). Kaydırıcıyı sürükleyin.` : "";
  if (!state.compare || !ql[a] || !ql[b]) { sw.hidden = true; clipPanes(); return; }
  const dir = `data/${state.aoi}/`;
  const bnd = state.stats.onizleme_sinir;
  before = L.imageOverlay(dir + ql[a], bnd, { pane: "before", alt: `${a} önizleme` }).addTo(map);
  after = L.imageOverlay(dir + ql[b], bnd, { pane: "after", alt: `${b} önizleme` }).addTo(map);
  $("#swipe-left").textContent = a;
  $("#swipe-right").textContent = b;
  sw.hidden = false;
  clipPanes();
}

let line;
function clipPanes() {
  const size = map.getSize();
  const nw = map.containerPointToLayerPoint([0, 0]);
  const se = map.containerPointToLayerPoint(size);
  const x = nw.x + size.x * state.swipe;
  const on = state.compare && before;
  map.getPane("before").style.clip = on ? `rect(${nw.y}px, ${x}px, ${se.y}px, ${nw.x}px)` : "";
  map.getPane("after").style.clip = on ? `rect(${nw.y}px, ${se.x}px, ${se.y}px, ${x}px)` : "";
  if (!line) { line = document.createElement("div"); line.className = "swipe-line"; $("#swipe").appendChild(line); }
  line.style.left = `${size.x * state.swipe - 1}px`;
}

/* ---------------------------------------------------------------- grafikler (tek seri, SVG) */
const tip = () => $("#tooltip");
function showTip(ev, html) { const t = tip(); t.innerHTML = html; t.hidden = false; t.style.left = ev.clientX + 12 + "px"; t.style.top = ev.clientY - 30 + "px"; }
function hideTip() { tip().hidden = true; }

function niceMax(v) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); const m = v / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; }

function barChart(el, rows, { color, unit = "ha", labelEvery = 1 }) {
  const W = 320, H = 170, L0 = 34, R = 6, T = 14, B = 22;
  const max = niceMax(Math.max(...rows.map((r) => r.v), 0));
  const bw = (W - L0 - R) / rows.length;
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${el.dataset.title || ""}">`;
  s += `<defs><pattern id="hatch-${el.id}" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="${color}" opacity=".25"/><line x1="0" y1="0" x2="0" y2="5" stroke="${color}" stroke-width="2"/></pattern></defs>`;
  for (const g of [0, max / 2, max]) s += `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}"/><text class="axis" x="${L0 - 5}" y="${y(g) + 4}" text-anchor="end">${fmt(g)}</text>`;
  rows.forEach((r, i) => {
    const x = L0 + i * bw + 2, w = Math.max(bw - 4, 2), h = Math.max(y(0) - y(r.v), 0);
    const fill = r.izleme ? `url(#hatch-${el.id})` : color;
    const ry = Math.min(4, w / 2, h);
    s += `<path d="M${x},${y(0)} v${-(h - ry)} q0,${-ry} ${ry},${-ry} h${w - 2 * ry} q${ry},0 ${ry},${ry} v${h - ry} z" fill="${fill}" ${r.izleme ? `stroke="${color}" stroke-dasharray="3 2"` : ""}/>`;
    s += `<rect x="${L0 + i * bw}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent" data-i="${i}"/>`;
    if (i % labelEvery === 0 || r.izleme) s += `<text class="axis" x="${x + w / 2}" y="${H - 6}" text-anchor="middle">${String(r.k).slice(2)}${r.izleme ? "*" : ""}</text>`;
  });
  const peak = rows.reduce((a, r, i) => (r.v > rows[a].v ? i : a), 0);
  if (rows[peak] && rows[peak].v > 0) s += `<text class="val" x="${L0 + peak * bw + bw / 2}" y="${y(rows[peak].v) - 4}" text-anchor="middle">${fmt(rows[peak].v)}</text>`;
  s += "</svg>";
  el.innerHTML = s;
  el.querySelectorAll("rect[data-i]").forEach((hit) => {
    const r = rows[+hit.dataset.i];
    hit.addEventListener("mousemove", (ev) => showTip(ev, `<strong>${r.k}</strong>: ${fmt(r.v, 1)} ${unit}${r.izleme ? " (izlemede)" : ""}`));
    hit.addEventListener("mouseleave", hideTip);
  });
}

function lineChart(el, rows, { color, unit = "ha" }) {
  const W = 320, H = 150, L0 = 34, R = 10, T = 14, B = 22;
  const max = niceMax(Math.max(...rows.map((r) => r.v), 0));
  const x = (i) => L0 + (W - L0 - R) * (i / Math.max(rows.length - 1, 1));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
  for (const g of [0, max / 2, max]) s += `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}"/><text class="axis" x="${L0 - 5}" y="${y(g) + 4}" text-anchor="end">${fmt(g)}</text>`;
  s += `<polyline points="${rows.map((r, i) => `${x(i)},${y(r.v)}`).join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  rows.forEach((r, i) => {
    s += `<circle cx="${x(i)}" cy="${y(r.v)}" r="4" fill="${color}" stroke="var(--surface)" stroke-width="2"/>`;
    if (i % 3 === 0 || i === rows.length - 1) s += `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="middle">${String(r.k).slice(2)}</text>`;
    s += `<rect x="${x(i) - (W - L0 - R) / rows.length / 2}" y="${T}" width="${(W - L0 - R) / rows.length}" height="${H - T - B}" fill="transparent" data-i="${i}"/>`;
  });
  const last = rows[rows.length - 1];
  if (last) s += `<text class="val" x="${x(rows.length - 1)}" y="${y(last.v) - 8}" text-anchor="end">${fmt(last.v)} ${unit}</text>`;
  el.innerHTML = s + "</svg>";
  el.querySelectorAll("rect[data-i]").forEach((hit) => {
    const r = rows[+hit.dataset.i];
    hit.addEventListener("mousemove", (ev) => showTip(ev, `<strong>${r.k}</strong>: ${fmt(r.v, 1)} ${unit}`));
    hit.addEventListener("mouseleave", hideTip);
  });
}

function renderCharts() {
  const st = state.stats, built = st.tur_yil_ha.yapilasma_olasi || {};
  const rows = st.yillar.slice(1).map((yr) => ({ k: yr, v: built[String(yr)] || 0, izleme: yr === st.izleme_yili }));
  $("#chart-built").dataset.title = `${st.ad}: yıllara göre yapılaşma (ha)`;
  barChart($("#chart-built"), rows, { color: TYPES.yapilasma_olasi.renk });
  const ws = st.su_alani_serisi;
  $("#water-section").hidden = !ws;
  if (ws) lineChart($("#chart-water"), ws.yillar.map((r) => ({ k: r.yil, v: r.su_ha })), { color: "#257de0" });
}

/* ---------------------------------------------------------------- panel */
function renderLayersList() {
  const ul = $("#layers");
  ul.innerHTML = "";
  const add = (html) => { const li = document.createElement("li"); li.innerHTML = html; ul.appendChild(li); return li; };
  for (const t of state.index.turler) {
    const exp = state.index.deneysel_turler.includes(t);
    const n = state.stats.poligon_sayisi[t] ?? 0;
    add(`<label class="check"><input type="checkbox" data-t="${t}" ${state.on[t] ? "checked" : ""}>
      <span class="swatch" style="background:${TYPES[t].renk}"></span>${TYPES[t].ad} ${exp ? '<span class="badge">deneysel</span>' : ""}</label>
      <span class="hint" style="margin-left:auto">${n}</span>`);
  }
  add(`<label class="check"><input type="checkbox" id="izleme" ${state.izleme ? "checked" : ""}>
    <span class="swatch dashed" style="border-color:#555"></span>${state.stats.izleme_yili} değişimleri (izlemede)</label>`);
  const ai = state.stats.aylik_izleme;
  if (state.monitor) add(`<label class="check"><input type="checkbox" id="uyari" ${state.uyari ? "checked" : ""}>
    <span class="swatch dashed" style="border-color:${UYARI.renk}"></span>${UYARI.ad} <span class="badge">doğrulanmadı</span></label>
    <span class="hint" style="margin-left:auto">${state.monitor.features.length}</span>`);
  if (ai) add(`<span class="hint">Aylık izleme (${ai.calisma_tarihi}): ${ai.durum === "tamam"
    ? `${ai.donem[0].slice(0, 7)} – ${ai.donem[1].slice(0, 7)} ↔ bir yıl önce, kapsama ${pct(ai.kapsama)}`
    : `atlandı (${ai.neden})`}</span>`);
  ul.querySelectorAll("input[data-t]").forEach((c) => c.addEventListener("change", () => { state.on[c.dataset.t] = c.checked; rebuildPolys(); }));
  $("#izleme").addEventListener("change", (e) => { state.izleme = e.target.checked; rebuildPolys(); });
  const u = $("#uyari"); if (u) u.addEventListener("change", (e) => { state.uyari = e.target.checked; rebuildPolys(); });
}

function renderLegend() {
  const items = state.index.turler.filter((t) => state.on[t]).map((t) => `<div><span class="swatch" style="background:${TYPES[t].renk}"></span>${TYPES[t].ad}</div>`);
  if (state.izleme) items.push(`<div><span class="swatch dashed" style="border-color:#555"></span>${state.stats.izleme_yili}: izlemede</div>`);
  if (state.monitor && state.uyari) items.push(`<div><span class="swatch dashed" style="border-color:${UYARI.renk}"></span>${UYARI.ad}</div>`);
  $("#legend").innerHTML = items.join("") || "<div>Katman seçilmedi</div>";
}

function fillYears() {
  const [a, b] = state.stats.kalici_yillar;
  for (const id of ["#y0", "#y1"]) {
    const s = $(id); s.innerHTML = "";
    for (let yr = a; yr <= b; yr++) s.add(new Option(yr, yr));
  }
  state.y0 = Math.max(a, Math.min(state.y0, b)); state.y1 = Math.max(a, Math.min(state.y1, b));
  $("#y0").value = state.y0; $("#y1").value = state.y1;
}

async function loadAoi(aoi) {
  state.aoi = aoi;
  const dir = `data/${aoi}/`;
  const [stats, changes, monitor] = await Promise.all([getJSON(dir + "stats.json"), getJSON(dir + "changes.geojson"),
    getJSON(dir + "monitor.geojson").catch(() => null)]);
  Object.assign(state, { stats, changes, monitor: monitor && monitor.features && monitor.features.length ? monitor : null });
  $("#aoi-tag").innerHTML = stats.test_aoi
    ? '<span class="tag test">görülmemiş bölge (test)</span> yöntem bu bölgede ayar yapılmadan test edildi'
    : '<span class="tag">geliştirme bölgesi</span> yöntem bu bölgede tasarlandı';
  fillYears();
  renderLayersList();
  rebuildPolys();
  updateCompare();
  renderCharts();
  map.fitBounds(stats.sinir, { padding: [10, 10] });
  history.replaceState(null, "", "#" + aoi);
}

/* ---------------------------------------------------------------- yöntem paneli */
function renderAccuracy() {
  const d = state.index.dogruluk;
  const cols = [...Object.keys(d.gelistirme).sort((a, b) => a.includes("+") - b.includes("+")),
    ...Object.keys(d.test_aoi).sort((a, b) => a.includes("+") - b.includes("+"))];
  const get = (c) => d.gelistirme[c] || d.test_aoi[c];
  const name = (c) => (c.includes("+") ? "birlikte" : (state.index.aoiler.find((a) => a.aoi === c) || { ad: c }).ad.split(/[–( ]/)[0]);
  const nd = Object.keys(d.gelistirme).length, nt = Object.keys(d.test_aoi).length;
  const R = [
    ["n (kesin etiket)", (r) => r.n],
    ["“Emin değilim” (hariç)", (r) => r.emin_degilim ?? "–"],
    ["Değişim kesinliği / duyarlılığı", (r) => `${pct(r.degisim_kesinlik)} / ${pct(r.degisim_duyarlilik)}`],
    ["Yapılaşma kesinliği / duyarlılığı", (r) => `${pct(r.yapilasma_kesinlik)} / ${pct(r.yapilasma_duyarlilik)}`],
    ["Yapılaşma F1", (r) => pct(r.yapilasma_f1)],
    ["Genel doğruluk (alan ağırlıklı, ± %95 GA)", (r) => `${pct(r.olofsson_genel)} ± ${fmt(100 * r.olofsson_genel_ga)}`],
    ["Haritadaki yapılaşma (ha)", (r) => fmt(r.yapilasma_harita_ha)],
    ["Kestirilen yapılaşma (ha, ± %95 GA)", (r) => `${fmt(r.yapilasma_kestirim_ha)} ± ${fmt(r.yapilasma_kestirim_ga_ha)}`],
    ["Kırılma yılı isabeti: tam / ±1", (r) => `${pct(r.yil_tam)} / ${pct(r.yil_pm1)} (${r.yil_n})`],
  ];
  let h = `<thead><tr class="grp"><th></th><th colspan="${nd}">Geliştirme bölgeleri</th><th colspan="${nt}">Görülmemiş bölgeler (test)</th></tr>`;
  h += `<tr><th></th>${cols.map((c) => `<th${c.includes("+") ? ' class="joint"' : ""}>${name(c)}</th>`).join("")}</tr></thead><tbody>`;
  for (const [lab, f] of R) h += `<tr><td>${lab}</td>${cols.map((c) => `<td${c.includes("+") ? ' class="joint"' : ""}>${f(get(c))}</td>`).join("")}</tr>`;
  $("#acc-table").innerHTML = h + "</tbody>";
}

function wireUi() {
  $("#aoi").addEventListener("change", (e) => loadAoi(e.target.value));
  $("#y0").addEventListener("change", (e) => { state.y0 = +e.target.value; if (state.y1 < state.y0) { state.y1 = state.y0; $("#y1").value = state.y1; } rebuildPolys(); updateCompare(); });
  $("#y1").addEventListener("change", (e) => { state.y1 = +e.target.value; if (state.y0 > state.y1) { state.y0 = state.y1; $("#y0").value = state.y0; } rebuildPolys(); updateCompare(); });
  $("#compare").addEventListener("change", (e) => { state.compare = e.target.checked; updateCompare(); });
  $("#swipe-range").addEventListener("input", (e) => { state.swipe = +e.target.value; clipPanes(); });
  document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { $("#" + b.dataset.open).hidden = false; }));
  document.querySelectorAll(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m || e.target.hasAttribute("data-close")) m.hidden = true; }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".modal").forEach((m) => (m.hidden = true)); });
  $("#panel-open").addEventListener("click", () => $("#panel").classList.add("open"));
  $("#panel-close").addEventListener("click", () => $("#panel").classList.remove("open"));
  const repo = document.querySelector('meta[name="repo-url"]').content;
  if (repo) { $("#repo-link").href = repo; $("#repo-line").hidden = false; }
}

async function main() {
  initMap();
  wireUi();
  state.index = await getJSON("data/index.json");
  for (const t of state.index.turler) state.on[t] = state.index.varsayilan_acik.includes(t);
  const sel = $("#aoi");
  for (const a of state.index.aoiler) sel.add(new Option(a.ad + (a.test_aoi ? " · test" : ""), a.aoi));
  $("#generated").textContent = `Oluşturma: ${state.index.olusturma}.`;
  renderAccuracy();
  const want = location.hash.slice(1);
  const first = state.index.aoiler.some((a) => a.aoi === want) ? want : state.index.aoiler[0].aoi;
  sel.value = first;
  await loadAoi(first);
}

main().catch((e) => { console.error(e); document.body.insertAdjacentHTML("afterbegin", `<p style="padding:12px;background:#fdd">Veri yüklenemedi: ${e.message}</p>`); });
