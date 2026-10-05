#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_copilot_images_vault.py — Convierte el backup de imagenes de Copilot
(imagenes + .json de backup_copilot_images.py) en un vault de Obsidian.

USO:
    python build_copilot_images_vault.py --backup-dir <backup> --vault-dir <vault>

Cada imagen es una nota con la imagen incrustada, su PROMPT completo (lo que
la interfaz de Copilot no ensena) y sus metadatos en el frontmatter. Hay un
_index.md con el resumen y las imagenes por mes.

El vault se puede regenerar las veces que haga falta. Esta herramienta NUNCA
borra nada: si una nota o imagen del vault ya no corresponde a ninguna del
backup, lo dice al final y la deja donde esta.

TEXTOS TRADUCIBLES: todos los literales que acaban en el vault estan en el
bloque T, como en build_flowmusic_vault.py.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_copilot_images import localizar_existente, nombre_seguro

T = {
    "carpeta_imagenes": "Imágenes",
    "carpeta_archivos": "Archivos",
    "fichero_indice": "_index",

    "sec_imagen": "## Imagen",
    "sec_prompt": "## Prompt",
    "sec_datos": "## Datos",
    "sin_imagen": "Sin imagen descargada. Vuelve a lanzar el backup.",
    "imagen_en_backup": "La imagen no se ha copiado al vault; está en el backup como",
    "sin_prompt": "Sin prompt registrado (la API no lo devuelve para esta imagen).",
    "sin_titulo": "Imagen sin prompt",
    "sin_fecha": "Sin fecha",

    "dato_fecha": "Creada",
    "dato_modificada": "Modificada",
    "dato_original": "Nombre original",
    "dato_tamano": "Tamaño",
    "dato_id": "Id de Copilot",

    "idx_titulo": "# Imágenes de Copilot",
    "idx_resumen": "## Resumen",
    "idx_por_mes": "## Por mes",
    "idx_n_imagenes": "imágenes",
    "idx_con_prompt": "con prompt",
    "idx_sin_prompt": "sin prompt",
    "idx_rango": "Rango de fechas",
}

TITULO_LARGO = 70


