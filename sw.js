const CACHE_NAME = 'remociones-v82';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './puntos_criticos.json',
  './emergencias_temporal.json',
  './vendor/idb.js',
  './vendor/leaflet.offline.js',
  './vendor/reterm-logo.png',
  './icons/caida-roca.svg',
  './icons/flujo-detritos.svg',
  './icons/deslizamiento.svg',
  './icons/aluvion.svg',
  './icons/avalancha.svg',
  './icons/reptacion.svg',
  './icons/otro.svg',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',
  'https://unpkg.com/georaster@1.6.0/dist/georaster.browser.bundle.min.js',
  'https://unpkg.com/georaster-layer-for-leaflet@4.1.2/dist/georaster-layer-for-leaflet.min.js'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Permite que la página fuerce la activación del SW nuevo (auto-actualización)
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const req = e.request;

  // Dejar que leaflet.offline maneje los tiles de mapa (IndexedDB) — Esri y OpenTopoMap;
  // si el SW los cacheara, el caché crecería sin límite y serviría tiles viejos
  if (req.url.includes('arcgisonline.com') || req.url.includes('opentopomap.org')) return;

  // Estaciones meteorológicas: KML del visor de alertas + gráficos QuickChart
  // van SIEMPRE a la red (datos en vivo; no cachear o el refresco de 3 h serviría datos viejos)
  if (req.url.includes('raw.githubusercontent.com') || req.url.includes('quickchart.io')) return;

  // Minutas ATG Flash: servicio REST de ArcGIS (features + adjuntos PDF) → siempre a la red
  if (req.url.includes('services1.arcgis.com')) return;

  // Emergencias 2026: KML en vivo del Visor de Emergencias (Google My Maps) → siempre a la red
  if (req.url.includes('google.com/maps/d/kml')) return;

  // Catálogo RMASA: informes PDF re-hosteados como assets de un GitHub Release (hasta ~55 MB
  // c/u) → siempre a la red, sin cachear (evita llenar el storage con descargas puntuales)
  if (req.url.includes('/releases/download/')) return;

  // Precipitación acumulada (Open-Meteo) → siempre a la red (dato en vivo, no cachear)
  if (req.url.includes('api.open-meteo.com')) return;

  const esDoc = req.mode === 'navigate' || req.destination === 'document' ||
                req.url.endsWith('/') || req.url.endsWith('index.html');

  // El índice de regiones IPT / capas de Infraestructura también va network-first: así
  // una región o capa nueva publicada aparece sin bump de versión (los archivos grandes
  // ipt/*.json e infra/*.json siguen cache-first)
  if (esDoc || req.url.endsWith('ipt/manifest.json') || req.url.endsWith('infra/manifest.json')) {
    // network-first para el HTML: siempre la última versión estando en línea
    e.respondWith(
      fetch(req).then(resp => {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(req, clone));
        return resp;
      }).catch(() => caches.match(req).then(r => r || caches.match('./index.html')))
    );
    return;
  }

  // cache-first para el resto de los assets
  e.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(resp => {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(req, clone));
        return resp;
      }).catch(() => {
        if (req.mode === 'navigate') return caches.match('./index.html');
      });
    })
  );
});
