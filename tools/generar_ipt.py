# -*- coding: utf-8 -*-
"""
Genera los archivos de la capa "IPT" de la PWA remociones-en-masa, POR REGION:

  ipt/ipt_<region>.json   GeoJSON compacto de una region
  ipt/manifest.json       indice que lee la PWA (id, nombre, archivo, bbox, n)

Agregar una region nueva = agregar su entrada en REGIONES (apuntando a la carpeta
con los shapefiles) y correr este script. No hay que tocar index.html.

Estructura esperada de la carpeta fuente (como IPT_Atacama):
  LU/   Limites urbanos               (poligonos)
  PRC/  Planes Reguladores Comunales  (poligonos; *ZNE* = lineas no edificables)
  PRI/  Plan Regulador Intercomunal   (poligonos)
Si una region no tiene alguna subcarpeta, simplemente se omite ese grupo.

Formato del JSON por region:
- FeatureCollection con miembro extra "zonas": diccionario deduplicado con la
  descripcion de cada zona (n=nombre, p=usos permitidos, x=prohibidos, d=documento);
  cada feature lleva solo la clave (z) + grupo (g) + comuna/localidad.
- Geometrias simplificadas en metros ANTES de reproyectar (LU/PRC 2 m, PRI 10 m:
  error menor que el GPS de terreno; a 5 m el PRI de Atacama quedaba en 9 MB).
- Coordenadas WGS84 con 5 decimales (~1.1 m), consistente con la simplificacion.

Ademas de las regiones IPT, genera una capa nacional de referencia:
  ipt/division_comunal.json  346 comunas (SUBDERE), grupo 'DC', auto:false
  (entra al mismo panel como pseudo-region que NO se autoselecciona porque
  cubre todo Chile; se prende a mano).

Uso:
  python tools/generar_ipt.py                    # todo (regiones + division comunal)
  python tools/generar_ipt.py atacama            # solo una region
  python tools/generar_ipt.py division_comunal   # solo la capa nacional de comunas
"""
import glob
import json
import os
import re
import sys
import warnings
from datetime import date

warnings.filterwarnings('ignore')
import geopandas as gpd  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

# ---- Configuracion de regiones -------------------------------------------------
# Regiones desde SHAPEFILES locales: id -> nombre visible + carpeta fuente.
REGIONES = {
    'atacama': {
        'nombre': 'Atacama',
        'src': r'C:\Users\carlos.venegas\Documents\Sernageomin_Emergencia 2026\IPT_Atacama',
    },
}

# Regiones desde el REST OFICIAL de MINVU (geoide.minvu.cl) — fuente autoritativa
# nacional de IPT, publica y con CORS. Se consulta directo (snapshot), SIN shapefiles.
# Es la fuente por defecto para regiones nuevas: basta agregar aqui la region con sus
# servicios FeatureServer. Cada servicio se mapea con 'auto' (clasifica cada capa por
# su nombre → PRC/PRI/AR/LU/ZNE) o un grupo fijo (p.ej. 'PRDU' para todo el servicio).
MINVU_BASE = 'https://geoide.minvu.cl/server/rest/services/IPT'
REGIONES_MINVU = {
    'coquimbo': {
        'nombre': 'Coquimbo',
        'servicios': {
            'PRC_Coquimbo': 'auto',     # planes reguladores comunales + limites urbanos + areas de riesgo comunales
            'PRI_Coquimbo': 'auto',     # planes intercomunales (Elqui/Limari) + zonas no edificables + areas de riesgo
            'PRDU_Coquimbo': 'PRDU',    # plan regional de desarrollo urbano (todo el servicio)
        },
    },
    'valparaiso': {
        'nombre': 'Valparaíso',
        'servicios': {
            # ojo: el nombre del servicio PRC lleva tilde en la URL (PRC_Valparaíso),
            # el de PRI no (PRI_Valparaiso) — asi estan publicados en geoide.minvu.cl.
            'PRC_Valparaíso': 'auto',   # ~50 subcapas: un PRC por comuna + seccionales + AR/ZNE de algunas comunas
            'PRI_Valparaiso': 'auto',
        },
        # sin PRDU: MINVU no publica PRDU_Valparaiso (solo existe para Arica y Parinacota, Coquimbo, OHiggins)
    },
}

