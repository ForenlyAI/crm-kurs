"""Rapor ve pano sayıları. Her sayı burada, tek yerde hesaplanır; arayüz yalnız gösterir.

Tanımlar (SITE-HARITASI.md'de de yazılı):
- Kazanma oranı      = kazanılan / (kazanılan + kaybedilen). Açık fırsatlar paydaya girmez.
- Aşamaya ulaşan     = aşama geçmişinde o aşamaya ya da daha ilerisine varmış fırsat sayısı.
                       Atlanan aşama geçilmiş sayılır. Kazanılan fırsat bütün açık aşamaları geçmiştir.
                       Kaybedilen fırsat, kaybedilmeden önce vardığı son açık aşamaya kadar sayılır.
- Aşama geçiş oranı  = bir sonraki aşamaya ulaşan / bu aşamaya ulaşan.
- Ağırlıklı değer    = açık fırsatların tutar × aşama olasılığı toplamı.
- Satış süresi (gün) = fırsatın oluşturulduğu gün ile 'Kazanıldı'ya geçtiği gün arası.
- Bayat fırsat       = açık ve son güncellemesinin üzerinden en az 14 gün geçmiş.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date

BAYAT_GUN = 14


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


def firsatlari_al(c: sqlite3.Connection, sahip_id: int | None = None, baslangic: str = "", bitis: str = "") -> list[dict]:
    sql = "SELECT * FROM firsat WHERE 1 = 1"
    p: list = []
    if sahip_id:
        sql += " AND sahip_id = ?"
        p.append(sahip_id)
    if baslangic:
        sql += " AND olusturma >= ?"
        p.append(baslangic)
    if bitis:
        sql += " AND olusturma <= ?"
        p.append(bitis)
    firsatlar = [dict(r) for r in c.execute(sql + " ORDER BY id", p)]
    gecmis = defaultdict(list)
    for r in c.execute("SELECT firsat_id, asama, tarih FROM asama_gecmisi ORDER BY tarih, id"):
        gecmis[r["firsat_id"]].append((r["asama"], r["tarih"]))
    for f in firsatlar:
        f["gecmis"] = gecmis[f["id"]]
    return firsatlar


def hesapla(c: sqlite3.Connection, bugun: date, sahip_id: int | None = None,
            baslangic: str = "", bitis: str = "") -> dict:
    asama = [dict(r) for r in c.execute("SELECT * FROM asama ORDER BY sira")]
    acik_kodlar = [a["kod"] for a in asama if a["acik"]]
    sira = {a["kod"]: a["sira"] for a in asama}
    olasilik = {a["kod"]: a["olasilik"] for a in asama}
    ad = {a["kod"]: a["ad"] for a in asama}
    KAZ, KAY = "kazanildi", "kaybedildi"

    firsatlar = firsatlari_al(c, sahip_id, baslangic, bitis)
    acik = [f for f in firsatlar if f["asama"] in acik_kodlar]
    kazanilan = [f for f in firsatlar if f["asama"] == KAZ]
    kaybedilen = [f for f in firsatlar if f["asama"] == KAY]

    # --- huni: her fırsatın vardığı en ileri aşama
    def en_ileri(f: dict) -> int:
        endeks = [sira[a] for a, _ in f["gecmis"] if a != KAY]
        if f["asama"] != KAY:
            endeks.append(sira[f["asama"]])
        return max(endeks) if endeks else 0

    ileri = [en_ileri(f) for f in firsatlar]
    huni_kodlar = acik_kodlar + [KAZ]
    huni = []
    for i, kod in enumerate(huni_kodlar):
        ulasan = sum(1 for x in ileri if x >= sira[kod])
        huni.append({"asama": kod, "ad": ad[kod], "ulasan": ulasan})
    for i, h in enumerate(huni):
        h["gecis_orani"] = _oran(huni[i + 1]["ulasan"], h["ulasan"]) if i + 1 < len(huni) else None

    # --- aşama bazında açık hat
    hat = []
    for kod in acik_kodlar:
        fs = [f for f in acik if f["asama"] == kod]
        toplam = sum(f["tutar"] or 0 for f in fs)
        hat.append({"asama": kod, "ad": ad[kod], "olasilik": olasilik[kod], "sayi": len(fs), "tutar": toplam,
                    "agirlikli": round(toplam * olasilik[kod] / 100, 2)})

    # --- kayıp nedenleri
    say = Counter(f["kayip_nedeni"] or "(boş)" for f in kaybedilen)
    nedenler = [{"neden": n, "sayi": s, "pay": _oran(s, len(kaybedilen))}
                for n, s in sorted(say.items(), key=lambda x: (-x[1], x[0]))]

    # --- kırılımlar
    def kirilim(anahtar: str, etiketler: dict) -> list[dict]:
        gruplar = defaultdict(list)
        for f in firsatlar:
            gruplar[f[anahtar]].append(f)
        sonuc = []
        for k, fs in gruplar.items():
            kz = [f for f in fs if f["asama"] == KAZ]
            ky = [f for f in fs if f["asama"] == KAY]
            sonuc.append({"ad": etiketler.get(k, k or "(boş)"), "firsat": len(fs), "kazanilan": len(kz),
                          "kaybedilen": len(ky), "kazanma_orani": _oran(len(kz), len(kz) + len(ky)),
                          "kazanilan_tutar": sum(f["tutar"] or 0 for f in kz),
                          "acik_tutar": sum(f["tutar"] or 0 for f in fs if f["asama"] in acik_kodlar)})
        return sorted(sonuc, key=lambda x: (-x["firsat"], x["ad"]))

    kaynak_sira = {r["ad"]: r["sira"] for r in c.execute("SELECT * FROM kaynak")}
    kaynaklar = sorted(kirilim("kaynak", {}), key=lambda x: kaynak_sira.get(x["ad"], 99))
    kullanicilar = {r["id"]: r["ad"] for r in c.execute("SELECT id, ad FROM kullanici")}
    sahipler = sorted(kirilim("sahip_id", kullanicilar), key=lambda x: x["ad"])

    # --- satış süresi
    sureler = []
    for f in kazanilan:
        kaz_tarih = [t for a, t in f["gecmis"] if a == KAZ]
        if kaz_tarih:
            sureler.append((date.fromisoformat(kaz_tarih[-1]) - date.fromisoformat(f["olusturma"])).days)

    # --- görev ve takip durumu (bugüne göre)
    acik_ids = {f["id"] for f in acik}
    gorevler = [dict(r) for r in c.execute("SELECT * FROM gorev WHERE durum = 'acik'")]
    b = bugun.isoformat()
    ileri_gorev = {g["firsat_id"] for g in gorevler if g["firsat_id"] and g["son_tarih"] >= b}
    herhangi_gorev = {g["firsat_id"] for g in gorevler if g["firsat_id"]}
    gorevsiz = sorted(acik_ids - herhangi_gorev)
    yalniz_geciken = sorted((acik_ids & herhangi_gorev) - ileri_gorev)
    bayat = sorted(f["id"] for f in acik if (bugun - date.fromisoformat(f["guncelleme"])).days >= BAYAT_GUN)
    ay = b[:7]
    bu_ay = [f for f in kazanilan if any(a == KAZ and t[:7] == ay for a, t in f["gecmis"])]

    return {
        "bugun": b,
        "filtre": {"sahip_id": sahip_id, "baslangic": baslangic, "bitis": bitis},
        "firsat_sayisi": len(firsatlar),
        "acik_sayi": len(acik),
        "acik_tutar": sum(f["tutar"] or 0 for f in acik),
        "agirlikli_tutar": round(sum(h["agirlikli"] for h in hat), 2),
        "kazanilan_sayi": len(kazanilan),
        "kaybedilen_sayi": len(kaybedilen),
        "kazanma_orani": _oran(len(kazanilan), len(kazanilan) + len(kaybedilen)),
        "kazanilan_tutar": sum(f["tutar"] or 0 for f in kazanilan),
        "ortalama_kazanilan_tutar": round(sum(f["tutar"] or 0 for f in kazanilan) / len(kazanilan), 2) if kazanilan else None,
        "ortalama_satis_suresi_gun": round(sum(sureler) / len(sureler), 2) if sureler else None,
        "bu_ay_kazanilan_sayi": len(bu_ay),
        "bu_ay_kazanilan_tutar": sum(f["tutar"] or 0 for f in bu_ay),
        "huni": huni,
        "hat": hat,
        "kayip_nedenleri": nedenler,
        "kaynaklar": kaynaklar,
        "sahipler": sahipler,
        "geciken_gorev": sum(1 for g in gorevler if g["son_tarih"] < b),
        "bugun_gorev": sum(1 for g in gorevler if g["son_tarih"] == b),
        "gorevsiz_firsatlar": gorevsiz,
        "yalniz_geciken_gorevli_firsatlar": yalniz_geciken,
        "bayat_firsatlar": bayat,
    }
