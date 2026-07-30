# Figura B (fotos + azimut) en el RETERM compilado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una segunda imagen satelital (Figura B) al RETERM compilado que ubique las
fotos de terreno de todas las RM del reporte, con el azimut de cada foto simbolizado como una
flecha desde el punto de su RM.

**Architecture:** Se extraen helpers compartidos de bbox/descarga satelital/grilla UTM/escala
desde `capturarFiguraACombinada` (sin cambiar su resultado visual actual) para que la nueva
Figura B reutilice el mismo encuadre y la misma descarga de red que ya usa la Figura A de
conjunto. Todo vive en `catastro-remociones/index.html` (app de archivo único, sin build ni
test runner) — la verificación se hace generando el `.docx` con datos sintéticos directamente
en la página cargada (vía `javascript_tool` sobre el preview `catastro`, puerto 8766) y
descomprimiendo el resultado con JSZip (ya cargado en la página) para inspeccionar
`word/document.xml` y los archivos de `word/media/`.

**Tech Stack:** HTML/JS vanilla, Canvas 2D, JSZip (ya vendorizado en la página), Esri
World_Imagery REST export, OOXML (`.docx`) construido a mano con los helpers `wP/wR/wC/wTr/wImg`
ya existentes.

**Spec:** `docs/superpowers/specs/2026-07-30-figura-b-fotos-azimuth-design.md`

---

## Antes de empezar

Abrir el preview de la app (sirve `index.html` en `http://localhost:8766`):

```
preview_start({ name: "catastro" })
navigate a http://localhost:8766
```

Todas las verificaciones de este plan se hacen con `javascript_tool` ejecutando JS directo en
esa página (patrón ya usado en toda la historia del proyecto — ver
`docs/superpowers/specs/2026-07-30-figura-b-fotos-azimuth-design.md`, sección Verificación).
Tras cada cambio de código en `index.html`, recargar la página (`location.reload()`) antes de
volver a probar — el Service Worker puede servir una versión vieja si solo se navega de nuevo
a la misma URL sin recargar.

---

### Task 1: Extraer helpers compartidos (bbox, descarga, grilla, escala)

**Files:**
- Modify: `catastro-remociones/index.html:3906-3996` (función `capturarFiguraACombinada`)

- [ ] **Step 1: Reemplazar la función actual por los helpers + la función refactorizada**

Reemplazar TODO el bloque actual (líneas 3906 a 3996, desde el comentario
`// Modelada en capturarFiguraA...` hasta el `}` que cierra `capturarFiguraACombinada`) por:

