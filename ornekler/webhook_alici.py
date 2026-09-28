"""Ders 4.1 — Mini CRM'den gelen olayları dinleyen küçük bir alıcı (n8n Webhook düğümünün yaptığı işin özü).

Her isteğin imzasını doğrular: HMAC-SHA256(sır, "zaman:gövde") == X-MiniCRM-Imza ?
İmza doğruysa 200 döner ve olayı ekrana yazar; yanlışsa 401 döner (Mini CRM teslimi "hata" diye kaydeder).

    uv run python ornekler/webhook_alici.py                  # 127.0.0.1:8061, sır Mini CRM veritabanından okunur
    uv run python ornekler/webhook_alici.py --sir yanlis     # negatif deneme: imza tutmaz → 401

Sonra Mini CRM → Otomasyon → Webhook adresi: http://localhost:8061/mini-crm
Not: sırrı veritabanından okumak yalnız bu lab'ın kolaylığıdır. Gerçekte sır, iki tarafa elle ve gizli girilir.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent


class Alici(BaseHTTPRequestHandler):
    sir = ""

    def log_message(self, *_):
        pass

    def do_POST(self):
        govde = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        zaman = self.headers.get("X-MiniCRM-Zaman", "")
        gelen = self.headers.get("X-MiniCRM-Imza", "")
        beklenen = hmac.new(self.sir.encode(), f"{zaman}:".encode() + govde, hashlib.sha256).hexdigest()
        dogru = hmac.compare_digest(gelen, beklenen)
        saat = datetime.now().strftime("%H:%M:%S")
        try:
            olay = json.loads(govde)
        except json.JSONDecodeError:
            olay = {}
        veri = olay.get("data", {})
        ozet = veri.get("ad") or f'{veri.get("ad", "")} {veri.get("soyad", "")}'.strip() or veri.get("baslik", "")
        if "asama" in veri and "onceki_asama" in veri:
            ozet += f' · {veri["onceki_asama"]} → {veri["asama"]}'
        print(f"[{saat}] {olay.get('event', '?'):<22} imza {'DOĞRU ' if dogru else 'YANLIŞ'} · {ozet}", flush=True)
        kod = 200 if dogru else 401
        yanit = b'{"alindi": true}' if dogru else b'{"hata": "imza tutmadi"}'
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(yanit)))
        self.end_headers()
        self.wfile.write(yanit)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8061)
    ap.add_argument("--sir", help="imza sırrı (verilmezse Mini CRM veritabanından okunur)")
    ap.add_argument("--db", type=Path, default=LAB / "calisma" / "mini-crm.db")
    a = ap.parse_args()
    if a.sir is None:
        yol = a.db if a.db.is_absolute() else LAB / a.db
        with sqlite3.connect(yol) as c:
            a.sir = c.execute("SELECT deger FROM ayar WHERE anahtar = 'webhook_sirri'").fetchone()[0]
    Alici.sir = a.sir
    print(f"Alıcı dinliyor: http://localhost:{a.port}/mini-crm  (Ctrl+C ile durur)", flush=True)
    try:
        HTTPServer(("127.0.0.1", a.port), Alici).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
