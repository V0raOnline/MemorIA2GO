#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config_loader.py — Carga parámetros compartidos para los scripts del ecosistema MemorIA.
Prioriza: argumento CLI > variable de entorno > config.yaml > valor por defecto.
"""

import os, json, yaml
from pathlib import Path

def load_config(config_path: str | None = None) -> dict:
    # Prioridad: ruta explícita o entorno
    cfg_file = (
        Path(config_path).expanduser()
        if config_path
        else Path(os.getenv("MEMORIA_CONFIG", "memoria_config.yaml"))
    )

    if not cfg_file.exists():
        raise FileNotFoundError(f"⚠️ Config file not found: {cfg_file}")

    # Leer YAML o JSON
    if cfg_file.suffix.lower() == ".json":
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    else:
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))

    # Asegurar estructura básica.
    #
    # setdefault NO basta, y esto costó una tarde de depuración con V0ra
    # (2026-08-11): en YAML, una clave suelta sin nada debajo
    #
    #     options:
    #
    # se carga como options: None, no como clave ausente. setdefault solo
    # actúa si la clave FALTA, así que el None sobrevivía y el primer
    # get_opt() reventaba con "'NoneType' object has no attribute 'get'".
    # El síntoma era desconcertante: Verificación en verde -- solo mira
    # 'paths' -- y el pipeline negándose a arrancar diciendo que no había
    # configuración. Un fichero entero vacío deja cfg en None, igual.
    if not isinstance(cfg, dict):
        cfg = {}
    for bloque in ("paths", "options"):
        if not isinstance(cfg.get(bloque), dict):
            cfg[bloque] = {}
    return cfg


def get_path(cfg: dict, key: str, default: str | None = None) -> Path:
    """Obtiene una ruta del bloque 'paths'"""
    p = cfg.get("paths", {}).get(key, default)
    return Path(p).expanduser().resolve() if p else None


def get_opt(cfg: dict, key: str, default=None):
    """Obtiene una opción genérica"""
    return cfg.get("options", {}).get(key, default)
