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
    if not (src / "Conversaciones").exists():
        raise SystemExit(f"❌ No encuentro {src}/Conversaciones")
    dst.mkdir(parents=True, exist_ok=True)

    notes = list(src.rglob("*.md"))
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
            if not link_path.exists():
                os.symlink(md, link_path)
                created += 1
        except FileExistsError:
            pass
        except OSError:
            # En Windows sin permisos de symlink, copia normal
            shutil.copy2(md, link_path)
            created += 1

    print(f"OK Enlaces creados/copias: {created}")
    print(f"Vault por proyectos listo en: {dst}")

if __name__ == "__main__":
    main()
