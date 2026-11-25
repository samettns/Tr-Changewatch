# CLAUDE.md — TR-ChangeWatch çalışma kuralları

Projenin kapsamı, mimarisi ve fazları `PROJECT_SPEC.md` içindedir. Her oturumun başında onu oku. Spec'te olmayan bir özellik ekleme; gerekiyorsa önce spec'teki "v2" bölümüne yazmayı öner.

## Çalışma biçimi
- Her seferinde tek modül yaz. Modülün testi geçmeden ve CLI komutu gerçek bir AOI'de çalışmadan sonraki modüle geçme.
- Bir fazı bitirdiğinde spec'teki "bitti" ölçütünü tek tek kontrol et ve sonucu bildir.
- Görsel çıktı üreten adımlarda (kompozit, değişim maskesi) PNG üret ve dosya yolunu söyle; doğruluğu ben gözle kontrol edeceğim.
- Eşikleri koda gömme; hepsi `config/settings.yaml` içinde olsun.
- Doğrulama test noktalarını eşik ayarlamak için kullanma; yalnızca kalibrasyon noktalarını kullan.

## Veri kuralları
- Tam Sentinel-2 sahnesi indirme; yalnızca AOI kutusunu pencereli oku (odc-stac).
- Ham veri önbelleği ve ara çıktılar önbellek klasörüne yazılır: varsayılan proje içi `./data` (`settings.yaml` → `cache_dir`); bu makinede `CHANGEWATCH_CACHE` ortam değişkeniyle harici SSD (`D:\tr-changewatch-data`). Sanal ortam (`.venv`) ve kod proje klasöründe, yerel diskte kalır.
- Baseline ≥ 04.00 sahnelerde offset harmonizasyonunu atlama. Karar `s2:processing_baseline` alanına göre verilir; alan yoksa tarihe göre (25.01.2022 ve sonrası) karar verilir ve log'a uyarı yazılır. İki durumun da unit testi olsun.
- GeoTIFF ve önbellek dosyalarını asla commit'leme (`data/` .gitignore'da). Repoya yalnızca GeoJSON, JSON, CSV ve küçük PNG girer.
- Testler ağa çıkmaz; sentetik diziler ve `tests/fixtures/` kullanılır.

## Git
- Commit mesajlarına `Co-Authored-By` satırı, Claude imzası veya oturum linki ekleme. Repoda yazar olarak yalnızca ben görünmeliyim.
- Commit'ten önce `git config user.name` ve `user.email` değerlerinin bana ait olduğunu kontrol et.
- README'de geliştirmede yapay zekâ araçlarının kullanıldığı belirtilebilir.
- Commit mesajları kısa ve Türkçe olsun (ör. `harmonize: baseline offset düzeltmesi ve testi`).

## Kod stili
- Python 3.12 (≥ 3.11), tip ipuçları, kısa docstring'ler.
- Her modülün tek bir sorumluluğu olsun (spec'teki repo yapısına uy).
