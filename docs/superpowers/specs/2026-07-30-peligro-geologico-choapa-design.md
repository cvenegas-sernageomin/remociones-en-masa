# Peligro Geológico Choapa (DCR + SFL) en el RETERM

## Contexto

El usuario compartió un dashboard ArcGIS público
(`https://www.arcgis.com/apps/dashboards/3ba65a1f7ae644f5a247b8026330e348`, "Plataforma de
Peligro Geológico (Piloto)") que muestra dos mapas de susceptibilidad para el **sector sur de
la Región de Coquimbo** (provincia de Choapa: Canela, Illapel, Los Vilos, Salamanca), citando
el informe SERNAGEOMIN IR-21-88 (Brantt/Pantoja/Muñoz 2021).

Investigación previa (sesión de brainstorming) confirmó:

- Detrás hay un único FeatureServer público, sin token, con CORS habilitado:
  `https://services1.arcgis.com/OyjvVdFTl5hfSdX3/arcgis/rest/services/Mapa_de_Peligro_Geológico_de_Coquimbo_500_WFL1/FeatureServer/0`
  (capa `PeligrosGeologicosCoquimbo`, polígonos, 165.343 features).
- Cada polígono lleva **dos clasificaciones simultáneas** (mismos polígonos base, dos campos):
  - `DCR` — Susceptibilidad de Deslizamiento y Caída de Rocas (Alta/Moderada/Baja).
  - `SFL` — Susceptibilidad de Flujos de Detritos (Alta/Moderada/Baja).
- Una consulta de punto (`geometryType=esriGeometryPoint&spatialRel=esriSpatialRelIntersects`)
  devuelve **ambos valores en una sola llamada** (verificado en vivo: punto en Illapel →
  `{SFL:"Moderada", DCR:"Baja", COMUNA:"Illapel", REGION:"Coquimbo"}`; punto fuera de Choapa →
  `features: []`, sin error).
- La otra capa que aparece en el mismo dashboard (`Remociones_en_Masa_Chile`, MapServer)
  requiere un token interno de SERNAGEOMIN — no es accesible desde la PWA pública, **queda
  fuera de alcance**.

El usuario pidió traer ambas clasificaciones (con sus 3 niveles cada una) — **no como capa
visualizable en el mapa**, sino como dato automático en el informe RETERM: dónde cae la RM
catastrada según esta clasificación.

## Decisión de arquitectura: consulta en vivo, no dataset local

A diferencia de comuna (346 polígonos) y zona morfoclimática (119 zonas), que se descargan
una vez y se cachean localmente para ray casting offline, esta capa tiene 165.343 polígonos —
demasiado denso para replicar ese patrón sin trabajo de simplificación/disolución adicional.
El usuario, al ver el trade-off (offline garantizado vs. simplicidad), **eligió consulta en
vivo al servidor ArcGIS en el momento de mover el marcador**, aceptando que si no hay conexión
en ese momento el dato queda ausente (igual que ya ocurre hoy con la precipitación vía
Open-Meteo o la Figura A satelital — fallas de red se degradan a "sin dato", nunca bloquean
el flujo).

## 1. Disparo automático con debounce

En `actualizarRegionComunaDisplay()` (index.html:1914 — misma función que ya recalcula
comuna/región y zona morfoclimática en cada movimiento del marcador), se agrega la consulta
de peligro geológico Choapa con un **debounce de 700ms** (mismo orden de magnitud que otros
debounces ya usados en la app, ej. recompute de pronóstico) para no disparar una llamada de
red en cada reposicionamiento rápido del marcador.

```
GET https://services1.arcgis.com/OyjvVdFTl5hfSdX3/arcgis/rest/services/
    Mapa_de_Peligro_Geológico_de_Coquimbo_500_WFL1/FeatureServer/0/query
    ?geometry={"x":lng,"y":lat,"spatialReference":{"wkid":4326}}
    &geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects
    &outFields=SFL,DCR&returnGeometry=false&f=json
```

Con `AbortSignal.timeout(8000)` (mismo timeout usado en otras llamadas de la app, ej. Figura
A satelital). **Token de "última consulta gana"**: cada llamada a la función de debounce
incrementa un contador (`_peligroChoapaGen`, mismo patrón que `_mapaFullRenderGen` de v97); si
al resolver la promesa el contador ya no es el más reciente, se descarta la respuesta sin
tocar el cache — evita que una respuesta tardía de una posición vieja del marcador sobrescriba
el resultado de la posición actual.

## 2. Cache en memoria

Nueva variable `ultimaPeligroChoapa` (null por defecto), mismo patrón que
`ultimaComunaRegion`/`ultimaZonaMorfo` (index.html:1909-1913):

- Consulta exitosa con `features.length > 0` → `{dcr: f.attributes.DCR, sfl: f.attributes.SFL}`.
- `features` vacío (punto fuera de Choapa), fetch fallido, o timeout → `null`.
- Se resetea a `null` en `resetFormForNewRM` (línea ~4925, junto a `ultimaComunaRegion`/
  `ultimaZonaMorfo`), simétrico con esas dos.

**Sin feedback en pantalla** durante la captura (decisión del usuario): a diferencia de
comuna/zona morfoclimática, esta clasificación no tiene un elemento visual en el wizard —
el cache solo se lee al generar el informe.

## 3. Persistencia en `collectFormData()`

Se guarda desde el cache (mismo patrón que `morfo-zona`/`morfo-nivel`, línea ~3510-3515):

```
data['peligro-dcr'] = ultimaPeligroChoapa ? ultimaPeligroChoapa.dcr : '';
data['peligro-sfl'] = ultimaPeligroChoapa ? ultimaPeligroChoapa.sfl : '';
```

Al reabrir una RM guardada para editar, estos campos persisten tal como se guardaron (no se
re-consultan a menos que el usuario mueva el marcador de nuevo) — mismo comportamiento ya
establecido para comuna/zona morfoclimática.

## 4. Frase en conclusiones del RETERM

En `construirContenidoReterm(data, opts)` — función compartida entre el informe individual
(`generateRETERM`) y el compilado (`generateRETERMCombinado`), así que ambos se benefician
sin tocarlos por separado — nueva entrada en `concluParts`, **solo si `data['peligro-dcr']`
tiene valor** (punto dentro de Choapa):

> "Según el Mapa de Peligro Geológico de Coquimbo (SERNAGEOMIN, sector sur — provincia de
> Choapa), el punto se emplaza en un sector con susceptibilidad **{DCR}** de deslizamiento y
> caída de rocas, y susceptibilidad **{SFL}** de flujos de detritos."