```js
// Modelada en capturarFiguraA, pero con bbox que abarca N puntos + marcador y etiqueta por punto.
// calcularBBoxConjunto/descargarSatelital/dibujarGrillaUTM/dibujarEscala se extrajeron para
// que capturarFiguraFotosAzimuth (Figura B: fotos+azimut) comparta el MISMO encuadre y la
// MISMA descarga de red que esta figura, en vez de duplicar ambas cosas.
function calcularBBoxConjunto(puntos) {
  const lats = puntos.map(p => p.lat), lngs = puntos.map(p => p.lng);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const latC = (minLat + maxLat) / 2, lngC = (minLng + maxLng) / 2;
  const W = 800, H = 600;
  const mPerLat = 111320, mPerLng = 111320 * Math.cos(latC * Math.PI / 180);
  // medio-anchos en metros: envolvente + 25% de margen, con un mínimo tipo FIGURA_A_RADIO_M
  let halfLatM = Math.max((maxLat - minLat) / 2 * mPerLat * 1.25, FIGURA_A_RADIO_M);
  let halfLngM = Math.max((maxLng - minLng) / 2 * mPerLng * 1.25, FIGURA_A_RADIO_M);
  // forzar relación de aspecto 4:3 (W/H) en metros reales para no deformar la imagen
  const targetAR = W / H;
  if (halfLngM / halfLatM < targetAR) halfLngM = halfLatM * targetAR;
  else halfLatM = halfLngM / targetAR;
  const halfLat = halfLatM / mPerLat, halfLng = halfLngM / mPerLng;
  return {
    west: lngC - halfLng, east: lngC + halfLng,
    south: latC - halfLat, north: latC + halfLat,
    latC, lngC, W, H
  };
}

async function descargarSatelital(bbox) {
  const { west, south, east, north, W, H } = bbox;
  const url = `https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export?bbox=${west},${south},${east},${north}&bboxSR=4326&size=${W},${H}&imageSR=4326&format=jpg&f=image`;
  try {
    const resp = await fetch(url, { signal: AbortSignal.timeout(12000) });
    if (!resp.ok) throw new Error('Esri export falló');
    const blob = await resp.blob();
    const imgUrl = URL.createObjectURL(blob);
    const img = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = imgUrl; });
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, W, H);
    URL.revokeObjectURL(imgUrl);
    return canvas;
  } catch {
    return null;
  }
}

function dibujarEtiqueta(ctx, x, y, text, align) {
  ctx.font = 'bold 12px Arial';
  const tw = ctx.measureText(text).width;
  const bx = align === 'right' ? x - tw - 8 : x + 2;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(bx, y, tw + 6, 15);
  ctx.fillStyle = '#fff';
  ctx.fillText(text, bx + 3, y + 12);
}

function dibujarGrillaUTM(ctx, bbox) {
  const { west, east, north, south, latC, lngC, W, H } = bbox;
  ctx.strokeStyle = 'rgba(255,255,0,0.85)';
  ctx.lineWidth = 1;
  [0.2, 0.5, 0.8].forEach(fx => {
    const x = fx * W;
    const utm = latLonToUTM(latC, west + fx * (east - west));
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    dibujarEtiqueta(ctx, x, 2, utm.E.toLocaleString() + ' E', fx > 0.8 ? 'right' : 'left');
  });
  [0.2, 0.5, 0.8].forEach(fy => {
    const y = fy * H;
    const utm = latLonToUTM(north - fy * (north - south), lngC);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    dibujarEtiqueta(ctx, 2, y + 2, utm.N.toLocaleString() + ' N', 'left');
  });
}

function dibujarEscala(ctx, bbox) {
  const { west, east, latC, W, H } = bbox;
  const escalaM = 200;
  const pxPorGrado = W / (east - west);
  const metrosPorGrado = 111320 * Math.cos(latC * Math.PI / 180);
  const escalaPx = escalaM / metrosPorGrado * pxPorGrado;
  const sx = W - escalaPx - 14, sy = H - 20;
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + escalaPx, sy); ctx.stroke();
  dibujarEtiqueta(ctx, sx, sy - 18, escalaM + ' m', 'left');
}

// puntos: [{lat,lng,label}]. bboxPre/canvasBasePre opcionales — si no se pasan, esta función
// calcula su propio bbox y hace su propia descarga (uso standalone). generateRETERMCombinado
// los pasa precalculados para compartir encuadre y descarga con capturarFiguraFotosAzimuth.
async function capturarFiguraACombinada(puntos, bboxPre, canvasBasePre) {
  if (!puntos || !puntos.length) return null;
  const bbox = bboxPre || calcularBBoxConjunto(puntos);
  const canvasBase = canvasBasePre !== undefined ? canvasBasePre : await descargarSatelital(bbox);
  if (!canvasBase) return null;
  const canvas = document.createElement('canvas');
  canvas.width = bbox.W; canvas.height = bbox.H;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(canvasBase, 0, 0);
  dibujarGrillaUTM(ctx, bbox);

  // Marcador + etiqueta por cada punto (proyección lineal inversa del bbox)
  puntos.forEach(p => {
    const px = (p.lng - bbox.west) / (bbox.east - bbox.west) * bbox.W;
    const py = (bbox.north - p.lat) / (bbox.north - bbox.south) * bbox.H;
    ctx.beginPath(); ctx.moveTo(px, py - 22); ctx.lineTo(px, py - 8);
    ctx.strokeStyle = '#ff0000'; ctx.lineWidth = 3; ctx.stroke();
    ctx.beginPath(); ctx.arc(px, py, 8, 0, 2 * Math.PI);
    ctx.fillStyle = '#ff0000'; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
    if (p.label) {
      ctx.font = 'bold 13px Arial';
      const tw = ctx.measureText(p.label).width;
      const lx = px + 12 + tw + 8 > bbox.W ? px - 12 - tw - 8 : px + 12;
      ctx.fillStyle = 'rgba(0,0,0,0.72)';
      ctx.fillRect(lx, py - 9, tw + 8, 18);
      ctx.fillStyle = '#fff';
      ctx.fillText(p.label, lx + 4, py + 4);
    }
  });

  dibujarEscala(ctx, bbox);
  return canvas.toDataURL('image/jpeg', 0.85);
}
```

