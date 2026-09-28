#!/usr/bin/env bash
# CRM 101 — lab kontrolü. Her dersin lab adımını gerçekten çalıştırır ve GEÇTİ/KALDI yazar.
#
#   ./kontrol.sh            (lab klasöründe; Linux/macOS ya da Windows'ta Git Bash/WSL)
#
# Öğrencinin Mini CRM'ine (calisma/mini-crm.db, port 8060) DOKUNMAZ: kendi geçici veritabanını
# 8065 portunda açar, 8066'da bir webhook alıcısı çalıştırır, sonunda hepsini kapatıp siler.
# İnternete bağlanmaz; hiçbir yere e-posta ya da veri göndermez.
set -u
cd "$(dirname "$0")"
PORT=8065; ALICI_PORT=8066
ADRES="http://localhost:$PORT"
DB="calisma/kontrol.db"
GUN="2026-09-25"
GECICI="$(mktemp -d)"
SUNUCU=""; ALICI=""
GECEN=0; KALAN=0

kapat() {
  [ -n "$ALICI" ] && kill "$ALICI" 2>/dev/null && wait "$ALICI" 2>/dev/null
  [ -n "$SUNUCU" ] && kill "$SUNUCU" 2>/dev/null && wait "$SUNUCU" 2>/dev/null
  rm -rf "$GECICI" "$DB"
}
trap kapat EXIT

sonuc() {  # sonuc <ders> <açıklama> <0=geçti>
  if [ "$3" = 0 ]; then printf 'GEÇTİ  %-5s %s\n' "$1" "$2"; GECEN=$((GECEN + 1))
  else printf 'KALDI  %-5s %s\n' "$1" "$2"; KALAN=$((KALAN + 1)); fi
}
bekle() { for _ in $(seq 1 50); do curl -s -o /dev/null "$1" && return 0; sleep 0.2; done; return 1; }
icerir() { grep -q -- "$2" "$1"; echo $?; }
al() { curl -s "$ADRES$1" -o "$GECICI/sayfa.html"; }
yolla() { curl -s -o /dev/null -w '%{http_code}' -X POST "$ADRES$1" "${@:2}"; }
json() { uv run --quiet python -c "import json,sys; d=json.load(open('$GECICI/j.json')); print($1)"; }
ice_aktar() {  # ice_aktar <nesne> <dosya> → önizleme sayfası $GECICI/ice.html
  curl -s -X POST "$ADRES/ice-aktar" -F "nesne=$1" -F "dosya=@$2;type=text/csv" -o "$GECICI/ice.html"
}
onayla() {
  local t; t=$(grep -oE 'name="token" value="[0-9a-f]+"' "$GECICI/ice.html" | grep -oE '[0-9a-f]{16}')
  curl -s -o /dev/null -w '%{redirect_url}' -X POST "$ADRES/ice-aktar/onayla" -d "token=$t"
}

