#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescue_pending.py — Descarga los pendientes de descarga y los archiva en su
banco, para que el siguiente reproceso los pinte enlazados en la nota.

POR QUÉ ES UN SCRIPT APARTE Y NO UN PASO DEL PIPELINE
─────────────────────────────────────────────────────
El pipeline no sale a Internet por iniciativa propia. Esa regla se ha ganado
su sitio dos veces y no se toca. La formulación buena es la de la sección 3i
de CONTEXT.md: *la app no sale a Internet por iniciativa propia; sale cuando
le pones un token en la mano y pulsas*. Aquí no hay token, pero sigue habiendo
un "pulsas": este script se ejecuta a mano, nunca desde `MemorIA2GO.py`, y sin
lanzarlo el pipeline se comporta exactamente igual que ayer.

Mismo patrón que MUSIC·0LOGY y Flow Music: herramienta hermana con red propia,
misma casa, pipeline intacto.

POR QUÉ EXISTE (V0ra, 2026-08-30)
─────────────────────────────────
V0ra descubrió que las URLs de contenido generado por Grok Imagine **no piden
autenticación**: cualquiera con el enlace se lleva el fichero. Medido sobre
sus 209 pendientes: todos en grok.com, ruta de tres segmentos y **cero
parámetros de query** — o sea, ni `Expires` ni `Signature`. No son enlaces
prefirmados: no caducan solos, y el enlace *es* la credencial.

La consecuencia que decidió construir esto: la herramienta recoge enlaces que
en el export están dispersos y los concentra en un único fichero plano. Quien
se lleve ese JSON se lleva la obra entera. Y como la URL se usa de clave
primaria (en ChatGPT literalmente `clave: url`), triar no reducía la
exposición: rescatar o descartar dejaba la URL dentro para siempre.

Bajar el binario es lo que convierte una llave viva en un fichero local.

**Lo que este script NO hace, y queda pendiente por decisión de V0ra**: no
borra ni ofusca las URLs ya guardadas. Primero salvar los activos, después
decidir qué se hace con los enlaces. Mientras tanto siguen ahí.

EL `link` NO ES EL ACTIVO (medido 2026-08-30, y casi cuesta un fallo silencioso)
───────────────────────────────────────────────────────────────────────────────
Los pendientes de Grok guardan `https://grok.com/imagine/post/<id>`, que es la
página compartible, no el fichero: responde HTML. La primera pasada real lo
cazó porque el guardia de firmas lo rechazó; sin él habríamos archivado 209
páginas de error con nombre de imagen.

De la página salen los dos caminos, verificados uno de cada:
  - vídeo  -> https://imagine-public.x.ai/imagine-public/share-videos/<id>.mp4
  - imagen -> https://grok.com/imagine/post/<id>/image

**En un post de vídeo, `og:image` es la miniatura.** Si se coge por ser la
primera etiqueta que aparece, se archiva un póster creyendo que es el vídeo, y
nada avisa. Por eso cada tipo de medio resuelve SOLO por su etiqueta.

Se intenta primero la URL derivada del `id` (una petición) y, si falla, se lee
la página y se saca de sus metaetiquetas (dos peticiones, pero se cree lo que
la página dice de sí misma en vez de un patrón inventado). Derivar es seguro
aquí porque el guardia de firmas convierte un patrón equivocado en un fallo
ruidoso, no en un fichero basura archivado.

QUÉ GARANTIZA
─────────────
- **Indistinguible del rescate manual.** Mismo banco, mismo nombre
  `sha1(bytes)[:16]+extensión`, mismo manifest y mismo modelo de estados que
  `registrar_pendiente()` de `launcher.py`. Un fichero rescatado aquí y otro
  subido por la pestaña Reconexión no se diferencian en nada.
- **No inventa rescates.** Si la descarga falla, la entrada se queda TAL CUAL
  (sin `estado`), así que sigue apareciendo en Reconexión para hacerla a mano.
  Nunca se marca `error`: eso la escondería de la pestaña, que es justo lo
  contrario de lo que hace falta.
- **No archiva basura.** Una URL sin autenticación puede responder 200 con una
  página de error. Se mira la firma de los bytes, no el nombre ni el
  Content-Type (que mienten: por eso existe `sniff_ext`), y lo que huele a
  HTML/JSON se rechaza en vez de guardarse como `.bin`.
