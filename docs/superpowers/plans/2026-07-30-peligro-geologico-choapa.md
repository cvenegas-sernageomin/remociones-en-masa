# Peligro Geológico Choapa (DCR+SFL) en el RETERM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consultar en vivo, al mover el marcador de una RM, el FeatureServer público de
SERNAGEOMIN que clasifica el sector sur de Coquimbo (provincia de Choapa) en susceptibilidad
de Deslizamiento/Caída de Rocas (DCR) y Flujos de Detritos (SFL), y agregar el resultado como
una oración en las conclusiones del RETERM (individual y compilado) y una fila en el KMZ,
solo cuando el punto cae dentro de esa cobertura.

**Architecture:** Mismo patrón ya usado para comuna/zona morfoclimática (variable de cache en
memoria actualizada desde `actualizarRegionComunaDisplay`, leída por `collectFormData` hacia
`data`), pero con una llamada de red en vivo (no ray casting local) con debounce 700ms y un
token de "última consulta gana" para descartar respuestas tardías. Todo vive en
`catastro-remociones/index.html`. Verificación con `javascript_tool` sobre el preview
`catastro` (puerto 8766), llamando las funciones nuevas directamente.

**Tech Stack:** HTML/JS vanilla, `fetch` a un FeatureServer ArcGIS REST público
(sin token), `setTimeout`/`clearTimeout` para debounce.

**Spec:** `docs/superpowers/specs/2026-07-30-peligro-geologico-choapa-design.md`

---

## Antes de empezar

```
preview_start({ name: "catastro" })
navigate a http://localhost:8766
```

Recargar (`location.reload()`) después de cada cambio de código antes de volver a probar.

---

### Task 1: Función de consulta en vivo + cache + debounce

**Files:**
- Modify: `catastro-remociones/index.html:1909-1913` (declaración de variables cache)
- Modify: `catastro-remociones/index.html:1914-1936` (`actualizarRegionComunaDisplay`)

- [ ] **Step 1: Agregar las variables de cache y de debounce**

Justo después de la línea `let ultimaZonaMorfo = null;` (index.html:1913), agregar:

```js
// Peligro geológico Choapa (DCR+SFL) del punto actual — consulta EN VIVO al FeatureServer
// público de SERNAGEOMIN (a diferencia de comuna/zona morfoclimática, que son datasets
// descargados una vez y cacheados para ray casting offline: este cubre solo 4 comunas de
// Choapa y tiene 165k polígonos, demasiado denso para replicar ese patrón — ver spec
// docs/superpowers/specs/2026-07-30-peligro-geologico-choapa-design.md). null si el punto
// cae fuera de Choapa, si la consulta falló, o si aún no se resolvió.
let ultimaPeligroChoapa = null;
let _peligroChoapaTimer = null;
let _peligroChoapaGen = 0;   // token "última consulta gana": descarta respuestas tardías de una posición vieja del marcador

const PELIGRO_CHOAPA_URL = 'https://services1.arcgis.com/OyjvVdFTl5hfSdX3/arcgis/rest/services/Mapa_de_Peligro_Geol%C3%B3gico_de_Coquimbo_500_WFL1/FeatureServer/0/query';

async function consultarPeligroChoapa(lat, lng) {
  const gen = ++_peligroChoapaGen;
  const geom = encodeURIComponent(JSON.stringify({ x: lng, y: lat, spatialReference: { wkid: 4326 } }));
  const url = `${PELIGRO_CHOAPA_URL}?geometry=${geom}&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=SFL,DCR&returnGeometry=false&f=json`;
  try {
    const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const j = await resp.json();
    if (gen !== _peligroChoapaGen) return;   // el marcador ya se movió de nuevo: descartar
    const f = (j.features || [])[0];
    ultimaPeligroChoapa = f ? { dcr: f.attributes.DCR || '', sfl: f.attributes.SFL || '' } : null;
  } catch (err) {
    if (gen !== _peligroChoapaGen) return;
    ultimaPeligroChoapa = null;
    console.warn('peligro geológico Choapa:', err);
  }
}

function programarConsultaPeligroChoapa(c) {
  clearTimeout(_peligroChoapaTimer);
  if (!c || c.lat == null) return;
  const lat = c.lat, lng = c.lng ?? c.lon;
  _peligroChoapaTimer = setTimeout(() => consultarPeligroChoapa(lat, lng), 700);
}
```

- [ ] **Step 2: Llamar la nueva función desde `actualizarRegionComunaDisplay`**

