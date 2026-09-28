# Mini CRM — Site Haritası (sözleşme)

İçerik dersleri bu dosyayı **sözleşme** olarak kullanır: ders metninde geçen sayfa adı, adres, düğme
yazısı, alan adı ve sayı burada yazdığı gibidir. Bir ad değişirse önce burası, sonra kod, sonra ders
metni güncellenir. Kök: `lab/`. Uygulama: `mini_crm/` (Python 3.12+, yalnız standart kitaplık).

- Adres: `http://localhost:8060` (öğrenci) · kontrol 8065 · ekran üretimi 8070 · webhook alıcısı 8061 (ekran üretiminde 8071, kontrolde 8066)
- Veritabanı: `calisma/mini-crm.db` (SQLite). Silinirse ya da `--sifirla` ile örnek veriden yeniden kurulur.
- "Bugün": gerçek gün; ders ekranları `--bugun 2026-09-25` ile. Örnek veri kurulumda bugüne kaydırılır.
- Üst bant her sayfada: "ÖRNEK VERİ · Bütün şirket, kişi, e-posta ve telefonlar uydurmadır."

## Sayfalar

| Menü | Adres | Ders | Ne gösterir / ne yapılır | Önemli öğeler (id / düğme yazısı) |
|---|---|---|---|---|
| Pano | `/` | 1.1, 3.4 | 6 gösterge kartı, aşamaya göre açık hat, en sık kayıp nedenleri, bayat fırsatlar | kartlar: Açık satış hattı · Ağırlıklı değer · Kazanma oranı · Bu ay kazanılan · Geciken görev · Sonraki adımı olmayan fırsat |
| Satış hattı | `/firsatlar` | 2.1, 2.2, 4.3 | 7 sütunlu pano (Yeni → Kaybedildi), sürükle-bırak ve ◀ ▶ | `?sahip=<id>` filtre, "Benim hattım", "Tablo görünümü" (`?gorunum=tablo`), "+ Yeni fırsat"; kart `.fkart[data-id]`, sütun `.kolon[data-asama]` |
| (fırsat) | `/firsat/<id>` | 1.2, 2.2, 2.3 | Aşama düğmeleri, "Kaybedildi olarak işaretle" (+ `#kayip_nedeni`), Aşama geçmişi, Bilgiler formu, Görevler, Notlar, "E-posta taslağı" | `?kaybet=1`: kayıp nedeni formu açık; görev formu `#baslik`, `#son_tarih`, `#sahip_id`, "Ekle" |
| (yeni fırsat) | `/firsat/yeni` | 1.2 | ad*, şirket, ana kişi, tutar*, sahip*, kaynak, beklenen kapanış, aşama | şirket ya da kişiden biri zorunlu |
| Kişiler | `/kisiler` | 1.2, 1.3 | liste, arama (`?ara=`), tanıtım izni rozeti | "+ Yeni kişi" |
| (kişi) | `/kisi/<id>`, `/kisi/yeni` | 1.3, 4.2 | form + "İzin ve aydınlatma" bölümü; yinelenen e-posta reddi | `#eposta` hata: "Bu e-posta zaten … kaydında var" |
| Şirketler | `/sirketler`, `/sirket/<id>`, `/sirket/yeni` | 1.2 | liste; şirketin kişileri ve fırsatları | alan adı benzersiz |
| Görevler | `/gorevler` | 2.3 | "Sonraki adımı olmayan açık fırsatlar" kutusu; Geciken / Bugün / Yaklaşan / Tamamlanan | `?sahip=`, "Benim görevlerim", "Tamamla" |
| Rapor | `/rapor` | 3.1, 3.2, 3.3 | 8 özet kart; huni (`#huni`); kayıp nedenleri (`#kayip`); kaynağa göre (`#kaynak`); sahibe göre (`#sahip`); "Hesap nasıl yapıldı" | filtre `#sahip`, `#baslangic`, `#bitis` (oluşturma tarihi), "Fırsatları CSV indir", "JSON" (`/api/rapor`) |
| Veri denetimi | `/denetim` | 1.3, 4.4 | 9 kural, durum rozeti (düzeltilmeli / gözden geçir / bilgi / temiz), bitirme ölçütü sütunu | `/api/denetim` |
| İçe aktar | `/ice-aktar` | 1.4 | `#nesne` (Şirketler / Kişiler / Fırsatlar), `#dosya`, "Yükle ve denetle" → özet, eşlenen/yok sayılan sütunlar, Hatalar tablosu, Önizleme (hatalı hücre sarı), "N kaydı içe aktar" (hata varsa kapalı) | boş şablon: `/ice-aktar/sablon/<nesne>.csv` |
| Dışa aktar | `/disa-aktar` | 3.1, 4.2 | `/disa-aktar/{sirket,kisi,firsat,gorev,asama_gecmisi}.csv` (UTF-8, virgül) | fırsat CSV'sinde `kazanilma_tarihi` sütunu |
| E-posta şablonları | `/sablonlar`, `/sablon/<id>` | 2.4 | tür rozeti (bilgilendirme / tanıtım), form, "Önizleme için kişi" → doldurulmuş e-posta + uyarılar | `?kisi=<id>&firsat=<id>`; yer tutucular `{{ad}} {{soyad}} {{sirket}} {{firsat}} {{tutar}} {{sahip}}` |
| Otomasyon | `/otomasyon` | 4.1 | 1 · CRM içi kurallar (aç/kapat), 2 · webhook adresi (`#webhook_url`), imza sırrı (maskeli), "Bekleyenleri şimdi gönder", Son olaylar, olay gövdesi (`?olay=<id>`, `#olay`) | `/api/olaylar` |
| KVKK ve izin | `/kvkk` | 4.2 | "hukuki danışmanlık değildir" notu, 4 sayaç, İlgili kişi başvuruları (son tarih = alınma + 30 gün), kişi listesi: "Verisini indir" (`/kvkk/disa/<id>.json`), "Anonimleştir" | başvuru formu `#kisi_id`, `#tur`, `#alinma`, "Başvuruyu kaydet" |
| Ekip | `/ekip` | 4.3 | kişi, rol, açık fırsat/tutar, geciken görev, kazanma oranı; "Aktif yap" | aktif kullanıcı üst sağda |

