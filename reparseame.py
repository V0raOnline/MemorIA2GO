#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reparseame.py -- REParsea·me: pone las notas de RAW como las escribiria el
parser de hoy, sin duplicar conversaciones. Diseno completo en REPARSEAME.md.

Pieza 1 (esta): el DIAGNOSTICO. Recorre las conversaciones de RAW y dice que
derivas tiene cada nota y si se arreglan con la nota sola o hace falta su
export. No escribe nada, nunca.

Uso:
  python reparseame.py                      (base del vault de memoria_config.yaml)
  python reparseame.py --base-vault RUTA
  python reparseame.py --csv informe.csv    (una fila por nota afectada)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import layout

HERE = Path(__file__).resolve().parent


class ErrorReparsea(Exception):
    pass


# Cada deriva: (que es, con que se arregla). «nota» = la propia nota lleva todo
# lo necesario (la linea de JSON crudo es el bloque completo); «export» = hace
# falta volver al export del que salio. Medidas en el vault real el 2026-11-16.
DERIVAS: Dict[str, tuple] = {
    "json_crudo": ("Bloques en JSON crudo", "nota"),
    # Estas dos parecian de nota, pero la importacion las resuelve con el export
    # (banco de imagenes, fuentes de cada cita): ver SOLO_CON_LA_NOTA.
    "bytes_nulos": ("Bytes nulos (marcadores de imagen sin resolver)", "export"),
    "citas_crudas": ("Citas internas en crudo", "export"),
    "imagen_no_disponible": ("Imagen no disponible", "export"),
    "sin_model": ("Sin modelo en el frontmatter", "export"),
    "sin_conv_id": ("Sin conv_id en el frontmatter", "export"),
}

def bloque_json(linea: str) -> Optional[dict]:
    """El bloque si la linea es un content dict volcado en crudo, o None.
    No basta con buscar '{"content_type": ' al principio: en los exports de
    2025 el orden de claves cambia ('{"content": ..., "content_type": ...}') y
    asi se escapaban 5.162 bloques en 1.266 notas del vault real."""
    if not (linea.startswith('{"') and linea.endswith("}")):
        return None
    try:
        d = json.loads(linea)
    except ValueError:
        return None
    return d if isinstance(d, dict) and "content_type" in d else None


def _tiene_json_crudo(texto: str) -> bool:
    return any(bloque_json(ln) for ln in texto.split("\n") if ln.startswith('{"'))
_IMAGEN_NO_DISPONIBLE = re.compile(rb"\*\[imagen no disponible en el export: ")
# Los marcadores internos de ChatGPT viven en el area de uso privado U+E200-U+E2FF
# (ver chatgpt_markers.py). Cadena normal, no raw: los caracteres van literales.
_CITA_CRUDA = re.compile("[-]")


def _frontmatter(texto: str) -> Dict[str, str]:
    if not texto.startswith("---\n"):
        return {}
    fin = texto.find("\n---", 4)
    if fin == -1:
        return {}
    campos = {}
    for linea in texto[4:fin].split("\n"):
        if ":" in linea and not linea.startswith((" ", "\t", "-")):
            k, v = linea.split(":", 1)
            campos[k.strip()] = v.strip().strip('"')
    return campos


def proveedor_de(front: Dict[str, str]) -> str:
    """Las notas antiguas no traen 'provider': su 'source' lo dice."""
    p = (front.get("provider") or "").lower()
    if p:
        return p
    src = (front.get("source") or "").lower()
    return "chatgpt" if src.startswith("chatgpt") else (src.split("_")[0] or "desconocido")


def derivas_de(datos: bytes) -> List[str]:
    """Las derivas de una nota, a partir de sus bytes tal cual estan en disco."""
    texto = datos.decode("utf-8", errors="replace")
    front = _frontmatter(texto)
    if proveedor_de(front) != "chatgpt":
        return []  # de momento todas las derivas conocidas son del parser de ChatGPT
    d = []
    if _tiene_json_crudo(texto):
        d.append("json_crudo")
    if b"\x00" in datos:
        d.append("bytes_nulos")
    # Las citas dentro de una linea de JSON crudo ya se arreglan con ella: solo
    # cuentan las que estan en el texto normal (8 notas en el vault real).
    if _CITA_CRUDA.search("\n".join(ln for ln in texto.split("\n") if not bloque_json(ln))):
        d.append("citas_crudas")
    if _IMAGEN_NO_DISPONIBLE.search(datos):
        d.append("imagen_no_disponible")
    if not front.get("model"):
        d.append("sin_model")
    if not front.get("conv_id"):
        d.append("sin_conv_id")
    return d


# ---------- pieza 2: reescribir una nota ----------
#
# Solo el JSON crudo se arregla de verdad con la nota sola: la linea es el
# bloque entero (json.dumps sin sangria, una linea). Citas y bytes nulos los
# resolvia la importacion con datos del export (las fuentes de cada cita, el
# banco de imagenes): sin el, el resultado no seria el de una importacion de
# hoy y la siguiente importacion duplicaria. Esas esperan a la pieza 3.

SOLO_CON_LA_NOTA = {"json_crudo"}

# Solo los roles que escribe el parser, y como los escribe: con una linea en
# blanco antes y otra despues. Un «### Pasos» dentro de una respuesta es
# contenido (vault_merge.read_note si los confunde), y un «### User» citado
# dentro de un bloque de codigo suele ir pegado a sus lineas.
_CABECERA = re.compile(r"\n\n### (User|Assistant|Tool|System|Unknown|Contexto)\n\n")


