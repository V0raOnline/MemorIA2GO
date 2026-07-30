#!/usr/bin/env python3
"""
verify_backup.py — Pasada de reconocimiento antes de montar el vault.

Cruza los IDs de _index.json contra los archivos reales en disco
(.mp3/.json/.jpg), detecta huecos y archivos vacíos/corruptos.

Colócalo en la misma carpeta que backup_suno.py (importa safe_filename
de ahí) y corre:

    python verify_backup.py --backup-dir ./suno_backup

--backup-dir se añadió al integrar la pestaña MUSIC·0LOGY (2026-07-30):
antes daba por hecho que el backup era hermano del script, y con la ruta
ya configurable desde la interfaz eso dejó de ser cierto. Sin el
argumento se mantiene el comportamiento de siempre.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_suno import safe_filename

_ap = argparse.ArgumentParser(description="Verifica la integridad de un backup de Suno.")
_ap.add_argument("--backup-dir", default=str(Path(__file__).parent / "suno_backup"),
                 help="Carpeta que contiene _index.json y las pistas descargadas.")
_args = _ap.parse_args()

backup_dir = Path(_args.backup_dir)
_index_path = backup_dir / "_index.json"
if not _index_path.is_file():
    print(f"[error] no hay _index.json en {backup_dir} — ¿has hecho el backup ya?")
    sys.exit(1)
index = json.loads(_index_path.read_text(encoding="utf-8"))

print(f"Total en indice: {len(index)}")

missing_mp3 = []
empty_mp3 = []
missing_json = []
bad_json = []
missing_jpg = []
empty_jpg = []
dup_ids = []
seen_ids = set()

for song in index:
    sid = song.get("id")
    if not sid:
        continue
    if sid in seen_ids:
        dup_ids.append(sid)
    seen_ids.add(sid)

    title = safe_filename(song.get("title"), sid)
    stem = f"{title}_{sid}"

    mp3 = backup_dir / f"{stem}.mp3"
    jsonf = backup_dir / f"{stem}.json"
    jpg = backup_dir / f"{stem}.jpg"

    if not mp3.exists():
        missing_mp3.append(stem)
    elif mp3.stat().st_size == 0:
        empty_mp3.append(stem)

    if not jsonf.exists():
        missing_json.append(stem)
    else:
        try:
            json.loads(jsonf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bad_json.append(stem)

    if not jpg.exists():
        missing_jpg.append(stem)
    elif jpg.stat().st_size == 0:
        empty_jpg.append(stem)

print(f"IDs duplicados en indice: {len(dup_ids)}")
print()
print(f"mp3 faltantes: {len(missing_mp3)}")
print(f"mp3 vacios (0 bytes): {len(empty_mp3)}")
print(f"json faltantes: {len(missing_json)}")
print(f"json corruptos: {len(bad_json)}")
print(f"jpg faltantes: {len(missing_jpg)}")
print(f"jpg vacios (0 bytes): {len(empty_jpg)}")
print()


def show(label, items, limit=15):
    if items:
        print(f"--- {label} (mostrando hasta {limit}) ---")
        for x in items[:limit]:
            print(f"  {x}")
        if len(items) > limit:
            print(f"  ... y {len(items) - limit} mas")
        print()


show("mp3 faltantes", missing_mp3)
show("mp3 vacios", empty_mp3)
show("json faltantes", missing_json)
show("json corruptos", bad_json)
show("jpg faltantes", missing_jpg)
show("jpg vacios", empty_jpg)

total_problems = (len(missing_mp3) + len(empty_mp3) + len(missing_json)
                   + len(bad_json) + len(missing_jpg) + len(empty_jpg))
if total_problems == 0:
    print("TODO OK: las pistas del indice tienen mp3+json+jpg validos.")
else:
    print(f"Hay {total_problems} problemas en total (ver arriba).")
