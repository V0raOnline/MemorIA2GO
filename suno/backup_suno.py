#!/usr/bin/env python3
"""
backup_suno.py — Backup simple de tu biblioteca de Suno.

Descarga audio + metadatos (letra, prompt, fecha, y si es cover/remix
de otra pista) de todas tus canciones, paginando automáticamente.

USO:
    python backup_suno.py --token "TU_BEARER_TOKEN" --browser-token "TU_BROWSER_TOKEN" --out ./suno_backup

Cómo conseguir los tokens (Suno usa Clerk + un header anti-bot propio
'browser-token'; la API NO se autentica solo con la cookie de sesión):
    1. Ve a suno.com/create o a tu Library, logueada.
    2. Abre DevTools (F12) -> pestaña Network.
    3. Refresca la página / navega a Library.
    4. Busca una request a studio-api.prod.suno.com (ej. "feed" o "clips").
       NO uses las de clerk.suno.com.
    5. Click en ella -> Headers -> busca "Authorization: Bearer eyJ..."
       y también "browser-token: ...".
    6. Copia el valor de Authorization SIN el prefijo "Bearer " (solo el JWT),
       y el valor completo de browser-token.
    7. Pásalos como --token y --browser-token, o guárdalos en archivos
       y usa --token-file.

OJO: el Bearer token caduca en minutos/pocas horas (típico de Clerk). Si
el backup es largo, puede que tengas que repetir estos pasos y relanzar
el script a mitad de camino — no se renueva solo.

RESUME: si ya existe un _index.json en la carpeta de salida, el listado
retoma automáticamente desde la página aproximada donde se quedó (en vez
de volver a pedir las ~100+ páginas desde cero), deduplicando por id por
si la librería cambió de orden entre medias. Usa --no-resume para forzar
un listado completo desde el principio.

NOTA: Esto usa la API interna no documentada de Suno (misma que usan
las extensiones de terceros). Puede romperse si Suno cambia su API;
en ese caso, revisa BASE_URL / LIBRARY_ENDPOINT y los nombres de campo
en el JSON de respuesta (imprime uno con --debug para inspeccionar).
"""

import argparse
import json
import time
import sys
from pathlib import Path
from datetime import datetime

import requests

# Fix: la consola de Windows (cp1252 por defecto) revienta con
# UnicodeEncodeError al hacer print() de titulos con caracteres no-ASCII
# (islandes, cirilico, etc.) -- fuerza stdout/stderr a UTF-8 y sustituye
# lo que no pueda mostrar en vez de crashear el proceso a mitad de backup.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://studio-api.prod.suno.com"
LIBRARY_ENDPOINT = "/api/feed/v2"  # ver nota si esto cambia
PAGE_SIZE = 50
MAX_PAGES = 500          # límite de seguridad contra loops infinitos
SLEEP_BETWEEN_PAGES = 1.2
SLEEP_BETWEEN_DOWNLOADS = 0.8
MAX_RETRIES = 3


def build_session(token: str, browser_token: str = None) -> requests.Session:
    s = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (backup script personal)",
        "Accept": "application/json",
    }
    if browser_token:
        headers["browser-token"] = browser_token
    s.headers.update(headers)
    return s


def get_with_retries(session, url, params=None, debug=False):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp
            if debug:
                print(f"  [aviso] status {resp.status_code} en intento {attempt}")
        except requests.RequestException as e:
            if debug:
                print(f"  [aviso] error de red en intento {attempt}: {e}")
        time.sleep(2 * attempt)  # backoff simple
    return None


def fetch_all_songs(session, debug=False, start_page=0, existing_songs=None):
    all_songs = list(existing_songs) if existing_songs else []
    seen_ids = {s.get("id") for s in all_songs if s.get("id")}
    page = start_page

    while page < MAX_PAGES:
        resp = get_with_retries(
            session,
            BASE_URL + LIBRARY_ENDPOINT,
            params={"page": page, "page_size": PAGE_SIZE},
            debug=debug,
        )
        if resp is None:
            print(f"[error] no se pudo obtener la página {page} tras {MAX_RETRIES} intentos. Deteniendo.")
            print(f"[info] última página completada con éxito: {page - 1}. "
                  f"Relanza el script tal cual: retomará solo desde aquí automáticamente.")
            break

        try:
            data = resp.json()
        except json.JSONDecodeError:
            print(f"[error] respuesta no-JSON en página {page}. Deteniendo.")
            break

        if debug and page == 0:
            print("[debug] estructura de la primera respuesta:")
            print(json.dumps(data, indent=2)[:2000])

        # El nombre del campo de lista puede variar (clips / songs / data...)
        songs = data.get("clips") or data.get("songs") or data.get("data") or []

        if not songs:
            print(f"[info] página {page} vacía — fin de la biblioteca.")
            break

        new_count = 0
        for s in songs:
            sid = s.get("id")
            if sid and sid in seen_ids:
                continue
            all_songs.append(s)
            if sid:
                seen_ids.add(sid)
            new_count += 1

        print(f"[info] página {page}: +{new_count} pistas nuevas (total {len(all_songs)})")

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_songs