En `actualizarRegionComunaDisplay()` (index.html:1914), agregar la llamada al final de la
función (después de la lógica de `ultimaComunaRegion`, antes del cierre `}`):

```js
function actualizarRegionComunaDisplay() {
  const el = document.getElementById('region-comuna-display');
  const c = getCoords();
  ultimaZonaMorfo = zonaMorfoDesdeCoords(c);
  if (!morfoPoligonos) cargarMorfoPoligonos().then(() => { ultimaZonaMorfo = zonaMorfoDesdeCoords(getCoords()); });
  programarConsultaPeligroChoapa(c);
  const r = comunaRegionDesdeCoords(c);
  if (r) {
    ultimaComunaRegion = r;
    if (el) { el.textContent = `🏛️ ${r.comuna || '—'} · ${r.region}`; el.style.color = ''; }
    return;
  }
  if (comunasPoligonos) {
    ultimaComunaRegion = null;
    if (el) { el.textContent = '⚠️ Sin comuna detectada en este punto — verificar región manualmente'; el.style.color = '#c0392b'; }
    return;
  }
  ultimaComunaRegion = { comuna: '', provincia: '', region: regionFromCoords(c) };
  if (el) { el.textContent = `⏳ ${ultimaComunaRegion.region} (aproximado — verificar con conexión)`; el.style.color = '#b7791f'; }
  cargarComunasPoligonos().then(() => actualizarRegionComunaDisplay());
}
```

(Solo se agregó la línea `programarConsultaPeligroChoapa(c);` — el resto de la función queda
igual, se transcribe completa para que quede claro dónde va la línea nueva.)

- [ ] **Step 3: Recargar el preview y verificar la consulta en vivo de forma aislada**

```js
(async () => {
  // Punto real dentro de Illapel (Choapa) — ya verificado en la investigación previa: {SFL:"Moderada", DCR:"Baja"}
  await consultarPeligroChoapa(-31.6335, -71.1691);
  const dentro = { ...ultimaPeligroChoapa };
  // Punto fuera de cobertura (Santiago)
  await consultarPeligroChoapa(-33.45, -70.66);
  const fuera = ultimaPeligroChoapa;
  return { dentro, fuera };
})()
```

Expected: `{ dentro: { dcr: "Baja", sfl: "Moderada" }, fuera: null }`.

- [ ] **Step 4: Verificar el token "última consulta gana"**

```js
(async () => {
  // Dos consultas casi simultáneas: la 2ª (fuera de cobertura) debe ganar aunque la 1ª
  // (dentro de cobertura) tarde más en resolver — simulamos disparando ambas sin esperar
  // la primera antes de la segunda.
  const p1 = consultarPeligroChoapa(-31.6335, -71.1691);   // Illapel (con dato)
  const p2 = consultarPeligroChoapa(-33.45, -70.66);        // Santiago (sin dato) — dispara después, debe ganar
  await Promise.all([p1, p2]);
  return ultimaPeligroChoapa;   // debe ser null (resultado de la última consulta), no el dato de Illapel
})()
```

Expected: `null`. Si da un objeto `{dcr,sfl}` en vez de `null`, el token de "última consulta
gana" no está descartando correctamente la respuesta de la 1ª consulta — revisar que
`gen !== _peligroChoapaGen` se compara DESPUÉS del `await fetch`, no antes.

- [ ] **Step 5: Verificar degradación silenciosa ante falla de red**

```js
(async () => {
  const fetchOriginal = window.fetch;
  window.fetch = () => Promise.reject(new Error('sin conexión (simulado)'));
  let lanzoExcepcion = false;
  try {
    await consultarPeligroChoapa(-31.6335, -71.1691);
  } catch (e) {
    lanzoExcepcion = true;
  } finally {
    window.fetch = fetchOriginal;
  }
  return { lanzoExcepcion, resultado: ultimaPeligroChoapa };
})()
```

Expected: `{ lanzoExcepcion: false, resultado: null }` — la función nunca debe propagar la
excepción hacia quien la llama (`programarConsultaPeligroChoapa`/`actualizarRegionComunaDisplay`
no tienen try/catch propio, así que una excepción no atrapada aquí rompería el flujo del
wizard).

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat: consulta en vivo de peligro geologico Choapa (DCR+SFL) al mover el marcador"
```

---

### Task 2: Reset y persistencia (`resetFormForNewRM`, `collectFormData`)

**Files:**
- Modify: `catastro-remociones/index.html:4925-4926` (`resetFormForNewRM`)
- Modify: `catastro-remociones/index.html:3513-3515` (`collectFormData`)

- [ ] **Step 1: Resetear el cache al empezar una RM nueva**

En `resetFormForNewRM()`, después de la línea:

```js
  ultimaZonaMorfo = null;   // simétrico con ultimaComunaRegion: no arrastrar la zona morfoclimática de la RM anterior