- [ ] **Step 2: Recargar el preview y verificar que Figura A no cambió de comportamiento**

Con el preview abierto en `http://localhost:8766`, ejecutar en `javascript_tool`:

```js
(async () => {
  const puntos = [{lat:-33.45,lng:-70.66,label:'RM-01'},{lat:-33.46,lng:-70.65,label:'RM-02'}];
  const bbox = calcularBBoxConjunto(puntos);
  const canvasBase = await descargarSatelital(bbox);
  const dataUrl = await capturarFiguraACombinada(puntos, bbox, canvasBase);
  return { tieneDataUrl: !!dataUrl, empiezaConJpeg: dataUrl ? dataUrl.startsWith('data:image/jpeg') : false, bbox };
})()
```

Expected: `{ tieneDataUrl: true, empiezaConJpeg: true, bbox: {...} }` — sin excepciones. Si
`descargarSatelital` devuelve `null` por falta de conexión al Esri export, `dataUrl` será
`null`; en ese caso repetir la prueba verificando solo que no lanza excepción.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "refactor: extraer helpers de bbox/descarga/grilla satelital de capturarFiguraACombinada"
```

---

### Task 2: Nueva función `capturarFiguraFotosAzimuth`

**Files:**
- Modify: `catastro-remociones/index.html` (agregar función nueva justo después de
  `capturarFiguraACombinada`, que quedó al final del Task 1)

- [ ] **Step 1: Agregar la función y la paleta de colores**

Insertar inmediatamente después del cierre de `capturarFiguraACombinada` (Task 1):

```js
// Paleta cíclica por RM para la Figura B (fotos+azimut) — 8 colores, se repite si hay más de
// 8 RM con fotos en el mismo reporte compilado.
const COLORES_RM_FOTOS = ['#e63946', '#3a86ff', '#2a9d8f', '#f4a261', '#8338ec', '#00b4d8', '#ff70a6', '#ffd60a'];

