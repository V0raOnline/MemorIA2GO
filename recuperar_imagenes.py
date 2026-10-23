#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recuperar_imagenes.py — Devuelve a las notas las imagenes de ChatGPT que quedaron
como "imagen no disponible en el export".

POR QUE EXISTE (2026-10-21)
───────────────────────────
El export de ChatGPT de octubre guarda las imagenes como `file_XXXX.dat`, sin el
sufijo -<uuid> del formato anterior, y AssetIndex solo conocia ese: no indexaba
ninguna y cada referencia salia como `*[imagen no disponible en el export: ...]*`,
sin un solo error. Ya esta arreglado para las importaciones nuevas, pero las notas
que ya existen siguen con el aviso.

POR QUE NO BASTA CON REIMPORTAR
───────────────────────────────
El merge de MERGED compara los mensajes por huella (rol + texto). Una nota con el
aviso y la misma nota con el enlace son, para el, mensajes DISTINTOS: reimportar deja
los dos. Medido sobre una copia del vault real: el hilo "Termino para latencia"
pasaba de 187 a 217 turnos de usuario y conservaba sus 44 avisos ademas de los 44
enlaces. Por eso esto sustituye el aviso por el enlace DENTRO de cada nota, sin
volver a fusionar nada, con el mismo texto que escribiria la importacion nueva
(`![](CHATGPT/<banco>/<huella>.<ext>)`): asi, cuando llegue el siguiente export,
el merge ve el mismo mensaje y no duplica.

LO QUE HACE
───────────
  1. Busca los avisos en RAW, MERGED y PRJ (las notas de PRJ son copias).
  2. Para cada puntero que el export SI trae, extrae el binario al banco que le toca
     (subida -> CHATGPT/ADJUNTOS, generada -> CHATGPT/GENERADAS), con el mismo
     criterio, la misma huella y el mismo manifiesto que la importacion.
  3. Sustituye el aviso por el enlace en las notas.
  4. Con --biblioteca, ademas, copia a GENERADAS las imagenes generadas que el export trae en
     `library_files.json` y ninguna conversacion enlaza (el export nuevo no lleva imagenes en los
     mensajes del asistente), y cada una la cuelga de SU conversacion: `origination_thread_id`
     es el conversation_id. Va como un mensaje `tool` al final de la nota (con el titulo y la
     hora de ChatGPT), igual que dejaban los exports antiguos, y el importador hace lo mismo
     con los exports nuevos. El mensaje exacto de origen no viene en el export, asi que no se
     puede colocar entre sus turnos.

LO QUE NO HACE
──────────────
  - No toca lo que el export no trae: esos avisos se quedan como estan.
  - No borra nada. Las imagenes copiadas se quedan aunque deshagas el cambio.
  - Sin --aplicar solo cuenta (simulacion): no escribe ni una nota ni una imagen.

SEGURIDAD
─────────
Con --aplicar guarda una copia EXACTA de cada nota antes de tocarla, y conserva su
fecha de modificacion (el merge desempata los renombrados por esa fecha). Se deshace
con --deshacer <carpeta de la copia>.

Uso:
  python recuperar_imagenes.py --export G:\\Backups\\export.zip --base-vault G:\\vaults
  python recuperar_imagenes.py --export ... --base-vault ... --aplicar [--biblioteca]
  python recuperar_imagenes.py --deshacer logs\\recuperar_imagenes_20261021_2200
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import split_chatgpt_export as sce  # noqa: E402

# El aviso que deja render_image_tokens cuando el binario no esta en el export.
MARCA_RE = re.compile(rb"\*\[imagen no disponible en el export: ([^\]\r\n]+)\]\*")

# origen de la imagen -> (carpeta del banco bajo la base, prefijo del enlace en las notas)
BANCOS = {
    "generada": "CHATGPT/GENERADAS",
    "subida": "CHATGPT/ADJUNTOS",
}

