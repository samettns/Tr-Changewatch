# TR-ChangeWatch

Ankara'daki seçili bölgelerde Sentinel-2 L2A ile yapılaşma ve arazi örtüsü değişimini kanıtıyla ve güven düzeyiyle haritalayan değişim izleme sistemi. Kapsam ve mimari: [PROJECT_SPEC.md](PROJECT_SPEC.md).

> Geliştirme sürüyor (Faz 2).

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
changewatch composite --aoi incek --years 2017 2024     # harmonizasyon + SCL maskesi + medyan kompozit
```

## Bilinen sınırlamalar

- **02.12 baseline'ında parlak yüzeyler bulut sayılabiliyor.** 2017–2020 sahneleri (processing baseline 02.12) bulutsuz günlerde bile parlak yüzeyleri (şantiye, yol, parlak çatı) SCL 8/9 (orta/yüksek olasılıklı bulut) olarak sınıflandırabiliyor. İncek 2017 yaz kompozitinde AOI piksellerinin ~%0,2'sinde 3'ten az geçerli gözlem kaldı; bu pikseller kompozitte boş bırakılır. Maske değiştirilmedi; bunun yerine her değişim poligonunda `dusuk_gozlem` kanıt alanı (önceki yıl kompozitindeki ortalama geçerli gözlem sayısı ve <3 gözlemli piksel oranı) raporlanır.
- Sahne düzeyindeki bulut oranı (`eo:cloud_cover`) 100×100 km MGRS karesine aittir, AOI'ye değil. Asıl temizlik piksel düzeyinde SCL maskesiyle yapılır.
