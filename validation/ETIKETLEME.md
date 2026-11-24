# Etiketleme talimatı

Ana soru: **"Bu noktada 2017'den bugüne yeni bina, şantiye veya yol yapıldı mı?"** Sistemin tahmini, tabaka ve AOI gösterilmez (kör etiketleme); karar yalnızca görüntülere dayanır.

## Başlatma

```bash
changewatch label            # yalnızca TEST noktaları (197) → validation/labels.csv
changewatch label --set su   # Gölbaşı su doğrulama seti (16 nokta) → validation/water_labels.csv
```

Kalibrasyon noktaları gizlidir (yöntem donduruldu; `validation.label_roles` ile açılır); CSV'deki satırları ve mevcut etiketleri korunur. Çipler yoksa ya da örnekleme değiştiyse önce `changewatch label-prep` çalıştırın.

## Ekranda ne var

- Üstte **2017** ve **2026** büyük, yan yana (820 m × 820 m, piksel büyütülmüş). Kırmızı artı = değerlendirilen 20 m piksel (ortası boş, piksel görünsün diye); kırmızı halka = 100 m yarıçap; sol altta 200 m ölçek çubuğu.
- Altta 2017–2026 tüm yıllar (2 × 5), aynı artı işaretiyle: değişimin hangi yıl başladığını buradan okuyun.
- Karar **artının merkezindeki piksel** içindir; halka yakın çevreyi gösterir.
- **G**: Google Haritalar uydu görünümü, noktada iğne ile açılır (güncel görüntü; geçmiş için Google Earth Pro "geçmiş görüntüler"; bu görüntüler repoya konmaz).

## Klavye

| Tuş | Anlamı |
|---|---|
| **E** | **evet** (tür varsayılan: yapılaşma) |
| **H** | **hayır** |
| **U** | **emin değilim** (metriklerden çıkarılır, ayrı sayılır) |
| **Y B K L D** | isteğe bağlı başka tür: yapılaşma · bitki kaybı · su kazanımı · su kaybı · diğer (basınca cevap "evet" olur) |
| **7 8 9 0 1 2 3 4 5 6** | isteğe bağlı: ilk görüldüğü yılın son hanesi (8 = 2018 … 0 = 2020 … 6 = 2026); girilmezse **bilinmiyor** |
| **X** | yıl bilinmiyor |
| **N** | not (isteğe bağlı) |
| **Enter** | kaydet + sonraki |
| **← / →** | önceki / sonraki (değiştirilmiş geçerli giriş gezinirken de kaydedilir) |
| **G** | Google Haritalar'da aç |

En hızlı akış: bak → **E/H/U** → **Enter**. İlerleme "Etiketlenen X / 197 test noktası" olarak görünür; "emin değilim" cevapları da sayılır ve ayrıca gösterilir. Her kayıttan sonra CSV yeniden yazılır; uygulama kapatılıp açılınca ilk etiketlenmemiş noktadan devam eder.

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
- Yıl girmek isteğe bağlıdır; girilmezse ya da **X** seçilirse "bilinmiyor" yazılır ve yıl isabeti hesabına katılmaz.
- Değişim olup olmadığından emin değilseniz **U** (emin değilim): nokta metriklere katılmaz, `changewatch validate` ayrı sayar.

## Notlar

Kısa ve somut olsun: "tesviye 2021, bina 2023", "tarla nadas", "göl rengi", "bulut artığı 2019". Notlar karar listesindeki belirsiz durumları (ör. Gölbaşı kuzey körfezi 2021) ayırmak için kullanılır.
