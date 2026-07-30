#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layout_migration.py — Convierte un vault construido con la edicion espanola
al layout de carpetas de la edicion inglesa (i18n fase 3b).

Para que existe (decision V0ra 2026-07-30): las dos ediciones nunca se
cruzan -- ella corre la espanola en local, la inglesa es para la comunidad
-- asi que NO hay estrategia de migracion de contenido: quien quiera el
contenido de las notas en ingles, reprocesa desde sus exports. Pero el
reproceso solo escribe notas nuevas; NO renombra las carpetas que ya
existen. Sin este paso, un vault ya construido acabaria con el arbol ingles
al lado del espanol, con las notas dobladas en la busqueda y en el grafo de
Obsidian. Renombrar primero y reprocesar despues deja una sola copia.

Lo que hace, en este orden:
  1. Renombra las carpetas estructurales (Conversaciones -> Conversations...).
  2. Renombra las notas generadas cuyo NOMBRE era espanol (_sin-tema.md...).
  3. Reescribe los enlaces de assets de las notas ya escritas, para que
     sigan apuntando a los bancos renombrados.

Lo que NO hace, a proposito:
  - No toca el contenido de las notas mas alla de los enlaces. El texto en
    espanol se queda hasta que el usuario reprocese: es SU contenido y su
    decision, no la nuestra.
  - No toca los ficheros de estado (_pendientes_descarga.json,
    _exports_procesados.json, _gizmos_pendientes.json). Decision de V0ra,
    quiza en una version futura. Sale gratis: los tres viven en carpetas
    que no se renombran (GROK/, CHATGPT/, RAW_VAULT/), asi que el triaje
    manual y el registro de importaciones sobreviven intactos.
  - No borra nada. Si el destino de un renombrado ya existe, esa entrada se
    salta y se reporta: mejor dejar el trabajo a medias y decirlo que
    fusionar dos arboles a ciegas.

Uso:
  python layout_migration.py BASE_VAULT --dry-run
  python layout_migration.py BASE_VAULT
