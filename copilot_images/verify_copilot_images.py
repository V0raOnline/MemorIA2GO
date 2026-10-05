#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_copilot_images.py — Pasada de reconocimiento sobre un backup de
imagenes de Copilot.

Cruza los ids de _index.json contra los ficheros reales en disco y detecta
huecos, imagenes vacias o de tamano distinto al que declara la API, JSON
corruptos y descargas a medias (.part sueltos).

USO:
    python verify_copilot_images.py --backup-dir ./copilot_images_backup

Las imagenes que estan en disco pero ya no salen en la biblioteca (por
ejemplo, las que borraste despues de bajarlas) se listan aparte: no son un
fallo del backup y NO se tocan.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_copilot_images import localizar_existente

IMAGENES = (".jpg", ".jpeg", ".png", ".webp")


def verificar(carpeta: Path) -> dict:
    """Devuelve el informe como diccionario; el main solo lo imprime."""
    indice = json.loads((carpeta / "_index.json").read_text(encoding="utf-8"))

    faltan, vacias, tamano, json_falta, json_corrupto = [], [], [], [], []
    ids_con_imagen = set()

    for id_, meta in indice.items():
        img = localizar_existente(carpeta, id_)
        # localizar_existente ignora las de 0 bytes: se distingue "no hay"
        # de "hay pero vacia" mirando el disco directamente.
        if img is None:
            vacia = [f for f in carpeta.iterdir()
                     if id_ in f.name and f.suffix.lower() in IMAGENES and f.is_file()]
            (vacias if vacia else faltan).append(id_)
            continue
        ids_con_imagen.add(id_)
        esperado = meta.get("size_bytes")
        if esperado and img.stat().st_size != esperado:
            tamano.append(f"{id_} (disco {img.stat().st_size}, API {esperado})")

        jsf = img.with_suffix(".json")
        if not jsf.is_file():
            json_falta.append(id_)
        else:
            try:
                json.loads(jsf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                json_corrupto.append(id_)

    ids = set(indice)
    fuera_de_biblioteca = sorted(
        f.name for f in carpeta.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGENES
        and not any(i in f.name for i in ids))
    parciales = sorted(p.name for p in carpeta.glob("*.part"))
    sin_prompt = sum(1 for m in indice.values() if not m.get("prompt"))

    return {
        "total": len(indice), "faltan": faltan, "vacias": vacias, "tamano": tamano,
        "json_falta": json_falta, "json_corrupto": json_corrupto,
        "parciales": parciales, "fuera_de_biblioteca": fuera_de_biblioteca,
        "sin_prompt": sin_prompt,
    }


def muestra(etiqueta, items, tope=15):
    if not items:
        return
    print(f"--- {etiqueta} (hasta {tope}) ---")
    for x in items[:tope]:
        print(f"  {x}")
    if len(items) > tope:
        print(f"  ... y {len(items) - tope} mas")
    print()


def main():
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Verifica la integridad de un backup de imagenes de Copilot.")
    ap.add_argument("--backup-dir", default="./copilot_images_backup",
                    help="Carpeta que contiene _index.json y las imagenes.")
    args = ap.parse_args()

    carpeta = Path(args.backup_dir)
    if not (carpeta / "_index.json").is_file():
        print(f"[error] no hay _index.json en {carpeta} - has hecho el backup ya?")
        sys.exit(1)

    r = verificar(carpeta)
    print(f"Total en indice: {r['total']} imagenes")
    if r["sin_prompt"]:
        print(f"Sin prompt en la API: {r['sin_prompt']} (no es un fallo del backup)")
    print()

    problemas = 0
    for etiqueta, clave in (("imagenes faltantes", "faltan"),
                            ("imagenes vacias (0 bytes)", "vacias"),
                            ("tamano distinto al de la API", "tamano"),
                            ("json faltantes", "json_falta"),
                            ("json corruptos", "json_corrupto"),
                            ("descargas a medias (.part sueltos)", "parciales")):
        if r[clave]:
            print(f"{etiqueta:<36}: {len(r[clave])}")
            problemas += len(r[clave])
    if r["fuera_de_biblioteca"]:
        print(f"{'en disco pero no en la biblioteca':<36}: {len(r['fuera_de_biblioteca'])} "
              f"(no es un fallo; no se tocan)")
    print()

    for etiqueta, clave in (("imagenes faltantes", "faltan"), ("imagenes vacias", "vacias"),
                            ("tamano distinto", "tamano"), ("json faltantes", "json_falta"),
                            ("json corruptos", "json_corrupto"),
                            ("descargas a medias", "parciales"),
                            ("en disco pero no en la biblioteca", "fuera_de_biblioteca")):
        muestra(etiqueta, r[clave])

    if problemas == 0:
        print("TODO OK: las imagenes del indice tienen sus ficheros completos.")
    else:
        print(f"Hay {problemas} problemas en total (ver arriba).")
        print("Relanza backup_copilot_images.py: lo que ya esta no se vuelve a pedir.")
        sys.exit(1)


if __name__ == "__main__":
    main()
