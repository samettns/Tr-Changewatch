# TR-ChangeWatch

Ankara'daki seçili bölgelerde Sentinel-2 L2A ile yapılaşma ve arazi örtüsü değişimini kanıtıyla ve güven düzeyiyle haritalayan değişim izleme sistemi. Kapsam ve mimari: [PROJECT_SPEC.md](PROJECT_SPEC.md).

> Geliştirme sürüyor (Faz 2). Kırılma yöntemi ve yapılaşma/bitki kaybı kuralları v1 için donduruldu; su kuralı Gölbaşı'nda tasarlanıyor.

## Kurulum

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
changewatch --help
```

Ham veri önbelleği `config/settings.yaml` içindeki `paths.cache_dir` klasörüne yazılır.

## Komutlar

```bash
changewatch check-aois                                  # AOI alan/sınır kontrolü
changewatch scenes    --aoi incek --years 2017-2026     # sahne/bulut/baseline özeti (indirme yok)
changewatch fetch     --aoi incek --years 2017 2024     # AOI penceresini önbelleğe indir
changewatch composite --aoi incek --years 2017 2024     # harmonizasyon + SCL maskesi + medyan kompozit (20 m + 10 m B08)
changewatch indices   --aoi incek --years 2017 2024     # NDVI, NDBI, MNDWI, BSI, doku (GeoTIFF + PNG)
changewatch detect    --aoi incek                       # kırılma noktası (varsayılan) → changes.geojson + izleme.geojson
changewatch detect    --aoi incek --method pairs        # ardışık yıl çiftleri (E1 karşılaştırması)
changewatch evaluate  --aoi incek --direct-years 2017 2024  # tür × yıl, yöntemler arası, tutarlılık
```

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

## Bilinen sınırlamalar

- **04.00 öncesi baseline'larda parlak yüzeyler bulut sayılabiliyor.** 2017–2021 sahneleri (processing baseline 02.12 ve 03.00) bulutsuz günlerde bile parlak yüzeyleri (şantiye, yol, parlak çatı) SCL 8/9 (orta/yüksek olasılıklı bulut) olarak sınıflandırabiliyor. İncek yaz kompozitlerinde 2017–2021 arasında AOI piksellerinin %0,05–0,35'inde 3'ten az geçerli gözlem kaldı (2022 ve sonrasında %0); bu pikseller kompozitte boş bırakılır. Maske değiştirilmedi; bunun yerine her değişim poligonunda `dusuk_gozlem` kanıt alanı (önceki yıl kompozitindeki ortalama geçerli gözlem sayısı ve <3 gözlemli piksel oranı) raporlanır.
- **Son yıl sıçramaları kalıcı katmana sızabilir.** Kalıcı katman en az 2 yıllık "sonrası" ister; yalnızca son yılda (ör. 2026) sıçrayan bir piksel b = 2025'te yarım basamak gösterir ve tek tük pikseller kalıcı katmanda 2025 kırılması olarak geçebilir (MMU tekilleri büyük ölçüde atar). 2026 kırılmaları ayrı `izleme.geojson` katmanındadır.
- **Doku zamanla yukarı kayıyor.** İncek'te AOI doku medyanı 2017→2026 0,021 → 0,030; skoru düşük (değişmeyen) piksellerde de ~%15 artış var. 2025–2026'da sahne sayısı (20–21) 14'e indirildiğinde medyan değişmiyor (0,0289 / 0,0301), yani kayma sahne sayısından kaynaklanmıyor. Nedeni açık (bitki/ağaç büyümesi, yaygın kentleşme veya algılayıcı farkı olabilir).
- Sahne düzeyindeki bulut oranı (`eo:cloud_cover`) 100×100 km MGRS karesine aittir, AOI'ye değil. Asıl temizlik piksel düzeyinde SCL maskesiyle yapılır.
