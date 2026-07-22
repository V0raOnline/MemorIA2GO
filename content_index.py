#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
content_index.py — Indice de contenido por proveedor: UN archivo por
proveedor (ChatGPT/Claude/Grok), con una rama colapsada por banco de
assets (generadas/adjuntos/artefactos...) y cada conversacion tambien
colapsada dentro. Usa <details>/<summary> HTML nativo, que Obsidian
renderiza colapsado por defecto sin plugins.

Decision V0ra 2026-07-22: antes eran hasta 3-4 archivos por proveedor
(uno por banco), cada uno un muro de texto plano con todo desplegado.
Ahora es uno por proveedor, colapsado, legible de un vistazo.

Reemplaza a image_index.py para el uso en el pipeline (paso4_indices),
que se queda como modulo standalone/testeado pero ya no se invoca ahi.
Dos diferencias clave frente a image_index.py:
  - Combina VARIOS bancos en un solo archivo de salida (una rama <details>
    por banco), no uno por banco.
  - Entiende tanto enlaces de imagen ![](...) como enlaces de archivo
    [texto](...) -- CLAUDE/ARTEFACTOS solo usa la segunda forma (no son
    imagenes), GROK/ADJUNTOS mezcla ambas segun el tipo de archivo.

Uso:
  python content_index.py MERGED_VAULT --conversations-dir Conversaciones \\
      --proveedor "ChatGPT" --out _index_chatgpt.md \\
      --banco "CHATGPT/GENERADAS:Generadas" \\
      --banco "CHATGPT/ADJUNTOS:Adjuntos"
