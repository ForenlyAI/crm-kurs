"""Rapor sayılarını Mini CRM'in kodunu KULLANMADAN yeniden hesaplar ve karşılaştırır.

Öğrencinin hesap tablosunda yaptığı işin aynısı: dışa aktarılan CSV'leri okur, sayar, böler.
Mini CRM'in /api/rapor çıktısıyla karşılaştırır. Bir fark varsa KALDI der ve 1 ile çıkar.

    uv run python dogrula/rapor_dogrula.py                       # http://localhost:8060
    uv run python dogrula/rapor_dogrula.py --beklenen            # + ilk kurulumdaki elle hesaplanmış sayılar
    uv run python dogrula/rapor_dogrula.py --bozuk               # negatif test: CSV'de bir satırı bozar, KALDI beklenir

Aşama olasılıkları burada ayrıca yazılıdır (Yeni 10, Nitelikli 25, Görüşme 40, Teklif 60, Pazarlık 80);
bu değerler Twenty'nin "Show Expected Amount" belgesindeki örnek tabloyla aynıdır.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date

ACIK = ["Yeni", "Nitelikli", "Görüşme", "Teklif", "Pazarlık"]
OLASILIK = {"Yeni": 10, "Nitelikli": 25, "Görüşme": 40, "Teklif": 60, "Pazarlık": 80}
SIRA = {a: i for i, a in enumerate(ACIK + ["Kazanıldı"])}

ETIKET = {
    "acik_sayi": "açık fırsat sayısı", "acik_tutar": "açık hat (TL)", "agirlikli_tutar": "ağırlıklı değer (TL)",
    "kazanilan_sayi": "kazanılan sayısı", "kaybedilen_sayi": "kaybedilen sayısı", "kazanma_orani": "kazanma oranı",
    "kazanilan_tutar": "kazanılan tutar (TL)", "ortalama_satis_suresi_gun": "ort. satış süresi (gün)",
}

# İlk kurulumdaki (veri/ornek-veri.json) sayılar, elle hesaplandı — 2026-09-25
BEKLENEN = {
    "acik_sayi": 12, "acik_tutar": 240800, "agirlikli_tutar": 128805,
    "kazanilan_sayi": 6, "kaybedilen_sayi": 6, "kazanma_orani": 0.5, "kazanilan_tutar": 171800,
    "ortalama_satis_suresi_gun": 26.67,
    "huni": [24, 21, 17, 13, 9, 6],
    "kayip:Fiyat yüksek": 3,
}


def al(adres: str) -> str:
    with urllib.request.urlopen(adres, timeout=10) as y:
        return y.read().decode("utf-8")


def hesapla(firsatlar: list[dict], gecmis: list[dict]) -> dict:
    g = defaultdict(list)
    for r in gecmis:
        g[int(r["firsat_id"])].append(r["asama"])
    acik = [f for f in firsatlar if f["asama"] in ACIK]
    kaz = [f for f in firsatlar if f["asama"] == "Kazanıldı"]
    kay = [f for f in firsatlar if f["asama"] == "Kaybedildi"]
    ileri = []
    for f in firsatlar:
        gorulen = [SIRA[a] for a in g[int(f["id"])] if a in SIRA]
        if f["asama"] in SIRA:
            gorulen.append(SIRA[f["asama"]])
        ileri.append(max(gorulen) if gorulen else 0)
    huni = [sum(1 for x in ileri if x >= i) for i in range(len(SIRA))]
    sureler = [(date.fromisoformat(f["kazanilma_tarihi"]) - date.fromisoformat(f["olusturma"])).days
               for f in kaz if f["kazanilma_tarihi"]]
    kaynak = defaultdict(lambda: [0, 0])
    for f in kaz:
        kaynak[f["kaynak"]][0] += 1
    for f in kay:
        kaynak[f["kaynak"]][1] += 1
    return {
        "acik_sayi": len(acik),
        "acik_tutar": sum(int(f["tutar"]) for f in acik),
        "agirlikli_tutar": sum(int(f["tutar"]) * OLASILIK[f["asama"]] / 100 for f in acik),
        "kazanilan_sayi": len(kaz),
        "kaybedilen_sayi": len(kay),
        "kazanma_orani": len(kaz) / (len(kaz) + len(kay)) if kaz or kay else None,
        "kazanilan_tutar": sum(int(f["tutar"]) for f in kaz),
        "ortalama_satis_suresi_gun": sum(sureler) / len(sureler) if sureler else None,
        "huni": huni,
        "gecis": [huni[i + 1] / huni[i] if huni[i] else None for i in range(len(huni) - 1)],
        "kayip": Counter(f["kayip_nedeni"] for f in kay),
        "kaynak_orani": {k: v[0] / (v[0] + v[1]) for k, v in kaynak.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adres", default="http://localhost:8060")
    ap.add_argument("--beklenen", action="store_true", help="ilk kurulumun elle hesaplanmış sayılarıyla da karşılaştır")
    ap.add_argument("--bozuk", action="store_true", help="negatif test: kazanılan ilk fırsatı kaybedilmiş say")
    ap.add_argument("--ozet", action="store_true", help="yalnız farklı satırları ve ana oranları yaz (hepsi yine karşılaştırılır)")
    a = ap.parse_args()

    firsatlar = list(csv.DictReader(io.StringIO(al(a.adres + "/disa-aktar/firsat.csv"))))
    gecmis = list(csv.DictReader(io.StringIO(al(a.adres + "/disa-aktar/asama_gecmisi.csv"))))
    crm = json.loads(al(a.adres + "/api/rapor"))
    if a.bozuk:
        for f in firsatlar:
            if f["asama"] == "Kazanıldı":
                f["asama"], f["kayip_nedeni"] = "Kaybedildi", "Fiyat yüksek"
                print(f"NEGATİF TEST: fırsat #{f['id']} CSV'de Kaybedildi yapıldı — farklar görünmeli\n")
                break
    b = hesapla(firsatlar, gecmis)

    satirlar: list[tuple[str, object, object]] = []
    for k, etiket in ETIKET.items():
        satirlar.append((etiket, b[k], crm[k]))
    for i, h in enumerate(crm["huni"]):
        satirlar.append((f"ulaşan: {h['ad']}", b["huni"][i], h["ulasan"]))
        if h["gecis_orani"] is not None:
            satirlar.append((f"geçiş: {h['ad']} →", b["gecis"][i], h["gecis_orani"]))
    for n in crm["kayip_nedenleri"]:
        satirlar.append((f"kayıp: {n['neden']}", b["kayip"].get(n["neden"], 0), n["sayi"]))
    for k in crm["kaynaklar"]:
        if k["kazanma_orani"] is not None:
            satirlar.append((f"kazanma: {k['ad']}", b["kaynak_orani"].get(k["ad"]), k["kazanma_orani"]))

    def esit(x, y) -> bool:
        if x is None or y is None:
            return x is None and y is None
        return abs(float(x) - float(y)) < 0.006   # CRM oranları 4, ortalamaları 2 basamağa yuvarlar

    def goster(v) -> str:   # Türkçe yazım: binlik ayırıcı nokta, ondalık virgül
        if v is None:
            return "—"
        if isinstance(v, float) and v < 1.5:
            s = f"{v:.4f}"
        elif isinstance(v, float):
            s = f"{v:,.2f}"
        else:
            s = f"{v:,}"
        return s.replace(",", "_").replace(".", ",").replace("_", ".")

    kalan = 0
    ana = tuple(ETIKET[k] for k in ("kazanma_orani", "kazanilan_sayi", "kaybedilen_sayi", "agirlikli_tutar"))
    print(f"{'ölçü':<28}{'CSV’den hesap':>15}{'Mini CRM':>13}  sonuç")
    for ad, x, y in satirlar:
        ok = esit(x, y)
        kalan += not ok
        if not a.ozet or not ok or ad in ana or ad.startswith("geçiş"):
            print(f"{ad:<28}{goster(x):>15}{goster(y):>13}  {'GEÇTİ' if ok else 'KALDI'}")
    if a.beklenen:
        print("\nelle hesaplanmış ilk kurulum sayıları:")
        for k, v in BEKLENEN.items():
            y = b["kayip"].get(k.split(":", 1)[1]) if k.startswith("kayip:") else b[k]
            ok = (y == v) if isinstance(v, list) else esit(y, v)
            kalan += not ok
            print(f"  {k:<26}{str(v):>22}  {'GEÇTİ' if ok else 'KALDI'}")
    print(f"\n{len(satirlar)} karşılaştırma · {'SONUÇ: GEÇTİ' if not kalan else f'SONUÇ: KALDI ({kalan} fark)'}")
    return 1 if kalan else 0


if __name__ == "__main__":
    sys.exit(main())
