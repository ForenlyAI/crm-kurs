"""Mini CRM — CRM 101 kursunun alıştırma uygulaması (yalnız Python standart kitaplığı).

Çalıştırma (lab klasöründen):
    uv run python -m mini_crm.sunucu                 # http://localhost:8060
    uv run python -m mini_crm.sunucu --sifirla       # örnek veriye dön, sonra aç
    uv run python -m mini_crm.sunucu --port 8070 --db calisma/deneme.db --bugun 2026-09-25

Bilgisayarınızdan dışarı çıkmaz: yalnız 127.0.0.1'i dinler. E-posta göndermez.
Webhook adresi girerseniz olayları yalnız o adrese gönderir (varsayılan: boş).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import secrets
import sqlite3
import sys
from datetime import date, timedelta
from email.parser import BytesParser
from email.policy import HTTP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "mini_crm"

from mini_crm import db, ice_aktar, metrik, otomasyon  # noqa: E402
from mini_crm.arayuz import alan, cubuk, e, girdi, sayfa, secim, tarih, tl, yonlendir_adresi, yuzde  # noqa: E402

STATIK = Path(__file__).resolve().parent / "statik"
DURUM_ROZET = {"kazanildi": "yesil", "kaybedildi": "kirmizi"}
KVKK_TALEP_TURLERI = [("bilgi", "Bilgi / erişim talebi"), ("duzeltme", "Düzeltme talebi"), ("silme", "Silme talebi"),
                      ("itiraz", "İtiraz")]


class Uygulama:
    def __init__(self, db_yolu: Path, bugun: date):
        self.db_yolu = db_yolu
        self.bugun = bugun
        if not db_yolu.exists():
            db.kur(db_yolu, bugun)
        self.c = db.baglan(db_yolu)
        self.yuklemeler: dict[str, tuple[str, bytes, str]] = {}   # içe aktarma önizlemesi → onay

    # ---------------------------------------------------------------- ortak
    def kullanicilar(self) -> dict[int, str]:
        return {r["id"]: r["ad"] for r in self.c.execute("SELECT id, ad FROM kullanici ORDER BY id")}

    def aktif(self) -> int:
        return int(db.ayar(self.c, "aktif_kullanici") or 1)

    def sayfa(self, baslik: str, govde: str, yol: str, q: dict) -> str:
        return sayfa(baslik, govde, yol, db.ayar(self.c, "isletme"), self.kullanicilar().get(self.aktif(), "?"),
                     q.get("m", ""), q.get("mt", ""))

    def asama_adlari(self) -> dict[str, str]:
        return {r["kod"]: r["ad"] for r in db.asamalar(self.c)}

    def sirket_secenek(self) -> list[tuple]:
        return [(r["id"], r["ad"]) for r in self.c.execute("SELECT id, ad FROM sirket ORDER BY ad")]

    def kisi_secenek(self) -> list[tuple]:
        return [(r["id"], f'{r["ad"]} {r["soyad"]}') for r in self.c.execute("SELECT id, ad, soyad FROM kisi ORDER BY ad, soyad")]

    def firsat_sorgu(self, where: str = "1=1", p: tuple = ()) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT f.*, s.ad AS sirket_ad, k.ad || ' ' || k.soyad AS kisi_ad, u.ad AS sahip_ad, a.ad AS asama_ad,"
            " a.olasilik, a.sira FROM firsat f LEFT JOIN sirket s ON s.id = f.sirket_id"
            " LEFT JOIN kisi k ON k.id = f.kisi_id LEFT JOIN kullanici u ON u.id = f.sahip_id"
            f" JOIN asama a ON a.kod = f.asama WHERE {where} ORDER BY f.id", p).fetchall()

    # ---------------------------------------------------------------- pano
    def pano(self, q: dict) -> str:
        m = metrik.hesapla(self.c, self.bugun)
        gorevsiz = len(m["gorevsiz_firsatlar"]) + len(m["yalniz_geciken_gorevli_firsatlar"])
        k = [
            ("Açık satış hattı", tl(m["acik_tutar"]), f'{m["acik_sayi"]} açık fırsat', ""),
            ("Ağırlıklı değer", tl(m["agirlikli_tutar"]), "tutar × aşama olasılığı", ""),
            ("Kazanma oranı", yuzde(m["kazanma_orani"]), f'{m["kazanilan_sayi"]} kazanılan / {m["kazanilan_sayi"] + m["kaybedilen_sayi"]} sonuçlanan', ""),
            ("Bu ay kazanılan", tl(m["bu_ay_kazanilan_tutar"]), f'{m["bu_ay_kazanilan_sayi"]} fırsat', ""),
            ("Geciken görev", str(m["geciken_gorev"]), f'bugün son günü olan: {m["bugun_gorev"]}', "uyari" if m["geciken_gorev"] else ""),
            ("Sonraki adımı olmayan fırsat", str(gorevsiz), "açık ama ileri tarihli görevi yok", "uyari" if gorevsiz else ""),
        ]
        kpi = "".join(f'<div class="kart kpi {c}"><div class="etiket">{e(a)}</div><div class="deger">{e(d)}</div>'
                      f'<div class="not">{e(n)}</div></div>' for a, d, n, c in k)
        en_buyuk = max([h["tutar"] for h in m["hat"]] + [1])
        hat = "".join(cubuk(f'{h["ad"]} ({h["sayi"]})', h["tutar"] / en_buyuk, tl(h["tutar"])) for h in m["hat"])
        kayip = "".join(cubuk(n["neden"], n["pay"] or 0, f'{n["sayi"]} · {yuzde(n["pay"])}', "kirmizi")
                        for n in m["kayip_nedenleri"][:4])
        ids = m["bayat_firsatlar"]
        bayat_satir = ""
        for f in self.firsat_sorgu(f"f.id IN ({','.join('?' * len(ids))})", tuple(ids)) if ids else []:
            gun = (self.bugun - date.fromisoformat(f["guncelleme"])).days
            bayat_satir += (f'<tr><td><a href="/firsat/{f["id"]}">{e(f["ad"])}</a><div class="soluk">{e(f["sirket_ad"] or f["kisi_ad"])}</div></td>'
                            f'<td>{e(f["asama_ad"])}</td><td>{e(f["sahip_ad"])}</td><td class="sayi">{gun} gün</td></tr>')
        bayat = (f'<div class="tablo"><table><tr><th>Fırsat</th><th>Aşama</th><th>Sahip</th><th class="sayi">Son hareket</th></tr>{bayat_satir}</table></div>'
                 if bayat_satir else '<p class="soluk">Bayat fırsat yok.</p>')
        govde = f"""<h1>Pano</h1><p class="alt">Bugün {tarih(m["bugun"])} · sayılar Rapor sayfasıyla aynı hesaptan gelir</p>
<div class="izgara i3">{kpi}</div>
<div class="izgara i2" style="margin-top:12px">
<div class="kart"><h2 style="margin-top:0">Açık hat, aşamaya göre</h2>{hat}</div>
<div class="kart"><h2 style="margin-top:0">En sık kayıp nedenleri</h2>{kayip}<p class="soluk" style="margin-bottom:0">{m["kaybedilen_sayi"]} kaybedilen fırsat · ayrıntı: <a href="/rapor">Rapor</a></p></div>
</div>
<h2>Bayat fırsatlar <span class="soluk" style="font-weight:400">(açık, {metrik.BAYAT_GUN}+ gündür hareket yok)</span></h2>{bayat}"""
        return self.sayfa("Pano", govde, "/", q)

    # ---------------------------------------------------------------- satış hattı
    def hat(self, q: dict) -> str:
        sahip = q.get("sahip", "")
        tablo = q.get("gorunum") == "tablo"
        where, p = ("f.sahip_id = ?", (int(sahip),)) if sahip.isdigit() else ("1=1", ())
        firsatlar = self.firsat_sorgu(where, p)
        asamalar = db.asamalar(self.c)
        filtre = (f'<form class="satir" method="get" action="/firsatlar">'
                  f'{alan("Sahip", secim("sahip", list(self.kullanicilar().items()), sahip, "Herkes"), kimlik="sahip")}'
                  f'<input type="hidden" name="gorunum" value="{"tablo" if tablo else ""}">'
                  f'<div class="alan"><button class="ikincil">Filtrele</button></div>'
                  f'<div class="alan"><a class="dugme ikincil" href="/firsatlar?sahip={self.aktif()}{"&gorunum=tablo" if tablo else ""}">Benim hattım</a></div>'
                  f'<div class="alan" style="margin-left:auto"><a class="dugme ikincil" href="/firsatlar?{"" if tablo else "gorunum=tablo&"}sahip={e(sahip)}">'
                  f'{"Pano görünümü" if tablo else "Tablo görünümü"}</a> <a class="dugme" href="/firsat/yeni">+ Yeni fırsat</a></div></form>')
        if tablo:
            satir = "".join(
                f'<tr><td><a href="/firsat/{f["id"]}">{e(f["ad"])}</a></td><td>{e(f["sirket_ad"] or "—")}</td>'
                f'<td><span class="rozet {DURUM_ROZET.get(f["asama"], "mavi")}">{e(f["asama_ad"])}</span></td>'
                f'<td class="sayi">{tl(f["tutar"])}</td><td>{e(f["sahip_ad"])}</td><td>{e(f["kaynak"])}</td>'
                f'<td>{tarih(f["beklenen_kapanis"])}</td><td>{tarih(f["guncelleme"])}</td></tr>' for f in firsatlar)
            icerik = (f'<div class="tablo"><table><tr><th>Fırsat</th><th>Şirket</th><th>Aşama</th><th class="sayi">Tutar</th>'
                      f'<th>Sahip</th><th>Kaynak</th><th>Beklenen kapanış</th><th>Son güncelleme</th></tr>{satir}</table></div>')
        else:
            kolonlar = []
            sirali = [a["kod"] for a in asamalar]
            geri = "/firsatlar" + (f"?sahip={sahip}" if sahip else "")
            for a in asamalar:
                fs = [f for f in firsatlar if f["asama"] == a["kod"]]
                kartlar = []
                for f in fs:
                    i = sirali.index(f["asama"])
                    dugmeler = ""
                    if a["acik"]:
                        onceki = sirali[i - 1] if i > 0 else ""
                        sonraki = sirali[i + 1]
                        if onceki:
                            dugmeler += (f'<form method="post" action="/firsat/{f["id"]}/asama"><input type="hidden" name="asama" value="{onceki}">'
                                         f'<input type="hidden" name="geri" value="{e(geri)}"><button class="kucuk ikincil" title="Önceki aşama" aria-label="Önceki aşamaya al">◀</button></form> ')
                        dugmeler += (f'<form method="post" action="/firsat/{f["id"]}/asama"><input type="hidden" name="asama" value="{sonraki}">'
                                     f'<input type="hidden" name="geri" value="{e(geri)}"><button class="kucuk ikincil" title="Sonraki aşama" aria-label="Sonraki aşamaya al">▶</button></form>')
                    alt_bilgi = e(f["kayip_nedeni"]) if f["asama"] == "kaybedildi" else e((f["sahip_ad"] or "").split(" ")[0])
                    kartlar.append(
                        f'<div class="fkart" draggable="true" data-id="{f["id"]}"><div class="ad"><a href="/firsat/{f["id"]}">{e(f["ad"])}</a></div>'
                        f'<div class="sirket">{e(f["sirket_ad"] or f["kisi_ad"] or "")}</div>'
                        f'<div class="alt-satir"><b>{tl(f["tutar"])}</b><span class="soluk">{alt_bilgi}</span></div>'
                        f'<div class="alt-satir"><span>{dugmeler}</span></div></div>')
                toplam = sum(f["tutar"] or 0 for f in fs)
                kolonlar.append(f'<section class="kolon {a["kod"]}" data-asama="{a["kod"]}" aria-label="{e(a["ad"])}">'
                                f'<h3><span>{e(a["ad"])}</span><span class="rozet">{len(fs)}</span></h3>'
                                f'<div class="toplam">{tl(toplam)}{" · %" + str(a["olasilik"]) if a["acik"] else ""}</div>{"".join(kartlar)}</section>')
            icerik = f'<div class="hat">{"".join(kolonlar)}</div><script src="/statik/hat.js"></script>'
        govde = (f'<h1>Satış hattı</h1><p class="alt">Kartı sürükleyip bırakın ya da ◀ ▶ ile aşama değiştirin. '
                 f'Kazanıldı / Kaybedildi için fırsatı açın.</p>{filtre}{icerik}')
        return self.sayfa("Satış hattı", govde, "/firsatlar", q)

    def firsat_formu(self, f: dict, hatalar: dict) -> str:
        asama_sec = [(a["kod"], a["ad"]) for a in db.asamalar(self.c)]
        kaynaklar = [(r["ad"], r["ad"]) for r in self.c.execute("SELECT ad FROM kaynak ORDER BY sira")]
        return (f'{alan("Fırsat adı *", girdi("ad", f.get("ad", ""), ek=" required"), hatalar.get("ad", ""), "ad")}'
                f'<div class="izgara i2">{alan("Şirket", secim("sirket_id", self.sirket_secenek(), f.get("sirket_id"), "— yok (bireysel) —"), kimlik="sirket_id")}'
                f'{alan("Ana kişi", secim("kisi_id", self.kisi_secenek(), f.get("kisi_id"), "— seçin —"), hatalar.get("kisi_id", ""), "kisi_id")}'
                f'{alan("Tutar (TL) *", girdi("tutar", f.get("tutar", ""), "number", " min=0 step=1"), hatalar.get("tutar", ""), "tutar")}'
                f'{alan("Sahip *", secim("sahip_id", list(self.kullanicilar().items()), f.get("sahip_id") or self.aktif()), kimlik="sahip_id")}'
                f'{alan("Kaynak", secim("kaynak", kaynaklar, f.get("kaynak"), "— seçin —"), kimlik="kaynak")}'
                f'{alan("Beklenen kapanış", girdi("beklenen_kapanis", f.get("beklenen_kapanis", ""), "date"), hatalar.get("beklenen_kapanis", ""), "beklenen_kapanis")}'
                + (f'{alan("Aşama", secim("asama", asama_sec[:5], f.get("asama", "yeni")), kimlik="asama")}' if not f.get("id") else "")
                + '</div>')

    def firsat(self, q: dict, fid: int) -> str:
        r = self.firsat_sorgu("f.id = ?", (fid,))
        if not r:
            return self.bulunamadi(q)
        f = r[0]
        adlar = self.asama_adlari()
        gecmis = self.c.execute("SELECT * FROM asama_gecmisi WHERE firsat_id = ? ORDER BY tarih, id", (fid,)).fetchall()
        zaman = "".join(f'<div><b>{tarih(g["tarih"])}</b> · {e(adlar.get(g["asama"], g["asama"]))}</div>' for g in gecmis)
        gorevler = self.c.execute("SELECT g.*, u.ad AS sahip_ad FROM gorev g LEFT JOIN kullanici u ON u.id = g.sahip_id"
                                  " WHERE firsat_id = ? ORDER BY durum, son_tarih", (fid,)).fetchall()
        notlar = self.c.execute("SELECT n.*, u.ad AS yazan FROM notlar n LEFT JOIN kullanici u ON u.id = n.yazan_id"
                                " WHERE firsat_id = ? ORDER BY tarih DESC, id DESC", (fid,)).fetchall()
        nedenler = [(r["ad"], r["ad"]) for r in self.c.execute("SELECT ad FROM kayip_nedeni ORDER BY sira")]
        asama_dugme = ""
        for a in db.asamalar(self.c):
            if a["kod"] in ("kaybedildi",) or a["kod"] == f["asama"]:
                continue
            asama_dugme += (f'<form method="post" action="/firsat/{fid}/asama" style="display:inline"><input type="hidden" name="asama" value="{a["kod"]}">'
                            f'<button class="{"" if a["kod"] == "kazanildi" else "ikincil "}kucuk">{e(a["ad"])}</button></form> ')
        kaybet_acik = q.get("kaybet") == "1"
        kaybet = (f'<form method="post" action="/firsat/{fid}/asama" class="satir" style="margin-top:10px"><input type="hidden" name="asama" value="kaybedildi">'
                  f'{alan("Kayıp nedeni *", secim("kayip_nedeni", nedenler, f["kayip_nedeni"], "— seçin —"), kimlik="kayip_nedeni")}'
                  f'<div class="alan"><button class="tehlike">Kaybedildi olarak işaretle</button></div></form>') if f["asama"] != "kaybedildi" else ""
        gorev_satir = "".join(
            f'<tr><td>{"✔ " if g["durum"] == "tamam" else ""}{e(g["baslik"])}'
            f'{"<div class=soluk>" + e(g["kaynak"]) + "</div>" if (g["kaynak"] or "").startswith("kural") else ""}</td>'
            f'<td>{e(g["sahip_ad"])}</td><td>{self.gorev_tarih_rozet(g)}</td>'
            f'<td class="sag">{self.tamamla_dugme(g, f"/firsat/{fid}")}</td></tr>' for g in gorevler)
        not_liste = "".join(f'<div class="kart" style="margin-bottom:8px"><div class="soluk">{tarih(n["tarih"])} · {e(n["yazan"])}</div>{e(n["metin"])}</div>' for n in notlar)
        govde = f"""<p><a href="/firsatlar">← Satış hattı</a></p>
