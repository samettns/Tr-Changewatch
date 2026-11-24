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
- **Yıllar:** 2017–2026 (10 yıllık kompozit, 9 yıl-yıl geçişi) + aylık izleme.
  - 2017–2018 Faz 1'de kontrol edildi: İncek yaz penceresinde yılda 13–16 bulutsuz tarih var, aralık 2017'ye genişletildi.
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
  → [6] İndeksler: NDVI, NDBI, MNDWI, BSI + 10 m B08'den doku (sahne bazında yerel std → medyan)
  → [7] Değişim adayları — iki yöntem (E1'de karşılaştırılır):
        (a) ardışık yıl çiftleri: CVA büyüklüğü + doku farkı, her biri için Otsu eşiği
        (b) kırılma noktası (varsayılan): piksel bazında 2017–2026 serisinde tek basamak (bkz. §4 "Kırılma noktası yöntemi")
  → [8] Morfoloji: açma/kapama, minimum haritalama birimi (MMU)
  → [9] Kalıcılık kuralı (a: değişim sonraki yılda sürüyor mu? b: kırılma sonrası parça ≥ 2 yıl ve kendi içinde tutarlı)
  → [10] Tür + güven: yapılaşma (olası) / bitki örtüsü kaybı / su değişimi / belirsiz
  → [11] Vektörleştirme → GeoJSON (alan_ha, tür, güven, kanıt alanları)
  → [12] Önizleme PNG + stats.json → docs/ (GitHub Pages)
```

### Teknik kararlar (değiştirmeden önce bu dosyayı güncelle)

| Konu | Karar | Neden |
|---|---|---|
| Koordinat sistemi | EPSG:32636 (UTM 36N) | Ankara bu dilimde; alan hesabı metre cinsinden doğru olur |
| Çalışma ızgarası | 20 m | B11/B12 (SWIR) 20 m; 10 m'ye örneklemek gerçek çözünürlük kazandırmaz |
| Doku | Her sahnede ayrı: maskeli B08 (10 m) üzerinde yerel std (maskeli piksel içeren pencereler dışlanır) → 20 m'ye blok ortalaması; sonra sahnelerin piksel bazında medyanı | Yapılaşma dokusu, sürülmüş tarlaya göre daha heterojendir. Std'yi kompozit üzerinde almak, komşu piksellerin farklı sahne kümelerinden medyanlanmasıyla (özellikle 04.00 öncesi SCL sorunu olan yıllarda) yapay kenar/kare desen üretiyordu |
| Bantlar | B02, B03, B04, B08, B11, B12, SCL | İndeksler + CVA için yeterli |
| Harmonizasyon | Processing baseline ≥ 04.00 sahnelerde −1000 DN offset düzeltmesi. Karar sahnenin `s2:processing_baseline` alanına göre verilir (ESA'nın yeniden işlediği eski sahneler de PB ≥ 04.00 olabilir). Alan yoksa tarihe göre karar verilir (25.01.2022 ve sonrası → düzelt) ve log'a uyarı yazılır. İki durumun da unit testi olur (Faz 1). | Yapılmazsa 2021→2022 arası her yerde sahte değişim çıkar |
| Veri önbelleği | Ham veri ve ara çıktılar `settings.yaml` içindeki `cache_dir`'de (harici SSD: `D:\tr-changewatch-data`). Klasör yoksa program anlaşılır bir hata verir. Sanal ortam (`.venv`) proje klasöründe, yerel diskte kalır. | Büyük veriler sistem diskini doldurmaz |
| Maskelenen SCL sınıfları | 0, 1, 3, 8, 9, 10, 11 | No-data, doymuş, gölge, bulut (orta/yüksek), sirrus, kar |
| Sahne seçimi | Sahne düzeyinde `eo:cloud_cover` < %60 (gevşek ön filtre). Aynı çekim + MGRS karesinin birden fazla işlenmiş sürümü varsa (ör. 2022–2023'te 04.00/05.09 ve 2024 yeniden işlemesi 05.10) en yüksek baseline'lı öğe tutulur. SCL maskesinden sonra AOI içindeki geçerli piksel oranı `min_valid_fraction` (%20) altındaki sahne kompozite alınmaz ve log'a yazılır. | Kopyalar medyanda iki kez sayılmasın; asıl bulut temizliği piksel düzeyinde SCL ile yapılır |
| Kompozit | Piksel bazlı medyan, en az N geçerli gözlem (varsayılan 3) | Tek sahne gürültüsünü ve kalan bulutları bastırır |
| Mevsim penceresi | Varsayılan 1 Temmuz–15 Eylül; alternatif 1 Mayıs–30 Haziran | Deney E2 ile karar verilecek |
| MMU | 0,5 ha (~13 piksel) | Tekil piksel gürültüsünü atar |
| Alan | piksel sayısı × 400 m² / 10 000 = ha | |

### Ankara'ya özgü tuzaklar (kural motoru bunlara göre tasarlanır)

1. **Çıplak toprak ≈ beton ve NDBI'nin ters çalışması:** Bozkırda sürülmüş tarla ile yeni yapılaşma spektral olarak benzer görünür. Dahası İncek'te bozkır/tarla NDBI ve BSI'de yerleşimden **daha yüksek** çıkıyor (bahçe, ağaç, kiremit çatı); bozkırdan konuta dönüşüm NDBI ve BSI'yi **düşürüyor**. Faz 2 keşif ölçümü (İncek, 2017→2024 yaz kompozitleri; doğrulama noktası kullanılmadı, eşik ayarlanmadı):

   | 2024 mutlak değerler (medyan) | NDVI | NDBI | BSI |
   |---|---|---|---|
   | Yerleşim (doku > 0,05) | 0,160 | 0,014 | 0,078 |
   | Bozkır/tarla (doku < 0,01) | 0,205 | 0,121 | 0,174 |

   | 2017→2024 farkları (medyan) | dNDVI | dNDBI | dBSI | dMNDWI |
   |---|---|---|---|---|
   | Doku düşük → yüksek (2017 < 0,02, Δ > +0,03; AOI'nin %5,4'ü) | −0,071 | −0,040 (%64'ü düşüş) | −0,038 (%69'u düşüş) | +0,111 |
   | Doku hep düşük (iki yılda da < 0,015) | +0,013 | −0,005 | −0,002 | −0,005 |

   Bu yüzden NDBI/BSI yön koşulu olarak kullanılmaz; yalnızca kanıt alanı olarak tutulur (E4 ile ölçülür).
2. **Nadas münavebesi:** İç Anadolu'da tarlalar bir yıl ekilip bir yıl boş bırakılabilir. Bu durum yıllar arasında "değişim, geri dönüş, değişim" deseni üretir.
3. **Çözüm:** "Olası yapılaşma" için birincil kanıt:
   - **doku artışı**
   - **kalıcılık:** değişim sonraki yıl(lar)da geri dönmüyor
   - su olmaması (sonraki yılda MNDWI ≤ su eşiği)

   NDVI, NDBI ve BSI farkları yön koşulu değildir; işaretli değerleriyle kanıt alanı olarak tutulur.

   Son yılın değişimleri doğrulanamaz; `durum: "izlemede"` olarak işaretlenir.

### Kırılma noktası yöntemi (LandTrendr/BFAST'ın basitleştirilmiş hâli)

Ardışık çift yönteminde iki yapısal sorun görüldü (İncek, 2017–2026): yıllık farklarda Otsu, gerçek değişim azınlıkta olduğu için gürültüyü bölüyor (her yıl alanın %7–19'u aday); "geri dönmüyor" kalıcılık testi her yıl farklı ürün ekilen tarlaları elemiyor. Kırılma yöntemi tüm seriyi birlikte kullanır:

- Piksel serisi: 2017–2026 yaz kompozitleri; değişkenler: bantlar (B02, B03, B04, B08, B11, B12; yansıtım) + doku. NDVI, NDBI, BSI, MNDWI yalnızca tür ve kanıt için.
- **z-ölçekleme:** her değişken kendi gürültü düzeyine (σ) bölünür; basamak ve yayılım bu ortak uzayda Öklid uzaklığıdır. Doku eklenmeden önce (yalnızca bantlar) yöntem İncek'te 2017→2024 doku artışlı adayın yalnızca %5'ini yakalıyordu: bozkır → konut dönüşümü spektrumdan çok dokuyu değiştiriyor.
- **Gürültü düzeyi σ:** referans piksel seçilmeden, tüm (AOI) piksellerin seçilen kırılmaya göre parça içi mutlak sapmalarının medyanı. İki sabit geçiş: (1) kırılmasız σ ile b seçilir, (2) bu b'ye göre σ yeniden hesaplanır ve b yeniden seçilir. (İlk denemede eşik AOI'nin basamak dağılımından medyan + k·MAD idi; rotasyon tarlaları dağılımı şişirip eşiği 0,249'a çıkardı ve yapılaşma basamaklarının %79'u eşiğin altında kaldı.)
- Her aday kırılma yılı b için (öncesi ≥ 1, sonrası ≥ 1 yıl): öncesi = y < b, sonrası = y ≥ b.
  - Basamak_z = |medyan(sonrası) − medyan(öncesi)|.
  - Yayılım_z = yılların kendi parça medyanına uzaklıklarının ortalaması (medyan yayılım, yarı yarıya salınan rotasyon serilerinde ≈ 0 çıkıp skoru patlatıyordu).
  - Gürültü_z = piksellerin yayılım_z medyanı (çok sabit pikseller skoru patlatmasın diye taban).
  - Skor = basamak_z / max(yayılım_z, gürültü_z).
- Kırılma yılı: yayılımı (toplam sapmayı) en aza indiren b (LandTrendr'daki segment uydurma gibi). İlk tasarımdaki "skoru en yüksek b" kuralı, medyan basamak gerçek yılın çevresinde düz kaldığı için yılı gürültüyle seçiyordu. Tam eşitlikte (eksik yıl) geç b: yeni durumun ilk gözlendiği yıl.
- Aday: skor > `score_k` (başlangıç 3) **ve** basamak_z > `step_k` × gürültü_z. (Not: `step_k` ≤ `score_k` iken ikinci koşul birinciden çıkar; ayrı tutulur ki ayrı kalibre edilebilsin.)
- Kırılma yılı = `degisim_yili`; 3×3 mod filtresiyle yumuşatılır. Morfoloji tüm aday maskesine, MMU her kırılma yılına ayrı uygulanır.
- Her yıl farklı ürün ekilen tarla: parça içi yayılım büyük → skor düşük → aday olmaz. Bu, kalıcılık kuralının yapısal karşılığıdır.
- Tür (parça medyanlarıyla; "anlamlı" = k × o değişkenin σ'sı, σ aynı yöntemle):
  - `su_degisimi`: sonrası medyan MNDWI > su eşiği ve öncesi ≤ su eşiği.
  - `yapilasma_olasi`: doku basamağı anlamlı pozitif (ve su değil).
  - `bitki_kaybi`: NDVI basamağı anlamlı negatif ve doku artışı yok.
  - `belirsiz`: diğerleri.
- Güven / durum: kırılma sonrası ≥ 3 yıl → yüksek, `kalici`; 2 yıl → orta, `kalici`. `belirsiz` her zaman düşük.
- **Kalıcı katman** `min_after = 2`: en geç kırılma yılı son yıldan bir önceki (2017–2026 için 2025). Uç yıl yanlılığı (1 yıllık parçanın sapması tanım gereği 0) nedeniyle son yıl kırılmaları kalıcı katmana alınmaz: İncek'te ham adayların %23'ü 2026'da kırılıyordu (eşit dağılımda %11).
- **İzleme katmanı** (`izleme.geojson`): `min_after = 1` ile ayrı geçiş; son yılda kırılan ve kalıcı katmanda olmayan parçalar. `durum: "izlemede"`, güven düşük. Ertesi yılın kompoziti gelince kalıcı katmanda yeniden değerlendirilir.
- `sinyal`: basamağın spektral (bantlar) ve doku bileşenleri kendi gürültüleriyle ayrı test edilir (bileşen_z > `step_k` × bileşen gürültüsü). İkisi de anlamlı → `ikisi`; biri → `spektral` / `doku`; hiçbiri tek başına anlamlı değilse gürültüye göre baskın olan. Parça değeri piksel çoğunluğudur; `spektral_payi`, `doku_payi` de tutulur.
- Ek kanıt alanları: `skor`, `basamak`, `sonrasi_yil_sayisi`, `yil_payi` (parçada kırılma yılı parçanın yılına eşit olan piksel payı).

### Tür ve güven kuralları — ardışık çift yöntemi (ilk sürüm, eşikler `settings.yaml` içinde)

- `yapilasma_olasi`: doku artışı + kalıcılık + su değil → güven: yüksek. Doku artışı + su değil ama kalıcılık doğrulanamıyor (son yıl) → güven: orta, `durum: "izlemede"`.
- `bitki_kaybi`: kalıcı NDVI düşüşü, doku artışı yok.
- `su_degisimi`: sonraki yılda MNDWI > su eşiği (`settings.yaml`, varsayılan 0) ve bu durum kalıcı.
- `belirsiz`: aday ama yukarıdakilerin hiçbirine yeterince uymuyor. Gizlenmez, haritada ayrı renkte gösterilir.
- Her poligonda kanıt alanları tutulur: `dNDVI`, `dNDBI`, `dBSI`, `dMNDWI`, `doku_artisi`, `kalici_mi`, `gecerli_gozlem_sayisi`, `dusuk_gozlem`.
- `dusuk_gozlem`: poligonun önceki yıl kompozitindeki ortalama geçerli gözlem sayısı ve geçerli gözlemi < `min_valid_obs` (3) olan piksel oranı. Neden: 04.00 öncesi baseline'larda (02.12 ve 03.00; 2017–2021) parlak yüzeyler (şantiye, yol, parlak çatı) bulutsuz sahnelerde de SCL 8/9 (bulut) sınıflandırılabiliyor; bu pikseller önceki yılda seyrek gözlemlenir. Maske değiştirilmez, durum kanıt olarak raporlanır.

## 5. Doğrulama (projenin asıl farkı)

- **Yöntem:** Tabakalı rastgele nokta örneklemesi. Poligon çizilmez; nokta etiketlemek çok daha hızlıdır.
  - Tabakalar: her değişim türü + "değişim yok". Toplam ~250–300 nokta.
  - Etiketleme: QGIS'te, Sentinel-2 kompozitleri ve Google Earth Pro geçmiş görüntülerine bakarak. Google Earth görüntüleri repoya **konmaz**; yalnızca etiketler (`validation/labels.csv`) paylaşılır.
- **Kalibrasyon ve test ayrımı:** Eşikler yalnızca kalibrasyon noktalarıyla ayarlanır (~%30). Test noktalarına eşik ayarlarken dokunulmaz.
- **Metrikler:** Karışıklık matrisi, kullanıcı ve üretici doğruluğu, yanlış alarm oranı, sınıf başına F1.

- **Geliştirme/test AOI ayrımı:**
  - Geliştirme AOI'leri: `incek` (yapılaşma ve bitki kaybı kuralları), `golbasi` (su kuralı; Mogan Gölü). Yöntem tasarımı ve eşik denemeleri yalnızca bunlarda yapılır.
  - Test AOI'leri: `baglica` ve `pursaklar`. Yöntem dondurulana kadar çalıştırılmaz (fetch dahil); dondurulduktan sonra hiçbir ayar değiştirilmeden test edilir.
  - **Dondurma kaydı:** kırılma yöntemi + yapılaşma ve bitki kaybı kuralları v1 için donduruldu (incek'te eşik denemesi yapılmaz; değişiklik ancak Faz 3 kalibrasyon noktalarıyla). Su kuralı Gölbaşı'nda tasarlanacak.

### Deneyler (README'de tablo + görsel olarak)

| Kod | Deney | Soru |
|---|---|---|
| E1 | Tek sahne ↔ medyan kompozit ↔ kompozit + kalıcılık (ardışık çift) ↔ kırılma noktası | Yanlış alarm ne kadar azalıyor? **(ana sonuç)** |
| E2 | Mevsim penceresi: Mayıs–Haziran ↔ Temmuz–Eylül | Ankara'da hangi pencere daha az yanlış alarm veriyor? |
| E3 | Harmonizasyon açık ↔ kapalı (2021→2023) | Offset düzeltmesi yapılmazsa ne kadar sahte değişim çıkıyor? |
| E4 | Eski NDBI/BSI artışı tabanlı yapılaşma kuralı ↔ doku + kalıcılık tabanlı kural | Doğrulama noktalarında hangisi yapılaşmayı daha iyi yakalıyor, yanlış alarm ne kadar? |

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
│   ├── change.py              # CVA + Otsu (ardışık çift yöntemi)
│   ├── breakpoint.py          # piksel bazında zaman serisi kırılma noktası
│   ├── evaluate.py            # yöntem karşılaştırması: tür × yıl, yöntemler arası, doğrudan karşılaştırmayla tutarlılık
│   ├── morphology.py          # açma/kapama, MMU
│   ├── classify.py            # tür + güven + kalıcılık
│   ├── vectorize.py           # raster → GeoJSON
│   ├── quicklook.py           # önizleme PNG
│   ├── validate.py            # örnekleme + metrikler
│   ├── monitor.py             # aylık izleme
│   ├── aoi.py                 # AOI okuma + check-aois kontrolleri
│   ├── config.py              # settings.yaml yükleme, cache_dir kontrolü
│   ├── cache.py               # cache_dir'deki ham sahne GeoTIFF'lerini okuma/yazma
│   └── cli.py                 # changewatch check-aois | scenes | fetch | composite | indices | detect [--method breakpoint|pairs] | evaluate | validate | publish | monitor
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

**CLI — `changewatch scenes --aoi <ad> [--years ...]`:** Yalnızca STAC meta verisini sorgular (indirme yok). Her yıl için yaz penceresindeki sahne sayısını, farklı tarih sayısını, bulut < `report_cloud_threshold` olanları ve processing baseline dağılımını tablo olarak yazdırır.

**Teknolojiler:** Python 3.12 (≥ 3.11), pyyaml, pystac-client, planetary-computer, odc-stac, xarray, rasterio, numpy, scipy, scikit-image (Otsu, morfoloji), geopandas, shapely, matplotlib, pytest. Web tarafında Leaflet + leaflet-side-by-side.

## 9. Fazlar ve "bitti" ölçütleri

Varsayım: günde 3–4 saat. MVP için 3–4 hafta.

| Faz | Süre | İş | Bitti sayılması için |
|---|---|---|---|
| 0 | 1 gün | Repo, ortam, AOI'leri çiz | `changewatch --help` çalışıyor, AOI'ler QGIS'te doğru yerde |
| 1 | 3–4 gün | Adım 1–5: STAC, pencereli okuma, harmonizasyon, maske, kompozit | İncek 2017 ve 2024 kompozit PNG'leri bulutsuz ve renkleri doğal; harmonizasyon testi geçiyor |
| 2 | 4–5 gün | Adım 6–11: indeksler, CVA, morfoloji, kurallar, GeoJSON | GeoJSON QGIS'te açılıyor; İncek'teki bilinen yeni yapılaşma alanları yakalanmış |
| 3 | 3–4 gün | Doğrulama noktaları, etiketleme, E1–E4 | Metrik tabloları ve 4 deney görseli hazır |
| 4 | 3 gün | Leaflet haritası, GitHub Pages | Canlı linkte AOI ve yıl seçilebiliyor, popup'lar çalışıyor |
| 5 | 2 gün | Actions (tests + monthly), README, demo GIF | Elle tetiklenen monthly işi başarılı commit atıyor |

**Kural:** Bir fazın "bitti" ölçütü sağlanmadan sonraki faza geçilmez.

## 10. v2 (v1 bitmeden başlanmaz)

- Derin öğrenme: TorchGeo ile SSL4EO-S12 ön-eğitimli Sentinel-2 enkoderi + Siamese başlık, OSCD üzerinde fine-tuning (eğitim yerel RTX 4080'de). Aynı Ankara test noktalarında klasik hatla karşılaştırma.
- Yeni vakalar: Manavgat yangını (dNBR), Mogan ve Tuz Gölü su alanı.
- Ankara dışındaki şehirler.
- Hazır arazi örtüsü ürünleriyle (ESA WorldCover vb.) çapraz kontrol.
