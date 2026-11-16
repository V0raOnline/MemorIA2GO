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
import sys
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
            "reescrita": nuevo is not None,
            "esquema": "base" if not m else ("hash" if m.group(1).lower().startswith("h") else "otro"),
        })
    ops: List[dict] = []
    for (carpeta, nombre_base), notas in grupos.items():
        # La del nombre sin sufijo primero: es el hueco que la importacion
        # compara antes que ninguno, y si hay identicas se queda ella.
        notas.sort(key=lambda n: (n["esquema"] != "base", n["ruta"].name))
        destino_de: Dict[str, Path] = {}
        ocupados = set()
        for n in notas:
            sha = hashlib.sha1(n["final"]).hexdigest()
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
            if destino != n["ruta"] or n["reescrita"]:
                ops.append({"tipo": "reescribir" if n["reescrita"] else "renombrar",
                            "origen": n["ruta"], "destino": destino, "final": n["final"]})
    return {"raw": raw, "ops": ops,
            "reescribir": sum(o["tipo"] == "reescribir" for o in ops),
            "renombrar": sum(o["tipo"] == "renombrar" for o in ops),
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
        os.utime(o["destino"], ns=(reg["mtime_ns"], reg["mtime_ns"]))
    log(f"Hecho. Copia para deshacer: {copia}")
    return copia


def deshacer(copia: Path, log: Callable[[str], None] = print) -> int:
    """Deja RAW como estaba antes de un --aplicar. Se niega si alguna nota
    escrita ha cambiado desde entonces: no pisa trabajo posterior."""
    copia = Path(copia)
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
    args = ap.parse_args(argv)
    try:
        if args.deshacer:
            deshacer(Path(args.deshacer))
            return 0
        base = args.base_vault or _config_base()
        if not base:
            ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
        inf = diagnosticar(Path(base))
        plan = planificar(Path(base))
        copia = aplicar(plan, Path(args.logs) if args.logs else None) if args.aplicar else None
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
    if copia:
        print(f"  para deshacer: python reparseame.py --deshacer \"{copia}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
