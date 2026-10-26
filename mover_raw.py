#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mover_raw.py — Lleva el RAW de un vault existente a otra carpeta, sin perder nada.

El RAW es la fuente del pipeline: el merge lo relee entero cada vez, y con el
viven el registro de exports ya importados y la lista de gizmos pendientes. No
se puede "cambiar la ruta" y ya: si la config apunta a un RAW vacio, las notas
nuevas irian a el, el merge no veria las anteriores y nada daria error. Por eso
el pipeline se niega a seguir cuando config y vault discrepan (layout.conflictos),
y esta herramienta es el camino correcto para que dejen de discrepar.

Que hace, en orden:
  1. Cuenta lo que hay y comprueba que cabe en el destino.
  2. COPIA cada fichero (a un .part y renombrando al terminar), conservando la
     fecha de modificacion: el merge decide por ella que titulo prevalece.
  3. VERIFICA cada fichero: tamano, SHA-1 y fecha. No se fia de que la copia
     "no haya dado error".
  4. Solo si todo coincide, escribe el marcador del vault con la nueva ubicacion.

Que NO hace: borrar. El original se queda donde estaba; lo borras tu cuando lo
hayas comprobado. Tampoco toca tu memoria_config.yaml: al terminar te dice que
valor poner en `raw_vault`.

Se puede repetir: lo que ya esta copiado y coincide se salta; un fichero del
destino que DIFIERE del original se rechaza (no se sobrescribe), igual que uno
que no existe en el origen (el destino no es una carpeta limpia).

Uso:
  python mover_raw.py --hacia "D:\\fuente_m3m0ria" [--config memoria_config.yaml] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import layout

# Segundos de diferencia admitidos entre la fecha del original y la de la copia:
# exFAT/FAT redondea a 2 s. Mas que eso es una fecha perdida, y el merge la usa. V0-m3m 2321ada5-21d8-4e91-8539-34e31d5539ea
TOLERANCIA_MTIME = 2.0
SUFIJO_PARCIAL = ".part"


class ErrorDeMovimiento(Exception):
    """Algo impide mover con seguridad. El mensaje dice que y que hacer."""


def _sha1(ruta: Path) -> str:
    h = hashlib.sha1()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def listar(raiz: Path) -> Dict[str, Path]:
    """{ruta relativa con '/': ruta} de todos los ficheros. No baja a enlaces a carpetas."""
    salida: Dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for fn in filenames:
            p = Path(dirpath) / fn
            salida[p.relative_to(raiz).as_posix()] = p
    return salida


def comprobar_destino(origen: Path, destino: Path, base_vault: Path, lay: layout.Layout) -> None:
    """Rechaza el destino si el movimiento no seria seguro. No toca el disco."""
    if layout.norm(origen) == layout.norm(destino):
        raise ErrorDeMovimiento(f"the RAW is already in {destino}.")
    if layout.dentro(layout.norm(destino), layout.norm(origen)):
        raise ErrorDeMovimiento("the destination is INSIDE the current RAW: the copy would copy itself.")
    if layout.dentro(layout.norm(origen), layout.norm(destino)):
        raise ErrorDeMovimiento("the current RAW is inside the destination: it would mix the source with other folders.")
    pedido = lay.con(externas={"raw": str(destino)})
    malos = pedido.problemas(base_vault)
    if malos:
        raise ErrorDeMovimiento("the destination is not valid:\n  - " + "\n  - ".join(malos))


def _espacio_libre(destino: Path) -> int:
    ancla = destino
    while not ancla.exists() and ancla != ancla.parent:
        ancla = ancla.parent
    return shutil.disk_usage(ancla).free


def planificar(origen: Dict[str, Path], destino: Path) -> Tuple[List[str], List[str], int]:
    """(por_copiar, ya_copiados, bytes_por_copiar). Falla si el destino no es limpio."""
    existentes = listar(destino) if destino.is_dir() else {}
    ajenos = [r for r in existentes
              if r not in origen and not (r.endswith(SUFIJO_PARCIAL) and r[:-len(SUFIJO_PARCIAL)] in origen)]
    if ajenos:
        muestra = ", ".join(sorted(ajenos)[:5])
        raise ErrorDeMovimiento(
            f"the destination already has {len(ajenos)} file(s) that are not in the RAW (e.g. {muestra}). "
            "It is not a clean folder; choose another one or empty it yourself.")
    por_copiar: List[str] = []
    ya: List[str] = []
    for rel, src in origen.items():
        dst = existentes.get(rel)
        if dst is None:
            por_copiar.append(rel)
        elif src.stat().st_size == dst.stat().st_size and _sha1(src) == _sha1(dst):
            ya.append(rel)
        else:
            raise ErrorDeMovimiento(
                f"in the destination, '{rel}' already exists and is DIFFERENT from the original. I will not overwrite it.")
    peso = sum(origen[r].stat().st_size for r in por_copiar)
    return por_copiar, ya, peso


