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
import re
import sys
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
    "bytes_nulos": ("Bytes nulos (marcadores de imagen sin resolver)", "nota"),
    "citas_crudas": ("Citas internas en crudo", "nota"),
    "imagen_no_disponible": ("Imagen no disponible", "export"),
    "sin_model": ("Sin modelo en el frontmatter", "export"),
    "sin_conv_id": ("Sin conv_id en el frontmatter", "export"),
}

_JSON_CRUDO = re.compile(rb'^\{"content_type": ', re.M)
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
    if _JSON_CRUDO.search(datos):
        d.append("json_crudo")
    if b"\x00" in datos:
        d.append("bytes_nulos")
    # Las citas dentro de una linea de JSON crudo ya se arreglan con ella: solo
    # cuentan las que estan en el texto normal (8 notas en el vault real).
    if _CITA_CRUDA.search("\n".join(ln for ln in texto.split("\n") if not ln.startswith('{"content_type": '))):
        d.append("citas_crudas")
    if _IMAGEN_NO_DISPONIBLE.search(datos):
        d.append("imagen_no_disponible")
    if not front.get("model"):
        d.append("sin_model")
    if not front.get("conv_id"):
        d.append("sin_conv_id")
    return d


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
    args = ap.parse_args(argv)
    base = args.base_vault or _config_base()
    if not base:
        ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
    try:
        inf = diagnosticar(Path(base))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
