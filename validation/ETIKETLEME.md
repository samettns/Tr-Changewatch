# Etiketleme talimatı

Amaç: her noktada **2017–2026 arasında arazi örtüsünün kalıcı olarak değişip değişmediğini**, değiştiyse türünü ve **değişimin ilk görüldüğü yılı** belirlemek. Sistemin tahmini gösterilmez (kör etiketleme); karar yalnızca görüntülere dayanır.

## Başlatma

```bash
changewatch label            # ana örnekleme (280 nokta) → validation/labels.csv
changewatch label --set su   # Gölbaşı su doğrulama seti (16 nokta) → validation/water_labels.csv
```

Çipler yoksa ya da örnekleme değiştiyse önce `changewatch label-prep` çalıştırın.

## Ekranda ne var

- Noktanın çevresi (820 m × 820 m), 2017–2026 yaz kompozitleri, 2 satır × 5 yıl. Sarı kare = değerlendirilen 20 m piksel; kesikli daire = yakın çevre (±60 m).
- Karar **sarı karenin içi** içindir. Çevredeki değişim tek başına "evet" demek için yeterli değildir.
- Emin olamazsanız **G** ile Google Haritalar uydu görünümünü açın (güncel ve geçmiş görüntü için Google Earth Pro'nun "geçmiş görüntüler" aracı da kullanılabilir; bu görüntüler repoya konmaz).

## Klavye

| Tuş | Anlamı |
|---|---|
| **E** / **H** | Değişim **evet** / **hayır** |
| **Y** | yapılaşma |
| **B** | bitki kaybı |
| **K** | su kazanımı |
| **L** | su kaybı |
| **D** | diğer |
| **8 9 0 1 2 3 4 5 6** | ilk görüldüğü yılın son hanesi (8 = 2018 … 0 = 2020 … 6 = 2026) |
| **X** | yıl bilinmiyor |
| **N** | not (isteğe bağlı) |
| **Enter** | kaydet + sonraki |
| **← / →** | önceki / sonraki (tam bir giriş varsa gezinirken de kaydedilir) |
| **G** | Google Haritalar'da aç |

Tür ya da yıl tuşuna basmak değişimi otomatik "evet" yapar. "Hayır" seçilince tür ve yıl temizlenir. Her kayıttan sonra CSV yeniden yazılır; uygulamayı kapatıp açınca ilk etiketlenmemiş noktadan devam eder. Geri dönüp düzeltme yapabilirsiniz.

## Ne zaman hangi tür

**Yapılaşma (Y)** — kalıcı, insan yapımı yüzeye dönüşüm başladı:
- bina, site, çatı, beton/asfalt alan, yeni yol, otopark;
- **şantiye, tesviye, hafriyat, temel kazısı** (inşaat başlamışsa yapılaşma sayılır, bitmiş olması gerekmez);
- sera/ahır gibi kalıcı yapılar.

**Bitki kaybı (B)** — yapı olmadan kalıcı yeşil örtü kaybı:
- ağaçlık/koru kesimi, bahçe/park sökümü, yangın sonrası kalıcı açıklık, kurumuş sulak bitki örtüsü.
- Kesimin ardından aynı yerde inşaat başladıysa bu tek bir süreçtir: tür **yapılaşma**, yıl sürecin **ilk görülen adımı** (kesim ya da tesviye hangisi önce görünüyorsa).

**Su kazanımı (K) / su kaybı (L)** — açık su kalıcı olarak başladı / bitti:
- kıyı çizgisinin ilerlemesi/çekilmesi, yeni gölet/baraj, kuruyan su alanı.
- **Göl içinde suyun rengi değişti** (yeşillenme, bulanıklık) → **değişim yok (H)**.
- Sazlık/kıyı bitkisi suyla dönüşümlü görünüyorsa ve kalıcı değilse → **değişim yok**; kalıcı ama türü belirsizse → **diğer**.

**Diğer (D)** — kalıcı değişim var ama yukarıdakilere uymuyor: maden/taş ocağı genişlemesi (inşaat değilse), dolgu/döküm alanı, belirsiz kalıcı yüzey değişimi.

**Değişim yok (H)**:
- **sürülmüş tarla, nadas, hasat, ekim–nadas döngüsü** (her yıl farklı görünse de);
- mevsimsel/yıllık yeşillik farkı, kuraklık yılı, bulut/gölge artığı, görüntü kalitesi farkı;
- 2017'den önce zaten yerleşim olan, sadece çatı rengi/çevre düzenlemesi değişen alanlar;
- göl içi renk değişimi.

## İlk görüldüğü yıl

- Değişimin **ilk göründüğü yaz** (ör. tesviye 2021 yazında görünüyorsa 2021). Bina 2023'te bitse de tesviye 2021'deyse **2021**.
- Değişim 2017'de zaten başlamışsa (2017 karesinde şantiye görünüyorsa): **H** (dönem içinde yeni başlamadı) ve notta "2017 öncesi" yazın.
- Emin değilseniz **X** (bilinmiyor) seçin; yıl isabeti hesabına katılmaz.

## Notlar

Kısa ve somut olsun: "tesviye 2021, bina 2023", "tarla nadas", "göl rengi", "bulut artığı 2019". Notlar karar listesindeki belirsiz durumları (ör. Gölbaşı kuzey körfezi 2021) ayırmak için kullanılır.
