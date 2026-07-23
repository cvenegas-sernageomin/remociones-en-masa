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

Uso:
  python tools/generar_ipt.py                 # todas las regiones configuradas
  python tools/generar_ipt.py atacama         # solo una
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


def round_coords(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(x, DECIMALES) for x in obj]
        return [round_coords(o) for o in obj]
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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pedidas = [a.lower() for a in sys.argv[1:]] or list(REGIONES)
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
        if rid not in REGIONES:
            print(f'Region desconocida: {rid} (configuradas: {", ".join(REGIONES)})')
            continue
        entrada = generar_region(rid, REGIONES[rid])
        if entrada:
            previas[rid] = entrada

    regiones = sorted(previas.values(), key=lambda r: r['nombre'])
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump({'regiones': regiones}, f, ensure_ascii=False, indent=1)
    print(f'\nmanifest.json: {len(regiones)} region(es): {", ".join(r["nombre"] for r in regiones)}')


if __name__ == '__main__':
    main()