def partir(texto: str):
    """(cabeza, mensajes) de una nota escrita por write_md, o None si no lo es.
    La cabeza es el frontmatter sin la raya de cierre."""
    if not texto.startswith("---\n"):
        return None
    fin = texto.find("\n---\n", 4)
    if fin == -1:
        return None
    # El cuerpo de write_md es "\n### R\n\nC\n\n### R2\n\nC2\n": con un salto
    # delante, cada cabecera queda entre "\n\n" y "\n\n".
    if not texto[fin + 5:]:
        return texto[:fin], []  # nota sin mensajes
    trozos = _CABECERA.split("\n" + texto[fin + 5:])
    if trozos[0]:
        return None  # texto antes del primer rol: no la escribio el parser
    # Sin perder un byte. Una respuesta que CITA una nota con sus cabeceras y
    # sus lineas en blanco se partiria donde no debe, y desde el texto no hay
    # forma de saberlo; pero si partir+componer es exacto, un corte falso
    # vuelve a unirse igual.
    mensajes = []
    for i in range(1, len(trozos), 2):
        seg = trozos[i + 1]
        if i + 2 >= len(trozos) and seg.endswith("\n"):
            seg = seg[:-1]
        mensajes.append({"role": trozos[i].lower(), "content": seg})
    return texto[:fin], mensajes


def componer(cabeza: str, mensajes: List[dict]) -> str:
    """Lo mismo que hace write_md con los mismos datos, byte a byte. No recorta
    el contenido: lo que viene de la nota ya salio recortado de write_md, y lo
    nuevo lo recorta reparar_texto."""
    lineas = ["---\n"]
    for m in mensajes:
        lineas.append(f"### {(m.get('role') or 'unknown').capitalize()}\n")
        lineas.append((m.get("content") or "") + "\n")
    texto = cabeza + "\n" + "\n".join(lineas)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", texto)


def reparar_texto(texto: str) -> Optional[str]:
    """La nota como la escribiria hoy la importacion, si lo unico que le pasa
    se arregla con la nota sola. None si no hay nada que hacer aqui."""
    import split_chatgpt_export as S
    p = partir(texto)
    if p is None:
        return None
    cabeza, mensajes = p
    if re.search(r'^title: "\{', cabeza, re.M):
        return None  # titulo sacado del JSON: el titulo bueno solo lo sabe el export
    estado, salida, cambio = S.EstadoHilo(), [], False
    for m in mensajes:
        lineas = m["content"].split("\n")
        bloque = bloque_json(lineas[-1])
        if bloque is None:
            salida.append(m)
            continue
        cambio = True
        # Mismos pasos y mismo orden que parse_json_conversations.
        if S.incorporar_especial(salida, bloque, estado):
            continue
        contenido = S._resolver_marcadores(S.render_bloque_sin_parts(bloque), None, None)
        adjuntos = "\n".join(lineas[:-1]).rstrip()
        if adjuntos:
            contenido = f"{adjuntos}\n\n{contenido}".strip() if contenido.strip() else adjuntos
        if contenido.strip():
            salida.append({"role": m["role"], "content": contenido.rstrip()})
    # incorporar_especial escribe sus bloques sin recortar; write_md los recorta.
    for m in salida:
        if m["role"] == "contexto":
            m["content"] = m["content"].rstrip()
    return componer(cabeza, salida) if cambio else None


# ---------- fase 4a: imagenes, desde los exports ----------
#
# RAW es el archivo de cada export (decision de V0ra, 2026-11-16): si un export
# no traia una imagen, su nota dice «imagen no disponible» y asi se queda. Lo
# que si se hace: buscar cada imagen avisada en CUALQUIER export, copiarla a
# su banco (mismo nombre que le daria la importacion) y apuntar puntero ->
# enlace en <CHATGPT>/_punteros_imagenes.json. La fusion (vault_merge.py) usa
# esa correspondencia para que en MERGED se vea la imagen si algun export la
# tuvo. Las imagenes copiadas a los bancos se quedan aunque se deshaga: nombre
# por huella, no duplican nada.

_AVISO_IMAGEN = re.compile(r"\*\[imagen no disponible en el export: ([^\]\r\n]+)\]\*")


def punteros_de(texto: str) -> set:
    return {m.group(1) for m in _AVISO_IMAGEN.finditer(texto)}


def exports_chatgpt(carpeta: Optional[Path]) -> List[Path]:
    """Los .zip de ChatGPT de la carpeta de exports, del mas reciente al mas antiguo."""
    if not carpeta or not Path(carpeta).is_dir():
        return []
    return sorted((p for p in Path(carpeta).glob("chatgpt_*.zip") if p.is_file()), reverse=True)