## Veri modeli (Twenty karşılığıyla)

| Mini CRM | Twenty | Alanlar | Kural |
|---|---|---|---|
| Şirket | Companies | ad*, alan_adi, sektor, calisan, sehir | `alan_adi` benzersiz |
| Kişi | People | ad*, soyad*, eposta, telefon, sirket, unvan, izin_tanitim (evet/hayir/boş), izin_tarihi, izin_kaynagi, aydinlatma_tarihi | `eposta` benzersiz; izin "evet" ise tarih + kaynak zorunlu |
| Fırsat | Opportunities | ad*, sirket, kisi, tutar*, sahip*, kaynak, beklenen_kapanis, asama*, kayip_nedeni | şirket ya da kişi; Kaybedildi ⇒ kayıp nedeni zorunlu; her aşama değişimi geçmişe yazılır |
| Görev | Tasks | baslik*, fırsat ya da kişi, sahip, son_tarih, durum (acik/tamam) | kuraldan gelen görevde `kaynak = kural: …` |
| Not | Notes | metin, fırsat ya da kişi, tarih, yazan | anonimleştirmede kişinin notları silinir |

Aşamalar ve olasılıklar (Twenty "Show Expected Amount" belgesindeki örnek tabloyla aynı):
Yeni %10 · Nitelikli %25 · Görüşme %40 · Teklif %60 · Pazarlık %80 · Kazanıldı %100 · Kaybedildi %0.
Kayıp nedenleri: Fiyat yüksek · Rakip seçildi · Bütçe ertelendi · Yanıt vermedi · İhtiyaç ortadan kalktı · Diğer.
Kaynaklar: Tavsiye · Web sitesi · Instagram · Fuar · Soğuk arama. Ekip: Ayşe Örnek (yönetici), Deniz Deneme, Kaan Kurgu (satış).

