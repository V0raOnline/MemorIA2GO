#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tree_index.py — Índice tipo árbol por proyecto con wikilinks (Obsidian)
Agrupa: Project_name → Año → Mes → Notas (ordenadas por fecha).

Adaptado de POC/CLI4Humans_v1.0_Release/tree_index.py a la estructura actual
de MemorIA2GO. Lee el front-matter YAML tal como lo escribe split_chatgpt_export.py
y vault_merge.py (title, date, Project_name).

Uso:
  python tree_index.py RUTA_AL_VAULT
  python tree_index.py RUTA_AL_VAULT --out _tree_index.md --max-per-month 0
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
import re
import argparse
from pathlib import Path
from collections import defaultdict

MONTH_NAMES_ES = {
    "01": "01 · enero", "02": "02 · febrero", "03": "03 · marzo",
    "04": "04 · abril", "05": "05 · mayo", "06": "06 · junio",
    "07": "07 · julio", "08": "08 · agosto", "09": "09 · septiembre",
    "10": "10 · octubre", "11": "11 · noviembre", "12": "12 · diciembre",
}

DATE_RX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Archivos de indice que genera el propio pipeline y que NUNCA deben contarse
# como conversaciones -- relevante sobre todo en PRJ_VAULT, donde conv_dir='.'
# hace que estos archivos vivan en la misma carpeta que se escanea.
INDEX_FILENAMES = {"_tree_index.md", "scaffolding_index.md", "_image_index.md", "_index.md"}


def iter_markdown_files(root: Path):
    """Como root.rglob('*.md') pero robusto ante symlinks/junctions colgando.
    Bug real 2026-07-22: el junction legado _assets (RAW_VAULT|PRJ_VAULT/
    _assets -> IMAGE_BANK) quedo apuntando a una carpeta ya borrada tras
    migrar su contenido a la taxonomia por proveedor/tipo, y Path.rglob()
    revienta con FileNotFoundError en cuanto lo pisa -- especialmente grave
    en PRJ_VAULT, donde conv_dir='.' hace que el escaneo arranque justo en
    la raiz del vault, al mismo nivel que el junction. os.walk() con
    onerror silencioso YA es robusto a esto (por eso tree_index.py nunca
    tuvo el bug), pero se poda ademas cualquier symlink/junction de
    dirnames antes de que os.walk baje a el: ni falta que hace explorarlo
    en busca de notas .md, esten rotos o no."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for fn in filenames:
            if fn.endswith(".md"):
                yield Path(dirpath) / fn


def read_frontmatter(path: Path) -> dict:
    """Lectura minima de front-matter YAML sin dependencias externas."""
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not txt.startswith("---"):
        return {}

    lines = txt.splitlines()
    if len(lines) < 3:
        return {}

    fm_lines = []
    ended = False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            ended = True
            break
        fm_lines.append(lines[i])
    if not ended:
        return {}

    fm = {}
    for raw in fm_lines:
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1].strip()
        fm[k] = v
    return fm


def infer_date_from_any(path: Path, title: str) -> str:
    m = DATE_RX.search(path.stem)
    if m:
        return "-".join(m.groups())
    m = DATE_RX.search(title or "")
    if m:
        return "-".join(m.groups())
    return "0000-00-00"


def to_wikilink(rel_md_path: Path, title: str) -> str:
    without_ext = rel_md_path.with_suffix("").as_posix()
    alias = title if title else rel_md_path.stem
    alias = alias.replace("|", "¦")
    return f"[[{without_ext}|{alias}]]"


def collect_notes(vault_root: Path, conversations_dir: str) -> list:
    base = vault_root / conversations_dir
    out = []
    for root, _, files in os.walk(base):
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            if fn in INDEX_FILENAMES:
                continue
            p = Path(root) / fn
            fm = read_frontmatter(p)
            project = (fm.get("Project_name") or "none").strip()
            title = (fm.get("title") or p.stem).strip()
            date = (fm.get("date") or "").strip()
            if not DATE_RX.match(date):
                date = infer_date_from_any(p, title)

            y, m, d = (date[0:4], date[5:7], date[8:10]) if len(date) >= 10 else ("0000", "00", "00")
            rel = p.relative_to(vault_root)
            out.append({
                "project": project or "none", "title": title, "date": date,
                "year": y, "month": m, "day": d, "rel": rel,
            })
    out.sort(key=lambda r: (r["date"], r["title"].lower()), reverse=True)
    return out


def group_by_project_year_month(rows: list):
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    counts = defaultdict(int)
    for r in rows:
        tree[r["project"]][r["year"]][r["month"]].append(r)
        counts[r["project"]] += 1
    return tree, counts


def render_markdown(tree, counts, max_per_month: int, conversations_dir: str) -> str:
    lines = []
    total_projects = len(tree)
    total_notes = sum(counts.values())

    lines.append("# Índice por Proyecto\n")
    lines.append(f"_Subcarpeta:_ `{conversations_dir}`  ·  _Proyectos:_ **{total_projects}**  ·  _Notas:_ **{total_notes}**\n")

    for proj in sorted(tree.keys(), key=lambda s: s.lower()):
        n = counts.get(proj, 0)
        lines.append(f"\n## {proj}  ({n})\n")

        for year in sorted(tree[proj].keys()):
            lines.append(f"\n### {year}\n")
            for month in sorted(tree[proj][year].keys()):
                month_label = MONTH_NAMES_ES.get(month, month)
                lines.append(f"\n#### {month_label}\n")

                notes = tree[proj][year][month]
                notes.sort(key=lambda r: (r['date'], r['title'].lower()))

                shown = 0
                for r in notes:
                    if max_per_month and shown >= max_per_month:
                        break
                    link = to_wikilink(r["rel"], r["title"])
                    lines.append(f"- {r['date']} — {link}")
                    shown += 1

                if max_per_month and len(notes) > max_per_month:
                    lines.append(f"- … ({len(notes) - max_per_month} más en este mes)")

    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Genera un arbol de navegacion por Project_name (wikilinks Obsidian).")
    ap.add_argument("vault", help="Ruta al vault (raiz que contiene la carpeta de conversaciones)")
    ap.add_argument("--out", default="_tree_index.md", help="Archivo de salida dentro del vault")
    ap.add_argument("--max-per-month", type=int, default=0, help="Limite de notas por mes (0 = sin limite)")
    ap.add_argument("--conversations-dir", default="Conversations", help="Subcarpeta a escanear dentro del vault")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"No existe la carpeta del vault: {vault}")

    rows = collect_notes(vault, args.conversations_dir)
    tree, counts = group_by_project_year_month(rows)
    md = render_markdown(tree, counts, args.max_per_month, args.conversations_dir)

    out_path = vault / args.out
    out_path.write_text(md, encoding="utf-8")
    print(f"Index generated: {out_path}")
    print(f"Projects: {len(tree)}  ·  Notes: {sum(counts.values())}")


if __name__ == "__main__":
    main()