def resolver_imagenes(base: Path, punteros: set, exports: List[Path], aplicar: bool,
                      log: Callable[[str], None] = print) -> Dict[str, str]:
    """{puntero: enlace} de las imagenes que trae algun export. Con aplicar,
    las copia a su banco (mismo nombre que les daria la importacion)."""
    import split_chatgpt_export as S
    import recuperar_imagenes as RI
    lay = layout.cargar(base)
    escritores = {origen: RI._Escritor(lay.ruta(base, clave), aplicar) for origen, clave in RI.BANCOS.items()}
    pendientes, enlaces = set(punteros), {}
    for exp in exports:
        if not pendientes:
            break
        try:
            with zipfile.ZipFile(exp) as zf:
                ids = set(S.AssetIndex(zf).by_id)
            aqui = {p for p in pendientes if S.AssetIndex.resolve_pointer_id(p) in ids}
            if not aqui:
                continue
            meta_de: Dict[str, dict] = {}
            _, zf = S.load_conversations(str(exp), image_meta_out=meta_de)
            indice, biblio = S.AssetIndex(zf), RI._leer_biblioteca(zf)
            for p in sorted(aqui):
                hallado = indice.get_bytes(p)
                if not hallado:
                    continue
                data, ext = hallado
                meta = dict(meta_de.get(p) or {})
                if not meta:
                    entrada = biblio.get(S.AssetIndex.resolve_pointer_id(p)) or {}
                    meta["origen"] = "generada" if entrada.get("image_gen_generation_id") else "subida"
                origen = meta.get("origen") if meta.get("origen") in escritores else "subida"
                enlaces[p] = lay.enlace(RI.BANCOS[origen], escritores[origen].write(data, ext, meta=meta or None))
                pendientes.discard(p)
            zf.close()
            log(f"  {exp.name}: {len(aqui)} imagenes")
        except (zipfile.BadZipFile, OSError, ValueError) as e:
            log(f"  {exp.name}: no lo puedo leer ({e}); sigo con los demas")
    for e in escritores.values():
        e.cerrar()
    log(f"Imagenes encontradas: {len(enlaces)} de {len(punteros)}; sin export que las traiga: {len(pendientes)}")
    return enlaces


def carpeta_raw(base: Path, lay=None) -> Path:
    lay = lay or layout.cargar(base)
    return lay.ruta(base, "raw").joinpath(*lay.rel("conversaciones").split("/"))


def diagnosticar(base: Path, log: Callable[[str], None] = print) -> dict:
    """Recorre RAW y cuenta. No escribe nada."""
    base = Path(base)
    raw = carpeta_raw(base)
    if not raw.is_dir():
        raise ErrorReparsea(f"no encuentro las conversaciones de RAW en {raw}")
    log(f"Revisando las notas de {raw} ...")
    por_deriva: Dict[str, int] = {k: 0 for k in DERIVAS}
    por_proveedor: Dict[str, int] = {}
    afectadas: List[dict] = []
    total = 0
    for nota in sorted(raw.rglob("*.md")):
        datos = nota.read_bytes()
        total += 1
        prov = proveedor_de(_frontmatter(datos.decode("utf-8", errors="replace")))
        por_proveedor[prov] = por_proveedor.get(prov, 0) + 1
        d = derivas_de(datos)
        if not d:
            continue
        for k in d:
            por_deriva[k] += 1
        afectadas.append({"nota": nota.relative_to(raw).as_posix(), "derivas": d,
                          "necesita_export": any(DERIVAS[k][1] == "export" for k in d)})
    return {
        "raw": str(raw), "notas": total, "por_proveedor": por_proveedor,
        "por_deriva": por_deriva, "afectadas": afectadas,
        "con_la_nota": sum(1 for a in afectadas if not a["necesita_export"]),
        "con_el_export": sum(1 for a in afectadas if a["necesita_export"]),
    }


# ---------- pieza 2: aplicar sobre RAW ----------
#
# Tres operaciones, por conversacion (misma carpeta y mismo nombre base):
#   - reescribir: la nota con JSON crudo, como la escribiria hoy la importacion;
#   - renombrar: las notas con huella pasan a llamarse por la huella de lo que
#     dicen (si no, la proxima importacion no las reconoce y escribe otra al lado);
#   - papelera: versiones identicas de la misma conversacion, se queda una.
# Antes de tocar nada, copia exacta de cada nota afectada en logs/, con un
# manifiesto para --deshacer. Las fechas de modificacion se conservan.

_SUFIJO = re.compile(r"-(h[0-9a-f]{7,8}|v\d+|t\d{12})(?:-\d+)?$", re.IGNORECASE)  # el de vault_merge.py


