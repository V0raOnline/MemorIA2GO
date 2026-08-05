#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flowmusic_stats.py — Estadisticas de la biblioteca de Flow Music para el
Observatorio.

Mismo criterio que suno_stats.py: lee `_index.json` del backup, NO el
vault construido. Es la fuente de verdad, funciona aunque el vault no se
haya construido todavia, y es un solo fichero en vez de recorrer 174
notas.

Diferencia de formato con Suno: alli `_index.json` es una LISTA de clips;
aqui es un DICT id -> metadata, porque el backup se construye hidratando
por id. Se aceptan las dos formas por si el formato cambia.

Campos verificados contra las 174 pistas reales (2026-08-05):
  - `duration` puede ser None: 15 pistas traen
    `duration_status = "not_requested"` porque Flow nunca la calculo. No
    se cuentan como cero, se ignoran para la media pero SI para el total
    de pistas.
  - `op_type` es el equivalente al `task` de Suno. `audio__create_song`
    marca una pista original; el resto son derivadas.
  - `source_clip_ids` es el linaje. 53 pistas lo traen.
"""
import json
from pathlib import Path
from typing import Optional

INDEX_FILENAME = "_index.json"

# op_type de una pista creada de cero, no derivada de otra. Es lo mas
# parecido al "Full Song" de Suno: distingue el material original de las
# variantes. Lo pinta la propia API, no lo inventamos aqui.
OP_ORIGINAL = "audio__create_song"


def _legible(segundos: float) -> str:
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def compute_flowmusic_stats(backup_dir) -> Optional[dict]:
    """None si no hay backup (la tarjeta no se pinta). Nunca lanza: no
    poder contar pistas no debe tumbar el dashboard entero."""
    if not backup_dir:
        return None
    path = Path(backup_dir) / INDEX_FILENAME
    if not path.is_file():
        return None

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
    except Exception:
        return None

    if isinstance(datos, dict):
        clips = list(datos.values())
    elif isinstance(datos, list):
        clips = datos
    else:
        return None

    total = 0
    favoritas = 0
    originales = 0
    con_linaje = 0
    con_letra = 0
    segundos = 0.0
    sin_duracion = 0
    conversaciones = set()

    for c in clips:
        if not isinstance(c, dict):
            continue
        # Flow Music marca las borradas con deleted_at en vez de tener
        # papelera. Contarlas inflaria el total con cosas que ya no estan.
        if c.get("deleted_at"):
            continue
        total += 1

        if c.get("is_favorite"):
            favoritas += 1
        if c.get("op_type") == OP_ORIGINAL:
            originales += 1
        if c.get("source_clip_ids"):
            con_linaje += 1
        if c.get("lyrics"):
            con_letra += 1

        duracion = c.get("duration")
        if isinstance(duracion, (int, float)):
            segundos += float(duracion)
        else:
            sin_duracion += 1

        conv = c.get("conversation_title")
        if conv:
            conversaciones.add(conv)

    if total == 0:
        return None

    return {
        "total": total,
        "favoritas": favoritas,
        "originales": originales,
        "con_linaje": con_linaje,
        "con_letra": con_letra,
        "conversaciones": len(conversaciones),
        "segundos": round(segundos),
        "duracion_legible": _legible(segundos),
        # Se expone para poder decir "8,5 h (15 sin medir)" en vez de dar
        # un total que parece completo y no lo es.
        "sin_duracion": sin_duracion,
    }
