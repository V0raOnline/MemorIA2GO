#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_flowmusic.py — Backup de tu biblioteca de Flow Music (flowmusic.app).

Descarga audio (m4a y wav), portada y metadatos (letra, timing de letra,
instruccion de generacion, linaje) de todas tus pistas.

USO:
    $env:FLOWMUSIC_TOKEN="eyJ..."          # PowerShell
    python backup_flowmusic.py --out ./flowmusic_backup

    python backup_flowmusic.py --token-file token.txt --out ./flowmusic_backup
    python backup_flowmusic.py --formats m4a --out ./flowmusic_backup

COMO CONSEGUIR EL TOKEN:
    1. Entra en flowmusic.app logueada.
    2. F12 -> pestana Network -> en el filtro escribe '__api'.
    3. Recarga. Clic derecho en cualquier request -> Copy -> "Copy as cURL".
    4. Del texto pegado, saca el valor de 'authorization:' SIN el prefijo
       'Bearer '. Es lo unico que hace falta: ni cookie, ni headers raros.

    NO copies el valor directamente del panel Headers: Chrome trunca los
    valores largos y los pinta con una elipsis (…). Te llevarias medio
    token con un caracter '…' literal en medio, y las cabeceras HTTP solo
    admiten latin-1, asi que reventaria con un UnicodeEncodeError que no
    dice nada util.

EL TOKEN CADUCA. Si el backup es largo puede que tengas que copiar uno
nuevo y relanzar — no se renueva solo. El resume lo cubre (ver abajo).

ARQUITECTURA (mapeada contra la API real, no supuesta):

    GET  /__api/conversations?limit=&offset=   listado, paginado
    GET  /__api/conversations/<id>             mensajes de la conversacion
           -> los ids de clip viven dentro, en las llamadas a herramientas
    POST /__api/clips  {"clip_ids": [...]}     metadata completa, en lote
    GET  storage.googleapis.com/producer-app-public/clips/<id>.m4a
                                              /clips/<id>.wav
                                              /assets/<id>.jpg

Flow Music no tiene un endpoint de biblioteca plana como el feed de Suno:
es un producto de chat, y las pistas cuelgan de las conversaciones. Por
eso hay que recorrer conversaciones para enumerar las pistas.

RESUME: se guarda en _state.json el 'last_message_at' de cada
conversacion ya recorrida. En la siguiente pasada solo se vuelven a leer
las conversaciones que han cambiado desde entonces. Es mas fiable que
retomar por numero de pagina (lo que hace el script de Suno): si
reordenas o anades pistas, esto sigue cuadrando. Usa --no-resume para
recorrerlo todo desde cero.

Los ficheros ya descargados no se vuelven a pedir. Las descargas van a un
.part que solo se renombra al terminar y cuadrar con el Content-Length,
asi que un corte a mitad no deja un wav truncado haciendose pasar por
completo.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# La consola de Windows (cp1252 por defecto) revienta con
# UnicodeEncodeError al hacer print() de titulos con caracteres no-ASCII
# -- fuerza stdout/stderr a UTF-8 y sustituye lo que no pueda mostrar en
# vez de crashear el proceso a mitad de backup.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://www.flowmusic.app"
CONVERSACIONES = "/__api/conversations"
CLIPS = "/__api/clips"

PAGINA = 100              # limite por peticion en el listado de conversaciones
LOTE_CLIPS = 50           # cuantos ids se hidratan de una vez
MAX_PAGINAS = 200         # tope de seguridad contra bucles infinitos
ESPERA_LISTADO = 0.6
ESPERA_DESCARGA = 0.4
MAX_REINTENTOS = 3
TIMEOUT = 60

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

EXTENSIONES = {"m4a": "audio_url", "wav": "wav_url"}


# ------------------------------------------------------------- sesiones

