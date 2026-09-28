"""Bütün ders ekranlarını GERÇEK Mini CRM üzerinde üretir (lab/ekran/<ders>/).

    uv run --group araclar python araclar/ekranlari_uret.py            # hepsi
    uv run --group araclar python araclar/ekranlari_uret.py 2.2 4.1    # yalnız bu dersler (sıra bağımlı adımlar yine çalışır)

Mini CRM ayrı bir veritabanıyla (calisma/ekran.db, bugün = 2026-09-25) 8070 portunda açılır,
öğrencinin 8060'ına dokunulmaz. Adımlar sırayla yapılır: önce ilk kurulum ekranları, sonra
değişiklik gerektirenler (içe aktarma, aşama değiştirme, webhook, KVKK başvurusu).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ekran import kaydet, sunucu, tarayici_ac, yeni_sayfa  # noqa: E402
from ortak import LAB, ekran_yolu  # noqa: E402

GUN = "2026-09-25"
PORT = 8070
ALICI_PORT = 8071
DB = "calisma/ekran.db"
SECILI = set(sys.argv[1:])


def istenen(ders: str) -> bool:
    return not SECILI or ders in SECILI


def terminal_komut(ders: str, ad: str, komut: str, klasor: str = ".", bekle: str = "", sure: float = 0) -> None:
    """terminal.py'yi ayrı süreçte çalıştırır (komut gerçekten çalışır, çıktı .txt + .png)."""
    ek = (["--bekle", bekle] if bekle else []) + (["--sure", str(sure)] if sure else [])
    subprocess.run([sys.executable, str(LAB / "araclar" / "terminal.py"), ders, ad, "-C", klasor, *ek, "--", *komut.split()],
                   cwd=LAB, check=False)


