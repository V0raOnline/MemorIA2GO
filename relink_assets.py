#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relink_assets.py — Reescribe enlaces de assets (![](...)) en notas ya
escritas cuando un banco cambia de nombre o de carpeta.

Herramienta reutilizable a propósito (decisión V0ra 2026-07-22: "empieza a
ser habitual" -- ya pasó una vez con _assets->IMAGE_BANK, ahora con
IMAGE_BANK->bancos por proveedor/tipo, y volverá a pasar). Sirve para
CUALQUIER reorganización futura de assets, no solo esta.

Toca las dos formas de enlace markdown: ![](ruta) de imagen y [texto](ruta)
de fichero -- nunca wikilinks [[...]] ni el resto del texto de la nota. No
escribe un archivo si no hubo cambios (no toca mtime sin motivo).

Nacio en 2026-07-22 casando SOLO ![](ruta), porque entonces los bancos solo
guardaban imagenes. CLAUDE/ARTIFACTS (siempre [texto](ruta)) y los adjuntos
no-imagen de Grok llegaron despues y la dejaron insuficiente sin que nada
avisara: mover uno de esos bancos dejaba los enlaces apuntando a la carpeta
vieja, en silencio. Corregido 2026-07-30.

Uso:
  python relink_assets.py RAW_VAULT --mapa mapeo.json
  python relink_assets.py MERGED_VAULT --mapa mapeo.json
  python relink_assets.py PRJ_VAULT --mapa mapeo.json
  python relink_assets.py RAW_VAULT --mapa mapeo.json --dry-run

mapeo.json: {"ruta_vieja_del_enlace": "ruta_nueva_del_enlace", ...}
Ejemplo: {"IMAGE_BANK/abc123def456.png": "CHATGPT/GENERATED/abc123def456.png"}
"""
import argparse
import json
import re
from pathlib import Path
from typing import Dict

from tree_index import iter_markdown_files

# Casa las DOS formas de enlace markdown: ![](ruta) de imagen y [texto](ruta)
# de fichero. Empezo siendo solo la primera (2026-07-22, cuando los bancos solo
# tenian imagenes); CLAUDE/ARTIFACTS usa SIEMPRE la segunda y GROK/ATTACHMENTS
# mezcla ambas segun el tipo, asi que la version de solo-imagen dejaba enlaces
# apuntando a la carpeta vieja sin avisar. El grupo 'bang' preserva cual era.
#
# El '(?<!\[)' del principio protege el contrato de la herramienta: NUNCA
# tocar wikilinks [[...]]. Sin el, "[[ruta]]" entraria por la rama de enlace.
ASSET_LINK_RE = re.compile(r"(?<!\[)(?P<bang>!)?\[(?P<text>[^\]]*)\]\((?P<path>[^)]+)\)")


def relink_file(path: Path, mapa: Dict[str, str]) -> int:
    """Devuelve cuantos enlaces se reescribieron en este archivo."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0

    cambios = 0

    def _sub(m: "re.Match[str]") -> str:
        nonlocal cambios
        nueva = mapa.get(m.group("path"))
        if nueva is None:
            return m.group(0)
        cambios += 1
        # Se reconstruye respetando la forma original: una imagen sigue siendo
        # imagen y un enlace conserva su texto (que en los artefactos de Claude
        # es el nombre de fichero visible, no un adorno).
        return f"{m.group('bang') or ''}[{m.group('text')}]({nueva})"

    nuevo_texto = ASSET_LINK_RE.sub(_sub, text)
    if cambios:
        path.write_text(nuevo_texto, encoding="utf-8", newline="")
    return cambios


def contar_cambios(path: Path, mapa: Dict[str, str]) -> int:
    """Version de solo-lectura de relink_file, para --dry-run."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for m in ASSET_LINK_RE.finditer(text) if m.group("path") in mapa)


def relink_vault(vault_root: Path, mapa: Dict[str, str], dry_run: bool = False) -> dict:
    stats = {"archivos_escaneados": 0, "archivos_tocados": 0, "enlaces_reescritos": 0}
    for f in iter_markdown_files(vault_root):
        stats["archivos_escaneados"] += 1
        n = contar_cambios(f, mapa) if dry_run else relink_file(f, mapa)
        if n:
            stats["archivos_tocados"] += 1
            stats["enlaces_reescritos"] += n
    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Reescribe enlaces de assets en notas segun un mapeo ruta_vieja -> ruta_nueva.")
    ap.add_argument("vault_root", help="Carpeta a recorrer recursivamente en busca de *.md "
                                        "(p.ej. RAW_VAULT, MERGED_VAULT o PRJ_VAULT)")
    ap.add_argument("--mapa", required=True, help="JSON {ruta_vieja: ruta_nueva} de los enlaces a reescribir")
    ap.add_argument("--dry-run", action="store_true", help="Solo cuenta cuantos enlaces cambiarian, no escribe nada")
    args = ap.parse_args()

    vault_root = Path(args.vault_root).expanduser().resolve()
    if not vault_root.is_dir():
        raise SystemExit(f"No existe: {vault_root}")

    with open(args.mapa, "r", encoding="utf-8-sig") as f:
        mapa = json.load(f)

    stats = relink_vault(vault_root, mapa, dry_run=args.dry_run)
    modo = "DRY-RUN (nothing written)" if args.dry_run else "Written"
    print(f"{modo}. Files scanned: {stats['archivos_escaneados']}")
    print(f"Files changed: {stats['archivos_tocados']}")
    print(f"Links rewritten: {stats['enlaces_reescritos']}")


if __name__ == "__main__":
    main()