def safe_filename(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    keep = "-_.() "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned[:120] if cleaned else fallback


def detect_lineage_from_title(title: str) -> list:
    """Suno marca covers/remixes/extends visiblemente en el título entre paréntesis."""
    if not title:
        return []
    markers = []
    for tag in ("(Cover)", "(Remix)", "(Extended)", "(Continued)", "(Remaster)", "(Edit)"):
        count = title.count(tag)
        if count:
            markers.append(f"{tag} x{count}" if count > 1 else tag)
    return markers


def extract_metadata(song: dict) -> dict:
    meta = song.get("metadata", {}) or {}
    title = song.get("title")

    # Campos internos de linaje (por si existen además de la señal en el título)
    lineage_candidates = {}
    for key in ("upsample_of_id", "history", "concat_history", "continued_from_id", "source_id"):
        if song.get(key) or meta.get(key):
            lineage_candidates[key] = song.get(key) or meta.get(key)

    title_lineage = detect_lineage_from_title(title)
    project = song.get("project") or {}

    return {
        "id": song.get("id"),
        "title": title,
        "created_at": song.get("created_at") or meta.get("created_at"),
        "status": song.get("status"),
        "model": song.get("model_name"),
        "major_model_version": song.get("major_model_version"),
        "duration": song.get("duration") or meta.get("duration"),
        "is_liked": song.get("is_liked"),
        "project_id": project.get("id") or None,
        "project_name": project.get("name") or None,
        "project_description": project.get("description") or None,
        "project_is_trashed": project.get("is_trashed"),
        "project_is_public": project.get("is_public"),
        # En modo custom, metadata.prompt ES la letra (con [Verse]/[Chorus]/etc.)
        "lyrics": meta.get("prompt"),
        # metadata.tags es el estilo/género/mood, no etiquetas sueltas
        "style_tags": meta.get("tags"),
        # Si algún día aparece un campo de descripción simple (modo no-custom)
        "simple_description": meta.get("gpt_description_prompt"),
        "audio_url": song.get("audio_url"),
        "image_url": song.get("image_url"),
        "image_large_url": song.get("image_large_url"),
        "cover_o_remix_detectado_en_titulo": title_lineage or None,
        "posible_origen_interno": lineage_candidates or None,
        "raw_metadata": meta,  # red de seguridad por si hay algo que no mapeamos
    }


def download_song(session, song: dict, out_dir: Path, debug=False):
    song_id = song.get("id", "sin_id")
    title = safe_filename(song.get("title"), song_id)
    audio_url = song.get("audio_url")

    if not audio_url:
        print(f"  [aviso] sin audio_url para '{title}' ({song_id}), se guarda solo metadata.")
    else:
        audio_path = out_dir / f"{title}_{song_id}.mp3"
        if not audio_path.exists():
            resp = get_with_retries(session, audio_url, debug=debug)
            if resp is not None:
                audio_path.write_bytes(resp.content)
                print(f"  [ok] audio: {audio_path.name}")
            else:
                print(f"  [error] no se pudo descargar audio de '{title}' ({song_id})")
        time.sleep(SLEEP_BETWEEN_DOWNLOADS)

    meta = extract_metadata(song)
    meta_path = out_dir / f"{title}_{song_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    image_url = song.get("image_large_url") or song.get("image_url")
    if image_url:
        img_path = out_dir / f"{title}_{song_id}.jpg"
        if not img_path.exists():
            resp = get_with_retries(session, image_url, debug=debug)
            if resp is not None:
                img_path.write_bytes(resp.content)
                print(f"  [ok] portada: {img_path.name}")
            else:
                print(f"  [aviso] no se pudo descargar la portada de '{title}' ({song_id})")
            time.sleep(SLEEP_BETWEEN_DOWNLOADS)


def main():
    parser = argparse.ArgumentParser(description="Backup simple de tu biblioteca de Suno.")
    parser.add_argument("--token", help="Bearer token (JWT de Clerk) copiado del navegador.")
    parser.add_argument("--token-file", help="Archivo de texto que contiene el token.")
    parser.add_argument("--browser-token", help="Valor del header 'browser-token' copiado del navegador.")
    parser.add_argument("--out", default="./suno_backup", help="Carpeta de salida.")
    parser.add_argument("--no-resume", action="store_true",
                         help="Ignora un _index.json existente y vuelve a listar la biblioteca desde cero.")
    parser.add_argument("--debug", action="store_true", help="Muestra info extra para depurar la API.")
    args = parser.parse_args()

    if not args.token and not args.token_file:
        print("[error] necesitas --token o --token-file")
        sys.exit(1)

    token = args.token or Path(args.token_file).read_text(encoding="utf-8").strip()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = build_session(token, args.browser_token)

    index_path = out_dir / "_index.json"
    existing_songs = []
    start_page = 0
    if index_path.exists() and not args.no_resume:
        try:
            existing_songs = json.loads(index_path.read_text(encoding="utf-8"))
            start_page = len(existing_songs) // PAGE_SIZE
            print(f"[info] _index.json existente encontrado: {len(existing_songs)} pistas ya listadas, "
                  f"retomando listado desde la página {start_page}.")
        except json.JSONDecodeError:
            print("[aviso] _index.json existente no es JSON válido, se listará desde cero.")

    print("[info] listando biblioteca...")
    songs = fetch_all_songs(session, debug=args.debug, start_page=start_page, existing_songs=existing_songs)
    print(f"[info] total encontrado: {len(songs)} pistas")

    if not songs:
        print("[info] nada que descargar. Si esperabas resultados, prueba con --debug "
              "para ver la respuesta cruda y ajustar LIBRARY_ENDPOINT / nombres de campo.")
        return

    index_path = out_dir / "_index.json"
    index_path.write_text(json.dumps(songs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[info] índice completo guardado en {index_path.name}")

    for i, song in enumerate(songs, start=1):
        print(f"[{i}/{len(songs)}] {song.get('title') or song.get('id')}")
        download_song(session, song, out_dir, debug=args.debug)

    print(f"\n[hecho] backup completo en: {out_dir.resolve()}")
    print(f"Terminado: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