"""
import argparse
import sys
from pathlib import Path
from typing import List, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import relink_assets

# Carpetas a renombrar, relativas a base_vault, siempre ruta VIEJA entera ->
# ruta NUEVA entera. Los padres van antes que sus hijos.
#
# Ojo con CLAUDE/ARTEFACTOS/codigo: para cuando le toca el turno, su carpeta
# padre ya se llama ARTIFACTS, asi que no esta donde dice la columna
# izquierda. De eso se encarga _origen_actual(), que mira las dos
# posibilidades -- expresarlo aqui con el nombre nuevo del padre parecia mas
# simple pero rompia la deteccion, que corre ANTES de renombrar nada: la
# subcarpeta no se veia en la primera pasada y hacian falta dos corridas.
CARPETAS: List[Tuple[str, str]] = [
    ("RAW_VAULT/Conversaciones", "RAW_VAULT/Conversations"),
    ("MERGED_VAULT/Conversaciones", "MERGED_VAULT/Conversations"),
    ("MERGED_VAULT/_Temas", "MERGED_VAULT/_Topics"),
    ("CHATGPT/GENERADAS", "CHATGPT/GENERATED"),
    ("CHATGPT/ADJUNTOS", "CHATGPT/ATTACHMENTS"),
    ("GROK/ADJUNTOS", "GROK/ATTACHMENTS"),
    ("GROK/GENERADAS_IMAGEN", "GROK/GENERATED_IMAGE"),
    ("GROK/GENERADAS_VIDEO", "GROK/GENERATED_VIDEO"),
    ("CLAUDE/ARTEFACTOS", "CLAUDE/ARTIFACTS"),
    ("CLAUDE/ARTEFACTOS/codigo", "CLAUDE/ARTIFACTS/code"),
]

# Notas generadas cuyo NOMBRE de fichero era espanol. Se expresan con la ruta
# entera vieja -> entera nueva, pero ojo: _sin-tema.md vive DENTRO de _Temas,
# asi que cuando le llega el turno su carpeta padre ya se ha renombrado y el
# fichero no esta donde dice la columna izquierda. _origen_actual() resuelve
# esa doble posibilidad en vez de depender del orden.
FICHEROS: List[Tuple[str, str]] = [
    ("MERGED_VAULT/_Temas/_sin-tema.md", "MERGED_VAULT/_Topics/_no-topic.md"),
    ("MERGED_VAULT/_grok_pendientes.md", "MERGED_VAULT/_grok_pending.md"),
    ("PRJ_VAULT/_grok_pendientes.md", "PRJ_VAULT/_grok_pending.md"),
]

# Prefijos de enlace a reescribir dentro de las notas. Mas especifico
# primero: CLAUDE/ARTEFACTOS/codigo/ tiene que ganar a CLAUDE/ARTEFACTOS/,
# o el segundo se lo come y deja la subcarpeta sin traducir.
PREFIJOS_ENLACE: List[Tuple[str, str]] = [
    ("CLAUDE/ARTEFACTOS/codigo/", "CLAUDE/ARTIFACTS/code/"),
    ("CLAUDE/ARTEFACTOS/", "CLAUDE/ARTIFACTS/"),
    ("CHATGPT/GENERADAS/", "CHATGPT/GENERATED/"),
    ("CHATGPT/ADJUNTOS/", "CHATGPT/ATTACHMENTS/"),
    ("GROK/ADJUNTOS/", "GROK/ATTACHMENTS/"),
    ("GROK/GENERADAS_IMAGEN/", "GROK/GENERATED_IMAGE/"),
    ("GROK/GENERADAS_VIDEO/", "GROK/GENERATED_VIDEO/"),
]

# Vaults que contienen notas con enlaces a los bancos.
VAULTS_CON_NOTAS = ("RAW_VAULT", "MERGED_VAULT", "PRJ_VAULT")


def _origen_actual(base: Path, viejo: str, nuevo: str) -> Path:
    """Donde esta AHORA MISMO lo que hay que renombrar. Puede seguir en su
    ruta vieja entera, o haber viajado ya con su carpeta padre renombrada
    (casos _Temas/_sin-tema.md y CLAUDE/ARTEFACTOS/codigo). Se comprueban
    las dos, en ese orden. Vale igual para carpetas y para ficheros."""
    tal_cual = base / viejo
    if tal_cual.exists():
        return tal_cual
    return base / Path(nuevo).parent / Path(viejo).name


def detectar(base_vault) -> dict:
    """Que hay que migrar en este vault. Barato (solo stat de rutas), pensado
    para llamarse en cada carga de la pestana sin coste apreciable.

    Devuelve {"necesaria": bool, "carpetas": [...], "ficheros": [...],
    "bloqueadas": [...]}. 'bloqueadas' son renombrados cuyo destino YA
    existe: hay que mirarlas a mano, no se tocan."""
    base = Path(base_vault)
    carpetas, ficheros, bloqueadas = [], [], []

    for viejo, nuevo in CARPETAS:
        origen, destino = _origen_actual(base, viejo, nuevo), base / nuevo
        if not origen.is_dir() or origen == destino:
            continue
        (bloqueadas if destino.exists() else carpetas).append(
            {"de": viejo, "a": nuevo})

    for viejo, nuevo in FICHEROS:
        origen, destino = _origen_actual(base, viejo, nuevo), base / nuevo
        if not origen.is_file() or origen == destino:
            continue
        (bloqueadas if destino.exists() else ficheros).append(
            {"de": viejo, "a": nuevo})

    return {
        "necesaria": bool(carpetas or ficheros or bloqueadas),
        "carpetas": carpetas,
        "ficheros": ficheros,
        "bloqueadas": bloqueadas,
    }


def _mapa_de_enlaces(vault_root: Path) -> dict:
    """Construye el mapa exacto {ruta_vieja: ruta_nueva} que espera
    relink_assets, recorriendo los enlaces que hay de verdad en las notas.

    Se hace asi en vez de reescribir por prefijo a saco para no inventar:
    solo se toca lo que existe, y el mapa resultante es inspeccionable."""
    mapa = {}
    for f in relink_assets.iter_markdown_files(vault_root):
        try:
            texto = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in relink_assets.ASSET_LINK_RE.finditer(texto):
            ruta = m.group("path")
            if ruta in mapa:
                continue
            for viejo, nuevo in PREFIJOS_ENLACE:
                if ruta.startswith(viejo):
                    mapa[ruta] = nuevo + ruta[len(viejo):]
                    break
    return mapa


def migrar(base_vault, dry_run: bool = False) -> dict:
    """Ejecuta la migracion completa. Con dry_run=True no escribe nada y
    devuelve el mismo informe que devolveria al ejecutarse de verdad."""
    base = Path(base_vault)
    plan = detectar(base)
    hechos = {"carpetas": [], "ficheros": [], "bloqueadas": plan["bloqueadas"],
              "enlaces_reescritos": 0, "notas_tocadas": 0, "errores": []}

    for entrada in plan["carpetas"]:
        # Igual que con los ficheros: se resuelve aqui, porque una subcarpeta
        # puede haber viajado ya con el renombrado de su padre en este mismo
        # bucle (CLAUDE/ARTEFACTOS/codigo).
        origen = _origen_actual(base, entrada["de"], entrada["a"])
        destino = base / entrada["a"]
        if not origen.is_dir() or origen == destino:
            continue
        if dry_run:
            hechos["carpetas"].append(entrada)
            continue
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            origen.rename(destino)
            hechos["carpetas"].append(entrada)
        except OSError as e:
            hechos["errores"].append(f"{entrada['de']} -> {entrada['a']}: {e}")

    for entrada in plan["ficheros"]:
        # Se resuelve AQUI, no en el plan: para este punto las carpetas ya se
        # han renombrado, asi que _sin-tema.md ya no esta donde el plan lo vio.
        origen = _origen_actual(base, entrada["de"], entrada["a"])
        destino = base / entrada["a"]
        if not origen.exists() or origen == destino:
            continue
        if dry_run:
            hechos["ficheros"].append(entrada)
            continue
        try:
            origen.rename(destino)
            hechos["ficheros"].append(entrada)
        except OSError as e:
            hechos["errores"].append(f"{entrada['de']} -> {entrada['a']}: {e}")

    for nombre in VAULTS_CON_NOTAS:
        vault = base / nombre
        if not vault.is_dir():
            continue
        mapa = _mapa_de_enlaces(vault)
        if not mapa:
            continue
        stats = relink_assets.relink_vault(vault, mapa, dry_run=dry_run)
        hechos["enlaces_reescritos"] += stats["enlaces_reescritos"]
        hechos["notas_tocadas"] += stats["archivos_tocados"]

    return hechos


def main():
    ap = argparse.ArgumentParser(
        description="Renombra el layout de un vault espanol al ingles y reengancha los enlaces.")
    ap.add_argument("base_vault", help="Carpeta base del vault (la que contiene RAW_VAULT, CHATGPT...)")
    ap.add_argument("--dry-run", action="store_true", help="Solo informa, no toca nada")
    args = ap.parse_args()

    base = Path(args.base_vault).expanduser().resolve()
    if not base.is_dir():
        raise SystemExit(f"Does not exist: {base}")

    plan = detectar(base)
    if not plan["necesaria"]:
        print("Nothing to migrate: this vault already uses the English layout.")
        return

    hechos = migrar(base, dry_run=args.dry_run)
    modo = "DRY-RUN (nothing written)" if args.dry_run else "Done"
    print(f"{modo}.")
    for c in hechos["carpetas"]:
        print(f"  folder: {c['de']} -> {c['a']}")
    for f in hechos["ficheros"]:
        print(f"  file:   {f['de']} -> {f['a']}")
    print(f"  links rewritten: {hechos['enlaces_reescritos']} in {hechos['notas_tocadas']} note(s)")
    for b in hechos["bloqueadas"]:
        print(f"  SKIPPED (target already exists): {b['de']} -> {b['a']}")
    for e in hechos["errores"]:
        print(f"  ERROR: {e}")
    if not args.dry_run:
        print("\nReprocess your exports to rewrite the note content in English.")


if __name__ == "__main__":
    main()
