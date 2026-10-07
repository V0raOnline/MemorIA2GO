#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_grok_imagine.py — Baja tu biblioteca de Grok Imagine (imagenes y
videos) y la archiva en el banco GROK/IMAGINE.

El export de Grok parece completo y no lo es: solo ~18% de las generaciones de
Imagine viajan en el zip, y las ediciones privadas no vienen ni con su
linaje. La biblioteca de grok.com si las tiene todas, y esta herramienta se
las pide a su API.

USO:
    $env:GROK_COOKIE="sso=...; ..."          # PowerShell
    python backup_grok_imagine.py --grok-dir "<base_vault>/GROK"

    python backup_grok_imagine.py --grok-dir ... --cookie-file cookie.txt
    python backup_grok_imagine.py --grok-dir ... --solo-inventario

COMO CONSEGUIR LA COOKIE:
    1. Entra en grok.com/imagine con la sesion iniciada (tu biblioteca).
    2. F12 -> pestana Network -> filtra por 'assets' y refresca.
    3. Clic en la peticion a /rest/assets -> Headers -> Request Headers.
    4. Copia el valor ENTERO de 'Cookie'.

CUIDADO CON ESTA CREDENCIAL: no es un Bearer que caduca en minutos, es la
cookie de sesion de grok.com. Da acceso completo a la cuenta. Por eso va por
entorno o fichero (nunca por argv, que es visible en la lista de procesos), no
se imprime nunca y solo viaja a grok.com y assets.grok.com.

ARQUITECTURA (mapeada contra la API real, CONTEXT.md 3x/3y):

    GET grok.com/rest/assets?pageSize=100&orderBy=ORDER_BY_CREATE_TIME
        &workspaceKind=WORKSPACE_KIND_IMAGINE_ALL[&pageToken=...]
        -> {"assets": [...], "nextPageToken": ...}
        Sin filtrar por mimeTypes devuelve todo, no solo imagenes.
    GET assets.grok.com/<key>      el binario. Las imagenes piden cookie; los
                                   videos suelen servirse sin ella.

El tamano no vale para saber si ya tienes algo: la version de compartir de un
video esta recodificada y pesa distinto. Se deduplica por HASH del contenido
contra TODOS los bancos de GROK, y se decide despues de bajar.

Reanudable: _estado.json lleva el estado por assetId. Cortarlo y relanzarlo
continua donde iba. El manifest conserva lo que el export tira: el linaje
(`edicion_de`) de las ediciones y si la raiz la subio el usuario.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from split_chatgpt_export import sniff_ext  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

URL_LISTADO = "https://grok.com/rest/assets"
URL_ASSETS = "https://assets.grok.com/"
PARAMS = {
    "pageSize": "100",
    "orderBy": "ORDER_BY_CREATE_TIME",
    "workspaceKind": "WORKSPACE_KIND_IMAGINE_ALL",
}
MAX_PAGINAS = 200
MAX_BYTES = 512 * 1024 * 1024
MAX_REINTENTOS = 3
ESPERA_LISTADO = 0.3
ESPERA_DESCARGA = 0.25
GUARDAR_CADA = 10
TERMINALES = ("ok", "repetida", "ausente")

CARPETA_BANCO = "IMAGINE"
INVENTARIO = "_inventario.json"
ESTADO = "_estado.json"
MANIFEST = "_image_manifest.json"


# ------------------------------------------------------------- sesion

