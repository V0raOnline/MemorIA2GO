#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_copilot_images.py — Backup de tu biblioteca de imagenes de Copilot.

El export de Copilot (CSV) no trae las imagenes que generas. Este script las
baja a traves de la misma API que usa la Biblioteca de copilot.com, y se
queda con lo que la interfaz no te da: el PROMPT de cada imagen, las fechas
exactas y el resto de metadatos.

USO:
    $env:COPILOT_TOKEN="eyJ..."          # PowerShell
    python backup_copilot_images.py --out ./copilot_images_backup

    python backup_copilot_images.py --token-file token.txt --out ./copilot_images_backup
    python backup_copilot_images.py --solo-metadata --out ./copilot_images_backup

COMO CONSEGUIR EL TOKEN:
    1. Entra en copilot.com logueada y abre Biblioteca -> Imagenes.
    2. F12 -> pestana Network -> filtro 'Artifact.ashx'.
    3. Recarga. Clic derecho en la peticion -> Copy -> "Copy as cURL".
    4. Del texto pegado saca el valor de 'authorization:' SIN el prefijo
       'Bearer '. Es lo unico que hace falta (confirmado por ablacion: de las
       16 cabeceras que manda el navegador, el resto sobra, incluida
       storageinfo).

    NO lo copies del panel Headers: Chrome trunca los valores largos con una
    elipsis (…) y el token llegaria cortado.

EL TOKEN CADUCA (suele durar en torno a una hora). Si caduca a mitad, copia
uno nuevo y relanza: el listado es de 5 peticiones y lo ya descargado no se
vuelve a pedir.

ARQUITECTURA (mapeada contra la API real):

    POST designerapp.officeapps.live.com/designerapp/Artifact.ashx
         ?action=getArtifactList&artifact=Image,Infographics,MultiPageStory,Poster,Banner
         cuerpo: {ThumbnailSpec, OrderBy:"creationIndex desc",
                  NextLink, NextLinkSignature, PageSize}
         -> Items[] con Prompt, fechas, nombre, DownloadUrl al ORIGINAL;
            NextLink + NextLinkSignature para la pagina siguiente.

    GET  <DownloadUrl>      OneDrive personal; lleva un token temporal en la
                            propia URL, no necesita el Bearer.

Las DownloadUrl caducan, por eso NO se guardan en disco: en cada pasada se
vuelve a listar (barato) y se descarga lo que falte.

Las imagenes ya bajadas a mano (nombre que contenga el id de Copilot) se
reconocen y no se duplican: solo se les anade el .json con los metadatos.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

URL_LISTADO = ("https://designerapp.officeapps.live.com/designerapp/Artifact.ashx"
               "?action=getArtifactList"
               "&artifact=Image,Infographics,MultiPageStory,Poster,Banner")

PAGINA = 100
MAX_PAGINAS = 100          # tope de seguridad contra bucles infinitos
ESPERA_LISTADO = 0.4
ESPERA_DESCARGA = 0.25
MAX_REINTENTOS = 3
TIMEOUT = 60

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

EXT_POR_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


# ------------------------------------------------------------- sesiones

def sesion_api(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    })
    return s


