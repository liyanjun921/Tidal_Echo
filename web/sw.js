/* Tidal Echo — service worker (offline shell + Web Push).
   IMPORTANT: bump CACHE on every front-end change, or installed clients keep the
   old shell (the precached index.html won't refresh until the SW reinstalls). */
const AI_NAME = "Émoi";
const CACHE = "emoi-v16-mobile-glass";
const scopedPrefix = "emoi-v";
const PRECACHE = [
  "./index.html", "./legacy-storage.js", "./styles.css", "./polish.css", "./emoi-archive-glass.css", "./emoi-phone.css", "./emoi-liquid.css", "./emoi-imessage.css", "./emoi-crystal.css", "./emoi-responsive.css", "./emoi-clear-home.css", "./emoi-wallpapers.js", "./emoi-phone.js", "./emoi-avatars.js", "./emoi-imessage.js", "./emoi-optics.js", "./assets/emoi-wallpaper-1.webp", "./assets/emoi-wallpaper-2.webp", "./assets/emoi-wallpaper-3.webp", "./assets/emoi-phone-aura.svg", "./assets/emoi-archive-botanical.svg", "./assets/emoi-archive-nocturne.svg", "./connection.css", "./app.js", "./reading.js", "./reading.css", "./checklist.js", "./checklist.css", "./cinema.js", "./cinema.css", "./relay-client.js", "./rich-text.js", "./memory.js", "./native-memory.js", "./ombre-memory.js", "./continuity.js", "./wren-room.js", "./wren-room.css", "./xinchao-room.js", "./xinchao-room.css", "./living-context.js", "./living-context.css",
  "./assets/water-light.webp", "./assets/lily-water.webp",
  "./assets/water-light-thumb.webp", "./assets/lily-water-thumb.webp",
].map(path => /\.(js|css)$/.test(path) ? path + "?v=16" : path);

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map(path => new Request(new URL(path, self.registration.scope), {cache:"reload"}))))
      .then(() => self.skipWaiting())
  );
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE && k.startsWith(scopedPrefix)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/relay/") || url.pathname.startsWith("/ombre/") || e.request.headers.has("Authorization") || url.searchParams.has("token")) return;
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request, {cache:"reload"}).then(response => {
      if (!response.ok) throw new Error("Navigation unavailable");
      return response;
    }).catch(async () => {
      const cache = await caches.open(CACHE);
      return await cache.match("./index.html") || Response.error();
    }));
    return;
  }
  if (e.request.method === "GET" && url.origin === location.origin) {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(e.request);
      if (cached) return cached;
      const response = await fetch(e.request);
      if (response.ok && !/\.(js|css)$/.test(url.pathname)) {
        try { await cache.put(e.request, response.clone()); } catch (_) {}
      }
      return response;
    })());
  }
});

// ── Web Push (VAPID) ──────────────────────────────
// The relay sends a push when the AI replies and no PWA tab is holding the stream;
// here we surface it on the lock screen.
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; }
  catch (_) { d = { body: (e.data && e.data.text && e.data.text()) || "" }; }
  const title = d.title || AI_NAME;                        // backend sends RELAY_AI_NAME as title
  const body  = d.body  || "你有一条新消息";
  const tag   = d.id ? ("companion-" + d.id) : "companion-msg";
  e.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag,
      renotify: true,
      icon:  "./icon-192.png",
      badge: "./icon-192.png",
      vibrate: [80, 40, 80],
      data: { url: d.url || "./" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "./";
  e.waitUntil(
    // matchAll only returns clients this SW controls (our own scope), so focus the first one.
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cls) => {
      for (const c of cls) {
        if ("focus" in c){ c.postMessage({ type: "backfill" }); return c.focus(); }
      }
      return self.clients.openWindow ? self.clients.openWindow(target) : null;
    })
  );
});
