"""Mini CRM'in gerçek ekran görüntüsü (Playwright + Chromium). Website Yapımı 101 lab aracının uyarlaması.

Kullanım (lab klasöründen; Mini CRM açık olmalı):
    uv run --group araclar python araclar/ekran.py <ders> <ad> <adres> [--mobil] [--tam]

Örnek:
    uv run --group araclar python araclar/ekran.py 2.1 satis-hatti http://localhost:8060/firsatlar

Python içinden (sunucuyu kendisi açıp kapatır, ayrı bir veritabanıyla):
    from ekran import sunucu, tarayici_ac, yeni_sayfa, kaydet
    with sunucu("calisma/ekran.db", bugun="2026-09-25") as adres, tarayici_ac() as t:
        s = yeni_sayfa(t); s.goto(adres + "/rapor"); kaydet(s, "3.1", "rapor")

- Masaüstü: 1280×800 görüş alanı. Mobil: 390×844 (dikey telefon, cihaz ölçeği 1).
- Yazı tipleri ve görseller yüklenmeden çekilmez; `--tam` tüm sayfa boyunu çeker.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ortak import LAB, MASAUSTU, MOBIL, ekran_yolu  # noqa: E402


def port_acik(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def sunucu(db: str = "calisma/ekran.db", bugun: str = "2026-09-25", port: int = 8070, sifirla: bool = True):
    """Mini CRM'i ayrı bir veritabanı ve portla açar (öğrencinin 8060'ına dokunmaz), çıkışta kapatır."""
    if port_acik(port):
        raise RuntimeError(f"{port} portu dolu — önce oradaki sunucuyu durdurun.")
    komut = [sys.executable, "-m", "mini_crm.sunucu", "--port", str(port), "--db", db, "--bugun", bugun, "--sessiz"]
    if sifirla:
        komut.append("--sifirla")
    s = subprocess.Popen(komut, cwd=LAB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        for _ in range(100):
            if port_acik(port):
                break
            if s.poll() is not None:
                raise RuntimeError(f"Mini CRM kapandı (kod {s.returncode})")
            time.sleep(0.1)
        yield f"http://localhost:{port}"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(s.pid, signal.SIGINT)
        try:
            s.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(s.pid, signal.SIGKILL)


@contextlib.contextmanager
def tarayici_ac():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # Tam Chromium + Türkçe dil ortamı: tarih kutusu (29.09.2026) ve dosya seçici ("Dosya Seç") Türkçe görünsün.
        # (Başsız "headless shell" dil paketlerini yüklemez; öğrencinin Türkçe tarayıcısında görünen bu.)
        t = p.chromium.launch(channel="chromium", args=["--lang=tr"],
                              env={**os.environ, "LANGUAGE": "tr", "LANG": "tr_TR.UTF-8", "LC_ALL": "tr_TR.UTF-8"})
        try:
            yield t
        finally:
            t.close()


def yeni_sayfa(tarayici, mobil: bool = False):
    if mobil:
        return tarayici.new_page(viewport=MOBIL, device_scale_factor=1, is_mobile=True, has_touch=True,
                                 locale="tr-TR", reduced_motion="reduce")
    return tarayici.new_page(viewport=MASAUSTU, locale="tr-TR", reduced_motion="reduce")


def kaydet(sayfa, ders: str, ad: str, tam: bool = False) -> Path:
    sayfa.evaluate("document.fonts.ready.then(() => true)")
    sayfa.wait_for_timeout(150)
    yol = ekran_yolu(ders, ad)
    sayfa.screenshot(path=str(yol), full_page=tam)
    print(yol.relative_to(LAB))
    return yol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ders")
    ap.add_argument("ad")
    ap.add_argument("adres")
    ap.add_argument("--mobil", action="store_true")
    ap.add_argument("--tam", action="store_true")
    a = ap.parse_args()
    with tarayici_ac() as t:
        s = yeni_sayfa(t, a.mobil)
        s.goto(a.adres, wait_until="networkidle")
        kaydet(s, a.ders, a.ad, a.tam)


if __name__ == "__main__":
    main()
