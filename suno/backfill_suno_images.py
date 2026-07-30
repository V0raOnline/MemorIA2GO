#!/usr/bin/env python3
"""
backfill_suno_images.py — Descarga las imágenes de portada que
backup_suno.py no bajó en la primera pasada.

No necesita token/auth: lee image_url / image_large_url directamente de
los .json ya guardados (raw_metadata.image_url / raw_metadata.image_large_url,
que vienen del CDN público de Suno) y descarga lo que falte.

USO:
    python backfill_suno_images.py --backup-dir ./suno_backup

Por cada <título>_<id>.json ya existente, guarda <título>_<id>.jpg
(prioriza image_large_url; si no existe, usa image_url). No repite
descargas ya hechas.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

MAX_RETRIES = 3
SLEEP_BETWEEN_DOWNLOADS = 0.5


def get_with_retries(session, url, debug=False):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp
            if debug:
                print(f"  [aviso] status {resp.status_code} en intento {attempt}")
        except requests.RequestException as e:
            if debug:
                print(f"  [aviso] error de red en intento {attempt}: {e}")
        time.sleep(2 * attempt)
    return None


def main():
    parser = argparse.ArgumentParser(description="Backfill de imágenes de portada de Suno.")
    parser.add_argument("--backup-dir", required=True, help="Carpeta con los .json de backup_suno.py")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    if not backup_dir.exists():
        print(f"[error] no existe {backup_dir}")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (backfill script personal)"})

    json_files = [f for f in backup_dir.glob("*.json") if f.name != "_index.json"]
    print(f"[info] {len(json_files)} archivos de metadata encontrados")

    downloaded = 0
    already_had = 0
    no_url = 0
    failed = 0

    for i, jf in enumerate(json_files, start=1):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        image_url = data.get("image_large_url") or data.get("image_url")

        img_path = jf.with_suffix(".jpg")
        if img_path.exists():
            already_had += 1
            continue

        if not image_url:
            no_url += 1
            if args.debug:
                print(f"  [aviso] sin image_url para {jf.stem}")
            continue

        resp = get_with_retries(session, image_url, debug=args.debug)
        if resp is None:
            failed += 1
            print(f"  [error] no se pudo descargar imagen de '{jf.stem}'")
            continue

        img_path.write_bytes(resp.content)
        downloaded += 1
        time.sleep(SLEEP_BETWEEN_DOWNLOADS)

        if i % 200 == 0:
            print(f"[info] {i}/{len(json_files)} procesados")

    print(f"\n[hecho] {downloaded} imágenes nuevas descargadas")
    print(f"[info] {already_had} ya existían, {no_url} sin URL de imagen, {failed} fallidas")


if __name__ == "__main__":
    main()
