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
import sys
import warnings
from datetime import date

warnings.filterwarnings('ignore')
import geopandas as gpd  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

# ---- Configuracion de regiones -------------------------------------------------
# id (slug del archivo) -> nombre visible + carpeta con los shapefiles fuente
REGIONES = {
    'atacama': {
        'nombre': 'Atacama',
        'src': r'C:\Users\carlos.venegas\Documents\Sernageomin_Emergencia 2026\IPT_Atacama',
    },
    # 'coquimbo': {'nombre': 'Coquimbo', 'src': r'...\IPT_Coquimbo'},
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

# tolerancia de simplificacion en metros, por grupo
TOL = {'LU': 2, 'PRC': 2, 'PRI': 10}
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


def generar_region(rid, cfg):
    src = cfg['src']
    if not os.path.isdir(src):
        print(f'[{rid}] AVISO: no existe la carpeta fuente {src} — omitida')
        return None

    features = []
    zonas = {}       # zkey -> {n: nombre, p: permitido, x: prohibido, d: documento}
    zkeys = {}       # (contenido compuesto) -> zkey, para dedupe
    bbox = [180.0, 90.0, -180.0, -90.0]

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
        es_zne = 'ZNE' in os.path.basename(shp).upper()
        g = 'ZNE' if es_zne else grupo

        gdf = gpd.read_file(shp)
        if gdf.crs is None:
            print(f'[{rid}] AVISO: {rel} sin CRS — omitido')
            continue
        gdf = gdf.to_crs(epsg=32719) if gdf.crs.to_epsg() != 32719 else gdf
        gdf['geometry'] = gdf.geometry.simplify(TOL.get(grupo, 2), preserve_topology=True)
        gdf = gdf.to_crs(epsg=4326)

        n_ok = 0
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            com = val(row, 'COM', 'COMUNA')
            loc = val(row, 'LOCALIDAD', 'LOC', 'SECTOR')
            zona = val(row, 'ZONA')
            nom = val(row, 'NOMBRE', 'NOM')
            up = val(row, 'UPERM')
            ux = val(row, 'UPROH')
            doc = val(row, 'INSTRUMENT', 'T_DO', 'T_DOC', 'DOC')
            if g == 'LU' and not zona:
                zona = 'LU'

            comp = (g, zona, nom, up, ux, doc)
            if comp not in zkeys:
                zk = f'{g}:{zona or nom or len(zkeys)}'
                base_zk, i = zk, 2
                while zk in zonas:
                    zk = f'{base_zk}~{i}'
                    i += 1
                zkeys[comp] = zk
                zonas[zk] = {k: v for k, v in
                             (('n', nom), ('p', up), ('x', ux), ('d', doc)) if v}
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
        print(f'[{rid}] {rel}: {n_ok} features (grupo {g})')

    if not features:
        print(f'[{rid}] sin features — no se genera archivo')
        return None

    archivo = f'ipt_{rid}.json'
    out_path = os.path.join(OUT_DIR, archivo)
    fc = {'type': 'FeatureCollection', 'zonas': zonas, 'features': features}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(out_path) / 1024
    print(f'[{rid}] -> {archivo}: {len(features)} features, {len(zonas)} zonas, {kb:.0f} KB')

    return {
        'id': rid,
        'nombre': cfg['nombre'],
        'archivo': archivo,
        'bbox': [round(v, 4) for v in bbox],
        'n': len(features),
        'generado': date.today().isoformat(),
    }


def generar_division_comunal():
    cfg = DIVISION_COMUNAL
    if not os.path.isfile(cfg['shp']):
        print(f"[{cfg['id']}] AVISO: no existe {cfg['shp']} — omitida")
        return None
    gdf = gpd.read_file(cfg['shp'])
    gdf = gdf.to_crs(epsg=32719) if (gdf.crs and gdf.crs.to_epsg() != 32719) else gdf
    gdf['geometry'] = gdf.geometry.simplify(cfg['tol'], preserve_topology=True)
    gdf = gdf.to_crs(epsg=4326)

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
            'geometry': round_coords(mapping(geom), cfg.get('decimales', DECIMALES)),
        })

    archivo = f"{cfg['id']}.json"
    out_path = os.path.join(OUT_DIR, archivo)
    fc = {'type': 'FeatureCollection', 'zonas': {}, 'features': features}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(out_path) / 1024
    print(f"[{cfg['id']}] -> {archivo}: {len(features)} comunas, {kb:.0f} KB")
    return {
        'id': cfg['id'],
        'nombre': cfg['nombre'],
        'archivo': archivo,
        'bbox': [round(v, 4) for v in bbox],
        'n': len(features),
        'auto': False,        # nunca autoseleccionar (cubre todo Chile)
        'generado': date.today().isoformat(),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pedidas = [a.lower() for a in sys.argv[1:]] or (list(REGIONES) + [DIVISION_COMUNAL['id']])
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
        elif rid in REGIONES:
            entrada = generar_region(rid, REGIONES[rid])
        else:
            print(f'Region desconocida: {rid} (configuradas: {", ".join(REGIONES)}, {DIVISION_COMUNAL["id"]})')
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
