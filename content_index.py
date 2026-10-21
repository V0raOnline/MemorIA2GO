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


# Las miniaturas las genera una herramienta externa (no el pipeline) con una miniatura
# por imagen: `thmbnail_<nombre>.png` para casi todas, y el MISMO nombre cuando la
# original es una .webp. Se buscan en ese orden, sin distinguir mayusculas.
THUMB_PREFIJO = "thmbnail_"


def miniaturas_existentes(thumbs_dir: Optional[Path]) -> Dict[str, str]:
    """{nombre en minusculas: nombre real} de lo que hay en la carpeta de miniaturas."""
    if not thumbs_dir or not Path(thumbs_dir).is_dir():
        return {}
    return {n.lower(): n for n in os.listdir(thumbs_dir)}


def miniatura_de(fname: str, existentes: Dict[str, str]) -> Optional[str]:
    """Nombre de la miniatura de `fname`, o None si no tiene."""
    for candidata in (f"{THUMB_PREFIJO}{Path(fname).stem}.png", fname):
        real = existentes.get(candidata.lower())
        if real:
            return real
    return None


def _url(ruta: str) -> str:
    """Ruta para un enlace markdown: un espacio la cortaria."""
    return ruta.replace(" ", "%20")


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
                # Dos cosas distintas que antes se confundian en una sola
                # variable, y de ahi el bug: 'ruta' es lo que va en el enlace
                # del indice (puede llevar subcarpeta -- CLAUDE/ARTEFACTOS
                # organiza por tipo), 'fname' es el nombre pelado, que es la
                # clave del manifest y el criterio de deduplicacion.
                # Reconstruir el enlace desde fname tiraba la subcarpeta y
                # dejaba los 16 artefactos del indice apuntando a la nada.
                ruta = m.group("fname")
                fname = os.path.basename(ruta)
                if fname in seen:
                    continue
                seen.add(fname)
                es_imagen = bool(m.group("bang")) and Path(fname).suffix.lower() in IMG_EXTS
                titulo = _display_title(line, m.group("text"), fname)
                caption = _caption_for(manifest.get(fname, {}))
                items.append({"fname": fname, "ruta": ruta, "es_imagen": es_imagen,
                              "titulo": titulo, "caption": caption})
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
            "prompt": (meta.get("prompt") or "").strip().strip('"'),
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
            # it["ruta"], no it["fname"]: conserva la subcarpeta de tipo.
            rel_path = f"{bank.prefix}/{it.get('ruta') or it['fname']}".replace("\\", "/")
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


def _celda_imagen(fname: str, bank_prefix: str, thumbs_prefix: str, existentes: Dict[str, str]) -> str:
    """La miniatura enlazada al original; sin miniatura, solo el enlace (nunca el original
    incrustado: es lo que pesa)."""
    ruta = f"{bank_prefix}/{fname}"
    miniatura = miniatura_de(fname, existentes)
    if miniatura is None:
        return f"[{fname}]({_url(ruta)}) _(sin miniatura)_"
    return f"[![]({_url(thumbs_prefix + '/' + miniatura)})]({_url(ruta)})"


def collect_unreferenced(bank_dir: Path, referenced: set) -> list:
    """Imagenes que hay en la carpeta del banco y ninguna nota enlaza."""
    if not bank_dir or not Path(bank_dir).is_dir():
        return []
    return sorted(n for n in os.listdir(bank_dir)
                  if Path(n).suffix.lower() in IMG_EXTS and n not in referenced)


def generate_gallery(vault: Path, conversations_dir: str, provider_title: str, bank: BankSpec,
                     thumbs_dir: Path, thumbs_prefix: str, vault_prefix: str = "") -> dict:
    """Galeria de las imagenes de UN banco: por mes, cada conversacion con sus miniaturas
    (cada una enlaza a la imagen original) y la ruta de cada fichero como enlace.
    `vault_prefix` es la carpeta del vault de las conversaciones relativa a la raiz de
    Obsidian ('MERGED_VAULT'): la galeria vive fuera de el, asi que sus wikilinks la llevan."""
    existentes = miniaturas_existentes(thumbs_dir)
    entries = []
    for e in collect_bank_entries(vault, conversations_dir, bank):
        imagenes = [it for it in e["items"] if it["es_imagen"]]
        if imagenes:
            entries.append({**e, "items": imagenes})
    referenciadas = {it["fname"] for e in entries for it in e["items"]}
    sin_conversacion = collect_unreferenced(bank.bank_dir, referenciadas)

    por_mes: Dict[str, list] = {}
    for e in entries:
        mes = e["date"][:7] if re.match(r"[0-9]{4}-[0-9]{2}", e["date"] or "") else "sin fecha"
        por_mes.setdefault(mes, []).append(e)

    total = sum(len(e["items"]) for e in entries) + len(sin_conversacion)
    todas = [it["fname"] for e in entries for it in e["items"]] + sin_conversacion
    sin_miniatura = sum(1 for n in todas if miniatura_de(n, existentes) is None)
    resumen = f"{total} imagenes · {len(entries)} conversaciones"
    if sin_miniatura:
        resumen += f" · {sin_miniatura} sin miniatura"
    lines = [f"# {provider_title} — imagenes {bank.label.lower()}", f"_{resumen}_", "",
             "Cada miniatura abre la imagen original; debajo, la ruta del fichero.", ""]

    def tira(nombres):
        return " ".join(_celda_imagen(n, bank.prefix, thumbs_prefix, existentes) for n in nombres)

    def ubicaciones(nombres):
        return "📂 " + " · ".join(f"[{n}]({_url(bank.prefix + '/' + n)})" for n in nombres)

    for mes, es in por_mes.items():
        n = sum(len(e["items"]) for e in es)
        lines += ["<details>", f"<summary><strong>{mes} ({n})</strong></summary>", ""]
        for e in es:
            ruta = f"{vault_prefix}/{e['rel'].as_posix()}" if vault_prefix else e["rel"].as_posix()
            nombres = [it["fname"] for it in e["items"]]
            lines += [f"**{e['date'] or 'sin fecha'} — [[{ruta}|{e['titulo']}]]**", "",
                      tira(nombres), "", ubicaciones(nombres), ""]
        lines += ["</details>", ""]
    if sin_conversacion:
        lines += ["<details>", f"<summary><strong>Sin conversacion ({len(sin_conversacion)})</strong></summary>", "",
                  tira(sin_conversacion), "", ubicaciones(sin_conversacion), "", "</details>", ""]
    return {"markdown": "\n".join(lines),
            "stats": {"imagenes": total, "conversaciones": len(entries), "sin_conversacion": len(sin_conversacion),
                      "con_miniatura": total - sin_miniatura, "sin_miniatura": sin_miniatura}}


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
    lines.insert(1, f"_{resumen}_")
    return {"markdown": "\n".join(lines), "stats": stats}


