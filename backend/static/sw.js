/* SilentSOS service worker — app-shell + API cache for offline use.
   Version the cache name to invalidate old shells on deploy. */
const CACHE = "silentsos-v1";
const SHELL = ["/", "/simulator", "/security", "/track-shell", "/manifest.json",
               "/i18n.js", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE)
      .map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/track/") || url.pathname.startsWith("/report/")) {
    // Network-first. Offline: the exact page if cached, else any cached
    // track shell (the HTML is identical for every alert id; the page
    // reads the id from the URL and renders last-known state).
    e.respondWith((async () => {
      try {
        const res = await fetch(e.request);
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      } catch {
        const exact = await caches.match(e.request);
        if (exact) return exact;
        if (url.pathname.startsWith("/track/")) {
          // The track HTML is identical for every alert id; the page reads
          // the id from the URL and renders last-known state from storage.
          const shell = await caches.match("/track-shell");
          if (shell) return shell;
        }
        return caches.match("/");
      }
    })());
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    // Network-first with cache fallback, so the tracking page can render
    // its last-known state offline. POSTs are never cached.
    e.respondWith((async () => {
      try {
        const res = await fetch(e.request);
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      } catch {
        const cached = await caches.match(e.request);
        if (cached) return cached;
        return new Response(JSON.stringify({ status: "error", offline: true }),
          { status: 503, headers: { "Content-Type": "application/json" } });
      }
    })());
    return;
  }

  // App shell: cache-first, then network.
  e.respondWith((async () => {
    const cached = await caches.match(e.request);
    if (cached) return cached;
    try {
      const res = await fetch(e.request);
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    } catch {
      return caches.match("/");
    }
  })());
});
