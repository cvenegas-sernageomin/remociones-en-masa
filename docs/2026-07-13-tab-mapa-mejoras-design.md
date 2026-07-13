# Tab de Mapa + mejoras portables — catastro-remociones

Fecha: 2026-07-13 · Estado: aprobado, en implementación

## Objetivo
Portar a `catastro-remociones` (PWA de remociones en masa) el "Modo Mapa" y las mejoras
de alto valor de GeoTerreno CDC, **sin** reescribir el wizard de 5 pasos.

Alcance elegido por el usuario: **Mapa + mejoras portables** (NO foto-mapa, NO acordeón,
NO migración de arquitectura).

## Componentes

### 1. Barra de vistas (tab bar)
Switch en el header: `📝 Ficha` (wizard actual) ⇄ `🗺️ Mapa`.
`showView(v)` alterna: en `mapa` oculta `#progress-bar`, `.step`, `#nav-buttons` y muestra
`#mapa-view`; en `ficha` restaura vía `goToStep(currentStep)`. `APP_VER` visible en el header.

### 2. Tab de Mapa (`#mapa-full`)
Leaflet + Esri World Imagery + tiles offline (mismo patrón que `initMap`). Muestra:
- Todas las RM guardadas (`rmGetAll`) como marcadores `divIcon`: círculo por zona
  (`ZONA_COLOR`) + simbología estructural SVG superpuesta (`data['estructuras-dip']`).
  Tooltip = ID; clic → `populateForm` + `showView('ficha')`.
- La RM en edición (form vivo) como marcador aparte.
- Líneas geológicas del store `lineas`.
- Botón leyenda `ⓘ`, botón `⬇️ Tiles` (descarga área visible), contador de puntos.

### 3. Simbología estructural (portada de GeoTerreno)
`_uv/_hl/_ht/simboloPlano/simboloLinea/svgEstructura`, adaptada a `{tipo, strike, dip,
trend, plunge}` de catastro. `strike` = rumbo RHR → az del plano. Falla = `tipo==='Falla'`.

### 4. Líneas geológicas dibujables
`LINEA_TIPOS/CERTEZA/COLOR/DASH`. Botón `✏️ Línea` activa dibujo (clic = vértice, banner
Finalizar/Cancelar). Al finalizar, mini-form tipo+certeza → store `lineas`
(`{id, geom:[[lat,lng]...], tipo, certeza}`). Clic en línea existente = editar/eliminar.
Export en `generateCombinedKMZ` como `LineString` con color por tipo.

### 5. Clinómetro combinado (trend/plunge)
Portar la matemática vectorial de GeoTerreno (`anglesFromEvent/ejesMundo/planoDeNormal/
lineaDeVector/medirEstructura`). En cada entrada de estructura: campos TREND/PLUNGE +
botones `📐 Medir plano` / `📏 Plano+línea`. `getEstDipValues` incluye trend/plunge.
Se conserva el `📡` actual como alias del plano.

### 6. Auto-actualización (infra)
- `sw.js`: **network-first para el HTML**, cache-first para assets, bypass de tiles
  `arcgisonline.com` (leaflet.offline). `CACHE_NAME` → `remociones-v6`.
- `index.html`: `controllerchange`→`location.reload()` con guarda anti-loop.
- `APP_VER` visible.

### 7. IndexedDB robusto
`rmDbOpen` → versión **2**: crea `rms` (si falta) + `lineas` (keyPath `id`). Manejo
`onblocked`/timeout/`onversionchange`→close. Helpers `lineaGetAll/lineaPut/lineaDelete`.

## Fuera de alcance
foto-mapa, editor en acordeón, migración a `nav()`/vendored libs.

## Riesgos controlados
- Libs por CDN se mantienen (SW las cachea).
- Cambio de esquema IndexedDB con bump de versión + `onupgradeneeded` idempotente.
- `invalidateSize()` al mostrar el mapa.

## Verificación
Preview local (`python -m http.server`) + navegador: alternar vistas, marcadores con
simbología, dibujar y exportar una línea al KMZ del día, y (en escritorio) confirmar que
la matemática del clinómetro no rompe el ingreso manual.
