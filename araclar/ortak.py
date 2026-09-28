"""Araçların ortak yolları ve görüş alanı ölçüleri (Website Yapımı 101 lab'ıyla aynı ölçüler)."""

from __future__ import annotations

from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
EKRAN = LAB / "ekran"
ARACLAR = LAB / "araclar"
FONT = ARACLAR / "fonts"

MASAUSTU = {"width": 1280, "height": 800}
MOBIL = {"width": 390, "height": 844}
TERMINAL = {"width": 740, "height": 462}


def ekran_yolu(ders: str, ad: str, uzanti: str = ".png") -> Path:
    """lab/ekran/<ders>/<ad>.png yolunu döndürür, klasörü oluşturur."""
    klasor = EKRAN / ders
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor / (ad if ad.endswith(uzanti) else f"{ad}{uzanti}")