```

agregar:

```js
  ultimaPeligroChoapa = null;   // simétrico con ultimaComunaRegion/ultimaZonaMorfo
```

- [ ] **Step 2: Persistir en `collectFormData()`**

Después de la línea:

```js
    'morfo-nivel': ultimaZonaMorfo ? ultimaZonaMorfo.nivel : '',
```

agregar:

```js
    'peligro-dcr': ultimaPeligroChoapa ? ultimaPeligroChoapa.dcr : '',
    'peligro-sfl': ultimaPeligroChoapa ? ultimaPeligroChoapa.sfl : '',
```

- [ ] **Step 3: Recargar el preview y verificar el reset + la persistencia**

```js
(async () => {
  await consultarPeligroChoapa(-31.6335, -71.1691);
  const antes = { ...ultimaPeligroChoapa };
  resetFormForNewRM();
  const despuesReset = ultimaPeligroChoapa;
  await consultarPeligroChoapa(-31.6335, -71.1691);
  const data = collectFormData();
  return { antes, despuesReset, dataDcr: data['peligro-dcr'], dataSfl: data['peligro-sfl'] };
})()
```

Expected: `{ antes: {dcr:"Baja", sfl:"Moderada"}, despuesReset: null, dataDcr: "Baja", dataSfl: "Moderada" }`.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: persistir peligro geologico Choapa en collectFormData + reset simetrico"
```

---

### Task 3: Frase en conclusiones del RETERM (individual y compilado)

**Files:**
- Modify: `catastro-remociones/index.html:3806-3808` (`construirContenidoReterm`, sección de
  conclusiones)

- [ ] **Step 1: Agregar la nueva oración condicional**

Después del bloque:

```js
      if (data['morfo-nivel']) {
        concluParts.push(`Según la zonificación morfoclimática de SERNAGEOMIN/DGA, el punto se emplaza en la zona "${esc(data['morfo-zona'])}"${data['morfo-region'] ? ' (' + esc(data['morfo-region']) + ')' : ''}, calificada con una posibilidad de ocurrencia de remociones en masa <b>${esc(data['morfo-nivel'])}</b>.`);
      }
```

agregar:

```js
      // Mapa de Peligro Geológico de Coquimbo (SERNAGEOMIN, sector sur — provincia de
      // Choapa): solo entra si el punto cayó dentro de esa cobertura (4 comunas) al
      // momento de mover el marcador — ver consultarPeligroChoapa.
      if (data['peligro-dcr']) {
        concluParts.push(`Según el Mapa de Peligro Geológico de Coquimbo (SERNAGEOMIN, sector sur — provincia de Choapa), el punto se emplaza en un sector con susceptibilidad <b>${esc(data['peligro-dcr'])}</b> de deslizamiento y caída de rocas, y susceptibilidad <b>${esc(data['peligro-sfl'])}</b> de flujos de detritos.`);
      }
```

- [ ] **Step 2: Recargar el preview y verificar en ambos informes (individual y compilado)**

```js
(async () => {
  const dataDentro = { coords: { lat: -31.6335, lng: -71.1691 }, region: 'Coquimbo (IV)', 'peligro-dcr': 'Baja', 'peligro-sfl': 'Moderada', 'fecha-inicio': '2026-07-01' };
  const dataFuera = { coords: { lat: -33.45, lng: -70.66 }, region: 'Metropolitana (RM)', 'fecha-inicio': '2026-07-01' };
  const cDentro = construirContenidoReterm(dataDentro, {});
  const cFuera = construirContenidoReterm(dataFuera, {});
  const fraseDentro = cDentro.concluParts.some(p => p.includes('Mapa de Peligro Geológico de Coquimbo'));
  const fraseFuera = cFuera.concluParts.some(p => p.includes('Mapa de Peligro Geológico de Coquimbo'));
  return { fraseDentro, fraseFuera };
})()
```