# Capa nacional de referencia: division comunal SUBDERE (346 comunas, todo Chile).
# Entra al mismo panel IPT como pseudo-region con auto:false (no se autoselecciona
# porque su bbox toca cualquier vista). Grupo 'DC'.
DIVISION_COMUNAL = {
    'id': 'division_comunal',
    'nombre': 'División comunal (Chile)',
    'shp': r'C:\Users\carlos.venegas\Documents\Sernageomin_Emergencia 2026'
           r'\IPT_Atacama\division_comunal\division_comunal\division_comunal.shp',
    'tol': 200,     # m; el shapefile fuente trae 2.7M vertices (46 MB); a 100 m quedaba en 10.7 MB
    'decimales': 4, # ~11 m — consistente con la tolerancia; es capa de referencia, no de precision
}

# tolerancia de simplificacion en metros, por grupo. Los IPT son referencia de
# planificacion (no medicion de precision), asi que unos metros de error en los
# bordes de zona son aceptables y bajan mucho el peso para uso movil en terreno.
TOL = {'LU': 3, 'PRC': 15, 'PRI': 20, 'PRDU': 40, 'AR': 40, 'ZNE': 8}
DECIMALES = 5

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, 'ipt')


def val(row, *cols):
    """Primer valor no vacio entre varias columnas alternativas."""
    for c in cols:
        if c in row.index:
            v = row[c]
            if v is not None and str(v).strip() and str(v).strip().lower() != 'none':
                return str(v).strip()
    return ''


def round_coords(obj, dec=DECIMALES):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(x, dec) for x in obj]
        return [round_coords(o, dec) for o in obj]
    return obj


def escribir_por_grupo(rid, nombre, acum, extra=None):
    """Parte el acumulado de una region en un archivo JSON por grupo (PRC/PRI/AR/…) y
    devuelve la entrada de manifest con la lista de grupos disponibles. Cada archivo lleva
    sus features + solo las zonas que usa. Asi la PWA baja cada categoria on-demand
    (crucial para regiones pesadas: las Areas de Riesgo de Coquimbo pesan lo que todo Atacama)."""
    from collections import defaultdict
    porg = defaultdict(list)
    for f in acum['features']:
        porg[f['properties']['g']].append(f)
    if not porg:
        print(f'[{rid}] sin features — no se genera archivo')
        return None
    grupos_meta = []
    for g in sorted(porg):
        feats = porg[g]
        zk = {f['properties'].get('z') for f in feats if f['properties'].get('z')}
        zonas = {k: acum['zonas'][k] for k in zk if k in acum['zonas']}
        archivo = f'{rid}_{g}.json'
        with open(os.path.join(OUT_DIR, archivo), 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'zonas': zonas, 'features': feats},
                      fh, ensure_ascii=False, separators=(',', ':'))
        kb = os.path.getsize(os.path.join(OUT_DIR, archivo)) / 1024
        grupos_meta.append({'g': g, 'archivo': archivo, 'n': len(feats)})
        print(f'[{rid}]   {archivo}: {len(feats)} features, {kb:.0f} KB')
    entrada = {
        'id': rid, 'nombre': nombre,
        'bbox': [round(v, 4) for v in acum['bbox']],
        'grupos': grupos_meta,
        'n': len(acum['features']),
        'generado': date.today().isoformat(),
    }
    if extra:
        entrada.update(extra)
    return entrada


def procesar_gdf(gdf, g, acum, tol=None):
    """Agrega las filas de un GeoDataFrame (EPSG:4326) al acumulador de una region.
    `g` = grupo (PRC/PRI/PRDU/AR/LU/ZNE). `acum` = dict con features/zonas/zkeys/bbox.
    Si `tol` (metros) se pasa, simplifica reproyectando a UTM 19S. Devuelve nº de filas OK.
    """
    if tol:
        gdf = gdf.copy()
        gdf = gdf.to_crs(epsg=32719) if (gdf.crs and gdf.crs.to_epsg() != 32719) else gdf.to_crs(epsg=32719)
        gdf['geometry'] = gdf.geometry.simplify(tol, preserve_topology=True)
        gdf = gdf.to_crs(epsg=4326)
    features, zonas, zkeys, bbox = acum['features'], acum['zonas'], acum['zkeys'], acum['bbox']
    n_ok = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        com = val(row, 'COM', 'COMUNA')
        loc = val(row, 'LOCALIDAD', 'LOC', 'SECTOR')
        zona = val(row, 'ZONA')
        nom = val(row, 'NOMBRE', 'NOM', 'CATEGORIA')
        up = val(row, 'UPERM')
        ux = val(row, 'UPROH')
        doc = val(row, 'INSTRUMENT', 'T_DO', 'T_DOC', 'DOC', 'DO')
        info = val(row, 'INFO')            # PRDU: descripcion general
        cond = val(row, 'CONDICIO')        # PRDU: condiciones
        if g in ('LU', 'ZNE', 'AR') and not zona:
            zona = g

        comp = (g, zona, nom, up, ux, doc, info, cond)
        if comp not in zkeys:
            zk = f'{g}:{zona or nom or len(zkeys)}'
            base_zk, i = zk, 2
            while zk in zonas:
                zk = f'{base_zk}~{i}'
                i += 1
            zkeys[comp] = zk
            zonas[zk] = {k: v for k, v in
                         (('n', nom), ('p', up), ('x', ux), ('d', doc), ('i', info), ('c', cond)) if v}
        zk = zkeys[comp]

        b = geom.bounds
        bbox[0] = min(bbox[0], b[0]); bbox[1] = min(bbox[1], b[1])
        bbox[2] = max(bbox[2], b[2]); bbox[3] = max(bbox[3], b[3])
        features.append({
            'type': 'Feature',
            'properties': {k: v for k, v in
                           (('g', g), ('z', zk), ('com', com), ('loc', loc)) if v},
            'geometry': round_coords(mapping(geom)),
        })
        n_ok += 1
    return n_ok


