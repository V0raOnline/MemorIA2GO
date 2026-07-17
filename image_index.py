#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
image_index.py — Indice navegable de imagenes, agrupado por conversacion,
con miniatura incrustada y metadatos (prompt de DALL-E, dimensiones, nombre
de adjunto original) leidos de _image_manifest.json.

Uso:
  python image_index.py RUTA_AL_VAULT
  python image_index.py RUTA_AL_VAULT --conversations-dir .   (para PRJ_VAULT)
"""
import argparse
import os
import re
from pathlib import Path
from typing import Dict

from tree_index import read_frontmatter, INDEX_FILENAMES

IMG_LINK_RE = re.compile(r"!\[\]\(([^)]+)\)")


def load_manifest(vault_path: Path) -> Dict[str, dict]:
    manifest_path = vault_path / "_assets" / "_image_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        import json
        with open(manifest_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def caption_for(fname: str, meta: dict) -> str:
    if not meta:
        return ""
    parts = []
    origen = meta.get("origen")
    if origen == "dalle":
        parts.append("Generada con DALL·E")
    elif origen == "subida":
        parts.append("Subida")
    w, h = meta.get("width"), meta.get("height")
    if w and h:
        parts.append(f"{w}×{h}")
    adj = meta.get("adjunto_nombre")
    if adj and adj != fname:
        parts.append(f"adjunto original: {adj}")
    line = " · ".join(parts)
    prompt = meta.get("prompt")
    if prompt:
        p = prompt.strip().replace("\n", " ")
        if len(p) > 300:
            p = p[:300] + "..."
        line += f'\n> "{p}"'
    return line


def collect_entries(vault_path: Path, conversations_dir: str, manifest: Dict[str, dict]) -> list:
    conv_base = vault_path if conversations_dir == "." else vault_path / conversations_dir
    entries = []
    if not conv_base.exists():
        return entries

    for f in conv_base.rglob("*.md"):
        if f.name in INDEX_FILENAMES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        links = IMG_LINK_RE.findall(text)
        if not links:
            continue

        fm = read_frontmatter(f)
        title = (fm.get("title") or f.stem).strip()
        date = (fm.get("date") or "").strip()

        images = []
        seen = set()
        for link in links:
            fname = os.path.basename(link)
            if fname in seen:
                continue
            seen.add(fname)
            meta = manifest.get(fname, {})
            images.append((fname, meta))

        entries.append({
            "rel": f.relative_to(vault_path).with_suffix(""),
            "title": title,
            "date": date,
            "images": images,
        })

    entries.sort(key=lambda e: (e["date"], e["title"].lower()), reverse=True)
    return entries


def render_markdown(entries: list) -> str:
    total_images = sum(len(e["images"]) for e in entries)
    lines = ["# Índice de Imágenes\n"]
    lines.append(f"_Conversaciones con imágenes:_ **{len(entries)}**  ·  _Referencias de imagen:_ **{total_images}**\n")

    for e in entries:
        link = f"[[{e['rel'].as_posix()}|{e['title']}]]"
        date_str = e["date"] or "sin fecha"
        lines.append(f"\n## {date_str} — {link}\n")
        for fname, meta in e["images"]:
            lines.append(f"![](_assets/{fname})")
            cap = caption_for(fname, meta)
            if cap:
                lines.append(f"*{cap}*")
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Genera un indice navegable de imagenes por conversacion.")
    ap.add_argument("vault", help="Ruta al vault")
    ap.add_argument("--out", default="_image_index.md", help="Archivo de salida dentro del vault")
    ap.add_argument("--conversations-dir", default="Conversaciones", help="Subcarpeta a escanear")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"No existe la carpeta del vault: {vault}")

    manifest = load_manifest(vault)
    entries = collect_entries(vault, args.conversations_dir, manifest)

    if not entries:
        print("No se encontraron imagenes incrustadas en ninguna nota.")
        return

    md = render_markdown(entries)
    out_path = vault / args.out
    out_path.write_text(md, encoding="utf-8")

    total_images = sum(len(e["images"]) for e in entries)
    print(f"Indice generado: {out_path}")
    print(f"Conversaciones con imagenes: {len(entries)}  ·  Referencias de imagen: {total_images}")


if __name__ == "__main__":
    main()
