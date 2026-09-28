"""Otomasyon: tetikleyici → koşul → eylem kuralları ve dışarıya olay gönderimi (webhook).

İki katman vardır (ders 4.1):
1. CRM içi kural: fırsat aşaması değişince görev açmak gibi. Burada, veritabanında çalışır.
2. Dışarıya olay: her kayıt değişikliği 'olay' tablosuna yazılır. Ayarlarda bir webhook adresi
   varsa (ör. bir n8n Webhook düğümünün adresi) olay oraya HTTP POST ile gönderilir.
   Gövde Twenty'nin biçimine benzer: {"event", "data", "timestamp"}.
   İmza: X-MiniCRM-Imza = HMAC-SHA256(sır, "{zaman}:{gövde}"), X-MiniCRM-Zaman = zaman.
   Alıcı aynı hesabı yapıp imzayı karşılaştırır (ornekler/webhook_alici.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import urllib.error
import urllib.request
from datetime import date, timedelta

from . import db


def imzala(sir: str, zaman: str, govde: bytes) -> str:
    return hmac.new(sir.encode(), f"{zaman}:".encode() + govde, hashlib.sha256).hexdigest()


def asama_degisti(c: sqlite3.Connection, firsat: dict, yeni: str, bugun: date) -> list[str]:
    """Aşama değişikliğinde etkin kuralları çalıştırır; yapılanları insan diliyle döndürür."""
    yapilan = []
    kurallar = {r["id"]: r for r in c.execute("SELECT * FROM kural WHERE aktif = 1")}
    plan = []
    if 1 in kurallar and yeni == "kazanildi":
        plan.append(("Teslimat ve fatura", 3, kurallar[1]["ad"]))
    if 2 in kurallar and yeni == "teklif":
        plan.append(("Teklifi takip et", 2, kurallar[2]["ad"]))
    for baslik, gun, kural_adi in plan:
        son = (bugun + timedelta(days=gun)).isoformat()
        cur = c.execute("INSERT INTO gorev (baslik, firsat_id, sahip_id, son_tarih, durum, olusturma, kaynak)"
                        " VALUES (?, ?, ?, ?, 'acik', ?, ?)",
                        (baslik, firsat["id"], firsat["sahip_id"], son, bugun.isoformat(), f"kural: {kural_adi}"))
        db.olay_yaz(c, "gorev", "created", cur.lastrowid)
        yapilan.append(f"Kural “{kural_adi}” çalıştı: “{baslik}” görevi açıldı (son tarih {son}).")
    return yapilan


def gonder(c: sqlite3.Connection, zaman_asimi: float = 3.0) -> list[dict]:
    """Bekleyen olayları ayarlı webhook adresine gönderir. Adres boşsa hiçbir şey yapmaz."""
    url = db.ayar(c, "webhook_url").strip()
    if not url:
        return []
    sir = db.ayar(c, "webhook_sirri")
    sonuc = []
    for r in c.execute("SELECT id, zaman, veri FROM olay WHERE teslim = 'bekliyor' ORDER BY id").fetchall():
        govde = r["veri"].encode("utf-8")
        istek = urllib.request.Request(url, data=govde, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-MiniCRM-Zaman": r["zaman"],
            "X-MiniCRM-Imza": imzala(sir, r["zaman"], govde),
            "User-Agent": "MiniCRM-ders/1.0",
        })
        try:
            with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
                durum = f"teslim edildi (HTTP {yanit.status})"
        except urllib.error.HTTPError as h:
            durum = f"hata (HTTP {h.code})"
        except (urllib.error.URLError, TimeoutError, OSError) as h:
            durum = f"hata ({getattr(h, 'reason', h)})"
        c.execute("UPDATE olay SET teslim = ? WHERE id = ?", (durum, r["id"]))
        sonuc.append({"id": r["id"], "durum": durum})
    c.commit()
    return sonuc


def olay_ornegi(c: sqlite3.Connection, olay_id: int) -> dict | None:
    r = c.execute("SELECT * FROM olay WHERE id = ?", (olay_id,)).fetchone()
    return json.loads(r["veri"]) if r else None