Expected: `{ fraseDentro: true, fraseFuera: false }`.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: frase de peligro geologico Choapa en conclusiones del RETERM"
```

---

### Task 4: Fila en el KMZ (`buildKML`)

**Files:**
- Modify: `catastro-remociones/index.html:2612` (`buildKML`)

- [ ] **Step 1: Agregar la fila nueva**

Después de la línea:

```js
  ${row('Zona morfoclimática', data['morfo-zona'] ? data['morfo-zona'] + (data['morfo-nivel'] ? ` (posibilidad ${data['morfo-nivel']})` : '') : null)}
```

agregar:

```js
  ${row('Peligro geológico (Choapa)', data['peligro-dcr'] ? `Deslizamiento/Caída de rocas: ${data['peligro-dcr']} · Flujos de detritos: ${data['peligro-sfl']}` : null)}
```

- [ ] **Step 2: Recargar el preview y verificar la fila en el KML generado**

```js
(async () => {
  const dataDentro = { coords: { lat: -31.6335, lng: -71.1691 }, region: 'Coquimbo (IV)', 'peligro-dcr': 'Baja', 'peligro-sfl': 'Moderada', zona: 'generacion' };
  const dataFuera = { coords: { lat: -33.45, lng: -70.66 }, region: 'Metropolitana (RM)', zona: 'generacion' };
  const kmlDentro = buildKML(dataDentro, [], null, null);
  const kmlFuera = buildKML(dataFuera, [], null, null);
  return {
    tieneFilaDentro: kmlDentro.includes('Peligro geológico (Choapa)') && kmlDentro.includes('Deslizamiento/Caída de rocas: Baja'),
    tieneFilaFuera: kmlFuera.includes('Peligro geológico (Choapa)')
  };
})()
```

Expected: `{ tieneFilaDentro: true, tieneFilaFuera: false }`.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: fila Peligro geologico (Choapa) en el KMZ individual"
```

---

### Task 5: Verificación end-to-end simulando movimiento del marcador

**Files:** ninguno (solo verificación manual sobre lo ya implementado en Tasks 1-4)

- [ ] **Step 1: Simular el flujo completo de captura para una RM dentro de Choapa**

Requiere que el wizard tenga un marcador colocable (`markerInstance`). Si el preview no tiene
un mapa Leaflet inicializado con marcador arrastrable en el paso correspondiente, hacer esta
verificación posicionando el marcador programáticamente:

```js
(async () => {
  resetFormForNewRM();
  markerInstance.setLatLng([-31.6335, -71.1691]);
  updateCoordsDisplay();   // dispara actualizarRegionComunaDisplay → programarConsultaPeligroChoapa (debounce 700ms)
  await new Promise(r => setTimeout(r, 1200));   // esperar a que resuelva el debounce + el fetch
  const data = collectFormData();
  return { dcr: data['peligro-dcr'], sfl: data['peligro-sfl'] };
})()
```

Expected: `{ dcr: "Baja", sfl: "Moderada" }` (mismo punto de Illapel usado en las pruebas
anteriores).

- [ ] **Step 2: Confirmar que mover el marcador fuera de Choapa limpia el dato**

```js
(async () => {
  markerInstance.setLatLng([-33.45, -70.66]);
  updateCoordsDisplay();
  await new Promise(r => setTimeout(r, 1200));
  const data = collectFormData();
  return { dcr: data['peligro-dcr'], sfl: data['peligro-sfl'] };
})()
```

Expected: `{ dcr: "", sfl: "" }`.

- [ ] **Step 3: Editar una RM ya guardada con el dato persistido (sin mover el marcador)**

Confirmar manualmente en el preview: guardar una RM con coords dentro de Choapa, reabrirla
desde "📋 RMs guardadas" sin tocar el marcador, generar el RETERM y verificar que la frase de
peligro geológico sigue apareciendo (leída desde `data['peligro-dcr']` guardado, sin necesidad
de una nueva consulta de red).

---

### Task 6: Bump de versión y publicación

**Files:**
- Modify: `catastro-remociones/index.html` (constante de versión — mismo procedimiento que en
  el plan de Figura B: confirmar el patrón exacto con `grep -n "APP_VER" index.html` antes de
  incrementar, ya que ambos planes tocan el mismo archivo y deben coordinarse en un solo bump
  si se implementan en la misma sesión)

- [ ] **Step 1: Confirmar versión actual y bump**

```bash
grep -n "APP_VER\|remociones-v" catastro-remociones/index.html catastro-remociones/sw.js | head -20
```

- [ ] **Step 2: Commit y push**

```bash
git add index.html sw.js
git commit -m "chore: bump version tras Peligro Geologico Choapa (DCR+SFL)"
git push
```

(Confirmar con el usuario antes de hacer `git push`.)
