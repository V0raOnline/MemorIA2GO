#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scaffolding_index.py — indice de archivos adjuntos/andamiaje ("que conversacion
uso el archivo X") encontrados en las notas del vault.

Adaptado de POC/CLI4Humans_v1.0_Release/scaffolding_index.py. El formato real
detectado en split_chatgpt_export.py es "📎 Archivo adjunto: **nombre** (tipo, ~N tokens)"
(metadata.attachments) -- se reconoce ese patron como principal. Se mantiene
tambien el patron legado "📄 Archivo cargado: **nombre**" (tether_quote, formato
de export antiguo que no se ha observado en datos reales recientes) por si
algun vault viejo lo usa.

Genera scaffolding_index.md con wikilinks a cada nota que uso ese archivo.
"""
import re
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path
import argparse
from collections import defaultdict

from tree_index import INDEX_FILENAMES, iter_markdown_files

ATTACHMENT_RE = re.compile(r"^\U0001F4CE\s*Archivo\s+adjunto:\s*\*\*(.+?)\*\*", re.MULTILINE)
LEGACY_SCAFFOLD_RE = re.compile(r"^\U0001F4C4\s*Archivo\s+cargado:\s*\*\*(.+?)\*\*", re.MULTILINE)


def scan_vault(vault_path: Path):
    """Recorre el vault buscando lineas de adjunto/andamiaje y devuelve
    {nombre_archivo: [ruta_relativa_de_nota, ...]}."""
    scaffolds = defaultdict(list)
    for md in iter_markdown_files(vault_path):
        if any(x in md.parts for x in (".obsidian", ".git", "_assets")):
            continue
        if md.name in INDEX_FILENAMES:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        names = set()
        for m in ATTACHMENT_RE.finditer(text):
            names.add(m.group(1).strip())
        for m in LEGACY_SCAFFOLD_RE.finditer(text):
            names.add(m.group(1).strip())

        for name in names:
            scaffolds[name].append(md.relative_to(vault_path))
    return scaffolds


def build_index_text(scaffolds: dict) -> str:
    lines = ["# Índice de Archivos Adjuntos\n"]
    lines.append(f"_Archivos distintos:_ **{len(scaffolds)}**\n")
    for name in sorted(scaffolds.keys(), key=str.lower):
        files = scaffolds[name]
        lines.append(f"## {name}  ({len(files)})\n")
        for f in sorted(files):
            lines.append(f"- [[{f.with_suffix('').as_posix()}]]")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Crea scaffolding_index.md con el listado de archivos adjuntos usados.")
    ap.add_argument("vault", help="Carpeta raiz del vault con notas .md")
    ap.add_argument("--out", default="scaffolding_index.md", help="Archivo de salida dentro del vault")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"Carpeta no valida: {vault}")

    scaffolds = scan_vault(vault)
    if not scaffolds:
        print("No indexable attachments found.")
        return

    index_text = build_index_text(scaffolds)
    out_path = vault / args.out
    out_path.write_text(index_text, encoding="utf-8")

    total_refs = sum(len(v) for v in scaffolds.values())
    print(f"Index generated: {out_path}")
    print(f"Distinct files detected: {len(scaffolds)}")
    print(f"References (file x note) indexed: {total_refs}")


if __name__ == "__main__":
    main()
