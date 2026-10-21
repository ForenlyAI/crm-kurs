# CRM'le Müşteri Takibi — Lab: Mini CRM

Bu klasör kursun pratik ortamıdır: **Mini CRM** adlı, bilgisayarınızda çalışan küçük bir CRM ve
alıştırma dosyaları. Örnek işletme **Mavi Kalem Baskı Atölyesi**'dir (uydurma): kartvizit, menü,
katalog ve afiş basan küçük bir atölye; müşterileri yerel işletmeler.

> Bütün şirket, kişi, e-posta ve telefonlar **uydurmadır**: e-postalar `example.com` altında,
> telefonlar `0000 000 00 ..`. Gerçek müşteri verinizi bu lab'a koymayın.

Mini CRM, gerçek bir CRM'in (kursta örnek: **Twenty**, açık kaynak) temel nesnelerini aynı adlarla
taşır: Kişiler (People), Şirketler (Companies), Fırsatlar (Opportunities), Görevler (Tasks), Notlar
(Notes). Twenty'yi kurmanız gerekmez; kavramlar Twenty'nin resmi belgelerinden, uygulama bu lab'dan.

## 1. Kurulum ve açma (tek komut)

Önce [uv](https://docs.astral.sh/uv/) kurulu olmalı. Sonra bu klasörde:

```bash
uv run python -m mini_crm.sunucu
```

İlk açılışta örnek veri kurulur ve şunu görürsünüz:

```
Örnek veri kuruldu: calisma/mini-crm.db (bugün = 2026-09-25)
Mini CRM açık: http://localhost:8060  (durdurmak için Ctrl+C)
```

Tarayıcıda **http://localhost:8060** adresini açın. Durdurmak için terminalde `Ctrl+C`.

- Mini CRM yalnız Python'un kendi kitaplığıyla çalışır (hiçbir paket gerekmez). `uv` doğru Python
  sürümünü (3.12+) kendisi getirir; `pyproject.toml` + `uv.lock` sürümleri sabitler.
- Yalnız bu bilgisayardan açılır (127.0.0.1). E-posta göndermez. İnternete çıkmaz — tek istisna:
  Otomasyon sayfasına bir webhook adresi yazarsanız olayları yalnız o adrese gönderir (varsayılan boş).

| Komut | Ne yapar |
|---|---|
| `uv run python -m mini_crm.sunucu` | Mini CRM'i açar (http://localhost:8060) |
| `uv run python -m mini_crm.sunucu --sifirla` | Bütün değişikliklerinizi silip örnek veriye döner |
| `uv run python -m mini_crm.sunucu --port 8070` | Başka bir portta açar (8060 doluysa) |
| `uv run python dogrula/rapor_dogrula.py` | Rapor sayılarını CSV'den bağımsız yeniden hesaplar (ders 3.2) |
| `uv run python ornekler/webhook_alici.py` | Olayları dinleyen küçük alıcı (ders 4.1) |
| `bash kontrol.sh` | Lab'ın her adımını dener, GEÇTİ/KALDI yazar |

**Tarihler:** Örnek verideki görev ve fırsat tarihleri, kurulum günü "bugün" sayılarak kaydırılır;
kursu hangi gün izlerseniz izleyin "geciken görev" ve "bugün" listeleri derstekiyle aynı görünür.
Ders ekranları 25.09.2026 günüyle çekildi.

### Windows

- uv kurulumu (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Komutlar PowerShell'de aynıdır: `uv run python -m mini_crm.sunucu`
- `kontrol.sh` bir bash betiğidir; Git Bash ya da WSL içinde çalıştırın (öğrenci için gerekli değil).
- Excel'de CSV açarken Türkçe karakterler bozuk görünürse: Veri → Metinden/CSV'den → kodlama **65001: UTF-8**.

### macOS / Linux

- uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## 2. Klasör yapısı

```
lab/
├── mini_crm/              ← UYGULAMA (Python standart kitaplığı)
│   ├── sunucu.py          sayfalar ve adresler (http://localhost:8060)
│   ├── db.py              SQLite şeması, örnek veriden kurulum, olay kaydı
│   ├── metrik.py          rapor ve pano sayıları (tek hesap yeri)
│   ├── ice_aktar.py       CSV okuma, sütun eşleme, satır doğrulama
│   ├── otomasyon.py       kurallar (tetikleyici → koşul → eylem) ve webhook gönderimi
│   ├── arayuz.py          sayfa iskeleti, TL / yüzde / tarih biçimi
│   └── statik/            stil, sürükle-bırak betiği, yazı tipleri (Source Sans 3, JetBrains Mono — OFL)
├── veri/
│   ├── ornek-veri.json    örnek veri (8 şirket, 14 kişi, 24 fırsat, 15 görev, 2 şablon)
│   └── ice-aktar/         içe aktarma alıştırma dosyaları (ders 1.4)
├── calisma/               sizin veritabanınız (mini-crm.db) — silerseniz örnek veriye döner
├── dogrula/rapor_dogrula.py   rapor sayılarını bağımsız yeniden hesaplar
├── ornekler/webhook_alici.py  webhook alıcısı (n8n Webhook düğümünün yaptığı işin özü)
├── araclar/               ders ekranlarını üreten araçlar (kurs ekibi için)
├── ekran/<ders>/          gerçek ekran görüntüleri (.png) ve terminal çıktıları (.txt)
├── kontrol.sh             bütün lab adımlarını dener
├── pyproject.toml, uv.lock, .python-version
├── README.md              bu dosya
└── SITE-HARITASI.md       sayfalar, adresler, kimlikler, sayılar — derslerin sözleşmesi
```

## 3. İçe aktarma dosyaları (`veri/ice-aktar/`)

| Dosya | Ne öğretir |
|---|---|
| `kisiler-hatali.csv` | Excel'den gelmiş gibi: `;` ayraçlı, UTF-8 (BOM'lu), Türkçe başlıklar. 9 satır, **9 hata**, dört tür: Yinelenen değer (2), Geçersiz biçim (3), Zorunlu alan boş (3), İlişki bulunamadı (1). Tek hata varsa hiçbir satır kaydedilmez |
| `kisiler-duzeltilmis.csv` | Aynı dosyanın düzeltilmiş hâli: 6 satır, 0 hata |
| `sirketler.csv` | 3 yeni şirket (virgül ayraçlı, kanonik başlıklar) |
| `kisiler-yeni-sirketler.csv` | O 3 şirketin kişileri. Şirketlerden **önce** aktarılırsa 3 × "İlişki bulunamadı" — sıra: şirket → kişi → fırsat |
| `firsatlar.csv` | 3 fırsat (biri Kaybedildi + kayıp nedeni) |

## 4. Kontrol

```bash
bash kontrol.sh
```

Öğrencinin Mini CRM'ine dokunmadan (ayrı veritabanı, port 8065) her dersin adımını dener:
sayfaların açılması, yinelenen e-postanın reddi, içe aktarmada 9 hata, aşama değişikliği ve geçmiş,
kayıp nedeni zorunluluğu, görev, şablon izni, rapor sayılarının bağımsız hesapla aynı çıkması,
webhook imzası (doğru sır → 200, yanlış sır → 401), KVKK başvuru süresi ve anonimleştirme.
İki **negatif test** vardır: bozulmuş CSV'de doğrulayıcı KALDI demeli, yanlış sırla alıcı reddetmeli.

Son çalıştırma (2026-09-25, Linux, Python 3.12.3, uv 0.12.5): **41 / 41 GEÇTİ**.

## 5. Ders görselleri nasıl üretildi (kurs ekibi için)

Tüm görüntüler **gerçek** Mini CRM'in ve **gerçek** komut çıktısının çekimidir.

```bash
uv run --group araclar python araclar/ekranlari_uret.py             # bütün dersler (ayrı veritabanı, port 8070)
uv run --group araclar python araclar/ekranlari_uret.py 2.2 4.1     # yalnız bu dersler
uv run --group araclar python araclar/ekran.py 3.1 rapor http://localhost:8060/rapor [--mobil] [--tam]
uv run --group araclar python araclar/terminal.py 3.2 rapor-dogrula -- uv run python dogrula/rapor_dogrula.py --ozet
```

- Tarayıcı: masaüstü 1280×800 (mobil 390×844). Tam Chromium, Türkçe dil ortamıyla (tarih kutusu
  `29.09.2026`, dosya seçici "Dosya Seç" görünsün diye). Terminal: 740×462, JetBrains Mono ~20 px
  (sığmazsa 14 px'e kadar küçülür, yine sığmazsa baştaki satırlar gizlenir ve bu üstte yazar).
  Ham çıktı `.txt` olarak `.png`'nin yanında durur.
- Terminal çıktısında tek düzeltme: lab'ın mutlak yolu `~/lab` olarak kısaltılır.
- Webhook ekranında imza sırrı yalnız ilk 4 karakteriyle görünür; her kurulumda yeni üretilir.