<h1>{e(f["ad"])} <span class="rozet {DURUM_ROZET.get(f["asama"], "mavi")}">{e(f["asama_ad"])}</span></h1>
<p class="alt">{e(f["sirket_ad"] or "Bireysel")} · {tl(f["tutar"])} · sahibi {e(f["sahip_ad"])} · kaynak {e(f["kaynak"] or "—")}
{(" · kayıp nedeni: <b>" + e(f["kayip_nedeni"]) + "</b>") if f["kayip_nedeni"] else ""}</p>
<div class="izgara i2">
<div class="kart"><h2 style="margin-top:0">Aşama</h2><div>{asama_dugme}</div>{kaybet if (kaybet_acik or f["asama"] != "kaybedildi") else ""}
<h2>Aşama geçmişi</h2><div class="zaman">{zaman}</div></div>
<div class="kart"><h2 style="margin-top:0">Bilgiler</h2><form method="post" action="/firsat/{fid}">{self.firsat_formu(dict(f), {})}
<button>Kaydet</button></form>
<p class="soluk" style="margin-bottom:0">Ana kişi: {("<a href='/kisi/" + str(f["kisi_id"]) + "'>" + e(f["kisi_ad"]) + "</a>") if f["kisi_id"] else "—"} ·
Oluşturma {tarih(f["olusturma"])} · son güncelleme {tarih(f["guncelleme"])} ·
<a href="/sablon/1?kisi={f["kisi_id"] or ""}&firsat={fid}">E-posta taslağı</a></p></div>
</div>
<div class="izgara i2" style="margin-top:12px">
<div class="kart"><h2 style="margin-top:0">Görevler</h2><div class="tablo"><table><tr><th>Görev</th><th>Sahip</th><th>Son tarih</th><th></th></tr>{gorev_satir or '<tr><td colspan=4 class="soluk">Görev yok — sonraki adımı yazın.</td></tr>'}</table></div>
{self.gorev_formu(firsat_id=fid, geri=f"/firsat/{fid}")}</div>
<div class="kart"><h2 style="margin-top:0">Notlar</h2>{not_liste or '<p class="soluk">Not yok.</p>'}
<form method="post" action="/not/yeni"><input type="hidden" name="firsat_id" value="{fid}"><textarea name="metin" aria-label="Yeni not" style="min-height:70px" required></textarea>
<div class="bosluk"></div><button class="ikincil">Not ekle</button></form></div></div>"""
        return self.sayfa(f["ad"], govde, f"/firsat/{fid}", q)

    def gorev_tarih_rozet(self, g) -> str:
        if g["durum"] == "tamam":
            return f'<span class="rozet yesil">tamam · {tarih(g["son_tarih"])}</span>'
        b = self.bugun.isoformat()
        if g["son_tarih"] < b:
            gun = (self.bugun - date.fromisoformat(g["son_tarih"])).days
            return f'<span class="rozet kirmizi">{tarih(g["son_tarih"])} · {gun} gün gecikti</span>'
        if g["son_tarih"] == b:
            return f'<span class="rozet sari">bugün</span>'
        return f'<span class="rozet">{tarih(g["son_tarih"])}</span>'

    def tamamla_dugme(self, g, geri: str) -> str:
        if g["durum"] == "tamam":
            return ""
        return (f'<form method="post" action="/gorev/{g["id"]}/tamamla" style="display:inline"><input type="hidden" name="geri" value="{e(geri)}">'
                f'<button class="kucuk ikincil">Tamamla</button></form>')

    def gorev_formu(self, firsat_id: int | None = None, kisi_id: int | None = None, geri: str = "/gorevler") -> str:
        yarin = (self.bugun + timedelta(days=1)).isoformat()
        return (f'<form method="post" action="/gorev/yeni" class="satir" style="margin-top:10px">'
                f'<input type="hidden" name="firsat_id" value="{firsat_id or ""}"><input type="hidden" name="kisi_id" value="{kisi_id or ""}">'
                f'<input type="hidden" name="geri" value="{e(geri)}">'
                f'<div class="alan" style="flex:1"><label for="baslik">Yeni görev (sonraki adım)</label>{girdi("baslik", "", ek=" required")}</div>'
                f'{alan("Son tarih", girdi("son_tarih", yarin, "date"), kimlik="son_tarih")}'
                f'{alan("Sahip", secim("sahip_id", list(self.kullanicilar().items()), self.aktif()), kimlik="sahip_id")}'
                f'<div class="alan"><button>Ekle</button></div></form>')

    def firsat_yeni(self, q: dict, f: dict | None = None, hatalar: dict | None = None) -> str:
        govde = (f'<p><a href="/firsatlar">← Satış hattı</a></p><h1>Yeni fırsat</h1>'
                 f'<div class="kart" style="max-width:760px"><form method="post" action="/firsat/yeni">{self.firsat_formu(f or {}, hatalar or {})}'
                 f'<button>Kaydet</button></form></div>')
        return self.sayfa("Yeni fırsat", govde, "/firsat/yeni", q)

    def firsat_dogrula(self, form: dict) -> tuple[dict, dict]:
        f = {k: form.get(k, "").strip() for k in ("ad", "sirket_id", "kisi_id", "tutar", "sahip_id", "kaynak", "beklenen_kapanis", "asama")}
        h = {}
        if not f["ad"]:
            h["ad"] = "Fırsatın adı boş olamaz."
        if not f["tutar"].isdigit():
            h["tutar"] = "Tutar tam sayı olmalı (TL)."
        if not f["sirket_id"] and not f["kisi_id"]:
            h["kisi_id"] = "Şirket ya da ana kişiden en az biri seçilmeli."
        return f, h

    # ---------------------------------------------------------------- kişiler / şirketler
    def kisiler(self, q: dict) -> str:
        ara = q.get("ara", "").strip()
        sql = ("SELECT k.*, s.ad AS sirket_ad FROM kisi k LEFT JOIN sirket s ON s.id = k.sirket_id")
        p: tuple = ()
        if ara:
            sql += " WHERE (k.ad || ' ' || k.soyad || ' ' || IFNULL(k.eposta,'') || ' ' || IFNULL(s.ad,'')) LIKE ?"
            p = (f"%{ara}%",)
        rows = self.c.execute(sql + " ORDER BY k.ad, k.soyad", p).fetchall()
        satir = "".join(
            f'<tr><td><a href="/kisi/{r["id"]}">{e(r["ad"])} {e(r["soyad"])}</a></td><td>{e(r["sirket_ad"] or "—")}</td>'
            f'<td>{e(r["unvan"])}</td><td>{e(r["eposta"] or "—")}</td><td>{e(r["telefon"])}</td><td>{self.izin_rozet(r)}</td></tr>' for r in rows)
        govde = (f'<h1>Kişiler</h1><p class="alt">{len(rows)} kişi · Twenty\'de karşılığı: People</p>'
                 f'<form class="satir" method="get"><div class="alan"><label for="ara">Ara</label>{girdi("ara", ara)}</div>'
                 f'<div class="alan"><button class="ikincil">Ara</button></div><div class="alan" style="margin-left:auto"><a class="dugme" href="/kisi/yeni">+ Yeni kişi</a></div></form>'
                 f'<div class="tablo"><table><tr><th>Ad soyad</th><th>Şirket</th><th>Unvan</th><th>E-posta</th><th>Telefon</th><th>Tanıtım izni</th></tr>{satir}</table></div>')
        return self.sayfa("Kişiler", govde, "/kisiler", q)

    def izin_rozet(self, r) -> str:
        if r["anonim"]:
            return '<span class="rozet">anonim</span>'
        if r["izin_tanitim"] == "evet":
            return f'<span class="rozet yesil">evet · {tarih(r["izin_tarihi"])}</span>'
        if r["izin_tanitim"] == "hayir":
            return '<span class="rozet kirmizi">hayır</span>'
        return '<span class="rozet sari">bilinmiyor</span>'

    def kisi_formu(self, k: dict, h: dict) -> str:
        izin = [("", "bilinmiyor"), ("evet", "evet"), ("hayir", "hayır")]
        return (f'<div class="izgara i2">{alan("Ad *", girdi("ad", k.get("ad", ""), ek=" required"), h.get("ad", ""), "ad")}'
                f'{alan("Soyad *", girdi("soyad", k.get("soyad", ""), ek=" required"), h.get("soyad", ""), "soyad")}'
                f'{alan("E-posta (benzersiz)", girdi("eposta", k.get("eposta", "") or "", "email"), h.get("eposta", ""), "eposta")}'
                f'{alan("Telefon", girdi("telefon", k.get("telefon", "")), h.get("telefon", ""), "telefon")}'
                f'{alan("Şirket", secim("sirket_id", self.sirket_secenek(), k.get("sirket_id"), "— yok (bireysel) —"), kimlik="sirket_id")}'
                f'{alan("Unvan", girdi("unvan", k.get("unvan", "")), kimlik="unvan")}</div>'
                f'<h2>İzin ve aydınlatma</h2><div class="izgara i2">'
                f'{alan("Tanıtım e-postası izni", secim("izin_tanitim", izin, k.get("izin_tanitim", "")), kimlik="izin_tanitim")}'
                f'{alan("İzin tarihi", girdi("izin_tarihi", k.get("izin_tarihi", ""), "date"), h.get("izin_tarihi", ""), "izin_tarihi")}'
                f'{alan("İznin kaynağı (nereden, nasıl)", girdi("izin_kaynagi", k.get("izin_kaynagi", "")), h.get("izin_kaynagi", ""), "izin_kaynagi")}'
                f'{alan("Aydınlatma yapıldığı tarih", girdi("aydinlatma_tarihi", k.get("aydinlatma_tarihi", ""), "date"), kimlik="aydinlatma_tarihi")}</div>')

    def kisi_dogrula(self, form: dict, kid: int | None) -> tuple[dict, dict]:
        alanlar = ("ad", "soyad", "eposta", "telefon", "sirket_id", "unvan", "izin_tanitim", "izin_tarihi", "izin_kaynagi", "aydinlatma_tarihi")
        k = {a: form.get(a, "").strip() for a in alanlar}
        k["eposta"] = k["eposta"].lower()
        h = {}
        for a in ("ad", "soyad"):
            if not k[a]:
                h[a] = "Boş olamaz."
        if k["eposta"]:
            if not ice_aktar.EPOSTA.match(k["eposta"]):
                h["eposta"] = "E-posta biçimi bozuk (ad@alan.com olmalı)."
            else:
                r = self.c.execute("SELECT id, ad, soyad FROM kisi WHERE eposta = ? AND id != ?", (k["eposta"], kid or 0)).fetchone()
                if r:
                    h["eposta"] = f'Bu e-posta zaten {r["ad"]} {r["soyad"]} kaydında var (kişi #{r["id"]}). Yinelenen kayıt açılmaz.'
        if k["telefon"] and not 10 <= len(re.sub(r"\D", "", k["telefon"])) <= 12:
            h["telefon"] = "Telefon 10–11 rakam olmalı."
        if k["izin_tanitim"] == "evet":
            if not k["izin_tarihi"]:
                h["izin_tarihi"] = "İzin 'evet' ise tarihi yazın (ispat için)."
            if not k["izin_kaynagi"]:
                h["izin_kaynagi"] = "İzin 'evet' ise nereden alındığını yazın."
        return k, h

    def kisi(self, q: dict, kid: int | None, k: dict | None = None, h: dict | None = None) -> str:
        if kid:
            r = self.c.execute("SELECT * FROM kisi WHERE id = ?", (kid,)).fetchone()
            if not r:
                return self.bulunamadi(q)
            kayit = k or dict(r)
            firsatlar = self.firsat_sorgu("f.kisi_id = ?", (kid,))
            fs = "".join(f'<li><a href="/firsat/{f["id"]}">{e(f["ad"])}</a> · {e(f["asama_ad"])} · {tl(f["tutar"])}</li>' for f in firsatlar)
            gorevler = self.c.execute("SELECT * FROM gorev WHERE kisi_id = ? ORDER BY durum, son_tarih", (kid,)).fetchall()
            gs = "".join(f'<li>{e(g["baslik"])} {self.gorev_tarih_rozet(g)}</li>' for g in gorevler)
            notlar = self.c.execute("SELECT * FROM notlar WHERE kisi_id = ? ORDER BY tarih DESC", (kid,)).fetchall()
            ns = "".join(f'<li>{tarih(n["tarih"])} · {e(n["metin"])}</li>' for n in notlar)
            yan = (f'<div class="kart"><h2 style="margin-top:0">Fırsatlar</h2><ul>{fs or "<li class=soluk>yok</li>"}</ul>'
                   f'<h2>Görevler</h2><ul>{gs or "<li class=soluk>yok</li>"}</ul>{self.gorev_formu(kisi_id=kid, geri=f"/kisi/{kid}")}'
                   f'<h2>Notlar</h2><ul>{ns or "<li class=soluk>yok</li>"}</ul></div>')
            baslik = f'{r["ad"]} {r["soyad"]}'
            eylem = f"/kisi/{kid}"
        else:
            kayit, yan, baslik, eylem = k or {}, "", "Yeni kişi", "/kisi/yeni"
        govde = (f'<p><a href="/kisiler">← Kişiler</a></p><h1>{e(baslik)}</h1>'
                 f'<div class="izgara i2"><div class="kart"><form method="post" action="{eylem}">{self.kisi_formu(kayit, h or {})}'
                 f'<button>Kaydet</button></form></div>{yan}</div>')
        return self.sayfa(baslik, govde, eylem, q)

    def sirketler(self, q: dict) -> str:
        rows = self.c.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM kisi k WHERE k.sirket_id = s.id) AS kisi_sayi,"
            " (SELECT COUNT(*) FROM firsat f WHERE f.sirket_id = s.id) AS firsat_sayi,"
            " (SELECT IFNULL(SUM(tutar),0) FROM firsat f WHERE f.sirket_id = s.id AND f.asama = 'kazanildi') AS kazanilan"
            " FROM sirket s ORDER BY s.ad").fetchall()
        satir = "".join(
            f'<tr><td><a href="/sirket/{r["id"]}">{e(r["ad"])}</a></td><td>{e(r["alan_adi"] or "—")}</td><td>{e(r["sektor"])}</td>'
            f'<td>{e(r["sehir"])}</td><td class="sayi">{r["kisi_sayi"]}</td><td class="sayi">{r["firsat_sayi"]}</td>'
            f'<td class="sayi">{tl(r["kazanilan"])}</td></tr>' for r in rows)
        govde = (f'<h1>Şirketler</h1><p class="alt">{len(rows)} şirket · Twenty\'de karşılığı: Companies</p>'
                 f'<p><a class="dugme" href="/sirket/yeni">+ Yeni şirket</a></p>'
                 f'<div class="tablo"><table><tr><th>Şirket</th><th>Alan adı</th><th>Sektör</th><th>Şehir</th>'
                 f'<th class="sayi">Kişi</th><th class="sayi">Fırsat</th><th class="sayi">Kazanılan</th></tr>{satir}</table></div>')
        return self.sayfa("Şirketler", govde, "/sirketler", q)

    def sirket(self, q: dict, sid: int | None, s: dict | None = None, h: dict | None = None) -> str:
        h = h or {}
        if sid:
            r = self.c.execute("SELECT * FROM sirket WHERE id = ?", (sid,)).fetchone()
            if not r:
                return self.bulunamadi(q)
            kayit = s or dict(r)
            kisiler = self.c.execute("SELECT * FROM kisi WHERE sirket_id = ? ORDER BY ad", (sid,)).fetchall()
            ks = "".join(f'<li><a href="/kisi/{k["id"]}">{e(k["ad"])} {e(k["soyad"])}</a> · {e(k["unvan"])}</li>' for k in kisiler)
            fs = "".join(f'<li><a href="/firsat/{f["id"]}">{e(f["ad"])}</a> · {e(f["asama_ad"])} · {tl(f["tutar"])}</li>'
                         for f in self.firsat_sorgu("f.sirket_id = ?", (sid,)))
            yan = f'<div class="kart"><h2 style="margin-top:0">Kişiler</h2><ul>{ks or "<li class=soluk>yok</li>"}</ul><h2>Fırsatlar</h2><ul>{fs or "<li class=soluk>yok</li>"}</ul></div>'
            baslik, eylem = r["ad"], f"/sirket/{sid}"
        else:
            kayit, yan, baslik, eylem = s or {}, "", "Yeni şirket", "/sirket/yeni"
        form = (f'{alan("Şirket adı *", girdi("ad", kayit.get("ad", ""), ek=" required"), h.get("ad", ""), "ad")}'
                f'{alan("Alan adı (benzersiz)", girdi("alan_adi", kayit.get("alan_adi") or ""), h.get("alan_adi", ""), "alan_adi")}'
                f'<div class="izgara i2">{alan("Sektör", girdi("sektor", kayit.get("sektor", "")), kimlik="sektor")}'
                f'{alan("Çalışan sayısı", girdi("calisan", kayit.get("calisan", "")), kimlik="calisan")}'
                f'{alan("Şehir", girdi("sehir", kayit.get("sehir", "")), kimlik="sehir")}</div>')
        govde = (f'<p><a href="/sirketler">← Şirketler</a></p><h1>{e(baslik)}</h1><div class="izgara i2">'
                 f'<div class="kart"><form method="post" action="{eylem}">{form}<button>Kaydet</button></form></div>{yan}</div>')
        return self.sayfa(baslik, govde, eylem, q)

    def sirket_dogrula(self, form: dict, sid: int | None) -> tuple[dict, dict]:
        s = {a: form.get(a, "").strip() for a in ("ad", "alan_adi", "sektor", "calisan", "sehir")}
        s["alan_adi"] = s["alan_adi"].lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
        h = {}
        if not s["ad"]:
            h["ad"] = "Boş olamaz."
        if s["alan_adi"]:
            if not ice_aktar.ALAN_ADI.match(s["alan_adi"]):
                h["alan_adi"] = "Alan adı biçimi bozuk (ör. lale-kafe.example.com)."
            else:
                r = self.c.execute("SELECT id, ad FROM sirket WHERE alan_adi = ? AND id != ?", (s["alan_adi"], sid or 0)).fetchone()
                if r:
                    h["alan_adi"] = f'Bu alan adı zaten {r["ad"]} kaydında var.'
        return s, h

    # ---------------------------------------------------------------- görevler
    def gorevler(self, q: dict) -> str:
        sahip = q.get("sahip", "")
        b = self.bugun.isoformat()
        where, p = "", ()
        if sahip.isdigit():
            where, p = " AND g.sahip_id = ?", (int(sahip),)
        tum = self.c.execute(
            "SELECT g.*, u.ad AS sahip_ad, f.ad AS firsat_ad, k.ad || ' ' || k.soyad AS kisi_ad FROM gorev g"
            " LEFT JOIN kullanici u ON u.id = g.sahip_id LEFT JOIN firsat f ON f.id = g.firsat_id"
            f" LEFT JOIN kisi k ON k.id = g.kisi_id WHERE 1=1{where} ORDER BY g.son_tarih, g.id", p).fetchall()
        gruplar = [("Geciken", [g for g in tum if g["durum"] == "acik" and g["son_tarih"] < b]),
                   ("Bugün", [g for g in tum if g["durum"] == "acik" and g["son_tarih"] == b]),
                   ("Yaklaşan", [g for g in tum if g["durum"] == "acik" and g["son_tarih"] > b]),
                   ("Tamamlanan", [g for g in tum if g["durum"] == "tamam"])]
        bolum = ""
        for ad, gs in gruplar:
            satir = "".join(
                f'<tr><td>{e(g["baslik"])}</td><td>{("<a href=/firsat/" + str(g["firsat_id"]) + ">" + e(g["firsat_ad"]) + "</a>") if g["firsat_id"] else ("<a href=/kisi/" + str(g["kisi_id"]) + ">" + e(g["kisi_ad"]) + "</a>")}</td>'
                f'<td>{e(g["sahip_ad"])}</td><td>{self.gorev_tarih_rozet(g)}</td><td class="sag">{self.tamamla_dugme(g, "/gorevler" + ("?sahip=" + sahip if sahip else ""))}</td></tr>'
                for g in gs)
            bolum += (f'<h2>{ad} <span class="rozet">{len(gs)}</span></h2>'
                      + (f'<div class="tablo"><table><tr><th>Görev</th><th>İlgili kayıt</th><th>Sahip</th><th>Son tarih</th><th></th></tr>{satir}</table></div>' if gs else '<p class="soluk">Yok.</p>'))
        m = metrik.hesapla(self.c, self.bugun)
        ids = m["gorevsiz_firsatlar"] + m["yalniz_geciken_gorevli_firsatlar"]
        adimsiz = "".join(
            f'<li><a href="/firsat/{f["id"]}">{e(f["ad"])}</a> · {e(f["asama_ad"])} · {e(f["sahip_ad"])} · '
            f'{"hiç görevi yok" if f["id"] in m["gorevsiz_firsatlar"] else "yalnız gecikmiş görevi var"}</li>'
            for f in (self.firsat_sorgu(f"f.id IN ({','.join('?' * len(ids))})", tuple(ids)) if ids else []))
        filtre = (f'<form class="satir" method="get">{alan("Sahip", secim("sahip", list(self.kullanicilar().items()), sahip, "Herkes"), kimlik="sahip")}'
                  f'<div class="alan"><button class="ikincil">Filtrele</button></div>'
                  f'<div class="alan"><a class="dugme ikincil" href="/gorevler?sahip={self.aktif()}">Benim görevlerim</a></div></form>')
        govde = (f'<h1>Görevler</h1><p class="alt">Bugün {tarih(b)} · Twenty\'de karşılığı: Tasks</p>{filtre}'
                 f'<div class="kart" style="margin-bottom:6px"><b>Sonraki adımı olmayan açık fırsatlar ({len(ids)})</b>'
                 f'<ul style="margin:6px 0 0">{adimsiz or "<li>yok</li>"}</ul></div>{bolum}')
        return self.sayfa("Görevler", govde, "/gorevler", q)

    # ---------------------------------------------------------------- şablonlar
    def sablonlar(self, q: dict) -> str:
        rows = self.c.execute("SELECT * FROM sablon ORDER BY id").fetchall()
        satir = "".join(f'<tr><td><a href="/sablon/{r["id"]}">{e(r["ad"])}</a></td><td>{self.tur_rozet(r["tur"])}</td><td>{e(r["konu"])}</td></tr>' for r in rows)
        govde = (f'<h1>E-posta şablonları</h1><p class="alt">Mini CRM e-posta GÖNDERMEZ; şablonu kişiye göre doldurup önizler. '
                 f'Yer tutucular: <code>{{{{ad}}}}</code> <code>{{{{soyad}}}}</code> <code>{{{{sirket}}}}</code> <code>{{{{firsat}}}}</code> <code>{{{{tutar}}}}</code> <code>{{{{sahip}}}}</code></p>'
                 f'<p><a class="dugme" href="/sablon/yeni">+ Yeni şablon</a></p>'
                 f'<div class="tablo"><table><tr><th>Şablon</th><th>Tür</th><th>Konu</th></tr>{satir}</table></div>')
        return self.sayfa("E-posta şablonları", govde, "/sablonlar", q)

    @staticmethod
    def tur_rozet(tur: str) -> str:
        return '<span class="rozet sari">tanıtım (ticari ileti)</span>' if tur == "tanitim" else '<span class="rozet mavi">bilgilendirme (işle ilgili)</span>'

    def sablon(self, q: dict, sid: int | None) -> str:
        s = dict(self.c.execute("SELECT * FROM sablon WHERE id = ?", (sid,)).fetchone() or {}) if sid else {"tur": "bilgilendirme", "konu": "", "govde": "", "ad": ""}
        if sid and not s:
            return self.bulunamadi(q)
        kisi_id = q.get("kisi", "")
        firsat_id = q.get("firsat", "")
        onizleme = ""
        if kisi_id.isdigit() and sid:
            onizleme = self.sablon_onizle(s, int(kisi_id), int(firsat_id) if firsat_id.isdigit() else None)
        eylem = f"/sablon/{sid}" if sid else "/sablon/yeni"
        form = (f'<form method="post" action="{eylem}">{alan("Şablon adı", girdi("ad", s.get("ad", ""), ek=" required"), kimlik="ad")}'
                f'{alan("Tür", secim("tur", [("bilgilendirme", "bilgilendirme (işle ilgili)"), ("tanitim", "tanıtım (ticari ileti — izin gerekir)")], s.get("tur")), kimlik="tur")}'
                f'{alan("Konu", girdi("konu", s.get("konu", "")), kimlik="konu")}'
                f'<div class="alan"><label for="govde">Gövde</label><textarea name="govde" id="govde">{e(s.get("govde", ""))}</textarea></div>'
                f'<button>Kaydet</button></form>')
        sec = (f'<form method="get" action="{eylem}" class="satir">{alan("Önizleme için kişi", secim("kisi", self.kisi_secenek(), kisi_id, "— seçin —"), kimlik="kisi")}'
               f'<input type="hidden" name="firsat" value="{e(firsat_id)}"><div class="alan"><button class="ikincil">Önizle</button></div></form>') if sid else ""
        govde = (f'<p><a href="/sablonlar">← Şablonlar</a></p><h1>{e(s.get("ad") or "Yeni şablon")} {self.tur_rozet(s.get("tur", ""))}</h1>'
                 f'<div class="izgara i2"><div class="kart">{form}</div><div class="kart"><h2 style="margin-top:0">Önizleme</h2>{sec}{onizleme}</div></div>')
        return self.sayfa("Şablon", govde, eylem, q)

    def sablon_onizle(self, s: dict, kisi_id: int, firsat_id: int | None) -> str:
        k = self.c.execute("SELECT k.*, s.ad AS sirket_ad FROM kisi k LEFT JOIN sirket s ON s.id = k.sirket_id WHERE k.id = ?", (kisi_id,)).fetchone()
        if not k:
            return '<p class="mesaj hata">Kişi bulunamadı.</p>'
        if firsat_id:
            fl = self.firsat_sorgu("f.id = ?", (firsat_id,))
        else:
            fl = self.firsat_sorgu("f.kisi_id = ? AND a.acik = 1", (kisi_id,)) or self.firsat_sorgu("f.kisi_id = ?", (kisi_id,))
        f = fl[-1] if fl else None
        degerler = {"ad": k["ad"], "soyad": k["soyad"], "sirket": k["sirket_ad"] or "", "firsat": f["ad"] if f else "",
                    "tutar": tl(f["tutar"]) if f else "", "sahip": f["sahip_ad"] if f else self.kullanicilar()[self.aktif()]}
        eksik = set()

        def doldur(metin: str) -> str:
            def yer(m):
                ad = m.group(1)
                if ad not in degerler or not degerler[ad]:
                    eksik.add(ad)
                    return f"[{ad} YOK]"
                return degerler[ad]
            return re.sub(r"\{\{\s*(\w+)\s*\}\}", yer, metin)

        konu, govde = doldur(s["konu"]), doldur(s["govde"])
        uyarilar = []
        if eksik:
            uyarilar.append(("hata", f"Doldurulamayan yer tutucu: {', '.join(sorted(eksik))}. Göndermeden önce metni düzeltin."))
        if k["anonim"]:
            uyarilar.append(("hata", "Bu kişi anonimleştirildi; ileti gönderilemez."))
        elif s["tur"] == "tanitim" and k["izin_tanitim"] != "evet":
            durum = "alıcı tanıtım iletilerini reddetmiş" if k["izin_tanitim"] == "hayir" else "alıcının izin kaydı yok"
            uyarilar.append(("hata", f"Gönderime uygun değil: bu bir tanıtım (ticari) iletisi ve {durum}."))
        elif s["tur"] == "tanitim":
            uyarilar.append(("", f"İzin kaydı var: {tarih(k['izin_tarihi'])} · {k['izin_kaynagi']}. İletide ret yolu bulunmalı."))
        if not k["eposta"] and not k["anonim"]:
            uyarilar.append(("hata", "Kişinin e-posta adresi yok."))
        u = "".join(f'<div class="mesaj {t}">{e(m)}</div>' for t, m in uyarilar)
        return (f'{u}<div class="soluk">Kime: {e(k["eposta"] or "—")}</div><div class="soluk">Konu: <b>{e(konu)}</b></div>'
                f'<div class="bosluk"></div><div class="eposta">{e(govde)}</div>'
                f'<p class="soluk">Mini CRM e-posta göndermez. Metni kopyalayıp kendi e-posta programınızda kullanın.</p>')

    # ---------------------------------------------------------------- rapor
    def rapor_parametre(self, q: dict) -> tuple[int | None, str, str]:
        s = q.get("sahip", "")
        return (int(s) if s.isdigit() else None), q.get("baslangic", ""), q.get("bitis", "")

    def rapor(self, q: dict) -> str:
        sahip, bas, bit = self.rapor_parametre(q)
        m = metrik.hesapla(self.c, self.bugun, sahip, bas, bit)
        filtre = (f'<form class="satir" method="get">{alan("Sahip", secim("sahip", list(self.kullanicilar().items()), sahip, "Herkes"), kimlik="sahip")}'
                  f'{alan("Oluşturma: başlangıç", girdi("baslangic", bas, "date"), kimlik="baslangic")}'
                  f'{alan("Oluşturma: bitiş", girdi("bitis", bit, "date"), kimlik="bitis")}'
                  f'<div class="alan"><button class="ikincil">Uygula</button></div>'
                  f'<div class="alan" style="margin-left:auto"><a class="dugme ikincil" href="/disa-aktar/firsat.csv">Fırsatları CSV indir</a> '
                  f'<a class="dugme ikincil" href="/api/rapor?{"&".join(f"{k}={v}" for k, v in (("sahip", sahip or ""), ("baslangic", bas), ("bitis", bit)) if v)}">JSON</a></div></form>')
        ozet = [("Fırsat (filtrede)", str(m["firsat_sayisi"])), ("Kazanılan / kaybedilen", f'{m["kazanilan_sayi"]} / {m["kaybedilen_sayi"]}'),
                ("Kazanma oranı", yuzde(m["kazanma_orani"])), ("Kazanılan tutar", tl(m["kazanilan_tutar"])),
                ("Ortalama kazanılan", tl(m["ortalama_kazanilan_tutar"])),
                ("Ortalama satış süresi", f'{str(m["ortalama_satis_suresi_gun"]).replace(".", ",")} gün' if m["ortalama_satis_suresi_gun"] is not None else "—"),
                ("Açık hat", tl(m["acik_tutar"])), ("Ağırlıklı değer", tl(m["agirlikli_tutar"]))]
        ozet_h = "".join(f'<div class="kart kpi"><div class="etiket">{e(a)}</div><div class="deger" style="font-size:21px">{e(d)}</div></div>' for a, d in ozet)
        ilk = m["huni"][0]["ulasan"] or 1
        huni = "".join(
            f'<tr><td>{e(h["ad"])}</td><td class="sayi">{h["ulasan"]}</td><td style="width:40%"><div class="iz-tek"><div class="dolu" style="width:{100 * h["ulasan"] / ilk:.1f}%"></div></div></td>'
            f'<td class="sayi">{yuzde(h["gecis_orani"]) if h["gecis_orani"] is not None else "—"}</td></tr>' for h in m["huni"])
        nedenler = "".join(cubuk(n["neden"], n["pay"] or 0, f'{n["sayi"]} · {yuzde(n["pay"])}', "kirmizi") for n in m["kayip_nedenleri"])

        def kirilim_tablo(liste, baslik):
            s = "".join(f'<tr><td>{e(x["ad"])}</td><td class="sayi">{x["firsat"]}</td><td class="sayi">{x["kazanilan"]}</td>'
                        f'<td class="sayi">{x["kaybedilen"]}</td><td class="sayi">{yuzde(x["kazanma_orani"])}</td>'
                        f'<td class="sayi">{tl(x["kazanilan_tutar"])}</td><td class="sayi">{tl(x["acik_tutar"])}</td></tr>' for x in liste)
            return (f'<div class="tablo"><table><tr><th>{baslik}</th><th class="sayi">Fırsat</th><th class="sayi">Kazanılan</th><th class="sayi">Kaybedilen</th>'
                    f'<th class="sayi">Kazanma oranı</th><th class="sayi">Kazanılan tutar</th><th class="sayi">Açık tutar</th></tr>{s}</table></div>')

        govde = f"""<h1>Rapor</h1><p class="alt">Bugün {tarih(m["bugun"])} · filtreler fırsatın oluşturulma tarihine göre çalışır</p>{filtre}
