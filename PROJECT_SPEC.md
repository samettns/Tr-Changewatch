# TR-ChangeWatch — Proje Spesifikasyonu (v1: Ankara)

> Bu dosya projenin tek doğruluk kaynağıdır. Kapsam dışına çıkan her şey "v2" bölümüne yazılır, v1'de yapılmaz.

## 1. Tek cümlelik tanım

Ankara'daki seçili bölgeler için Sentinel-2 görüntülerini otomatik indiren, bulut ve mevsim kaynaklı sahte değişimleri azaltan, yapılaşma ve arazi örtüsü değişimini **kanıtıyla ve güven düzeyiyle** haritalayan, sonuçlarını kendi topladığımız doğrulama noktalarıyla ölçen ve aylık olarak kendini güncelleyen bir değişim izleme sistemi.

## 2. Ne iddia ediyoruz, ne iddia etmiyoruz

**İddia ediyoruz:**
- Seçili Ankara bölgelerinde yapılaşmış alanın ve arazi örtüsünün yıllar içindeki değişimini hektar cinsinden ölçmek.
- Mevsimsel kompozit + kalıcılık kuralının yanlış alarmı ne kadar azalttığını **ölçmek**.
- Her değişim poligonu için hangi kanıtlara dayandığını göstermek.

**İddia etmiyoruz:**
- Tek tek bina tespiti. Çalışma ızgarası 20 m; bir piksel 400 m².
- "Sentinel-2 ile değişim tespiti yapan ilk proje" olmak.
- Spektral indekslerin kesin sınıflandırma yaptığını. İndeksler kanıt sunar, kesin hüküm vermez.
- Güven puanının gerçek dünyadaki kesinlik olduğunu. Bu puan kural tabanlı bir tahmin güvenidir.

## 3. Kapsam (v1)

- **Bölge:** Yalnızca Ankara. 3–4 küçük ilgi alanı (AOI), her biri en fazla ~10×10 km.
  Aday bölgeler: İncek–Kızılcaşar, Gölbaşı (Mogan çevresi), Bağlıca–Etimesgut, Pursaklar.
  Sınırlar geojson.io'da çizilip `config/aois.geojson` dosyasına konur.
- **Veri:** Sentinel-2 L2A (Planetary Computer STAC). Derin öğrenme ve yüksek çözünürlüklü veri setleri (LEVIR-CD, WHU-CD) v1'de **yok**.
- **Yıllar:** 2019–2026 (8 yıllık kompozit, 7 yıl-yıl geçişi) + aylık izleme.
  - 2017–2018 eklenebilir: Faz 1'de bu yılların Ankara için yeterli bulutsuz gözlemi olup olmadığı kontrol edilir, yeterliyse aralık genişletilir.
  - Kalıcılık kuralı gereği son yılın (2026) değişimleri `durum: "izlemede"` olarak işaretlenir. 2027 kompoziti gelince doğrulanır.
  - Her yeni yılın yaz penceresi bitince (Eylül sonrası) o yıl otomatik olarak eklenir.
- **Çıktılar:** GeoJSON poligonlar, özet istatistik JSON'ları, küçük önizleme PNG'leri, statik web haritası.

## 4. Mimari / veri hattı

```
config/aois.geojson + settings.yaml
  → [1] STAC arama (Planetary Computer, sentinel-2-l2a, bulut filtresi)
  → [2] Pencereli okuma (odc-stac; yalnızca AOI kutusu, COG; tam sahne İNDİRİLMEZ)
  → [3] Radyometrik harmonizasyon (processing baseline ≥ 04.00 → offset düzeltmesi)
  → [4] SCL maskesi (bulut, gölge, sirrus, kar, no-data)
  → [5] Mevsimsel medyan kompozit (her yıl aynı tarih penceresi)
  → [6] İndeksler: NDVI, NDBI, MNDWI, BSI + 10 m bantlardan doku (yerel std)
  → [7] Değişim adayları: CVA büyüklüğü + Otsu eşiği
  → [8] Morfoloji: açma/kapama, minimum haritalama birimi (MMU)
  → [9] Kalıcılık kuralı (değişim sonraki yıl(lar)da da sürüyor mu?)
  → [10] Tür + güven: yapılaşma (olası) / bitki örtüsü kaybı / su değişimi / belirsiz
  → [11] Vektörleştirme → GeoJSON (alan_ha, tür, güven, kanıt alanları)
  → [12] Önizleme PNG + stats.json → docs/ (GitHub Pages)
```

