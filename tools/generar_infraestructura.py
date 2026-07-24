# -*- coding: utf-8 -*-
"""
Genera la capa "Infraestructura Crítica" de la PWA remociones-en-masa a partir de las
capas KML ya recopiladas en el repo fallas-activas-chile (proyecto hermano, mismo usuario).

  infra/<sector>_<id>.json   una capa (FeatureCollection compacto)
  infra/manifest.json        índice: sectores (icono/color) + capas (id, archivo, n, tipo)

30 capas en 7 sectores (agua, energía, relaves, salud, seguridad, transporte, educación),
mismo agrupamiento y colores que fallas-activas-chile/visor-web/index.html (SECTORES/
LAYER_DEFS) para que quien ya conoce ese visor reconozca la misma paleta acá.

OJO ENCODING: los KML de origen declaran encoding="utf-8" en su prólogo XML y los bytes
son UTF-8 real (verificado a mano) — NO forzar cp1252 ni ningún otro encoding al leerlos
(mismo error que se cometió y corrigió en generar_ipt.py con la capa morfoclimática:
ver esa nota). geopandas respeta el encoding declarado por defecto.

Uso:
  python tools/generar_infraestructura.py            # todas las capas
  python tools/generar_infraestructura.py bomberos    # solo una capa (por id)
"""
import json
import os
import sys
import warnings
from datetime import date

warnings.filterwarnings('ignore')
import geopandas as gpd  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

# Carpeta fuente: repo fallas-activas-chile ya clonado localmente (mismo usuario).
SRC = r'C:\Users\carlos.venegas\Documents\Claude\fallas-activas-chile\data'

SECTORES = {
    'agua':       {'label': 'Agua',        'icon': '💧', 'color': '#38bdf8'},
    'energia':    {'label': 'Energía',     'icon': '⚡', 'color': '#f59e0b'},
    'relaves':    {'label': 'Relaves',     'icon': '⛏️', 'color': '#92400e'},
    'salud':      {'label': 'Salud',       'icon': '🏥', 'color': '#f43f5e'},
    'transporte': {'label': 'Transporte',  'icon': '🚦', 'color': '#a855f7'},
    'seguridad':  {'label': 'Seguridad',   'icon': '🚨', 'color': '#ef4444'},
    'educacion':  {'label': 'Educación',   'icon': '📚', 'color': '#06b6d4'},
}