echo "python $(uv run --quiet python -c 'import platform; print(platform.python_version())') · uv $(uv --version | cut -d' ' -f2)"
uv sync --frozen --inexact --quiet; sonuc "lab" "uv sync --frozen (pyproject + uv.lock; Mini CRM paket istemiyor)" $?
uv run --quiet python -m py_compile mini_crm/*.py dogrula/*.py ornekler/*.py araclar/*.py; sonuc "lab" "bütün Python dosyaları derleniyor" $?

uv run --quiet python -m mini_crm.sunucu --port "$PORT" --db "$DB" --sifirla --bugun "$GUN" --sessiz >"$GECICI/sunucu.log" 2>&1 &
SUNUCU=$!
bekle "$ADRES/"; sonuc "lab" "Mini CRM açıldı ($ADRES, bugün=$GUN)" $?

# --- her sayfa açılıyor mu
hata=0
for yol in / /firsatlar "/firsatlar?gorunum=tablo" /firsat/24 /firsat/yeni /kisiler /kisi/4 /kisi/yeni /sirketler /sirket/2 \
           /gorevler /sablonlar /sablon/1 /rapor /denetim /ice-aktar /disa-aktar /otomasyon /kvkk /ekip \
           /api/rapor /api/denetim /disa-aktar/firsat.csv /disa-aktar/kisi.csv /ice-aktar/sablon/kisi.csv /statik/stil.css; do
  kod=$(curl -s -o /dev/null -w '%{http_code}' "$ADRES$yol"); [ "$kod" = 200 ] || { echo "   $yol → $kod"; hata=1; }
done
kod=$(curl -s -o /dev/null -w '%{http_code}' "$ADRES/olmayan-sayfa"); [ "$kod" = 404 ] || hata=1
sonuc "tümü" "26 sayfa 200, olmayan sayfa 404" $hata

# --- 1.1 / 3.4 pano sayıları
curl -s "$ADRES/api/rapor" -o "$GECICI/j.json"
[ "$(json 'd["acik_sayi"], d["acik_tutar"], d["geciken_gorev"], len(d["gorevsiz_firsatlar"]) + len(d["yalniz_geciken_gorevli_firsatlar"])')" = "12 240800 3 5" ]
sonuc "1.1" "pano: 12 açık fırsat, 240.800 TL, 3 geciken görev, 5 sonraki adımsız fırsat" $?

# --- 1.2 kişi-şirket-fırsat ilişkisi
al /sirket/2; [ "$(icerir "$GECICI/sayfa.html" 'Kerem')$(icerir "$GECICI/sayfa.html" 'Ürün katalogu')" = "00" ]
sonuc "1.2" "şirket sayfası bağlı kişiyi ve fırsatı gösteriyor" $?
kod=$(yolla /sirket/yeni -d "ad=Deneme Ajans&alan_adi=deneme-ajans.example.com&sektor=Reklam"); [ "$kod" = 303 ]
sonuc "1.2" "yeni şirket kaydı (303 → şirket sayfası)" $?
kod=$(yolla /kisi/yeni -d "ad=Derya&soyad=Deneme&eposta=derya@deneme-ajans.example.com&sirket_id=9&unvan=Kurucu"); [ "$kod" = 303 ]
sonuc "1.2" "yeni kişi, yeni şirkete bağlı" $?
kod=$(yolla /firsat/yeni -d "ad=Broşür baskısı&sirket_id=9&kisi_id=15&tutar=9500&sahip_id=1&kaynak=Tavsiye&beklenen_kapanis=2026-10-30&asama=yeni"); [ "$kod" = 303 ]
sonuc "1.2" "yeni fırsat, şirket + kişiyle ilişkili" $?
al /firsat/25; [ "$(icerir "$GECICI/sayfa.html" 'Deneme Ajans')$(icerir "$GECICI/sayfa.html" 'Derya Deneme')" = "00" ]
sonuc "1.2" "fırsat sayfası şirketi ve kişiyi gösteriyor" $?

# --- 1.3 veri kuralı: yinelenen e-posta reddedilir
curl -s -X POST "$ADRES/kisi/yeni" -d "ad=Elif&soyad=Örnek&eposta=ELIF@lale-kafe.example.com" -o "$GECICI/sayfa.html"
[ "$(icerir "$GECICI/sayfa.html" 'zaten Elif Örnek kaydında var')" = 0 ]; sonuc "1.3" "aynı e-postayla ikinci kişi açılamıyor (büyük harfle bile)" $?
curl -s -X POST "$ADRES/kisi/yeni" -d "ad=Deniz&soyad=Kurgu&eposta=deniz@ornek&izin_tanitim=evet" -o "$GECICI/sayfa.html"
[ "$(icerir "$GECICI/sayfa.html" 'biçimi bozuk')$(icerir "$GECICI/sayfa.html" 'tarihi yazın')" = "00" ]
sonuc "1.3" "bozuk e-posta ve tarihsiz izin reddediliyor" $?

# --- 1.4 içe aktarma
ice_aktar kisi veri/ice-aktar/kisiler-hatali.csv
[ "$(icerir "$GECICI/ice.html" '9 hata')$(icerir "$GECICI/ice.html" 'noktalı virgül')$(icerir "$GECICI/ice.html" '<button disabled>1 kaydı')" = "000" ]
sonuc "1.4" "kisiler-hatali.csv: 9 hata (4 tür), ; ayraç tanındı, aktar düğmesi kapalı" $?
[ "$(onayla)" = "$ADRES/ice-aktar?m=Dosyada%20hata%20oldu%C4%9Fu%20i%C3%A7in%20hi%C3%A7bir%20kay%C4%B1t%20aktar%C4%B1lmad%C4%B1.&mt=hata" ]
sonuc "1.4" "hatalı dosya zorla onaylanınca hiçbir satır yazılmıyor" $?
ice_aktar kisi veri/ice-aktar/kisiler-yeni-sirketler.csv
[ "$(icerir "$GECICI/ice.html" '3 hata')$(icerir "$GECICI/ice.html" 'İlişki bulunamadı')" = "00" ]
sonuc "1.4" "şirketler aktarılmadan kişiler: 3 × İlişki bulunamadı (sıra önemli)" $?
ice_aktar sirket veri/ice-aktar/sirketler.csv; [ "$(onayla)" = "$ADRES/sirketler?m=3%20kay%C4%B1t%20i%C3%A7e%20aktar%C4%B1ld%C4%B1." ]
sonuc "1.4" "sirketler.csv → 3 şirket aktarıldı" $?
ice_aktar kisi veri/ice-aktar/kisiler-yeni-sirketler.csv; r1=$(onayla)
ice_aktar kisi veri/ice-aktar/kisiler-duzeltilmis.csv; r2=$(onayla)
ice_aktar firsat veri/ice-aktar/firsatlar.csv; r3=$(onayla)
[ "$r1$r2$r3" = "$ADRES/kisiler?m=3%20kay%C4%B1t%20i%C3%A7e%20aktar%C4%B1ld%C4%B1.$ADRES/kisiler?m=6%20kay%C4%B1t%20i%C3%A7e%20aktar%C4%B1ld%C4%B1.$ADRES/firsatlar?m=3%20kay%C4%B1t%20i%C3%A7e%20aktar%C4%B1ld%C4%B1." ]
sonuc "1.4" "sonra kişiler (3 + düzeltilmiş 6) ve fırsatlar (3) aktarıldı" $?

# --- 2.1 / 2.2 satış hattı
al /firsatlar; [ "$(grep -o 'class="fkart"' "$GECICI/sayfa.html" | wc -l | tr -d ' ')" = 28 ]; sonuc "2.1" "panoda 28 kart (24 örnek + 1 yeni + 3 içe aktarılan)" $?
yolla /firsat/13/asama -d "asama=nitelikli" >/dev/null
curl -s "$ADRES/disa-aktar/asama_gecmisi.csv" | grep -q '^13,Nitelikli,'; sonuc "2.2" "▶ ile aşama değişti, geçmişe tarihli satır yazıldı" $?
yolla /firsat/15/asama -d "asama=kaybedildi" >/dev/null
curl -s "$ADRES/api/rapor" -o "$GECICI/j.json"; [ "$(json 'd["kaybedilen_sayi"]')" = 7 ]
sonuc "2.2" "kayıp nedeni seçilmeden Kaybedildi yapılamıyor (sayı 7'de kaldı: 6 + içe aktarılan 1)" $?
yolla /firsat/15/asama -d "asama=kaybedildi&kayip_nedeni=Rakip seçildi" >/dev/null
curl -s "$ADRES/api/rapor" -o "$GECICI/j.json"; [ "$(json 'd["kaybedilen_sayi"]')" = 8 ]; sonuc "2.2" "nedenle Kaybedildi → kaybedilen 8" $?

# --- 2.3 görev
yolla /gorev/yeni -d "baslik=Numune gönder&firsat_id=20&son_tarih=2026-09-29&sahip_id=3" >/dev/null
curl -s "$ADRES/api/rapor" -o "$GECICI/j.json"; [ "$(json '20 not in d["gorevsiz_firsatlar"]')" = True ]
sonuc "2.3" "görev eklenince fırsat 'sonraki adımsız' listesinden çıkıyor" $?
yolla /gorev/7/tamamla >/dev/null; curl -s "$ADRES/disa-aktar/gorev.csv" | grep -q '^7,.*,tamam,'; sonuc "2.3" "görev tamamlandı" $?

# --- 2.4 şablon ve izin
al "/sablon/2?kisi=2"; [ "$(icerir "$GECICI/sayfa.html" 'Gönderime uygun değil')" = 0 ]; sonuc "2.4" "tanıtım şablonu, izni 'hayır' kişi: gönderime uygun değil" $?
al "/sablon/2?kisi=1"; [ "$(icerir "$GECICI/sayfa.html" 'Gönderime uygun değil')$(icerir "$GECICI/sayfa.html" 'Merhaba Elif')" = "10" ]
sonuc "2.4" "tanıtım şablonu, izni 'evet' kişi: dolduruldu, uyarı yok" $?
al "/sablon/1?kisi=13&firsat=14"; [ "$(icerir "$GECICI/sayfa.html" 'Doldurulamayan yer tutucu: sirket')" = 0 ]
sonuc "2.4" "bireysel kişide {{sirket}} boş kalınca uyarı" $?
yolla /sablon/yeni -d "ad=Teslim bilgisi&tur=bilgilendirme&konu={{firsat}} teslim tarihi&govde=Merhaba {{ad}}, {{firsat}} ({{tutar}}) işiniz hazır. {{sahip}}" >/dev/null
al "/sablon/3?kisi=1&firsat=21"; [ "$(icerir "$GECICI/sayfa.html" 'Merhaba Elif, Kış menüsü (12.500 TL) işiniz hazır')$(icerir "$GECICI/sayfa.html" 'Doldurulamayan')" = "01" ]
sonuc "2.4" "yeni bilgilendirme şablonu kaydedildi, önizlemede yer tutucular doldu" $?

# --- 3.1–3.3 rapor: bağımsız yeniden hesap + negatif test
uv run --quiet python dogrula/rapor_dogrula.py --adres "$ADRES" >"$GECICI/d.txt"; sonuc "3.2" "rapor sayıları CSV'den bağımsız hesapla aynı (değişikliklerden sonra)" $?
uv run --quiet python dogrula/rapor_dogrula.py --adres "$ADRES" --bozuk >"$GECICI/d.txt"; [ $? = 1 ]
sonuc "3.2" "NEGATİF: CSV'de bir satır bozulunca doğrulayıcı KALDI diyor" $?
kod=$(curl -s -o /dev/null -w '%{http_code}' "$ADRES/rapor?sahip=1&baslangic=2026-08-01&bitis=2026-09-30"); [ "$kod" = 200 ]
sonuc "3.1" "rapor filtreleri (sahip + tarih aralığı) çalışıyor" $?

# --- 4.1 otomasyon: kural + webhook (imza doğru ve yanlış)
uv run --quiet python ornekler/webhook_alici.py --port "$ALICI_PORT" --db "$DB" >"$GECICI/alici.log" 2>&1 &
ALICI=$!; sleep 1.5
yolla /otomasyon/webhook -d "webhook_url=http://localhost:$ALICI_PORT/mini-crm" >/dev/null
yolla /firsat/24/asama -d "asama=kazanildi" >/dev/null; sleep 0.5
grep -q 'opportunity.updated.*imza DOĞRU.*pazarlik → kazanildi' "$GECICI/alici.log"; sonuc "4.1" "webhook: olay alıcıya ulaştı, imza doğrulandı" $?
grep -q 'task.created.*imza DOĞRU.*Teslimat ve fatura' "$GECICI/alici.log"; sonuc "4.1" "kural: Kazanıldı → 'Teslimat ve fatura' görevi açıldı ve olayı gitti" $?
kill "$ALICI"; wait "$ALICI" 2>/dev/null
uv run --quiet python ornekler/webhook_alici.py --port "$ALICI_PORT" --sir yanlis-sir >"$GECICI/alici2.log" 2>&1 &
ALICI=$!; sleep 1.5
yolla /firsat/23/asama -d "asama=kazanildi" >/dev/null; sleep 0.5
curl -s "$ADRES/api/olaylar" | grep -q 'hata (HTTP 401)'; sonuc "4.1" "NEGATİF: yanlış sırla alıcı 401 döndü, Mini CRM teslimi hata diye kaydetti" $?
kill "$ALICI"; wait "$ALICI" 2>/dev/null; ALICI=""
yolla /otomasyon/webhook -d "webhook_url=" >/dev/null
yolla /otomasyon/kural/2 >/dev/null; yolla /firsat/18/asama -d "asama=teklif" >/dev/null
curl -s "$ADRES/disa-aktar/gorev.csv" | grep -q ',Teklifi takip et,18,.*,acik,.*kural: Teklif aşamasına takip görevi'
sonuc "4.1" "öğrencinin açtığı kural 2: Teklif'e geçen fırsata 'Teklifi takip et' görevi" $?

# --- 4.2 KVKK
curl -s "$ADRES/api/denetim" -o "$GECICI/j.json"; once=$(json '[len(k["kayitlar"]) for k in d if k["kural"] == "Tanıtım izni bilinmeyen kişi"][0]')
kod=$(yolla /kisi/4 -d "ad=Burak&soyad=Taslak&eposta=burak@nane-dis.example.com&telefon=0000 000 00 04&sirket_id=4&unvan=Klinik müdürü&izin_tanitim=evet&izin_tarihi=2026-09-25&izin_kaynagi=Web sitesi formu")
curl -s "$ADRES/api/denetim" -o "$GECICI/j.json"; [ "$kod" = 303 ] && [ "$(json '[len(k["kayitlar"]) for k in d if k["kural"] == "Tanıtım izni bilinmeyen kişi"][0]')" = $((once - 1)) ]
sonuc "4.2" "Burak Taslak'a izin girildi: 'izni bilinmeyen' bir azaldı ($once → $((once - 1)))" $?
yolla /kvkk/talep -d "kisi_id=13&tur=silme&alinma=2026-09-25" >/dev/null
al /kvkk; [ "$(icerir "$GECICI/sayfa.html" '25.10.2026')" = 0 ]; sonuc "4.2" "başvuru kaydı: son tarih 30 gün sonra (25.10.2026)" $?
yolla /kvkk/anonimlestir/13 >/dev/null
curl -s "$ADRES/kvkk/disa/13.json" -o "$GECICI/j.json"
[ "$(json 'd["kisi"]["ad"], d["kisi"]["eposta"], len(d["firsatlar"])')" = "Anonim None 1" ]
sonuc "4.2" "anonimleştirme: ad/e-posta silindi, fırsat (tutar) duruyor" $?

# --- 4.3 ekip
yolla /ekip/aktif -d "kullanici_id=2" >/dev/null; al /; [ "$(icerir "$GECICI/sayfa.html" 'Aktif kullanıcı: <b>Deniz Deneme')" = 0 ]
sonuc "4.3" "aktif kullanıcı değişti (Benim hattım görünümü için)" $?
kod=$(yolla /firsat/17 -d "ad=Restoran menüsü&sirket_id=7&kisi_id=12&tutar=14500&sahip_id=3&kaynak=Fuar&beklenen_kapanis=2026-10-25")
curl -s "$ADRES/disa-aktar/firsat.csv" | grep -q '^17,Restoran menüsü,.*,Kaan Kurgu,'; [ $? = 0 ] && [ "$kod" = 303 ]
sonuc "4.3" "fırsatın sahibi Deniz → Kaan yapıldı" $?

# --- 4.4 denetim
curl -s "$ADRES/api/denetim" -o "$GECICI/j.json"; [ "$(json 'len(d)')" = 9 ]; sonuc "4.4" "veri denetimi 9 kuralı çalıştırıyor" $?

BOS_PORT=8067
uv run --quiet python -m mini_crm.sunucu --port "$BOS_PORT" --db calisma/kontrol-bos.db --sifirla --bos --bugun "$GUN" --sessiz >/dev/null 2>&1 &
BOS=$!; bekle "http://localhost:$BOS_PORT/"
hata=0; for yol in / /firsatlar /rapor /denetim /kvkk /gorevler; do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$BOS_PORT$yol")" = 200 ] || hata=1; done
curl -s "http://localhost:$BOS_PORT/api/rapor" -o "$GECICI/j.json"; [ "$(json 'd["firsat_sayisi"], d["kazanma_orani"]')" = "0 None" ] || hata=1
kill "$BOS"; wait "$BOS" 2>/dev/null; rm -f calisma/kontrol-bos.db
sonuc "4.4" "boş CRM (--sifirla --bos): kayıtsız açılıyor, sayfalar 200, oran boş" $hata

echo "----"
echo "Toplam: $((GECEN + KALAN)) · Geçti: $GECEN · Kaldı: $KALAN"
if [ "$KALAN" = 0 ]; then echo "SONUÇ: GEÇTİ"; else echo "SONUÇ: KALDI"; fi
[ "$KALAN" = 0 ]
