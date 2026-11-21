// Copie hors ligne + réception d'un PDF partagé depuis une autre appli (WhatsApp, Fichiers...).
const CACHE = "edt-v5";
const PARTAGE = "edt-partage";
const FICHIERS = ["./", "index.html", "edt-pdf.js", "manifest.json",
                  "lib/pdf.min.js", "lib/pdf.worker.min.js"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c =>
    Promise.all(FICHIERS.map(f => c.add(f).catch(() => {})))));   // un fichier absent n'empêche pas l'installation
  self.skipWaiting();
});
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);

  // « Partager → EDT » : le PDF arrive en POST, on le garde puis on ouvre la page qui l'importe
  if (req.method === "POST" && url.pathname.endsWith("/partage")) {
    e.respondWith((async () => {
      try {
        const data = await req.formData();
        const fichier = data.get("pdf");
        if (fichier) {
          const c = await caches.open(PARTAGE);
          await c.put("fichier-partage", new Response(fichier, {headers: {"Content-Type": "application/pdf"}}));
        }
      } catch (err) {}
      return Response.redirect(new URL("./?partage=1", self.registration.scope).href, 303);
    })());
    return;
  }

  if (req.method !== "GET") return;
  e.respondWith(
    fetch(req).then(r => {
      const copie = r.clone();
      caches.open(CACHE).then(c => c.put(req, copie));
      return r;
    }).catch(() => caches.match(req, {ignoreSearch: true}))
  );
});
