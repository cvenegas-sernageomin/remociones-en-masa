# Figura B: fotos de terreno + azimuth en el RETERM compilado

## Contexto

El RETERM compilado (varias RM en un solo `.docx`, `generateRETERMCombinado`, index.html) ya
incluye una **Figura A de conjunto** (`capturarFiguraACombinada`): imagen satelital Esri con
grilla UTM y un marcador rojo + etiqueta `RM-NN` por cada RM del reporte.

Las fotos de terreno (`rec.fotos[]`) no tienen coordenada GPS propia — solo un `azimuth`
(0–360°, dirección hacia la que apuntaba la cámara). Hoy ese azimuth solo aparece como texto
en el pie de cada foto en "Registro fotográfico" (`"🧭 120°N"`), nunca en un mapa.

Se pide una **segunda imagen (Figura B)** en el RETERM compilado: una imagen satelital que
ubique las fotos de terreno del reporte y simbolice el azimuth de cada una.

Alcance: **solo el RETERM compilado** (`generateRETERMCombinado`). El informe individual
(`generateRETERM`, una sola RM) no se toca.

## 1. Refactor compartido (bbox + descarga satelital)

Extraer de `capturarFiguraACombinada` (index.html:3907) dos helpers reutilizables, sin cambiar
su comportamiento actual:

- `calcularBBoxConjunto(puntos)` → `{west, east, north, south, latC, lngC, W, H}`. Mismo cálculo
  que hoy: envolvente de los puntos + margen 25% (mínimo `FIGURA_A_RADIO_M`), forzado a
  aspecto 4:3 (W=800, H=600).
- `descargarSatelital(bbox)` → hace el `fetch` a
  `server.arcgisonline.com/.../World_Imagery/MapServer/export` con ese bbox y devuelve un
  `<canvas>` ya con la imagen base dibujada (sin marcadores ni grilla). `null` si falla
  (timeout 12s u otro error), igual que hoy.

`capturarFiguraACombinada(puntos)` pasa a construir su bbox y su canvas base con estos
helpers, y dibuja encima grilla UTM + marcador rojo + etiqueta + escala — **idéntico
resultado visual al actual**, solo reorganizado.

`capturarFiguraFotosAzimuth(puntos)` (función nueva) recibe el **mismo array de puntos**
que ya arma `generateRETERMCombinado` para Figura A y por lo tanto obtiene el **mismo bbox**;
reutiliza el **mismo canvas base ya descargado** (se pasa como parámetro desde
`generateRETERMCombinado`, que llama `descargarSatelital` una sola vez y lo entrega a ambas
funciones de dibujo) — una sola llamada de red total para ambas figuras.

## 2. Datos de entrada y agrupación por RM

En `generateRETERMCombinado`, junto al array `puntos` que ya se arma para Figura A
(línea ~4013), se arma un array paralelo para Figura B:

```
gruposFotos = records.map((rec, i) => {
  const p = coordDe(rec.data);
  if (!p) return null;
  const fotosConDatos = (rec.fotos || [])
    .filter(f => f.blob || f.blobDataUrl)
    .map((f, k) => ({ numFoto: k + 1, azimuth: f.azimuth ?? null }));
  if (!fotosConDatos.length) return null;   // RM sin fotos usables: no aparece en Figura B
  return { label: rmLbl(i), lat: p.lat, lng: p.lng, fotos: fotosConDatos };
}).filter(Boolean);
```

- Solo entran RM con al menos una foto con `blob`/`blobDataUrl` real.
- Paleta fija de 8 colores, cíclica por índice de RM dentro de `gruposFotos` (no por índice
  global de `records`, para que los colores no salten si alguna RM intermedia no tiene fotos):
  `['#e63946','#3a86ff','#2a9d8f','#f4a261','#8338ec','#00b4d8','#ff70a6','#ffd60a']`.
- Por cada foto con `azimuth != null`: vector unitario con `dx = sin(az * PI/180)`,
  `dy = -cos(az * PI/180)` (0°=Norte arriba de la imagen, sentido horario, mapa siempre
  north-up — mismo supuesto que el resto de la app).
- Fotos con `azimuth == null`: se marcan aparte (sin vector), se dibujan como punto sin flecha.

## 3. Dibujo sobre el canvas (`capturarFiguraFotosAzimuth`)

Recibe `(gruposFotos, bbox, canvasBase)`. Clona `canvasBase` y dibuja encima:

1. **Grilla UTM** — igual a Figura A (mismas líneas amarillas + etiquetas E/N), para
   consistencia visual entre ambas figuras.
