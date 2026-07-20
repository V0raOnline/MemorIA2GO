#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MemorIA2GO.py — Orquestador para migración de contexto desde ChatGPT.

Flujo:
  Paso 1  → split_chatgpt_export.py   (todo export VALIDO y PENDIENTE en
                                        exports_dir → RAW_VAULT/Conversaciones,
                                        con --keep-versions: nunca sobrescribe nada)
  Paso 2  → vault_merge.py            (RAW_VAULT → MERGED_VAULT, fusiona variantes
                                        sin perder ni duplicar mensajes)
  Paso 3  → project_organizer.py      (MERGED_VAULT → PRJ_VAULT, organiza por proyecto)

Importación incremental por defecto: exports_dir puede tener varios exports
de fechas distintas (un export es un volcado completo, no un incremental —
una conversación borrada en la cuenta simplemente desaparece de exports
futuros). Se lleva un registro de qué archivos ya se importaron
(RAW_VAULT/_exports_procesados.json) para no reprocesar cada vez, pero
--reprocess-all fuerza a reprocesar todos los exports válidos igualmente
(seguro: --keep-versions + merge por huella no duplican nada).

El banco de imágenes (IMAGE_BANK) vive siempre al mismo nivel que los vaults
(RAW_VAULT, MERGED_VAULT, PRJ_VAULT), como carpeta hermana dentro de la carpeta
base. Cada vault referencia las mismas imágenes vía un junction "_assets" — cero
duplicación de binarios, y los enlaces relativos nunca salen del vault (Obsidian
los renderiza sin problema).

Uso rápido:
  python MemorIA2GO.py
  python MemorIA2GO.py --config mi_config.yaml
  python MemorIA2GO.py --config mi_config.yaml --reprocess-all