# id, sector, etiqueta visible, archivo fuente (relativo a SRC), tipo de geometría,
# tolerancia de simplificación en metros (solo se usa si kind == 'line').
CAPAS = [
    {'id': 'agua_potable_rural', 'sector': 'agua', 'label': 'Agua Potable Rural', 'archivo': 'agua/agua_potable_rural.kml', 'kind': 'point'},
    {'id': 'bocatomas', 'sector': 'agua', 'label': 'Bocatomas', 'archivo': 'agua/bocatomas.kml', 'kind': 'point'},

    {'id': 'almacenes_combustible', 'sector': 'energia', 'label': 'Almacenes de Combustible', 'archivo': 'energia/almacenes_combustible.kml', 'kind': 'point'},
    {'id': 'centrales_biomasa', 'sector': 'energia', 'label': 'Centrales de Biomasa', 'archivo': 'energia/centrales_biomasa.kml', 'kind': 'point'},
    {'id': 'centrales_eolicas', 'sector': 'energia', 'label': 'Centrales Eólicas', 'archivo': 'energia/centrales_eolicas.kml', 'kind': 'point'},
    {'id': 'centrales_geotermicas', 'sector': 'energia', 'label': 'Centrales Geotérmicas', 'archivo': 'energia/centrales_geotermicas.kml', 'kind': 'point'},
    {'id': 'centrales_hidroelectricas', 'sector': 'energia', 'label': 'Centrales Hidroeléctricas', 'archivo': 'energia/centrales_hidroelectricas.kml', 'kind': 'point'},
    {'id': 'centrales_solares', 'sector': 'energia', 'label': 'Centrales Solares', 'archivo': 'energia/centrales_solares.kml', 'kind': 'point'},
    {'id': 'gasoductos', 'sector': 'energia', 'label': 'Gasoductos', 'archivo': 'energia/gasoductos.kml', 'kind': 'line', 'tol': 30},
    {'id': 'lineas_sea', 'sector': 'energia', 'label': 'Líneas Eléctricas SEA', 'archivo': 'energia/lineas_sea.kml', 'kind': 'line', 'tol': 30},
    {'id': 'lineas_sem', 'sector': 'energia', 'label': 'Líneas Eléctricas SEM', 'archivo': 'energia/lineas_sem.kml', 'kind': 'line', 'tol': 30},
    {'id': 'lineas_sic', 'sector': 'energia', 'label': 'Líneas Eléctricas SIC', 'archivo': 'energia/lineas_sic.kml', 'kind': 'line', 'tol': 30},
    {'id': 'lineas_sing', 'sector': 'energia', 'label': 'Líneas Eléctricas SING', 'archivo': 'energia/lineas_sing.kml', 'kind': 'line', 'tol': 30},
    {'id': 'oleoductos', 'sector': 'energia', 'label': 'Oleoductos', 'archivo': 'energia/oleoductos.kml', 'kind': 'line', 'tol': 30},
    {'id': 'subestaciones_sea', 'sector': 'energia', 'label': 'Subestaciones SEA', 'archivo': 'energia/subestaciones_sea.kml', 'kind': 'point'},
    {'id': 'subestaciones_sem', 'sector': 'energia', 'label': 'Subestaciones SEM', 'archivo': 'energia/subestaciones_sem.kml', 'kind': 'point'},
    {'id': 'subestaciones_sic', 'sector': 'energia', 'label': 'Subestaciones SIC', 'archivo': 'energia/subestaciones_sic.kml', 'kind': 'point'},
    {'id': 'subestaciones_sing', 'sector': 'energia', 'label': 'Subestaciones SING', 'archivo': 'energia/subestaciones_sing.kml', 'kind': 'point'},
    {'id': 'terminales_maritimos_descarga', 'sector': 'energia', 'label': 'Terminales Marítimos de Descarga', 'archivo': 'energia/terminales_maritimos_descarga.kml', 'kind': 'point'},
    {'id': 'termoelectricas', 'sector': 'energia', 'label': 'Termoeléctricas', 'archivo': 'energia/termoelectricas.kml', 'kind': 'point'},

    {'id': 'relaves_sernageomin_2025', 'sector': 'relaves', 'label': 'Relaves (SERNAGEOMIN, oct. 2025)', 'archivo': 'relaves/relaves_sernageomin_2025.kml', 'kind': 'point'},

    {'id': 'establecimientos_salud', 'sector': 'salud', 'label': 'Establecimientos de Salud', 'archivo': 'salud/establecimientos_salud.kml', 'kind': 'point'},

    {'id': 'infraestructura_portuaria', 'sector': 'transporte', 'label': 'Infraestructura Portuaria', 'archivo': 'transporte/infraestructura_portuaria.kml', 'kind': 'point'},
    {'id': 'red_aeroportuaria', 'sector': 'transporte', 'label': 'Red Aeroportuaria', 'archivo': 'transporte/red_aeroportuaria.kml', 'kind': 'point'},
    {'id': 'red_ferrea', 'sector': 'transporte', 'label': 'Red Férrea', 'archivo': 'transporte/red_ferrea.kml', 'kind': 'line', 'tol': 30},
    {'id': 'red_vial', 'sector': 'transporte', 'label': 'Red Vial', 'archivo': 'transporte/red_vial.kml', 'kind': 'line', 'tol': 150, 'pesada': True},
    {'id': 'puentes', 'sector': 'transporte', 'label': 'Puentes', 'archivo': 'transporte/puentes.kml', 'kind': 'point'},

    {'id': 'carabineros', 'sector': 'seguridad', 'label': 'Cuarteles de Carabineros', 'archivo': 'seguridad/carabineros.kml', 'kind': 'point'},
    {'id': 'bomberos', 'sector': 'seguridad', 'label': 'Parques de Bomberos', 'archivo': 'seguridad/bomberos.kml', 'kind': 'point'},

    {'id': 'establecimientos_educacion', 'sector': 'educacion', 'label': 'Establecimientos Educacionales', 'archivo': 'educacion/establecimientos_educacion.kml', 'kind': 'point'},
]

# Columnas que agrega geopandas al leer KML y que no son datos reales del atributo
# original (metadata de estilo/KML) — se descartan siempre.
DROP_COLS = {'id', 'Name', 'description', 'timestamp', 'begin', 'end', 'altitudeMode',
             'tessellate', 'extrude', 'visibility', 'drawOrder', 'icon', 'geometry'}

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, 'infra')


