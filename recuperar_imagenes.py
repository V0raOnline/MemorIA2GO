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
  4. Con --biblioteca, ademas, copia a GENERADAS las imagenes generadas que el export
     trae en `library_files.json` y ninguna conversacion enlaza (el export nuevo no
     lleva imagenes en los mensajes del asistente). No las puede devolver a su
     conversacion: el mensaje de origen no viene en el export.

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

    if aplicar and notas_a_tocar:
        marca_tiempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        logs = Path(carpeta_logs) if carpeta_logs else HERE / "logs"
        copia = logs / f"recuperar_imagenes_{marca_tiempo}"
        copia.mkdir(parents=True, exist_ok=True)
        resultado["copia"] = str(copia)
        log(f"Copia de seguridad de las {len(notas_a_tocar)} notas en {copia}")
        for ruta in notas_a_tocar:
            _hacer_copia(ruta, base, copia)
        (copia / "diario.json").write_text(json.dumps({
            "export": str(export), "base": str(base), "fecha": marca_tiempo,
            "notas": [str(r.relative_to(base)) for r in notas_a_tocar],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        def sustituir(m):
            p = m.group(1).decode("utf-8", errors="replace")
            if p in enlace_de:
                return b"![](" + enlace_de[p].encode("utf-8") + b")"
            return m.group(0)

        for ruta in notas_a_tocar:
            datos = ruta.read_bytes()
            nuevo = MARCA_RE.sub(sustituir, datos)
            if nuevo != datos:
                _escribir_conservando_fecha(ruta, nuevo)
                resultado["notas_cambiadas"] += 1
        for e in escritores.values():
            e.cerrar()
        log(f"  {resultado['notas_cambiadas']} notas cambiadas.")

    # ---- la biblioteca: generadas que ninguna conversacion enlaza
    if biblioteca:
        resultado["biblioteca"] = _recuperar_biblioteca(zf, indice, image_meta, base, aplicar, escritores, log)
    zf.close()
    return resultado


def _recuperar_biblioteca(zf, indice, image_meta, base: Path, aplicar: bool, escritores, log) -> dict:
    """Imagenes generadas del export que ninguna conversacion enlaza (library_files.json)."""
    biblioteca = list(_leer_biblioteca(zf).values())
    if not biblioteca:
        log("  El export no trae library_files.json: nada que recuperar de la biblioteca.")
        return {"generadas": 0, "sin_fichero": 0, "ya_enlazadas": 0, "copiadas": 0}
    referenciadas = {sce.AssetIndex.resolve_pointer_id(p) for p in image_meta}
    generadas = [x for x in biblioteca
                 if (x.get("mime_type") or "").startswith("image/") and x.get("image_gen_generation_id")]
    ya = sin_fichero = 0
    nuevas = 0
    escritor = escritores["generada"]
    for x in generadas:
        fid = x.get("file_id") or ""
        if fid in referenciadas:
            ya += 1
            continue
        hallado = indice.get_bytes(fid)
        if not hallado:
            sin_fichero += 1
            continue
        data, ext = hallado
        meta = {"origen": "generada", "titulo_biblioteca": x.get("file_name") or "",
                "creada": (x.get("created_at") or "")[:19], "sin_conversacion": True}
        escritor.write(data, ext, meta=meta)
        nuevas += 1
    if aplicar:
        escritor.cerrar()
    log(f"  Biblioteca: {len(generadas)} imagenes generadas; {ya} ya enlazadas a una conversacion; "
        f"{sin_fichero} sin fichero en el zip; {nuevas} {'copiadas' if aplicar else 'por copiar'} a GENERADAS.")
    return {"generadas": len(generadas), "sin_fichero": sin_fichero, "ya_enlazadas": ya, "copiadas": nuevas}


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
    ap.add_argument("--deshacer", metavar="CARPETA", help="Restaurar las notas desde la copia de un --aplicar")
    args = ap.parse_args(argv)

    try:
        if args.deshacer:
            deshacer(Path(args.deshacer))
            return 0
        if not args.export:
            ap.error("hace falta --export (o --deshacer)")
        base = args.base_vault or _config_base()
        if not base:
            ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
        r = recuperar(Path(args.export), Path(base), aplicar=args.aplicar, biblioteca=args.biblioteca)
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
    if r["copia"]:
        print(f"  copia de seguridad:         {r['copia']}")
        print(f"  para deshacer:              python recuperar_imagenes.py --deshacer \"{r['copia']}\"")
    if not r["aplicado"]:
        print("  Para hacerlo de verdad, repite con --aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
