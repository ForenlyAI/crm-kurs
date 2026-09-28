"""Mini CRM veri katmanı: SQLite şeması, tohum veriden kurulum, olay (webhook) kaydı.

Veritabanı tek bir dosyadır (varsayılan: lab/calisma/mini-crm.db). Silinirse bir sonraki
açılışta tohum veriden (veri/ornek-veri.json) yeniden kurulur.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
TOHUM = LAB / "veri" / "ornek-veri.json"
VARSAYILAN_DB = LAB / "calisma" / "mini-crm.db"

SEMA = """
CREATE TABLE ayar (anahtar TEXT PRIMARY KEY, deger TEXT);
CREATE TABLE asama (kod TEXT PRIMARY KEY, ad TEXT NOT NULL, sira INTEGER NOT NULL,
                    olasilik INTEGER NOT NULL, acik INTEGER NOT NULL);
CREATE TABLE kullanici (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, rol TEXT NOT NULL, unvan TEXT);
CREATE TABLE sirket (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, alan_adi TEXT UNIQUE, sektor TEXT,
                     calisan TEXT, sehir TEXT, olusturma TEXT NOT NULL);
CREATE TABLE kisi (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, soyad TEXT NOT NULL,
                   sirket_id INTEGER REFERENCES sirket(id), unvan TEXT, eposta TEXT UNIQUE,
                   telefon TEXT, izin_tanitim TEXT DEFAULT '', izin_tarihi TEXT DEFAULT '',
                   izin_kaynagi TEXT DEFAULT '', aydinlatma_tarihi TEXT DEFAULT '',
                   anonim INTEGER DEFAULT 0, olusturma TEXT NOT NULL);
CREATE TABLE firsat (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, sirket_id INTEGER REFERENCES sirket(id),
                     kisi_id INTEGER REFERENCES kisi(id), tutar INTEGER, sahip_id INTEGER REFERENCES kullanici(id),
                     kaynak TEXT, beklenen_kapanis TEXT, asama TEXT NOT NULL REFERENCES asama(kod),
                     kayip_nedeni TEXT DEFAULT '', olusturma TEXT NOT NULL, guncelleme TEXT NOT NULL);
CREATE TABLE asama_gecmisi (id INTEGER PRIMARY KEY, firsat_id INTEGER NOT NULL REFERENCES firsat(id),
                            asama TEXT NOT NULL, tarih TEXT NOT NULL);
CREATE TABLE gorev (id INTEGER PRIMARY KEY, baslik TEXT NOT NULL, firsat_id INTEGER REFERENCES firsat(id),
                    kisi_id INTEGER REFERENCES kisi(id), sahip_id INTEGER REFERENCES kullanici(id),
                    son_tarih TEXT NOT NULL, durum TEXT NOT NULL DEFAULT 'acik', olusturma TEXT NOT NULL,
                    kaynak TEXT DEFAULT 'elle');
CREATE TABLE notlar (id INTEGER PRIMARY KEY, firsat_id INTEGER, kisi_id INTEGER, tarih TEXT NOT NULL,
                     yazan_id INTEGER, metin TEXT NOT NULL);
CREATE TABLE sablon (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, tur TEXT NOT NULL, konu TEXT NOT NULL, govde TEXT NOT NULL);
CREATE TABLE kayip_nedeni (ad TEXT PRIMARY KEY, sira INTEGER);
CREATE TABLE kaynak (ad TEXT PRIMARY KEY, sira INTEGER);
CREATE TABLE kural (id INTEGER PRIMARY KEY, ad TEXT, tetikleyici TEXT, kosul TEXT, eylem TEXT, aktif INTEGER);
CREATE TABLE olay (id INTEGER PRIMARY KEY, olay TEXT NOT NULL, zaman TEXT NOT NULL, veri TEXT NOT NULL,
                   teslim TEXT DEFAULT 'bekliyor');
CREATE TABLE kvkk_talep (id INTEGER PRIMARY KEY, kisi_id INTEGER, tur TEXT NOT NULL, alinma TEXT NOT NULL,
                         son_tarih TEXT NOT NULL, durum TEXT NOT NULL DEFAULT 'acik', not_ TEXT DEFAULT '');