// gruposFotos: [{label:'RM-01', lat, lng, fotos:[{numFoto, azimuth}]}], ya filtrado para
// incluir solo RM con al menos una foto usable (ver generateRETERMCombinado). bbox/canvasBase
// deben ser los MISMOS que usó capturarFiguraACombinada para este reporte (mismo encuadre).
async function capturarFiguraFotosAzimuth(gruposFotos, bbox, canvasBase) {
  if (!gruposFotos || !gruposFotos.length || !canvasBase) return null;
  const canvas = document.createElement('canvas');
  canvas.width = bbox.W; canvas.height = bbox.H;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(canvasBase, 0, 0);
  dibujarGrillaUTM(ctx, bbox);

  const LARGO_FLECHA = 38;
  gruposFotos.forEach((g, gi) => {
    const color = COLORES_RM_FOTOS[gi % COLORES_RM_FOTOS.length];
    const px = (g.lng - bbox.west) / (bbox.east - bbox.west) * bbox.W;
    const py = (bbox.north - g.lat) / (bbox.north - bbox.south) * bbox.H;

    // Marcador de la RM (color propio, no rojo como Figura A, para distinguir ambas figuras)
    ctx.beginPath(); ctx.arc(px, py, 7, 0, 2 * Math.PI);
    ctx.fillStyle = color; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();

    g.fotos.forEach(f => {
      if (f.azimuth == null) {
        // Foto sin azimut conocido: aro sin flecha alrededor del marcador de la RM
        ctx.beginPath(); ctx.arc(px, py, 13, 0, 2 * Math.PI);
        ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
        return;
      }
      const rad = f.azimuth * Math.PI / 180;
      const dx = Math.sin(rad), dy = -Math.cos(rad);   // 0°=Norte arriba, sentido horario
      const ex = px + dx * LARGO_FLECHA, ey = py + dy * LARGO_FLECHA;
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ex, ey); ctx.stroke();
      // Punta de flecha
      const headLen = 8, ang = Math.atan2(ey - py, ex - px);
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - headLen * Math.cos(ang - Math.PI / 6), ey - headLen * Math.sin(ang - Math.PI / 6));
      ctx.lineTo(ex - headLen * Math.cos(ang + Math.PI / 6), ey - headLen * Math.sin(ang + Math.PI / 6));
      ctx.closePath(); ctx.fill();
      // Etiqueta RM0N-FK junto a la punta
      const label = g.label.replace('RM-', 'RM') + '-F' + f.numFoto;
      ctx.font = 'bold 11px Arial';
      const tw = ctx.measureText(label).width;
      const lx = ex + dx * 12 - (dx < 0 ? tw + 4 : 0);
      const ly = ey + dy * 12;
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(lx - 2, ly - 10, tw + 6, 14);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, lx, ly + 1);
    });
  });

  // Leyenda de colores por RM (esquina inferior izquierda)
  const legendH = gruposFotos.length * 16 + 8;
  const legendYStart = bbox.H - 20 - legendH;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(6, legendYStart - 4, 90, legendH);
  gruposFotos.forEach((g, gi) => {
    const y = legendYStart + gi * 16 + 8;
    ctx.fillStyle = COLORES_RM_FOTOS[gi % COLORES_RM_FOTOS.length];
    ctx.fillRect(10, y - 8, 12, 12);
    ctx.fillStyle = '#fff';
    ctx.font = '11px Arial';
    ctx.fillText(g.label, 26, y + 2);
  });

  dibujarEscala(ctx, bbox);
  return canvas.toDataURL('image/jpeg', 0.85);
}
```

- [ ] **Step 2: Recargar el preview y verificar la función de forma aislada**

```js
(async () => {
  const puntos = [{lat:-33.45,lng:-70.66,label:'RM-01'}];
  const bbox = calcularBBoxConjunto(puntos);
  const canvasBase = await descargarSatelital(bbox);
  const gruposFotos = [
    { label: 'RM-01', lat: -33.45, lng: -70.66, fotos: [
      { numFoto: 1, azimuth: 45 },
      { numFoto: 2, azimuth: 200 },
      { numFoto: 3, azimuth: null }
    ] }
  ];
  const dataUrl = await capturarFiguraFotosAzimuth(gruposFotos, bbox, canvasBase);
  const vacio = await capturarFiguraFotosAzimuth([], bbox, canvasBase);
  const sinCanvas = await capturarFiguraFotosAzimuth(gruposFotos, bbox, null);
  return { tieneDataUrl: !!dataUrl, esJpeg: dataUrl?.startsWith('data:image/jpeg'), vacioEsNull: vacio === null, sinCanvasEsNull: sinCanvasEsNull === null };
})()
```

Expected: `{ tieneDataUrl: true, esJpeg: true, vacioEsNull: true, sinCanvasEsNull: true }`
(si `descargarSatelital` falló por conectividad, `canvasBase` será `null` y por diseño
`capturarFiguraFotosAzimuth` debe devolver `null` también — verificar ese caso por separado
si ocurre).

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: agregar capturarFiguraFotosAzimuth (dibujo de Figura B)"
```

---

### Task 3: Integrar Figura B en `generateRETERMCombinado`

**Files:**
- Modify: `catastro-remociones/index.html:4001-4226` (función `generateRETERMCombinado`)

- [ ] **Step 1: Compartir bbox/descarga entre Figura A y Figura B, y armar `gruposFotos`**

Reemplazar (dentro de `generateRETERMCombinado`, justo después de armar `puntos`):

```js
    // Puntos GPS (rotulados RM-01, RM-02…) para la figura de conjunto
    const puntos = [];
    records.forEach((rec, i) => {
      const p = coordDe(rec.data);
      if (p) puntos.push({ lat: p.lat, lng: p.lng, label: rmLbl(i) });
    });
    const figConjunto = puntos.length ? await capturarFiguraACombinada(puntos) : null;
```

por:

```js
    // Puntos GPS (rotulados RM-01, RM-02…) para la figura de conjunto
    const puntos = [];
    records.forEach((rec, i) => {
      const p = coordDe(rec.data);
      if (p) puntos.push({ lat: p.lat, lng: p.lng, label: rmLbl(i) });
    });
    // bbox + descarga satelital compartidos entre Figura A (conjunto de RM) y Figura B
    // (fotos + azimut): mismo encuadre exacto, una sola llamada de red para ambas.
    const bboxConjunto = puntos.length ? calcularBBoxConjunto(puntos) : null;
    const canvasBaseConjunto = bboxConjunto ? await descargarSatelital(bboxConjunto) : null;
    const figConjunto = (puntos.length && canvasBaseConjunto)
      ? await capturarFiguraACombinada(puntos, bboxConjunto, canvasBaseConjunto) : null;

    // Grupos de fotos por RM (con azimut) para la Figura B — solo RM con al menos una foto
    // usable (blob o blobDataUrl real, no un item de foto vacío del wizard).
    const gruposFotos = [];
    records.forEach((rec, i) => {
      const p = coordDe(rec.data);
      if (!p) return;
      const fotosConDatos = (rec.fotos || [])
        .filter(f => f.blob || f.blobDataUrl)
        .map((f, k) => ({ numFoto: k + 1, azimuth: f.azimuth ?? null }));
      if (!fotosConDatos.length) return;
      gruposFotos.push({ label: rmLbl(i), lat: p.lat, lng: p.lng, fotos: fotosConDatos });
    });
    const figFotosAzimuth = (gruposFotos.length && canvasBaseConjunto)
      ? await capturarFiguraFotosAzimuth(gruposFotos, bboxConjunto, canvasBaseConjunto) : null;
```