def sin_triar(pendientes: list) -> list:
    """Los que siguen siendo tarea. Sin `estado` = sin triar, para no romper
    ficheros anteriores al modelo de estados.

    Las entradas ya rescatadas o descartadas se CONSERVAN en el JSON porque el
    pipeline las necesita (borrarlas hacia que el siguiente --reprocess-all las
    volviera a listar: bug real b8a9c82), pero no son tareas. Este filtro
    faltaba aqui: la UI y el backend si lo hacian y el generador de la nota se
    quedo sin enterarse cuando se anadio el modelo de estados. Listarlas pedia
    bajar a mano lo que ya estaba bajado y, peor, mantenia vivo el enlace
    externo dentro de una nota del vault -- que es justo lo que el rescate
    viene a quitar de en medio (2026-08-30)."""
    return [p for p in pendientes
            if (p.get("estado") or "sin_triar") == "sin_triar"]


def render_pendientes_note(pendientes: list, titulo: str) -> str:
    """Nota separada del indice de contenido (decision V0ra 2026-07-22):
    esto es una lista de tareas -- lo que falta descargar a mano -- no
    contenido que ya tienes archivado, asi que no comparte sitio con el
    indice real. Colapsada igual que el resto.

    Filtra aqui dentro a proposito: cualquier llamador futuro hereda el
    filtro sin tener que acordarse."""
    pendientes = sin_triar(pendientes)
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
        prompt = (p.get("prompt") or "").strip().strip('"')
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
    ap.add_argument("--galeria", action="store_true",
                     help="En vez del indice colapsable, una GALERIA de las imagenes de UN banco (el primer "
                          "--banco): miniaturas enlazadas al original. Necesita --miniaturas.")
    ap.add_argument("--miniaturas", default=None,
                     help="prefijo_del_banco=prefijo_de_sus_miniaturas (solo con --galeria): la carpeta donde "
                          "estan las miniaturas del banco, tal como va en los enlaces.")
    ap.add_argument("--out-dir", default=None,
                     help="Carpeta donde se escribe --out. Por defecto, el vault. La galeria vive junto a su "
                          "banco (CHATGPT/), no dentro del vault de conversaciones.")
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

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else vault

    if args.galeria:
        if not args.miniaturas or "=" not in args.miniaturas:
            raise SystemExit("--galeria necesita --miniaturas prefijo_del_banco=prefijo_de_las_miniaturas")
        prefijo_banco, thumbs_prefix = args.miniaturas.split("=", 1)
        banco = next((b for b in bancos if b.prefix == prefijo_banco), None)
        if banco is None:
            raise SystemExit(f"--miniaturas habla del banco '{prefijo_banco}', que no esta entre los --banco")
        thumbs_dir = base_vault / thumbs_prefix
        if not thumbs_dir.is_dir():
            raise SystemExit(f"no existe la carpeta de miniaturas: {thumbs_dir}")
        try:
            vault_prefix = vault.relative_to(base_vault).as_posix()
        except ValueError:
            vault_prefix = ""
        g = generate_gallery(vault, args.conversations_dir, args.proveedor, banco, thumbs_dir, thumbs_prefix, vault_prefix)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / args.out).write_text(g["markdown"], encoding="utf-8")
        s = g["stats"]
        print(f"Galeria generada: {out_dir / args.out}")
        print(f"  {s['imagenes']} imagenes en {s['conversaciones']} conversaciones "
              f"({s['con_miniatura']} con miniatura, {s['sin_miniatura']} sin ella, "
              f"{s['sin_conversacion']} sin conversacion)")
        return

    resultado = generate_provider_index(vault, args.conversations_dir, args.proveedor, bancos)
    out_path = out_dir / args.out
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
        # El recuento es de lo que la nota lista, no del fichero entero: si
        # dijera len(pendientes) volveria a contar las ya triadas.
        print(f"Nota de pendientes: {pend_out} ({len(sin_triar(pendientes))})")


if __name__ == "__main__":
    main()
