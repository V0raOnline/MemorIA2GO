#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault_merge.py — Construye un vault MERGED a partir de un vault RAW generado por
split_chatgpt_export.py con --keep-versions.

Adaptado de POC/CLI4Humans_v1.0_Release/vault_cleaner.py a la estructura actual
de MemorIA2GO (Conversaciones/ con front-matter Project_name, source_project_id,
tags, etc. y enlaces de imagen ![](...)).

Reglas:
- Agrupa todas las variantes de una misma conversación (mismo nombre base sin
  sufijo -hXXXXXXXX / -N).
- Elige "campeón" = variante con más palabras (empate: más bytes).
- Con --merge: fusiona mensajes de TODAS las variantes deduplicando por huella
  (rol + contenido normalizado), preservando el orden de aparición del campeón
  y añadiendo al final los mensajes exclusivos de otras variantes que el
  campeón no tuviera.
- Con --reverse-blocks: invierte el orden de los bloques consecutivos del mismo
  rol (conserva el orden interno usuario→asistente dentro de cada bloque).
- NUNCA borra ni modifica el RAW de entrada.

Uso:
  python vault_merge.py RAW_DIR MERGED_DIR --merge --by-year --by-month
  python vault_merge.py RAW_DIR MERGED_DIR --merge --reverse-blocks --by-year --by-month
