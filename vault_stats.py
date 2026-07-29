#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault_stats.py — Calcula estadisticas de un base_vault de MemorIA2GO:
notas por vault, fecha mas antigua/moderna, imagenes, tamano en disco,
dias desde la ultima importacion.

Pensado para dos usos:
- CLI: `python vault_stats.py RUTA_BASE_VAULT` imprime un informe legible.
- Modulo: `compute_stats(Path(...))` devuelve un dict, listo para servir
  como JSON desde el futuro launcher web.

No duplica el parseo de front-matter: reutiliza read_frontmatter y DATE_RX
de tree_index.py, que ya estan probados contra datos reales.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
from typing import Optional

from tree_index import read_frontmatter, DATE_RX, INDEX_FILENAMES, iter_markdown_files


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def compute_single_vault_stats(vault_path: Path, conversations_dir: str) -> dict:
    """conversations_dir='.' si las notas cuelgan directo de vault_path (caso
    PRJ_VAULT); 'Conversaciones' si viven en esa subcarpeta (RAW/MERGED)."""
    conv_base = vault_path if conversations_dir == "." else vault_path / conversations_dir

    total_size = 0
    if vault_path.exists():
        # os.walk (no Path.rglob): un junction colgando (p.ej. _assets tras
        # la migracion de bancos 2026-07-22) hace que rglob reviente con
        # FileNotFoundError en cuanto lo pisa. os.walk con onerror silencioso
        # ya es robusto por si solo, pero se poda igual por claridad -- nunca
        # queremos contar bytes de un banco de assets compartido aqui.
        for dirpath, dirnames, filenames in os.walk(vault_path, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink() and d != "_assets"]
            for fn in filenames:
                fpath = Path(dirpath) / fn
                try:
                    total_size += fpath.stat().st_size
                except OSError:
                    pass

    note_count = 0
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    por_mes: dict = {}
    por_proyecto: dict = {}
    por_proveedor: dict = {}
    if conv_base.exists():
        for f in iter_markdown_files(conv_base):
            if f.name in INDEX_FILENAMES:
                continue
            note_count += 1
            fm = read_frontmatter(f)
            d = (fm.get("date") or "").strip()
            if DATE_RX.match(d):
                if min_date is None or d < min_date:
                    min_date = d
                if max_date is None or d > max_date:
                    max_date = d
                mes = d[:7]
            else:
                mes = "no date"
            por_mes[mes] = por_mes.get(mes, 0) + 1
            # Notas anteriores al multi-proveedor no traen provider: son de
            # ChatGPT por definicion (el campo nacio con los adaptadores).
            prov = (fm.get("provider") or "chatgpt").strip()
            por_proveedor[prov] = por_proveedor.get(prov, 0) + 1
            if conversations_dir == ".":
                rel = f.relative_to(conv_base)
                proyecto = rel.parts[0] if len(rel.parts) > 1 else "(sin proyecto)"
                por_proyecto[proyecto] = por_proyecto.get(proyecto, 0) + 1

    result = {
        "existe": vault_path.exists(),
        "notas": note_count,
        "fecha_mas_antigua": min_date,
        "fecha_mas_moderna": max_date,
        "tamano_bytes": total_size,
        "tamano_legible": human_size(total_size),
        # {"AAAA-MM": n_notas, ..., "sin fecha": n} ordenado; "sin fecha" queda al final
        "notas_por_mes": dict(sorted(por_mes.items())),
        "notas_por_proveedor": dict(sorted(por_proveedor.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    if conversations_dir == ".":
        # Solo tiene sentido en vaults organizados por proyecto (PRJ_VAULT)
        result["notas_por_proyecto"] = dict(
            sorted(por_proyecto.items(), key=lambda kv: (-kv[1], kv[0]))
        )
    return result


def _count_dir(path: Path) -> "tuple[int, int]":
    """(num_archivos, bytes) de un directorio plano, sin bajar a
    subcarpetas, excluyendo manifest/ficheros ocultos (prefijo _)."""
    if not path.exists():
        return 0, 0
    files = [f for f in path.iterdir() if f.is_file() and not f.name.startswith("_")]
    return len(files), sum(f.stat().st_size for f in files)


# Bancos fijos por proveedor (taxonomia 2026-07-22, ver CONTEXT.md seccion 3):
# (ruta relativa a base_vault, etiqueta legible). Claude no esta aqui porque
# sus subcarpetas (markdown/html/codigo/...) son dinamicas por tipo -- se
# recorren directamente en compute_asset_stats.
ASSET_BANKS = {
    "chatgpt": [("CHATGPT/GENERADAS", "generadas"), ("CHATGPT/ADJUNTOS", "adjuntos")],
    "grok": [("GROK/ADJUNTOS", "adjuntos"), ("GROK/GENERADAS_IMAGEN", "generadas (imagen)"),
             ("GROK/GENERADAS_VIDEO", "generadas (video)")],
}


def compute_asset_stats(base_vault: Path) -> dict:
    """Reemplaza al viejo compute_image_bank_stats (media IMAGE_BANK, vacio
    a proposito desde la migracion de taxonomia). Cuenta los 6 bancos reales
    -- generadas/adjuntos por proveedor, mas los artefactos de Claude por
    tipo -- con total agregado y desglose por proveedor."""
    base_vault = Path(base_vault)
    por_proveedor: dict = {}
    total_items = 0
    total_bytes = 0

    for proveedor, bancos in ASSET_BANKS.items():
        detalle = []
        items = 0
        size = 0
        for rel, etiqueta in bancos:
            n, b = _count_dir(base_vault / rel)
            detalle.append({"etiqueta": etiqueta, "items": n})
            items += n
            size += b
        por_proveedor[proveedor] = {"items": items, "bytes": size, "detalle": detalle}
        total_items += items
        total_bytes += size

    claude_dir = base_vault / "CLAUDE" / "ARTEFACTOS"
    detalle = []
    items = 0
    size = 0
    if claude_dir.exists():
        for sub in sorted(p for p in claude_dir.iterdir() if p.is_dir()):
            n, b = _count_dir(sub)
            if n:
                detalle.append({"etiqueta": sub.name, "items": n})
            items += n
            size += b
    por_proveedor["claude"] = {"items": items, "bytes": size, "detalle": detalle}
    total_items += items
    total_bytes += size

    return {
        "total_items": total_items,
        "total_bytes": total_bytes,
        "tamano_legible": human_size(total_bytes),
        "por_proveedor": por_proveedor,
    }


def compute_last_import(raw_vault: Path) -> Optional[dict]:
    path = raw_vault / "_last_import.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        ts = datetime.datetime.fromisoformat(data["timestamp"])
        dias = (datetime.datetime.now() - ts).days
        return {
            "timestamp": data["timestamp"],
            "dias_transcurridos": dias,
            "export_path": data.get("export_path"),
        }
    except Exception:
        return None


def compute_gizmos_pendientes(raw_vault: Path) -> int:
    path = raw_vault / "_gizmos_pendientes.json"
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return len(data)
    except Exception:
        return 0


def compute_stats(base_vault: Path, prj_vault_name: str = "PRJ_VAULT") -> dict:
    base_vault = Path(base_vault)
    raw_vault = base_vault / "RAW_VAULT"
    merged_vault = base_vault / "MERGED_VAULT"
    project_vault = base_vault / prj_vault_name

    # Resumen de temas escrito por orphan_cloud al generar el indice
    # (tolerante: sin indice generado, sin seccion de temas)
    temas_stats = None
    try:
        temas_stats = json.loads(
            (merged_vault / "_Temas" / ".temas_stats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    return {
        "base_vault": str(base_vault),
        "vaults": {
            "RAW_VAULT": compute_single_vault_stats(raw_vault, "Conversaciones"),
            "MERGED_VAULT": compute_single_vault_stats(merged_vault, "Conversaciones"),
            prj_vault_name: compute_single_vault_stats(project_vault, "."),
        },
        "assets": compute_asset_stats(base_vault),
        "ultima_importacion": compute_last_import(raw_vault),
        "gizmos_pendientes": compute_gizmos_pendientes(raw_vault),
        "temas": temas_stats,
        "calculado": datetime.datetime.now().isoformat(timespec="seconds"),
    }


CACHE_FILENAME = ".m3m0ria_stats.json"


def cache_path(base_vault: Path) -> Path:
    return Path(base_vault) / CACHE_FILENAME


def save_cache(base_vault: Path, stats: dict) -> Path:
    """Vuelca las estadisticas a un cache junto al base_vault (el punto
    inicial del nombre lo oculta de Obsidian). Escritura atomica via tmp +
    replace: un corte a mitad nunca deja un JSON corrupto a medias."""
    p = cache_path(base_vault)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    tmp.replace(p)
    return p


def load_cache(base_vault: Path) -> Optional[dict]:
    """Lee el cache si existe; None si falta o esta corrupto. El cache nunca
    es fuente unica de verdad: ante cualquier duda, el llamante recalcula."""
    p = cache_path(base_vault)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def print_report(stats: dict):
    print(f"Base vault: {stats['base_vault']}\n")

    ui = stats.get("ultima_importacion")
    if ui:
        print(f"Last import: {ui['dias_transcurridos']} day(s) ago ({ui['timestamp']})")
    else:
        print("Last import: no record (step 1 never ran with this version)")

    if stats.get("gizmos_pendientes"):
        print(f"Unnamed gizmos: {stats['gizmos_pendientes']}")

    print()
    for name, v in stats["vaults"].items():
        if not v["existe"]:
            print(f"{name}: does not exist yet")
            continue
        rango = f"{v['fecha_mas_antigua']} -> {v['fecha_mas_moderna']}" if v["fecha_mas_antigua"] else "no dates"
        print(f"{name}: {v['notas']} notes | {rango} | {v['tamano_legible']}")

    a = stats["assets"]
    print(f"\nAssets: {a['total_items']} total | {a['tamano_legible']}")
    for proveedor, v in a["por_proveedor"].items():
        detalle = " · ".join(f"{d['items']} {d['etiqueta']}" for d in v["detalle"] if d["items"])
        print(f"  {proveedor}: {v['items']} ({detalle or 'no content'})")


def main():
    ap = argparse.ArgumentParser(description="Estadisticas de un base_vault de MemorIA2GO.")
    ap.add_argument("base_vault")
    ap.add_argument("--prj-vault-name", default="PRJ_VAULT")
    ap.add_argument("--json", action="store_true", help="Imprime JSON crudo en vez del informe legible")
    ap.add_argument("--write-cache", action="store_true",
                    help="Escribe las estadisticas en el cache junto al base_vault (usado por el paso 4 del pipeline)")
    args = ap.parse_args()

    stats = compute_stats(Path(args.base_vault), args.prj_vault_name)

    if args.write_cache:
        p = save_cache(Path(args.base_vault), stats)
        print(f"Statistics cache written: {p}")

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()