def planificar(base: Path, log: Callable[[str], None] = print) -> dict:
    """Que haria --aplicar. No escribe nada."""
    raw = carpeta_raw(Path(base))
    if not raw.is_dir():
        raise ErrorReparsea(f"no encuentro las conversaciones de RAW en {raw}")
    log(f"Preparando el plan sobre {raw} ...")
    grupos: Dict[tuple, List[dict]] = defaultdict(list)
    for nota in sorted(raw.rglob("*.md")):
        datos = nota.read_bytes()
        texto = datos.decode("utf-8", errors="replace")
        nuevo = reparar_texto(texto) if proveedor_de(_frontmatter(texto)) == "chatgpt" else None
        m = _SUFIJO.search(nota.stem)
        grupos[(nota.parent, nota.stem[:m.start()] if m else nota.stem)].append({
            "ruta": nota, "final": nuevo.encode("utf-8") if nuevo is not None else datos,
            "reescrita": nuevo is not None, "mtime": nota.stat().st_mtime_ns,
            "esquema": "base" if not m else ("hash" if m.group(1).lower().startswith("h") else "otro"),
        })
    ops: List[dict] = []
    for (carpeta, nombre_base), notas in grupos.items():
        # La del nombre sin sufijo primero: es el hueco que la importacion
        # compara antes que ninguno, y si hay identicas se queda ella.
        notas.sort(key=lambda n: (n["esquema"] != "base", n["ruta"].name))
        for n in notas:
            n["sha"] = hashlib.sha1(n["final"]).hexdigest()
        # La que se queda hereda la fecha MAS RECIENTE de sus identicas: la
        # fusion elige el titulo de una conversacion renombrada por la version
        # mas reciente en disco, y sin esto 5 conversaciones cambiaban de nombre
        # en MERGED (medido en la copia del vault real).
        mas_reciente: Dict[str, int] = {}
        for n in notas:
            mas_reciente[n["sha"]] = max(mas_reciente.get(n["sha"], 0), n["mtime"])
        destino_de: Dict[str, Path] = {}
        ocupados = set()
        for n in notas:
            sha = n["sha"]
            if sha in destino_de:
                ops.append({"tipo": "papelera", "origen": n["ruta"], "igual_a": destino_de[sha]})
                continue
            destino = n["ruta"]
            if n["esquema"] == "hash":
                destino = carpeta / f"{nombre_base}-h{sha[:8]}.md"
                i = 2
                while destino in ocupados:  # colision real de 32 bits: el contador de write_md
                    destino = carpeta / f"{nombre_base}-h{sha[:8]}-{i}.md"
                    i += 1
            ocupados.add(destino)
            destino_de[sha] = destino
            if destino != n["ruta"] or n["reescrita"] or mas_reciente[sha] != n["mtime"]:
                tipo = "reescribir" if n["reescrita"] else ("renombrar" if destino != n["ruta"] else "fecha")
                ops.append({"tipo": tipo, "origen": n["ruta"], "destino": destino, "final": n["final"],
                            "mtime_final": mas_reciente[sha]})
    return {"raw": raw, "ops": ops,
            "reescribir": sum(o["tipo"] == "reescribir" for o in ops),
            "renombrar": sum(o["tipo"] == "renombrar" for o in ops),
            "fecha": sum(o["tipo"] == "fecha" for o in ops),
            "papelera": sum(o["tipo"] == "papelera" for o in ops),
            "renombradas_al_reescribir": sum(o["tipo"] == "reescribir" and o["destino"] != o["origen"] for o in ops)}


def aplicar(plan: dict, carpeta_logs: Optional[Path] = None, log: Callable[[str], None] = print) -> Path:
    """Ejecuta el plan. Devuelve la carpeta de la copia (para --deshacer)."""
    raw: Path = plan["raw"]
    copia = Path(carpeta_logs or HERE / "logs") / f"reparseame_{datetime.now():%Y%m%d-%H%M%S}"
    (copia / "notas").mkdir(parents=True)
    manifiesto = {"raw": str(raw), "ops": []}
    # 1. Copia exacta de todo lo que se va a tocar, antes de tocar nada.
    for o in plan["ops"]:
        rel = o["origen"].relative_to(raw)
        dst = copia / "notas" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(o["origen"], dst)
        manifiesto["ops"].append({"tipo": o["tipo"], "origen": rel.as_posix(),
                                  "destino": o["destino"].relative_to(raw).as_posix() if "destino" in o else None,
                                  "mtime_ns": o["origen"].stat().st_mtime_ns,
                                  "sha1_final": hashlib.sha1(o["final"]).hexdigest() if "final" in o else None})
    (copia / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=1), encoding="utf-8")
    # 2. Fuera los originales que cambian de nombre o sobran; 3. escribir los destinos.
    for o in plan["ops"]:
        if o["tipo"] == "papelera" or o["destino"] != o["origen"]:
            o["origen"].unlink()
    for o, reg in zip(plan["ops"], manifiesto["ops"]):
        if o["tipo"] == "papelera":
            continue
        o["destino"].write_bytes(o["final"])
        os.utime(o["destino"], ns=(o["mtime_final"], o["mtime_final"]))
    log(f"Hecho. Copia para deshacer: {copia}")
    return copia


def deshacer(copia: Path, log: Callable[[str], None] = print) -> int:
    """Deja RAW como estaba antes de un --aplicar. Se niega si alguna nota
    escrita ha cambiado desde entonces: no pisa trabajo posterior."""
    copia = Path(copia)
    if (copia / "deshecho.json").exists():
        raise ErrorReparsea(f"esta copia ya se deshizo: {copia}")
    _deshacer_derivados(copia, log)  # primero los derivados: se rehicieron a partir del RAW reparado
    man = json.loads((copia / "manifiesto.json").read_text(encoding="utf-8"))
    raw = Path(man["raw"])
    for reg in man["ops"]:
        if reg["destino"]:
            d = raw / reg["destino"]
            if d.exists() and hashlib.sha1(d.read_bytes()).hexdigest() != reg["sha1_final"]:
                raise ErrorReparsea(f"{reg['destino']} ha cambiado desde que se aplico: no deshago nada")
    for reg in man["ops"]:
        if reg["destino"]:
            d = raw / reg["destino"]
            if d.exists():
                d.unlink()
    for reg in man["ops"]:
        o = raw / reg["origen"]
        shutil.copy2(copia / "notas" / reg["origen"], o)
        os.utime(o, ns=(reg["mtime_ns"], reg["mtime_ns"]))
    (copia / "deshecho.json").write_text(json.dumps({"cuando": datetime.now().isoformat()}), encoding="utf-8")
    log(f"{len(man['ops'])} notas restauradas desde {copia}.")
    return len(man["ops"])


