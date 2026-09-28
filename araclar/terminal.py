"""Bir komutu GERÇEKTEN çalıştırır, çıktısını ham .txt olarak saklar ve 740×462 terminal görüntüsü çizer.

(Website Yapımı 101 lab'ındaki araçla aynıdır; yalnız örnekler bu lab'a göre.)

Kullanım (lab klasöründen):
    uv run --group araclar python araclar/terminal.py <ders> <ad> [-C klasör] [--bekle DESEN] [--sure SN] -- <komut ...>
    uv run --group araclar python araclar/terminal.py --ciz ekran/3.2/rapor-dogrula.txt      # yalnız yeniden çiz

Örnekler:
    ... terminal.py 3.2 rapor-dogrula -- uv run python dogrula/rapor_dogrula.py --beklenen
    ... terminal.py 1.1 mini-crm-ac --bekle "Mini CRM açık" --sure 20 -- uv run python -m mini_crm.sunucu --port 8070

- Komut verilen klasörde çalışır; stdout+stderr geldiği sırayla yakalanır.
- `--bekle DESEN`: çıktıda desen görülünce 1 sn daha bekler, sonra komutu Ctrl+C (SIGINT) ile durdurur.
  `--sure`: en fazla bu kadar saniye bekler (sonra yine SIGINT). Uzun süre çalışan sunucular için.
- Renk kodları ve imleç hareketleri küçük bir terminal öykünücüsüyle ekranda son görünen hâline
  indirgenir; metnin kendisi değişmez.
- Tek düzeltme: lab klasörünün mutlak yolu `~/lab` olarak kısaltılır (istem satırıyla tutarlı).
- Ham çıktı: lab/ekran/<ders>/<ad>.txt (ilk satır istem satırıdır). Görüntü: aynı adla .png
"""

from __future__ import annotations

import argparse
import html
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ortak import FONT, LAB, TERMINAL, ekran_yolu  # noqa: E402

CSI = re.compile(r"\x1b\[([0-9;?]*)([ -/]*)([@-~])")
OSC = re.compile(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)")

SABLON = """<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><style>
@font-face {{ font-family: "T"; src: url("{f1}") format("woff2"); unicode-range: U+0000-00FF, U+0131, U+2000-206F, U+20AC, U+2212; }}
@font-face {{ font-family: "T"; src: url("{f2}") format("woff2"); unicode-range: U+0100-024F, U+1E00-1EFF; }}
html, body {{ margin: 0; width: {g}px; height: {y}px; background: #0f141f; overflow: hidden; }}
pre {{ margin: 0; padding: 16px 20px; height: 100%; box-sizing: border-box; overflow: hidden; white-space: pre-wrap;
  word-break: break-word; font: {b}px/{lh} "T", "DejaVu Sans Mono", monospace; font-variant-ligatures: none; color: #d6dbe6; }}
.k {{ color: #7ee2a8; }} .i {{ color: #7aa2f7; }} .n {{ color: #8b94a8; font-size: {nb}px; }}
</style></head><body><pre id="e">{not_}<span class="i">{istem} $</span> <span class="k">{komut}</span>
{cikti}<span class="i">{istem} $</span> ▍</pre></body></html>"""


def oykunle(ham: str) -> str:
    """ANSI renk/imleç kodlarını işleyip ekranda son görünen metni döndürür."""
    ham = OSC.sub("", ham).replace("\r\n", "\n")
    satirlar: list[list[str]] = [[]]
    r = c = 0
    i = 0
    while i < len(ham):
        ch = ham[i]
        if ch == "\x1b":
            m = CSI.match(ham, i)
            if m:
                parm, _, kom = m.groups()
                n = int(parm) if parm.isdigit() else 1
                if kom == "A":
                    r = max(0, r - n)
                elif kom == "B":
                    r += n
                elif kom == "G":
                    c = (int(parm) - 1) if parm.isdigit() else 0
                elif kom == "K":
                    while len(satirlar) <= r:
                        satirlar.append([])
                    if parm == "2":
                        satirlar[r] = []
                    elif parm in ("", "0"):
                        del satirlar[r][c:]
                elif kom == "J" and parm in ("", "0"):
                    del satirlar[r + 1:]
                    del satirlar[r][c:]
                i = m.end()
                continue
            i += 1
            continue
        if ch == "\n":
            r += 1
            c = 0
        elif ch == "\r":
            c = 0
        elif ch == "\b":
            c = max(0, c - 1)
        elif ch >= " " or ch == "\t":
            while len(satirlar) <= r:
                satirlar.append([])
            satir = satirlar[r]
            while len(satir) < c:
                satir.append(" ")
            if c < len(satir):
                satir[c] = ch
            else:
                satir.append(ch)
            c += 1
        i += 1
        while len(satirlar) <= r:
            satirlar.append([])
    metin = "\n".join("".join(s).rstrip() for s in satirlar)
    return metin.strip("\n")


AJAN_DEGISKENLERI = re.compile(
    r"^(AI_AGENT|AGENT|CLAUDECODE|CLAUDE_.*|CODEX_.*|GEMINI_CLI|OPENCODE.*|CURSOR_TRACE_ID|AUGMENT_AGENT|"
    r"AMP_CURRENT_THREAD_ID|ANTIGRAVITY_.*|QWEN_CODE|CRUSH|AIDER_.*|VSCODE_AGENT_FOLDER|REPLIT_MODE|REPL_ID)$")