"""

import sys
import datetime
import json
import subprocess
import time
from pathlib import Path

# Fuerza UTF-8 en stdout/stderr: sin esto, la consola legacy de Windows (cp1252)
# revienta con UnicodeEncodeError en cuanto imprime un emoji (🧙, 📦, etc.),
# algo real que le puede pasar a cualquiera cuya terminal no esté en UTF-8.
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --- Dependencia opcional: rich para output bonito ---
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
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

# --- Validacion previa (preflight) ---
try:
    from preflight import validate_export_file, validate_config, list_pending_exports, mark_processed
    HAS_PREFLIGHT = True
except ImportError:
    HAS_PREFLIGHT = False

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
    """Elimina comillas, espacios, BOM y caracteres raros que pegan los usuarios desde el explorador."""
    return raw.strip().lstrip("\ufeff").strip().strip('"').strip("'").strip()

def ask(prompt: str, default: str = "") -> str:
    if USE_RICH:
        val = Prompt.ask(prompt, default=default)
    else:
        val = input(f"{prompt} [{default}]: ").strip()
        val = val if val else default
    return sanitize_path(val)

def confirm(prompt: str, default: bool = True) -> bool:
    """Confirmación propia, sin pasar por rich.prompt.Confirm: ese componente
    fuerza y/n en inglés y no gestiona bien la entrada no interactiva (pipes).
    Aquí usamos input() plano, que acepta s/si/sí ademas de y/yes, y funciona
    igual de bien interactivo que por pipe. También se limpia un posible BOM
    inicial (\ufeff) que algunos pipes de Windows inyectan de forma invisible."""
    suffix = "[S/n]" if default else "[s/N]"
    full_prompt = f"{prompt} {suffix}: "
    if USE_RICH:
        console.print(full_prompt, end="")
    else:
        print(full_prompt, end="")
    try:
        val = input().strip().lstrip("\ufeff").strip().lower()
    except EOFError:
        val = ""
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
# Banco de imágenes: junction al mismo nivel que los vaults
# ─────────────────────────────────────────

def ensure_image_bank_junction(vault_root: Path, image_bank: Path, log_path: Path) -> Path:
    """Crea (si no existe) {vault_root}/_assets como junction hacia image_bank.
    image_bank vive como carpeta hermana de los vaults (RAW_VAULT, MERGED_VAULT,
    PRJ_VAULT), nunca dentro de uno de ellos. Idempotente y no destructivo."""
    image_bank.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    junction = vault_root / "_assets"

    if junction.exists():
        return junction

    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(image_bank)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            warn(f"No pude crear el junction de imágenes en {junction}: {result.stderr.strip()}")
            log(log_path, f"WARN junction fallido: {result.stderr.strip()}")
        else:
            log(log_path, f"Junction creado: {junction} -> {image_bank}")
    else:
        try:
            junction.symlink_to(image_bank, target_is_directory=True)
            log(log_path, f"Symlink creado: {junction} -> {image_bank}")
        except OSError as e:
            warn(f"No pude crear el symlink de imágenes en {junction}: {e}")
            log(log_path, f"WARN symlink fallido: {e}")

    return junction

# ─────────────────────────────────────────
# Helpers de resolución de rutas
# ─────────────────────────────────────────

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

    exports_dir = ask("📦 Carpeta donde guardas tus exports de ChatGPT (.zip/.json/.html) — "
                       "puede tener varios, se procesan todos los pendientes")
    while not Path(exports_dir).is_dir():
        error(f"No existe esa carpeta: {exports_dir}")
        exports_dir = ask("📦 Carpeta con tus exports de ChatGPT")

    default_vault = str(HERE / "output_vault")
    vault_path = ask("📁 Carpeta base donde viven todos los vaults (RAW/MERGED/PRJ/IMAGE_BANK)", default=default_vault)

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
        "exports_dir": Path(exports_dir),
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

        if not exports_dir or not exports_dir.is_dir() or not base_vault:
            return None

        return {
            "exports_dir": exports_dir,
            "vault_path": base_vault,
            "gizmo_map_path": gizmo_map if (gizmo_map and gizmo_map.exists()) else None,
            "by_date": get_opt(cfg, "by_month", True),
            "make_index": get_opt(cfg, "make_index", True),
            "prj_vault_name": get_opt(cfg, "prj_vault_name", "PRJ_VAULT"),
            "dry_run": get_opt(cfg, "dry_run", False),
            "keep_hashes": get_opt(cfg, "keep_hashes", False),
        }
    except Exception as e:
        warn(f"No pude cargar config YAML: {e}")
        return None

# ─────────────────────────────────────────
# Pasos del pipeline
# ─────────────────────────────────────────

def paso1_split(params: dict, image_bank: Path, log_path: Path, reprocess_all: bool = False) -> Path:
    """Procesa TODO export valido y pendiente en exports_dir hacia
    RAW_VAULT/Conversaciones. Incremental por defecto (registro en
    _exports_procesados.json); reprocess_all fuerza a repasarlos todos.
    Nunca sobrescribe: toda colisión de nombre genera una variante con
    sufijo hash (--keep-versions)."""
    rule("Paso 1 — Importar (RAW_VAULT)")

    script = HERE / "split_chatgpt_export.py"
    if not script.exists():
        error(f"No encuentro split_chatgpt_export.py en {HERE}")
        sys.exit(1)

    raw_vault = params["vault_path"] / "RAW_VAULT"

    if not HAS_PREFLIGHT:
        error("No encuentro preflight.py -- no puedo determinar que exports procesar. Abortando.")
        sys.exit(1)

    pending = list_pending_exports(params["exports_dir"], raw_vault, reprocess_all=reprocess_all)
    if not pending:
        info("No hay exports nuevos que importar -- todo al día." if not reprocess_all
             else "No hay ningún export válido en exports_dir.")
        ensure_image_bank_junction(raw_vault, image_bank, log_path)
        return raw_vault

    info(f"Exports pendientes de importar: {len(pending)} ({', '.join(p.name for p in pending)})")

    assets_junction = ensure_image_bank_junction(raw_vault, image_bank, log_path)
    conv_dir = raw_vault / "Conversaciones"
    conv_dir.mkdir(parents=True, exist_ok=True)

    procesados_ok = []
    for export_path in pending:
        info(f"\n→ Importando: {export_path.name}")
        args = [
            export_path,
            conv_dir,
            "--by-year",
            "--by-month",
            "--keep-versions",
            "--assets-dir", assets_junction,
            "--manifest", HERE / "logs",
            "--export-name", export_path.name,
        ]
        if params.get("gizmo_map_path"):
            args += ["--gizmo-map", params["gizmo_map_path"]]

        ok_flag = run_script(script, args, log_path)
        if not ok_flag:
            error(f"Fallo importando {export_path.name}. Abortando el resto de la cola.")
            sys.exit(1)
        procesados_ok.append(export_path)

    mark_processed(raw_vault, procesados_ok)

    # Registro de "ultima importacion" -- lo necesita el dashboard para calcular
    # dias transcurridos sin tener que adivinar por fecha de modificacion de archivos.
    last_import_path = raw_vault / "_last_import.json"
    with open(last_import_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.datetime.now().isoformat(),
            "exports_procesados_esta_vez": [p.name for p in procesados_ok],
        }, f, ensure_ascii=False, indent=2)

    return raw_vault

def paso2_merge(params: dict, raw_vault: Path, image_bank: Path, log_path: Path) -> Path:
    """RAW_VAULT → MERGED_VAULT: fusiona variantes por huella de mensaje,
    sin perder contenido divergente entre reimportaciones."""
    rule("Paso 2 — Fusionar sin pérdidas (MERGED_VAULT)")

    script = HERE / "vault_merge.py"
    if not script.exists():
        error(f"No encuentro vault_merge.py en {HERE}")
        sys.exit(1)

    merged_vault = params["vault_path"] / "MERGED_VAULT"
    ensure_image_bank_junction(merged_vault, image_bank, log_path)

    args = [raw_vault, merged_vault, "--merge", "--by-year", "--by-month", "--verbose"]

    ok_flag = run_script(script, args, log_path)
    if not ok_flag:
        error("Paso 2 fallido. Abortando.")
        sys.exit(1)

    return merged_vault

def paso3_organizar(params: dict, merged_vault: Path, image_bank: Path, log_path: Path):
    """Reorganiza MERGED_VAULT por Project_name en PRJ_VAULT."""
    rule("Paso 3 — Organizar por proyectos (PRJ_VAULT)")

    script = HERE / "project_organizer.py"
    if not script.exists():
        warn("No encuentro project_organizer.py — omitiendo paso 3.")
        return

    project_vault = params["vault_path"] / params.get("prj_vault_name", "PRJ_VAULT")
    project_vault.mkdir(parents=True, exist_ok=True)

    if params.get("by_date"):
        # Con by_date, la profundidad de PRJ_VAULT (proyecto/año/mes) coincide con
        # la de MERGED_VAULT (Conversaciones/año/mes) — los enlaces de imagen
        # relativos siguen resolviendo bien tras symlink/copia.
        ensure_image_bank_junction(project_vault, image_bank, log_path)
    else:
        warn("Sin organización por año/mes, los enlaces de imagen en PRJ_VAULT "
             "pueden no resolver correctamente (profundidad distinta a MERGED_VAULT).")

    args = [merged_vault, project_vault]
    if params.get("by_date"):
        args.append("--by-date")

    ok_flag = run_script(script, args, log_path)
    if not ok_flag:
        warn("Paso 3 fallido — MERGED_VAULT sigue disponible como fuente de verdad.")
        return None
    ok(f"Vault por proyectos listo en: {project_vault}")
    return project_vault

def paso4_indices(merged_vault: Path, project_vault: Path | None, log_path: Path):
    """Genera _tree_index.md (navegacion por proyecto/ano/mes),
    scaffolding_index.md (que conversacion uso que archivo adjunto) e
    _image_index.md en MERGED_VAULT y, si existe, tambien en PRJ_VAULT.
    No fatal si falla: son indices de navegacion, no datos de origen."""
    rule("Paso 4 — Indices de navegacion")

    tree_script = HERE / "tree_index.py"
    scaffold_script = HERE / "scaffolding_index.py"
    image_script = HERE / "image_index.py"

    targets = [(merged_vault, "Conversaciones")]
    if project_vault is not None:
        # PRJ_VAULT no tiene subcarpeta "Conversaciones": project_organizer.py
        # organiza directo como {proyecto}/{ano}/{mes}/nota.md desde la raiz.
        targets.append((project_vault, "."))

    for vault, conv_dir in targets:
        if tree_script.exists():
            run_script(tree_script, [vault, "--conversations-dir", conv_dir, "--max-per-month", "0"], log_path)
        else:
            warn("No encuentro tree_index.py — omitiendo indice de proyectos.")

        if scaffold_script.exists():
            run_script(scaffold_script, [vault], log_path)
        else:
            warn("No encuentro scaffolding_index.py — omitiendo indice de adjuntos.")

        if image_script.exists():
            run_script(image_script, [vault, "--conversations-dir", conv_dir], log_path)
        else:
            warn("No encuentro image_index.py — omitiendo indice de imagenes.")

    # Cache de estadisticas: se recalcula aqui, en el momento barato (batch,
    # ya hemos tocado todo el vault), para que /api/stats del launcher
    # responda al instante leyendo el cache en vez de reescanear todo el
    # frontmatter en cada peticion del dashboard.
    # Indice de temas de huerfanas: derivado y regenerable. Solo corre si hay
    # curacion (topic_map.json junto a los scripts); sin mapa, sin ruido.
    # Va ANTES que la cache de estadisticas para que esta ya recoja el
    # resumen de temas recien generado (.temas_stats.json).
    topic_map = HERE / "topic_map.json"
    cloud_script = HERE / "orphan_cloud.py"
    if topic_map.exists() and cloud_script.exists():
        run_script(cloud_script,
                   [merged_vault.parent, "--generate-topics", "--topic-map", topic_map],
                   log_path)

    stats_script = HERE / "vault_stats.py"
    if stats_script.exists():
        cache_args = [merged_vault.parent, "--write-cache"]
        if project_vault is not None:
            cache_args += ["--prj-vault-name", project_vault.name]
        run_script(stats_script, cache_args, log_path)
    else:
        warn("No encuentro vault_stats.py — omitiendo cache de estadisticas.")

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
    ap.add_argument("--from-merge", action="store_true",
                    help="Salta el paso 1 (importar) y arranca en el paso 2, reutilizando el "
                         "RAW_VAULT ya existente. Pensado para relanzar tras corregir gizmos "
                         "huerfanos con patch_gizmo_map.py sin repetir la importacion completa.")
    ap.add_argument("--reprocess-all", action="store_true",
                    help="Ignora el registro de exports ya procesados y reprocesa todos los "
                         "exports validos de exports_dir. Seguro (--keep-versions + merge por "
                         "huella no duplican nada), solo mas lento.")
    ap.add_argument("--yes", action="store_true",
                    help="No pide confirmacion de la config cargada -- la acepta directamente. "
                         "Necesario para lanzar el pipeline sin terminal interactiva (p.ej. desde launcher.py).")
    args = ap.parse_args()

    if USE_RICH:
        console.print()
        console.print(Panel(
            "[bold cyan]M3M0R·IA[/bold cyan]\n"
            "[white]Tu contexto listo para MCP / Obsidian[/white]\n"
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
            console.print(f"  [cyan]Exports: [/cyan][bright_cyan]{escape(str(params['exports_dir']))}[/bright_cyan]")
            console.print(f"  [cyan]Vault:   [/cyan][bright_cyan]{escape(str(params['vault_path']))}[/bright_cyan]")
            console.print(f"  [cyan]PRJ vault: [/cyan][bright_cyan]{escape(str(params.get('prj_vault_name', 'PRJ_VAULT')))}[/bright_cyan]")
        else:
            info(f"  Exports: {params['exports_dir']}")
            info(f"  Vault:   {params['vault_path']}")
            info(f"  PRJ vault: {params.get('prj_vault_name', 'PRJ_VAULT')}")
        if not args.yes and not confirm("[bold]¿Usar esta configuración?[/bold]", default=True):
            params = None

    if not params:
        params = wizard()

    log(log_path, f"Exports: {params['exports_dir']}")
    log(log_path, f"Vault:  {params['vault_path']}")

    image_bank = params["vault_path"] / "IMAGE_BANK"
    info(f"🖼  Banco de imágenes: {image_bank}")

    # Pipeline
    if args.from_merge:
        raw_vault = params["vault_path"] / "RAW_VAULT"
        if not raw_vault.exists():
            error(f"--from-merge requiere un RAW_VAULT existente y no lo encuentro en: {raw_vault}")
            sys.exit(1)
        rule("Paso 1 — Omitido (--from-merge, reutilizando RAW_VAULT existente)")
        ok(f"RAW_VAULT reutilizado: {raw_vault}")
    else:
        raw_vault = paso1_split(params, image_bank, log_path, reprocess_all=args.reprocess_all)

    merged_vault = paso2_merge(params, raw_vault, image_bank, log_path)
    project_vault = paso3_organizar(params, merged_vault, image_bank, log_path)
    paso4_indices(merged_vault, project_vault, log_path)

    rule("Proceso completado")
    ok(f"RAW_VAULT     → {raw_vault}")
    ok(f"MERGED_VAULT  → {merged_vault}")
    if project_vault is not None:
        ok(f"PRJ_VAULT     → {project_vault}")
    ok(f"IMAGE_BANK    → {image_bank}")

    try:
        from vault_stats import compute_stats, print_report
        rule("Resumen")
        print_report(compute_stats(params["vault_path"], params.get("prj_vault_name", "PRJ_VAULT")))
    except Exception as e:
        warn(f"No pude generar el resumen de estadisticas: {e}")

    info(f"\nLog guardado en: {log_path}")
    info("\nPróximo paso: añade la ruta del vault (MERGED_VAULT o PRJ_VAULT) al MCP config de Claude Desktop.")

    log(log_path, "Sesión finalizada correctamente.")

if __name__ == "__main__":
    main()
