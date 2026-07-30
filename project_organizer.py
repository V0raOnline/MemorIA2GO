#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_organizer.py — Crea un vault alternativo por proyectos enlazando notas desde otro vault.

Uso:
    python project_organizer.py <origen> <destino> [--by-date]

Ejemplo:
    python project_organizer.py MERGED_VAULT PROJECT_VAULT --by-date
"""

import os, re, argparse, shutil
from pathlib import Path

from tree_index import iter_markdown_files

def extract_yaml_field(text: str, key: str) -> str | None:
    m = re.search(rf'^{key}:\s*["\']?([^"\n\r#]+)', text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="Vault fuente (por ejemplo MERGED_VAULT)")
    ap.add_argument("target", help="Vault destino (nuevo vault por proyectos)")
    ap.add_argument("--by-date", action="store_true", help="Subcarpetas por año/mes dentro de cada proyecto")
    args = ap.parse_args()

    src = Path(args.source).expanduser().resolve()
    dst = Path(args.target).expanduser().resolve()
    if not (src / "Conversations").exists():
        raise SystemExit(f"❌ No encuentro {src}/Conversations")
    dst.mkdir(parents=True, exist_ok=True)

    # Solo las conversaciones, no todo el vault. Bug real (2026-07-28): al
    # recorrer `src` entero se arrastraban tambien las notas GENERATED
    # (_tree_index, scaffolding_index, _index_chatgpt/claude/grok,
    # _grok_pending y todas las de _Topics/). Ninguna tiene Project_name
    # ni date, asi que caian en el cajon none/0000/00 y se refrescaban en
    # cada corrida: 24 ficheros y 1353 KB duplicados en el vault real de
    # V0ra, con sus enlaces contando doble en el grafo de Obsidian.
    # PRJ_VAULT es una vista de CONVERSACIONES por proyecto -- los indices
    # no pintan nada ahi. Filtrar por carpeta en vez de por lista de
    # nombres evita tener que acordarse de cada indice nuevo que se anada.
    notes = list(iter_markdown_files(src / "Conversations"))
    created = 0
    for md in notes:
        try:
            txt = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        project = extract_yaml_field(txt, "Project_name") or "none"
        date = extract_yaml_field(txt, "date") or "0000-00-00"
        y, m, *_ = (date.split("-") + ["00", "00"])[:2]

        out_dir = dst / project
        if args.by_date:
            out_dir = out_dir / y / m
        out_dir.mkdir(parents=True, exist_ok=True)

        link_path = out_dir / md.name
        try:
            # PRJ es una vista derivada de MERGED: refrescar SIEMPRE. El
            # 'if not exists' original dejaba copias rancias para siempre en
            # Windows sin permisos de symlink (frontmatter viejo, campeones
            # antiguos), porque la copia de la primera ejecucion nunca se
            # volvia a tocar.
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            os.symlink(md, link_path)
            created += 1
        except OSError:
            # En Windows sin permisos de symlink, copia normal (sobrescribe).
            # Si la nota esta bloqueada (p.ej. abierta en otra app), no abortar
            # el paso entero: se refrescara en la proxima pasada.
            try:
                shutil.copy2(md, link_path)
                created += 1
            except OSError:
                pass

    print(f"OK Links created/copied: {created}")
    print(f"Project vault ready at: {dst}")

if __name__ == "__main__":
    main()