"""
import argparse
import glob
import hashlib
import os
import re
from typing import Dict, List, Tuple

HASH_SUFFIX_RE = re.compile(r"-(h[0-9a-f]{7,8}|v\d+|t\d{12})(?:-\d+)?(?=\.md$)", re.IGNORECASE)


def normalize_text(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").strip())


def msg_fingerprint(msg: Dict[str, str]) -> str:
    role = (msg.get("role", "") or "").lower()
    norm = role + "::" + normalize_text(msg.get("content", ""))
    return hashlib.sha1(norm.encode("utf-8", errors="ignore")).hexdigest()


def group_blocks(messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    """Agrupa mensajes por TURNO completo: desde un mensaje de 'user' hasta
    justo antes del siguiente 'user' (inclusive de todo lo que haya en medio:
    Assistant, Tool, Síntesis, etc). Un turno puede legitimamente contener
    varios mensajes de Assistant seguidos (p.ej. cuando el asistente usa una
    herramienta internamente) sin que eso implique una regeneración descartada.
    Si hay mensajes antes del primer 'user', forman su propio bloque inicial."""
    blocks: List[List[Dict[str, str]]] = []
    cur: List[Dict[str, str]] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        if role == "user" and cur:
            blocks.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        blocks.append(cur)
    return blocks


def flatten_blocks(blocks: List[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for b in blocks:
        out.extend(b)
    return out


def read_note(md_path: str) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """Lee front-matter (dict plano) y mensajes (### Role\\n...) de una nota."""
    front: Dict[str, str] = {}
    messages: List[Dict[str, str]] = []
    with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()

    body = txt
    if txt.startswith("---\n"):
        end = txt.find("\n---\n", 4)
        if end != -1:
            for line in txt[4:end].splitlines():
                if not line.strip() or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                front[k.strip()] = v.strip()
            body = txt[end + 5:]

    parts = re.split(r"(?m)^###\s+([A-Za-z]+)\s*$", body)
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            role = parts[i].strip().lower()
            content = parts[i + 1].strip()
            messages.append({"role": role, "content": content})
    return front, messages


def write_note(dst_path: str, front: Dict[str, str], messages: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    lines: List[str] = ["---"]
    for k, v in front.items():
        lines.append(f"{k}: {v}")
    lines.append("---\n")
    for m in messages:
        role_title = (m.get("role", "unknown") or "unknown").capitalize()
        lines.append(f"### {role_title}\n")
        lines.append((m.get("content", "") or "").rstrip() + "\n")
    text = "\n".join(lines).strip() + "\n"
    # Normaliza CRLF/CR sueltos a LF puro ANTES de colapsar: si no, escribir en
    # modo texto sin newline='' duplica los saltos al pasar por la traduccion
    # universal-newline de Python en Windows (\r\n existente -> \r\r\n).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # cosmetico: colapsa 3+ saltos de linea a 2 (heredado de TidyBlankLines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    with open(dst_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def base_name(filename: str) -> str:
    """Quita sufijos de versión (-hXXXXXXXX, -N, -tYYYYMMDDHHMM) del nombre base."""
    stem = filename[:-3] if filename.lower().endswith(".md") else filename
    stem = HASH_SUFFIX_RE.sub("", stem + ".md")[:-3]
    return stem


def main():
    ap = argparse.ArgumentParser(description="Fusiona variantes de un vault RAW en un vault MERGED sin perder mensajes.")
    ap.add_argument("raw_dir")
    ap.add_argument("merged_dir")
    ap.add_argument("--merge", action="store_true", help="Fusiona mensajes de todas las variantes (recomendado)")
    ap.add_argument("--reverse-blocks", action="store_true", help="Invierte el orden de bloques usuario/asistente")
    ap.add_argument("--by-year", action="store_true")
    ap.add_argument("--by-month", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    conv_dir = os.path.join(args.raw_dir, "Conversaciones")
    if not os.path.isdir(conv_dir):
        conv_dir = args.raw_dir  # permite apuntar directo a la carpeta de notas

    files = sorted(glob.glob(os.path.join(conv_dir, "**", "*.md"), recursive=True))
    groups: Dict[str, List[str]] = {}
    for path in files:
        b = base_name(os.path.basename(path))
        groups.setdefault(b, []).append(path)

    out_conv = os.path.join(args.merged_dir, "Conversaciones")
    os.makedirs(out_conv, exist_ok=True)

    stats = {"grupos": 0, "variantes_totales": 0, "mensajes_campeon": 0,
             "mensajes_fusionados": 0, "mensajes_recuperados": 0, "notas_escritas": 0}

    for base, paths in sorted(groups.items()):
        stats["grupos"] += 1
        stats["variantes_totales"] += len(paths)

        variants = []
        for p in paths:
            front, messages = read_note(p)
            words = sum(len((m.get("content") or "").split()) for m in messages)
            variants.append({"path": p, "front": front, "messages": messages,
                              "words": words, "size": os.path.getsize(p)})

        variants.sort(key=lambda v: (v["words"], v["size"]), reverse=True)
        champion = variants[0]
        stats["mensajes_campeon"] += len(champion["messages"])

        # El source base se hereda del campeon (claude_export, chatgpt_export, ...)
        # en vez de hardcodearlo: el merge es agnostico del proveedor. Se limpian
        # sufijos de ejecuciones previas antes de re-anexarlos.
        base_source = (champion["front"].get("source") or "chatgpt_export").strip('"')
        for _suf in ("_reverse", "_merged"):
            if base_source.endswith(_suf):
                base_source = base_source[: -len(_suf)]

        if args.merge and len(variants) > 1:
            seen = set(msg_fingerprint(m) for m in champion["messages"])
            merged = list(champion["messages"])
            recovered = 0
            for v in variants[1:]:
                for m in v["messages"]:
                    fp = msg_fingerprint(m)
                    if fp not in seen:
                        merged.append(m)
                        seen.add(fp)
                        recovered += 1
            stats["mensajes_recuperados"] += recovered
            stats["mensajes_fusionados"] += len(merged)
            final_messages = merged
            source_tag = f"{base_source}_merged" if recovered else base_source
        else:
            final_messages = champion["messages"]
            stats["mensajes_fusionados"] += len(final_messages)
            source_tag = base_source

        if args.reverse_blocks:
            final_messages = flatten_blocks(list(reversed(group_blocks(final_messages))))
            source_tag += "_reverse"

        front = dict(champion["front"])
        front["source"] = f'"{source_tag}"'

        date = front.get("date", "0000-00-00").strip('"')
        y, m = (date[:4], date[5:7]) if re.match(r"\d{4}-\d{2}-\d{2}", date) else ("0000", "00")
        out_dir = out_conv
        if args.by_year:
            out_dir = os.path.join(out_dir, y)
        if args.by_month:
            out_dir = os.path.join(out_dir, m if args.by_year else f"{y}-{m}")

        dst = os.path.join(out_dir, base + ".md")
        write_note(dst, front, final_messages)
        stats["notas_escritas"] += 1

        if args.verbose and len(variants) > 1:
            print(f"  {base}: {len(variants)} variantes -> {len(final_messages)} mensajes "
                  f"(campeón tenía {len(champion['messages'])})")

    print(f"\nListo. MERGED en: {args.merged_dir}")
    print(f"Grupos de conversación: {stats['grupos']}")
    print(f"Variantes de entrada:   {stats['variantes_totales']}")
    print(f"Notas escritas:         {stats['notas_escritas']}")
    print(f"Mensajes recuperados por fusión (no estaban en el campeón): {stats['mensajes_recuperados']}")


if __name__ == "__main__":
    main()