Si no hay dato (fuera de Choapa, o sin conexión al momento de mover el marcador): no se agrega
ninguna oración ni marcador de "sin dato" — mismo criterio que zona morfoclimática cuando la
zona no tiene nivel calificado.

## 5. Fila en el KMZ

Mismo patrón que la fila "Zona morfoclimática" (buildKML / generateCombinedKMZ): nueva fila
**"Peligro geológico (Choapa)"** con valor `"Deslizamiento/Caída de rocas: {DCR} · Flujos de
detritos: {SFL}"`, agregada solo si hay dato.

## Fuera de alcance

- No se visualiza como capa en el mapa (Tab de Mapa) — confirmado explícitamente por el
  usuario, es solo para el informe.
- No se agrega la cita bibliográfica (IR-21-88, Brantt/Pantoja/Muñoz 2021) automáticamente a
  la sección Referencias del RETERM (selector manual existente desde v75) — si el usuario
  quiere citarla, la selecciona a mano si está en la lista de 52 referencias.
- No se trae la capa `Remociones_en_Masa_Chile` (requiere token interno SERNAGEOMIN,
  inaccesible desde la PWA pública).
- No se pre-descarga ni se cachea el dataset localmente — si no hay señal al mover el
  marcador, el dato queda ausente para esa RM (aceptado explícitamente por el usuario).

## Verificación planeada

En preview (Browser MCP, pruebas programáticas):

- Marcador dentro de Illapel/Choapa → tras ~700ms, `ultimaPeligroChoapa` refleja
  `{dcr,sfl}` reales (comparar contra consulta directa a la API); frase aparece en
  conclusiones del RETERM individual y del compilado; fila aparece en el KMZ.
- Marcador fuera de Choapa (ej. Santiago) → `ultimaPeligroChoapa` queda `null`; sin frase, sin
  fila KMZ, sin error visible.
- Mover el marcador varias veces rápido (simulando drags sucesivos) → solo la última posición
  determina el resultado final (verificar que el token de "última consulta gana" descarta
  respuestas tardías de posiciones intermedias).
- Simular fallo de red (bloquear el dominio del FeatureServer) → informe se genera igual, sin
  la frase, sin excepción no capturada.
- Editar una RM guardada con dato ya persistido → la frase/fila reaparecen sin necesidad de
  mover el marcador de nuevo (leídas desde `data['peligro-dcr']`/`data['peligro-sfl']`
  guardados).