- **Reanudable.** El JSON se guarda cada pocos rescates y al salir, también si
  la cortas con Ctrl-C. Volver a lanzarlo continúa donde estaba.

Uso:
    python rescue_pending.py                      # Grok, todos los pendientes
    python rescue_pending.py --dry-run            # dice qué haría, sin red
    python rescue_pending.py --limite 3           # solo los tres primeros
    python rescue_pending.py --proveedor chatgpt  # las imágenes web de ChatGPT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from html import unescape
from pathlib import Path
from typing import Callable, Optional

for _flujo in (sys.stdout, sys.stderr):
    # La consola de Windows llega en cp1252 y estos mensajes llevan acentos y
    # el interpunto de MUSIC·0LOGY. Sin esto, el script revienta al imprimir.
    try:
        _flujo.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from split_chatgpt_export import sniff_ext  # noqa: E402  (tras ajustar sys.path)
from pendientes import sanear, cuenta_credenciales, esta_sin_triar  # noqa: E402


# Tope por fichero. Un vídeo de Imagine son megas, no cientos: si algo llega
# con este tamaño es que no es lo que creemos y mejor no escribirlo en disco.
MAX_BYTES = 512 * 1024 * 1024
FLUSH_CADA = 10

# Tope para la PÁGINA del post, que no es un activo: las de Imagine rondan
# los 850 KB de HTML. Si llega mucho más, no es lo que creemos.
MAX_PAGINA = 8 * 1024 * 1024

# Formas del activo derivadas del id del post, verificadas contra los dos
# tipos reales el 2026-08-30. Ver el bloque "EL `link` NO ES EL ACTIVO".
URL_VIDEO = "https://imagine-public.x.ai/imagine-public/share-videos/%s.mp4"
URL_IMAGEN = "https://grok.com/imagine/post/%s/image"

# Etiqueta que describe el activo de cada tipo de medio. Es un mapa estricto a
# propósito: en un post de vídeo, og:image existe y es la miniatura, así que
# "la primera que haya" archivaría el póster en lugar del vídeo.
META_POR_MEDIO = {"video": "og:video", "image": "og:image"}


# ── Los dos proveedores, que NO tienen la misma forma ──────────────────────
#
# Grok    -- generaciones propias de V0ra en Imagine cuyo binario no viaja en
#            el zip. Clave `id`, enlace en `link`, banco por tipo de medio.
# ChatGPT -- imágenes de búsqueda web (de terceros) que salieron en la
#            conversación. Clave `url`, que es también el enlace, banco propio.
#
# Copiado del contrato real de launcher.py, no reinventado: si esto diverge,
# el paso 1 deja de pintar los rescates.
PROVEEDORES = {
    "grok": {"carpeta": "GROK", "clave": "id"},
    "chatgpt": {"carpeta": "CHATGPT", "clave": "url"},
}


class ErrorDeRescate(Exception):
    """Falla el rescate de UNA entrada. Nunca aborta el recorrido: se anota,
    la entrada se deja sin triar y se sigue con la siguiente."""


# ── Lectura y escritura de la lista de pendientes ──────────────────────────

def ruta_pendientes(base_vault: Path, proveedor: str) -> Path:
    return base_vault / PROVEEDORES[proveedor]["carpeta"] / "_pendientes_descarga.json"