def sesion_cdn() -> requests.Session:
    """Sesion SIN el token para bajar las imagenes: la URL ya lleva su propia
    autorizacion temporal y el Bearer no hay por que entregarselo a otro host."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


# -------------------------------------------------------------- listado

def pedir_pagina(session, siguiente: str, firma: str):
    """Devuelve el JSON de una pagina, 'caducado' si el token no vale, o None."""
    cuerpo = json.dumps({
        "ThumbnailSpec": "large",
        "OrderBy": "creationIndex desc",
        "NextLink": siguiente,
        "NextLinkSignature": firma,
        "PageSize": str(PAGINA),
    })
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            r = session.post(URL_LISTADO, data=cuerpo, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                return "caducado"
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * intento)
    return None


def listar_imagenes(session):
    """Recorre el listado paginado. Devuelve (items, error) donde error es
    None, 'caducado' o 'fallo'. Deduplica por ID: si una pagina repitiera
    elementos, no se cuentan dos veces."""
    items, vistos = [], set()
    siguiente, firma = "", ""
    for _ in range(MAX_PAGINAS):
        datos = pedir_pagina(session, siguiente, firma)
        if datos == "caducado":
            return items, "caducado"
        if not isinstance(datos, dict):
            return items, "fallo"
        nuevos = [i for i in (datos.get("Items") or []) if i.get("ID") not in vistos]
        vistos.update(i.get("ID") for i in nuevos)
        items.extend(nuevos)
        print(f"[info] listing: +{len(nuevos)} (total {len(items)})")
        info = datos.get("NextLinkInfo") or {}
        siguiente = info.get("NextLink") or datos.get("NextLink") or ""
        firma = info.get("NextLinkSignature") or ""
        if not siguiente or not nuevos:
            return items, None
        time.sleep(ESPERA_LISTADO)
    return items, None


# ------------------------------------------------------------- metadata

def nombre_seguro(texto, fallback: str, largo: int = 60) -> str:
    texto = (texto or "").strip()
    permitidos = "-_.() "
    limpio = "".join(c for c in texto if c.isalnum() or c in permitidos).strip()
    limpio = re.sub(r"\s+", " ", limpio)[:largo].strip()
    return limpio if limpio else fallback


def extraer_metadata(item: dict) -> dict:
    """Lo que vale la pena conservar. La DownloadUrl y las miniaturas llevan
    tokens temporales: se quitan, tanto de los campos como de 'raw'."""
    custom = item.get("ArtifactCustomMetadata") or {}
    crudo = {k: v for k, v in item.items() if k not in ("DownloadUrl", "Thumbnail")}
    return {
        "id": item.get("ID"),
        "name": item.get("Name"),
        "prompt": custom.get("Prompt") or None,
        "artifact_type": custom.get("ArtifactType"),
        "created_at": item.get("CreatedDateTime"),
        "modified_at": item.get("LastModifiedDateTime"),
        "creation_index": custom.get("CreationIndex"),
        "creation_id": custom.get("CreationId"),
        "user_action": custom.get("UserAction") or None,
        "template_metadata": custom.get("TemplateMetadata") or None,
        "mime": item.get("MimeType") or None,
        "size_bytes": item.get("SizeInBytes") or None,
        "width": item.get("Width"),
        "height": item.get("Height"),
        # Red de seguridad, como en los backups de Suno y Flow Music.
        "raw": crudo,
    }


def extension(item: dict) -> str:
    nombre = item.get("Name") or ""
    ext = os.path.splitext(nombre)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return ".jpg" if ext == ".jpeg" else ext
    return EXT_POR_MIME.get(item.get("MimeType") or "", ".jpg")


def nombre_base(item: dict) -> str:
    """fecha_prompt_id: se encuentra mirando la carpeta y el id garantiza que
    no choca con otra imagen del mismo prompt."""
    fecha = (item.get("CreatedDateTime") or "")[:10] or "no-date"
    custom = item.get("ArtifactCustomMetadata") or {}
    corto = nombre_seguro(custom.get("Prompt") or item.get("Name"), "image")
    return f"{fecha}_{corto}_{item['ID']}"


def localizar_existente(carpeta: Path, id_: str):
    """Imagen ya en disco cuyo nombre contiene el id (p.ej. las bajadas a
    mano antes de existir esta herramienta). Ignora .json y .part."""
    for f in carpeta.iterdir():
        if id_ in f.name and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") \
                and f.is_file() and f.stat().st_size > 0:
            return f
    return None


# ------------------------------------------------------------ descargas

def descargar(cdn, url: str, destino: Path, esperado_bytes=None) -> str:
    """Devuelve 'ok', 'caducado' o 'error'. Escribe a .part y solo renombra
    si el tamano cuadra, para que un corte no deje una imagen truncada
    haciendose pasar por completa."""
    parcial = Path(str(destino) + ".part")
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            with cdn.get(url, stream=True, timeout=TIMEOUT) as r:
                if r.status_code in (401, 403):
                    return "caducado"
                if r.status_code != 200:
                    time.sleep(2 * intento)
                    continue
                esperado = int(r.headers.get("content-length") or 0) or (esperado_bytes or 0)
                escrito = 0
                with open(parcial, "wb") as fh:
                    for trozo in r.iter_content(chunk_size=1 << 16):
                        if trozo:
                            fh.write(trozo)
                            escrito += len(trozo)
                if escrito == 0 or (esperado and escrito != esperado):
                    parcial.unlink(missing_ok=True)
                    time.sleep(2 * intento)
                    continue
                parcial.replace(destino)
                return "ok"
        except requests.RequestException:
            time.sleep(2 * intento)
    parcial.unlink(missing_ok=True)
    return "error"


def guardar_imagen(cdn, item: dict, carpeta: Path, solo_metadata=False) -> str:
    """Devuelve 'nueva', 'ya', 'error' o 'caducado'. Siempre deja el .json."""
    id_ = item["ID"]
    existente = localizar_existente(carpeta, id_)
    base = existente.stem if existente else nombre_base(item)

    (carpeta / f"{base}.json").write_text(
        json.dumps(extraer_metadata(item), indent=2, ensure_ascii=False), encoding="utf-8")

    if existente:
        return "ya"
    if solo_metadata:
        return "ya"
    url = item.get("DownloadUrl")
    if not url:
        return "error"
    estado = descargar(cdn, url, carpeta / f"{base}{extension(item)}",
                       esperado_bytes=item.get("SizeInBytes") or None)
    return {"ok": "nueva"}.get(estado, estado)


# ----------------------------------------------------------------- main

def leer_token(args):
    token = args.token or os.environ.get("COPILOT_TOKEN")
    if not token and args.token_file:
        try:
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
        except OSError:
            print(f"[error] cannot read the token file: {args.token_file}")
            sys.exit(1)
    if token and token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def main():
    ap = argparse.ArgumentParser(description="Backup of your Copilot image library.")
    ap.add_argument("--token", help="Bearer token. Better via environment or --token-file.")
    ap.add_argument("--token-file", help="Text file with the token.")
    ap.add_argument("--out", default="./copilot_images_backup", help="Output folder.")
    ap.add_argument("--solo-metadata", action="store_true",
                    help="Saves the index and the .json files but downloads no images.")
    args = ap.parse_args()

    # Igual que Suno y Flow Music: por entorno o fichero, nunca en argv.
    token = leer_token(args)
    if not token:
        print("[error] you need COPILOT_TOKEN, --token-file or --token")
        sys.exit(1)
    if "…" in token:
        print("[error] the token contains the character '…': you copied it truncated from the")
        print("        Chrome Headers panel. Take it from a 'Copy as cURL' instead.")
        sys.exit(1)

    carpeta = Path(args.out)
    carpeta.mkdir(parents=True, exist_ok=True)

    print("[info] listing the library...")
    items, error = listar_imagenes(sesion_api(token))
    if error == "caducado":
        print("[error] the token has expired or is invalid. Copy a new one and run again.")
        sys.exit(1)
    if not items:
        print("[error] no images were returned. Expired token, or the API changed.")
        sys.exit(1)
    if error == "fallo":
        print(f"[warning] the listing was cut short at {len(items)} images; continuing with those.")

    indice = {i["ID"]: extraer_metadata(i) for i in items}
    (carpeta / "_index.json").write_text(
        json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8")
    con_prompt = sum(1 for m in indice.values() if m["prompt"])
    print(f"[info] index: {len(indice)} images, {con_prompt} with a prompt")

    cdn = sesion_cdn()
    nuevas = ya = errores = 0
    for n, item in enumerate(items, start=1):
        estado = guardar_imagen(cdn, item, carpeta, solo_metadata=args.solo_metadata)
        if estado == "nueva":
            nuevas += 1
            print(f"[{n}/{len(items)}] new: {item['ID']}")
            time.sleep(ESPERA_DESCARGA)
        elif estado == "ya":
            ya += 1
        elif estado == "caducado":
            print("[error] the download URLs have expired. Run again: what was downloaded is kept.")
            errores += 1
            break
        else:
            errores += 1
            print(f"[{n}/{len(items)}] [error] could not download {item['ID']}")

    print(f"\n[done] new: {nuevas} · already there: {ya} · errors: {errores}")
    print(f"        backup at: {carpeta.resolve()}")
    print(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    sys.exit(1 if errores else 0)


if __name__ == "__main__":
    main()
