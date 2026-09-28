"""HTML yardımcıları: sayfa iskeleti, biçimlendirme (TL, yüzde, tarih)."""

from __future__ import annotations

import html
from urllib.parse import quote

e = lambda x: html.escape("" if x is None else str(x), quote=True)  # noqa: E731

MENU = [
    ("CRM", [("/", "Pano"), ("/firsatlar", "Satış hattı"), ("/kisiler", "Kişiler"), ("/sirketler", "Şirketler"),
             ("/gorevler", "Görevler")]),
    ("Ölçmek", [("/rapor", "Rapor"), ("/denetim", "Veri denetimi")]),
    ("Araçlar", [("/ice-aktar", "İçe aktar"), ("/disa-aktar", "Dışa aktar"), ("/sablonlar", "E-posta şablonları"),
                 ("/otomasyon", "Otomasyon"), ("/kvkk", "KVKK ve izin"), ("/ekip", "Ekip")]),
]
TEKIL = {"/firsatlar": "/firsat/", "/kisiler": "/kisi/", "/sirketler": "/sirket/", "/sablonlar": "/sablon/",
         "/gorevler": "/gorev/"}


def tl(n) -> str:
    if n is None or n == "":
        return "—"
    n = round(float(n))
    return f"{n:,.0f}".replace(",", ".") + " TL"


def yuzde(x) -> str:
    if x is None:
        return "—"
    v = round(x * 100, 1)
    s = f"{v:.1f}".replace(".", ",")
    return "%" + s.removesuffix(",0")


def tarih(t: str | None) -> str:
    if not t:
        return "—"
    y, a, g = t[:10].split("-")
    return f"{g}.{a}.{y}"


def yonlendir_adresi(yol: str, mesaj: str = "", tur: str = "") -> str:
    ayrac = "&" if "?" in yol else "?"
    if not mesaj:
        return yol
    return f"{yol}{ayrac}m={quote(mesaj)}" + (f"&mt={tur}" if tur else "")


def sayfa(baslik: str, govde: str, yol: str, isletme: str, kullanici: str, mesaj: str = "", mesaj_turu: str = "") -> str:
    menu = []
    for grup, ogeler in MENU:
        menu.append(f'<div class="grup">{e(grup)}</div>')
        for adres, ad in ogeler:
            tekil = TEKIL.get(adres, adres + "/")
            etkin = yol == adres or (adres != "/" and yol.startswith(tekil))
            nitelik = ' class="etkin" aria-current="page"' if etkin else ""
            menu.append(f'<a href="{adres}"{nitelik}>{e(ad)}</a>')
    m = f'<div class="mesaj {e(mesaj_turu)}" role="status">{e(mesaj)}</div>' if mesaj else ""
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(baslik)} · Mini CRM</title><link rel="stylesheet" href="/statik/stil.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%232458c6'/%3E%3C/svg%3E"></head>
<body>
<header class="ust"><a class="logo" href="/">Mini CRM<small>{e(isletme)}</small></a>
<span class="kullanici">Aktif kullanıcı: <b>{e(kullanici)}</b></span></header>
<div class="ornek">ÖRNEK VERİ · Bütün şirket, kişi, e-posta ve telefonlar uydurmadır. Mini CRM, CRM 101 kursunun alıştırma uygulamasıdır.</div>
<div class="duzen"><nav class="yan" aria-label="Ana menü">{''.join(menu)}</nav>
<main>{m}{govde}</main></div>
</body></html>"""


def secim(ad: str, secenekler: list[tuple], secili=None, bos: str | None = None, ek: str = "") -> str:
    o = [f'<option value="">{e(bos)}</option>'] if bos is not None else []
    for deger, etiket in secenekler:
        s = " selected" if str(deger) == str(secili) else ""
        o.append(f'<option value="{e(deger)}"{s}>{e(etiket)}</option>')
    return f'<select name="{e(ad)}" id="{e(ad)}"{ek}>{"".join(o)}</select>'


def alan(etiket: str, icerik: str, hata: str = "", kimlik: str = "") -> str:
    h = f'<div class="hata-yazi">{e(hata)}</div>' if hata else ""
    return f'<div class="alan{" hata" if hata else ""}"><label for="{e(kimlik)}">{e(etiket)}</label>{icerik}{h}</div>'


def girdi(ad: str, deger="", tur: str = "text", ek: str = "") -> str:
    return f'<input type="{tur}" name="{e(ad)}" id="{e(ad)}" value="{e(deger)}"{ek}>'


def cubuk(etiket: str, oran: float, sag: str, renk: str = "") -> str:
    w = max(0.0, min(1.0, oran)) * 100
    return (f'<div class="cubuk"><span>{e(etiket)}</span><div class="iz"><div class="dolu {renk}" style="width:{w:.1f}%"></div></div>'
            f'<span class="sag">{sag}</span></div>')