2. **Por cada grupo (RM) en `gruposFotos`**:
   - Marcador circular relleno del color de esa RM, contorno blanco, en su punto GPS
     (mismo tamaño/estilo que el marcador rojo de Figura A, pero coloreado por RM).
   - Por cada foto **con azimuth**: flecha desde el marcador hacia afuera, longitud fija
     ~38px, color de la RM, con punta de flecha simple (2 segmentos cortos en la punta).
     Etiqueta `RM0N-FK` junto a la punta (fondo `rgba(0,0,0,0.6)`, texto blanco, mismo
     estilo de etiqueta que usa Figura A para `RM-NN`).
   - Por cada foto **sin azimuth**: un aro pequeño (círculo sin relleno) alrededor del
     marcador de esa RM, sin flecha ni etiqueta individual — indica "hay una foto de este
     punto, dirección desconocida" sin inventar un ángulo.
3. **Leyenda** (esquina inferior u opuesta a la escala): un cuadro de fondo semitransparente
   con una línea por cada RM presente en `gruposFotos` — muestra de color + `RM-NN`.
4. **Escala aproximada** (200 m) — igual que Figura A.

Devuelve `canvas.toDataURL('image/jpeg', 0.85)`, o `null` si `canvasBase` es `null`
(descarga falló) o `gruposFotos` está vacío.

## 4. Ubicación en el documento y casos borde

En `generateRETERMCombinado`, justo antes de armar `fotosRows` (línea ~4115):

- Se calcula `gruposFotos` (sección 2) y se llama
  `capturarFiguraFotosAzimuth(gruposFotos, bboxConjunto, canvasBaseConjunto)`.
- **Si devuelve imagen**: se inserta como fila de ancho completo (mismo patrón `fullRow` +
  `wImg` que usan las fotos individuales), con caption:
  > "Figura B. Ubicación y azimut de las fotografías de terreno incluidas en este reporte
  > (imagen satelital con grilla UTM; cada flecha indica la dirección hacia la que apuntaba
  > la cámara al momento de tomarla)."
- **Si `gruposFotos` queda vacío** (ninguna RM aporta foto usable) **o la descarga falló**:
  se omite la fila completa — sin placeholder ni texto de "figura no disponible". No tiene
  sentido señalar una figura faltante cuando no hay fotos que mostrar; y si fue por falla de
  red, ya se pierde silenciosamente igual que Figura A en el mismo caso.
- El resto de "Registro fotográfico" (línea ~4115 en adelante) **no cambia**: sigue listando
  cada foto individualmente con su descripción + azimuth en texto. Figura B es un índice
  visual adicional, nunca un reemplazo de esa sección.
- La numeración `RM0N-FK` de Figura B usa el mismo índice `k+1` que ya usa el caption de cada
  foto individual más abajo (`'RM-01 — Fotografía 1'`) — deben coincidir para que el lector
  pueda cruzar una flecha del mapa con su foto en la sección siguiente.

## Fuera de alcance

- No se toca el informe individual (`generateRETERM`, una sola RM) ni su Figura A propia
  (`capturarFiguraA`).
- No se agregan coordenadas GPS individuales por foto (siguen heredando la coordenada de su RM).
- No se resuelve superposición de flechas cuando dos fotos de la misma RM tienen azimuth
  casi idéntico (quedarían visualmente encimadas) — no se pidió y añade complejidad sin caso
  de uso reportado; si aparece en uso real, ver GOTCHA a futuro.
- No se agrega esta figura al KMZ compilado ni al respaldo JSON — es exclusiva del `.docx`.

## Verificación planeada

En preview (Browser MCP, pruebas programáticas — ver `feedback-preview-mcp-roto`, no confiar
en screenshots para el estado real):

- RETERM compilado con 3 RM sintéticas: 1 con 3 fotos (azimuths distintos), 1 con 1 foto sin
  azimuth, 1 sin fotos → Figura B debe mostrar 2 marcadores (no 3), un abanico de 3 flechas
  etiquetadas RM01-F1/F2/F3, un aro sin flecha en la RM sin azimuth, leyenda con 2 colores.
- Verificar que Figura A y Figura B comparten exactamente el mismo encuadre (mismos bbox
  numéricos) y que solo hubo una descarga de red al generar (`read_network_requests`).
- Caso sin ninguna foto usable en ninguna RM → no aparece fila de Figura B, resto del
  documento sin cambios (diff contra un RETERM compilado generado antes de este cambio).
- Caso de falla de red simulada (bloquear el dominio de Esri) → informe se genera igual,
  sin Figura A ni B, sin excepción no capturada.