# ---------- fase 3: los derivados (MERGED y PRJ) ----------
#
# MERGED no es solo la fusion: en MERGED_VAULT/Conversaciones conviven las
# carpetas de año (las escribe vault_merge.py) con Sesiones-Code y
# Sesiones-Codex (las escribe session_ingest.py), y al lado estan CLAUDE_CODE,
# CODEX, _Temas y los indices. Por eso no se sustituye MERGED entero: se
# rehace la fusion aparte y se sincronizan SOLO las notas de las carpetas de año.
#
# - Una nota de MERGED con lineas que la fusion de RAW no produce se edito a
#   mano: se marca y no se toca (decision de V0ra). Medido el 2026-11-16:
#   exactamente una, una errata corregida en Obsidian.
# - Una nota de MERGED que la fusion ya no produce es huerfana (la fusion
#   nunca borra): a la copia, si su conversacion sigue existiendo con otro
#   nombre. Si no, se deja y se avisa.
# - PRJ es una vista de MERGED: se refresca con project_organizer.py, como en
#   el pipeline, y sus copias huerfanas van a la copia.

_ANIO = re.compile(r"^\d{4}/")


def _notas_fusion(carpeta: Path) -> Dict[str, Path]:
    """Las notas que escribe vault_merge.py: las de las carpetas de año."""
    if not carpeta.is_dir():
        return {}
    return {p.relative_to(carpeta).as_posix(): p for p in carpeta.rglob("*.md")
            if _ANIO.match(p.relative_to(carpeta).as_posix())}


def _lineas_de(datos: bytes) -> set:
    return set(datos.decode("utf-8", errors="replace").split("\n"))


def editada_a_mano(en_merged: bytes, de_la_fusion: bytes) -> bool:
    """MERGED dice algo que la fusion de RAW no dice. Si solo le FALTA algo
    (se quedo atras, p. ej. sin las imagenes de la biblioteca), no es una edicion."""
    return en_merged != de_la_fusion and bool(_lineas_de(en_merged) - _lineas_de(de_la_fusion))


def _params(base: Path) -> dict:
    import MemorIA2GO as M
    p = M.load_from_yaml(str(HERE / "memoria_config.yaml")) or {}
    p["vault_path"] = Path(base)
    return p


def fusionar(base: Path, destino: Path) -> Path:
    """vault_merge.py con los argumentos del pipeline (paso 2), pero hacia
    `destino`. Devuelve su carpeta de conversaciones."""
    lay = layout.cargar(base)
    if getattr(lay, "particion", "unico") == "proveedor":
        raise ErrorReparsea("MERGED partido por proveedor: REParsea·me todavia no lo sabe sincronizar")
    r = subprocess.run([sys.executable, str(HERE / "vault_merge.py"), str(lay.ruta(base, "raw")), str(destino),
                        "--merge", "--by-year", "--by-month", "--base-vault", str(base)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE),
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        raise ErrorReparsea("la fusion fallo: " + (r.stderr or r.stdout)[-600:])
    return Path(destino) / lay.conv_rel()


def _conv_id(p: Path) -> Optional[str]:
    return _frontmatter(p.read_text(encoding="utf-8", errors="replace")).get("conv_id") or None


def planificar_merged(base: Path, antes: Path, despues: Path) -> dict:
    """Que cambia en MERGED. `antes` y `despues` son fusiones de RAW sin
    reparar y reparado; con `antes` se distinguen las ediciones a mano."""
    lay = layout.cargar(base)
    conv = lay.ruta(base, "merged") / lay.conv_rel()
    actual, n_antes, n_desp = _notas_fusion(conv), _notas_fusion(antes), _notas_fusion(despues)
    protegidas = sorted(k for k in actual if k in n_antes
                        and editada_a_mano(actual[k].read_bytes(), n_antes[k].read_bytes()))
    escribir = sorted(k for k in n_desp if k not in protegidas
                      and (k not in actual or actual[k].read_bytes() != n_desp[k].read_bytes()))
    vivas = {_conv_id(p) for p in n_desp.values()} - {None}
    huerfanas, desconocidas = [], []
    for k in sorted(set(actual) - set(n_desp) - set(protegidas)):
        (huerfanas if _conv_id(actual[k]) in vivas else desconocidas).append(k)
    return {"conv": conv, "despues": despues, "protegidas": protegidas, "escribir": escribir,
            "nuevas": [k for k in escribir if k not in actual], "huerfanas": huerfanas,
            "desconocidas": desconocidas}


def aplicar_merged(pm: dict, copia: Path, log: Callable[[str], None] = print) -> dict:
    conv: Path = pm["conv"]
    registro = {"conv": str(conv), "sobrescritas": [], "nuevas": [], "huerfanas": []}
    for k in pm["escribir"] + pm["huerfanas"]:
        if (conv / k).exists():
            dst = copia / "merged" / k
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(conv / k, dst)
    for k in pm["escribir"]:
        datos = (pm["despues"] / k).read_bytes()
        (registro["nuevas"] if not (conv / k).exists() else registro["sobrescritas"]).append(
            {"rel": k, "sha1": hashlib.sha1(datos).hexdigest()})
        (conv / k).parent.mkdir(parents=True, exist_ok=True)
        (conv / k).write_bytes(datos)
    for k in pm["huerfanas"]:
        (conv / k).unlink()
        registro["huerfanas"].append({"rel": k})
    log(f"MERGED: {len(pm['escribir'])} notas al dia, {len(pm['huerfanas'])} huerfanas a la copia, "
        f"{len(pm['protegidas'])} editadas a mano sin tocar.")
    return registro


def _prj_esperadas(params: dict, conv: Path) -> Dict[str, Path]:
    """Lo que project_organizer.py deja en PRJ: proyecto[/año/mes]/nombre."""
    from project_organizer import extract_yaml_field
    lay = layout.cargar(params["vault_path"])
    merged = lay.ruta(params["vault_path"], "merged")
    esperadas = {}
    for d in lay.conv_dirs(merged):
        for md in (merged / d).rglob("*.md"):
            txt = md.read_text(encoding="utf-8", errors="ignore")
            proyecto = extract_yaml_field(txt, "Project_name") or "none"
            y, m, *_ = ((extract_yaml_field(txt, "date") or "0000-00-00").split("-") + ["00", "00"])[:2]
            rel = f"{proyecto}/{y}/{m}/{md.name}" if params.get("by_date") else f"{proyecto}/{md.name}"
            esperadas[rel] = md
    return esperadas


def actualizar_prj(params: dict, conv: Path, copia: Path, conocidas: set, log_path: Path,
                   log: Callable[[str], None] = print) -> dict:
    """Refresca PRJ como el paso 3 del pipeline y aparta sus copias huerfanas:
    las que no corresponden a ninguna nota de MERGED pero son copia exacta de
    algo que si estuvo (por su sha1), o la misma conversacion que ahora vive en
    otra carpeta. Lo que no se reconoce, se deja."""
    import MemorIA2GO as M
    lay = layout.cargar(params["vault_path"])
    if not lay.proyectos:
        return {"huerfanas": [], "desconocidas": []}
    prj = lay.ruta(params["vault_path"], "prj")
    M.paso3_organizar(params, lay.ruta(params["vault_path"], "merged"), log_path)
    esperadas = _prj_esperadas(params, conv)
    # La misma conversacion con el mismo nombre en otra carpeta: cambio de
    # proyecto (o de fecha) y aqui quedo su copia vieja. 16 en el vault real,
    # casi todas de `none/` a `Substack/`.
    vive_en_otro_sitio = defaultdict(set)
    for rel, md in esperadas.items():
        vive_en_otro_sitio[rel.rsplit("/", 1)[-1]].add(_conv_id(md))
    huerfanas, desconocidas = [], []
    for p in sorted(prj.rglob("*.md")):
        rel = p.relative_to(prj).as_posix()
        if "/" not in rel or rel in esperadas:
            continue  # los indices viven en la raiz de PRJ
        movida = (_conv_id(p) or None) in (vive_en_otro_sitio.get(p.name, set()) - {None})
        if movida or hashlib.sha1(p.read_bytes()).hexdigest() in conocidas:
            dst = copia / "prj" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dst))
            huerfanas.append(rel)
        else:
            desconocidas.append(rel)
    log(f"PRJ: refrescado; {len(huerfanas)} copias huerfanas a la copia, {len(desconocidas)} sin reconocer (se quedan).")
    return {"prj": str(prj), "huerfanas": huerfanas, "desconocidas": desconocidas}