### Teknik kararlar (değiştirmeden önce bu dosyayı güncelle)

| Konu | Karar | Neden |
|---|---|---|
| Koordinat sistemi | EPSG:32636 (UTM 36N) | Ankara bu dilimde; alan hesabı metre cinsinden doğru olur |
| Çalışma ızgarası | 20 m | B11/B12 (SWIR) 20 m; 10 m'ye örneklemek gerçek çözünürlük kazandırmaz |
| Doku | B08 (10 m) üzerinde yerel std → 20 m'ye ortalama | Yapılaşma dokusu, sürülmüş tarlaya göre daha heterojendir |
| Bantlar | B02, B03, B04, B08, B11, B12, SCL | İndeksler + CVA için yeterli |
| Harmonizasyon | Processing baseline ≥ 04.00 sahnelerde −1000 DN offset düzeltmesi. Karar sahnenin `s2:processing_baseline` alanına göre verilir (ESA'nın yeniden işlediği eski sahneler de PB ≥ 04.00 olabilir). Alan yoksa tarihe göre karar verilir (25.01.2022 ve sonrası → düzelt) ve log'a uyarı yazılır. İki durumun da unit testi olur (Faz 1). | Yapılmazsa 2021→2022 arası her yerde sahte değişim çıkar |
| Veri önbelleği | Ham veri ve ara çıktılar `settings.yaml` içindeki `cache_dir`'de (harici SSD: `D:\tr-changewatch-data`). Klasör yoksa program anlaşılır bir hata verir. Sanal ortam (`.venv`) proje klasöründe, yerel diskte kalır. | Büyük veriler sistem diskini doldurmaz |
| Maskelenen SCL sınıfları | 0, 1, 3, 8, 9, 10, 11 | No-data, doymuş, gölge, bulut (orta/yüksek), sirrus, kar |
| Kompozit | Piksel bazlı medyan, en az N geçerli gözlem (varsayılan 3) | Tek sahne gürültüsünü ve kalan bulutları bastırır |
| Mevsim penceresi | Varsayılan 1 Temmuz–15 Eylül; alternatif 1 Mayıs–30 Haziran | Deney E2 ile karar verilecek |
| MMU | 0,5 ha (~13 piksel) | Tekil piksel gürültüsünü atar |
| Alan | piksel sayısı × 400 m² / 10 000 = ha | |

### Ankara'ya özgü tuzaklar (kural motoru bunlara göre tasarlanır)

1. **Çıplak toprak ≈ beton:** Bozkırda sürülmüş tarla ile yeni yapılaşma spektral olarak benzer görünür. Tek başına NDBI artışı yapılaşma sayılmaz.
2. **Nadas münavebesi:** İç Anadolu'da tarlalar bir yıl ekilip bir yıl boş bırakılabilir. Bu durum yıllar arasında "değişim, geri dönüş, değişim" deseni üretir.
3. **Çözüm:** "Olası yapılaşma" için birlikte sağlanması gerekenler:
   - NDBI ve BSI artışı
   - NDVI düşüşü
   - doku artışı
   - MNDWI'ye göre su olmaması
   - **kalıcılık:** değişim sonraki yıl(lar)da geri dönmüyor

   Son yılın değişimleri doğrulanamaz; `durum: "izlemede"` olarak işaretlenir.

### Tür ve güven kuralları (ilk sürüm, eşikler `settings.yaml` içinde)

- `yapilasma_olasi`: yukarıdaki koşulların tamamı + kalıcılık → güven: yüksek. Koşulların bir kısmı sağlanıyorsa → orta.
- `bitki_kaybi`: kalıcı NDVI düşüşü, NDBI ve doku artışı yok.
- `su_degisimi`: MNDWI işareti değişmiş.
- `belirsiz`: aday ama yukarıdakilerin hiçbirine yeterince uymuyor. Gizlenmez, haritada ayrı renkte gösterilir.
- Her poligonda kanıt alanları tutulur: `dNDVI`, `dNDBI`, `dBSI`, `dMNDWI`, `doku_artisi`, `kalici_mi`, `gecerli_gozlem_sayisi`.

## 5. Doğrulama (projenin asıl farkı)

- **Yöntem:** Tabakalı rastgele nokta örneklemesi. Poligon çizilmez; nokta etiketlemek çok daha hızlıdır.
  - Tabakalar: her değişim türü + "değişim yok". Toplam ~250–300 nokta.
  - Etiketleme: QGIS'te, Sentinel-2 kompozitleri ve Google Earth Pro geçmiş görüntülerine bakarak. Google Earth görüntüleri repoya **konmaz**; yalnızca etiketler (`validation/labels.csv`) paylaşılır.
- **Kalibrasyon ve test ayrımı:** Eşikler yalnızca kalibrasyon noktalarıyla ayarlanır (~%30). Test noktalarına eşik ayarlarken dokunulmaz.
- **Metrikler:** Karışıklık matrisi, kullanıcı ve üretici doğruluğu, yanlış alarm oranı, sınıf başına F1.

### Deneyler (README'de tablo + görsel olarak)

| Kod | Deney | Soru |
|---|---|---|
| E1 | Tek sahne ↔ medyan kompozit ↔ kompozit + kalıcılık | Yanlış alarm ne kadar azalıyor? **(ana sonuç)** |
| E2 | Mevsim penceresi: Mayıs–Haziran ↔ Temmuz–Eylül | Ankara'da hangi pencere daha az yanlış alarm veriyor? |
| E3 | Harmonizasyon açık ↔ kapalı (2021→2023) | Offset düzeltmesi yapılmazsa ne kadar sahte değişim çıkıyor? |

## 6. Web arayüzü

- `docs/` altında statik Leaflet sayfası, GitHub Pages üzerinden yayınlanır. Streamlit **yok**; Pages sunucu çalıştırmaz.
- Özellikler:
  - AOI seçici.
  - **Yıl aralığı seçici:** başlangıç ve bitiş yılı (ör. 2019 → 2026). Her AOI için tek bir `changes.geojson` tutulur; her poligonda `degisim_yili` alanı bulunur. Seçilen aralıktaki poligonlar tarayıcıda filtrelenir, her yıl çifti için ayrı dosya üretilmez.
  - Önce/sonra kaydırıcı: seçilen iki yılın kompozit önizleme PNG'leri (AOI başına yıl başına bir PNG).
  - Türe göre renkli poligonlar. `izlemede` ve `on_uyari` durumundakiler kesikli çizgiyle gösterilir.
  - Poligona tıklayınca alan, tür, değişim yılı, güven ve kanıt bilgisi.
  - AOI başına özet grafik: yıllara göre yapılaşan hektar.
  - Ayrı "son durum" katmanı: aylık izlemenin ön uyarıları.
- Boyut bütçesi: `docs/data` toplamı < 50 MB. PNG başına ≤ 500 KB.

## 7. Otomasyon (GitHub Actions)

- `tests.yml`: her push'ta `pytest`. Testler ağa çıkmaz; küçük sentetik diziler ve `tests/fixtures/` kullanılır.
- `monthly.yml`: ayda bir (cron) + elle tetikleme (`workflow_dispatch`).
  - **Aylık izleme tanımı:** Son 3 ay ile önceki yılın aynı 3 ayı karşılaştırılır (mevsimsel hizalı). Sonuçlar `durum: "on_uyari"` olarak işaretlenir ve doğrulanmış yıllık analizden ayrı katmanda gösterilir.
  - Kış aylarında bulut ve kar nedeniyle veri kapsaması düşük olabilir. Kapsama yüzdesi `stats.json` içine yazılır ve eşik altındaysa analiz atlanır.
  - Yalnızca GeoJSON, JSON ve küçük PNG commit'lenir. **GeoTIFF asla commit'lenmez.**
  - Public repoda standart runner (4 CPU, 16 GB RAM, GPU yok). Pencereli okuma ile küçük AOI'ler rahatça sığar.
  - Not: Public repolarda 60 gün aktivite olmazsa zamanlanmış iş devre dışı kalır. README'de belirtilir; uyarı e-postası gelince Actions sekmesinden yeniden etkinleştirilir.

## 8. Repo yapısı

```
tr-changewatch/
├── README.md
├── PROJECT_SPEC.md
├── CLAUDE.md
├── pyproject.toml
├── config/
│   ├── aois.geojson
│   └── settings.yaml          # pencereler, eşikler, MMU, SCL sınıfları
├── src/changewatch/
│   ├── stac.py                # arama + pencereli yükleme
│   ├── harmonize.py           # baseline offset düzeltmesi
│   ├── mask.py                # SCL maskesi
│   ├── composite.py           # mevsimsel medyan
│   ├── indices.py             # NDVI, NDBI, MNDWI, BSI, doku
│   ├── change.py              # CVA + Otsu
│   ├── morphology.py          # açma/kapama, MMU
│   ├── classify.py            # tür + güven + kalıcılık
│   ├── vectorize.py           # raster → GeoJSON
│   ├── quicklook.py           # önizleme PNG
│   ├── validate.py            # örnekleme + metrikler
│   ├── monitor.py             # aylık izleme
│   ├── aoi.py                 # AOI okuma + check-aois kontrolleri
│   ├── config.py              # settings.yaml yükleme, cache_dir kontrolü
│   └── cli.py                 # changewatch check-aois | fetch | composite | detect | validate | publish | monitor
├── tests/
│   └── fixtures/
├── validation/
│   ├── points.geojson
│   └── labels.csv
├── docs/                      # GitHub Pages
│   ├── index.html
│   ├── app.js
│   └── data/<aoi>/{changes.geojson, stats.json, monitor.geojson, quicklooks/<yil>.png}
├── data/                      # yerel/geçici dosyalar, .gitignore'da (asıl önbellek cache_dir'de)
└── .github/workflows/{tests.yml, monthly.yml}
```

**CLI — `changewatch check-aois`:** `config/aois.geojson` içindeki her AOI için adını, km² cinsinden alanını (EPSG:32636'da) ve sınırlarını yazdırır. Alan `max_aoi_km2`'den (100 km²) büyükse veya AOI `settings.yaml`'daki kaba Ankara sınır kutusunun dışına taşıyorsa uyarı verir. Uyarılar AOI'yi engellemez.

**Teknolojiler:** Python 3.12 (≥ 3.11), pyyaml, pystac-client, planetary-computer, odc-stac, xarray, rasterio, numpy, scipy, scikit-image (Otsu, morfoloji), geopandas, shapely, matplotlib, pytest. Web tarafında Leaflet + leaflet-side-by-side.

## 9. Fazlar ve "bitti" ölçütleri

Varsayım: günde 3–4 saat. MVP için 3–4 hafta.

| Faz | Süre | İş | Bitti sayılması için |
|---|---|---|---|
| 0 | 1 gün | Repo, ortam, AOI'leri çiz | `changewatch --help` çalışıyor, AOI'ler QGIS'te doğru yerde |
| 1 | 3–4 gün | Adım 1–5: STAC, pencereli okuma, harmonizasyon, maske, kompozit | İncek 2019 ve 2024 kompozit PNG'leri bulutsuz ve renkleri doğal; harmonizasyon testi geçiyor |
| 2 | 4–5 gün | Adım 6–11: indeksler, CVA, morfoloji, kurallar, GeoJSON | GeoJSON QGIS'te açılıyor; İncek'teki bilinen yeni yapılaşma alanları yakalanmış |
| 3 | 3–4 gün | Doğrulama noktaları, etiketleme, E1–E3 | Metrik tabloları ve 3 deney görseli hazır |
| 4 | 3 gün | Leaflet haritası, GitHub Pages | Canlı linkte AOI ve yıl seçilebiliyor, popup'lar çalışıyor |
| 5 | 2 gün | Actions (tests + monthly), README, demo GIF | Elle tetiklenen monthly işi başarılı commit atıyor |

**Kural:** Bir fazın "bitti" ölçütü sağlanmadan sonraki faza geçilmez.

## 10. v2 (v1 bitmeden başlanmaz)

- Derin öğrenme: TorchGeo ile SSL4EO-S12 ön-eğitimli Sentinel-2 enkoderi + Siamese başlık, OSCD üzerinde fine-tuning (eğitim yerel RTX 4080'de). Aynı Ankara test noktalarında klasik hatla karşılaştırma.
- Yeni vakalar: Manavgat yangını (dNBR), Mogan ve Tuz Gölü su alanı.
- Ankara dışındaki şehirler.
- Hazır arazi örtüsü ürünleriyle (ESA WorldCover vb.) çapraz kontrol.
