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
import os
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


def sesion_activa() -> Optional[str]:
    """El sessionId de la sesion de Claude Code EN CURSO, si esto corre dentro
    de una. Claude Code lo publica en el entorno. Fuera de Claude Code (o en
    Codex) devuelve None."""
    return (os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or "").strip() or None


def _esta_creciendo(jsonl: Path) -> bool:
    """Red de seguridad para cuando no hay sessionId en el entorno: un fichero
    que cambia de tamaño mientras se lee es una sesion viva. La propia lectura
    del contenido da la ventana temporal; no hace falta un sleep artificial."""
    try:
        antes = jsonl.stat().st_size
        _ = jsonl.read_bytes()
        return jsonl.stat().st_size != antes
    except OSError:
        return False


def _id_de(jsonl: Path) -> Optional[str]:
    """El sessionId de un .jsonl, leido de su primera linea util. Barato."""
    try:
        with jsonl.open("r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                d = json.loads(linea)
                if isinstance(d, dict) and d.get("sessionId"):
                    return d["sessionId"]
                break
    except (OSError, ValueError):
        pass
    return None


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
    stats = {"sesiones": 0, "vacias": 0, "notas": 0, "activa_omitida": 0}
    activa = sesion_activa()
    log("%d ficheros de sesion bajo %s" % (len(jsonls), projects_dir))
    for j in jsonls:
        # Omitir la sesion EN CURSO: su .jsonl esta creciendo mientras la
        # leemos, asi que su captura seria parcial. (El caso mas meta posible:
        # ingerir la conversacion en la que se escribe este ingestor.) Se
        # detecta por el sessionId del entorno, o -- si no lo hay -- porque el
        # fichero cambia de tamaño al leerlo.
        if (activa and _id_de(j) == activa) or _esta_creciendo(j):
            stats["activa_omitida"] += 1
            log("  OMITIDA (sesión activa, captura parcial): %s" % j.name[:40])
            continue
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
    if stats.get("activa_omitida"):
        print("Sesión activa omitida: %d (relanza cuando la cierres para "
              "capturarla entera)" % stats["activa_omitida"])
    print("Fuente cruda preservada en MERGED_VAULT/%s" % BANCO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
