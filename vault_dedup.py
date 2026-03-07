#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault_dedup.py — Limpieza de deltas y duplicados en vault Por_Proyectos.

Logica:
  - Conserva el archivo canonico (sin sufijo hash) — siempre el mas completo
  - Elimina todos los numerados (-2, -3, ... -N) — copias identicas
  - Elimina variantes de hash (-hXXXXXXXX y sus numerados) — ramas alternativas

Uso:
  python vault_dedup.py <vault_dir>               # elimina directamente
  python vault_dedup.py <vault_dir> --dry-run     # solo muestra que borraria
  python vault_dedup.py <vault_dir> --keep-hashes # conserva variantes de hash
"""

import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict

HASH_PATTERN    = re.compile(r'^(.+?)(-h[0-9a-f]{7,8})(-\d+)?\.md$', re.IGNORECASE)
NUMERIC_PATTERN = re.compile(r'^(.+?)(-\d+)\.md$')


def get_base(filename: str) -> str:
    hm = HASH_PATTERN.match(filename)
    if hm:
        return hm.group(1)
    nm = NUMERIC_PATTERN.match(filename)
    if nm:
        return nm.group(1)
    return filename.replace('.md', '')


def classify(files: list) -> dict:
    canonical = None
    hash_variants = defaultdict(list)
    numeric_dupes = []

    for f in files:
        name = f.name
        hm = HASH_PATTERN.match(name)
        if hm:
            hash_variants[hm.group(2)].append(f)
        elif NUMERIC_PATTERN.match(name):
            numeric_dupes.append(f)
        else:
            canonical = f

    return {
        "canonical": canonical,
        "hash_variants": dict(hash_variants),
        "numeric_dupes": numeric_dupes,
    }


def collect_groups(vault_dir: Path) -> dict:
    groups = defaultdict(list)
    for md in vault_dir.rglob("*.md"):
        base = get_base(md.name)
        groups[base].append(md)
    return groups


def plan_deletions(groups: dict, keep_hashes: bool = False) -> list:
    to_delete = []

    for base, files in groups.items():
        if len(files) == 1:
            continue

        classified = classify(files)

        # Numerados sueltos (sin hash) — copias del canonico
        to_delete.extend(classified["numeric_dupes"])

        # Variantes de hash
        for hash_key, variant_files in classified["hash_variants"].items():
            root_variant = None
            numbered = []
            for f in variant_files:
                hm = HASH_PATTERN.match(f.name)
                if hm and hm.group(3) is None:
                    root_variant = f
                else:
                    numbered.append(f)
            # Numerados de la variante: siempre se eliminan
            to_delete.extend(numbered)
            # Raiz de la variante: solo si no se pide conservar
            if not keep_hashes and root_variant:
                to_delete.append(root_variant)

    return to_delete


def main():
    ap = argparse.ArgumentParser(
        description="Limpia deltas y duplicados del vault Por_Proyectos."
    )
    ap.add_argument("vault", help="Carpeta raiz del vault a limpiar")
    ap.add_argument("--dry-run", action="store_true", help="Solo muestra, no borra")
    ap.add_argument("--keep-hashes", action="store_true",
                    help="Conserva variantes de hash (solo borra numerados)")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.exists():
        print(f"Error: no existe {vault}")
        sys.exit(1)

    print(f"Analizando: {vault}")
    groups = collect_groups(vault)
    to_delete = plan_deletions(groups, keep_hashes=args.keep_hashes)

    if not to_delete:
        print("Nada que limpiar. El vault ya esta deduplicado.")
        return

    total_size = sum(f.stat().st_size for f in to_delete if f.exists())
    print(f"Archivos a eliminar: {len(to_delete)}")
    print(f"Espacio liberado:    {total_size / 1024 / 1024:.2f} MB\n")

    if args.dry_run:
        print("-- DRY RUN (no se borra nada) --")
        for f in sorted(to_delete):
            print(f"  DEL  {f.name}")
        return

    deleted = 0
    errors = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"Error borrando {f.name}: {e}")
            errors += 1

    print(f"Eliminados: {deleted} archivos ({total_size / 1024 / 1024:.2f} MB liberados)")
    if errors:
        print(f"Errores: {errors}")
    print("Vault limpio.")


if __name__ == "__main__":
    main()