# Donde viven las notas dentro de la base (nombres de siempre).
CARPETAS_NOTAS = ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT")


class ErrorRecuperar(Exception):
    pass


def _titulo(texto: bytes) -> str:
    m = re.search(rb'^title:\s*"?(.*?)"?\s*$', texto[:2000], re.MULTILINE)
    return m.group(1).decode("utf-8", errors="replace") if m else ""


def buscar_avisos(base: Path):
    """({puntero: [rutas]}, {puntero: titulo de la primera nota}, notas_escaneadas)."""
    por_puntero: Dict[str, List[Path]] = {}
    titulo_de: Dict[str, str] = {}
    escaneadas = 0
    for rel in CARPETAS_NOTAS:
        raiz = base / rel
        if not raiz.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                ruta = Path(dirpath) / fn
                if ruta.is_symlink():
                    continue
                escaneadas += 1
                datos = ruta.read_bytes()
                for m in MARCA_RE.finditer(datos):
                    p = m.group(1).decode("utf-8", errors="replace")
                    lista = por_puntero.setdefault(p, [])
                    if not lista or lista[-1] != ruta:
                        lista.append(ruta)
                    titulo_de.setdefault(p, _titulo(datos))
    return por_puntero, titulo_de, escaneadas


class _Escritor:
    """AssetWriter de la importacion, o una version que no escribe nada (simulacion).
    Los dos dan el MISMO nombre de fichero: huella SHA-1 del contenido + extension."""

    def __init__(self, carpeta: Path, aplicar: bool):
        self.carpeta = carpeta
        self.aplicar = aplicar
        self.real = sce.AssetWriter(str(carpeta)) if aplicar else None
        self.nombres: Dict[str, str] = {}
        self.manifiesto: Dict[str, dict] = {}

    def write(self, data: bytes, ext: str, meta: Optional[dict] = None) -> str:
        if self.real is not None:
            return self.real.write(data, ext, meta=meta)
        h = hashlib.sha1(data).hexdigest()[:16]
        self.nombres[h] = f"{h}{ext}"
        return f"{h}{ext}"

    def cerrar(self) -> int:
        return self.real.flush_manifest() if self.real is not None else 0


def _leer_biblioteca(zf) -> Dict[str, dict]:
    """{file_id: entrada} de library_files.json, o {} si el export no la trae."""
    try:
        datos = json.loads(zf.read("library_files.json").decode("utf-8-sig"))
    except (KeyError, ValueError):
        return {}
    return {x["file_id"]: x for x in datos if isinstance(x, dict) and x.get("file_id")}


def _hacer_copia(ruta: Path, base: Path, destino: Path) -> None:
    rel = ruta.relative_to(base)
    copia = destino / rel
    copia.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ruta, copia)          # copy2: conserva tambien la fecha de modificacion


def _escribir_conservando_fecha(ruta: Path, datos: bytes) -> None:
    st = ruta.stat()
    tmp = ruta.with_name(ruta.name + ".recuperar.part")
    tmp.write_bytes(datos)
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(tmp, ruta)