def yaml_escape(value) -> str:
    """Los prompts son texto libre: pueden llevar comillas, barras y saltos de
    linea. Se escapan los tres para que el frontmatter siga siendo valido."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    texto = (str(value).replace("\\", "\\\\").replace('"', '\\"')
             .replace("\r", "").replace("\n", "\\n"))
    return f'"{texto}"'


def citar(texto: str) -> str:
    """Mete el prompt en una cita y neutraliza el Markdown de dentro, igual
    que en build_flowmusic_vault.py: sin esto un '##' o un '---' dentro del
    prompt se convierte en estructura de la nota. El contenido se conserva
    entero y literal, solo cambia como se enmarca."""
    lineas = []
    for linea in texto.splitlines():
        if not linea.strip():
            lineas.append(">")
            continue
        limpia = re.sub(r"^(\s*)(#{1,6})(\s)", r"\1\\\2\3", linea)
        lineas.append(f"> {limpia}")
    return "\n".join(lineas)


def cargar_indice(backup_dir: Path) -> dict:
    ruta = backup_dir / "_index.json"
    if not ruta.is_file():
        print(f"[error] no hay _index.json en {backup_dir}")
        sys.exit(1)
    return json.loads(ruta.read_text(encoding="utf-8"))


def titulo_de(meta: dict) -> str:
    prompt = (meta.get("prompt") or "").strip()
    if not prompt:
        return T["sin_titulo"]
    linea = prompt.splitlines()[0].strip()
    return linea if len(linea) <= TITULO_LARGO else linea[:TITULO_LARGO].rstrip() + "…"


def calcular_nombres(indice: dict) -> dict:
    """'fecha · prompt corto · ultimos 8 del id'.

    Sin corchetes (Obsidian corta el wikilink en el primer ']]'). El id va
    siempre: varias imagenes comparten prompt, y en Windows el sistema de
    ficheros no distingue mayusculas, asi que la colision se comprueba en
    minusculas y, si aun asi choca, se usa el id entero."""
    propuestas = {}
    for id_, meta in indice.items():
        fecha = (meta.get("created_at") or "")[:10] or "sin-fecha"
        corto = nombre_seguro(meta.get("prompt") or meta.get("name"), "imagen", largo=50)
        nombre = f"{fecha} · {corto} · {id_[-8:]}"
        propuestas.setdefault(nombre.lower(), []).append((id_, nombre))
    nombres, usados = {}, set()
    for entradas in propuestas.values():
        for n, (id_, nombre) in enumerate(entradas):
            final = nombre if len(entradas) == 1 else nombre[:-8] + id_
            while final.lower() in usados:
                n += 1
                final = f"{nombre[:-8]}{id_} {n}"
            usados.add(final.lower())
            nombres[id_] = final
    return nombres


def construir_nota(meta: dict, nombre: str, nombre_imagen, en_backup=None) -> str:
    id_ = meta["id"]
    fm = ["---",
          f"id: {yaml_escape(id_)}",
          f"title: {yaml_escape(titulo_de(meta))}",
          f"prompt: {yaml_escape(meta.get('prompt'))}",
          f"created_at: {yaml_escape(meta.get('created_at'))}",
          f"modified_at: {yaml_escape(meta.get('modified_at'))}",
          f"original_name: {yaml_escape(meta.get('name'))}",
          f"size_bytes: {yaml_escape(meta.get('size_bytes'))}",
          f"artifact_type: {yaml_escape(meta.get('artifact_type'))}",
          "source: copilot_images",
          "---", ""]
    cuerpo = [f"# {titulo_de(meta)}", "", T["sec_imagen"], ""]
    if nombre_imagen:
        cuerpo.append(f"![[{nombre_imagen}]]")
    elif en_backup:
        cuerpo.append(f"{T['imagen_en_backup']} `{en_backup}`.")
    else:
        cuerpo.append(T["sin_imagen"])
    cuerpo += ["", T["sec_prompt"], ""]
    cuerpo.append(citar(meta["prompt"]) if meta.get("prompt") else T["sin_prompt"])
    cuerpo += ["", T["sec_datos"], ""]
    cuerpo.append(f"- {T['dato_fecha']}: {meta.get('created_at') or T['sin_fecha']}")
    if meta.get("modified_at") and meta["modified_at"] != meta.get("created_at"):
        cuerpo.append(f"- {T['dato_modificada']}: {meta['modified_at']}")
    if meta.get("name"):
        cuerpo.append(f"- {T['dato_original']}: `{meta['name']}`")
    if meta.get("size_bytes"):
        cuerpo.append(f"- {T['dato_tamano']}: {meta['size_bytes'] / 1024:.0f} KB")
    cuerpo.append(f"- {T['dato_id']}: `{id_}`")
    return "\n".join(fm + cuerpo) + "\n"


def construir_indice(indice: dict, nombres: dict) -> str:
    fechas = sorted((m.get("created_at") or "")[:10] for m in indice.values() if m.get("created_at"))
    con_prompt = sum(1 for m in indice.values() if m.get("prompt"))
    lineas = [T["idx_titulo"], "", T["idx_resumen"], "",
              f"- {len(indice)} {T['idx_n_imagenes']}",
              f"- {con_prompt} {T['idx_con_prompt']}, {len(indice) - con_prompt} {T['idx_sin_prompt']}"]
    if fechas:
        lineas.append(f"- {T['idx_rango']}: {fechas[0]} → {fechas[-1]}")
    lineas += ["", T["idx_por_mes"], ""]

    por_mes = {}
    for id_, meta in indice.items():
        por_mes.setdefault((meta.get("created_at") or "")[:7] or T["sin_fecha"], []).append(id_)
    for mes in sorted(por_mes, reverse=True):
        lineas.append(f"### {mes} ({len(por_mes[mes])})")
        for id_ in sorted(por_mes[mes], key=lambda i: indice[i].get("created_at") or "", reverse=True):
            lineas.append(f"- [[{nombres[id_]}]]")
        lineas.append("")
    return "\n".join(lineas) + "\n"


def main():
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Construye un vault de Obsidian desde un backup de imagenes de Copilot.")
    ap.add_argument("--backup-dir", required=True, help="Carpeta con _index.json y las imagenes.")
    ap.add_argument("--vault-dir", required=True, help="Carpeta de salida del vault.")
    ap.add_argument("--no-copy-images", action="store_true",
                    help="No copiar las imagenes al vault: solo las notas.")
    args = ap.parse_args()

    backup_dir, vault_dir = Path(args.backup_dir), Path(args.vault_dir)
    if not backup_dir.exists():
        print(f"[error] no existe {backup_dir}")
        sys.exit(1)

    notas_dir = vault_dir / T["carpeta_imagenes"]
    archivos_dir = vault_dir / T["carpeta_archivos"]
    notas_dir.mkdir(parents=True, exist_ok=True)
    archivos_dir.mkdir(parents=True, exist_ok=True)

    indice = cargar_indice(backup_dir)
    print(f"[info] {len(indice)} imagenes en el indice")
    nombres = calcular_nombres(indice)

    escritas, copiadas, sin_imagen = set(), 0, 0
    imagenes_escritas = set()
    for id_, meta in indice.items():
        origen = localizar_existente(backup_dir, id_)
        nombre_img = None
        if origen is None:
            sin_imagen += 1
        elif not args.no_copy_images:
            nombre_img = f"{nombres[id_]}{origen.suffix.lower()}"
            destino = archivos_dir / nombre_img
            if not destino.exists():
                shutil.copy2(origen, destino)
            imagenes_escritas.add(destino)
            copiadas += 1

        mes = (meta.get("created_at") or "")[:7] or T["sin_fecha"]
        carpeta = notas_dir / mes
        carpeta.mkdir(parents=True, exist_ok=True)
        destino_nota = carpeta / f"{nombres[id_]}.md"
        en_backup = origen.name if (origen is not None and args.no_copy_images) else None
        destino_nota.write_text(construir_nota(meta, nombres[id_], nombre_img, en_backup),
                                encoding="utf-8")
        escritas.add(destino_nota)

    (vault_dir / f"{T['fichero_indice']}.md").write_text(
        construir_indice(indice, nombres), encoding="utf-8")

    # Informa, no borra: si cambia el formato del nombre, las notas viejas
    # quedan aqui y sus enlaces dejan de apuntar a nada. Que las quite una
    # persona, no el script.
    sobran = [p for p in notas_dir.rglob("*.md") if p not in escritas]
    sobran += [p for p in archivos_dir.iterdir() if p.is_file() and p not in imagenes_escritas] \
        if not args.no_copy_images else []

    print(f"[info] notas escritas: {len(escritas)}")
    if not args.no_copy_images:
        print(f"[info] imagenes en el vault: {copiadas}")
    if sin_imagen:
        print(f"[aviso] {sin_imagen} imagen(es) sin fichero en el backup")
    if sobran:
        print(f"[aviso] {len(sobran)} fichero(s) del vault no corresponden a este backup "
              f"(no se han tocado). Ejemplo: {sobran[0].name}")
    print(f"\n[hecho] vault en: {vault_dir.resolve()}")


if __name__ == "__main__":
    main()