"""
import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from tree_index import read_frontmatter, INDEX_FILENAMES, iter_markdown_files

IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Linea completa que produce render_claude_artifact_tokens (split_chatgpt_
# export.py): "🧩 Artefacto: **Titulo** → [fname](CLAUDE/ARTEFACTOS/...)".
# El enlace en si solo trae el nombre de fichero (hash) como texto, no un
# titulo legible -- este patron recupera el titulo real cuando esta linea
# esta presente. Sin el, se degrada al texto del enlace o al nombre de
# fichero embellecido.
ARTIFACT_TITLE_RE = re.compile(r"Artefacto:\s*\*\*(?P<title>[^*]+)\*\*")


class BankSpec(NamedTuple):
    prefix: str       # p.ej. "CHATGPT/GENERADAS" -- tal cual aparece en los enlaces
    label: str         # p.ej. "Generadas" -- texto de la rama colapsada
    bank_dir: Optional[Path] = None  # por defecto: vault/prefix
    catalog: bool = False  # True: banco SIN enlaces en ninguna nota (media_posts de
    # Grok/Imagine son root-level, no viven en ninguna conversacion) -- se indexa
    # directo desde el manifest/carpeta, no cruzando con notas.


def _link_re(prefix: str) -> "re.Pattern[str]":
    """Casa tanto ![](prefix/...) como [texto](prefix/...) -- ver docstring
    del modulo. El grupo 'bang' distingue cual de los dos era."""
    return re.compile(r"(?P<bang>!)?\[(?P<text>[^\]]*)\]\(" + re.escape(prefix) + r"/(?P<fname>[^)]+)\)")


def _display_title(line: str, link_text: str, fname: str) -> str:
    m = ARTIFACT_TITLE_RE.search(line)
    if m:
        return m.group("title").strip()
    if link_text.strip():
        return link_text.strip()
    # Sin texto de enlace (imagenes: ![](...) siempre trae texto vacio) ni
    # patron de artefacto: embellecer el nombre de fichero como ultimo recurso.
    stem = Path(fname).stem
    return stem.replace("-", " ").replace("_", " ").strip() or fname


def _load_manifest(bank_dir: Path) -> Dict[str, dict]:
    p = bank_dir / "_image_manifest.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _caption_for(meta: dict) -> str:
    if not meta:
        return ""
    parts = []
    origen = meta.get("origen")
    if origen in ("generada", "dalle"):
        parts.append("Generada")
    elif origen == "subida":
        parts.append("Subida")
    w, h = meta.get("width"), meta.get("height")
    if w and h:
        parts.append(f"{w}×{h}")
    return " · ".join(parts)


def collect_bank_entries(vault: Path, conversations_dir: str, bank: BankSpec) -> list:
    """Una entrada por conversacion que referencia este banco, con la lista
    de items (fname, es_imagen, titulo, caption) encontrados en ella."""
    conv_base = vault if conversations_dir == "." else vault / conversations_dir
    link_re = _link_re(bank.prefix)
    bank_dir = bank.bank_dir or (vault / bank.prefix)
    manifest = _load_manifest(bank_dir)

    entries = []
    if not conv_base.exists():
        return entries

    for f in iter_markdown_files(conv_base):
        if f.name in INDEX_FILENAMES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        items = []
        seen = set()
        for line in text.splitlines():
            for m in link_re.finditer(line):
                fname = os.path.basename(m.group("fname"))
                if fname in seen:
                    continue
                seen.add(fname)
                es_imagen = bool(m.group("bang")) and Path(fname).suffix.lower() in IMG_EXTS
                titulo = _display_title(line, m.group("text"), fname)
                caption = _caption_for(manifest.get(fname, {}))
                items.append({"fname": fname, "es_imagen": es_imagen, "titulo": titulo, "caption": caption})
        if not items:
            continue

        fm = read_frontmatter(f)
        entries.append({
            "rel": f.relative_to(vault).with_suffix(""),
            "titulo": (fm.get("title") or f.stem).strip(),
            "date": (fm.get("date") or "").strip(),
            "items": items,
        })

    entries.sort(key=lambda e: (e["date"], e["titulo"].lower()), reverse=True)
    return entries


def collect_catalog_entries(bank: BankSpec, vault: Path) -> list:
    """Para bancos sin enlace en ninguna nota (media_posts de Grok/Imagine):
    lista directa desde el manifest, ordenada por create_time cuando lo
    trae (catch-up 2026-07-22 en process_grok_media_posts; las entradas
    extraidas antes de ese catch-up no lo tienen, van al final)."""
    bank_dir = bank.bank_dir or (vault / bank.prefix)
    manifest = _load_manifest(bank_dir)
    items = []
    for fname, meta in manifest.items():
        if not (bank_dir / fname).exists():
            continue
        items.append({
            "fname": fname,
            "es_imagen": Path(fname).suffix.lower() in IMG_EXTS,
            "prompt": (meta.get("prompt") or "").strip(),
            "create_time": meta.get("create_time") or "",
        })
    items.sort(key=lambda it: it["create_time"], reverse=True)
    return items


def render_catalog_branch(bank: BankSpec, items: list) -> str:
    lines = ["<details>", f"<summary><strong>{bank.label} ({len(items)})</strong></summary>", ""]
    for it in items:
        rel_path = f"{bank.prefix}/{it['fname']}".replace("\\", "/")
        fecha = it["create_time"][:10] if it["create_time"] else "fecha desconocida"
        lines.append("<details>")
        lines.append(f"<summary>{fecha} — {it['fname']}</summary>")
        lines.append("")
        if it["es_imagen"]:
            lines.append(f"![]({rel_path})")
        else:
            lines.append(f"📄 [{it['fname']}]({rel_path})")
        if it["prompt"]:
            lines.append(f'> "{it["prompt"]}"')
        lines.append("")
        lines.append("</details>")
        lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def render_bank_branch(bank: BankSpec, entries: list) -> str:
    total_items = sum(len(e["items"]) for e in entries)
    lines = [f"<details>", f"<summary><strong>{bank.label} ({total_items})</strong></summary>", ""]
    for e in entries:
        link = f"[[{e['rel'].as_posix()}|{e['titulo']}]]"
        date_str = e["date"] or "sin fecha"
        lines.append("<details>")
        lines.append(f"<summary>{date_str} — {link}</summary>")
        lines.append("")
        for it in e["items"]:
            rel_path = f"{bank.prefix}/{it['fname']}".replace("\\", "/")
            if it["es_imagen"]:
                lines.append(f"![]({rel_path})")
                if it["caption"]:
                    lines.append(f"*{it['caption']}*")
            else:
                lines.append(f"📄 [{it['titulo']}]({rel_path})")
            lines.append("")
        lines.append("</details>")
        lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def generate_provider_index(vault: Path, conversations_dir: str, provider_title: str,
                             bancos: List[BankSpec]) -> dict:
    """Funcion reutilizable (pensada tambien para el futuro boton
    'Reindexar' de Cartografia). Devuelve {"markdown": str, "stats": {...}}."""
    lines = [f"# {provider_title}", ""]
    stats = {}
    resumen_partes = []
    for bank in bancos:
        if bank.catalog:
            items = collect_catalog_entries(bank, vault)
            stats[bank.label] = {"conversaciones": None, "items": len(items)}
            resumen_partes.append(f"{len(items)} {bank.label.lower()}")
            lines.append(render_catalog_branch(bank, items))
            continue
        entries = collect_bank_entries(vault, conversations_dir, bank)
        total = sum(len(e["items"]) for e in entries)
        stats[bank.label] = {"conversaciones": len(entries), "items": total}
        resumen_partes.append(f"{total} {bank.label.lower()}")
        lines.append(render_bank_branch(bank, entries))
    resumen = " · ".join(resumen_partes) if resumen_partes else "sin contenido"
    lines.insert(1, f"_{resumen}_\n")
    return {"markdown": "\n".join(lines), "stats": stats}


def render_pendientes_note(pendientes: list, titulo: str) -> str:
    """Nota separada del indice de contenido (decision V0ra 2026-07-22):
    esto es una lista de tareas -- lo que falta descargar a mano -- no
    contenido que ya tienes archivado, asi que no comparte sitio con el
    indice real. Colapsada igual que el resto."""
    lines = [f"# {titulo}", ""]
    if not pendientes:
        lines.append("_Nada pendiente -- todo lo que el export trae ya esta extraido._")
        return "\n".join(lines)
    lines.append(f"_{len(pendientes)} generaciones sin binario en el export. El export solo trae "
                 "un enlace externo que puede caducar o pedir sesión iniciada -- descárgalas a mano "
                 "desde el enlace si te interesan; no se descargan solas._\n")
    pendientes_ordenados = sorted(pendientes, key=lambda p: p.get("create_time") or "", reverse=True)
    for p in pendientes_ordenados:
        fecha = (p.get("create_time") or "")[:10] or "fecha desconocida"
        tipo = p.get("media_type") or "?"
        prompt = (p.get("prompt") or "").strip()
        resumen = (prompt[:70] + "...") if len(prompt) > 70 else (prompt or "(sin prompt)")
        lines.append("<details>")
        lines.append(f"<summary>{fecha} — {tipo} — \"{resumen}\"</summary>")
        lines.append("")
        if prompt:
            lines.append(f'> "{prompt}"')
            lines.append("")
        link = p.get("link")
        if link:
            lines.append(f"[Ver en grok.com]({link})")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Genera un indice de contenido colapsable por proveedor.")
    ap.add_argument("vault", help="Ruta al vault a escanear (donde viven las notas)")
    ap.add_argument("--base-vault", default=None,
                     help="Raiz donde viven los bancos de assets (hermanos de RAW_VAULT/MERGED_VAULT/"
                          "PRJ_VAULT), p.ej. CHATGPT/GENERADAS cuelga de aqui. Por defecto, el propio "
                          "vault (sirve si vault YA es esa raiz, pero normalmente no lo es).")
    ap.add_argument("--conversations-dir", default="Conversaciones")
    ap.add_argument("--proveedor", required=True, help="Titulo del proveedor (ChatGPT, Claude, Grok...)")
    ap.add_argument("--out", required=True, help="Archivo de salida dentro del vault")
    ap.add_argument("--banco", action="append", default=[],
                     help="prefijo:etiqueta -- repetible, un --banco por rama con enlaces en notas. "
                          "Ejemplo: 'CHATGPT/GENERADAS:Generadas'")
    ap.add_argument("--banco-catalogo", action="append", default=[],
                     help="prefijo:etiqueta -- repetible, para bancos SIN enlace en ninguna nota "
                          "(p.ej. GROK/GENERADAS_IMAGEN: media_posts es root-level). Se lista "
                          "directo desde el manifest, no cruzando con notas.")
    ap.add_argument("--pendientes-json", default=None,
                     help="[Grok] Ruta a _pendientes_descarga.json -- genera ademas una nota aparte "
                          "(--pendientes-out) con la lista de generaciones sin binario local.")
    ap.add_argument("--pendientes-out", default=None,
                     help="Archivo de salida (dentro de vault) para la nota de pendientes.")
    ap.add_argument("--pendientes-titulo", default="Grok — pendientes de descarga")
    args = ap.parse_args()

    if not args.banco and not args.banco_catalogo:
        raise SystemExit("Hace falta al menos un --banco o --banco-catalogo")

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"No existe la carpeta del vault: {vault}")
    base_vault = Path(args.base_vault).expanduser().resolve() if args.base_vault else vault

    bancos = []
    for raw in args.banco:
        prefix, label = raw.split(":", 1)
        bancos.append(BankSpec(prefix=prefix, label=label, bank_dir=base_vault / prefix))
    for raw in args.banco_catalogo:
        prefix, label = raw.split(":", 1)
        bancos.append(BankSpec(prefix=prefix, label=label, bank_dir=base_vault / prefix, catalog=True))

    resultado = generate_provider_index(vault, args.conversations_dir, args.proveedor, bancos)
    out_path = vault / args.out
    out_path.write_text(resultado["markdown"], encoding="utf-8")

    print(f"Indice generado: {out_path}")
    for label, s in resultado["stats"].items():
        print(f"  {label}: {s['conversaciones']} conversaciones, {s['items']} items")

    if args.pendientes_json and args.pendientes_out:
        pend_path = Path(args.pendientes_json)
        pendientes = []
        if pend_path.exists():
            try:
                with open(pend_path, "r", encoding="utf-8-sig") as f:
                    pendientes = json.load(f)
            except Exception:
                pendientes = []
        nota = render_pendientes_note(pendientes, args.pendientes_titulo)
        pend_out = vault / args.pendientes_out
        pend_out.write_text(nota, encoding="utf-8")
        print(f"Nota de pendientes: {pend_out} ({len(pendientes)})")


if __name__ == "__main__":
    main()