def generar_region(rid, cfg):
    src = cfg['src']
    if not os.path.isdir(src):
        print(f'[{rid}] AVISO: no existe la carpeta fuente {src} — omitida')
        return None

    acum = {'features': [], 'zonas': {}, 'zkeys': {}, 'bbox': [180.0, 90.0, -180.0, -90.0]}

    for shp in sorted(glob.glob(os.path.join(src, '**', '*.shp'), recursive=True)):
        rel = os.path.relpath(shp, src)
        grupo = rel.split(os.sep)[0].upper()   # LU / PRC / PRI
        if grupo not in TOL:
            # carpeta no estandar: intentar deducir del nombre del archivo
            nombre_arch = os.path.basename(shp).upper()
            grupo = next((g for g in ('PRI', 'PRC', 'LU') if g in nombre_arch), None)
            if not grupo:
                print(f'[{rid}] AVISO: {rel} sin grupo LU/PRC/PRI reconocible — omitido')
                continue
        if 'ZNE' in os.path.basename(shp).upper():
            grupo = 'ZNE'

        gdf = gpd.read_file(shp)
        if gdf.crs is None:
            print(f'[{rid}] AVISO: {rel} sin CRS — omitido')
            continue
        n_ok = procesar_gdf(gdf, grupo, acum, tol=TOL.get(grupo, 2))
        print(f'[{rid}] {rel}: {n_ok} features (grupo {grupo})')

    return escribir_por_grupo(rid, cfg['nombre'], acum)


def generar_division_comunal():
    cfg = DIVISION_COMUNAL
    if not os.path.isfile(cfg['shp']):
        print(f"[{cfg['id']}] AVISO: no existe {cfg['shp']} — omitida")
        return None
    gdf = gpd.read_file(cfg['shp'])
    gdf = gdf.to_crs(epsg=32719) if (gdf.crs and gdf.crs.to_epsg() != 32719) else gdf
    gdf['geometry'] = gdf.geometry.simplify(cfg['tol'], preserve_topology=True)
    gdf = gdf.to_crs(epsg=4326)

    dec = cfg.get('decimales', DECIMALES)
    features = []
    bbox = [180.0, 90.0, -180.0, -90.0]
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        b = geom.bounds
        bbox[0] = min(bbox[0], b[0]); bbox[1] = min(bbox[1], b[1])
        bbox[2] = max(bbox[2], b[2]); bbox[3] = max(bbox[3], b[3])
        features.append({
            'type': 'Feature',
            'properties': {k: v for k, v in (
                ('g', 'DC'),
                ('com', val(row, 'NOM_COM')),
                ('loc', val(row, 'NOM_PROV')),                                  # provincia en el campo "loc"
                ('reg', val(row, 'NOM_REG')),                                   # nombre de región tal cual (ya trae "Región de/del/Metropolitana…")
            ) if v},
            'geometry': round_coords(mapping(geom), dec),
        })

    acum = {'features': features, 'zonas': {}, 'zkeys': {}, 'bbox': bbox}
    # nunca autoseleccionar (cubre todo Chile); DC no tiene checkbox de categoria
    return escribir_por_grupo(cfg['id'], cfg['nombre'], acum, extra={'auto': False})


# ---- Regiones desde el REST de MINVU -------------------------------------------
_ACENTOS = str.maketrans('áéíóúÁÉÍÓÚ', 'aeiouAEIOU')