def _cambiar_notas(base: Path, notas, transformar, export: Path, aplicar: bool,
                   carpeta_logs: Optional[Path], etiqueta: str, log) -> tuple:
    """Aplica `transformar(ruta, datos) -> datos` a cada nota. Con aplicar guarda antes una copia
    EXACTA de las que cambian, conserva la fecha de modificacion y escribe de forma atomica.
    Devuelve (notas_cambiadas, carpeta_de_la_copia)."""
    if not aplicar or not notas:
        return 0, None
    marca_tiempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logs = Path(carpeta_logs) if carpeta_logs else HERE / "logs"
    copia = logs / f"recuperar_imagenes_{marca_tiempo}{etiqueta}"
    copia.mkdir(parents=True, exist_ok=True)
    log(f"Copia de seguridad de las {len(notas)} notas en {copia}")
    for ruta in notas:
        _hacer_copia(ruta, base, copia)
    (copia / "diario.json").write_text(json.dumps({
        "export": str(export), "base": str(base), "fecha": marca_tiempo,
        "notas": [str(r.relative_to(base)) for r in notas],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    cambiadas = 0
    for ruta in notas:
        datos = ruta.read_bytes()
        nuevo = transformar(ruta, datos)
        if nuevo != datos:
            _escribir_conservando_fecha(ruta, nuevo)
            cambiadas += 1
    return cambiadas, str(copia)


CONV_ID_RE = re.compile(rb'^conv_id:\s*"?([^"\r\n]+?)"?\s*$', re.MULTILINE)


def notas_por_conv_id(base: Path) -> Dict[str, List[Path]]:
    """{conversation_id: [notas de RAW, MERGED y PRJ]} segun el `conv_id` de la cabecera."""
    por_hilo: Dict[str, List[Path]] = {}
    for rel in CARPETAS_NOTAS:
        raiz = base / rel
        if not raiz.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                ruta = Path(dirpath) / fn
                if ruta.is_symlink():
                    continue
                with open(ruta, "rb") as f:
                    m = CONV_ID_RE.search(f.read(2000))
                if m:
                    por_hilo.setdefault(m.group(1).decode("utf-8", errors="replace"), []).append(ruta)
    return por_hilo


def recuperar(export: Path, base: Path, aplicar: bool = False, biblioteca: bool = False,
              carpeta_logs: Optional[Path] = None, log=print) -> dict:
    export, base = Path(export), Path(base)
    if not export.is_file() or export.suffix.lower() != ".zip":
        raise ErrorRecuperar(f"--export tiene que ser el .zip del export de ChatGPT: {export}")
    if not base.is_dir():
        raise ErrorRecuperar(f"no existe la carpeta base: {base}")
    if not any((base / c).is_dir() for c in CARPETAS_NOTAS):
        raise ErrorRecuperar(f"no encuentro RAW_VAULT, MERGED_VAULT ni PRJ_VAULT en {base}")

    log(f"Buscando avisos 'imagen no disponible' en {base} ...")
    por_puntero, titulo_de, escaneadas = buscar_avisos(base)
    marcas = sum(len(v) for v in por_puntero.values())
    log(f"  {escaneadas} notas revisadas; {len(por_puntero)} imagenes distintas en {len(set(p for v in por_puntero.values() for p in v))} notas con aviso.")

    log(f"Leyendo el export {export.name} (puede tardar un par de minutos) ...")
    image_meta: Dict[str, dict] = {}
    conversaciones, zf = sce.load_conversations(str(export), image_meta_out=image_meta)
    if zf is None:
        raise ErrorRecuperar("el export no es un .zip con imagenes dentro")
    indice = sce.AssetIndex(zf)
    log(f"  {len(conversaciones)} conversaciones; {len(indice.by_id)} imagenes indexadas en el zip.")
    if not indice.by_id:
        raise ErrorRecuperar("no he podido indexar ninguna imagen del zip: el formato del export no se reconoce")

    escritores = {origen: _Escritor(base / prefijo, aplicar) for origen, prefijo in BANCOS.items()}
    biblioteca_por_id = _leer_biblioteca(zf)
    enlace_de: Dict[str, str] = {}
    sin_recuperar: List[str] = []
    bytes_total = 0
    for puntero in sorted(por_puntero):
        hallado = indice.get_bytes(puntero)
        if not hallado:
            sin_recuperar.append(puntero)
            continue
        data, ext = hallado
        meta = dict(image_meta.get(puntero) or {})
        if not meta:
            # Un aviso de una conversacion que este export ya no trae (las notas vienen de
            # exports anteriores): no hay metadatos de conversacion, pero la biblioteca del
            # export dice si la imagen es generada o subida y como se llamaba.
            entrada = biblioteca_por_id.get(sce.AssetIndex.resolve_pointer_id(puntero)) or {}
            meta["origen"] = "generada" if entrada.get("image_gen_generation_id") else "subida"
            if entrada.get("file_name") and meta["origen"] == "subida":
                meta["adjunto_nombre"] = entrada["file_name"]
        origen = meta.get("origen") or "subida"
        if origen not in escritores:
            origen = "subida"
        if titulo_de.get(puntero):
            meta["primera_conversacion"] = titulo_de[puntero]
        fname = escritores[origen].write(data, ext, meta=meta or None)
        enlace_de[puntero] = f"{BANCOS[origen]}/{fname}"
        bytes_total += len(data)

    resultado = {
        "aplicado": aplicar, "notas_revisadas": escaneadas, "imagenes_con_aviso": len(por_puntero),
        "marcas": marcas, "recuperables": len(enlace_de), "sin_recuperar": len(sin_recuperar),
        "marcas_recuperables": sum(len(por_puntero[p]) for p in enlace_de),
        "bytes": bytes_total, "notas_cambiadas": 0, "copia": None,
        "biblioteca": None, "sin_recuperar_punteros": sin_recuperar,
    }

    # ---- las notas
    cambios: Dict[Path, bytes] = {}
    for puntero, rutas in por_puntero.items():
        if puntero not in enlace_de:
            continue
        for ruta in rutas:
            cambios.setdefault(ruta, b"")
    notas_a_tocar = sorted(cambios)
    resultado["notas_a_cambiar"] = len(notas_a_tocar)

    def sustituir_avisos(ruta, datos):
        def sustituir(m):
            p = m.group(1).decode("utf-8", errors="replace")
            if p in enlace_de:
                return b"![](" + enlace_de[p].encode("utf-8") + b")"
            return m.group(0)
        return MARCA_RE.sub(sustituir, datos)

    resultado["notas_cambiadas"], resultado["copia"] = _cambiar_notas(
        base, notas_a_tocar, sustituir_avisos, export, aplicar, carpeta_logs, "", log)
    if aplicar:
        for e in escritores.values():
            e.cerrar()
        log(f"  {resultado['notas_cambiadas']} notas cambiadas.")

    # ---- la biblioteca: generadas que ninguna conversacion enlaza
    if biblioteca:
        resultado["biblioteca"] = _colgar_biblioteca(zf, indice, image_meta, base, aplicar, escritores,
                                                     export, carpeta_logs, log)
    zf.close()
    return resultado


def _colgar_biblioteca(zf, indice, image_meta, base: Path, aplicar: bool, escritores, export: Path,
                       carpeta_logs: Optional[Path], log) -> dict:
    """Imagenes generadas de library_files.json que ninguna conversacion enlaza: las copia a GENERADAS
    y las cuelga de su conversacion (mensaje `tool` al final de cada nota del hilo)."""
    cero = {"generadas": 0, "sin_fichero": 0, "ya_enlazadas": 0, "copiadas": 0, "con_hilo": 0,
            "sin_nota": 0, "bloques": 0, "notas_a_cambiar": 0, "notas_cambiadas": 0, "copia": None}
    entradas = sce.entradas_biblioteca_generadas(zf)
    if not entradas:
        log("  El export no trae imagenes generadas en library_files.json: nada que colgar.")
        return cero
    referenciadas = {sce.AssetIndex.resolve_pointer_id(p) for p in image_meta}
    r = dict(cero, generadas=len(entradas))
    escritor = escritores["generada"]
    enlace_de: Dict[str, str] = {}
    candidatas: List[dict] = []
    for x in entradas:
        if x["file_id"] in referenciadas:
            r["ya_enlazadas"] += 1
        elif x["file_id"] not in indice.by_id:
            r["sin_fichero"] += 1
        else:
            candidatas.append(x)
    for x in candidatas:
        data, ext = indice.get_bytes(x["file_id"])
        meta = {"origen": "generada", "generador": "chatgpt-biblioteca", "titulo_biblioteca": sce.titulo_biblioteca(x),
                "creada": (x.get("created_at") or "")[:19]}
        enlace_de[x["file_id"]] = f"{BANCOS['generada']}/{escritor.write(data, ext, meta=meta)}"
    r["copiadas"] = len(candidatas)

    # Cada imagen en las notas de su hilo.
    por_nota = notas_por_conv_id(base)
    por_hilo: Dict[str, List[dict]] = {}
    for x in candidatas:
        if x.get("origination_thread_id"):
            por_hilo.setdefault(x["origination_thread_id"], []).append(x)
    cambios: Dict[Path, List[dict]] = {}
    for hilo, imagenes in por_hilo.items():
        rutas = por_nota.get(hilo)
        if not rutas:
            r["sin_nota"] += len(imagenes)
            continue
        r["con_hilo"] += len(imagenes)
        for ruta in rutas:
            cambios[ruta] = imagenes

    def anadir(ruta, datos):
        for x in cambios[ruta]:
            enlace = f"![]({enlace_de[x['file_id']]})"
            if enlace.encode("utf-8") in datos:
                continue                                   # ya esta: repetir no duplica
            bloque = sce.texto_biblioteca(x, enlace)
            datos = datos.rstrip(b"\n") + b"\n\n### Tool\n\n" + bloque.encode("utf-8") + b"\n"
        return datos

    pendientes = [ruta for ruta in sorted(cambios) if anadir(ruta, ruta.read_bytes()) != ruta.read_bytes()]
    r["notas_a_cambiar"] = len(pendientes)
    r["bloques"] = sum(1 for ruta in pendientes for x in cambios[ruta]
                       if f"![]({enlace_de[x['file_id']]})".encode("utf-8") not in ruta.read_bytes())
    r["notas_cambiadas"], r["copia"] = _cambiar_notas(base, pendientes, anadir, export, aplicar, carpeta_logs,
                                                       "_biblioteca", log)
    if aplicar:
        escritor.cerrar()
    log(f"  Biblioteca: {r['generadas']} imagenes generadas; {r['ya_enlazadas']} ya enlazadas a una conversacion; "
        f"{r['sin_fichero']} sin fichero en el zip; {r['copiadas']} {'copiadas' if aplicar else 'por copiar'} a "
        f"GENERADAS; {r['con_hilo']} con conversacion en el vault ({r['bloques']} bloques "
        f"{'anadidos' if aplicar else 'por anadir'} en {r['notas_a_cambiar']} notas); {r['sin_nota']} sin nota.")
    return r


CAMPOS_GENERADOR = ("generador", "modelo", "edicion")


def completar_metadatos(export: Path, base: Path, aplicar: bool = False, carpeta_logs: Optional[Path] = None,
                        log=print) -> dict:
    """Las generadas importadas antes de que el importador guardara con que se genero: saca del
    export, exacto, la herramienta, el modelo del chat y si es una edicion, y lo anade a su entrada
    del manifiesto de GENERADAS. Casa cada imagen por su huella (el nombre del fichero), asi que
    no depende de en que nota este. No toca entradas que ya lo tienen ni nada mas del manifiesto."""
    export, base = Path(export), Path(base)
    if not export.is_file() or export.suffix.lower() != ".zip":
        raise ErrorRecuperar(f"--export tiene que ser el .zip del export de ChatGPT: {export}")
    ruta_man = base / BANCOS["generada"] / "_image_manifest.json"
    if not ruta_man.is_file():
        raise ErrorRecuperar(f"no encuentro el manifiesto de las generadas: {ruta_man}")
    manifiesto = json.loads(ruta_man.read_text(encoding="utf-8-sig"))
    faltan = {k for k, v in manifiesto.items() if isinstance(v, dict) and "generador" not in v}
    r = {"aplicado": aplicar, "en_manifiesto": len(manifiesto), "sin_generador": len(faltan),
         "completables": 0, "copia": None}
    if not faltan:
        log("Todas las generadas del manifiesto tienen ya su generador.")
        return r

    log(f"Leyendo el export {export.name} ...")
    image_meta: Dict[str, dict] = {}
    _, zf = sce.load_conversations(str(export), image_meta_out=image_meta)
    if zf is None:
        raise ErrorRecuperar("el export no es un .zip con imagenes dentro")
    indice = sce.AssetIndex(zf)
    for x in sce.entradas_biblioteca_generadas(zf):
        image_meta.setdefault(sce.puntero_de_biblioteca(x), {"origen": "generada", "generador": "chatgpt-biblioteca"})
    nuevos: Dict[str, dict] = {}
    for puntero, meta in image_meta.items():
        if meta.get("origen") != "generada" or "generador" not in meta:
            continue
        hallado = indice.get_bytes(puntero)
        if not hallado:
            continue
        data, ext = hallado
        fname = f"{hashlib.sha1(data).hexdigest()[:16]}{ext}"
        if fname in faltan and fname not in nuevos:
            nuevos[fname] = {k: meta[k] for k in CAMPOS_GENERADOR if k in meta}
    zf.close()
    r["completables"] = len(nuevos)
    log(f"  {len(faltan)} generadas sin generador en el manifiesto; {len(nuevos)} se completan con este export.")
    if not aplicar or not nuevos:
        return r

    marca_tiempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    copia = (Path(carpeta_logs) if carpeta_logs else HERE / "logs") / f"recuperar_imagenes_{marca_tiempo}_metadatos"
    copia.mkdir(parents=True, exist_ok=True)
    _hacer_copia(ruta_man, base, copia)
    (copia / "diario.json").write_text(json.dumps({
        "export": str(export), "base": str(base), "fecha": marca_tiempo,
        "notas": [str(ruta_man.relative_to(base))],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    actual = json.loads(ruta_man.read_text(encoding="utf-8-sig"))     # releido: por si cambio mientras tanto
    for fname, campos in nuevos.items():
        if fname in actual and "generador" not in actual[fname]:
            actual[fname].update(campos)
    tmp = ruta_man.with_name(ruta_man.name + ".recuperar.part")
    tmp.write_text(json.dumps(actual, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta_man)
    r["copia"] = str(copia)
    return r


def deshacer(copia: Path, log=print) -> int:
    """Restaura las notas desde la copia hecha antes de --aplicar. Devuelve cuantas."""
    copia = Path(copia)
    diario = copia / "diario.json"
    if not diario.is_file():
        raise ErrorRecuperar(f"no es una copia de recuperar_imagenes (falta diario.json): {copia}")
    d = json.loads(diario.read_text(encoding="utf-8"))
    base = Path(d["base"])
    n = 0
    for rel in d["notas"]:
        origen, destino = copia / rel, base / rel
        if not origen.is_file():
            log(f"  [aviso] falta en la copia: {rel}")
            continue
        shutil.copy2(origen, destino)
        n += 1
    log(f"{n} notas restauradas desde {copia}. Las imagenes copiadas a los bancos se quedan.")
    return n


def _config_base() -> Optional[str]:
    try:
        from config_loader import load_config, get_path
        base = get_path(load_config(str(HERE / "memoria_config.yaml")), "base_vault")
        return str(base) if base else None
    except Exception:
        return None


def main(argv=None) -> int:
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Devuelve a las notas las imagenes de ChatGPT que quedaron como "
                                              "'imagen no disponible en el export'.")
    ap.add_argument("--export", help="El .zip del export de ChatGPT que trae las imagenes")
    ap.add_argument("--base-vault", help="Carpeta base del vault (por defecto, la de memoria_config.yaml)")
    ap.add_argument("--aplicar", action="store_true", help="Hacer los cambios de verdad (sin esto solo cuenta)")
    ap.add_argument("--biblioteca", action="store_true",
                    help="Copiar tambien a GENERADAS las imagenes generadas que el export trae y ninguna "
                         "conversacion enlaza")
    ap.add_argument("--metadatos", action="store_true",
                    help="En vez de reparar notas: completar en el manifiesto de GENERADAS con que se genero cada "
                         "imagen (herramienta, modelo del chat, si es una edicion), sacado exacto del export")
    ap.add_argument("--deshacer", metavar="CARPETA", help="Restaurar las notas desde la copia de un --aplicar")
    ap.add_argument("--logs", metavar="CARPETA",
                    help="Donde guardar las copias de seguridad (por defecto, logs/ junto al programa)")
    args = ap.parse_args(argv)
    logs = Path(args.logs) if args.logs else None

    try:
        if args.deshacer:
            deshacer(Path(args.deshacer))
            return 0
        if not args.export:
            ap.error("hace falta --export (o --deshacer)")
        base = args.base_vault or _config_base()
        if not base:
            ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
        if args.metadatos:
            m = completar_metadatos(Path(args.export), Path(base), aplicar=args.aplicar, carpeta_logs=logs)
            print()
            print("SIMULACION (no se ha escrito nada)" if not m["aplicado"] else "HECHO")
            print(f"  generadas en el manifiesto: {m['en_manifiesto']} | sin generador: {m['sin_generador']} | "
                  f"{'completadas' if m['aplicado'] else 'se completan'} con este export: {m['completables']}")
            if m["copia"]:
                print(f"  para deshacer:              python recuperar_imagenes.py --deshacer \"{m['copia']}\"")
            return 0
        r = recuperar(Path(args.export), Path(base), aplicar=args.aplicar, biblioteca=args.biblioteca,
                      carpeta_logs=logs)
    except ErrorRecuperar as e:
        print(f"[error] {e}")
        return 2

    print()
    print("SIMULACION (no se ha escrito nada)" if not r["aplicado"] else "HECHO")
    print(f"  avisos en las notas:        {r['marcas']} ({r['imagenes_con_aviso']} imagenes distintas)")
    print(f"  recuperables con este export: {r['marcas_recuperables']} avisos ({r['recuperables']} imagenes, "
          f"{r['bytes'] // (1024 * 1024)} MB)")
    print(f"  que el export no trae:      {r['sin_recuperar']} imagenes (se quedan como aviso)")
    print(f"  notas {'cambiadas' if r['aplicado'] else 'que se cambiarian'}: "
          f"{r['notas_cambiadas'] if r['aplicado'] else r['notas_a_cambiar']}")
    if r["biblioteca"] and r["biblioteca"]["generadas"]:
        b = r["biblioteca"]
        print(f"  biblioteca: {b['generadas']} generadas; {b['copiadas']} {'copiadas' if r['aplicado'] else 'por copiar'} "
              f"a GENERADAS; {b['bloques']} {'anadidas' if r['aplicado'] else 'por anadir'} a sus conversaciones "
              f"({b['notas_a_cambiar']} notas); {b['sin_nota']} sin nota en el vault; "
              f"{b['sin_fichero']} sin fichero en el zip; {b['ya_enlazadas']} ya enlazadas")
    if r["biblioteca"] and r["biblioteca"]["copia"]:
        print(f"  copia (biblioteca):         {r['biblioteca']['copia']}")
        print(f"  para deshacer:              python recuperar_imagenes.py --deshacer \"{r['biblioteca']['copia']}\""
              + (" y despues la de abajo" if r["copia"] else ""))
    if r["copia"]:
        print(f"  copia de seguridad:         {r['copia']}")
        print(f"  para deshacer:              python recuperar_imagenes.py --deshacer \"{r['copia']}\"")
    if not r["aplicado"]:
        print("  Para hacerlo de verdad, repite con --aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
