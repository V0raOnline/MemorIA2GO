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
    print(f"[error] no _index.json in {carpeta} -- have you run the backup yet?")
    sys.exit(1)

indice = json.loads(indice_path.read_text(encoding="utf-8"))

# Las borradas en Flow Music no se comprueban: el backup no les descarga
# ficheros, asi que contarlas aqui daria huecos falsos. Mismo criterio que
# build_flowmusic_vault.py y flowmusic_stats.py — si los tres no filtran
# igual, la interfaz acaba enseñando dos totales distintos de la misma
# biblioteca, que es justo lo que pasaba.
_borradas = sum(1 for m in indice.values() if m.get("deleted_at"))
if _borradas:
    indice = {c: m for c, m in indice.items() if not m.get("deleted_at")}

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
        print("[warn] _ausentes.json is corrupt, ignoring it")
formatos = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
malos = [f for f in formatos if f not in EXTENSIONES]
if malos:
    print(f"[error] unrecognised format: {malos}. Valid: {list(EXTENSIONES)}")
    sys.exit(1)

print(f"Total in index: {len(indice)} tracks")
if _borradas:
    print(f"Deleted in Flow Music, not checked: {_borradas}")
print(f"Formats checked: {', '.join(formatos)}")
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
        print(f"{f} missing           : {len(faltan[f])}")
        problemas += len(faltan[f])
    if vacios.get(f):
        print(f"{f} empty (0 bytes)    : {len(vacios[f])}")
        problemas += len(vacios[f])
if json_corrupto:
    print(f"corrupt json         : {len(json_corrupto)}")
    problemas += len(json_corrupto)
if parciales:
    print(f"partial downloads    : {len(parciales)} (stray .part files)")
    problemas += len(parciales)

for f in formatos:
    if sin_url[f]:
        print(f"no {f} in the API     : {len(sin_url[f])} (not a backup failure)")
    if no_en_cdn[f]:
        print(f"{f} missing from CDN   : {len(no_en_cdn[f])} (404, not a backup failure)")

print()


def muestra(etiqueta, items, tope=15):
    if not items:
        return
    print(f"--- {etiqueta} (up to {tope}) ---")
    for x in items[:tope]:
        print(f"  {x}")
    if len(items) > tope:
        print(f"  ... and {len(items) - tope} more")
    print()


for f in formatos + ["jpg", "json"]:
    muestra(f"{f} missing", faltan.get(f) or [])
    muestra(f"{f} empty", vacios.get(f) or [])
muestra("corrupt json", json_corrupto)
muestra("partial downloads", parciales)

if problemas == 0:
    print("ALL OK: the tracks in the index have their files complete.")
else:
    print(f"{problemas} problems in total (see above).")
    print("Run backup_flowmusic.py again: files already present are not requested again.")