def copiar(origen: Dict[str, Path], destino: Path, por_copiar: List[str]) -> None:
    for rel in por_copiar:
        dst = destino.joinpath(*rel.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        parcial = dst.with_name(dst.name + SUFIJO_PARCIAL)
        shutil.copy2(origen[rel], parcial)   # copy2 conserva la fecha de modificacion V0-m3m 2321ada5-21d8-4e91-8539-34e31d5539ea
        os.replace(parcial, dst)


def verificar(origen: Dict[str, Path], destino: Path) -> List[str]:
    """Una linea por cada fichero que NO coincide. Vacia = copia identica."""
    fallos: List[str] = []
    for rel, src in origen.items():
        dst = destino.joinpath(*rel.split("/"))
        if not dst.is_file():
            fallos.append(f"missing in the destination: {rel}")
            continue
        if src.stat().st_size != dst.stat().st_size:
            fallos.append(f"different size: {rel}")
            continue
        if _sha1(src) != _sha1(dst):
            fallos.append(f"different content: {rel}")
            continue
        if abs(src.stat().st_mtime - dst.stat().st_mtime) > TOLERANCIA_MTIME:
            fallos.append(f"modification date lost: {rel}")
    return fallos


def mover(base_vault: Path, hacia: Path, dry_run: bool = False, log=print) -> int:
    base_vault = Path(base_vault)
    lay = layout.cargar(base_vault, usar_entorno=False)
    origen_dir = lay.ruta(base_vault, "raw")
    destino = Path(hacia).expanduser().resolve()

    if not origen_dir.is_dir():
        raise ErrorDeMovimiento(f"there is no RAW to move: {origen_dir} does not exist.")
    comprobar_destino(origen_dir, destino, base_vault, lay)

    origen = listar(origen_dir)
    por_copiar, ya, peso = planificar(origen, destino)
    total = sum(p.stat().st_size for p in origen.values())
    log(f"Current RAW : {origen_dir}")
    log(f"Destination : {destino}")
    log(f"Files       : {len(origen)} ({total / 1e6:.1f} MB); to copy {len(por_copiar)}, "
        f"already in the destination {len(ya)}")

    libre = _espacio_libre(destino)
    if peso * 1.02 > libre:
        raise ErrorDeMovimiento(
            f"not enough space: {peso / 1e6:.1f} MB needed and the destination has {libre / 1e6:.1f} MB free.")
    if dry_run:
        log("DRY-RUN: nothing has been copied or written.")
        return 0

    copiar(origen, destino, por_copiar)
    fallos = verificar(origen, destino)
    if fallos:
        for f in fallos[:20]:
            log(f"  ✗ {f}")
        raise ErrorDeMovimiento(
            f"verification failed for {len(fallos)} file(s). The marker has NOT been touched "
            "and the original is intact. You can run the command again.")

    nuevo = lay.con(externas={"raw": str(destino)})
    layout.escribir_marcador(base_vault, nuevo)
    log(f"✓ Copy verified: {len(origen)} identical files (size, SHA-1 and date).")
    log("")
    log("Two things are left, both for you:")
    log(f"  1. In Settings (or in memoria_config.yaml) set:  raw_vault: '{destino}'")
    log(f"  2. Once you have checked it, delete the old RAW: {origen_dir}")
    log("     This tool does not delete it.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Moves the RAW to another folder: copies, verifies, does not delete.")
    ap.add_argument("--hacia", required=True, help="Destination folder (absolute) for the RAW")
    ap.add_argument("--config", default=None, help="memoria_config.yaml (default: the one next to the program)")
    ap.add_argument("--base-vault", default=None, help="Base folder; alternative to --config")
    ap.add_argument("--dry-run", action="store_true", help="Only counts and checks, does not copy")
    args = ap.parse_args(argv)

    try:
        if args.base_vault:
            base = Path(args.base_vault)
        else:
            from config_loader import load_config, get_path
            cfg_path = args.config or str(Path(__file__).resolve().parent / "memoria_config.yaml")
            base = get_path(load_config(cfg_path), "base_vault")
            if not base:
                raise ErrorDeMovimiento("'base_vault' is not configured.")
        if not Path(base).is_dir():
            raise ErrorDeMovimiento(f"the base folder does not exist: {base}")
        return mover(base, Path(args.hacia), dry_run=args.dry_run)
    except ErrorDeMovimiento as e:
        print(f"✗ {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
