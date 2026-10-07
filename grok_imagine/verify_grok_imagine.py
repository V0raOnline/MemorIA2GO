#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_grok_imagine.py — Reconcilia lo que Grok dice tener contra lo que hay
en disco.

Cruza el inventario de la biblioteca (_inventario.json) con el estado de la
descarga (_estado.json) y con los ficheros reales del banco GROK/IMAGINE:
activos nunca intentados, fallidos, desaparecidos del servidor, y ficheros
del manifest que ya no estan en disco.

USO:
    python verify_grok_imagine.py --grok-dir "<base_vault>/GROK"

No toca nada. Los activos 'ya no existen' (404) no son un fallo del backup:
el servidor ya no los tiene. Y 'ya la tenias' tampoco: el contenido esta en
otro banco, deduplicado por hash.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

CARPETA_BANCO = "IMAGINE"


def _json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def verificar(grok_dir: Path) -> dict:
    banco = grok_dir / CARPETA_BANCO
    inventario = _json(banco / "_inventario.json", None)
    if inventario is None:
        return {"sin_inventario": True}
    estado = _json(banco / "_estado.json", {})
    manifest = _json(banco / "_image_manifest.json", {})

    por_id = {a.get("assetId"): a for a in inventario}
    nunca = [i for i in por_id if i not in estado]
    fallidos = [i for i in por_id if estado.get(i) in ("error", "sin key")]
    ausentes = [i for i in por_id if estado.get(i) == "ausente"]
    cuentas = Counter(estado.get(i, "sin intentar") for i in por_id)

    manifest_por_asset = {m.get("assetId"): f for f, m in manifest.items()}
    ok_sin_manifest = [i for i in por_id if estado.get(i) == "ok" and i not in manifest_por_asset]
    faltan_en_disco = sorted(f for f in manifest if not (banco / f).is_file())
    vacios = sorted(f for f in manifest if (banco / f).is_file() and (banco / f).stat().st_size == 0)
    parciales = sorted(p.name for p in banco.glob("*.part"))

    return {
        "sin_inventario": False,
        "total": len(por_id),
        "cuentas": dict(cuentas),
        "nunca": nunca, "fallidos": fallidos, "ausentes": ausentes,
        "ok_sin_manifest": ok_sin_manifest,
        "faltan_en_disco": faltan_en_disco, "vacios": vacios, "parciales": parciales,
        "borrados_marcados": sum(1 for a in por_id.values() if a.get("isDeleted")),
    }


def muestra(etiqueta, items, tope=15):
    if not items:
        return
    print("--- %s (up to %d) ---" % (etiqueta, tope))
    for x in items[:tope]:
        print("  %s" % x)
    if len(items) > tope:
        print("  ... and %d more" % (len(items) - tope))
    print()


def main():
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Checks the Grok Imagine backup.")
    ap.add_argument("--grok-dir", required=True, help="GROK folder of the vault.")
    args = ap.parse_args()

    r = verificar(Path(args.grok_dir))
    if r["sin_inventario"]:
        print("[error] no inventory in %s - have you run the backup yet?"
              % (Path(args.grok_dir) / CARPETA_BANCO))
        sys.exit(1)

    print("Assets in the library: %d" % r["total"])
    for estado, n in sorted(r["cuentas"].items(), key=lambda kv: -kv[1]):
        print("  %-14s %d" % (estado, n))
    if r["borrados_marcados"]:
        print("Marked as deleted in the API: %d (informational)" % r["borrados_marcados"])
    print()

    problemas = 0
    for etiqueta, clave in (("not attempted", "nunca"), ("failed", "fallidos"),
                            ("ok with no manifest entry", "ok_sin_manifest"),
                            ("in the manifest but not on disk", "faltan_en_disco"),
                            ("empty files (0 bytes)", "vacios"),
                            ("partial downloads (.part)", "parciales")):
        if r[clave]:
            print("%-34s: %d" % (etiqueta, len(r[clave])))
            problemas += len(r[clave])
    if r["ausentes"]:
        print("%-34s: %d (404; not a backup failure)" % ("no longer on the server", len(r["ausentes"])))
    print()

    for etiqueta, clave in (("not attempted", "nunca"), ("failed", "fallidos"),
                            ("ok with no manifest", "ok_sin_manifest"),
                            ("missing on disk", "faltan_en_disco"), ("empty", "vacios"),
                            ("partial downloads", "parciales"), ("no longer exist", "ausentes")):
        muestra(etiqueta, r[clave])

    if problemas == 0:
        print("ALL OK: everything Grok says it has is in your banks or no longer exists.")
    else:
        print("There are %d problems in total (see above)." % problemas)
        print("Run backup_grok_imagine.py again: what is already there is not requested again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