def ogrenci_ortami() -> dict[str, str]:
    """Öğrencinin normal terminalindeki ortamı taklit eder.

    Astro 7 (am-i-vibing paketiyle) bir yapay zekâ ajanı tarafından çalıştırıldığını anlarsa
    `astro dev` sunucusunu arka plana atar ve JSON günlük basar. Öğrencinin göreceği çıktı bu değildir;
    bu yüzden ajan ortam değişkenlerini temizleyip komutu sıradan bir terminaldeki gibi çalıştırırız.
    """
    ortam = {k: v for k, v in os.environ.items() if not AJAN_DEGISKENLERI.match(k)}
    ortam.setdefault("TERM", "xterm-256color")
    return ortam


def calistir(komut: list[str], klasor: Path, bekle: str | None, sure: float | None) -> tuple[str, int]:
    ortam = ogrenci_ortami()
    for p in list(komut):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", p):
            k, v = p.split("=", 1)
            ortam[k] = v
            komut = komut[1:]
        else:
            break
    s = subprocess.Popen(komut, cwd=klasor, env=ortam, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    parcalar: list[bytes] = []

    def oku() -> None:
        assert s.stdout
        for parca in iter(lambda: s.stdout.read1(4096), b""):
            parcalar.append(parca)

    t = threading.Thread(target=oku, daemon=True)
    t.start()
    baslangic = time.time()
    uzun = bekle is not None or sure is not None
    goruldu = None
    while s.poll() is None:
        time.sleep(0.2)
        if not uzun:
            continue
        metin = oykunle(b"".join(parcalar).decode("utf-8", "replace"))
        if bekle and goruldu is None and re.search(bekle, metin):
            goruldu = time.time()
        if (goruldu and time.time() - goruldu > 1.0) or (sure and time.time() - baslangic > sure):
            os.killpg(s.pid, signal.SIGINT)
            try:
                s.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(s.pid, signal.SIGKILL)
            break
    s.wait()
    t.join(timeout=5)
    ham = b"".join(parcalar).decode("utf-8", "replace")
    return oykunle(ham), s.returncode


def ciz(txt: Path) -> Path:
    from playwright.sync_api import sync_playwright

    satir = txt.read_text(encoding="utf-8").rstrip("\n").split("\n")
    istem, komut = satir[0].split(" $ ", 1)
    cikti = satir[1:]
    png = txt.with_suffix(".png")
    with sync_playwright() as p, tempfile.TemporaryDirectory() as gd:
        tarayici = p.chromium.launch()
        s = tarayici.new_page(viewport=TERMINAL)
        f = Path(gd) / "t.html"
        lh = 1.42

        def dene(b: int, gizli: int) -> bool:
            not_ = f'<span class="n">… ilk {gizli} satır sığmadı (tamamı {txt.name})</span>\n' if gizli else ""
            f.write_text(SABLON.format(
                f1=(FONT / "jetbrains-mono-400-latin.woff2").as_uri(),
                f2=(FONT / "jetbrains-mono-400-latin-ext.woff2").as_uri(),
                g=TERMINAL["width"], y=TERMINAL["height"], b=b, lh=lh, nb=max(12, b - 4),
                istem=html.escape(istem), komut=html.escape(komut), not_=not_,
                cikti="".join(html.escape(x) + "\n" for x in cikti[gizli:])), encoding="utf-8")
            s.goto(f.as_uri())
            s.evaluate("document.fonts.ready.then(() => true)")
            return s.evaluate("(() => { const e = document.getElementById('e'); return e.scrollHeight <= e.clientHeight; })()")

        b, gizli = 20, 0
        while not dene(b, gizli):
            if b > 14:
                b -= 1
            elif lh > 1.2:
                lh = 1.2
            elif gizli < len(cikti):
                gizli += 1
            else:
                break
        s.screenshot(path=str(png))
        tarayici.close()
    print(f"{png.relative_to(LAB)} · {b}px{f' · ilk {gizli} satır gizli' if gizli else ''}")
    return png


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--ciz":
        for yol in sys.argv[2:]:
            ciz(Path(yol).resolve())
        return 0
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    ayrac = sys.argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("ders")
    ap.add_argument("ad")
    ap.add_argument("-C", dest="klasor", default=".")
    ap.add_argument("--bekle")
    ap.add_argument("--sure", type=float)
    a = ap.parse_args(sys.argv[1:ayrac])
    komut = sys.argv[ayrac + 1:]
    klasor = (LAB / a.klasor).resolve()
    cikti, kod = calistir(komut, klasor, a.bekle, a.sure)
    cikti = cikti.replace(str(LAB), "~/lab")
    alt = klasor.relative_to(LAB).as_posix()
    istem = "~/lab" if alt == "." else f"~/lab/{alt}"
    txt = ekran_yolu(a.ders, a.ad, ".txt")
    txt.write_text(f"{istem} $ {' '.join(komut)}\n{cikti}\n", encoding="utf-8")
    ciz(txt)
    print(f"çıkış kodu: {kod}")
    # Uzun süreli komutları biz durdurduk (SIGINT); onların kodu hata sayılmaz.
    return 0 if (a.bekle or a.sure) else kod


if __name__ == "__main__":
    sys.exit(main())