def fix_mojibake(s):
    """Repara doble-codificación UTF-8 (ej. 'Ã\\x91uble' en vez de 'Ñuble'), un defecto
    real de la fuente detectado en establecimientos_educacion.kml (29.395 ocurrencias:
    Región/Categoría/etc quedaron re-codificadas) y unas pocas en lineas_sing.kml — NO es
    un bug de este script (el KML declara encoding utf-8 y geopandas lo respeta bien para
    la mayoría de los campos; estos valores puntuales ya vienen mal en el archivo fuente).
    Solo corrige si el string tiene los caracteres delatores (Ã/Â/�) Y el "undo" da un
    resultado válido — evita tocar texto que ya está bien."""
    if not isinstance(s, str) or not s or not any(c in s for c in ('Ã', 'Â', '�')):
        return s
    try:
        return s.encode('latin-1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def valor_vacio(v):
    """Mismo filtro que fallas-activas-chile/visor-web (esValorVacio): oculta campos
    nulos/vacíos/placeholder (-99) para no inflar el JSON con ruido sin información."""
    if v is None:
        return True
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return True
    except Exception:
        pass
    s = str(v).strip()
    return s in ('', '-99', '-99.0', 'None', 'nan', 'NaT')


def round_coords(obj, dec):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(x, dec) for x in obj]
        return [round_coords(o, dec) for o in obj]
    return obj


def generar_capa(cap):
    ruta = os.path.join(SRC, cap['archivo'])
    if not os.path.isfile(ruta):
        print(f"[{cap['id']}] AVISO: no existe {ruta} — omitida")
        return None
    gdf = gpd.read_file(ruta)   # respeta encoding="utf-8" del prólogo del KML (NO forzar otro)

    if cap['kind'] == 'line':
        tol = cap.get('tol', 30)
        gdf = gdf.to_crs(epsg=32719)
        gdf['geometry'] = gdf.geometry.simplify(tol, preserve_topology=True)
        gdf = gdf.to_crs(epsg=4326)
        dec = 5
    else:
        dec = 5

    attr_cols = [c for c in gdf.columns if c not in DROP_COLS]
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        nombre = row.get('Name')
        nombre = fix_mojibake(str(nombre).strip()) if nombre and str(nombre).strip().lower() != 'none' else ''
        attrs = {c: row[c] for c in attr_cols if not valor_vacio(row[c])}
        # SimpleData llega como texto salvo que geopandas infiera número; castear numpy
        # types a tipos nativos de Python para que json.dump no truene.
        attrs = {k: (v.item() if hasattr(v, 'item') else v) for k, v in attrs.items()}
        attrs = {k: (fix_mojibake(v) if isinstance(v, str) else v) for k, v in attrs.items()}
        props = {}
        if nombre:
            props['n'] = nombre
        if attrs:
            props['a'] = attrs
        features.append({
            'type': 'Feature',
            'properties': props,
            'geometry': round_coords(mapping(geom), dec),
        })

    data = {'type': 'FeatureCollection', 'sector': cap['sector'], 'kind': cap['kind'], 'features': features}
    archivo = f"{cap['sector']}_{cap['id']}.json"
    ruta_out = os.path.join(OUT_DIR, archivo)
    with open(ruta_out, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(ruta_out) / 1024
    print(f"[{cap['id']}] {len(features)} features, {kb:.0f} KB -> {archivo}")
    return {'id': cap['id'], 'sector': cap['sector'], 'label': cap['label'], 'archivo': archivo,
            'kind': cap['kind'], 'n': len(features), 'pesada': cap.get('pesada', False)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pedidas = set(a.lower() for a in sys.argv[1:]) or {c['id'] for c in CAPAS}

    manifest_path = os.path.join(OUT_DIR, 'manifest.json')
    previas = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding='utf-8') as f:
                previas = {c['id']: c for c in json.load(f).get('capas', [])}
        except Exception:
            pass

    for cap in CAPAS:
        if cap['id'] not in pedidas:
            continue
        entrada = generar_capa(cap)
        if entrada:
            previas[cap['id']] = entrada

    capas_out = sorted(previas.values(), key=lambda c: (c['sector'], c['label']))
    manifest = {'sectores': SECTORES, 'capas': capas_out, 'generado': date.today().isoformat()}
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"\nmanifest.json: {len(capas_out)} capa(s) en {len(SECTORES)} sectores")


if __name__ == '__main__':
    main()