def sesion_api(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    return s


def sesion_cdn() -> requests.Session:
    """Sesion SIN el token para bajar de storage.googleapis.com.

    El bucket es publico y no pide autenticacion, asi que mandar ahi el
    Bearer no aporta nada y se lo estaria entregando a un tercero. Sesion
    aparte, sin credenciales."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def pedir(session, url, metodo="GET", cuerpo=None, debug=False):
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            if metodo == "POST":
                r = session.post(url, data=cuerpo, timeout=TIMEOUT)
            else:
                r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403):
                print(f"  [error] {r.status_code}: the token has expired or is not valid.")
                print("          Copy a fresh one and relaunch: resume picks up where it left off.")
                return None
            if debug:
                print(f"  [warn] status {r.status_code} on attempt {intento}")
        except requests.RequestException as e:
            if debug:
                print(f"  [warn] network error on attempt {intento}: {e}")
        time.sleep(2 * intento)  # backoff simple
    return None


# -------------------------------------------------------------- listado

def listar_conversaciones(session, debug=False):
    """Pagina con limit/offset. Ojo: la respuesta es una lista pelada, sin
    'next' ni 'total', asi que el final se detecta porque llega una pagina
    mas corta que el limite."""
    todas, offset = [], 0
    for _ in range(MAX_PAGINAS):
        url = f"{BASE}{CONVERSACIONES}?limit={PAGINA}&offset={offset}"
        r = pedir(session, url, debug=debug)
        if r is None:
            print(f"[error] failed to list conversations at offset {offset}.")
            break
        try:
            lote = r.json()
        except json.JSONDecodeError:
            print(f"[error] non-JSON response at offset {offset}.")
            break
        if not isinstance(lote, list) or not lote:
            break
        todas.extend(lote)
        print(f"[info] conversations: +{len(lote)} (total {len(todas)})")
        if len(lote) < PAGINA:
            break
        offset += PAGINA
        time.sleep(ESPERA_LISTADO)
    return todas


CARPETA_CONVERSACIONES = "_conversations"


def ruta_conversacion(carpeta: Path, conv: dict) -> Path:
    """Una conversacion, un fichero. El titulo va delante para poder
    encontrarla mirando la carpeta, igual que con las pistas."""
    nombre = nombre_seguro(conv.get("title"), conv["id"])
    return carpeta / CARPETA_CONVERSACIONES / f"{nombre}_{conv['id']}.json"


def recolectar_clip_ids(valor, encontrados=None):
    """Saca todos los ids de clip de una conversacion.

    Se recorre el arbol entero buscando claves 'clip_id' y 'clip_ids' en
    vez de ir a rutas fijas. En los datos reales aparecen al menos en
    parts[].content.clip_outputs[], parts[].content.stems[],
    parts[].content.clip_id y parts[].args.clip_ids[] — y con una API sin
    documentar es mas seguro buscar por nombre de clave que fiarse de que
    esas rutas no cambien."""
    encontrados = encontrados if encontrados is not None else []
    if isinstance(valor, dict):
        for k, v in valor.items():
            if k == "clip_id" and isinstance(v, str):
                encontrados.append(v)
            elif k == "clip_ids" and isinstance(v, list):
                encontrados.extend(x for x in v if isinstance(x, str))
            else:
                recolectar_clip_ids(v, encontrados)
    elif isinstance(valor, list):
        for v in valor:
            recolectar_clip_ids(v, encontrados)
    return encontrados


def hidratar_clips(session, clip_ids, debug=False):
    """POST /__api/clips con los ids en el cuerpo. GET sobre esa ruta
    devuelve 405: solo acepta POST."""
    clips = {}
    ids = list(clip_ids)
    for i in range(0, len(ids), LOTE_CLIPS):
        lote = ids[i:i + LOTE_CLIPS]
        cuerpo = json.dumps({"clip_ids": lote})
        r = pedir(session, BASE + CLIPS, metodo="POST", cuerpo=cuerpo, debug=debug)
        if r is None:
            print(f"  [error] could not hydrate batch {i // LOTE_CLIPS + 1}")
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(f"  [error] non-JSON response hydrating batch {i // LOTE_CLIPS + 1}")
            continue
        clips.update(data.get("clips") or {})
        print(f"  [info] hydrated {len(clips)}/{len(ids)} clips")
        time.sleep(ESPERA_LISTADO)
    return clips


# ------------------------------------------------------------- metadata

def nombre_seguro(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    permitidos = "-_.() "
    limpio = "".join(c for c in name if c.isalnum() or c in permitidos).strip()
    return limpio[:120] if limpio else fallback


def _valor(campo):
    """Varios campos vienen envueltos en {'status': ..., 'value': ...}
    porque se calculan de forma asincrona. Devuelve el value si lo hay."""
    if isinstance(campo, dict) and "value" in campo:
        return campo["value"]
    return campo


def extraer_metadata(clip: dict, conversacion: dict = None) -> dict:
    operacion = clip.get("operation") or {}
    letra = _valor(clip.get("lyrics")) or {}

    # duration llega como {'status': ..., 'value': '270.57...'}, con el
    # value en string. Si la pista aun se esta procesando no hay value, y
    # entonces hay que dejar None: guardar el diccionario a medias en un
    # campo que se espera numerico revienta a quien lo consuma despues.
    bruto = clip.get("duration")
    estado_duracion = bruto.get("status") if isinstance(bruto, dict) else None
    try:
        duracion = float(_valor(bruto))
    except (TypeError, ValueError):
        duracion = None

    return {
        "id": clip.get("id"),
        "title": clip.get("title"),
        "created_at": clip.get("created_at"),
        "duration": duracion,
        "duration_status": estado_duracion,
        "author_id": clip.get("author_id"),
        "privacy": clip.get("privacy"),
        "is_favorite": clip.get("is_favorite"),
        "favorite_count": clip.get("favorite_count"),
        "play_count": clip.get("play_count"),
        "has_vocals": clip.get("has_vocals"),
        "allow_public_use": clip.get("allow_public_use"),
        "is_remix_eligible": clip.get("is_remix_eligible"),
        "deleted_at": clip.get("deleted_at"),
        # La letra vive anidada bajo lyrics.value.text
        "lyrics": (letra or {}).get("text") if isinstance(letra, dict) else None,
        "lyrics_id": (letra or {}).get("id") if isinstance(letra, dict) else None,
        "lyrics_timing": _valor(clip.get("lyrics_timing")),
        # op_type es el equivalente al 'task' de Suno: que operacion creo
        # esta pista (audio__create_song, audio__render_edit,
        # audio__split_stems...).
        "op_type": clip.get("op_type"),
        "op_id": clip.get("op_id"),
        # El linaje: de que pistas sale esta. Equivale a los
        # cover_clip_id / mashup_clip_ids de Suno.
        "source_clip_ids": operacion.get("source_clip_ids"),
        "clip_outputs": operacion.get("clip_outputs"),
        "recipe_id": operacion.get("recipe_id"),
        # La instruccion en lenguaje natural con la que se pidio la pista.
        "instruction": operacion.get("instruction"),
        "conversation_id": operacion.get("conversation_id"),
        "conversation_title": (conversacion or {}).get("title"),
        "project_id": (conversacion or {}).get("project_id"),
        "audio_url": clip.get("audio_url"),
        "wav_url": clip.get("wav_url"),
        "image_url": clip.get("image_url"),
        "video_url": clip.get("video_url"),
        # Red de seguridad, igual que en el backup de Suno: si manana
        # aparece un campo que no mapeamos, esta aqui.
        "raw": clip,
    }


# ------------------------------------------------------------ descargas

def descargar(cdn, url, destino: Path, debug=False) -> str:
    """Devuelve 'ya', 'ok' o 'error'.

    Escribe primero a un .part y solo renombra si el tamano cuadra con el
    Content-Length. Sin esto, un corte de red a mitad de un wav de 50 MB
    deja un fichero truncado que en la siguiente pasada parece completo y
    nunca se repara."""
    if destino.exists() and destino.stat().st_size > 0:
        return "ya"

    parcial = Path(str(destino) + ".part")
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            with cdn.get(url, stream=True, timeout=TIMEOUT) as r:
                if r.status_code == 404:
                    # Ausencia permanente, no un fallo transitorio: la API
                    # construye wav_url a partir del id del clip, exista el
                    # fichero o no. Los stems (audio__split_stems) solo se
                    # renderizan en m4a, asi que su wav_url siempre da 404.
                    # Reintentarlo son tres peticiones y dos esperas tiradas.
                    return "ausente"
                if r.status_code != 200:
                    if debug:
                        print(f"      [warn] status {r.status_code} on attempt {intento}")
                    time.sleep(2 * intento)
                    continue
                esperado = int(r.headers.get("content-length") or 0)
                escrito = 0
                with open(parcial, "wb") as fh:
                    for trozo in r.iter_content(chunk_size=1 << 16):
                        if trozo:
                            fh.write(trozo)
                            escrito += len(trozo)
                if esperado and escrito != esperado:
                    print(f"      [warn] incomplete download ({escrito}/{esperado} bytes), retrying")
                    parcial.unlink(missing_ok=True)
                    time.sleep(2 * intento)
                    continue
                parcial.replace(destino)
                return "ok"
        except requests.RequestException as e:
            if debug:
                print(f"      [warn] network error on attempt {intento}: {e}")
            time.sleep(2 * intento)

    parcial.unlink(missing_ok=True)
    return "error"


def guardar_clip(cdn, meta: dict, carpeta: Path, formatos, debug=False):
    """Devuelve la lista de formatos que el CDN no tiene (404), para que
    verify_flowmusic.py no los cuente como descargas fallidas."""
    clip_id = meta.get("id") or "sin_id"
    titulo = nombre_seguro(meta.get("title"), clip_id)
    base = f"{titulo}_{clip_id}"
    ausentes = []

    (carpeta / f"{base}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    for ext in formatos:
        url = meta.get(EXTENSIONES[ext])
        if not url:
            print(f"      [warn] no {ext} for '{titulo}'")
            continue
        estado = descargar(cdn, url, carpeta / f"{base}.{ext}", debug=debug)
        if estado == "ok":
            print(f"      [ok] {ext}")
        elif estado == "ausente":
            print(f"      [info] no {ext} on the CDN for '{titulo}'")
            ausentes.append(ext)
        elif estado == "error":
            print(f"      [error] could not download the {ext} for '{titulo}'")
        if estado != "ya":
            time.sleep(ESPERA_DESCARGA)

    if meta.get("image_url"):
        estado = descargar(cdn, meta["image_url"], carpeta / f"{base}.jpg", debug=debug)
        if estado == "ok":
            print("      [ok] cover")
        elif estado == "ausente":
            ausentes.append("jpg")
        if estado != "ya":
            time.sleep(ESPERA_DESCARGA)

    return ausentes


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Backup de tu biblioteca de Flow Music.")
    ap.add_argument("--token", help="Bearer token. Mejor por entorno o --token-file.")
    ap.add_argument("--token-file", help="Fichero de texto con el token.")
    ap.add_argument("--out", default="./flowmusic_backup", help="Carpeta de salida.")
    ap.add_argument("--formats", default="m4a,wav",
                    help="Formatos de audio separados por coma: m4a, wav, o ambos.")
    ap.add_argument("--no-resume", action="store_true",
                    help="Recorre todas las conversaciones aunque no hayan cambiado.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Procesa solo las N conversaciones mas recientes. Para probar.")
    ap.add_argument("--rehidratar", action="store_true",
                    help="Vuelve a pedir la metadata de TODAS las pistas del indice, "
                         "no solo de las nuevas. Para reconstruir el indice sin "
                         "volver a descargar el audio, que no se toca.")
    ap.add_argument("--solo-metadata", action="store_true",
                    help="Construye el indice pero no descarga audio ni portadas. "
                         "Sirve para validar el recorrido entero sin bajar gigas.")
    ap.add_argument("--debug", action="store_true", help="Info extra para depurar.")
    args = ap.parse_args()

    # Igual que en backup_suno.py: el token por entorno o por fichero,
    # nunca en argv, porque argv es visible en la lista de procesos del
    # sistema (tasklist / ps) para cualquiera que mire.
    token = args.token or os.environ.get("FLOWMUSIC_TOKEN")
    if not token and args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if token and token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print("[error] you need FLOWMUSIC_TOKEN, --token-file or --token")
        sys.exit(1)
    if "…" in token:
        print("[error] the token contains the character '…': you copied it truncated from")
        print("        Chrome's Headers panel. Take it from a 'Copy as cURL' instead.")
        sys.exit(1)

    formatos = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    desconocidos = [f for f in formatos if f not in EXTENSIONES]
    if desconocidos:
        print(f"[error] unrecognised format: {desconocidos}. Valid: {list(EXTENSIONES)}")
        sys.exit(1)

    carpeta = Path(args.out)
    carpeta.mkdir(parents=True, exist_ok=True)

    api = sesion_api(token)
    cdn = sesion_cdn()

    estado_path = carpeta / "_state.json"
    indice_path = carpeta / "_index.json"
    estado = {}
    indice = {}
    if not args.no_resume:
        if estado_path.exists():
            try:
                estado = json.loads(estado_path.read_text(encoding="utf-8"))
                print(f"[info] previous state: {len(estado)} conversations already read")
            except json.JSONDecodeError:
                print("[warn] _state.json is corrupt, everything will be read again")
        if indice_path.exists():
            try:
                indice = json.loads(indice_path.read_text(encoding="utf-8"))
                print(f"[info] previous index: {len(indice)} tracks")
            except json.JSONDecodeError:
                print("[warn] _index.json is corrupt, it will be rebuilt")

    print("[info] listing conversations...")
    conversaciones = listar_conversaciones(api, debug=args.debug)
    if not conversaciones:
        print("[error] no conversations returned. Expired token, or the API changed.")
        sys.exit(1)
    (carpeta / "_conversations.json").write_text(
        json.dumps(conversaciones, indent=2, ensure_ascii=False), encoding="utf-8")

    # Solo se relee lo que ha cambiado desde la ultima pasada.
    # Se relee una conversacion si ha cambiado O si no tenemos su JSON
    # guardado. Lo segundo hace que los backups hechos antes de que
    # guardaramos conversaciones se completen solos en la siguiente pasada,
    # sin tener que acordarse de pasar --no-resume.
    (carpeta / CARPETA_CONVERSACIONES).mkdir(parents=True, exist_ok=True)
    pendientes = [c for c in conversaciones
                  if estado.get(c["id"]) != c.get("last_message_at")
                  or not ruta_conversacion(carpeta, c).is_file()]
    print(f"[info] {len(conversaciones)} conversations, {len(pendientes)} to read")

    if args.limit:
        pendientes = pendientes[:args.limit]
        print(f"[info] --limit {args.limit}: only {len(pendientes)} will be processed")

    clip_ids_por_conv = {}
    for i, conv in enumerate(pendientes, start=1):
        titulo = conv.get("title") or conv["id"]
        print(f"[{i}/{len(pendientes)}] reading: {titulo}")
        r = pedir(api, f"{BASE}{CONVERSACIONES}/{conv['id']}", debug=args.debug)
        if r is None:
            print("  [warn] could not be read, it will be retried on the next pass")
            continue
        try:
            detalle = r.json()
        except json.JSONDecodeError:
            print("  [warn] non-JSON response, skipping")
            continue

        # La conversacion entera, no solo los ids. Es la mitad de la
        # memoria: lo que pediste, lo que respondio el agente y con que
        # instrucciones acabo generando cada pista. Ya la teniamos pedida
        # -- guardarla no cuesta ni una llamada mas.
        ruta_conversacion(carpeta, conv).write_text(
            json.dumps(detalle, indent=2, ensure_ascii=False), encoding="utf-8")

        ids = list(dict.fromkeys(recolectar_clip_ids(detalle)))
        clip_ids_por_conv[conv["id"]] = ids
        mensajes = len(detalle.get("messages") or [])
        print(f"  [info] {len(ids)} clip ids, {mensajes} messages saved")
        estado[conv["id"]] = conv.get("last_message_at")
        time.sleep(ESPERA_LISTADO)

    estado_path.write_text(json.dumps(estado, indent=2), encoding="utf-8")

    # Hidratar todo lo nuevo de una tacada, en lotes.
    todos_ids = []
    for ids in clip_ids_por_conv.values():
        todos_ids.extend(ids)
    if args.rehidratar:
        # Tambien los que ya estaban: sirve para reconstruir el indice con
        # una version nueva de extraer_metadata sin tocar el audio.
        todos_ids.extend(indice.keys())
        nuevos = list(dict.fromkeys(todos_ids))
        print(f"\n[info] --rehidratar: {len(nuevos)} clips (all of them, not just the new ones)")
    else:
        nuevos = [i for i in dict.fromkeys(todos_ids) if i not in indice]
        print(f"\n[info] {len(nuevos)} new clips to hydrate")

    if nuevos:
        clips = hidratar_clips(api, nuevos, debug=args.debug)
        conv_por_clip = {}
        for conv_id, ids in clip_ids_por_conv.items():
            for cid in ids:
                conv_por_clip[cid] = conv_id
        por_id = {c["id"]: c for c in conversaciones}
        for cid, clip in clips.items():
            # El propio clip declara de que conversacion sale; el mapa que
            # construimos al recorrer es solo el plan B. Asi --rehidratar
            # sigue resolviendo el titulo aunque no haya recorrido nada.
            conv_id = ((clip.get("operation") or {}).get("conversation_id")
                       or conv_por_clip.get(cid))
            indice[cid] = extraer_metadata(clip, por_id.get(conv_id))
        indice_path.write_text(
            json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[info] index saved: {len(indice)} tracks in total")

    if args.solo_metadata:
        print("\n[info] --solo-metadata: no audio or covers are downloaded.")
    else:
        print(f"\n[info] downloading ({', '.join(formatos)} + cover)...")
        # Se acumula, no se sobreescribe: en una pasada con resume la
        # mayoria de ficheros ya estan y no se vuelve a comprobar el CDN,
        # asi que lo detectado en pasadas anteriores hay que conservarlo.
        ausentes_path = carpeta / "_ausentes.json"
        ausentes = {}
        if ausentes_path.exists():
            try:
                ausentes = json.loads(ausentes_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        for i, (cid, meta) in enumerate(indice.items(), start=1):
            print(f"[{i}/{len(indice)}] {meta.get('title') or cid}")
            faltan = guardar_clip(cdn, meta, carpeta, formatos, debug=args.debug)
            if faltan:
                ausentes[cid] = sorted(set(ausentes.get(cid, [])) | set(faltan))
        if ausentes:
            ausentes_path.write_text(
                json.dumps(ausentes, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[info] {len(ausentes)} tracks with a format the CDN does not have "
                  f"(recorded in _ausentes.json, they are not failures)")

    print(f"\n[done] backup at: {carpeta.resolve()}")
    print(f"Finished: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
