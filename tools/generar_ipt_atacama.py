# -*- coding: utf-8 -*-
"""
Genera ipt_atacama.json (GeoJSON compacto) para la capa "IPT" de la PWA
remociones-en-masa, a partir de los shapefiles de Instrumentos de
Planificacion Territorial de Atacama:

  LU/   Limites urbanos (13 poligonos)
  PRC/  Planes Reguladores Comunales (12 shp; incluye Huasco_ZNE que son lineas)
  PRI/  Plan Regulador Intercomunal Costero (563 poligonos, el mas pesado)

- Reproyecta EPSG:32719 -> 4326.
- Simplifica en metros (UTM) ANTES de reproyectar: LU/PRC 2 m, PRI 5 m.
- Coordenadas con 5 decimales (~1.1 m), consistente con la simplificacion.
- Atributos normalizados y deduplicados: las descripciones largas de zona
  (nombre, usos permitidos/prohibidos) van UNA vez en el diccionario "zonas";
  cada feature solo lleva la clave. Esto achica mucho el PRI (563 features
  pero ~30 zonas distintas).

Uso:  python tools/generar_ipt_atacama.py
Salida: ipt_atacama.json en la raiz del repo (junto a puntos_criticos.json).
"""
import glob
import json
import os
import warnings

warnings.filterwarnings('ignore')
import geopandas as gpd  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

SRC = r'C:\Users\carlos.venegas\Documents\Sernageomin_Emergencia 2026\IPT_Atacama'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ipt_atacama.json')

# tolerancia de simplificacion en metros, por grupo. El PRI (intercomunal costero,
# zonas rurales extensas) va a 10 m: error menor que el GPS de terreno y baja el
# archivo a un tamano razonable para movil (a 5 m quedaba en 9 MB).
TOL = {'LU': 2, 'PRC': 2, 'PRI': 10}
DECIMALES = 5


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


def main():
    features = []
    zonas = {}       # zkey -> {n: nombre, p: permitido, x: prohibido, d: documento}
    zkeys = {}       # (texto compuesto) -> zkey, para dedupe
    resumen = []

    for shp in sorted(glob.glob(os.path.join(SRC, '**', '*.shp'), recursive=True)):
        rel = os.path.relpath(shp, SRC)
        grupo = rel.split(os.sep)[0]           # LU / PRC / PRI
        es_zne = 'ZNE' in os.path.basename(shp)
        g = 'ZNE' if es_zne else grupo

        gdf = gpd.read_file(shp)
        if gdf.crs is None or gdf.crs.to_epsg() != 32719:
            gdf = gdf.to_crs(epsg=32719)
        tol = TOL.get(grupo, 2)
        gdf['geometry'] = gdf.geometry.simplify(tol, preserve_topology=True)
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

            # dedupe de la descripcion de zona
            comp = (g, zona, nom, up, ux, doc)
            if comp not in zkeys:
                zk = f'{g}:{zona or nom or len(zkeys)}'
                # si colisiona la clave con contenido distinto, sufija
                base, i = zk, 2
                while zk in zonas:
                    zk = f'{base}~{i}'
                    i += 1
                zkeys[comp] = zk
                zonas[zk] = {k: v for k, v in
                             (('n', nom), ('p', up), ('x', ux), ('d', doc)) if v}
            zk = zkeys[comp]

            features.append({
                'type': 'Feature',
                'properties': {k: v for k, v in
                               (('g', g), ('z', zk), ('com', com), ('loc', loc)) if v},
                'geometry': round_coords(mapping(geom)),
            })
            n_ok += 1
        resumen.append(f'{rel}: {n_ok} features (grupo {g}, tol {tol} m)')

    fc = {
        'type': 'FeatureCollection',
        'zonas': zonas,               # miembro extra (GeoJSON lo permite); la PWA lo lee
        'features': features,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))

    kb = os.path.getsize(OUT) / 1024
    print('\n'.join(resumen))
    print(f'\nTotal: {len(features)} features, {len(zonas)} zonas unicas')
    print(f'Salida: {OUT} ({kb:.0f} KB)')


if __name__ == '__main__':
    main()