<div class="izgara i4">{ozet_h}</div>
<div class="izgara i2" style="margin-top:12px">
<div><h2 id="huni">Aşama dönüşümü (huni)</h2><div class="tablo"><table><tr><th>Aşama</th><th class="sayi">Ulaşan</th><th></th><th class="sayi">Sonrakine geçiş</th></tr>{huni}</table></div>
<p class="soluk">Ulaşan: o aşamaya ya da ötesine varmış fırsat. Atlanan aşama geçilmiş sayılır. Açık fırsatlar henüz yolda olduğu için geçiş oranı zamanla değişir.</p></div>
<div><h2 id="kayip">Kayıp nedenleri</h2><div class="kart">{nedenler or '<p class="soluk">Kaybedilen fırsat yok.</p>'}</div></div>
</div>
<h2 id="kaynak">Kaynağa göre</h2>{kirilim_tablo(m["kaynaklar"], "Kaynak")}
<h2 id="sahip">Sahibe göre</h2>{kirilim_tablo(m["sahipler"], "Sahip")}
<h2>Hesap nasıl yapıldı</h2><div class="kart"><ul style="margin:0">
<li><b>Kazanma oranı</b> = kazanılan ÷ (kazanılan + kaybedilen). Açık fırsatlar paydaya girmez.</li>
<li><b>Sonrakine geçiş</b> = bir sonraki aşamaya ulaşan ÷ bu aşamaya ulaşan.</li>
<li><b>Ağırlıklı değer</b> = her açık fırsatın tutarı × aşama olasılığı (Yeni %10, Nitelikli %25, Görüşme %40, Teklif %60, Pazarlık %80), toplamı.</li>
<li><b>Satış süresi</b> = fırsatın açıldığı gün ile Kazanıldı'ya geçtiği gün arası; kazanılanların ortalaması.</li>
<li>Her sayıyı <a href="/disa-aktar/firsat.csv">CSV</a> ile bir hesap tablosunda yeniden hesaplayabilirsiniz; lab'daki <code>dogrula/rapor_dogrula.py</code> bunu otomatik yapar.</li></ul></div>"""
        return self.sayfa("Rapor", govde, "/rapor", q)

    # ---------------------------------------------------------------- denetim
    def denetim_listesi(self) -> list[dict]:
        b = self.bugun.isoformat()
        m = metrik.hesapla(self.c, self.bugun)
        bul = []

        def ekle(kural: str, olcut: str, ciddiyet: str, kayitlar: list[tuple[str, str]]):
            bul.append({"kural": kural, "olcut": olcut, "ciddiyet": ciddiyet, "kayitlar": kayitlar})

        ekle("Şirketi olmayan kişi", "Ç1", "bilgi", [(f"/kisi/{r['id']}", f"{r['ad']} {r['soyad']}") for r in self.c.execute(
            "SELECT * FROM kisi WHERE sirket_id IS NULL AND anonim = 0")])
        ekle("E-postası olmayan kişi", "Ç1", "uyari", [(f"/kisi/{r['id']}", f"{r['ad']} {r['soyad']}") for r in self.c.execute(
            "SELECT * FROM kisi WHERE (eposta IS NULL OR eposta = '') AND anonim = 0")])
        ekle("Fırsatta eksik alan (tutar, sahip, beklenen kapanış, şirket/kişi)", "Ç1", "hata", [(f"/firsat/{r['id']}", r["ad"]) for r in self.c.execute(
            "SELECT * FROM firsat WHERE tutar IS NULL OR sahip_id IS NULL OR IFNULL(beklenen_kapanis,'') = ''"
            " OR (sirket_id IS NULL AND kisi_id IS NULL)")])
        ekle("Kaybedildi ama kayıp nedeni boş", "Ç3", "hata", [(f"/firsat/{r['id']}", r["ad"]) for r in self.c.execute(
            "SELECT * FROM firsat WHERE asama = 'kaybedildi' AND IFNULL(kayip_nedeni,'') = ''")])
        ids = m["gorevsiz_firsatlar"] + m["yalniz_geciken_gorevli_firsatlar"]
        ekle("Açık fırsat, ileri tarihli görevi (sonraki adımı) yok", "Ç3", "hata",
             [(f"/firsat/{f['id']}", f["ad"]) for f in (self.firsat_sorgu(f"f.id IN ({','.join('?' * len(ids))})", tuple(ids)) if ids else [])])
        ekle("Beklenen kapanış tarihi geçmiş açık fırsat", "Ç4", "uyari", [(f"/firsat/{r['id']}", f"{r['ad']} ({tarih(r['beklenen_kapanis'])})") for r in self.c.execute(
            "SELECT f.* FROM firsat f JOIN asama a ON a.kod = f.asama WHERE a.acik = 1 AND beklenen_kapanis != '' AND beklenen_kapanis < ?", (b,))])
        ekle(f"Bayat fırsat ({metrik.BAYAT_GUN}+ gün hareketsiz)", "Ç4", "uyari",
             [(f"/firsat/{f['id']}", f["ad"]) for f in (self.firsat_sorgu(f"f.id IN ({','.join('?' * len(m['bayat_firsatlar']))})", tuple(m["bayat_firsatlar"])) if m["bayat_firsatlar"] else [])])
        ekle("Tanıtım izni 'evet' ama tarih ya da kaynak yok", "Ç8", "hata", [(f"/kisi/{r['id']}", f"{r['ad']} {r['soyad']}") for r in self.c.execute(
            "SELECT * FROM kisi WHERE izin_tanitim = 'evet' AND (IFNULL(izin_tarihi,'') = '' OR IFNULL(izin_kaynagi,'') = '')")])
        ekle("Tanıtım izni bilinmeyen kişi", "Ç7", "uyari", [(f"/kisi/{r['id']}", f"{r['ad']} {r['soyad']}") for r in self.c.execute(
            "SELECT * FROM kisi WHERE IFNULL(izin_tanitim,'') = '' AND anonim = 0")])
        return bul

    def denetim(self, q: dict) -> str:
        bul = self.denetim_listesi()
        rozet = {"hata": "kirmizi", "uyari": "sari", "bilgi": ""}
        ad = {"hata": "düzeltilmeli", "uyari": "gözden geçir", "bilgi": "bilgi"}
        satir = ""
        for b in bul:
            n = len(b["kayitlar"])
            liste = ", ".join(f'<a href="{u}">{e(t)}</a>' for u, t in b["kayitlar"]) or '<span class="soluk">—</span>'
            satir += (f'<tr><td>{e(b["kural"])}</td><td><span class="rozet {rozet[b["ciddiyet"]] if n else "yesil"}">{ad[b["ciddiyet"]] if n else "temiz"}</span></td>'
                      f'<td class="sayi">{n}</td><td>{liste}</td><td>{e(b["olcut"])}</td></tr>')
        hata = sum(len(b["kayitlar"]) for b in bul if b["ciddiyet"] == "hata")
        govde = (f'<h1>Veri denetimi</h1><p class="alt">CRM\'deki verinin eksiklerini listeler. Bitirme ödevinden önce “düzeltilmeli” satırları sıfırlayın '
                 f'(son sütun: ilgili bitirme ölçütü).</p><div class="mesaj {"hata" if hata else ""}">Düzeltilmesi gereken kayıt: {hata}</div>'
                 f'<div class="tablo"><table><tr><th>Kural</th><th>Durum</th><th class="sayi">Kayıt</th><th>Kayıtlar</th><th>Ölçüt</th></tr>{satir}</table></div>')
        return self.sayfa("Veri denetimi", govde, "/denetim", q)

    # ---------------------------------------------------------------- içe / dışa aktarma
    def ice_aktar_sayfa(self, q: dict, sonuc: dict | None = None, token: str = "") -> str:
        nesne = (sonuc or {}).get("nesne") or q.get("nesne", "kisi")
        adlar = {"sirket": "Şirketler", "kisi": "Kişiler", "firsat": "Fırsatlar"}
        tablo_sutun = "".join(f'<tr><td><code>{k}</code>{" *" if z else ""}</td><td>{e(a)}</td></tr>' for k, (z, a) in ice_aktar.SUTUNLAR[nesne].items())
        form = (f'<form method="post" action="/ice-aktar" enctype="multipart/form-data" class="satir">'
                f'{alan("Ne aktarılıyor?", secim("nesne", list(adlar.items()), nesne), kimlik="nesne")}'
                f'<div class="alan"><label for="dosya">CSV dosyası</label><input type="file" name="dosya" id="dosya" accept=".csv,text/csv" required></div>'
                f'<div class="alan"><button>Yükle ve denetle</button></div></form>')
        yardim = (f'<div class="kart"><h2 style="margin-top:0">Beklenen sütunlar · {adlar[nesne]}</h2><div class="tablo"><table><tr><th>Sütun</th><th>Açıklama</th></tr>{tablo_sutun}</table></div>'
                  f'<p class="soluk">* zorunlu. Sıra: önce şirketler, sonra kişiler, sonra fırsatlar. <a href="/ice-aktar/sablon/{nesne}.csv">Boş şablonu indir</a></p></div>')
        sonuc_h = ""
        if sonuc:
            hatalar = sonuc["hatalar"]
            tur_ozet = " · ".join(f"{t}: {n}" for t, n in sonuc.get("tur_sayilari", {}).items())
            bas = (f'<div class="mesaj {"hata" if hatalar else ""}">{sonuc["satir_sayisi"]} satır okundu · kodlama {e(sonuc["kodlama"])} · ayraç {e(sonuc["ayrac"])} · '
                   f'{"<b>" + str(len(hatalar)) + " hata</b> (" + e(tur_ozet) + ") — hiçbir satır kaydedilmedi" if hatalar else "hata yok, kaydetmeye hazır"}</div>')
            esl = ", ".join(f'{e(x["dosyadaki"])} → <code>{e(x["alan"])}</code>' for x in sonuc["eslenen"])
            yok = ", ".join(e(x) for x in sonuc["yok_sayilan"])
            bas += f'<p><b>Eşlenen sütunlar:</b> {esl or "—"}' + (f'<br><b>Yok sayılan:</b> {yok}' if yok else "") + "</p>"
            sutunlar = list(ice_aktar.SUTUNLAR[sonuc["nesne"]])
            satirlar = ""
            for s in sonuc["satirlar"]:
                hucre = "".join(f'<td class="{"hucre-hata" if k in s["hatali_sutunlar"] else ""}">{e(s["kayit"].get(k, ""))}</td>' for k in sutunlar)
                satirlar += f'<tr class="{"hatali" if s["hatali_sutunlar"] else ""}"><td class="sayi">{s["satir"]}</td>{hucre}</tr>'
            onizleme = (f'<h2>Önizleme</h2><div class="tablo" style="overflow-x:auto"><table><tr><th class="sayi">Satır</th>'
                        f'{"".join(f"<th>{k}</th>" for k in sutunlar)}</tr>{satirlar}</table></div>')
            hata_tablo = ""
            if hatalar:
                hs = "".join(f'<tr><td class="sayi">{h["satir"]}</td><td><code>{e(h["sutun"])}</code></td><td>{e(h["deger"])}</td>'
                             f'<td><span class="rozet kirmizi">{e(h["tur"])}</span></td><td>{e(h["aciklama"])}</td></tr>' for h in hatalar)
                hata_tablo = (f'<h2>Hatalar</h2><div class="tablo"><table><tr><th class="sayi">Satır</th><th>Sütun</th><th>Değer</th><th>Tür</th><th>Açıklama</th></tr>{hs}</table></div>'
                              f'<p class="soluk">Dosyayı hesap tablosunda düzeltip yeniden yükleyin. Satır numarası, başlık satırı 1 sayılarak verilir.</p>')
            onay = (f'<form method="post" action="/ice-aktar/onayla"><input type="hidden" name="token" value="{e(token)}">'
                    f'<button {"disabled" if hatalar else ""}>{len(sonuc["gecerli"])} kaydı içe aktar</button></form>')
            sonuc_h = bas + hata_tablo + onizleme + '<div class="bosluk"></div>' + onay
        govde = (f'<h1>İçe aktar (CSV)</h1><p class="alt">Dosya önce denetlenir; tek bir hata varsa hiçbir satır kaydedilmez. '
                 f'Örnek dosyalar: <code>lab/veri/ice-aktar/</code></p>{form}'
                 f'<div class="izgara i2" style="grid-template-columns: minmax(0, 1fr) 330px; margin-top:10px"><div>{sonuc_h or "<p class=soluk>Henüz dosya yüklenmedi.</p>"}</div>{yardim}</div>')
        return self.sayfa("İçe aktar", govde, "/ice-aktar", q)

    def disa_aktar_sayfa(self, q: dict) -> str:
        s = [("sirket", "Şirketler"), ("kisi", "Kişiler"), ("firsat", "Fırsatlar"), ("gorev", "Görevler"), ("asama_gecmisi", "Aşama geçmişi")]
        li = "".join(f'<li><a href="/disa-aktar/{k}.csv">{a} (CSV)</a></li>' for k, a in s)
        govde = (f'<h1>Dışa aktar</h1><p class="alt">UTF-8, virgülle ayrılmış CSV. Excel\'de Türkçe karakterler bozuk görünürse '
                 f'Veri → Metinden/CSV\'den ile açıp kodlamayı UTF-8 seçin.</p><div class="kart"><ul>{li}</ul></div>'
                 f'<p class="soluk">Dışa aktarılan dosya kişisel veri içerir: nereye kaydettiğinize ve kiminle paylaştığınıza dikkat edin.</p>')
        return self.sayfa("Dışa aktar", govde, "/disa-aktar", q)

    def csv_uret(self, nesne: str) -> str | None:
        sorgular = {
            "sirket": "SELECT id, ad, alan_adi, sektor, calisan, sehir, olusturma FROM sirket ORDER BY id",
            "kisi": ("SELECT k.id, k.ad, k.soyad, k.eposta, k.telefon, s.alan_adi AS sirket_alan_adi, k.unvan, k.izin_tanitim,"
                     " k.izin_tarihi, k.izin_kaynagi, k.aydinlatma_tarihi, k.olusturma FROM kisi k LEFT JOIN sirket s ON s.id = k.sirket_id ORDER BY k.id"),
            "firsat": ("SELECT f.id, f.ad, s.alan_adi AS sirket_alan_adi, k.eposta AS kisi_eposta, f.tutar, a.ad AS asama, u.ad AS sahip,"
                       " f.kaynak, f.beklenen_kapanis, f.kayip_nedeni, f.olusturma, f.guncelleme,"
                       " (SELECT MAX(tarih) FROM asama_gecmisi g WHERE g.firsat_id = f.id AND g.asama = 'kazanildi') AS kazanilma_tarihi"
                       " FROM firsat f LEFT JOIN sirket s ON s.id = f.sirket_id LEFT JOIN kisi k ON k.id = f.kisi_id"
                       " LEFT JOIN kullanici u ON u.id = f.sahip_id JOIN asama a ON a.kod = f.asama ORDER BY f.id"),
            "gorev": ("SELECT g.id, g.baslik, g.firsat_id, g.kisi_id, u.ad AS sahip, g.son_tarih, g.durum, g.olusturma, g.kaynak"
                      " FROM gorev g LEFT JOIN kullanici u ON u.id = g.sahip_id ORDER BY g.id"),
            "asama_gecmisi": "SELECT g.firsat_id, a.ad AS asama, g.tarih FROM asama_gecmisi g JOIN asama a ON a.kod = g.asama ORDER BY g.firsat_id, g.tarih, g.id",
        }
        if nesne not in sorgular:
            return None
        cur = self.c.execute(sorgular[nesne])
        cikti = io.StringIO()
        w = csv.writer(cikti, lineterminator="\n")
        w.writerow([d[0] for d in cur.description])
        w.writerows([["" if v is None else v for v in r] for r in cur.fetchall()])
        return cikti.getvalue()

    # ---------------------------------------------------------------- otomasyon
    def otomasyon_sayfa(self, q: dict) -> str:
        kurallar = self.c.execute("SELECT * FROM kural ORDER BY id").fetchall()
        ks = "".join(
            f'<tr><td><b>{e(r["ad"])}</b></td><td><code>{e(r["tetikleyici"])}</code></td><td>{e(r["kosul"])}</td><td>{e(r["eylem"])}</td>'
            f'<td><form method="post" action="/otomasyon/kural/{r["id"]}"><button class="kucuk {"" if r["aktif"] else "ikincil"}">'
            f'{"Açık — kapat" if r["aktif"] else "Kapalı — aç"}</button></form></td></tr>' for r in kurallar)
        url = db.ayar(self.c, "webhook_url")
        sir = db.ayar(self.c, "webhook_sirri")
        goster = q.get("sir") == "goster"
        olaylar = self.c.execute("SELECT * FROM olay ORDER BY id DESC LIMIT 25").fetchall()
        bekleyen = self.c.execute("SELECT COUNT(*) FROM olay WHERE teslim = 'bekliyor'").fetchone()[0]
        os_ = "".join(f'<tr><td class="sayi"><a href="/otomasyon?olay={r["id"]}#olay">{r["id"]}</a></td><td><code>{e(r["olay"])}</code></td>'
                      f'<td>{e(r["zaman"])}</td><td>{e(r["teslim"])}</td></tr>' for r in olaylar)
        secili = q.get("olay", "")
        ornek = ""
        if secili.isdigit():
            v = otomasyon.olay_ornegi(self.c, int(secili))
            if v:
                ornek = f'<h2 id="olay">Olay #{e(secili)} — gönderilen gövde</h2><pre class="json">{e(json.dumps(v, ensure_ascii=False, indent=2))}</pre>'
        govde = f"""<h1>Otomasyon</h1><p class="alt">Tetikleyici → koşul → eylem. İçeride kural, dışarıya olay (webhook).</p>
<h2>1 · CRM içi kurallar</h2><div class="tablo"><table><tr><th>Kural</th><th>Tetikleyici</th><th>Koşul</th><th>Eylem</th><th></th></tr>{ks}</table></div>
<h2>2 · Dışarıya olay gönderimi (webhook)</h2>
<div class="izgara i2"><div class="kart"><form method="post" action="/otomasyon/webhook">
{alan("Webhook adresi (ör. n8n Webhook düğümünün test adresi) — boş bırakılırsa hiçbir yere gönderilmez", girdi("webhook_url", url, "url", ' placeholder="http://localhost:5678/webhook-test/..."'), kimlik="webhook_url")}
<button>Kaydet</button></form>
<p>İmza sırrı: <code>{e(sir if goster else sir[:4] + "•" * 20)}</code> <a href="/otomasyon?sir={"" if goster else "goster"}">{"gizle" if goster else "göster"}</a></p>
<p class="soluk" style="margin-bottom:0">Her istekte <code>X-MiniCRM-Zaman</code> ve <code>X-MiniCRM-Imza</code> başlıkları gider:
imza = HMAC-SHA256(sır, "zaman:gövde"). Alıcı aynı hesabı yapıp karşılaştırır. Sırrı kimseyle paylaşmayın, ekran görüntüsüne koymayın.</p></div>
<div class="kart"><p><b>{bekleyen}</b> olay gönderilmeyi bekliyor.</p>
<form method="post" action="/otomasyon/gonder"><button {"disabled" if not url else ""}>Bekleyenleri şimdi gönder</button></form>
<p class="soluk" style="margin-bottom:0">Twenty'de karşılığı: Settings → APIs &amp; Webhooks → Webhooks. Olay adları aynı biçimde:
<code>opportunity.updated</code>, <code>person.created</code> …</p></div></div>
<h2>Son olaylar</h2><div class="tablo"><table><tr><th class="sayi">#</th><th>Olay</th><th>Zaman (UTC)</th><th>Teslim</th></tr>{os_ or '<tr><td colspan=4 class="soluk">Henüz olay yok — bir fırsatın aşamasını değiştirin.</td></tr>'}</table></div>
{ornek}"""
        return self.sayfa("Otomasyon", govde, "/otomasyon", q)

    # ---------------------------------------------------------------- KVKK
    def kvkk_sayfa(self, q: dict) -> str:
        kisiler = self.c.execute("SELECT k.*, s.ad AS sirket_ad FROM kisi k LEFT JOIN sirket s ON s.id = k.sirket_id ORDER BY k.id").fetchall()
        say = {"evet": 0, "hayir": 0, "": 0}
        for k in kisiler:
            if not k["anonim"]:
                say[k["izin_tanitim"] or ""] += 1
        aydinlatmasiz = sum(1 for k in kisiler if not k["aydinlatma_tarihi"] and not k["anonim"])
        satir = "".join(
            f'<tr><td><a href="/kisi/{k["id"]}">{e(k["ad"])} {e(k["soyad"])}</a><div class="soluk">{e(k["sirket_ad"] or "bireysel")}</div></td>'
            f'<td>{self.izin_rozet(k)}</td><td>{e(k["izin_kaynagi"] or "—")}</td><td>{tarih(k["aydinlatma_tarihi"])}</td>'
            f'<td class="sag"><a class="dugme ikincil" href="/kvkk/disa/{k["id"]}.json">Verisini indir</a> '
            f'<form method="post" action="/kvkk/anonimlestir/{k["id"]}" style="display:inline" onsubmit="return confirm(\'Bu kişinin adı, e-postası, telefonu ve notları kalıcı olarak silinecek. Emin misiniz?\')">'
            f'<button class="kucuk tehlike" {"disabled" if k["anonim"] else ""}>Anonimleştir</button></form></td></tr>' for k in kisiler)
        talepler = self.c.execute("SELECT t.*, k.ad || ' ' || k.soyad AS kisi_ad FROM kvkk_talep t LEFT JOIN kisi k ON k.id = t.kisi_id ORDER BY t.id DESC").fetchall()
        tur_ad = dict(KVKK_TALEP_TURLERI)
        ts = ""
        for t in talepler:
            kalan = (date.fromisoformat(t["son_tarih"]) - self.bugun).days
            durum = '<span class="rozet yesil">kapandı</span>' if t["durum"] == "kapali" else (
                f'<span class="rozet {"kirmizi" if kalan < 0 else "sari"}">{kalan} gün kaldı</span>')
            kapat = "" if t["durum"] == "kapali" else (f'<form method="post" action="/kvkk/talep/{t["id"]}/kapat" style="display:inline">'
                                                         f'<button class="kucuk ikincil">Sonuçlandı</button></form>')
            ts += (f'<tr><td>{t["id"]}</td><td>{e(t["kisi_ad"])}</td><td>{e(tur_ad.get(t["tur"], t["tur"]))}</td><td>{tarih(t["alinma"])}</td>'
                   f'<td>{tarih(t["son_tarih"])}</td><td>{durum}</td><td>{kapat}</td></tr>')
        govde = f"""<h1>KVKK ve izin</h1>
<div class="mesaj bilgi">Bu sayfa bir alıştırma aracıdır; hukuki danışmanlık değildir. Kendi işletmeniz için bir hukukçuya danışın.</div>
<div class="izgara i4"><div class="kart kpi"><div class="etiket">Tanıtım izni var</div><div class="deger">{say["evet"]}</div></div>
<div class="kart kpi"><div class="etiket">Reddetmiş</div><div class="deger">{say["hayir"]}</div></div>
<div class="kart kpi uyari"><div class="etiket">İzin durumu bilinmiyor</div><div class="deger">{say[""]}</div></div>
<div class="kart kpi uyari"><div class="etiket">Aydınlatma tarihi yok</div><div class="deger">{aydinlatmasiz}</div></div></div>
<h2>İlgili kişi başvuruları</h2>
<form method="post" action="/kvkk/talep" class="satir">{alan("Kişi", secim("kisi_id", self.kisi_secenek(), None), kimlik="kisi_id")}
{alan("Talep", secim("tur", KVKK_TALEP_TURLERI, "bilgi"), kimlik="tur")}{alan("Alınma tarihi", girdi("alinma", self.bugun.isoformat(), "date"), kimlik="alinma")}
<div class="alan"><button>Başvuruyu kaydet</button></div></form>
<p class="soluk">Son tarih, alınma tarihine 30 gün eklenerek hesaplanır (6698 sayılı Kanun md. 13: en geç otuz gün).</p>
<div class="tablo"><table><tr><th>#</th><th>Kişi</th><th>Talep</th><th>Alındı</th><th>Son tarih</th><th>Durum</th><th></th></tr>{ts or '<tr><td colspan=7 class="soluk">Kayıtlı başvuru yok.</td></tr>'}</table></div>
<h2>Kişiler ve izin kayıtları</h2>
<div class="tablo"><table><tr><th>Kişi</th><th>Tanıtım izni</th><th>İznin kaynağı</th><th>Aydınlatma</th><th></th></tr>{satir}</table></div>"""
        return self.sayfa("KVKK ve izin", govde, "/kvkk", q)

    def kisi_verisi(self, kid: int) -> dict | None:
        k = self.c.execute("SELECT * FROM kisi WHERE id = ?", (kid,)).fetchone()
        if not k:
            return None
        return {
            "aciklama": "Mini CRM'de bu kişiye ait kayıtların dökümü (ilgili kişi başvurusu için).",
            "olusturma": self.bugun.isoformat(),
            "kisi": dict(k),
            "sirket": dict(self.c.execute("SELECT * FROM sirket WHERE id = ?", (k["sirket_id"],)).fetchone() or {}) if k["sirket_id"] else None,
            "firsatlar": [dict(r) for r in self.c.execute("SELECT id, ad, tutar, asama, olusturma FROM firsat WHERE kisi_id = ?", (kid,))],
            "gorevler": [dict(r) for r in self.c.execute("SELECT id, baslik, son_tarih, durum FROM gorev WHERE kisi_id = ?", (kid,))],
            "notlar": [dict(r) for r in self.c.execute("SELECT id, tarih, metin FROM notlar WHERE kisi_id = ?", (kid,))],
        }

    # ---------------------------------------------------------------- ekip
    def ekip_sayfa(self, q: dict) -> str:
        m = metrik.hesapla(self.c, self.bugun)
        b = self.bugun.isoformat()
        satir = ""
        for u in self.c.execute("SELECT * FROM kullanici ORDER BY id"):
            acik = self.c.execute("SELECT COUNT(*), IFNULL(SUM(tutar),0) FROM firsat f JOIN asama a ON a.kod = f.asama WHERE a.acik = 1 AND sahip_id = ?", (u["id"],)).fetchone()
            gec = self.c.execute("SELECT COUNT(*) FROM gorev WHERE durum = 'acik' AND son_tarih < ? AND sahip_id = ?", (b, u["id"])).fetchone()[0]
            sh = next((x for x in m["sahipler"] if x["ad"] == u["ad"]), None)
            aktif = u["id"] == self.aktif()
            satir += (f'<tr><td><b>{e(u["ad"])}</b><div class="soluk">{e(u["unvan"])}</div></td><td>{"yönetici" if u["rol"] == "yonetici" else "satış"}</td>'
                      f'<td class="sayi">{acik[0]}</td><td class="sayi">{tl(acik[1])}</td><td class="sayi">{gec}</td>'
                      f'<td class="sayi">{yuzde(sh["kazanma_orani"]) if sh else "—"}</td>'
                      f'<td><a href="/firsatlar?sahip={u["id"]}">hattı</a> · <a href="/gorevler?sahip={u["id"]}">görevleri</a></td>'
                      f'<td>{"<span class=\'rozet mavi\'>aktif</span>" if aktif else self.aktif_dugme(u["id"])}</td></tr>')
        govde = f"""<h1>Ekip</h1><p class="alt">Her fırsatın ve görevin bir sahibi vardır. Mini CRM'de giriş yoktur; “aktif kullanıcı” yalnız “Benim hattım / Benim görevlerim” görünümlerini seçer.</p>
<div class="tablo"><table><tr><th>Kişi</th><th>Rol</th><th class="sayi">Açık fırsat</th><th class="sayi">Açık tutar</th><th class="sayi">Geciken görev</th><th class="sayi">Kazanma oranı</th><th>Görünümler</th><th></th></tr>{satir}</table></div>
<h2>Roller (Twenty'de nasıl?)</h2><div class="kart"><p style="margin-top:0">Gerçek bir CRM'de roller, kimin hangi kaydı görüp değiştirebileceğini belirler
(Twenty: Settings → Members → Roles). Mini CRM bunu yapmaz; ekip kurallarını yazılı tutarsınız (ders 4.3).</p>
<ul style="margin-bottom:0"><li><b>yönetici</b>: bütün kayıtlar, ayarlar, dışa aktarma</li><li><b>satış</b>: kendi fırsat ve görevleri; başkasının kaydını değiştirmeden önce sahibine sorar</li></ul></div>"""
        return self.sayfa("Ekip", govde, "/ekip", q)

    @staticmethod
    def aktif_dugme(uid: int) -> str:
        return (f'<form method="post" action="/ekip/aktif" style="display:inline"><input type="hidden" name="kullanici_id" value="{uid}">'
                f'<button class="kucuk ikincil">Aktif yap</button></form>')

    def bulunamadi(self, q: dict) -> str:
        return self.sayfa("Bulunamadı", '<h1>Sayfa ya da kayıt bulunamadı</h1><p><a href="/">Panoya dön</a></p>', "", q)

    # ---------------------------------------------------------------- yazma işlemleri
    def asama_degistir(self, fid: int, yeni: str, kayip_nedeni: str = "") -> tuple[str, str]:
        f = self.c.execute("SELECT * FROM firsat WHERE id = ?", (fid,)).fetchone()
        adlar = self.asama_adlari()
        if not f or yeni not in adlar:
            return "Geçersiz fırsat ya da aşama.", "hata"
        if yeni == "kaybedildi" and not kayip_nedeni:
            return "Kaybedildi için kayıp nedeni seçmelisiniz.", "hata"
        if yeni == f["asama"]:
            return "Fırsat zaten bu aşamada.", "bilgi"
        b = self.bugun.isoformat()
        self.c.execute("UPDATE firsat SET asama = ?, kayip_nedeni = ?, guncelleme = ? WHERE id = ?",
                       (yeni, kayip_nedeni if yeni == "kaybedildi" else "", b, fid))
        self.c.execute("INSERT INTO asama_gecmisi (firsat_id, asama, tarih) VALUES (?, ?, ?)", (fid, yeni, b))
        veri = db.kayit_sozlugu(self.c, "firsat", fid)
        veri["onceki_asama"] = f["asama"]
        db.olay_yaz(self.c, "firsat", "updated", fid, veri)
        yapilan = otomasyon.asama_degisti(self.c, dict(f), yeni, self.bugun)
        self.c.commit()
        otomasyon.gonder(self.c)
        return f'“{f["ad"]}” → {adlar[yeni]}. ' + " ".join(yapilan), ""


