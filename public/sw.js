// v4 - explicit network/no-store for /api/*, network-first for shell
const CACHE = "gsr-v4";

const SHELL = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/manifest.json",
  "/icon.svg"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => (k !== CACHE ? caches.delete(k) : null)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Only handle GET
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Never cache API responses: always go to network, bypass caches
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(new Request(req, { cache: "no-store" })));
    return;
  }

  // Network-first for everything else; cache on success
  event.respondWith(
    (async () => {
      try {
        const fresh = await fetch(new Request(req, { cache: "no-store" }));
        // Cache only same-origin basic responses
        if (url.origin === self.location.origin && fresh && fresh.ok && fresh.type === "basic") {
          const cache = await caches.open(CACHE);
          cache.put(req, fresh.clone());
        }
        return fresh;
      } catch (e) {
        const cached = await caches.match(req);
        return cached || new Response("Offline", { status: 503 });
      }
    })()
  );
});
