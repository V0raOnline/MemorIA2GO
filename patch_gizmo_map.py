#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_gizmo_map.py — Reescribe Project_name/source_project en el front-matter
de notas ya existentes en RAW_VAULT, sin reimportar ni crear variantes nuevas.

Uso:
  python patch_gizmo_map.py RAW_VAULT gizmo_map.json

Para cada nota en RAW_VAULT/Conversaciones:
- Lee source_project_id del front-matter.
- Si ese id esta en gizmo_map.json y el Project_name actual es "none" (o
  distinto al nombre mapeado), reescribe SOLO esas dos lineas del front-matter,
  byte a byte igual el resto de la nota. No se toca el cuerpo del mensaje.

Pensado para ejecutarse despues de rellenar gizmos huerfanos y ANTES de
volver a correr vault_merge.py (--from-merge), para que el merge ya vea el
Project_name correcto en todas las variantes y no haya que desempatar nada.
"""
import argparse
import glob
import json
import os
import re


def norm_hex_id(s: str):
    if not s:
        return None
    s = s.strip().lower()
    m = re.search(r'(?:^g(?:-p)?-)?([0-9a-f]{32})$', s)
    return m.group(1) if m else None


def load_gizmo_map(path: str) -> dict:
    # utf-8-sig tolera un posible BOM inicial (PowerShell -Encoding UTF8 lo anade,
    # y json.load() normal no lo acepta) sin afectar a archivos sin BOM.
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)
    gizmo_map = {}
    for k, v in raw.items():
        hx = norm_hex_id(k)
        if not hx:
            continue
        gizmo_map[hx] = v
        gizmo_map["g-" + hx] = v
        gizmo_map["g-p-" + hx] = v
    return gizmo_map


def extract_frontmatter_id(front_lines: list, key: str) -> str:
    for line in front_lines:
        if line.startswith(f"{key}:"):
            v = line.split(":", 1)[1].strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            return v
    return ""


def patch_note(path: str, gizmo_map: dict) -> bool:
    """Devuelve True si se modifico la nota."""
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()

    if not txt.startswith("---"):
        return False
    end = txt.find("\n---\n", 4)
    if end == -1:
        return False

    front_block = txt[4:end]
    front_lines = front_block.split("\n")
    body = txt[end + 5:]

    source_project_id = extract_frontmatter_id(front_lines, "source_project_id")
    if not source_project_id:
        return False

    hx = norm_hex_id(source_project_id)
    new_name = gizmo_map.get(source_project_id) or gizmo_map.get("g-" + (hx or "")) or gizmo_map.get("g-p-" + (hx or "")) or gizmo_map.get(hx or "")
    if not new_name:
        return False

    current_name = extract_frontmatter_id(front_lines, "Project_name")
    if current_name == new_name:
        return False

    changed = False
    new_front_lines = []
    seen_source_project = False
    for line in front_lines:
        if line.startswith("Project_name:"):
            new_front_lines.append(f'Project_name: "{new_name}"')
            changed = True
        elif line.startswith("source_project:"):
            new_front_lines.append(f'source_project: "{new_name}"')
            seen_source_project = True
        else:
            new_front_lines.append(line)

    if not seen_source_project:
        # Insertar despues de source_project_id para mantener el bloque legible
        insert_at = len(new_front_lines)
        for i, line in enumerate(new_front_lines):
            if line.startswith("source_project_id:"):
                insert_at = i + 1
                break
        new_front_lines.insert(insert_at, f'source_project: "{new_name}"')

    if not changed:
        return False

    new_txt = "---\n" + "\n".join(new_front_lines) + "\n---\n" + body
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_txt)
    return True


def main():
    ap = argparse.ArgumentParser(description="Parchea Project_name en RAW_VAULT a partir de un gizmo_map.json actualizado.")
    ap.add_argument("raw_vault", help="Ruta a RAW_VAULT (o a la carpeta que contiene Conversaciones)")
    ap.add_argument("gizmo_map", help="Ruta al gizmo_map.json ya actualizado")
    args = ap.parse_args()

    conv_dir = os.path.join(args.raw_vault, "Conversaciones")
    if not os.path.isdir(conv_dir):
        conv_dir = args.raw_vault

    gizmo_map = load_gizmo_map(args.gizmo_map)

    files = glob.glob(os.path.join(conv_dir, "**", "*.md"), recursive=True)
    patched = 0
    for f in files:
        if patch_note(f, gizmo_map):
            patched += 1

    print(f"Notas revisadas: {len(files)}")
    print(f"Notas parcheadas: {patched}")

    # Limpia de _gizmos_pendientes.json los gizmos que ya tienen nombre --
    # si no, seguirian apareciendo como pendientes en la web indefinidamente,
    # incluso despues de nombrarlos, hasta la proxima vez que corra el paso 1.
    pendientes_path = os.path.join(args.raw_vault, "_gizmos_pendientes.json")
    if os.path.exists(pendientes_path):
        try:
            with open(pendientes_path, "r", encoding="utf-8-sig") as f:
                pendientes = json.load(f)
        except Exception:
            pendientes = {}
        resueltos = [k for k in pendientes if k in gizmo_map]
        for k in resueltos:
            del pendientes[k]
        if resueltos:
            with open(pendientes_path, "w", encoding="utf-8") as f:
                json.dump(pendientes, f, ensure_ascii=False, indent=2)
            print(f"Gizmos resueltos, quitados de pendientes: {len(resueltos)}")


if __name__ == "__main__":
    main()
