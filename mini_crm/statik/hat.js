// Satış hattı panosu: kartı sürükleyip başka aşamaya bırakınca aşama değişir.
// Kaybedildi sütununa bırakılan kart için kayıp nedeni sorulur (fırsat sayfasına gider).
// JavaScript kapalıysa kartlardaki ◀ ▶ düğmeleri aynı işi yapar.
document.querySelectorAll(".fkart").forEach((k) => {
  k.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", k.dataset.id);
    k.classList.add("surukleniyor");
  });
  k.addEventListener("dragend", () => k.classList.remove("surukleniyor"));
});
document.querySelectorAll(".kolon").forEach((kol) => {
  kol.addEventListener("dragover", (e) => { e.preventDefault(); kol.classList.add("uzerinde"); });
  kol.addEventListener("dragleave", () => kol.classList.remove("uzerinde"));
  kol.addEventListener("drop", async (e) => {
    e.preventDefault();
    kol.classList.remove("uzerinde");
    const id = e.dataTransfer.getData("text/plain");
    const asama = kol.dataset.asama;
    if (asama === "kaybedildi") { location.href = `/firsat/${id}?kaybet=1`; return; }
    const govde = new URLSearchParams({ asama, geri: location.pathname + location.search });
    const y = await fetch(`/firsat/${id}/asama`, { method: "POST", body: govde, redirect: "follow" });
    location.href = y.url;
  });
});