def clasificar_capa(nombre):
    """Grupo IPT segun el nombre de la capa MINVU (sin acentos, minuscula)."""
    # normaliza "_" a espacio ANTES de aplicar \b: en regex "_" es caracter de palabra,
    # asi que "..._zne" no tiene frontera antes de la z y \bzne\b no calzaba (bug real,
    # visto en "IPT_PRC_05_LosAndes_ZNE" -> quedaba mal clasificado como PRC).
    n = nombre.translate(_ACENTOS).lower().replace('_', ' ')
    if 'riesgo' in n:
        return 'AR'                       # area de riesgo (prioritario: aplica sobre PRC/PRI)
    if 'no edificable' in n or re.search(r'\bzne\b', n):
        return 'ZNE'                       # incluye nombres abreviados tipo "PRC LosAndes ZNE"
    if 'limite urbano' in n or 'limites urbano' in n:
        return 'LU'                       # cubre singular y plural ("Limites Urbanos")
    if 'prdu' in n:
        return 'PRDU'
    if n.startswith('pri') or ' pri' in n or '_pri' in n:
        return 'PRI'
    return 'PRC'


def _query_layer_geojson(base, lid, maxrec=2000):
    import requests
    feats, offset = [], 0
    while True:
        params = {'where': '1=1', 'outFields': '*', 'outSR': 4326, 'f': 'geojson',
                  'returnGeometry': 'true', 'resultOffset': offset, 'resultRecordCount': maxrec}
        r = requests.get(f'{base}/{lid}/query', params=params, timeout=120)
        r.raise_for_status()
        fs = r.json().get('features', [])
        feats.extend(fs)
        if len(fs) < maxrec:
            break
        offset += maxrec
    return feats


def generar_region_minvu(rid, cfg):
    acum = {'features': [], 'zonas': {}, 'zkeys': {}, 'bbox': [180.0, 90.0, -180.0, -90.0]}
    import requests
    for svc, modo in cfg['servicios'].items():
        base = f'{MINVU_BASE}/{svc}/FeatureServer'
        try:
            capas = requests.get(f'{base}/layers', params={'f': 'json'}, timeout=60).json().get('layers', [])
        except Exception as e:
            print(f'[{rid}] {svc}: no se pudieron listar capas ({e})')
            continue
        for capa in capas:
            lid, nom, geot = capa['id'], capa['name'], capa.get('geometryType', '')
            if geot == 'esriGeometryPoint':
                continue      # los puntos (p.ej. "Area de Riesgo Punto") no encajan en el render de zonas
            grupo = modo if modo != 'auto' else clasificar_capa(nom)
            try:
                feats = _query_layer_geojson(base, lid)
            except Exception as e:
                print(f'[{rid}] {svc}/{lid} {nom}: query fallo ({e})')
                continue
            if not feats:
                continue
            gdf = gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326')
            n = procesar_gdf(gdf, grupo, acum, tol=TOL.get(grupo, 5))
            print(f'[{rid}] {svc}/{lid} {nom} -> {grupo}: {n} features')

    return escribir_por_grupo(rid, cfg['nombre'], acum, extra={'fuente': 'MINVU'})


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pedidas = [a.lower() for a in sys.argv[1:]] or (
        list(REGIONES) + list(REGIONES_MINVU) + [DIVISION_COMUNAL['id']])
    manifest_path = os.path.join(OUT_DIR, 'manifest.json')
    # partir del manifest existente para no perder regiones no regeneradas en esta corrida
    previas = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding='utf-8') as f:
                previas = {r['id']: r for r in json.load(f).get('regiones', [])}
        except Exception:
            pass

    for rid in pedidas:
        if rid == DIVISION_COMUNAL['id']:
            entrada = generar_division_comunal()
        elif rid in REGIONES_MINVU:
            entrada = generar_region_minvu(rid, REGIONES_MINVU[rid])
        elif rid in REGIONES:
            entrada = generar_region(rid, REGIONES[rid])
        else:
            conf = ', '.join(list(REGIONES) + list(REGIONES_MINVU) + [DIVISION_COMUNAL['id']])
            print(f'Region desconocida: {rid} (configuradas: {conf})')
            continue
        if entrada:
            previas[rid] = entrada

    # regiones primero (orden alfabetico), capas nacionales (auto:false) al final
    regiones = sorted(previas.values(), key=lambda r: (r.get('auto') is False, r['nombre']))
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump({'regiones': regiones}, f, ensure_ascii=False, indent=1)
    print(f'\nmanifest.json: {len(regiones)} region(es): {", ".join(r["nombre"] for r in regiones)}')


if __name__ == '__main__':
    main()
