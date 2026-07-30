#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suno_stats.py — Estadisticas de la biblioteca de Suno para el Observatorio.

Lee `_index.json` del backup, NO el vault construido. Tres razones:
  - Es la fuente de verdad: el listado crudo completo tal cual lo devuelve
    la API, con todos los campos. El vault es un derivado.
  - Funciona aunque el vault no se haya construido todavia, que es
    justamente el estado en el que quieres ver la tarjeta: acabas de
    terminar un backup y quieres saber que has salvado.
  - Un solo fichero de 12 MB en vez de recorrer 2094 notas.

Campos usados, verificados contra las 2094 pistas reales de V0ra
(2026-07-30) -- no contra la documentacion, que tenia dos errores:
  - `duration` vive en `metadata`, NO en el nivel superior (el CONTEXT de
    SunoDownloader lo listaba como top-level).
  - `metadata.task` se documentaba como gen/cover/mashup_condition; en los
    datos reales hay seis valores mas (extend, upsample, infill,
    artist_consistency, upload_extend, cadena vacia) y `gen` no aparece
    NUNCA: 1151 de 2094 lo traen a None. build_suno_vault.py ya lo maneja
    (`raw.get("task") or "gen"`), pero aqui no se usa task para nada
    precisamente por eso.

Se cuenta por badge y por campos booleanos de nivel superior, que si son
estables.
"""
import json
from pathlib import Path
from typing import Optional

INDEX_FILENAME = "_index.json"

# Badge que marca una pista terminada, no una variante intermedia. Es la
# etiqueta que la propia UI de Suno pinta, asi que no la inventamos
# nosotros. Util de verdad: en arboles de 60+ variantes es lo unico que
# distingue "esta es LA version" de "esta es un intento".
BADGE_COMPLETA = "Full Song"


def _horas(segundos: float) -> str:
    if segundos < 3600:
        return f"{segundos / 60:.0f} min"
    return f"{segundos / 3600:.0f} h"


def compute_suno_stats(backup_dir) -> Optional[dict]:
    """None si no hay backup (la tarjeta no se pinta). Nunca lanza: no
    poder contar canciones no debe tumbar el dashboard entero."""
    if not backup_dir:
        return None
    path = Path(backup_dir) / INDEX_FILENAME
    if not path.is_file():
        return None

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            clips = json.load(f)
    except Exception:
        return None
    if not isinstance(clips, list):
        return None

    total = 0
    favoritas = 0
    completas = 0
    segundos = 0.0
    proyectos = set()
    sin_proyecto = 0

    for c in clips:
        if not isinstance(c, dict):
            continue
        # La papelera de Suno no se cuenta como biblioteca. Hoy V0ra tiene
        # 0, pero el campo existe y contar basura inflaria el total.
        if c.get("is_trashed"):
            continue
        total += 1
        meta = c.get("metadata") or {}
        if c.get("is_liked"):
            favoritas += 1
        try:
            segundos += float(meta.get("duration") or 0)
        except (TypeError, ValueError):
            pass
        for b in meta.get("secondary_badges") or []:
            if isinstance(b, dict) and b.get("display_name") == BADGE_COMPLETA:
                completas += 1
                break
        proy = c.get("project") or {}
        nombre = proy.get("name") if isinstance(proy, dict) else None
        if nombre:
            proyectos.add(nombre)
        else:
            sin_proyecto += 1

    return {
        "total": total,
        "favoritas": favoritas,
        "completas": completas,
        "proyectos": len(proyectos),
        "sin_proyecto": sin_proyecto,
        "duracion_segundos": round(segundos),
        "duracion_legible": _horas(segundos),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Suno library statistics.")
    ap.add_argument("backup_dir", help="Folder holding _index.json and the downloaded tracks")
    args = ap.parse_args()

    stats = compute_suno_stats(args.backup_dir)
    if stats is None:
        raise SystemExit(f"No {INDEX_FILENAME} found in {args.backup_dir}")

    print(f"Tracks:    {stats['total']} | {stats['duracion_legible']}")
    print(f"Favorites: {stats['favoritas']}")
    print(f"Complete:  {stats['completas']} (badge '{BADGE_COMPLETA}')")
    print(f"Projects:  {stats['proyectos']} ({stats['sin_proyecto']} track(s) with no project)")


if __name__ == "__main__":
    main()
