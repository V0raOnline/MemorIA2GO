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

    # Asegurar estructura básica
    cfg.setdefault("paths", {})
    cfg.setdefault("options", {})
    return cfg


def get_path(cfg: dict, key: str, default: str | None = None) -> Path:
    """Obtiene una ruta del bloque 'paths'"""
    p = cfg.get("paths", {}).get(key, default)
    return Path(p).expanduser().resolve() if p else None


def get_opt(cfg: dict, key: str, default=None):
    """Obtiene una opción genérica"""
    return cfg.get("options", {}).get(key, default)