- [ ] **Step 2: Construir la fila OOXML de Figura B**

Ubicar el bloque `--- Figura A de conjunto ---` (empieza con `let figCell;`, termina justo
antes de `// --- Encabezado de identificación ---`). Inmediatamente DESPUÉS de ese bloque
(o sea, después de la línea `figCell = wP(wR('Figura A: sin imagen satelital...`),
agregar:

```js
    // --- Figura B: fotos de terreno + azimut (fila de ancho completo, antes del Registro fotográfico) ---
    let figBRow = '';
    if (figFotosAzimuth) {
      const bytesB = dataUrlToU8(figFotosAzimuth);
      const extB = /^data:image\/png/.test(figFotosAzimuth) ? 'png' : 'jpg';
      const dB = await imgDims(figFotosAzimuth);
      const figBCx = Math.round(6.6 * EMU_IN), figBCy = Math.round(figBCx * dB.h / dB.w);
      const ridB = 'rId' + (++rc);
      imgRels.push('<Relationship Id="' + ridB + '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/figuraFotosAzimuth.' + extB + '"/>');
      mediaFiles.push({ name: 'word/media/figuraFotosAzimuth.' + extB, bytes: bytesB });
      figBRow = fullRow(
        wP(wImg(ridB, figBCx, figBCy, 901, 'FiguraFotosAzimuth'), { align: 'center', after: 40 })
        + wP(wR('Figura B. Ubicación y azimut de las fotografías de terreno incluidas en este reporte (imagen satelital con grilla UTM; cada flecha indica la dirección hacia la que apuntaba la cámara al momento de tomarla).', { i: true, sz: 17 }), { align: 'center' })
      );
    }
```

Nota: este bloque usa `rc`, `imgRels`, `mediaFiles` y `fullRow`, todos ya declarados más arriba
en la misma función (`let rc = 3; const imgRels = []; const mediaFiles = [];` y
`const fullRow = (c) => ...`) — confirmar que el bloque queda DESPUÉS de esas declaraciones
(están antes del bloque de Figura A, así que agregar esto justo después de Figura A ya cumple
el orden correcto).

- [ ] **Step 3: Insertar la fila en la tabla, antes de "Registro fotográfico"**

Reemplazar:

```js
      + secRow('Insumos utilizados para el análisis') + fullRow(wP(wR(insumos), { align: 'both' }))
      + (fotosRows ? secRow('Registro fotográfico') + fotosRows : '')
```

por:

```js
      + secRow('Insumos utilizados para el análisis') + fullRow(wP(wR(insumos), { align: 'both' }))
      + figBRow
      + (fotosRows ? secRow('Registro fotográfico') + fotosRows : '')
```

- [ ] **Step 4: Recargar el preview y verificar end-to-end con RM sintéticas**

Ejecutar en `javascript_tool` (crea 3 RM sintéticas: una con 3 fotos y azimuts distintos, una
con 1 foto sin azimut, una sin fotos — igual al caso de prueba del spec):

