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
# exFAT/FAT redondea a 2 s. Mas que eso es una fecha perdida, y el merge la usa.
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
        raise ErrorDeMovimiento(f"el RAW ya esta en {destino}.")
    if layout.dentro(layout.norm(destino), layout.norm(origen)):
        raise ErrorDeMovimiento("el destino esta DENTRO del RAW actual: la copia se copiaria a si misma.")
    if layout.dentro(layout.norm(origen), layout.norm(destino)):
        raise ErrorDeMovimiento("el RAW actual esta dentro del destino: mezclaria la fuente con otras carpetas.")
    pedido = lay.con(externas={"raw": str(destino)})
    malos = pedido.problemas(base_vault)
    if malos:
        raise ErrorDeMovimiento("el destino no es valido:\n  - " + "\n  - ".join(malos))


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
            f"el destino ya tiene {len(ajenos)} fichero(s) que no estan en el RAW (p.ej. {muestra}). "
            "No es una carpeta limpia; elige otra o vaciala tu.")
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
                f"en el destino, '{rel}' ya existe y es DISTINTO del original. No lo sobrescribo.")
    peso = sum(origen[r].stat().st_size for r in por_copiar)
    return por_copiar, ya, peso


def copiar(origen: Dict[str, Path], destino: Path, por_copiar: List[str]) -> None:
    for rel in por_copiar:
        dst = destino.joinpath(*rel.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        parcial = dst.with_name(dst.name + SUFIJO_PARCIAL)
        shutil.copy2(origen[rel], parcial)   # copy2 conserva la fecha de modificacion
        os.replace(parcial, dst)


def verificar(origen: Dict[str, Path], destino: Path) -> List[str]:
    """Una linea por cada fichero que NO coincide. Vacia = copia identica."""
    fallos: List[str] = []
    for rel, src in origen.items():
        dst = destino.joinpath(*rel.split("/"))
        if not dst.is_file():
            fallos.append(f"falta en el destino: {rel}")
            continue
        if src.stat().st_size != dst.stat().st_size:
            fallos.append(f"tamano distinto: {rel}")
            continue
        if _sha1(src) != _sha1(dst):
            fallos.append(f"contenido distinto: {rel}")
            continue
        if abs(src.stat().st_mtime - dst.stat().st_mtime) > TOLERANCIA_MTIME:
            fallos.append(f"fecha de modificacion perdida: {rel}")
    return fallos


def mover(base_vault: Path, hacia: Path, dry_run: bool = False, log=print) -> int:
    base_vault = Path(base_vault)
    lay = layout.cargar(base_vault, usar_entorno=False)
    origen_dir = lay.ruta(base_vault, "raw")
    destino = Path(hacia).expanduser().resolve()

    if not origen_dir.is_dir():
        raise ErrorDeMovimiento(f"no hay un RAW que mover: {origen_dir} no existe.")
    comprobar_destino(origen_dir, destino, base_vault, lay)

    origen = listar(origen_dir)
    por_copiar, ya, peso = planificar(origen, destino)
    total = sum(p.stat().st_size for p in origen.values())
    log(f"RAW actual : {origen_dir}")
    log(f"Destino    : {destino}")
    log(f"Ficheros   : {len(origen)} ({total / 1e6:.1f} MB); por copiar {len(por_copiar)}, "
        f"ya en el destino {len(ya)}")

    libre = _espacio_libre(destino)
    if peso * 1.02 > libre:
        raise ErrorDeMovimiento(
            f"no hay sitio: hacen falta {peso / 1e6:.1f} MB y el destino tiene {libre / 1e6:.1f} MB libres.")
    if dry_run:
        log("DRY-RUN: no se ha copiado ni escrito nada.")
        return 0

    copiar(origen, destino, por_copiar)
    fallos = verificar(origen, destino)
    if fallos:
        for f in fallos[:20]:
            log(f"  ✗ {f}")
        raise ErrorDeMovimiento(
            f"la verificacion ha fallado en {len(fallos)} fichero(s). El marcador NO se ha tocado "
            "y el original sigue intacto. Puedes repetir el comando.")

    nuevo = lay.con(externas={"raw": str(destino)})
    layout.escribir_marcador(base_vault, nuevo)
    log(f"✓ Copia verificada: {len(origen)} ficheros identicos (tamano, SHA-1 y fecha).")
    log("")
    log("Faltan dos cosas, las dos tuyas:")
    log(f"  1. En Configuracion (o en memoria_config.yaml) pon:  raw_vault: '{destino}'")
    log(f"  2. Cuando lo hayas comprobado, borra el RAW antiguo: {origen_dir}")
    log("     Esta herramienta no lo borra.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Mueve el RAW a otra carpeta: copia, verifica, no borra.")
    ap.add_argument("--hacia", required=True, help="Carpeta destino (absoluta) para el RAW")
    ap.add_argument("--config", default=None, help="memoria_config.yaml (por defecto, el del programa)")
    ap.add_argument("--base-vault", default=None, help="Carpeta base; alternativa a --config")
    ap.add_argument("--dry-run", action="store_true", help="Solo cuenta y comprueba, no copia")
    args = ap.parse_args(argv)

    try:
        if args.base_vault:
            base = Path(args.base_vault)
        else:
            from config_loader import load_config, get_path
            cfg_path = args.config or str(Path(__file__).resolve().parent / "memoria_config.yaml")
            base = get_path(load_config(cfg_path), "base_vault")
            if not base:
                raise ErrorDeMovimiento("'base_vault' esta sin configurar.")
        if not Path(base).is_dir():
            raise ErrorDeMovimiento(f"la carpeta base no existe: {base}")
        return mover(base, Path(args.hacia), dry_run=args.dry_run)
    except ErrorDeMovimiento as e:
        print(f"✗ {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
