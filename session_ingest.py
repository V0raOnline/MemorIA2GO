#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_ingest.py — Ingesta las sesiones locales de Claude Code al vault.

Herramienta hermana, ejecutada a mano: el pipeline (MemorIA2GO.py) no la llama.
Sin lanzarla, todo se comporta igual que antes.

QUE HACE, POR SESION (diseño cerrado en CONTEXT 3y)
────────────────────────────────────────────────────
1. Copia el `.jsonl` CRUDO e integro a un banco de fuente
   (MERGED_VAULT/CLAUDE_CODE/SESIONES), nombrado por hash de contenido. Es la
   unica copia: estas sesiones no salen de ningun export, y la carpeta de
   origen (~/.claude/projects) es efimera. Se preserva SIEMPRE, pase lo que
   pase con las notas -- si mañana quieres regenerarlas con otra verbosidad, la
   fuente sigue ahi (mismo principio que "no borres los zip").
2. Parsea la sesion y genera las tres notas:
   - la MADRE va a Conversaciones/Sesiones-Code/AAAA/MM/ -> Cartografia la ve
     (recorre Conversaciones/ recursivo) y la cruza con los temas; entra con
     Project_name: none (huerfana, candidata a tema), provider: claude-code.
     Subcarpeta propia a proposito: la separa de las conversaciones de export
     para que un futuro reproceso del pipeline no la mezcle ni la pise.
   - las HIJAS (razonamientos, herramientas) van al banco, FUERA de
     Conversaciones/. Cartografia ni las mira: su vocabulario (git, rutas,
     comandos) contaminaria la nube.

IDEMPOTENTE: el banco de fuente deduplica por hash; una sesion ya ingerida con
el mismo contenido no se reescribe. Reprocesar es seguro.

NO deriva Project_name del cwd (decision de V0ra): en la UI de Claude Code los
proyectos son cosmeticos (puro basename del cwd, sin id ni enlace) y el cwd es
fragil. Las sesiones entran como huerfanas y se agrupan a mano, como todo lo
curado de la casa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from providers import claudecode_adapter as cc  # noqa: E402
import session_notes as sn  # noqa: E402

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

BANCO = "CLAUDE_CODE/SESIONES"
SUBCARPETA_MADRE = "Sesiones-Code"


def _hash_fichero(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def _preservar_fuente(jsonl: Path, banco_dir: Path) -> str:
    """Copia el .jsonl crudo al banco, nombrado por hash. Devuelve el nombre.
    Idempotente: si ya esta, no reescribe."""
    banco_dir.mkdir(parents=True, exist_ok=True)
    h = _hash_fichero(jsonl)
    dest = banco_dir / ("%s.jsonl" % h)
    if not dest.exists():
        dest.write_bytes(jsonl.read_bytes())
    return dest.name


def _anotar_manifest(banco_dir: Path, fuente_nombre: str, sesion: dict,
                     jsonl: Path) -> None:
    manifest_path = banco_dir / "_sesiones_manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest[fuente_nombre] = {
        "session_id": sesion.get("session_id"),
        "title": sesion.get("title"),
        "project_cwd": sesion.get("project"),
        "git_branch": sesion.get("git_branch"),
        "turnos": len(sesion.get("turns") or []),
        "origen": str(jsonl),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def ingest_sesion(jsonl: Any, base_vault: Any, nivel: int = sn.NIVEL_PLEGADO
                  ) -> Optional[Dict[str, Path]]:
    """Ingesta UNA sesion. Devuelve {rol: ruta} de las notas escritas, o None
    si el .jsonl no tenia contenido util."""
    jsonl = Path(jsonl)
    base_vault = Path(base_vault)
    merged = base_vault / "MERGED_VAULT"
    banco_dir = merged / BANCO

    sesion = cc.parse_fichero(jsonl)
    if not sesion or not sesion.get("turns"):
        return None

    # 1. Fuente cruda, siempre (aunque las notas ya existan).
    fuente = _preservar_fuente(jsonl, banco_dir)
    _anotar_manifest(banco_dir, fuente, sesion, jsonl)

    # 2. Notas: madre a Conversaciones/Sesiones-Code/AAAA/MM, hijas al banco.
    fecha = sn._fecha(sesion.get("create_time"))  # AAAA-MM-DD o 'sin-fecha'
    y, m = (fecha.split("-")[0], fecha.split("-")[1]) if "-" in fecha else ("sin-fecha", "")
    madre_dir = merged / "Conversaciones" / SUBCARPETA_MADRE / y / m

    extra_madre = {
        "Project_name": "none",           # huerfana: se agrupa a mano
        "source": "claude_code_session",
        "conv_id": sesion.get("session_id"),
    }
    return sn.generar_notas(sesion, madre_dir, nivel=nivel,
                            hijas_dir=banco_dir, extra_madre=extra_madre)


def ingest_dir(projects_dir: Any, base_vault: Any,
               nivel: int = sn.NIVEL_PLEGADO,
               log=print) -> Dict[str, int]:
    """Ingesta todos los .jsonl bajo projects_dir (recursivo). Cada carpeta es
    un proyecto de Claude Code; se recorren todas."""
    projects_dir = Path(projects_dir)
    jsonls = sorted(projects_dir.rglob("*.jsonl"))
    stats = {"sesiones": 0, "vacias": 0, "notas": 0}
    log("%d ficheros de sesion bajo %s" % (len(jsonls), projects_dir))
    for j in jsonls:
        try:
            escritas = ingest_sesion(j, base_vault, nivel=nivel)
        except Exception as e:
            log("  FALLA %s: %s" % (j.name, str(e)[:60]))
            continue
        if not escritas:
            stats["vacias"] += 1
            continue
        stats["sesiones"] += 1
        stats["notas"] += len(escritas)
        log("  %-40s -> %s" % (j.name[:40], "+".join(sorted(escritas))))
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ingesta las sesiones locales de Claude Code al vault. "
                    "A mano: el pipeline no la llama.")
    ap.add_argument("--projects-dir", default=None,
                    help="Carpeta de sesiones (por defecto ~/.claude/projects)")
    ap.add_argument("--config", default=None, help="Ruta a memoria_config.yaml")
    ap.add_argument("--base-vault", default=None,
                    help="Salta la config y usa esta carpeta base")
    ap.add_argument("--nivel", type=int, default=sn.NIVEL_PLEGADO,
                    choices=[0, 1, 2, 3],
                    help="Verbosidad del output de herramientas (2 por defecto)")
    args = ap.parse_args()

    projects = Path(args.projects_dir) if args.projects_dir \
        else Path.home() / ".claude" / "projects"
    if not projects.exists():
        print("No existe la carpeta de sesiones: %s" % projects)
        return 2

    if args.base_vault:
        base_vault = Path(args.base_vault)
    else:
        from config_loader import load_config, get_path
        cfg = load_config(args.config or str(HERE / "memoria_config.yaml"))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            print("base_vault no configurado")
            return 2

    stats = ingest_dir(projects, base_vault, nivel=args.nivel)
    print()
    print("Sesiones ingeridas: %d  ·  vacias: %d  ·  notas escritas: %d"
          % (stats["sesiones"], stats["vacias"], stats["notas"]))
    print("Fuente cruda preservada en MERGED_VAULT/%s" % BANCO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