"""


def bugun_hesapla(deger: str | None) -> date:
    return date.fromisoformat(deger) if deger else date.today()


def kaydir(tarih: str, gun: int) -> str:
    """'2026-09-25' biçimindeki tarihi gun kadar kaydırır (boşsa boş döner)."""
    if not tarih:
        return tarih
    return (date.fromisoformat(tarih) + timedelta(days=gun)).isoformat()


def baglan(yol: Path) -> sqlite3.Connection:
    c = sqlite3.connect(yol, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def kur(yol: Path, bugun: date, tohum: Path = TOHUM, bos: bool = False) -> None:
    """Veritabanını siler ve tohum veriden yeniden kurar.

    bos=True: yalnız ayarlar (aşamalar, ekip, kayıp nedenleri, kaynaklar, kurallar, şablonlar) kurulur;
    şirket, kişi, fırsat, görev ve not yoktur (bitirme ödevi için temiz başlangıç).

    Tohumdaki tarihler referans güne göre yazılmıştır; kurulumda hepsi 'bugün'e kaydırılır,
    böylece 'geciken görev' ve 'bugün' listeleri kurs hangi gün izlenirse izlensin aynı görünür.
    """
    v = json.loads(tohum.read_text(encoding="utf-8"))
    if bos:
        for anahtar in ("sirketler", "kisiler", "firsatlar", "gorevler", "notlar"):
            v[anahtar] = []
    gun = (bugun - date.fromisoformat(v["referans_tarih"])).days
    yol.parent.mkdir(parents=True, exist_ok=True)
    if yol.exists():
        yol.unlink()
    c = baglan(yol)
    c.executescript(SEMA)
    k = lambda t: kaydir(t, gun)  # noqa: E731
    c.executemany("INSERT INTO ayar VALUES (?, ?)", [
        ("isletme", v["isletme"]["ad"]),
        ("webhook_url", ""),
        ("webhook_sirri", secrets.token_hex(16)),
        ("aktif_kullanici", "1"),
        ("kurulum", bugun.isoformat()),
    ])
    for i, a in enumerate(v["asamalar"]):
        c.execute("INSERT INTO asama VALUES (?, ?, ?, ?, ?)", (a["kod"], a["ad"], i, a["olasilik"], int(a["acik"])))
    for i, n in enumerate(v["kayip_nedenleri"]):
        c.execute("INSERT INTO kayip_nedeni VALUES (?, ?)", (n, i))
    for i, n in enumerate(v["kaynaklar"]):
        c.execute("INSERT INTO kaynak VALUES (?, ?)", (n, i))
    for u in v["kullanicilar"]:
        c.execute("INSERT INTO kullanici VALUES (?, ?, ?, ?)", (u["id"], u["ad"], u["rol"], u["unvan"]))
    for s in v["sirketler"]:
        c.execute("INSERT INTO sirket VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (s["id"], s["ad"], s["alan_adi"], s["sektor"], s["calisan"], s["sehir"], k(s["olusturma"])))
    for p in v["kisiler"]:
        c.execute("INSERT INTO kisi (id, ad, soyad, sirket_id, unvan, eposta, telefon, izin_tanitim, izin_tarihi,"
                  " izin_kaynagi, aydinlatma_tarihi, olusturma) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (p["id"], p["ad"], p["soyad"], p["sirket_id"], p["unvan"], p["eposta"], p["telefon"],
                   p["izin_tanitim"], k(p["izin_tarihi"]), p["izin_kaynagi"], k(p["aydinlatma_tarihi"]), k(p["olusturma"])))
    for f in v["firsatlar"]:
        son = f["gecmis"][-1]["tarih"]
        c.execute("INSERT INTO firsat VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f["id"], f["ad"], f["sirket_id"], f["kisi_id"], f["tutar"], f["sahip_id"], f["kaynak"],
                   k(f["beklenen_kapanis"]), f["asama"], f["kayip_nedeni"], k(f["olusturma"]), k(son)))
        for g in f["gecmis"]:
            c.execute("INSERT INTO asama_gecmisi (firsat_id, asama, tarih) VALUES (?, ?, ?)",
                      (f["id"], g["asama"], k(g["tarih"])))
    for g in v["gorevler"]:
        c.execute("INSERT INTO gorev (id, baslik, firsat_id, kisi_id, sahip_id, son_tarih, durum, olusturma)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (g["id"], g["baslik"], g["firsat_id"], g["kisi_id"], g["sahip_id"], k(g["son_tarih"]),
                   g["durum"], k(g["olusturma"])))
    for n in v["notlar"]:
        c.execute("INSERT INTO notlar VALUES (?,?,?,?,?,?)",
                  (n["id"], n["firsat_id"], n["kisi_id"], k(n["tarih"]), n["yazan_id"], n["metin"]))
    for s in v["sablonlar"]:
        c.execute("INSERT INTO sablon VALUES (?,?,?,?,?)", (s["id"], s["ad"], s["tur"], s["konu"], s["govde"]))
    for r in v["kurallar"]:
        c.execute("INSERT INTO kural VALUES (?,?,?,?,?,?)",
                  (r["id"], r["ad"], r["tetikleyici"], r["kosul"], r["eylem"], int(r["aktif"])))
    c.commit()
    c.close()


def ayar(c: sqlite3.Connection, anahtar: str) -> str:
    r = c.execute("SELECT deger FROM ayar WHERE anahtar = ?", (anahtar,)).fetchone()
    return r["deger"] if r else ""


def ayar_yaz(c: sqlite3.Connection, anahtar: str, deger: str) -> None:
    c.execute("INSERT INTO ayar VALUES (?, ?) ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
              (anahtar, deger))


def asamalar(c: sqlite3.Connection) -> list[sqlite3.Row]:
    return c.execute("SELECT * FROM asama ORDER BY sira").fetchall()


def zaman_damgasi() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def kayit_sozlugu(c: sqlite3.Connection, tablo: str, kimlik: int) -> dict:
    r = c.execute(f"SELECT * FROM {tablo} WHERE id = ?", (kimlik,)).fetchone()  # tablo adı koddan gelir
    return dict(r) if r else {"id": kimlik}


NESNE_ADI = {"kisi": "person", "sirket": "company", "firsat": "opportunity", "gorev": "task"}


def olay_yaz(c: sqlite3.Connection, tablo: str, islem: str, kimlik: int, veri: dict | None = None) -> int:
    """Değişikliği giden olaylar kutusuna yazar (Twenty'nin webhook biçimine benzer: event, data, timestamp).

    islem: created / updated / deleted. Gönderim otomasyon.py'de yapılır.
    """
    govde = {
        "event": f"{NESNE_ADI.get(tablo, tablo)}.{islem}",
        "data": veri if veri is not None else kayit_sozlugu(c, tablo, kimlik),
        "timestamp": zaman_damgasi(),
    }
    # Webhook adresi yokken oluşan olay kimseye gitmez (Twenty'de de webhook, eklendiği andan sonrasını gönderir).
    teslim = "bekliyor" if ayar(c, "webhook_url") else "webhook yok"
    cur = c.execute("INSERT INTO olay (olay, zaman, veri, teslim) VALUES (?, ?, ?, ?)",
                    (govde["event"], govde["timestamp"], json.dumps(govde, ensure_ascii=False), teslim))
    return cur.lastrowid
