const CACHE_NAME = 'remociones-v6';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icons/caida-roca.svg',
  './icons/flujo-detritos.svg',
  './icons/deslizamiento.svg',
  './icons/aluvion.svg',
  './icons/avalancha.svg',
  './icons/reptacion.svg',
  './icons/otro.svg',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://unpkg.com/leaflet.offline@2.2.0/dist/leaflet.offline.js',
  'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',
  'https://unpkg.com/georaster@1.6.0/dist/georaster.browser.bundle.min.js',
  'https://unpkg.com/georaster-layer-for-leaflet@3.9.0/dist/georaster-layer-for-leaflet.min.js',
  'https://cvenegas-sernageomin.github.io/voz-terreno/voz-module.js',
  'https://cvenegas-sernageomin.github.io/voz-terreno/whisper-worker.js',
  'https://cvenegas-sernageomin.github.io/voz-terreno/transformers.min.js'
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

  // Dejar que leaflet.offline maneje los tiles de Esri (IndexedDB)
  if (req.url.includes('arcgisonline.com')) return;

  const esDoc = req.mode === 'navigate' || req.destination === 'document' ||
                req.url.endsWith('/') || req.url.endsWith('index.html');

  if (esDoc) {
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
