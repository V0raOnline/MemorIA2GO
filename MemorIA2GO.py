#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MemorIA2GO.py — Orquestador simplificado para migración de contexto desde ChatGPT.

Flujo:
  Paso 1 → split_chatgpt_export.py   (ZIP/JSON/HTML → .md con frontmatter)
  Paso 2 → project_organizer.py      (organiza vault por Project_name)

Uso rápido:
  python MemorIA2GO.py
  python MemorIA2GO.py --config mi_config.yaml
"""

import sys
import datetime
import subprocess
import time
from pathlib import Path

# --- Dependencia opcional: rich para output bonito ---
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    console = Console()
    USE_RICH = True
except ImportError:
    USE_RICH = False

# --- Config loader del ecosistema ---
try:
    from config_loader import load_config, get_path, get_opt
    HAS_CONFIG_LOADER = True
except ImportError:
    HAS_CONFIG_LOADER = False

HERE = Path(__file__).resolve().parent

# ─────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────

def info(msg: str):
    if USE_RICH:
        console.print(f"[cyan]{msg}[/cyan]")
    else:
        print(msg)

def ok(msg: str):
    if USE_RICH:
        console.print(f"[green bold]✓ {msg}[/green bold]")
    else:
        print(f"✓ {msg}")

def warn(msg: str):
    if USE_RICH:
        console.print(f"[yellow]⚠ {msg}[/yellow]")
    else:
        print(f"⚠ {msg}")

def error(msg: str):
    if USE_RICH:
        console.print(f"[red bold]✗ {msg}[/red bold]")
    else:
        print(f"✗ {msg}")

def sanitize_path(raw: str) -> str:
    """Elimina comillas, espacios y caracteres raros que pegan los usuarios desde el explorador."""
    return raw.strip().strip('"').strip("'").strip()

def ask(prompt: str, default: str = "") -> str:
    if USE_RICH:
        val = Prompt.ask(prompt, default=default)
    else:
        val = input(f"{prompt} [{default}]: ").strip()
        val = val if val else default
    return sanitize_path(val)

def confirm(prompt: str, default: bool = True) -> bool:
    if USE_RICH:
        return Confirm.ask(prompt, default=default)
    val = input(f"{prompt} [{'S/n' if default else 's/N'}]: ").strip().lower()
    if not val:
        return default
    return val in ("s", "si", "sí", "y", "yes")

def rule(title: str = ""):
    if USE_RICH:
        console.rule(f"[bold magenta]{title}[/bold magenta]")
    else:
        print(f"\n{'─' * 50}  {title}")

# ─────────────────────────────────────────
# Logging
# ─────────────────────────────────────────

def init_logger() -> Path:
    logs_dir = HERE / "logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    log_path = logs_dir / f"memoria2go_{ts}.log"
    log_path.touch(exist_ok=True)
    return log_path

def log(log_path: Path, msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

# ─────────────────────────────────────────
# Ejecución de scripts
# ─────────────────────────────────────────

def run_script(script: Path, args: list, log_path: Path) -> bool:
    cmd = [sys.executable, str(script)] + [str(a) for a in args]
    info(f"  → {' '.join(cmd)}")
    log(log_path, f"CMD: {' '.join(cmd)}")

    start = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"},
    )
    elapsed = round(time.time() - start, 2)

    if result.stdout.strip():
        info(result.stdout.strip())
        log(log_path, f"STDOUT: {result.stdout.strip()}")
    if result.stderr.strip():
        warn(result.stderr.strip())
        log(log_path, f"STDERR: {result.stderr.strip()}")

    if result.returncode == 0:
        ok(f"Completado en {elapsed}s")
        log(log_path, f"OK ({elapsed}s)")
        return True
    else:
        error(f"Falló con código {result.returncode}")
        log(log_path, f"FAIL código {result.returncode}")
        return False

# ─────────────────────────────────────────
# Helpers de resolución de rutas
# ─────────────────────────────────────────

def resolve_export(raw: str) -> Path | None:
    """Acepta archivo directo o carpeta. Si es carpeta, busca el .zip/.json/.html más reciente."""
    p = Path(raw)
    if p.is_file() and p.suffix.lower() in (".zip", ".json", ".html", ".htm"):
        return p
    if p.is_dir():
        for ext in ("*.zip", "*.json", "*.html", "*.htm"):
            candidates = sorted(p.glob(ext), key=lambda x: x.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0]
    return None

def resolve_gizmo_map(raw: str) -> Path | None:
    """Acepta archivo .json directo o carpeta que contenga gizmo_map.json."""
    p = Path(raw)
    if p.is_file() and p.suffix.lower() == ".json":
        return p
    if p.is_dir():
        candidate = p / "gizmo_map.json"
        if candidate.exists():
            return candidate
    return None

# ─────────────────────────────────────────
# Wizard de primera configuración
# ─────────────────────────────────────────

def wizard() -> dict:
    rule("🧙 Configuración inicial")
    info("Responde estas preguntas para configurar MemorIA2GO.\n")

    export_path = ask("📦 Ruta al archivo de exportación de ChatGPT (.zip, .json o .html) o carpeta que lo contenga")
    export_path = resolve_export(export_path)
    while export_path is None:
        error("No encuentro un archivo .zip/.json/.html válido en esa ruta.")
        raw = ask("📦 Ruta al archivo de exportación")
        export_path = resolve_export(raw)

    default_vault = str(HERE / "output_vault")
    vault_path = ask("📁 Carpeta de destino para el vault", default=default_vault)

    gizmo_map_path = ask(
        "🗺  Ruta al gizmo_map.json (mapa de proyectos) — deja vacío para omitir",
        default=""
    )
    gizmo_map_path = resolve_gizmo_map(gizmo_map_path) if gizmo_map_path else None

    prj_vault_name = ask("📂 Nombre del vault de proyectos", default="PRJ_VAULT")
    if not prj_vault_name:
        prj_vault_name = "PRJ_VAULT"

    by_date = confirm("📅 ¿Organizar notas por año/mes dentro de cada proyecto?", default=True)
    make_index = confirm("📋 ¿Generar índice de conversaciones (_index.md)?", default=True)

    return {
        "export_path": export_path,
        "vault_path": Path(vault_path),
        "gizmo_map_path": gizmo_map_path,
        "prj_vault_name": prj_vault_name,
        "by_date": by_date,
        "make_index": make_index,
        "dry_run": False,
        "keep_hashes": False,
    }

# ─────────────────────────────────────────
# Carga de config desde YAML (si existe)
# ─────────────────────────────────────────

def load_from_yaml(config_path: str | None = None) -> dict | None:
    if not HAS_CONFIG_LOADER:
        return None
    try:
        cfg = load_config(config_path)
        exports_dir = get_path(cfg, "exports_dir")
        base_vault = get_path(cfg, "base_vault")
        gizmo_map = get_path(cfg, "gizmo_map")

        # Busca el primer archivo de export disponible en exports_dir
        export_path = None
        if exports_dir and exports_dir.exists():
            for ext in ("*.zip", "*.json", "*.html"):
                candidates = sorted(exports_dir.glob(ext), key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    export_path = candidates[0]
                    break

        if not export_path or not base_vault:
            return None

        vault_path = base_vault

        return {
            "export_path": export_path,
            "vault_path": vault_path,
            "gizmo_map_path": gizmo_map if (gizmo_map and gizmo_map.exists()) else None,
            "by_date": get_opt(cfg, "by_month", True),
            "make_index": get_opt(cfg, "make_index", True),
            "prj_vault_name": get_opt(cfg, "prj_vault_name", "MEMORIA2GO_VAULT"),
            "dry_run": get_opt(cfg, "dry_run", False),
            "keep_hashes": get_opt(cfg, "keep_hashes", False),
        }
    except Exception as e:
        warn(f"No pude cargar config YAML: {e}")
        return None

# ─────────────────────────────────────────
# Pasos del pipeline
# ─────────────────────────────────────────

def paso1_split(params: dict, log_path: Path) -> Path:
    """ZIP/JSON/HTML → .md con frontmatter en vault/Conversaciones"""
    rule("Paso 1 — Importar y convertir chats")

    script = HERE / "split_chatgpt_export.py"
    if not script.exists():
        error(f"No encuentro split_chatgpt_export.py en {HERE}")
        sys.exit(1)

    raw_vault = params["vault_path"] / "Conversaciones"
    raw_vault.mkdir(parents=True, exist_ok=True)

    args = [
        params["export_path"],
        raw_vault,
        "--by-year",
        "--by-month",
        "--skip-identical",
    ]

    if params.get("gizmo_map_path"):
        args += ["--gizmo-map", params["gizmo_map_path"]]

    if params.get("make_index"):
        args.append("--make-index")

    ok_flag = run_script(script, args, log_path)
    if not ok_flag:
        error("Paso 1 fallido. Abortando.")
        sys.exit(1)

    return raw_vault

def paso2_organizar(params: dict, raw_vault: Path, log_path: Path):
    """Reorganiza vault por Project_name"""
    rule("Paso 2 — Organizar por proyectos")

    script = HERE / "project_organizer.py"
    if not script.exists():
        warn("No encuentro project_organizer.py — omitiendo paso 2.")
        return

    project_vault = params["vault_path"] / params.get("prj_vault_name", "PRJ_VAULT")
    project_vault.mkdir(parents=True, exist_ok=True)

    args = [params["vault_path"], project_vault]
    if params.get("by_date"):
        args.append("--by-date")

    ok_flag = run_script(script, args, log_path)
    if not ok_flag:
        warn("Paso 2 fallido — el vault base sigue disponible en Conversaciones/")
        return
    ok(f"Vault por proyectos listo en: {project_vault}")

# ─────────────────────────────────────────
# Paso 3: Deduplicacion
# ─────────────────────────────────────────

def paso3_dedup(params: dict, log_path: Path):
    """Limpia deltas y duplicados del PRJ_VAULT."""
    rule("Paso 3 — Deduplicar vault")

    script = HERE / "vault_dedup.py"
    if not script.exists():
        warn("No encuentro vault_dedup.py — omitiendo paso 3.")
        return

    prj_vault = params["vault_path"] / params.get("prj_vault_name", "PRJ_VAULT")
    if not prj_vault.exists():
        warn(f"No existe {prj_vault} — omitiendo dedup.")
        return

    args = [prj_vault]
    if params.get("dry_run"):
        args.append("--dry-run")
    if params.get("keep_hashes"):
        args.append("--keep-hashes")

    ok_flag = run_script(script, args, log_path)
    if not ok_flag:
        warn("Paso 3 fallido — vault disponible pero sin deduplicar.")

# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="MemorIA2GO — Migra tu historial de ChatGPT a un vault MCP-ready."
    )
    ap.add_argument("--config", default=None, help="Ruta a memoria_config.yaml (opcional)")
    ap.add_argument("--no-wizard", action="store_true", help="Fuerza uso de config YAML sin wizard")
    args = ap.parse_args()

    if USE_RICH:
        console.print()
        console.print(Panel(
            "[bold cyan]MemorIA2GO[/bold cyan]\n"
            "[white]Tu contexto de ChatGPT listo para MCP[/white]\n"
            "[bold orange1]TODO tu historial en Claude Desktop[/bold orange1]",
            border_style="bright_magenta",
            expand=False,
            padding=(0, 4),
        ))
        console.print()
    else:
        print("\n=== MemorIA2GO — Migracion de contexto ChatGPT a MCP ===\n")

    log_path = init_logger()
    log(log_path, "Sesión iniciada")

    # Intentar cargar desde YAML primero
    params = None
    if not args.no_wizard:
        params = load_from_yaml(args.config)

    if params:
        if USE_RICH:
            console.print("[cyan]Config cargada desde YAML.[/cyan]")
            console.print("[cyan]Acepta la configuración precargada o personaliza la configuración->[/cyan]")
        else:
            info("Config cargada desde YAML.")
        if USE_RICH:
            from rich.markup import escape
            console.print(f"  [cyan]Export:  [/cyan][bright_cyan]{escape(str(params['export_path']))}[/bright_cyan]")
            console.print(f"  [cyan]Vault:   [/cyan][bright_cyan]{escape(str(params['vault_path']))}[/bright_cyan]")
            console.print(f"  [cyan]PRJ vault: [/cyan][bright_cyan]{escape(str(params.get('prj_vault_name', 'PRJ_VAULT')))}[/bright_cyan]")
        else:
            info(f"  Export:  {params['export_path']}")
            info(f"  Vault:   {params['vault_path']}")
            info(f"  PRJ vault: {params.get('prj_vault_name', 'PRJ_VAULT')}")
        if not confirm("[bold]¿Usar esta configuración?[/bold]", default=True):
            params = None

    if not params:
        params = wizard()

    log(log_path, f"Export: {params['export_path']}")
    log(log_path, f"Vault:  {params['vault_path']}")

    # Pipeline
    raw_vault = paso1_split(params, log_path)
    paso2_organizar(params, raw_vault, log_path)
    paso3_dedup(params, log_path)

    rule("Proceso completado")
    ok(f"Vault disponible en: {params['vault_path']}")
    info(f"Log guardado en:    {log_path}")
    info("\nPróximo paso: añade la ruta del vault al MCP config de Claude Desktop.")

    log(log_path, "Sesión finalizada correctamente.")

if __name__ == "__main__":
    main()