def limpiar_cookie(cookie: str) -> str:
    cookie = (cookie or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    return cookie


def cookie_valida(cookie: str):
    """None si sirve, o el motivo. Las cabeceras HTTP solo admiten latin-1 y
    Chrome trunca los valores largos con «…»: sin esta guarda el fallo es un
    UnicodeEncodeError que no explica nada."""
    if not cookie:
        return "the cookie is missing"
    if "…" in cookie:
        return "the cookie contains «…»: you copied it truncated from the Headers panel"
    try:
        cookie.encode("latin-1")
    except UnicodeEncodeError:
        return "the cookie contains characters that cannot go in an HTTP header"
    return None


def crear_sesion(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    if cookie:
        s.headers["Cookie"] = cookie
    return s


# ------------------------------------------------------------- listado

def listar_assets(session):
    """Devuelve (assets, error): error None, 'caducada' o 'fallo'.

    Salvaguarda de paginacion: si la pagina N repite lo de la anterior, el
    nombre del parametro no es el que creemos y seguir seria girar en redondo."""
    assets, vistos, token = [], set(), None
    for pagina in range(1, MAX_PAGINAS + 1):
        params = dict(PARAMS)
        if token:
            params["pageToken"] = token
        datos = None
        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                r = session.get("%s?%s" % (URL_LISTADO, urlencode(params)), timeout=60)
            except requests.RequestException:
                time.sleep(2 * intento)
                continue
            if r.status_code in (401, 403):
                return assets, "caducada"
            if r.status_code == 200:
                try:
                    datos = r.json()
                except ValueError:
                    datos = None
                break
            time.sleep(2 * intento)
        if not isinstance(datos, dict):
            return assets, "fallo"

        nuevos = [a for a in (datos.get("assets") or []) if a.get("assetId") not in vistos]
        if pagina > 1 and not nuevos:
            print("[warning] page %d brings nothing new: 'pageToken' does not seem to be "
                  "the right parameter. Stopping here." % pagina)
            return assets, "fallo"
        vistos.update(a.get("assetId") for a in nuevos)
        assets.extend(nuevos)
        token = datos.get("nextPageToken") or datos.get("next_page_token")
        print("[info] listing: page %d, +%d (total %d)" % (pagina, len(nuevos), len(assets)))
        if not token:
            return assets, None
        time.sleep(ESPERA_LISTADO)
    return assets, None


# ------------------------------------------------------------- bancos

def indexar_bancos(grok_dir: Path) -> dict:
    """Hash del contenido -> 'banco/fichero' de todo lo ya archivado en GROK.
    Se saltan los ficheros de trabajo (los que empiezan por '_')."""
    ya = {}
    if not grok_dir.is_dir():
        return ya
    for banco in grok_dir.iterdir():
        if not banco.is_dir():
            continue
        for f in banco.iterdir():
            if f.is_file() and not f.name.startswith("_"):
                ya[hashlib.sha1(f.read_bytes()).hexdigest()] = "%s/%s" % (banco.name, f.name)
    return ya


def leer_json(ruta: Path, defecto):
    if ruta.is_file():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return defecto


def escribir_json(ruta: Path, datos) -> None:
    """Escritura atomica: un corte a mitad no deja un manifest a medias, que
    es lo que decide que se vuelve a bajar y que no."""
    parcial = Path(str(ruta) + ".part")
    parcial.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    parcial.replace(ruta)


# ----------------------------------------------------------- descarga

def descargar(session, key: str):
    """Devuelve (estado, datos_o_motivo). Estados: 'ok', 'caducada' (401/403),
    'ausente' (404, permanente) o 'error' (transitorio)."""
    url = URL_ASSETS + key.lstrip("/")
    motivo = "error de red"
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            with session.get(url, timeout=(10, 120), stream=True) as r:
                if r.status_code in (401, 403):
                    return "caducada", "HTTP %d" % r.status_code
                if r.status_code == 404:
                    return "ausente", "HTTP 404"
                if r.status_code != 200:
                    motivo = "HTTP %d" % r.status_code
                    time.sleep(2 * intento)
                    continue
                esperado = int(r.headers.get("content-length") or 0)
                trozos, total = [], 0
                for t in r.iter_content(65536):
                    if not t:
                        continue
                    total += len(t)
                    if total > MAX_BYTES:
                        return "error", "demasiado grande"
                    trozos.append(t)
                data = b"".join(trozos)
                if not data:
                    motivo = "respuesta vacia"
                    time.sleep(2 * intento)
                    continue
                if esperado and len(data) != esperado:
                    motivo = "descarga incompleta (%d/%d)" % (len(data), esperado)
                    time.sleep(2 * intento)
                    continue
                cabeza = data[:512].lstrip()[:64].lower()
                if sniff_ext(data[:32]) == ".bin" and any(
                        cabeza.startswith(f) for f in (b"<!doctype", b"<html", b"{", b"[")):
                    return "error", "no es un activo (HTML/JSON)"
                return "ok", data
        except requests.RequestException as e:
            motivo = "error de red: %s" % str(e)[:40]
            time.sleep(2 * intento)
    return "error", motivo


def entrada_manifest(asset: dict, key: str) -> dict:
    aux = asset.get("auxKeys") or {}
    return {
        "origen": "imagine",
        "assetId": asset.get("assetId"),
        "key": key,
        "mime": asset.get("mimeType"),
        "create_time": asset.get("createTime"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "is_public": asset.get("isPublic"),
        # El linaje que el export NO trae: de que imagen es edicion.
        "edicion_de": aux.get("original-image") or None,
        "raiz_subida_por_usuario": aux.get("image_edit_is_root_user_uploaded"),
        "bajada_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def procesar(session, assets, banco: Path, ya: dict, estado: dict, manifest: dict) -> dict:
    """Baja lo pendiente. Devuelve contadores. Corta si la cookie caduca."""
    cuentas = {"nuevas": 0, "repetidas": 0, "ausentes": 0, "errores": 0, "caducada": False}
    pendientes = [a for a in assets if estado.get(a.get("assetId")) not in TERMINALES]
    print("[info] to attempt: %d of %d" % (len(pendientes), len(assets)))

    def guardar():
        escribir_json(banco / ESTADO, estado)
        escribir_json(banco / MANIFEST, manifest)

    try:
        for n, a in enumerate(pendientes, 1):
            aid = a.get("assetId")
            key = (a.get("key") or "").lstrip("/")
            etiqueta = (aid or "?")[:36]
            if not key:
                estado[aid] = "sin key"
                cuentas["errores"] += 1
                print("[%d/%d] %s NO key" % (n, len(pendientes), etiqueta))
                continue

            res, dato = descargar(session, key)
            if res == "caducada":
                cuentas["caducada"] = True
                print("[error] the cookie has expired or is invalid (%s). Copy a new one and run again: "
                      "what was already downloaded is kept." % dato)
                break
            if res == "ausente":
                estado[aid] = "ausente"
                cuentas["ausentes"] += 1
                print("[%d/%d] %s no longer exists on the server (404)" % (n, len(pendientes), etiqueta))
                continue
            if res != "ok":
                estado[aid] = "error"
                cuentas["errores"] += 1
                print("[%d/%d] %s FAILED: %s" % (n, len(pendientes), etiqueta, dato))
                continue

            h = hashlib.sha1(dato).hexdigest()
            if h in ya:
                estado[aid] = "repetida"
                cuentas["repetidas"] += 1
                print("[%d/%d] %s you already had it (%s)" % (n, len(pendientes), etiqueta, ya[h]))
            else:
                fname = "%s%s" % (h[:16], sniff_ext(dato[:32]))
                destino = banco / fname
                parcial = Path(str(destino) + ".part")
                parcial.write_bytes(dato)
                parcial.replace(destino)
                ya[h] = "%s/%s" % (banco.name, fname)
                manifest[fname] = entrada_manifest(a, key)
                estado[aid] = "ok"
                cuentas["nuevas"] += 1
                print("[%d/%d] %s -> %s (%.1f KB)" % (n, len(pendientes), etiqueta, fname, len(dato) / 1024))

            if n % GUARDAR_CADA == 0:
                guardar()
            time.sleep(ESPERA_DESCARGA)
    finally:
        guardar()
    return cuentas


# ----------------------------------------------------------------- main

def leer_cookie(args):
    cookie = args.cookie or os.environ.get("GROK_COOKIE")
    if not cookie and args.cookie_file:
        try:
            cookie = Path(args.cookie_file).read_text(encoding="utf-8")
        except OSError:
            print("[error] cannot read the cookie file: %s" % args.cookie_file)
            sys.exit(1)
    return limpiar_cookie(cookie)


def main():
    ap = argparse.ArgumentParser(description="Backup of your Grok Imagine library.")
    ap.add_argument("--grok-dir", required=True,
                    help="GROK folder of the vault (the one holding the banks).")
    ap.add_argument("--cookie", help="grok.com cookie. Better via environment or --cookie-file.")
    ap.add_argument("--cookie-file", help="Text file with the cookie.")
    ap.add_argument("--solo-inventario", action="store_true",
                    help="Saves the listing but downloads not a single byte.")
    args = ap.parse_args()

    # Igual que en el resto de backups: por entorno o fichero, nunca en argv.
    cookie = leer_cookie(args)
    motivo = cookie_valida(cookie)
    if motivo:
        print("[error] %s. Use the GROK_COOKIE variable, --cookie-file or --cookie." % motivo)
        sys.exit(1)

    grok_dir = Path(args.grok_dir)
    if not grok_dir.is_dir():
        print("[error] the GROK folder does not exist: %s" % grok_dir)
        sys.exit(1)
    banco = grok_dir / CARPETA_BANCO
    banco.mkdir(parents=True, exist_ok=True)

    session = crear_sesion(cookie)
    print("[info] listing the Imagine library...")
    assets, error = listar_assets(session)
    if error == "caducada":
        print("[error] the cookie has expired or is invalid. Copy a new one and run again.")
        sys.exit(1)
    if not assets:
        print("[error] no assets were returned. Expired cookie, or the API changed.")
        sys.exit(1)
    if error == "fallo":
        print("[warning] the listing was cut short at %d assets; continuing with those." % len(assets))

    escribir_json(banco / INVENTARIO, assets)
    pesos = sum(int(a.get("sizeBytes") or 0) for a in assets)
    print("[info] inventory: %d assets, %.1f MB" % (len(assets), pesos / 1048576))
    if args.solo_inventario:
        print("[done] --solo-inventario: nothing was downloaded.")
        return

    estado = leer_json(banco / ESTADO, {})
    manifest = leer_json(banco / MANIFEST, {})
    ya = indexar_bancos(grok_dir)
    print("[info] already archived in the Grok banks: %d files" % len(ya))

    c = procesar(session, assets, banco, ya, estado, manifest)
    ediciones = sum(1 for m in manifest.values() if m.get("edicion_de"))
    print("\n[done] new: %d · you already had: %d · no longer exist: %d · failed: %d"
          % (c["nuevas"], c["repetidas"], c["ausentes"], c["errores"]))
    print("        edits with their parent recorded: %d" % ediciones)
    print("        bank: %s" % banco.resolve())
    print("Finished: %s" % datetime.datetime.now().isoformat(timespec="seconds"))
    sys.exit(1 if (c["errores"] or c["caducada"]) else 0)


if __name__ == "__main__":
    main()
