#!/usr/bin/env python3
"""
regenerate_suno_metadata.py — Regenera los .json de metadata por pista a
partir de _index.json (el listado crudo completo que backup_suno.py ya
guardó), SIN volver a tocar la API de Suno ni re-descargar audio/imágenes.

Útil cuando cambiamos qué campos extraemos (extract_metadata en
backup_suno.py) y queremos que los .json existentes reflejen el mapeo
nuevo, sin gastar tiempo/token en un backup completo otra vez.

USO:
    python regenerate_suno_metadata.py --backup-dir ./suno_backup

Requiere que backup_suno.py esté en la misma carpeta (importa
extract_metadata y safe_filename de ahí, para no duplicar la lógica de
mapeo en dos sitios que puedan desincronizarse).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from backup_suno import extract_metadata, safe_filename
except ImportError:
    print("[error] no se encuentra backup_suno.py en la misma carpeta que este script.")
    print("        Copia regenerate_suno_metadata.py junto a backup_suno.py y reintenta.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Regenera los .json de metadata desde _index.json.")
    parser.add_argument("--backup-dir", required=True, help="Carpeta con _index.json (la de backup_suno.py)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    index_path = backup_dir / "_index.json"

    if not index_path.exists():
        print(f"[error] no existe {index_path}")
        sys.exit(1)

    print("[info] leyendo _index.json...")
    songs = json.loads(index_path.read_text(encoding="utf-8"))
    print(f"[info] {len(songs)} pistas en el índice crudo")

    regenerated = 0
    skipped_no_title = 0

    for i, song in enumerate(songs, start=1):
        song_id = song.get("id", "sin_id")
        title = safe_filename(song.get("title"), song_id)

        meta = extract_metadata(song)
        meta_path = backup_dir / f"{title}_{song_id}.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        regenerated += 1

        if i % 200 == 0:
            print(f"[info] {i}/{len(songs)} regenerados")

    print(f"\n[hecho] {regenerated} archivos .json regenerados en {backup_dir}")
    print("[info] audio (.mp3) y portadas (.jpg) no se han tocado.")


if __name__ == "__main__":
    main()