def leer_pendientes(path: Path) -> list:
    """utf-8-sig porque el fichero ha pasado por manos y editores de Windows y
    un BOM delante rompería json.load en silencio. Mismo criterio que
    `_leer_pendientes` en launcher.py."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        datos = json.load(f)
    return datos if isinstance(datos, list) else []


def escribir_pendientes(path: Path, datos: list, proveedor: str = "grok") -> None:
    """tmp+replace: un corte a mitad no puede dejar el triaje en un JSON roto.
    Idéntico a `_escribir_pendientes` de launcher.py, saneo incluido: lo que
    sale de aquí lleva `ref` y ninguna entrada triada conserva su enlace."""
    sanear(datos, proveedor)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


def sin_triar(pendientes: list) -> list:
    """Sin `estado` = sin triar, para no romper ficheros ya existentes."""
    return [p for p in pendientes
            if (p.get("estado") or "sin_triar") == "sin_triar"]


# ── Red ────────────────────────────────────────────────────────────────────

def descargar(url: str, *, intentos: int = 3, timeout=(10, 60)) -> bytes:
    """Baja la URL entera a memoria, con reintentos para lo que es transitorio.

    Un 404 no se reintenta: si el enlace ya no existe, insistir tres veces solo
    hace perder tiempo y ruido. Los 5xx y el 429 sí, que son del otro lado.
    """
    import requests

    ultimo = None
    for intento in range(1, intentos + 1):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code in (404, 403, 410):
                raise ErrorDeRescate("HTTP %d" % resp.status_code)
            resp.raise_for_status()

            trozos, total = [], 0
            for trozo in resp.iter_content(chunk_size=65536):
                if not trozo:
                    continue
                total += len(trozo)
                if total > MAX_BYTES:
                    raise ErrorDeRescate("pasa de %d MB, no lo escribo"
                                         % (MAX_BYTES // (1024 * 1024)))
                trozos.append(trozo)
            return b"".join(trozos)

        except ErrorDeRescate:
            raise
        except Exception as e:          # red, timeout, 5xx, 429
            ultimo = e
            if intento < intentos:
                time.sleep(intento * 2)
    raise ErrorDeRescate("no se pudo descargar (%s)" % ultimo)


def descargar_texto(url: str, *, timeout=(10, 60)) -> str:
    """Baja una página HTML. Separada de `descargar` porque lo que se espera
    aquí es justo lo que allí se rechaza."""
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text[:MAX_PAGINA]


# ── Resolver dónde está el activo de verdad ────────────────────────────────

def url_derivada(entrada: dict) -> Optional[str]:
    """La URL del activo a partir del id del post, sin pedir la página."""
    ident = str(entrada.get("id") or "").strip()
    if not ident:
        return None
    if entrada.get("media_type") == "video":
        return URL_VIDEO % ident
    return URL_IMAGEN % ident


def meta_contenido(html: str, clave: str) -> Optional[str]:
    """El `content` de la metaetiqueta pedida. Tolerante con el orden de los
    atributos y con `property=` o `name=`, que las dos formas se ven."""
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if re.search(r'(?:property|name)\s*=\s*["\']%s["\']' % re.escape(clave),
                     tag, re.I):
            m = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.I)
            if m and m.group(1).strip():
                return unescape(m.group(1).strip())
    return None


def url_desde_pagina(html: str, entrada: dict) -> Optional[str]:
    """El activo según lo que la propia página dice de sí misma.

    Cada tipo de medio mira SOLO su etiqueta: og:image en un post de vídeo es
    la miniatura, y devolverla sería archivar un póster como si fuera el vídeo.
    """
    clave = META_POR_MEDIO.get(entrada.get("media_type"))
    if not clave:
        return None
    return meta_contenido(html, clave)


def obtener_activo(entrada: dict, proveedor: str, fetch, fetch_pagina) -> bytes:
    """Los bytes del activo, probando la vía barata antes que la robusta.

    En ChatGPT la propia entrada ya guarda la URL directa: no hay nada que
    resolver ni página que leer.
    """
    if proveedor == "chatgpt":
        url = (entrada.get("url") or "").strip()
        if not url:
            raise ErrorDeRescate("sin enlace")
        data = fetch(url)
        comprobar_asset(data)
        return data

    fallo = None
    derivada = url_derivada(entrada)
    if derivada:
        try:
            data = fetch(derivada)
            comprobar_asset(data)
            return data
        except ErrorDeRescate as e:
            fallo = e

    # Red de seguridad: preguntarle a la página en vez de insistir con un
    # patrón que quizá haya cambiado.
    pagina_url = (entrada.get("link") or "").strip()
    if pagina_url and fetch_pagina:
        try:
            url = url_desde_pagina(fetch_pagina(pagina_url), entrada)
        except Exception as e:
            raise ErrorDeRescate("no se pudo leer la página (%s)" % e)
        if url:
            data = fetch(url)
            comprobar_asset(data)
            return data
        raise ErrorDeRescate("la página no declara el activo (%s)"
                             % META_POR_MEDIO.get(entrada.get("media_type"),
                                                  "tipo de medio desconocido"))

    raise fallo or ErrorDeRescate("sin enlace")


def comprobar_asset(data: bytes) -> str:
    """Devuelve la extensión, o revienta si esto no es un activo.

    Una URL sin autenticación puede contestar 200 con una página de error, y
    guardarla como `.bin` sería justo el fallo silencioso que esta casa
    colecciona: el fichero existiría, el manifest lo daría por bueno y la nota
    enlazaría a una imagen que es HTML.
    """
    if not data:
        raise ErrorDeRescate("respuesta vacía")

    ext = sniff_ext(data)
    if ext != ".bin":
        return ext

    cabeza = data[:512].lstrip()[:64].lower()
    for firma in (b"<!doctype", b"<html", b"<?xml", b"{", b"["):
        if cabeza.startswith(firma):
            raise ErrorDeRescate("no es un activo (parece HTML/JSON)")
    # Formato que sniff_ext no conoce todavía (webm, mov...). Se guarda, pero
    # se cuenta aparte para que salga en el resumen y se pueda mirar.
    return ".bin"


# ── Archivado, calcado del rescate manual de launcher.py ───────────────────

def _banco(base_vault: Path, proveedor: str, entrada: dict) -> Path:
    if proveedor == "chatgpt":
        # Banco propio a propósito (decisión V0ra 2026-07-27): no es GENERADAS
        # (no la generó la IA) ni ADJUNTOS (no la subió ella).
        return base_vault / "CHATGPT" / "WEB"
    nombre = ("GENERADAS_VIDEO" if entrada.get("media_type") == "video"
              else "GENERADAS_IMAGEN")
    return base_vault / "GROK" / nombre


def _anotar_manifest(banco: Path, fname: str, proveedor: str, entrada: dict) -> None:
    manifest_path = banco / "_image_manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            # Un manifest corrupto no puede impedir archivar: se reconstruye.
            manifest = {}

    if proveedor == "chatgpt":
        manifest[fname] = {
            "origen": "web",
            "url_original": entrada.get("url"),
            "queries": entrada.get("queries") or [],
            "conversaciones": entrada.get("conversaciones") or [],
        }
    else:
        manifest[fname] = {
            "origen": "generada",
            "prompt": entrada.get("prompt"),
            "media_type": entrada.get("media_type"),
            "create_time": entrada.get("create_time"),
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def archivar(base_vault: Path, proveedor: str, entrada: dict, data: bytes) -> str:
    """Escribe el binario en su banco y anota el manifest. Devuelve el nombre.

    Mismo esquema hash+extensión que la extracción automática, para que un
    activo rescatado aquí sea indistinguible de uno sacado del export.
    """
    ext = comprobar_asset(data)
    banco = _banco(base_vault, proveedor, entrada)
    banco.mkdir(parents=True, exist_ok=True)

    fname = "%s%s" % (hashlib.sha1(data).hexdigest()[:16], ext)
    dest = banco / fname
    if not dest.exists():
        dest.write_bytes(data)

    _anotar_manifest(banco, fname, proveedor, entrada)
    return fname


# ── El recorrido ───────────────────────────────────────────────────────────

def rescatar(base_vault: Path,
             proveedor: str = "grok",
             *,
             fetch: Optional[Callable[[str], bytes]] = None,
             fetch_pagina: Optional[Callable[[str], str]] = None,
             limite: Optional[int] = None,
             dry_run: bool = False,
             pausa: float = 0.4,
             log: Callable[[str], None] = print) -> dict:
    """Recorre los pendientes sin triar y los rescata uno a uno.

    `fetch` y `fetch_pagina` se inyectan para poder probar todo el recorrido
    sin red. Si se pasa `fetch` a mano y no `fetch_pagina`, no hay red de
    seguridad por página: falla y se anota, que es lo que quieren los tests.
    """
    if proveedor not in PROVEEDORES:
        raise ValueError("proveedor desconocido: %s" % proveedor)

    if fetch is None:
        fetch = descargar
        fetch_pagina = fetch_pagina or descargar_texto
    cfg = PROVEEDORES[proveedor]
    path = ruta_pendientes(base_vault, proveedor)
    pendientes = leer_pendientes(path)
    cola = sin_triar(pendientes)
    if limite is not None:
        cola = cola[:limite]

    stats = {"total": len(pendientes), "sin_triar": len(sin_triar(pendientes)),
             "intentados": len(cola), "rescatados": 0, "fallidos": 0,
             "desconocidos": 0, "fallos": []}

    if not cola:
        log("No hay pendientes sin triar en %s." % cfg["carpeta"])
        return stats

    log("%s: %d sin triar, %d a intentar%s"
        % (cfg["carpeta"], stats["sin_triar"], len(cola),
           "  [DRY-RUN, sin red]" if dry_run else ""))

    sucios = 0
    try:
        for i, entrada in enumerate(cola, 1):
            ident = entrada.get(cfg["clave"]) or "(sin clave)"
            etiqueta = str(ident)[:48]

            if dry_run:
                destino = (url_derivada(entrada) if proveedor == "grok"
                           else (entrada.get("url") or ""))
                log("  [%d/%d] %-50s -> %s  %s"
                    % (i, len(cola), etiqueta,
                       _banco(base_vault, proveedor, entrada).name,
                       destino or "(habrá que leer la página)"))
                continue

            try:
                data = obtener_activo(entrada, proveedor, fetch, fetch_pagina)
                fname = archivar(base_vault, proveedor, entrada, data)
            except ErrorDeRescate as e:
                # La entrada se queda intacta y sin `estado`: sigue saliendo en
                # Reconexión para rescatarla a mano.
                stats["fallidos"] += 1
                stats["fallos"].append((etiqueta, str(e)))
                log("  [%d/%d] %-50s FALLA: %s" % (i, len(cola), etiqueta, e))
                continue

            entrada["estado"] = "rescatada"
            entrada["fichero"] = fname
            stats["rescatados"] += 1
            if fname.endswith(".bin"):
                stats["desconocidos"] += 1
            sucios += 1
            log("  [%d/%d] %-50s -> %s (%.1f KB)"
                % (i, len(cola), etiqueta, fname, len(data) / 1024))

            if sucios >= FLUSH_CADA:
                escribir_pendientes(path, pendientes, proveedor)
                sucios = 0
            if pausa:
                time.sleep(pausa)

    except KeyboardInterrupt:
        log("\nInterrumpido. Guardando lo rescatado hasta aquí...")
    finally:
        if sucios and not dry_run:
            escribir_pendientes(path, pendientes, proveedor)

    return stats


def _resumen(stats: dict, log=print) -> None:
    log("")
    log("Rescatados: %d   ·   Fallidos: %d   ·   Sin triar antes: %d"
        % (stats["rescatados"], stats["fallidos"], stats["sin_triar"]))
    if stats["desconocidos"]:
        log("Ojo: %d con formato que sniff_ext no conoce, guardados como .bin."
            % stats["desconocidos"])
    if stats["fallos"]:
        log("")
        log("Los fallidos siguen sin triar y salen en Reconexión para hacerlos")
        log("a mano. Motivos:")
        for ident, motivo in stats["fallos"][:20]:
            log("  · %-50s %s" % (ident, motivo))
        if len(stats["fallos"]) > 20:
            log("  ... y %d más." % (len(stats["fallos"]) - 20))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Descarga los pendientes y los archiva en su banco. "
                    "Se ejecuta a mano: el pipeline nunca lo llama.")
    ap.add_argument("--proveedor", default="grok", choices=sorted(PROVEEDORES),
                    help="grok (tus generaciones de Imagine) o chatgpt "
                         "(imágenes de búsqueda web de terceros)")
    ap.add_argument("--config", default=None, help="Ruta a memoria_config.yaml")
    ap.add_argument("--base-vault", default=None,
                    help="Salta la config y usa esta carpeta base")
    ap.add_argument("--limite", type=int, default=None,
                    help="Intenta solo los N primeros (para probar)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Dice qué haría, sin tocar la red ni el disco")
    ap.add_argument("--pausa", type=float, default=0.4,
                    help="Segundos entre descargas (por educación)")
    args = ap.parse_args()

    if args.base_vault:
        base_vault = Path(args.base_vault).expanduser().resolve()
    else:
        from config_loader import load_config, get_path
        cfg = load_config(args.config or str(HERE / "memoria_config.yaml"))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            print("base_vault no está configurado en memoria_config.yaml")
            return 2

    if not base_vault.exists():
        print("La carpeta base no existe: %s" % base_vault)
        return 2

    stats = rescatar(base_vault, args.proveedor,
                     limite=args.limite, dry_run=args.dry_run, pausa=args.pausa)
    _resumen(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
