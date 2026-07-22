#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
image_index.py — Indice navegable de imagenes, agrupado por conversacion,
con miniatura incrustada y metadatos (prompt de DALL-E, dimensiones, nombre
de adjunto original) leidos de _image_manifest.json.

Generalizado 2026-07-22 (taxonomia por proveedor y tipo): un banco ya no es
siempre IMAGE_BANK -- puede ser CHATGPT/GENERADAS, CHATGPT/ADJUNTOS, etc.
--bank-prefix fija tanto el prefijo de enlace que se busca en las notas
como, por defecto, la carpeta donde vive el manifest (bank_dir = vault/
bank_prefix salvo que se pase --bank-dir explicito). El comportamiento por
defecto (sin --bank-prefix) es identico al de antes: IMAGE_BANK.

Uso:
  python image_index.py RUTA_AL_VAULT
  python image_index.py RUTA_AL_VAULT --conversations-dir .   (para PRJ_VAULT)
  python image_index.py RUTA_AL_VAULT --bank-prefix CHATGPT/GENERADAS \\
      --out _generadas_index.md --titulo "Índice de Imágenes Generadas"
"""
import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from tree_index import read_frontmatter, INDEX_FILENAMES, iter_markdown_files


def make_link_re(bank_prefix: str) -> "re.Pattern[str]":
    """Solo enlaces con el prefijo real que este pipeline usa al incrustar
    imagenes de ESTE banco (ver BankTarget.rel_prefix en
    split_chatgpt_export.py). Sin este filtro, cualquier "![](...)" pegado
    dentro de una conversacion -- ejemplos de sintaxis markdown, URLs
    externas dentro de texto citado/tether (Medium, capturas ajenas...) --
    se contaria como imagen real y apareceria como icono roto en el indice
    (bug reportado 2026-07-21: se leyo como "hemos perdido los indices"
    cuando el indice era correcto y el ruido era de siempre). Verificado
    contra el vault real: de 3331 coincidencias crudas del regex generico,
    1724 no tenian el prefijo IMAGE_BANK/ y CERO de las que si lo tenian
    apuntaban a un archivo inexistente."""
    return re.compile(r"!\[\]\(" + re.escape(bank_prefix) + r"/([^)]+)\)")


def load_manifest(bank_dir: Path, legacy_assets_fallback: Optional[Path] = None) -> Dict[str, dict]:
    """legacy_assets_fallback: solo para el banco IMAGE_BANK por defecto --
    _assets era el layout antiguo (junction dentro de cada subvault) para
    vaults sin migrar todavia. Los bancos nuevos (GENERADAS/ADJUNTOS/...)
    no tienen ese layout legado, asi que no aplica."""
    candidatos = [bank_dir / "_image_manifest.json"]
    if legacy_assets_fallback is not None:
        candidatos.append(legacy_assets_fallback / "_image_manifest.json")
    for candidato in candidatos:
        if candidato.exists():
            try:
                with open(candidato, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                return {}
    return {}


def caption_for(fname: str, meta: dict) -> tuple:
    """Devuelve (metadatos_una_linea, prompt) por separado para que el
    renderer los emita con formato distinto: metadatos en italica compacta,
    prompt en blockquote propio. Antes iban juntos y el asterisco de italica
    rompia el blockquote del prompt (bug 2026-07-20)."""
    if not meta:
        return ("", "")
    parts = []
    origen = meta.get("origen")
    if origen in ("generada", "dalle"):  # "dalle" = valor legado (manifests previos al fix 2026-07-22)
        parts.append("Generada")
    elif origen == "subida":
        parts.append("Subida")
    w, h = meta.get("width"), meta.get("height")
    if w and h:
        parts.append(f"{w}×{h}")
    adj = meta.get("adjunto_nombre")
    if adj and adj != fname:
        parts.append(f"adjunto original: {adj}")
    metadatos = " · ".join(parts)
    prompt = (meta.get("prompt") or "").strip().replace("\n", " ")
    if len(prompt) > 300:
        prompt = prompt[:300] + "..."
    return (metadatos, prompt)


def collect_entries(vault_path: Path, conversations_dir: str, manifest: Dict[str, dict],
                     link_re: "re.Pattern[str]") -> list:
    conv_base = vault_path if conversations_dir == "." else vault_path / conversations_dir
    entries = []
    if not conv_base.exists():
        return entries

    for f in iter_markdown_files(conv_base):
        if f.name in INDEX_FILENAMES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        links = link_re.findall(text)
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


def render_markdown(entries: list, bank_prefix: str, titulo: str) -> str:
    total_images = sum(len(e["images"]) for e in entries)
    lines = [f"# {titulo}\n"]
    lines.append(f"_Conversaciones con imágenes:_ **{len(entries)}**  ·  _Referencias de imagen:_ **{total_images}**\n")

    for e in entries:
        link = f"[[{e['rel'].as_posix()}|{e['title']}]]"
        date_str = e["date"] or "sin fecha"
        lines.append(f"\n## {date_str} — {link}\n")
        for fname, meta in e["images"]:
            lines.append(f"![]({bank_prefix}/{fname})")
            metadatos, prompt = caption_for(fname, meta)
            if metadatos:
                lines.append(f"*{metadatos}*")
            if prompt:
                lines.append(f'> "{prompt}"')
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def generate_index(vault: Path, conversations_dir: str, bank_prefix: str,
                    bank_dir: Optional[Path], titulo: str) -> dict:
    """Funcion reutilizable (usada tambien por el futuro boton "Reindexar"
    de Cartografia). Devuelve stats; no imprime nada."""
    bank_dir = bank_dir or (vault / bank_prefix)
    legacy_fallback = (vault / "_assets") if bank_prefix == "IMAGE_BANK" else None
    manifest = load_manifest(bank_dir, legacy_assets_fallback=legacy_fallback)
    link_re = make_link_re(bank_prefix)
    entries = collect_entries(vault, conversations_dir, manifest, link_re)
    total_images = sum(len(e["images"]) for e in entries)
    return {"entries": entries, "total_conversaciones": len(entries), "total_imagenes": total_images}


def main():
    ap = argparse.ArgumentParser(description="Genera un indice navegable de imagenes por conversacion.")
    ap.add_argument("vault", help="Ruta al vault")
    ap.add_argument("--out", default=None, help="Archivo de salida dentro del vault (por defecto: segun --bank-prefix)")
    ap.add_argument("--conversations-dir", default="Conversaciones", help="Subcarpeta a escanear")
    ap.add_argument("--bank-prefix", default="IMAGE_BANK",
                     help="Prefijo de enlace del banco a indexar (ej. CHATGPT/GENERADAS). Por defecto IMAGE_BANK.")
    ap.add_argument("--bank-dir", default=None,
                     help="Carpeta fisica donde vive _image_manifest.json de este banco. "
                          "Por defecto: {vault}/{bank-prefix}.")
    ap.add_argument("--titulo", default=None, help="Titulo del indice (por defecto segun --bank-prefix)")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"No existe la carpeta del vault: {vault}")

    bank_dir = Path(args.bank_dir).expanduser().resolve() if args.bank_dir else None
    titulo = args.titulo or f"Índice de Imágenes — {args.bank_prefix}"
    out_name = args.out or ("_image_index.md" if args.bank_prefix == "IMAGE_BANK"
                             else f"_index_{args.bank_prefix.split('/')[-1].lower()}.md")

    resultado = generate_index(vault, args.conversations_dir, args.bank_prefix, bank_dir, titulo)
    entries = resultado["entries"]

    if not entries:
        print(f"No se encontraron imagenes incrustadas en ninguna nota para el banco {args.bank_prefix}.")
        return

    md = render_markdown(entries, args.bank_prefix, titulo)
    out_path = vault / out_name
    out_path.write_text(md, encoding="utf-8")

    print(f"Indice generado: {out_path}")
    print(f"Conversaciones con imagenes: {resultado['total_conversaciones']}  ·  "
          f"Referencias de imagen: {resultado['total_imagenes']}")


if __name__ == "__main__":
    main()
