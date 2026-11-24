# TR-ChangeWatch

Ankara'daki seçili bölgelerde Sentinel-2 L2A ile yapılaşma ve arazi örtüsü değişimini kanıtıyla ve güven düzeyiyle haritalayan değişim izleme sistemi. Kapsam ve mimari: [PROJECT_SPEC.md](PROJECT_SPEC.md).

> Geliştirme sürüyor (Faz 3 hazırlığı). Kırılma yöntemi ve yapılaşma/bitki kaybı kuralları v1 için donduruldu; su kuralı Gölbaşı'nda tasarlandı; doğrulama noktaları etiketlenmeyi bekliyor.

## Kurulum

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
changewatch --help
```

Ham veri önbelleği ve ara çıktılar `config/settings.yaml` içindeki `paths.cache_dir` klasörüne yazılır (harici disk). Repoya yalnızca kod, GeoJSON, JSON, CSV ve küçük PNG girer.

## Komutlar

```bash
changewatch check-aois                                  # AOI alan/sınır kontrolü
changewatch scenes      --aoi incek --years 2017-2026   # sahne/bulut/baseline özeti (indirme yok)
changewatch fetch       --aoi incek                     # AOI penceresini önbelleğe indir (20 m + 10 m B08)
changewatch composite   --aoi incek                     # harmonizasyon + SCL maskesi + medyan kompozit + sahne bazında doku
changewatch indices     --aoi incek --years 2017 2024   # NDVI, NDBI, MNDWI, BSI, doku (GeoTIFF + PNG)
changewatch detect      --aoi incek                     # kırılma noktası (varsayılan) → changes.geojson + izleme.geojson
changewatch detect      --aoi incek --method pairs      # ardışık yıl çiftleri (E1 karşılaştırması için)
changewatch water       --aoi golbasi                   # yıllık su maskesi, su alanı serisi ve grafiği
changewatch evaluate    --aoi incek --direct-years 2017 2024  # tür × yıl, yöntemler arası, tutarlılık
changewatch sample                                      # Faz 3: tabakalı örnekleme, labels.csv şablonu, çipler, QGIS yükleyici
changewatch label-prep                                  # kör etiketleme çipleri + Gölbaşı su doğrulama seti
changewatch label [--set su]                            # kör etiketleme arayüzü (talimat: validation/ETIKETLEME.md)
changewatch validate                                    # etiketlerden karışıklık matrisi, tür/yıl bazlı ve Olofsson alan ağırlıklı metrikler
changewatch experiments [--build]                       # E1, E3–E5 varyantları ve nokta tahminleri (E2 v2'de)
```

## Geliştirme ve test AOI'leri

Yöntem tasarımı ve eşik denemeleri yalnızca **geliştirme AOI'lerinde** yapılır: `incek` (yapılaşma, bitki kaybı) ve `golbasi` (su kuralı, Mogan Gölü). **Test AOI'leri** `baglica` ve `pursaklar`, yöntem dondurulana kadar hiç çalıştırılmaz (indirme dahil); dondurulduktan sonra hiçbir ayar değiştirilmeden çalıştırılır. Böylece test AOI'lerindeki sonuçlar, yöntemin o bölgelere göre ayarlanmamış olduğunu gösterir.

## Bulgu: İncek'te NDBI ve BSI ters çalışıyor

Literatürde yapılaşma için sık kullanılan "NDBI artışı" İncek'te geçerli değil. Bozkır ve sürülmüş tarla, NDBI ve BSI'de yerleşimden **daha yüksek** değer veriyor (yerleşimde bahçe, ağaç ve kiremit çatı var). Bu yüzden bozkırın konuta dönüşmesi NDBI ve BSI'yi **düşürüyor**.

| 2024 yaz kompoziti (medyan) | NDVI | NDBI | BSI |
|---|---|---|---|
| Yerleşim (doku > 0,05) | 0,160 | 0,014 | 0,078 |
| Bozkır/tarla (doku < 0,01) | 0,205 | 0,121 | 0,174 |

| 2017→2024 farkı (medyan) | dNDVI | dNDBI | dBSI | dMNDWI |
|---|---|---|---|---|
| Doku düşükten yükseğe çıkan pikseller (AOI'nin %5,4'ü) | −0,071 | −0,040 (%64'ü düşüş) | −0,038 (%69'u düşüş) | +0,111 |
| Dokusu iki yılda da düşük kalan pikseller | +0,013 | −0,005 | −0,002 | −0,005 |

Bu ölçüm keşif amaçlıdır; doğrulama noktası kullanılmadı ve eşik ayarlanmadı. Sonuç olarak yapılaşma kuralının birincil kanıtı **doku artışı + kalıcılık** oldu; NDVI, NDBI ve BSI farkları işaretli değerleriyle kanıt alanı olarak tutuluyor. İki kuralın doğrulama noktalarındaki karşılaştırması deney **E4**'te yapılacak.

## Yöntem geçişi: ardışık yıl çiftlerinden kırılma noktasına

İlk yöntem her ardışık yıl çiftinde (2017→2018 … 2025→2026) CVA büyüklüğü ve doku farkını Otsu ile eşikleyip bir sonraki yılda "geri dönmüyor mu" diye kalıcılık arıyordu. İncek'te iki yapısal sorun çıktı:

- **Otsu yıllık farklarda gürültüyü bölüyor.** Gerçek değişim alanın birkaç yüzdesiyken her yıl alanın %7–19'u aday oldu; 9 yılda AOI'nin %47'si en az bir kez "değişti".
- **Kalıcılık testi tarla rotasyonunu elemiyor.** Her yıl farklı ürün ekilen tarla "geri dönmediği" için kalıcı sayıldı.

Bu yüzden LandTrendr/BFAST'ın basitleştirilmiş bir hâline geçildi: her pikselin 2017–2026 serisinde (bantlar + doku, her biri kendi gürültüsüyle z-ölçekli) tek bir basamak aranır; kırılma yılı parça içi sapmayı en aza indiren yıldır, aday için basamak gürültünün k katını aşmalıdır. Yıl yıl değişen tarlanın parça içi yayılımı büyük olduğu için skoru düşük kalır; kalıcılık yöntemin içindedir.

| İncek, 2017–2026 | Ardışık çift | Kırılma noktası |
|---|---|---|
| Yapılaşma (ha) | 1 545 | 417 (+ 2026 izleme 117) |
| Tüm türler, ayak izi (ha) | 2 826 | 518 |
| Doğrudan 2017→2024 doku artışlı adayla örtüşme (yöntemin içeride kalan payı) | %36 | %59 |

Ardışık çift yöntemi silinmedi (`--method pairs`); doğrulama noktalarında E1'de karşılaştırılacak.

## Bulgu: Gölbaşı su alanındaki artışın çoğu çatı ve seralardan

İlk su kuralı "MNDWI > 0 olan her piksel su" diyordu. Gölbaşı'nda bu seri 2017→2025 arasında **+37,6 ha** artış gösteriyordu. Su yalnızca ≥ 5 ha bağlı su kütlelerine ait pikseller olarak tanımlanınca artış **+12,6 ha**'ya iniyor. Aradaki fark, MNDWI > 0 veren küçük parçalardan (çatı, sera, gölcük) geliyor ve bu parçalar yıllar içinde 8 ha'dan 33 ha'ya büyüyor; büyük olasılıkla Gölbaşı'ndaki yapılaşmayla birlikte.

| Yıl | Su (≥ 5 ha kütleler) | Eski seri (tüm MNDWI > 0) | Elenen küçük parçalar |
|---|---|---|---|
| 2017 | 521 | 529 | 8 |
| 2021 | 546 | 561 | 15 |
| 2024 | 528 | 559 | 31 |
| 2025 | 534 | 567 | 33 |

Grafik `changewatch water --aoi golbasi` ile üretilir (eski seri kesikli). 2021'deki sıçramanın bir kısmı göl suyunun renk değişiminden (alg/bulanıklık) gelebilir; göl içi renk değişimi su kazanımı sayılmaz (su kütlelerinin iç delikleri doldurulur, kazanım/kayıp yalnızca kıyı şeridinde aranır).

## Bilinen sınırlamalar

- **04.00 öncesi baseline'larda parlak yüzeyler bulut sayılabiliyor.** 2017–2021 sahneleri (processing baseline 02.12 ve 03.00) bulutsuz günlerde bile parlak yüzeyleri (şantiye, yol, parlak çatı) SCL 8/9 (orta/yüksek olasılıklı bulut) olarak sınıflandırabiliyor. İncek yaz kompozitlerinde 2017–2021 arasında AOI piksellerinin %0,05–0,35'inde 3'ten az geçerli gözlem kaldı (2022 ve sonrasında %0); bu pikseller kompozitte boş bırakılır. Maske değiştirilmedi; bunun yerine her değişim poligonunda `dusuk_gozlem` kanıt alanı (önceki yıl kompozitindeki ortalama geçerli gözlem sayısı ve <3 gözlemli piksel oranı) raporlanır.
- **Son yıl sıçramaları kalıcı katmana sızabilir.** Kalıcı katman en az 2 yıllık "sonrası" ister; yalnızca son yılda (ör. 2026) sıçrayan bir piksel b = 2025'te yarım basamak gösterir ve tek tük pikseller kalıcı katmanda 2025 kırılması olarak geçebilir (MMU tekilleri büyük ölçüde atar). 2026 kırılmaları ayrı `izleme.geojson` katmanındadır.
- **Doku zamanla yukarı kayıyor.** İncek'te AOI doku medyanı 2017→2026 0,021 → 0,030; skoru düşük (değişmeyen) piksellerde de ~%15 artış var. 2025–2026'da sahne sayısı (20–21) 14'e indirildiğinde medyan değişmiyor (0,0289 / 0,0301), yani kayma sahne sayısından kaynaklanmıyor. Nedeni açık (bitki/ağaç büyümesi, yaygın kentleşme veya algılayıcı farkı olabilir); etkisi deney E5'te ölçülecek.
- **Tek değişkenli su kırılması gürültüye duyarlı.** MNDWI serisinde kırılma adayı tek başına AOI'nin büyük bir kısmını işaretler (Gölbaşı'nda ~2 000 ha); su katmanında özgüllüğü su kütlesi durumu değişimi ve kıyı şeridi koşulları sağlar (→ ~5 ha).
- **Su değişimleri doğrulama örneklemesinde neredeyse yok.** Su türleri Gölbaşı'nda toplam ~5 ha; tabaka alt sınırı yalnızca ≥ 20 ha tabakalara uygulandığı için su tabakaları 0–1 nokta aldı. Su kuralının doğruluğu bu örneklemeyle ölçülemez.
- **Su kütlelerinin iç delikleri doldurulur.** Göl içinde MNDWI'yi düşüren renk/bulanıklık değişimi su kazanımı/kaybı üretmesin diye ≥ 5 ha su kütlelerinin içindeki boşluklar su sayılır. Yan etkisi: göl içindeki gerçek adalar da su olarak haritalanır (Mogan'da belirgin ada yok).
- Sahne düzeyindeki bulut oranı (`eo:cloud_cover`) 100×100 km MGRS karesine aittir, AOI'ye değil. Asıl temizlik piksel düzeyinde SCL maskesiyle yapılır.