class Isleyici(BaseHTTPRequestHandler):
    uyg: Uygulama
    server_version = "MiniCRM/1.0"

    def log_message(self, fmt, *args):  # noqa: D401
        if not getattr(self.server, "sessiz", False):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def gonder(self, govde: str | bytes, tur: str = "text/html; charset=utf-8", kod: int = 200, ek: dict | None = None):
        veri = govde.encode("utf-8") if isinstance(govde, str) else govde
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(veri)

    def yonlendir(self, yol: str, mesaj: str = "", tur: str = ""):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", yonlendir_adresi(yol, mesaj, tur))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form_oku(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        ham = self.rfile.read(n) if n else b""
        tur = self.headers.get("Content-Type", "")
        if tur.startswith("multipart/form-data"):
            msj = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {tur}\r\n\r\n".encode() + ham)
            sonuc = {}
            for parca in msj.iter_parts():
                ad = parca.get_param("name", header="content-disposition")
                if parca.get_filename() is not None:
                    sonuc[ad] = parca.get_payload(decode=True) or b""
                    sonuc[ad + "__ad"] = parca.get_filename()
                else:
                    sonuc[ad] = (parca.get_payload(decode=True) or b"").decode("utf-8", "replace")
            return sonuc
        return {k: v[0] for k, v in parse_qs(ham.decode("utf-8"), keep_blank_values=True).items()}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        yol = u.path.rstrip("/") or "/"
        a = self.uyg
        try:
            if yol.startswith("/statik/"):
                return self.statik(yol)
            rotalar = [
                (r"/", lambda: a.pano(q)),
                (r"/firsatlar", lambda: a.hat(q)),
                (r"/firsat/yeni", lambda: a.firsat_yeni(q)),
                (r"/firsat/(\d+)", lambda i: a.firsat(q, int(i))),
                (r"/kisiler", lambda: a.kisiler(q)),
                (r"/kisi/yeni", lambda: a.kisi(q, None)),
                (r"/kisi/(\d+)", lambda i: a.kisi(q, int(i))),
                (r"/sirketler", lambda: a.sirketler(q)),
                (r"/sirket/yeni", lambda: a.sirket(q, None)),
                (r"/sirket/(\d+)", lambda i: a.sirket(q, int(i))),
                (r"/gorevler", lambda: a.gorevler(q)),
                (r"/sablonlar", lambda: a.sablonlar(q)),
                (r"/sablon/yeni", lambda: a.sablon(q, None)),
                (r"/sablon/(\d+)", lambda i: a.sablon(q, int(i))),
                (r"/rapor", lambda: a.rapor(q)),
                (r"/denetim", lambda: a.denetim(q)),
                (r"/ice-aktar", lambda: a.ice_aktar_sayfa(q)),
                (r"/disa-aktar", lambda: a.disa_aktar_sayfa(q)),
                (r"/otomasyon", lambda: a.otomasyon_sayfa(q)),
                (r"/kvkk", lambda: a.kvkk_sayfa(q)),
                (r"/ekip", lambda: a.ekip_sayfa(q)),
            ]
            for desen, f in rotalar:
                m = re.fullmatch(desen, yol)
                if m:
                    return self.gonder(f(*m.groups()))
            if m := re.fullmatch(r"/ice-aktar/sablon/(sirket|kisi|firsat)\.csv", yol):
                return self.gonder(ice_aktar.ornek_dosya(m.group(1)), "text/csv; charset=utf-8",
                                   ek={"Content-Disposition": f'attachment; filename="{m.group(1)}-sablon.csv"'})
            if m := re.fullmatch(r"/disa-aktar/(\w+)\.csv", yol):
                metin = a.csv_uret(m.group(1))
                if metin is not None:
                    return self.gonder(metin, "text/csv; charset=utf-8",
                                       ek={"Content-Disposition": f'attachment; filename="mini-crm-{m.group(1)}.csv"'})
            if m := re.fullmatch(r"/kvkk/disa/(\d+)\.json", yol):
                v = a.kisi_verisi(int(m.group(1)))
                if v:
                    return self.gonder(json.dumps(v, ensure_ascii=False, indent=2), "application/json; charset=utf-8",
                                       ek={"Content-Disposition": f'attachment; filename="kisi-{m.group(1)}-veri.json"'})
            if yol == "/api/rapor":
                s, b1, b2 = a.rapor_parametre(q)
                return self.gonder(json.dumps(metrik.hesapla(a.c, a.bugun, s, b1, b2), ensure_ascii=False, indent=2),
                                   "application/json; charset=utf-8")
            if yol == "/api/olaylar":
                rows = [dict(r) | {"veri": json.loads(r["veri"])} for r in a.c.execute("SELECT * FROM olay ORDER BY id")]
                return self.gonder(json.dumps(rows, ensure_ascii=False, indent=2), "application/json; charset=utf-8")
            if yol == "/api/denetim":
                return self.gonder(json.dumps(a.denetim_listesi(), ensure_ascii=False, indent=2), "application/json; charset=utf-8")
            return self.gonder(a.bulunamadi(q), kod=404)
        except Exception as h:  # öğrenci ekranında anlaşılır hata
            import traceback
            traceback.print_exc()
            return self.gonder(f"<h1>Beklenmeyen hata</h1><pre>{e(h)}</pre>", kod=500)

    def statik(self, yol: str):
        dosya = (STATIK / yol.removeprefix("/statik/")).resolve()
        if not str(dosya).startswith(str(STATIK)) or not dosya.is_file():
            return self.gonder("bulunamadı", "text/plain; charset=utf-8", 404)
        tur = mimetypes.guess_type(dosya.name)[0] or "application/octet-stream"
        if dosya.suffix == ".woff2":
            tur = "font/woff2"
        if tur.startswith("text/") or tur.endswith("javascript"):
            tur += "; charset=utf-8"
        return self.gonder(dosya.read_bytes(), tur)

    def do_POST(self):
        u = urlparse(self.path)
        yol = u.path.rstrip("/")
        a = self.uyg
        form = self.form_oku()
        b = a.bugun.isoformat()
        try:
            if m := re.fullmatch(r"/firsat/(\d+)/asama", yol):
                fid = int(m.group(1))
                mesaj, tur = a.asama_degistir(fid, form.get("asama", ""), form.get("kayip_nedeni", ""))
                geri = form.get("geri") or f"/firsat/{fid}"
                if tur == "hata" and form.get("asama") == "kaybedildi":
                    geri = f"/firsat/{fid}?kaybet=1"
                return self.yonlendir(geri if geri.startswith("/") else "/", mesaj, tur)
            if yol == "/firsat/yeni":
                f, h = a.firsat_dogrula(form)
                if h:
                    return self.gonder(a.firsat_yeni({"m": "Formda hata var.", "mt": "hata"}, f, h))
                asama = f["asama"] or "yeni"
                cur = a.c.execute("INSERT INTO firsat (ad, sirket_id, kisi_id, tutar, sahip_id, kaynak, beklenen_kapanis, asama,"
                                  " olusturma, guncelleme) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                  (f["ad"], f["sirket_id"] or None, f["kisi_id"] or None, int(f["tutar"]), int(f["sahip_id"] or a.aktif()),
                                   f["kaynak"], f["beklenen_kapanis"], asama, b, b))
                a.c.execute("INSERT INTO asama_gecmisi (firsat_id, asama, tarih) VALUES (?,?,?)", (cur.lastrowid, asama, b))
                db.olay_yaz(a.c, "firsat", "created", cur.lastrowid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(f"/firsat/{cur.lastrowid}", "Fırsat eklendi. Şimdi sonraki adımı görev olarak yazın.")
            if m := re.fullmatch(r"/firsat/(\d+)", yol):
                fid = int(m.group(1))
                f, h = a.firsat_dogrula(form)
                if h:
                    return self.yonlendir(f"/firsat/{fid}", " ".join(h.values()), "hata")
                a.c.execute("UPDATE firsat SET ad=?, sirket_id=?, kisi_id=?, tutar=?, sahip_id=?, kaynak=?, beklenen_kapanis=?, guncelleme=? WHERE id=?",
                            (f["ad"], f["sirket_id"] or None, f["kisi_id"] or None, int(f["tutar"]), int(f["sahip_id"]), f["kaynak"],
                             f["beklenen_kapanis"], b, fid))
                db.olay_yaz(a.c, "firsat", "updated", fid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(f"/firsat/{fid}", "Kaydedildi.")
            if yol == "/kisi/yeni" or re.fullmatch(r"/kisi/\d+", yol):
                kid = int(yol.rsplit("/", 1)[1]) if yol[-1].isdigit() else None
                k, h = a.kisi_dogrula(form, kid)
                if h:
                    return self.gonder(a.kisi({"m": "Kayıt kaydedilmedi: formdaki hataları düzeltin.", "mt": "hata"}, kid, k, h))
                deger = (k["ad"], k["soyad"], k["eposta"] or None, k["telefon"], k["sirket_id"] or None, k["unvan"], k["izin_tanitim"],
                         k["izin_tarihi"], k["izin_kaynagi"], k["aydinlatma_tarihi"])
                if kid:
                    a.c.execute("UPDATE kisi SET ad=?, soyad=?, eposta=?, telefon=?, sirket_id=?, unvan=?, izin_tanitim=?, izin_tarihi=?,"
                                " izin_kaynagi=?, aydinlatma_tarihi=? WHERE id=?", deger + (kid,))
                    db.olay_yaz(a.c, "kisi", "updated", kid)
                else:
                    cur = a.c.execute("INSERT INTO kisi (ad, soyad, eposta, telefon, sirket_id, unvan, izin_tanitim, izin_tarihi,"
                                      " izin_kaynagi, aydinlatma_tarihi, olusturma) VALUES (?,?,?,?,?,?,?,?,?,?,?)", deger + (b,))
                    kid = cur.lastrowid
                    db.olay_yaz(a.c, "kisi", "created", kid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(f"/kisi/{kid}", "Kişi kaydedildi.")
            if yol == "/sirket/yeni" or re.fullmatch(r"/sirket/\d+", yol):
                sid = int(yol.rsplit("/", 1)[1]) if yol[-1].isdigit() else None
                s, h = a.sirket_dogrula(form, sid)
                if h:
                    return self.gonder(a.sirket({"m": "Kayıt kaydedilmedi: formdaki hataları düzeltin.", "mt": "hata"}, sid, s, h))
                deger = (s["ad"], s["alan_adi"] or None, s["sektor"], s["calisan"], s["sehir"])
                if sid:
                    a.c.execute("UPDATE sirket SET ad=?, alan_adi=?, sektor=?, calisan=?, sehir=? WHERE id=?", deger + (sid,))
                    db.olay_yaz(a.c, "sirket", "updated", sid)
                else:
                    sid = a.c.execute("INSERT INTO sirket (ad, alan_adi, sektor, calisan, sehir, olusturma) VALUES (?,?,?,?,?,?)", deger + (b,)).lastrowid
                    db.olay_yaz(a.c, "sirket", "created", sid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(f"/sirket/{sid}", "Şirket kaydedildi.")
            if yol == "/gorev/yeni":
                if not form.get("baslik", "").strip():
                    return self.yonlendir(form.get("geri") or "/gorevler", "Görev başlığı boş olamaz.", "hata")
                gid = a.c.execute("INSERT INTO gorev (baslik, firsat_id, kisi_id, sahip_id, son_tarih, durum, olusturma) VALUES (?,?,?,?,?, 'acik', ?)",
                                  (form["baslik"].strip(), form.get("firsat_id") or None, form.get("kisi_id") or None,
                                   int(form.get("sahip_id") or a.aktif()), form.get("son_tarih") or b, b)).lastrowid
                if form.get("firsat_id"):
                    a.c.execute("UPDATE firsat SET guncelleme = ? WHERE id = ?", (b, form["firsat_id"]))
                db.olay_yaz(a.c, "gorev", "created", gid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(form.get("geri") or "/gorevler", "Görev eklendi.")
            if m := re.fullmatch(r"/gorev/(\d+)/tamamla", yol):
                a.c.execute("UPDATE gorev SET durum = 'tamam' WHERE id = ?", (int(m.group(1)),))
                db.olay_yaz(a.c, "gorev", "updated", int(m.group(1)))
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir(form.get("geri") or "/gorevler", "Görev tamamlandı. Sonraki adımı yazmayı unutmayın.")
            if yol == "/not/yeni":
                a.c.execute("INSERT INTO notlar (firsat_id, kisi_id, tarih, yazan_id, metin) VALUES (?,?,?,?,?)",
                            (form.get("firsat_id") or None, form.get("kisi_id") or None, b, a.aktif(), form.get("metin", "").strip()))
                if form.get("firsat_id"):
                    a.c.execute("UPDATE firsat SET guncelleme = ? WHERE id = ?", (b, form["firsat_id"]))
                a.c.commit()
                return self.yonlendir(f"/firsat/{form.get('firsat_id')}" if form.get("firsat_id") else "/", "Not eklendi.")
            if yol == "/sablon/yeni" or re.fullmatch(r"/sablon/\d+", yol):
                sid = int(yol.rsplit("/", 1)[1]) if yol[-1].isdigit() else None
                deger = (form.get("ad", "").strip() or "Adsız şablon", form.get("tur", "bilgilendirme"), form.get("konu", ""), form.get("govde", ""))
                if sid:
                    a.c.execute("UPDATE sablon SET ad=?, tur=?, konu=?, govde=? WHERE id=?", deger + (sid,))
                else:
                    sid = a.c.execute("INSERT INTO sablon (ad, tur, konu, govde) VALUES (?,?,?,?)", deger).lastrowid
                a.c.commit()
                return self.yonlendir(f"/sablon/{sid}", "Şablon kaydedildi. Bir kişi seçip önizleyin.")
            if yol == "/ice-aktar":
                nesne = form.get("nesne", "kisi")
                if nesne not in ice_aktar.SUTUNLAR:
                    nesne = "kisi"
                ham = form.get("dosya", b"")
                if isinstance(ham, str):
                    ham = ham.encode()
                sonuc = ice_aktar.dogrula(a.c, nesne, ham)
                token = secrets.token_hex(8)
                a.yuklemeler = {token: (nesne, ham, form.get("dosya__ad", ""))}
                return self.gonder(a.ice_aktar_sayfa({}, sonuc, token))
            if yol == "/ice-aktar/onayla":
                kayit = a.yuklemeler.pop(form.get("token", ""), None)
                if not kayit:
                    return self.yonlendir("/ice-aktar", "Yükleme bulunamadı; dosyayı yeniden yükleyin.", "hata")
                nesne, ham, _ = kayit
                sonuc = ice_aktar.dogrula(a.c, nesne, ham)
                n = ice_aktar.kaydet(a.c, sonuc, a.bugun)
                otomasyon.gonder(a.c)
                hedef = {"sirket": "/sirketler", "kisi": "/kisiler", "firsat": "/firsatlar"}[nesne]
                if not n:
                    return self.yonlendir("/ice-aktar", "Dosyada hata olduğu için hiçbir kayıt aktarılmadı.", "hata")
                return self.yonlendir(hedef, f"{n} kayıt içe aktarıldı.")
            if m := re.fullmatch(r"/otomasyon/kural/(\d+)", yol):
                a.c.execute("UPDATE kural SET aktif = 1 - aktif WHERE id = ?", (int(m.group(1)),))
                a.c.commit()
                return self.yonlendir("/otomasyon", "Kural güncellendi.")
            if yol == "/otomasyon/webhook":
                url = form.get("webhook_url", "").strip()
                if url and not re.match(r"^https?://", url):
                    return self.yonlendir("/otomasyon", "Adres http:// ya da https:// ile başlamalı.", "hata")
                db.ayar_yaz(a.c, "webhook_url", url)
                a.c.commit()
                return self.yonlendir("/otomasyon", "Webhook adresi kaydedildi." if url else "Webhook kapatıldı (adres boş).")
            if yol == "/otomasyon/gonder":
                s = otomasyon.gonder(a.c)
                basarili = sum(1 for x in s if x["durum"].startswith("teslim"))
                return self.yonlendir("/otomasyon", f"{len(s)} olay denendi, {basarili} teslim edildi.", "" if basarili == len(s) else "hata")
            if yol == "/kvkk/talep":
                alinma = form.get("alinma") or b
                son = (date.fromisoformat(alinma) + timedelta(days=30)).isoformat()
                a.c.execute("INSERT INTO kvkk_talep (kisi_id, tur, alinma, son_tarih) VALUES (?,?,?,?)",
                            (int(form["kisi_id"]), form.get("tur", "bilgi"), alinma, son))
                a.c.commit()
                return self.yonlendir("/kvkk", f"Başvuru kaydedildi; son tarih {tarih(son)}.")
            if m := re.fullmatch(r"/kvkk/talep/(\d+)/kapat", yol):
                a.c.execute("UPDATE kvkk_talep SET durum = 'kapali' WHERE id = ?", (int(m.group(1)),))
                a.c.commit()
                return self.yonlendir("/kvkk", "Başvuru sonuçlandı olarak işaretlendi.")
            if m := re.fullmatch(r"/kvkk/anonimlestir/(\d+)", yol):
                kid = int(m.group(1))
                a.c.execute("UPDATE kisi SET ad = 'Anonim', soyad = ?, eposta = NULL, telefon = '', unvan = '', izin_tanitim = '',"
                            " izin_tarihi = '', izin_kaynagi = '', aydinlatma_tarihi = '', anonim = 1 WHERE id = ?", (f"#{kid}", kid))
                a.c.execute("DELETE FROM notlar WHERE kisi_id = ?", (kid,))
                db.olay_yaz(a.c, "kisi", "updated", kid)
                a.c.commit()
                otomasyon.gonder(a.c)
                return self.yonlendir("/kvkk", f"Kişi #{kid} anonimleştirildi: ad, e-posta, telefon ve notlar silindi; fırsat tutarları raporda kalır.")
            if yol == "/ekip/aktif":
                db.ayar_yaz(a.c, "aktif_kullanici", str(int(form.get("kullanici_id", "1"))))
                a.c.commit()
                return self.yonlendir("/ekip", "Aktif kullanıcı değişti.")
            return self.gonder(a.bulunamadi({}), kod=404)
        except sqlite3.IntegrityError as h:
            a.c.rollback()
            return self.yonlendir("/", f"Kayıt reddedildi (veritabanı kuralı): {h}", "hata")
        except (ValueError, KeyError) as h:
            a.c.rollback()
            return self.yonlendir(urlparse(self.headers.get("Referer", "/")).path or "/",
                                  f"Formda eksik ya da geçersiz alan: {h}", "hata")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mini CRM — CRM 101 alıştırma uygulaması")
    ap.add_argument("--port", type=int, default=8060)
    ap.add_argument("--db", type=Path, default=db.VARSAYILAN_DB, help="veritabanı dosyası (lab klasörüne göre)")
    ap.add_argument("--bugun", help="uygulamanın 'bugün' saydığı tarih, YYYY-AA-GG (varsayılan: gerçek bugün)")
    ap.add_argument("--sifirla", action="store_true", help="veritabanını silip örnek veriden yeniden kur")
    ap.add_argument("--bos", action="store_true", help="--sifirla ile: örnek kayıtlar olmadan boş kur (bitirme ödevi)")
    ap.add_argument("--sessiz", action="store_true", help="istek günlüğü yazma")
    a = ap.parse_args()
    bugun = db.bugun_hesapla(a.bugun)
    yol = a.db if a.db.is_absolute() else (db.LAB / a.db)
    if a.sifirla or not yol.exists():
        db.kur(yol, bugun, bos=a.bos)
        print(f"{'Boş CRM' if a.bos else 'Örnek veri'} kuruldu: {yol.relative_to(db.LAB) if yol.is_relative_to(db.LAB) else yol} (bugün = {bugun.isoformat()})")
    Isleyici.uyg = Uygulama(yol, bugun)
    sunucu = HTTPServer(("127.0.0.1", a.port), Isleyici)
    sunucu.sessiz = a.sessiz
    print(f"Mini CRM açık: http://localhost:{a.port}  (durdurmak için Ctrl+C)")
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        print("\nMini CRM kapatıldı.")


if __name__ == "__main__":
    main()