## Sayı tanımları (`mini_crm/metrik.py`, bağımsız kopya `dogrula/rapor_dogrula.py`)

- **Kazanma oranı** = kazanılan ÷ (kazanılan + kaybedilen); açık fırsat paydaya girmez.
- **Aşamaya ulaşan** = o aşamaya ya da ötesine varmış fırsat; atlanan aşama geçilmiş sayılır; kazanılan bütün açık aşamaları geçmiştir; kaybedilen, kaybedilmeden önceki son açık aşamasına kadar sayılır.
- **Geçiş oranı** = sonraki aşamaya ulaşan ÷ bu aşamaya ulaşan.
- **Ağırlıklı değer** = Σ açık fırsat tutarı × aşama olasılığı.
- **Satış süresi** = oluşturma → Kazanıldı günü; kazanılanların ortalaması.
- **Bayat** = açık ve 14+ gündür güncellenmemiş. **Sonraki adımı olmayan** = açık ve ileri tarihli (son tarih ≥ bugün) açık görevi yok.

## Örnek verinin sayıları (ilk kurulum, bugün = 25.09.2026) — elle hesaplandı, `rapor_dogrula.py --beklenen` ile doğrulandı

| Ölçü | Değer |
|---|---|
| Fırsat | 24 (6 kazanılan, 6 kaybedilen, 12 açık) |
| Açık hat / ağırlıklı değer | 240.800 TL / 128.805 TL |
| Kazanma oranı | %50 (6 / 12) |
| Kazanılan tutar / ortalama | 171.800 TL / 28.633 TL |
| Ortalama satış süresi | 26,67 gün (20, 46, 8, 24, 30, 32) |
| Huni (ulaşan) | Yeni 24 → Nitelikli 21 → Görüşme 17 → Teklif 13 → Pazarlık 9 → Kazanıldı 6 |
| Geçiş oranları | %87,5 · %81 · %76,5 · %69,2 · %66,7 |
| Kayıp nedenleri | Fiyat yüksek 3 (%50) · Bütçe ertelendi 1 · Rakip seçildi 1 · Yanıt vermedi 1 |
| Kaynağa göre kazanma | Tavsiye %66,7 (2/3) · Web sitesi %50 · Instagram %50 · Soğuk arama %50 · Fuar %33,3 (1/3) |
| Görevler | 3 geciken (#8 15.09, #7 19.09, #5 22.09), 1 bugün (#2) |
| Sonraki adımı olmayan | 5 fırsat: hiç görevi yok 2 (Üye kartları #16, Hasta bilgilendirme broşürü #20), yalnız gecikmiş görevi olan 3 (#18, #21, #22) |
| Bayat | 4 (#16, #18, #20, #22) · beklenen kapanışı geçmiş: 1 (#22, 20.09.2026) |
| Tanıtım izni | evet 8 · hayır 3 · bilinmiyor 3 (Burak Taslak, Deren Temsili, İpek Örnek) |
| Bu ay kazanılan | 1 fırsat, 9.800 TL (#6, 04.09) |

Açıklayıcı kayıtlar: #24 Konut projesi katalogu (Pazarlık, 56.000 TL, Pusula Emlak — 1.2 ve 4.1'in fırsatı),
#5 Fuar standı baskıları (Nitelikli → Teklif, Görüşme atlanmış), #14 Düğün davetiyesi (şirketsiz, bireysel
kişi Nazlı Taslak — şablonda `{{sirket}}` boş kalır), #22 Okul sezonu kampanya seti (2.2'de Kaybedildi yapılır).

## Otomasyon ve webhook

- Kural 1 (açık): Fırsat Kazanıldı olunca sahibine 3 gün sonrası için "Teslimat ve fatura" görevi.
- Kural 2 (kapalı; öğrenci açar): Teklif aşamasına girince 2 gün sonrası için "Teklifi takip et" görevi.
- Olay adları Twenty biçiminde: `person.created`, `company.updated`, `opportunity.updated`, `task.created` …
  Gövde: `{"event", "data", "timestamp"}`; `opportunity.updated` gövdesinde `onceki_asama` da var.
- Başlıklar: `X-MiniCRM-Zaman`, `X-MiniCRM-Imza` = HMAC-SHA256(sır, "zaman:gövde") (Twenty: `X-Twenty-Webhook-Signature`, aynı ilke).
- Webhook adresi yokken oluşan olay "webhook yok" diye kaydedilir, sonradan gönderilmez.

## İçe aktarma kuralları (`mini_crm/ice_aktar.py`)

Kodlama: UTF-8 (BOM'lu/BOM'suz); değilse Windows-1254 diye okunur ve uyarı verir. Ayraç: ilk satırda `;` `,`'den
çoksa noktalı virgül. Başlıklar Türkçe/İngilizce takma adlarla eşlenir (ör. "E-posta" → `eposta`, "Şirket" →
`sirket_alan_adi`); eşlenmeyen sütun "yok sayılan" olarak gösterilir. Hata türleri (Twenty'deki dört türle aynı):
**Yinelenen değer** (CRM'de ya da dosyada), **Geçersiz biçim**, **Zorunlu alan boş**, **İlişki bulunamadı**.
Tarih: `YYYY-AA-GG` ya da `GG.AA.YYYY`. Tutar: `12500` ya da `12.500`. Satır numarası başlık = 1.

## Ders ekranları (`ekran/`, `araclar/ekranlari_uret.py` ile)

| Ders | Dosyalar |
|---|---|
| 1.1 | `pano.png`, `mini-crm-ac.png/.txt` |
| 1.2 | `sirket-demir-mobilya.png`, `firsat-konut-katalogu.png`, `kisiler.png` |
| 1.3 | `kisi-yinelenen-eposta.png` (+ 4.4 `veri-denetimi.png`) |
| 1.4 | `csv-hatali-dosya.png/.txt`, `ice-aktar-hatali.png`, `ice-aktar-hatali-tam.png`, `ice-aktar-duzeltilmis.png`, `ice-aktar-sonuc.png` |
| 2.1 | `satis-hatti.png`, `satis-hatti-tablo.png` |
| 2.2 | `surukle-birak-sonrasi.png`, `kaybedildi-neden-sor.png`, `kaybedildi-sonrasi.png` |
| 2.3 | `gorevler.png`, `firsat-gorev-eklendi.png` |
| 2.4 | `sablonlar.png`, `sablon-takip-onizleme.png`, `sablon-tanitim-izin-yok.png` |
| 3.1 | `rapor.png`, `rapor-ayse.png`, `firsat-csv.png/.txt`, `mini-crm-firsat.csv` |
| 3.2 | `rapor-huni.png`, `rapor-dogrula.png/.txt`, `rapor-dogrula-tam.txt/.png`, `rapor-dogrula-bozuk.png/.txt` |
| 3.3 | `rapor-kayip-kaynak.png` |
| 3.4 | `pano-tam.png` |
| 4.1 | `otomasyon.png`, `kazanildi-kural-calisti.png`, `olay-govdesi.png`, `webhook-alici.png/.txt` |
| 4.2 | `kvkk.png`, `kvkk-tam.png`, `kisi-izin-bilinmiyor.png` |
| 4.3 | `ekip.png`, `satis-hatti-deniz.png` |
| 4.4 | `veri-denetimi.png` |