def _fotografiar(raiz: Path, filtro: Callable[[str], bool], destino: Path) -> List[str]:
    """Copia exacta de las notas de `raiz` que pasan el filtro. Para que
    --deshacer deje PRJ y los indices de MERGED como estaban: el refresco y los
    indices tocan cientos de ficheros que no son conversaciones reparadas."""
    rels = []
    if raiz.is_dir():
        for p in raiz.rglob("*.md"):
            rel = p.relative_to(raiz).as_posix()
            if filtro(rel):
                (destino / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, destino / rel)
                rels.append(rel)
    return rels


def _restaurar_foto(raiz: Path, filtro: Callable[[str], bool], foto: Path, rels: List[str]) -> None:
    for p in list(raiz.rglob("*.md")) if raiz.is_dir() else []:
        rel = p.relative_to(raiz).as_posix()
        if filtro(rel) and rel not in set(rels):
            p.unlink()  # lo creo el refresco o los indices
    for rel in rels:
        (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(foto / rel, raiz / rel)


def _filtro_indices(base: Path) -> Callable[[str], bool]:
    """Lo de MERGED que no son notas de conversacion ni de sesiones: indices y
    _Temas. Las carpetas salen de layout.py, como en todo el programa."""
    lay = layout.cargar(base)
    merged = lay.ruta(base, "merged")
    fuera = [d.rstrip("/") + "/" for d in lay.conv_dirs(merged)]
    for clave in ("sesiones.claude_code", "sesiones.codex"):
        try:
            rel = lay.ruta(base, clave).relative_to(merged).as_posix()
            fuera.append(rel.split("/")[0] + "/")
        except (KeyError, ValueError):
            pass
    return lambda rel: not rel.startswith(tuple(fuera))


def _sha_de(carpetas) -> set:
    return {hashlib.sha1(p.read_bytes()).hexdigest() for c in carpetas if c.is_dir() for p in c.rglob("*.md")}


def _staging(carpeta_logs: Optional[Path]) -> Path:
    return Path(carpeta_logs or HERE / "logs") / f"_reparseame_staging_{datetime.now():%Y%m%d-%H%M%S}"


def simular_derivados(base: Path, carpeta_logs: Optional[Path] = None, log: Callable[[str], None] = print) -> dict:
    """Sin escribir en el vault: fusiona RAW tal cual aparte y lo compara con
    MERGED para contar ediciones a mano y huerfanas que ya hay."""
    tmp = _staging(carpeta_logs)
    try:
        log("Fusionando RAW aparte para compararlo con MERGED (menos de un minuto) ...")
        antes = fusionar(base, tmp / "antes")
        pm = planificar_merged(base, antes, antes)
        return {"protegidas": pm["protegidas"], "huerfanas": pm["huerfanas"],
                "desconocidas": pm["desconocidas"], "atrasadas": len(pm["escribir"])}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def punteros_en_raw(base: Path) -> set:
    """Las imagenes que las notas de RAW citan con un aviso."""
    punteros = set()
    for nota in carpeta_raw(Path(base)).rglob("*.md"):
        texto = nota.read_bytes().decode("utf-8", errors="replace")
        if "imagen no disponible" in texto:
            punteros |= punteros_de(texto)
    return punteros


def preparar_imagenes(base: Path, exports: List[Path], aplicar: bool, log: Callable[[str], None] = print) -> int:
    """Fase 4a: imagenes avisadas que trae algun export -> a su banco y a la
    correspondencia que lee la fusion. Devuelve cuantas se encontraron."""
    import split_chatgpt_export as S
    enlaces = resolver_imagenes(base, punteros_en_raw(base), exports, aplicar, log)
    if aplicar and enlaces:
        S.guardar_enlaces_imagen(str(layout.cargar(base).ruta(base, "chatgpt.raiz")), enlaces)
    return len(enlaces)


def ejecutar(base: Path, carpeta_logs: Optional[Path] = None, log: Callable[[str], None] = print,
             exports: Optional[List[Path]] = None) -> dict:
    """Todo REParsea·me: imagenes (fase 4a), RAW (fase 2), MERGED y PRJ (fase 3) e indices."""
    import MemorIA2GO as M
    base = Path(base)
    params = _params(base)
    lay = layout.cargar(base)
    merged = lay.ruta(base, "merged")
    tmp = _staging(carpeta_logs)
    try:
        # «antes» es la fusion tal como produjo el MERGED de hoy: ANTES de
        # anadir imagenes a la correspondencia. Si se hiciera despues, los
        # avisos que MERGED aun tiene parecerian lineas de mas y cientos de
        # notas pasarian por editadas a mano (453 en la copia del vault real).
        log("1/5 Fusionando RAW tal cual, para reconocer lo editado a mano en MERGED ...")
        antes = fusionar(base, tmp / "antes")
        conocidas = _sha_de([merged / d for d in lay.conv_dirs(merged)])
        log("2/5 Imagenes que faltan, desde los exports (a los bancos, no a RAW), y RAW ...")
        exports = exports if exports is not None else exports_chatgpt(params.get("exports_dir"))
        punteros = Path(lay.ruta(base, "chatgpt.raiz")) / "_punteros_imagenes.json"
        punteros_antes = punteros.read_bytes() if punteros.exists() else None
        imagenes = preparar_imagenes(base, exports, aplicar=True, log=log)
        plan = planificar(base, log)
        plan["imagenes"] = imagenes
        copia = aplicar(plan, carpeta_logs, log)
        # Para que --deshacer devuelva tambien la correspondencia de imagenes: si
        # no, la siguiente fusion volveria a poner las que esta pasada anadio.
        if punteros_antes is not None:
            (copia / "punteros_antes.json").write_bytes(punteros_antes)
        log("3/5 Fusionando RAW reparado ...")
        despues = fusionar(base, tmp / "despues")
        pm = planificar_merged(base, antes, despues)
        reg = aplicar_merged(pm, copia, log)
        conocidas |= _sha_de([copia / "merged"]) | _sha_de([merged / d for d in lay.conv_dirs(merged)])
        log("4/5 Refrescando PRJ ...")
        prj = lay.ruta(base, "prj")
        foto_prj = _fotografiar(prj, lambda rel: True, copia / "foto_prj") if lay.proyectos else []
        foto_ind = _fotografiar(merged, _filtro_indices(base), copia / "foto_indices")
        logp = copia / "pipeline.log"
        rp = actualizar_prj(params, pm["conv"], copia, conocidas, logp, log)
        rp["foto"] = foto_prj
        reg["foto_indices"] = foto_ind
        reg["merged"] = str(merged)
        reg["base"] = str(base)
        reg["punteros"] = str(punteros)
        derivados = {"merged": reg, "prj": rp, "protegidas": pm["protegidas"], "desconocidas": pm["desconocidas"]}
        (copia / "derivados.json").write_text(json.dumps(derivados, ensure_ascii=False, indent=1), encoding="utf-8")
        log("5/5 Indices ...")
        M.paso4_indices(base, merged, lay.ruta(base, "prj") if lay.proyectos else None, logp)
        return {"plan": plan, "copia": copia, "merged": pm, "prj": rp}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _deshacer_derivados(copia: Path, log: Callable[[str], None]) -> None:
    ruta = copia / "derivados.json"
    if not ruta.exists():
        return
    d = json.loads(ruta.read_text(encoding="utf-8"))
    conv = Path(d["merged"]["conv"])
    for e in d["merged"]["sobrescritas"] + d["merged"]["nuevas"]:
        p = conv / e["rel"]
        if p.exists() and hashlib.sha1(p.read_bytes()).hexdigest() != e["sha1"]:
            raise ErrorReparsea(f"MERGED: {e['rel']} ha cambiado desde que se aplico: no deshago nada")
    for e in d["merged"]["nuevas"]:
        (conv / e["rel"]).unlink(missing_ok=True)
    for e in d["merged"]["sobrescritas"] + d["merged"]["huerfanas"]:
        (conv / e["rel"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copia / "merged" / e["rel"], conv / e["rel"])
    if "foto_indices" in d["merged"]:
        _restaurar_foto(Path(d["merged"]["merged"]), _filtro_indices(Path(d["merged"]["base"])),
                        copia / "foto_indices", d["merged"]["foto_indices"])
    if d["prj"].get("prj"):
        _restaurar_foto(Path(d["prj"]["prj"]), lambda rel: True, copia / "foto_prj", d["prj"].get("foto", []))
    if d["merged"].get("punteros"):
        punteros = Path(d["merged"]["punteros"])
        if (copia / "punteros_antes.json").exists():
            shutil.copy2(copia / "punteros_antes.json", punteros)
        else:
            punteros.unlink(missing_ok=True)  # no existia antes de esta pasada
    log(f"MERGED restaurado ({len(d['merged']['sobrescritas'])} notas, {len(d['merged']['huerfanas'])} huerfanas, "
        f"indices) y PRJ como estaba ({len(d['prj'].get('foto', []))} notas).")


def escribir_csv(informe: dict, ruta: Path) -> None:
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nota", "derivas", "necesita_export"])
        for a in informe["afectadas"]:
            w.writerow([a["nota"], " ".join(a["derivas"]), "si" if a["necesita_export"] else "no"])


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
    ap = argparse.ArgumentParser(description="REParsea·me: diagnostico de las notas escritas con un parser antiguo. "
                                             "No escribe nada.")
    ap.add_argument("--base-vault", help="Carpeta base del vault (por defecto, la de memoria_config.yaml)")
    ap.add_argument("--csv", metavar="FICHERO", help="Guardar una fila por nota afectada")
    ap.add_argument("--aplicar", action="store_true",
                    help="Reescribir RAW de verdad (sin esto solo cuenta). Cierra Obsidian y haz copia del vault antes")
    ap.add_argument("--deshacer", metavar="CARPETA", help="Dejar RAW como antes de un --aplicar")
    ap.add_argument("--logs", metavar="CARPETA", help="Donde guardar la copia (por defecto, logs/ junto al programa)")
    ap.add_argument("--exports", metavar="CARPETA",
                    help="Donde estan los exports (por defecto, exports_dir de memoria_config.yaml)")
    args = ap.parse_args(argv)
    try:
        if args.deshacer:
            deshacer(Path(args.deshacer))
            return 0
        base = args.base_vault or _config_base()
        if not base:
            ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
        logs = Path(args.logs) if args.logs else None
        inf = diagnosticar(Path(base))
        exports = (exports_chatgpt(Path(args.exports)) if args.exports
                   else exports_chatgpt(_params(Path(base)).get("exports_dir")))
        if args.aplicar:
            res = ejecutar(Path(base), logs, exports=exports)
            plan, copia, der = res["plan"], res["copia"], {
                "protegidas": res["merged"]["protegidas"], "huerfanas": res["merged"]["huerfanas"],
                "desconocidas": res["merged"]["desconocidas"], "atrasadas": len(res["merged"]["escribir"]),
                "prj_huerfanas": res["prj"]["huerfanas"], "prj_desconocidas": res["prj"]["desconocidas"]}
        else:
            imagenes = preparar_imagenes(Path(base), exports, aplicar=False)
            plan, copia = planificar(Path(base)), None
            plan["imagenes"] = imagenes
            der = simular_derivados(Path(base), logs)
    except ErrorReparsea as e:
        print(f"[error] {e}")
        return 2
    print()
    print(f"DIAGNOSTICO (no se ha escrito nada) -- {inf['notas']} notas en RAW")
    print("  por proveedor: " + ", ".join(f"{k} {v}" for k, v in sorted(inf["por_proveedor"].items())))
    for k, (nombre, como) in DERIVAS.items():
        print(f"  {inf['por_deriva'][k]:6}  {nombre}  (se arregla con {'la nota' if como == 'nota' else 'el export'})")
    print(f"  notas afectadas: {len(inf['afectadas'])} "
          f"({inf['con_la_nota']} con la nota sola, {inf['con_el_export']} necesitan su export)")
    if args.csv:
        escribir_csv(inf, Path(args.csv))
        print(f"  informe: {args.csv}")
    print()
    print("HECHO en RAW" if copia else "PLAN para RAW (sin --aplicar no se escribe nada)")
    print(f"  notas {'reescritas' if copia else 'que se reescriben'}: {plan['reescribir']} "
          f"({plan['renombradas_al_reescribir']} cambian de nombre)")
    print(f"  {'renombradas' if copia else 'que se renombran'} por su huella sin cambiar el texto: {plan['renombrar']}")
    print(f"  versiones identicas {'apartadas' if copia else 'que se apartan'} a la copia: {plan['papelera']}")
    print(f"  imagenes avisadas que trae algun export (al banco; se veran en MERGED): {plan['imagenes']}")
    print()
    print("HECHO en MERGED y PRJ" if copia else "MERGED y PRJ (se rehacen al aplicar)")
    if copia:
        print(f"  notas de MERGED puestas al dia: {der['atrasadas']}")
    else:
        print(f"  notas de MERGED que ya se habian quedado atras de RAW: {der['atrasadas']}")
    print(f"  huerfanas de MERGED {'apartadas' if copia else 'que se apartan'}: {len(der['huerfanas'])}")
    if copia:
        print(f"  copias huerfanas de PRJ apartadas: {len(der['prj_huerfanas'])}"
              f" ({len(der['prj_desconocidas'])} sin reconocer, se quedan)")
    print(f"  editadas a mano en MERGED, sin tocar: {len(der['protegidas'])}")
    for k in der["protegidas"]:
        print(f"      {k}")
    if der["desconocidas"]:
        print(f"  notas de MERGED que no sale de RAW y no reconozco (se quedan): {len(der['desconocidas'])}")
        for k in der["desconocidas"][:10]:
            print(f"      {k}")
    if copia:
        print(f"\n  para deshacer: python reparseame.py --deshacer \"{copia}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