```js
(async () => {
  // JPEG 1x1 real (via canvas) para que blob/imgDims funcionen sin datos reales de cámara
  const fotoBlob = () => new Promise(res => {
    const c = document.createElement('canvas'); c.width = 4; c.height = 3;
    c.getContext('2d').fillRect(0, 0, 4, 3);
    c.toBlob(b => res(b), 'image/jpeg');
  });
  const b1 = await fotoBlob(), b2 = await fotoBlob(), b3 = await fotoBlob(), b4 = await fotoBlob();
  const records = [
    { data: { coords: { lat: -33.45, lng: -70.66 }, region: 'Metropolitana (RM)', 'fecha-inicio': '2026-07-01', confirmada: true },
      fotos: [{ blob: b1, desc: '', azimuth: 30 }, { blob: b2, desc: '', azimuth: 150 }, { blob: b3, desc: '', azimuth: 280 }] },
    { data: { coords: { lat: -33.50, lng: -70.70 }, region: 'Metropolitana (RM)', 'fecha-inicio': '2026-07-01', confirmada: true },
      fotos: [{ blob: b4, desc: '', azimuth: null }] },
    { data: { coords: { lat: -33.55, lng: -70.72 }, region: 'Metropolitana (RM)', 'fecha-inicio': '2026-07-01', confirmada: true },
      fotos: [] }
  ];
  const r = await generateRETERMCombinado(records, '05', true);
  const zip = await JSZip.loadAsync(r.blob);
  const docXml = await zip.file('word/document.xml').async('string');
  const mediaFiles = Object.keys(zip.files).filter(n => n.startsWith('word/media/'));
  return {
    tieneFiguraFotosAzimuth: mediaFiles.some(n => n.includes('figuraFotosAzimuth')),
    tieneFiguraB_Caption: docXml.includes('Figura B. Ubicación y azimut'),
    nMediaFiles: mediaFiles.length
  };
})()
```

Expected: `{ tieneFiguraFotosAzimuth: true, tieneFiguraB_Caption: true, nMediaFiles: <n> }` (n
incluye logo + figuraConjunto + figuraFotosAzimuth + 4 fotos = 7, salvo que la descarga
satelital haya fallado por conectividad, en cuyo caso `figConjunto`/`figFotosAzimuth` serán
`null` y no se generan esos dos archivos — repetir la verificación de todos modos con
conexión activa).

- [ ] **Step 5: Verificar el caso sin fotos usables en ninguna RM (no debe aparecer Figura B)**

```js
(async () => {
  const records = [
    { data: { coords: { lat: -33.45, lng: -70.66 }, region: 'Metropolitana (RM)', 'fecha-inicio': '2026-07-01', confirmada: true }, fotos: [] }
  ];
  const r = await generateRETERMCombinado(records, '05', true);
  const zip = await JSZip.loadAsync(r.blob);
  const docXml = await zip.file('word/document.xml').async('string');
  const mediaFiles = Object.keys(zip.files).filter(n => n.startsWith('word/media/'));
  return { tieneFiguraB_Caption: docXml.includes('Figura B'), tieneFiguraFotosAzimuth: mediaFiles.some(n => n.includes('figuraFotosAzimuth')) };
})()
```

Expected: `{ tieneFiguraB_Caption: false, tieneFiguraFotosAzimuth: false }`.

- [ ] **Step 6: Verificar que Figura A y Figura B comparten una sola descarga de red**

Con `mcp__Claude_Browser__read_network_requests` (no `javascript_tool`), limpiar el registro
recargando la página, ejecutar el mismo script del Step 4 (3 RM sintéticas) vía
`javascript_tool`, y luego llamar `read_network_requests` filtrando
`urlPattern: "World_Imagery"`.

Expected: **una sola** entrada `GET .../World_Imagery/MapServer/export...` (no dos) — confirma
que `descargarSatelital` se llamó una vez y su resultado se compartió entre
`capturarFiguraACombinada` y `capturarFiguraFotosAzimuth`.

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "feat: Figura B (fotos+azimut) en el RETERM compilado"
```

---

### Task 4: Bump de versión y publicación

**Files:**
- Modify: `catastro-remociones/index.html` (constante `APP_VER` / comentario de versión, y
  cache `remociones-vN` en `sw.js` si el proyecto lo requiere para forzar actualización del
  Service Worker — confirmar el nombre exacto de la constante de versión buscando `APP_VER` en
  el archivo antes de este paso, ya que no se leyó su valor actual en este plan)

- [ ] **Step 1: Buscar y confirmar el patrón de versión actual**

```bash
grep -n "APP_VER\|remociones-v" catastro-remociones/index.html catastro-remociones/sw.js | head -20
```

Incrementar el número de versión siguiendo el mismo patrón ya usado en v90-v97 (buscar el
último número usado en los commits recientes con `git log --oneline -5` dentro de
`catastro-remociones/`).

- [ ] **Step 2: Commit y push**

```bash
git add index.html sw.js
git commit -m "chore: bump version tras Figura B fotos+azimut"
git push
```

(Confirmar con el usuario antes de hacer `git push`, según las reglas de seguridad del
proyecto — no se hace push sin autorización explícita.)