def main() -> None:
    with sunucu(DB, GUN, PORT) as adres, tarayici_ac() as t:
        s = yeni_sayfa(t)

        def git(yol: str) -> None:
            s.goto(adres + yol, wait_until="networkidle")

        # ------------------------------------------------ ilk kurulum ekranları
        if istenen("1.1"):
            git("/"); kaydet(s, "1.1", "pano")
        if istenen("1.2"):
            git("/sirket/2"); kaydet(s, "1.2", "sirket-demir-mobilya")
            git("/firsat/24"); kaydet(s, "1.2", "firsat-konut-katalogu")
            git("/kisiler"); kaydet(s, "1.2", "kisiler")
        if istenen("2.1"):
            git("/firsatlar"); kaydet(s, "2.1", "satis-hatti")
            git("/firsatlar?gorunum=tablo"); kaydet(s, "2.1", "satis-hatti-tablo")
        if istenen("2.3"):
            git("/gorevler"); kaydet(s, "2.3", "gorevler")
        if istenen("2.4"):
            git("/sablonlar"); kaydet(s, "2.4", "sablonlar")
            git("/sablon/1?kisi=1&firsat=21"); kaydet(s, "2.4", "sablon-takip-onizleme")
            git("/sablon/2?kisi=2"); kaydet(s, "2.4", "sablon-tanitim-izin-yok")
        if istenen("3.1"):
            git("/rapor"); kaydet(s, "3.1", "rapor")
            git("/rapor?sahip=1"); kaydet(s, "3.1", "rapor-ayse")
            with s.expect_download() as indir:
                s.click("text=Fırsatları CSV indir")
            hedef = ekran_yolu("3.1", "mini-crm-firsat", ".csv")
            indir.value.save_as(hedef)
            terminal_komut("3.1", "firsat-csv", "head -n 6 mini-crm-firsat.csv", "ekran/3.1")
        if istenen("3.2"):
            git("/rapor#huni"); s.locator("#huni").scroll_into_view_if_needed(); kaydet(s, "3.2", "rapor-huni")
            terminal_komut("3.2", "rapor-dogrula", f"uv run python dogrula/rapor_dogrula.py --adres http://localhost:{PORT} --ozet")
            terminal_komut("3.2", "rapor-dogrula-tam", f"uv run python dogrula/rapor_dogrula.py --adres http://localhost:{PORT} --beklenen")
            terminal_komut("3.2", "rapor-dogrula-bozuk", f"uv run python dogrula/rapor_dogrula.py --adres http://localhost:{PORT} --bozuk --ozet")
        if istenen("3.3"):
            git("/rapor"); s.locator("#kaynak").scroll_into_view_if_needed(); kaydet(s, "3.3", "rapor-kayip-kaynak")
        if istenen("3.4"):
            git("/"); kaydet(s, "3.4", "pano-tam", tam=True)
        if istenen("4.4") or istenen("1.3"):
            git("/denetim"); kaydet(s, "4.4", "veri-denetimi")
        if istenen("4.2"):
            git("/kisi/4"); kaydet(s, "4.2", "kisi-izin-bilinmiyor")
        if istenen("4.3"):
            git("/ekip"); kaydet(s, "4.3", "ekip")
            git("/firsatlar?sahip=2"); kaydet(s, "4.3", "satis-hatti-deniz")

        # ------------------------------------------------ değişiklik gerektirenler
        if istenen("1.3"):
            git("/kisi/yeni")
            s.fill("#ad", "Elif"); s.fill("#soyad", "Örnek"); s.fill("#eposta", "elif@lale-kafe.example.com")
            s.click("main form button"); s.wait_for_load_state("networkidle")
            kaydet(s, "1.3", "kisi-yinelenen-eposta")
        if istenen("1.4"):
            terminal_komut("1.4", "csv-hatali-dosya", "cat veri/ice-aktar/kisiler-hatali.csv")
            git("/ice-aktar")
            s.select_option("#nesne", "kisi"); s.set_input_files("#dosya", str(LAB / "veri/ice-aktar/kisiler-hatali.csv"))
            s.click("text=Yükle ve denetle"); s.wait_for_load_state("networkidle")
            kaydet(s, "1.4", "ice-aktar-hatali")
            kaydet(s, "1.4", "ice-aktar-hatali-tam", tam=True)
            git("/ice-aktar")
            s.select_option("#nesne", "kisi"); s.set_input_files("#dosya", str(LAB / "veri/ice-aktar/kisiler-duzeltilmis.csv"))
            s.click("text=Yükle ve denetle"); s.wait_for_load_state("networkidle")
            kaydet(s, "1.4", "ice-aktar-duzeltilmis")
            s.click("text=kaydı içe aktar"); s.wait_for_load_state("networkidle")
            kaydet(s, "1.4", "ice-aktar-sonuc")
        if istenen("2.2"):
            git("/firsatlar")
            with s.expect_navigation(wait_until="networkidle"):
                s.locator('.fkart[data-id="13"]').drag_to(s.locator('.kolon[data-asama="nitelikli"]'))
            kaydet(s, "2.2", "surukle-birak-sonrasi")
            git("/firsat/22?kaybet=1"); kaydet(s, "2.2", "kaybedildi-neden-sor")
            s.select_option("#kayip_nedeni", "Fiyat yüksek"); s.click("text=Kaybedildi olarak işaretle")
            s.wait_for_load_state("networkidle"); kaydet(s, "2.2", "kaybedildi-sonrasi")
        if istenen("2.3"):
            git("/firsat/20")
            s.fill("#baslik", "Broşür için numune kâğıtları götür"); s.fill("#son_tarih", "2026-09-29")
            s.click("text=Ekle"); s.wait_for_load_state("networkidle")
            kaydet(s, "2.3", "firsat-gorev-eklendi")
        if istenen("4.1"):
            alici = subprocess.Popen([sys.executable, "ornekler/webhook_alici.py", "--port", str(ALICI_PORT), "--db", DB],
                                     cwd=LAB, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            time.sleep(1.2)
            git("/otomasyon"); s.fill("#webhook_url", f"http://localhost:{ALICI_PORT}/mini-crm")
            s.click('form[action="/otomasyon/webhook"] button'); s.wait_for_load_state("networkidle")
            git("/firsat/24"); s.click("form button:has-text('Kazanıldı')"); s.wait_for_load_state("networkidle")
            kaydet(s, "4.1", "kazanildi-kural-calisti")
            with urllib.request.urlopen(adres + "/api/olaylar") as y:
                olaylar = json.load(y)
            oid = max(o["id"] for o in olaylar if o["olay"] == "opportunity.updated")
            git("/otomasyon"); kaydet(s, "4.1", "otomasyon")
            git(f"/otomasyon?olay={oid}"); s.locator("#olay").scroll_into_view_if_needed(); kaydet(s, "4.1", "olay-govdesi")
            time.sleep(0.5)
            os.killpg(alici.pid, signal.SIGINT)
            cikti, _ = alici.communicate(timeout=10)
            txt = ekran_yolu("4.1", "webhook-alici", ".txt")
            txt.write_text(f"~/lab $ uv run python ornekler/webhook_alici.py\n{cikti.strip()}\n^C\n", encoding="utf-8")
            subprocess.run([sys.executable, str(LAB / "araclar" / "terminal.py"), "--ciz", str(txt)], cwd=LAB, check=False)
            git("/otomasyon"); s.fill("#webhook_url", ""); s.click('form[action="/otomasyon/webhook"] button'); s.wait_for_load_state("networkidle")
        if istenen("4.2"):
            git("/kvkk")
            s.select_option("#kisi_id", "2"); s.select_option("#tur", "silme")
            s.click("text=Başvuruyu kaydet"); s.wait_for_load_state("networkidle")
            kaydet(s, "4.2", "kvkk")
            kaydet(s, "4.2", "kvkk-tam", tam=True)


if __name__ == "__main__":
    main()
    if not SECILI or "1.1" in SECILI:
        # 1.1: öğrencinin ilk komutu. Öğrenci veritabanı yoksa önce kurulum satırı görünür.
        (LAB / "calisma" / "mini-crm.db").unlink(missing_ok=True)
        terminal_komut("1.1", "mini-crm-ac", "uv run python -m mini_crm.sunucu", bekle="Mini CRM açık", sure=30)
