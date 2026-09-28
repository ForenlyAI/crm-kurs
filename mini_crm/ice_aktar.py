"""CSV içe aktarma: dosyayı okur, sütunları eşler, her satırı doğrular, hatasızsa kaydeder.

Hata türleri Twenty'nin içe aktarma belgesindeki dört türle aynı adlandırılır:
  Yinelenen değer · Geçersiz biçim · Zorunlu alan boş · İlişki bulunamadı
Kural: dosyada tek bir hata varsa hiçbir satır kaydedilmez (önce düzelt, sonra aktar).
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import date, datetime

from . import db

EPOSTA = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
ALAN_ADI = re.compile(r"^(?!-)[a-z0-9-]+(\.[a-z0-9-]+)+$")

# nesne → sütun → (zorunlu mu, açıklama). Sıra: ekranda gösterilen sıra.
SUTUNLAR = {
    "sirket": {
        "ad": (True, "şirket adı"),
        "alan_adi": (False, "web alan adı, ör. lale-kafe.example.com (benzersiz)"),
        "sektor": (False, "serbest metin"),
        "calisan": (False, "1-10, 11-50, 51-200 …"),
        "sehir": (False, "serbest metin"),
    },
    "kisi": {
        "ad": (True, "kişinin adı"),
        "soyad": (True, "kişinin soyadı"),
        "eposta": (False, "ad@alan.com biçiminde (benzersiz)"),
        "telefon": (False, "10–11 rakam; boşluk serbest"),
        "sirket_alan_adi": (False, "bağlı şirketin alan adı — şirket önce içe aktarılmış olmalı"),
        "unvan": (False, "serbest metin"),
        "izin_tanitim": (False, "evet / hayir / boş (bilinmiyor)"),
        "izin_tarihi": (False, "YYYY-AA-GG ya da GG.AA.YYYY — izin 'evet' ise zorunlu"),
        "izin_kaynagi": (False, "iznin nereden alındığı — izin 'evet' ise zorunlu"),
    },
    "firsat": {
        "ad": (True, "fırsatın adı"),
        "sirket_alan_adi": (False, "şirketin alan adı — önce şirketler"),
        "kisi_eposta": (False, "ana kişinin e-postası — önce kişiler"),
        "tutar": (True, "TL, tam sayı: 12500 ya da 12.500"),
        "asama": (True, "Yeni, Nitelikli, Görüşme, Teklif, Pazarlık, Kazanıldı, Kaybedildi"),
        "sahip": (True, "ekip üyesinin adı, ör. Deniz Deneme"),
        "kaynak": (False, "Tavsiye, Web sitesi, Instagram, Fuar, Soğuk arama"),
        "beklenen_kapanis": (False, "YYYY-AA-GG ya da GG.AA.YYYY"),
        "kayip_nedeni": (False, "aşama Kaybedildi ise zorunlu"),
    },
}

TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
TAKMA = {
    "adi": "ad", "isim": "ad", "firstname": "ad", "name": "ad", "sirketadi": "ad",
    "soyadi": "soyad", "lastname": "soyad",
    "email": "eposta", "e-posta": "eposta", "mail": "eposta", "epostaadresi": "eposta",
    "tel": "telefon", "phone": "telefon", "telefonnumarasi": "telefon",
    "domain": "alan_adi", "alanadi": "alan_adi", "web": "alan_adi", "website": "alan_adi",
    "sirket": "sirket_alan_adi", "sirketalanadi": "sirket_alan_adi", "company": "sirket_alan_adi",
    "kisi": "kisi_eposta", "kisieposta": "kisi_eposta",
    "izin": "izin_tanitim", "izintanitim": "izin_tanitim", "tanitimizni": "izin_tanitim",
    "izintarihi": "izin_tarihi", "izinkaynagi": "izin_kaynagi",
    "beklenenkapanis": "beklenen_kapanis", "kapanistarihi": "beklenen_kapanis",
    "kayipnedeni": "kayip_nedeni", "stage": "asama", "amount": "tutar", "owner": "sahip",
    "calisansayisi": "calisan", "unvani": "unvan", "gorev": "unvan",
}


def sutun_normalle(ad: str) -> str:
    sade = ad.strip().lower().replace("i̇", "i").translate(TR)
    sade = re.sub(r"[\s_\-\.]", "", sade)
    for kanonik in {k for s in SUTUNLAR.values() for k in s}:
        if sade == kanonik.replace("_", ""):
            return kanonik
    return TAKMA.get(sade, ad.strip())


def metni_coz(ham: bytes) -> tuple[str, str]:
    """UTF-8 (BOM'lu ya da BOM'suz) dener; olmazsa Türkçe Windows kodlaması (cp1254)."""
    try:
        return ham.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        return ham.decode("cp1254", errors="replace"), "Windows-1254 (UTF-8 değil — kaydederken UTF-8 seçin)"


def ayrac_bul(metin: str) -> str:
    ilk = metin.splitlines()[0] if metin.strip() else ""
    return ";" if ilk.count(";") > ilk.count(",") else ","


def tarih_coz(deger: str) -> str | None:
    for bicim in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(deger, bicim).date().isoformat()
        except ValueError:
            pass
    return None


def tutar_coz(deger: str) -> int | None:
    d = deger.replace(" ", "").replace("TL", "").replace("₺", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", d):
        d = d.replace(".", "")
    return int(d) if d.isdigit() else None


def dogrula(c: sqlite3.Connection, nesne: str, ham: bytes) -> dict:
    metin, kodlama = metni_coz(ham)
    ayrac = ayrac_bul(metin)
    okuyucu = csv.reader(io.StringIO(metin), delimiter=ayrac)
    satirlar = [s for s in okuyucu if any(h.strip() for h in s)]
    sonuc = {"nesne": nesne, "kodlama": kodlama, "ayrac": "noktalı virgül (;)" if ayrac == ";" else "virgül (,)",
             "satir_sayisi": max(0, len(satirlar) - 1), "eslenen": [], "yok_sayilan": [], "eksik_zorunlu": [],
             "hatalar": [], "gecerli": [], "satirlar": []}
    if not satirlar:
        sonuc["hatalar"].append({"satir": 1, "sutun": "-", "deger": "", "tur": "Zorunlu alan boş", "aciklama": "dosya boş"})
        return sonuc
    beklenen = SUTUNLAR[nesne]
    baslik = [sutun_normalle(h) for h in satirlar[0]]
    for ham_ad, ad in zip(satirlar[0], baslik):
        (sonuc["eslenen"] if ad in beklenen else sonuc["yok_sayilan"]).append(
            {"dosyadaki": ham_ad.strip(), "alan": ad} if ad in beklenen else ham_ad.strip())
    sonuc["eksik_zorunlu"] = [k for k, (z, _) in beklenen.items() if z and k not in baslik]
    for k in sonuc["eksik_zorunlu"]:
        sonuc["hatalar"].append({"satir": 1, "sutun": k, "deger": "", "tur": "Zorunlu alan boş",
                                 "aciklama": f"'{k}' sütunu dosyada yok"})

    def hata(satir: int, sutun: str, deger: str, tur: str, aciklama: str) -> None:
        sonuc["hatalar"].append({"satir": satir, "sutun": sutun, "deger": deger, "tur": tur, "aciklama": aciklama})

    mevcut_eposta = {r[0].lower() for r in c.execute("SELECT eposta FROM kisi WHERE eposta IS NOT NULL")}
    mevcut_alan = {r[0].lower(): r[1] for r in c.execute("SELECT alan_adi, id FROM sirket WHERE alan_adi IS NOT NULL")}
    kisi_eposta = {r[0].lower(): r[1] for r in c.execute("SELECT eposta, id FROM kisi WHERE eposta IS NOT NULL")}
    asama_ad = {r["ad"].lower(): r["kod"] for r in c.execute("SELECT * FROM asama")}
    kullanici = {r["ad"].lower(): r["id"] for r in c.execute("SELECT * FROM kullanici")}
    kaynaklar = {r["ad"].lower(): r["ad"] for r in c.execute("SELECT * FROM kaynak")}
    nedenler = {r["ad"].lower(): r["ad"] for r in c.execute("SELECT * FROM kayip_nedeni")}
    dosyada: dict[str, int] = {}

    for i, s in enumerate(satirlar[1:], start=2):
        kayit = {k: "" for k in beklenen}
        for ad, deger in zip(baslik, s):
            if ad in beklenen:
                kayit[ad] = deger.strip()
        onceki = len(sonuc["hatalar"])
        for k, (zorunlu, _) in beklenen.items():
            if zorunlu and k in baslik and not kayit[k]:
                hata(i, k, "", "Zorunlu alan boş", f"'{k}' boş olamaz")

        if nesne == "sirket":
            a = kayit["alan_adi"].lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
            kayit["alan_adi"] = a
            if a:
                if not ALAN_ADI.match(a):
                    hata(i, "alan_adi", a, "Geçersiz biçim", "alan adı biçimi bozuk")
                elif a in mevcut_alan:
                    hata(i, "alan_adi", a, "Yinelenen değer", "bu alan adıyla bir şirket CRM'de zaten var")
                elif a in dosyada:
                    hata(i, "alan_adi", a, "Yinelenen değer", f"aynı alan adı dosyada {dosyada[a]}. satırda da var")
                else:
                    dosyada[a] = i

        elif nesne == "kisi":
            e = kayit["eposta"].lower()
            kayit["eposta"] = e
            if e:
                if not EPOSTA.match(e):
                    hata(i, "eposta", e, "Geçersiz biçim", "e-posta biçimi bozuk (ad@alan.com olmalı)")
                elif e in mevcut_eposta:
                    hata(i, "eposta", e, "Yinelenen değer", "bu e-postayla bir kişi CRM'de zaten var")
                elif e in dosyada:
                    hata(i, "eposta", e, "Yinelenen değer", f"aynı e-posta dosyada {dosyada[e]}. satırda da var")
                else:
                    dosyada[e] = i
            t = kayit["telefon"]
            if t and (not re.fullmatch(r"\+?[\d\s()]+", t) or not 10 <= len(re.sub(r"\D", "", t)) <= 12):
                hata(i, "telefon", t, "Geçersiz biçim", "telefon 10–11 rakam olmalı")
            sa = kayit["sirket_alan_adi"].lower()
            if sa:
                if sa in mevcut_alan:
                    kayit["sirket_id"] = mevcut_alan[sa]
                else:
                    hata(i, "sirket_alan_adi", sa, "İlişki bulunamadı", "bu alan adıyla şirket yok — önce şirketi aktarın")
            iz = kayit["izin_tanitim"].lower().replace("ı", "i")
            if iz not in ("", "evet", "hayir"):
                hata(i, "izin_tanitim", kayit["izin_tanitim"], "Geçersiz biçim", "yalnız evet, hayir ya da boş")
            kayit["izin_tanitim"] = iz
            if kayit["izin_tarihi"]:
                td = tarih_coz(kayit["izin_tarihi"])
                if not td:
                    hata(i, "izin_tarihi", kayit["izin_tarihi"], "Geçersiz biçim", "tarih YYYY-AA-GG ya da GG.AA.YYYY olmalı")
                kayit["izin_tarihi"] = td or ""
            if iz == "evet":
                if not kayit["izin_tarihi"] and "izin_tarihi" not in [h["sutun"] for h in sonuc["hatalar"][onceki:]]:
                    hata(i, "izin_tarihi", "", "Zorunlu alan boş", "izin 'evet' ise izin tarihi gerekir")
                if not kayit["izin_kaynagi"]:
                    hata(i, "izin_kaynagi", "", "Zorunlu alan boş", "izin 'evet' ise iznin kaynağı gerekir")

        elif nesne == "firsat":
            sa = kayit["sirket_alan_adi"].lower()
            if sa:
                if sa in mevcut_alan:
                    kayit["sirket_id"] = mevcut_alan[sa]
                else:
                    hata(i, "sirket_alan_adi", sa, "İlişki bulunamadı", "bu alan adıyla şirket yok")
            ke = kayit["kisi_eposta"].lower()
            if ke:
                if ke in kisi_eposta:
                    kayit["kisi_id"] = kisi_eposta[ke]
                else:
                    hata(i, "kisi_eposta", ke, "İlişki bulunamadı", "bu e-postayla kişi yok")
            if kayit["tutar"]:
                tt = tutar_coz(kayit["tutar"])
                if tt is None:
                    hata(i, "tutar", kayit["tutar"], "Geçersiz biçim", "tutar tam sayı olmalı (12500 ya da 12.500)")
                kayit["tutar_sayi"] = tt
            if kayit["asama"]:
                kod = asama_ad.get(kayit["asama"].lower())
                if not kod:
                    hata(i, "asama", kayit["asama"], "Geçersiz biçim", "aşama listede yok")
                kayit["asama_kod"] = kod
                if kod == "kaybedildi":
                    if not kayit["kayip_nedeni"]:
                        hata(i, "kayip_nedeni", "", "Zorunlu alan boş", "Kaybedildi ise kayıp nedeni gerekir")
                    elif kayit["kayip_nedeni"].lower() not in nedenler:
                        hata(i, "kayip_nedeni", kayit["kayip_nedeni"], "Geçersiz biçim", "kayıp nedeni listede yok")
            if kayit["sahip"]:
                kayit["sahip_id"] = kullanici.get(kayit["sahip"].lower())
                if not kayit["sahip_id"]:
                    hata(i, "sahip", kayit["sahip"], "İlişki bulunamadı", "bu adla ekip üyesi yok")
            if kayit["kaynak"] and kayit["kaynak"].lower() not in kaynaklar:
                hata(i, "kaynak", kayit["kaynak"], "Geçersiz biçim", "kaynak listede yok")
            if kayit["beklenen_kapanis"]:
                td = tarih_coz(kayit["beklenen_kapanis"])
                if not td:
                    hata(i, "beklenen_kapanis", kayit["beklenen_kapanis"], "Geçersiz biçim", "tarih YYYY-AA-GG ya da GG.AA.YYYY olmalı")
                kayit["beklenen_kapanis"] = td or ""

        satir_hatalari = sonuc["hatalar"][onceki:]
        sonuc["satirlar"].append({"satir": i, "kayit": kayit, "hatali_sutunlar": sorted({h["sutun"] for h in satir_hatalari})})
        if not satir_hatalari:
            sonuc["gecerli"].append(kayit)
    sonuc["tur_sayilari"] = {}
    for h in sonuc["hatalar"]:
        sonuc["tur_sayilari"][h["tur"]] = sonuc["tur_sayilari"].get(h["tur"], 0) + 1
    return sonuc


def kaydet(c: sqlite3.Connection, sonuc: dict, bugun: date) -> int:
    """Doğrulama sonucunu kaydeder. Hata varsa hiçbir şey yazmaz ve 0 döner."""
    if sonuc["hatalar"]:
        return 0
    b = bugun.isoformat()
    n = 0
    for k in sonuc["gecerli"]:
        if sonuc["nesne"] == "sirket":
            cur = c.execute("INSERT INTO sirket (ad, alan_adi, sektor, calisan, sehir, olusturma) VALUES (?,?,?,?,?,?)",
                            (k["ad"], k["alan_adi"] or None, k["sektor"], k["calisan"], k["sehir"], b))
            db.olay_yaz(c, "sirket", "created", cur.lastrowid)
        elif sonuc["nesne"] == "kisi":
            cur = c.execute("INSERT INTO kisi (ad, soyad, sirket_id, unvan, eposta, telefon, izin_tanitim, izin_tarihi,"
                            " izin_kaynagi, olusturma) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (k["ad"], k["soyad"], k.get("sirket_id"), k["unvan"], k["eposta"] or None, k["telefon"],
                             k["izin_tanitim"], k["izin_tarihi"], k["izin_kaynagi"], b))
            db.olay_yaz(c, "kisi", "created", cur.lastrowid)
        else:
            cur = c.execute("INSERT INTO firsat (ad, sirket_id, kisi_id, tutar, sahip_id, kaynak, beklenen_kapanis,"
                            " asama, kayip_nedeni, olusturma, guncelleme) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (k["ad"], k.get("sirket_id"), k.get("kisi_id"), k["tutar_sayi"], k["sahip_id"], k["kaynak"],
                             k["beklenen_kapanis"], k["asama_kod"], k["kayip_nedeni"], b, b))
            c.execute("INSERT INTO asama_gecmisi (firsat_id, asama, tarih) VALUES (?,?,?)", (cur.lastrowid, k["asama_kod"], b))
            db.olay_yaz(c, "firsat", "created", cur.lastrowid)
        n += 1
    c.commit()
    return n


def ornek_dosya(nesne: str) -> str:
    """Boş şablon: yalnız başlık satırı (Twenty'deki 'Download sample file' gibi)."""
    return ",".join(SUTUNLAR[nesne]) + "\n"

