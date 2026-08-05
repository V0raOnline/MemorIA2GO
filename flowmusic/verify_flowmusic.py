#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_flowmusic.py — Pasada de reconocimiento sobre un backup de Flow Music.

Cruza los ids de _index.json contra los ficheros reales en disco y
detecta huecos, ficheros vacios, JSON corruptos y descargas cortadas a
medias (.part sueltos).

USO:
    python verify_flowmusic.py --backup-dir ./flowmusic_backup
    python verify_flowmusic.py --backup-dir ./flowmusic_backup --formats m4a

Comprueba los formatos que le digas; por defecto los mismos que baja el
script de backup. Si solo pediste m4a, pasale --formats m4a o te marcara
33 wav "faltantes" que nunca pediste.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_flowmusic import nombre_seguro, EXTENSIONES

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser(description="Verifica la integridad de un backup de Flow Music.")
ap.add_argument("--backup-dir", default="./flowmusic_backup",
                help="Carpeta que contiene _index.json y las pistas descargadas.")
ap.add_argument("--formats", default="m4a,wav",
                help="Formatos que deberian existir, separados por coma.")
args = ap.parse_args()

carpeta = Path(args.backup_dir)
indice_path = carpeta / "_index.json"
if not indice_path.is_file():
    print(f"[error] no hay _index.json en {carpeta} - has hecho el backup ya?")
    sys.exit(1)

indice = json.loads(indice_path.read_text(encoding="utf-8"))

# Formatos que el CDN no tiene (404), anotados por el backup. Un wav_url en
# la metadata NO prueba que el fichero exista: la API lo construye a partir
# del id del clip. Los stems, por ejemplo, solo se renderizan en m4a.
# Contarlos como descargas fallidas seria mentir en el informe.
ausentes = {}
ausentes_path = carpeta / "_ausentes.json"
if ausentes_path.exists():
    try:
        ausentes = json.loads(ausentes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("[aviso] _ausentes.json corrupto, se ignora")
formatos = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
malos = [f for f in formatos if f not in EXTENSIONES]
if malos:
    print(f"[error] formato no reconocido: {malos}. Validos: {list(EXTENSIONES)}")
    sys.exit(1)

print(f"Total en indice: {len(indice)} pistas")
print(f"Formatos comprobados: {', '.join(formatos)}")
print()

faltan = {f: [] for f in formatos}
vacios = {f: [] for f in formatos}
faltan["jpg"], vacios["jpg"] = [], []
faltan["json"], vacios["json"] = [], []
json_corrupto = []
sin_url = {f: [] for f in formatos}
no_en_cdn = {f: [] for f in formatos}
parciales = []

for cid, meta in indice.items():
    titulo = nombre_seguro(meta.get("title"), cid)
    base = f"{titulo}_{cid}"

    for f in formatos:
        # Si la API nunca dio URL para ese formato, no es un fallo del
        # backup: es que esa pista no lo tiene.
        if not meta.get(EXTENSIONES[f]):
            sin_url[f].append(base)
            continue
        if f in (ausentes.get(cid) or []):
            no_en_cdn[f].append(base)
            continue
        ruta = carpeta / f"{base}.{f}"
        if not ruta.exists():
            faltan[f].append(base)
        elif ruta.stat().st_size == 0:
            vacios[f].append(base)

    jpg = carpeta / f"{base}.jpg"
    if meta.get("image_url"):
        if not jpg.exists():
            faltan["jpg"].append(base)
        elif jpg.stat().st_size == 0:
            vacios["jpg"].append(base)

    jsf = carpeta / f"{base}.json"
    if not jsf.exists():
        faltan["json"].append(base)
    else:
        if jsf.stat().st_size == 0:
            vacios["json"].append(base)
        else:
            try:
                json.loads(jsf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                json_corrupto.append(base)

# Un .part que sobrevive a la ejecucion es una descarga que se corto y no
# llego a cuadrar con el Content-Length.
for p in carpeta.glob("*.part"):
    parciales.append(p.name)

problemas = 0
for f in formatos + ["jpg", "json"]:
    if faltan.get(f):
        print(f"{f} faltantes        : {len(faltan[f])}")
        problemas += len(faltan[f])
    if vacios.get(f):
        print(f"{f} vacios (0 bytes)  : {len(vacios[f])}")
        problemas += len(vacios[f])
if json_corrupto:
    print(f"json corruptos       : {len(json_corrupto)}")
    problemas += len(json_corrupto)
if parciales:
    print(f"descargas a medias   : {len(parciales)} (.part sueltos)")
    problemas += len(parciales)

for f in formatos:
    if sin_url[f]:
        print(f"sin {f} en la API     : {len(sin_url[f])} (no es un fallo del backup)")
    if no_en_cdn[f]:
        print(f"{f} inexistente en CDN : {len(no_en_cdn[f])} (404, no es un fallo del backup)")

print()


def muestra(etiqueta, items, tope=15):
    if not items:
        return
    print(f"--- {etiqueta} (hasta {tope}) ---")
    for x in items[:tope]:
        print(f"  {x}")
    if len(items) > tope:
        print(f"  ... y {len(items) - tope} mas")
    print()


for f in formatos + ["jpg", "json"]:
    muestra(f"{f} faltantes", faltan.get(f) or [])
    muestra(f"{f} vacios", vacios.get(f) or [])
muestra("json corruptos", json_corrupto)
muestra("descargas a medias", parciales)

if problemas == 0:
    print("TODO OK: las pistas del indice tienen sus ficheros completos.")
else:
    print(f"Hay {problemas} problemas en total (ver arriba).")
    print("Relanza backup_flowmusic.py: los ficheros que ya estan no se vuelven a pedir.")
