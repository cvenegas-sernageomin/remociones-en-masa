# -*- coding: utf-8 -*-
"""
Regenera el array REFERENCIAS embebido en index.html a partir de la planilla
institucional de publicaciones (xlsx).

Uso:
  python tools/generar_referencias.py "<ruta al .xlsx>"

La planilla se espera con la hoja "Lista":
  fila 1  titulo
  fila 2  encabezados: "Serie a la que pertenece" | "REFERENCIA BIBLIOGRAFICA"
  fila 3+ datos

Que hace, ademas de leer:
- Clasifica cada referencia por TEMA a partir de su texto:
    RM  remociones en masa y peligros/riesgos geologicos (lo mas especifico)
    OT  geologia para el ordenamiento territorial
    MAP mapas y cartas geologicas (contexto, va al final)
- Deduce las REGIONES que cubre (atacama/coquimbo/valparaiso) del propio texto.
  Sin region => referencia general (Chile/Andes): aplica siempre, en cualquier region.
- Ordena por tema y alfabeticamente por autor dentro de cada tema, ignorando tildes.
- Reemplaza en index.html el bloque `const REFERENCIAS = [ ... ];` (no toca nada mas).

El array queda YA ORDENADO como se muestra en la app y como se emite en el informe,
asi que la PWA solo respeta ese orden y no tiene que reordenar nada.
"""
import io
import json
import os
import re
import sys
import unicodedata

import openpyxl

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(BASE, 'index.html')

SERIES = {
    'Básica': 'B',
    'Boletín': 'BO',
    'Publicación Geológica Multinacional': 'PGM',
    'Mapas Geológicos': 'MG',
    'Informe Registrado': 'IR',
}

RE_OT = re.compile(r'ordenamiento territorial', re.I)
RE_RM = re.compile(
    r'remoci[oó]n|remociones|movimientos en masa|peligros? geol|riesgos? geol|inundaci', re.I)

ORDEN_TEMA = {'RM': 0, 'OT': 1, 'MAP': 2}


def tema(texto):
    if RE_OT.search(texto):
        return 'OT'
    if RE_RM.search(texto):
        return 'RM'
    return 'MAP'


def regiones(texto):
    t = texto.lower()
    out = []
    if 'atacama' in t:
        out.append('atacama')
    if 'coquimbo' in t:
        out.append('coquimbo')
    if 'valpara' in t:
        out.append('valparaiso')
    return out


def clave_alfabetica(texto):
    """Alfabetico ignorando tildes: asi 'Álvarez' queda junto a 'Alvarez' y no al final."""
    s = unicodedata.normalize('NFD', texto.lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def leer(xlsx):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb['Lista']
    refs = []
    for fila in ws.iter_rows(min_row=3, values_only=True):
        serie = str(fila[0]).strip() if fila[0] else ''
        texto = ' '.join(str(fila[1]).split()) if fila[1] else ''
        if not texto:
            continue
        if serie not in SERIES:
            print('AVISO: serie desconocida %r — se omite: %s' % (serie, texto[:70]))
            continue
        refs.append({'s': SERIES[serie], 'r': texto, 't': tema(texto), 'g': regiones(texto)})
    return refs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    xlsx = sys.argv[1]
    if not os.path.isfile(xlsx):
        print('No existe el archivo: %s' % xlsx)
        return 1

    refs = leer(xlsx)
    refs.sort(key=lambda r: (ORDEN_TEMA[r['t']], clave_alfabetica(r['r'])))

    lineas = []
    for r in refs:
        g = '[' + ','.join("'%s'" % x for x in r['g']) + ']'
        txt = r['r'].replace('\\', '\\\\').replace("'", "\\'")
        lineas.append("  {t:'%s',s:'%s',g:%s,r:'%s'}," % (r['t'], r['s'], g, txt))

    with io.open(INDEX, encoding='utf-8') as f:
        html = f.read()

    m = re.search(r'const REFERENCIAS = \[\n.*?\n\];', html, re.S)
    if not m:
        print('ERROR: no se encontro el bloque `const REFERENCIAS = [...]` en index.html')
        return 1

    nuevo = 'const REFERENCIAS = [\n' + '\n'.join(lineas) + '\n];'
    html = html[:m.start()] + nuevo + html[m.end():]
    with io.open(INDEX, 'w', encoding='utf-8', newline='') as f:
        f.write(html)

    por_tema = {t: sum(1 for r in refs if r['t'] == t) for t in ORDEN_TEMA}
    sin_region = sum(1 for r in refs if not r['g'])
    print('%d referencias escritas en index.html' % len(refs))
    print('  por tema: RM=%d OT=%d MAP=%d' % (por_tema['RM'], por_tema['OT'], por_tema['MAP']))
    print('  generales (sin region, aplican siempre): %d' % sin_region)
    print('RECORDAR: subir APP_VER en index.html y CACHE_NAME en sw.js.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
