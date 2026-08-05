#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_flowmusic_vault.py — Convierte el backup de Flow Music (JSON + m4a
generados por backup_flowmusic.py) en un vault de Obsidian independiente.

USO:
    python build_flowmusic_vault.py --backup-dir <backup> --vault-dir <vault>

Mismo planteamiento que build_suno_vault.py (§3i/§3l del CONTEXT), con las
diferencias que impone la API de Riffusion:

  - El linaje sale de `source_clip_ids`, no de cover_clip_id/mashup.
  - Los grupos son CONVERSACIONES, no proyectos: en Flow Music `project_id`
    viene a null en todas las pistas y lo que agrupa de verdad es la
    conversacion en la que se generaron.
  - No hay badges en la API. Se derivan de `op_type`, que es mas rico que
    el `task` de Suno (create_song, render_edit, modify_song, split_stems,
    upload, apply_effect).
  - Se copia el m4a al vault, NO el wav: el wav esta para archivo y son
    ~5 GB. El vault esta para escuchar y navegar. El wav se queda en el
    backup, y la nota dice donde.

TEXTOS TRADUCIBLES: todos los literales que acaban en el vault estan en el
bloque T de mas abajo. Al portar a release/en se traduce ese bloque y poco
mas, en vez de ir cazando cadenas por el fichero (que es lo que hay que
hacer hoy con build_suno_vault.py).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- textos

T = {
    "carpeta_canciones": "Canciones",
    "carpeta_audio": "Audio",
    "carpeta_portadas": "Portadas",
    "sin_conversacion": "_Sin conversación",
    "fichero_indice": "_index",
    "fichero_linaje": "_linaje",

    "sec_familia": "## Familia",
    "sec_instruccion": "## Instrucción",
    "sec_letra": "## Letra",
    "sec_audio": "## Audio",

    "familia_original": "Original — no sale de ninguna pista anterior.",
    "familia_de": "Sale de:",
    "familia_deriva": "Han salido de esta:",
    "instruccion_ninguna": "Sin instrucción registrada (la API solo la guarda "
                           "en las operaciones de edición).",
    "letra_ninguna": "Sin letra.",
    "wav_en_backup": "El WAV sin pérdida no se copia al vault; está en el backup como",
    "sin_audio": "Sin audio descargado.",

    "idx_titulo": "# Flow Music",
    "idx_favoritas": "## ❤️ Favoritas",
    "idx_linaje": "## 🧬 Linaje",
    "idx_linaje_ver": "Ver [[_linaje]] — archivo separado, que es grande.",
    "idx_conversaciones": "## Conversaciones",
    "idx_por_tipo": "## Por tipo de operación",
    "idx_resumen": "## Resumen",

    "lin_titulo": "# Linaje",
    "lin_intro": "Cada árbol es una pista original y todo lo que salió de ella. "
                 "El código Dewey de cada nota dice su posición: `0` es la raíz, "
                 "`0.1` su primer descendiente, `0.1.2` el segundo de aquel.",
    "lin_familias": "## Familias con descendencia",
    "lin_sueltas": "## Pistas sin descendencia",
    "lin_pistas": "pistas",
    "lin_favoritas": "favoritas",

    # op_type -> etiqueta legible. Las claves NO se traducen (vienen de la
    # API); los valores si.
    "badges": {
        "audio__create_song": "Original",
        "audio__render_edit": "Edición",
        "audio__modify_song": "Modificación",
        "audio__split_stems": "Stem",
        "audio_upload": "Subida",
        "audio__apply_effect": "Efecto",
    },
    "badge_desconocido": "Otro",
    "badge_favorita": "Favorita",
}


# ------------------------------------------------------------- utilidades

def safe_filename(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    permitidos = "-_.() "
    limpio = "".join(c for c in name if c.isalnum() or c in permitidos).strip()
    return limpio[:120] if limpio else fallback


def safe_folder_name(name: str, fallback: str = None) -> str:
    fallback = fallback or T["sin_conversacion"]
    if not name:
        return fallback
    permitidos = "-_.() "
    limpio = "".join(c for c in name.strip() if c.isalnum() or c in permitidos).strip()
    return limpio[:80] if limpio else fallback


def yaml_escape(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(yaml_escape(v) for v in value) + "]"
    texto = str(value).replace('"', '\\"')
    return f'"{texto}"'


def cargar_indice(backup_dir: Path) -> dict:
    """El backup de Flow Music guarda _index.json como un dict id -> meta,
    a diferencia del de Suno, que es una lista. Se lee de ahi y no de los
    .json sueltos: es la misma informacion y en un solo fichero."""
    ruta = backup_dir / "_index.json"
    if not ruta.is_file():
        print(f"[error] no hay _index.json en {backup_dir}")
        sys.exit(1)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(datos, list):  # tolerancia por si cambia el formato
        datos = {d["id"]: d for d in datos if d.get("id")}

    # Las borradas no entran. No es una pista que perdimos: en los datos
    # reales la unica con deleted_at viene sin titulo, sin op_type, sin
    # letra y sin audio_url — una generacion fallida que Flow descarto. Le
    # haciamos una nota vacia en el vault. Mismo criterio que
    # flowmusic_stats.py, para que los dos den el mismo numero.
    vivas = {cid: m for cid, m in datos.items() if not m.get("deleted_at")}
    borradas = len(datos) - len(vivas)
    if borradas:
        print(f"[info] {borradas} pista(s) borrada(s) en Flow Music, se omiten")
    return vivas


# ---------------------------------------------------------------- linaje

def padre_principal(meta: dict, por_id: dict):
    """Una pista puede declarar varios origenes; para el arbol solo cuenta
    el primero que exista en el backup. Los demas se siguen mostrando en la
    seccion Familia de la nota, que no se pierde informacion."""
    for oid in meta.get("source_clip_ids") or []:
        if oid in por_id and oid != meta.get("id"):
            return oid
    return None


def calcular_dewey(por_id: dict):
    """Bosque genealogico con codigos '0', '0.1', '0.2.1'... Mismo esquema
    que el vault de Suno, para que las dos bibliotecas se lean igual."""
    hijos, raices = {}, []
    for cid, meta in por_id.items():
        padre = padre_principal(meta, por_id)
        if padre:
            hijos.setdefault(padre, []).append(cid)
        else:
            raices.append(cid)

    def por_fecha(cid):
        return por_id[cid].get("created_at") or ""

    raices.sort(key=por_fecha)
    for kids in hijos.values():
        kids.sort(key=por_fecha)

    codigos, visitados = {}, set()

    def asignar(cid, codigo):
        if cid in visitados:  # guarda por si los datos traen un ciclo
            return
        visitados.add(cid)
        codigos[cid] = codigo
        for i, k in enumerate(hijos.get(cid, []), start=1):
            asignar(k, f"{codigo}.{i}")

    for r in raices:
        asignar(r, "0")
    return codigos, hijos, raices


def calcular_nombres(por_id: dict, codigos: dict):
    """'Titulo [codigo].md'. Si dos pistas colisionan en titulo+codigo se
    desambigua con los primeros 8 caracteres del id, y solo a las que
    chocan: los stems se llaman todos igual salvo el sufijo, asi que aqui
    pasa mas que en Suno.

    La colision se detecta SIN distinguir mayusculas, aunque los nombres se
    conserven tal cual. En Windows (y en macOS por defecto) el sistema de
    ficheros es insensible a mayusculas, asi que 'VIBE YOUR CODING [0].m4a'
    y 'Vibe Your Coding [0].m4a' son el mismo fichero: uno pisa al otro sin
    avisar y la nota acaba embebiendo el audio de otra pista. Pasa de
    verdad — hay dos pistas en el catalogo cuyos titulos solo difieren en
    eso."""
    propuestas = {}
    for cid, meta in por_id.items():
        base = f"{safe_filename(meta.get('title'), cid)} [{codigos.get(cid, '0')}]"
        propuestas.setdefault(base.lower(), []).append((cid, base))

    nombres = {}
    for _, entradas in propuestas.items():
        if len(entradas) == 1:
            cid, base = entradas[0]
            nombres[cid] = base
        else:
            for cid, base in sorted(entradas,
                                    key=lambda e: por_id[e[0]].get("created_at") or ""):
                nombres[cid] = f"{base} {cid[:8]}"
    return nombres


def badges_de(meta: dict) -> list:
    """Flow Music no expone badges como Suno; se derivan de op_type."""
    badges = [T["badges"].get(meta.get("op_type"), T["badge_desconocido"])]
    if meta.get("is_favorite"):
        badges.append(T["badge_favorita"])
    return badges


# ----------------------------------------------------------------- notas

def frontmatter(meta: dict, codigo: str, badges: list) -> str:
    lineas = ["---"]
    lineas.append(f"id: {yaml_escape(meta.get('id'))}")
    lineas.append(f"title: {yaml_escape(meta.get('title'))}")
    lineas.append(f"dewey_code: {yaml_escape(codigo)}")
    lineas.append(f"created_at: {yaml_escape(meta.get('created_at'))}")
    lineas.append(f"op_type: {yaml_escape(meta.get('op_type'))}")
    lineas.append(f"duration_sec: {yaml_escape(meta.get('duration'))}")
    if meta.get("duration_status"):
        lineas.append(f"duration_status: {yaml_escape(meta.get('duration_status'))}")
    lineas.append(f"is_favorite: {yaml_escape(meta.get('is_favorite', False))}")
    lineas.append(f"play_count: {yaml_escape(meta.get('play_count'))}")
    lineas.append(f"favorite_count: {yaml_escape(meta.get('favorite_count'))}")
    lineas.append(f"privacy: {yaml_escape(meta.get('privacy'))}")
    lineas.append(f"conversation: {yaml_escape(meta.get('conversation_title'))}")
    lineas.append("badges:")
    for b in badges:
        lineas.append(f"  - {yaml_escape(b)}")
    lineas.append("---")
    return "\n".join(lineas)


def seccion_familia(meta: dict, por_id: dict, nombres: dict, hijos: dict) -> str:
    origenes = [o for o in (meta.get("source_clip_ids") or []) if o in por_id]
    descendientes = hijos.get(meta.get("id"), [])

    lineas = [T["sec_familia"], ""]
    if not origenes and not descendientes:
        lineas.append(T["familia_original"])
        return "\n".join(lineas)

    if origenes:
        lineas.append(T["familia_de"])
        for o in origenes:
            lineas.append(f"- [[{nombres[o]}]]")
        lineas.append("")
    else:
        lineas.append(T["familia_original"])
        lineas.append("")

    if descendientes:
        lineas.append(T["familia_deriva"])
        for d in descendientes:
            lineas.append(f"- [[{nombres[d]}]]")
    return "\n".join(lineas).rstrip()


def construir_nota(meta: dict, por_id: dict, nombres: dict, codigos: dict,
                   hijos: dict, con_audio: bool) -> str:
    cid = meta["id"]
    badges = badges_de(meta)
    partes = [frontmatter(meta, codigos.get(cid, "0"), badges), ""]
    partes.append(f"# {meta.get('title') or cid}")
    partes.append("")
    partes.append(seccion_familia(meta, por_id, nombres, hijos))
    partes.append("")

    partes.append(T["sec_audio"])
    partes.append("")
    if con_audio:
        partes.append(f"![[{nombres[cid]}.m4a]]")
        if meta.get("wav_url"):
            partes.append("")
            partes.append(f"{T['wav_en_backup']} `{nombres[cid]}.wav`.")
    else:
        partes.append(T["sin_audio"])
    partes.append("")

    partes.append(T["sec_instruccion"])
    partes.append("")
    partes.append(meta.get("instruction") or T["instruccion_ninguna"])
    partes.append("")

    partes.append(T["sec_letra"])
    partes.append("")
    partes.append(meta.get("lyrics") or T["letra_ninguna"])
    return "\n".join(partes) + "\n"


# --------------------------------------------------------------- indices

def construir_linaje(por_id: dict, nombres: dict, hijos: dict, raices: list) -> str:
    lineas = [T["lin_titulo"], "", T["lin_intro"], ""]

    def descendencia(cid):
        salida = []
        for k in hijos.get(cid, []):
            salida.append(k)
            salida.extend(descendencia(k))
        return salida

    con_hijos = [r for r in raices if hijos.get(r)]
    sueltas = [r for r in raices if not hijos.get(r)]

    lineas.append(f"{T['lin_familias']} ({len(con_hijos)})")
    lineas.append("")
    for r in con_hijos:
        familia = [r] + descendencia(r)
        favoritas = sum(1 for c in familia if por_id[c].get("is_favorite"))
        lineas.append(f"### {por_id[r].get('title') or r}")
        lineas.append(f"*{len(familia)} {T['lin_pistas']}, "
                      f"{favoritas} {T['lin_favoritas']}*")
        lineas.append("")

        def pintar(cid, nivel):
            sangria = "  " * nivel
            marca = " ❤️" if por_id[cid].get("is_favorite") else ""
            lineas.append(f"{sangria}- [[{nombres[cid]}]]{marca}")
            for k in hijos.get(cid, []):
                pintar(k, nivel + 1)

        pintar(r, 0)
        lineas.append("")

    lineas.append(f"{T['lin_sueltas']} ({len(sueltas)})")
    lineas.append("")
    for r in sueltas:
        marca = " ❤️" if por_id[r].get("is_favorite") else ""
        lineas.append(f"- [[{nombres[r]}]]{marca}")
    return "\n".join(lineas) + "\n"


def construir_indice(por_id: dict, nombres: dict, hijos: dict, raices: list) -> str:
    lineas = [T["idx_titulo"], ""]

    total = len(por_id)
    con_letra = sum(1 for m in por_id.values() if m.get("lyrics"))
    con_linaje = sum(1 for m in por_id.values() if m.get("source_clip_ids"))
    segundos = sum(m.get("duration") or 0 for m in por_id.values()
                   if isinstance(m.get("duration"), (int, float)))
    lineas.append(T["idx_resumen"])
    lineas.append("")
    lineas.append(f"- {total} pistas, {segundos / 3600:.1f} h")
    lineas.append(f"- {con_letra} con letra")
    lineas.append(f"- {con_linaje} con origen declarado")
    lineas.append(f"- {len(raices)} árboles genealógicos")
    lineas.append("")

    favoritas = [c for c, m in por_id.items() if m.get("is_favorite")]
    if favoritas:
        lineas.append(f"{T['idx_favoritas']} ({len(favoritas)})")
        lineas.append("")
        for c in sorted(favoritas, key=lambda i: por_id[i].get("created_at") or ""):
            lineas.append(f"- [[{nombres[c]}]]")
        lineas.append("")

    lineas.append(T["idx_linaje"])
    lineas.append("")
    lineas.append(T["idx_linaje_ver"])
    lineas.append("")

    por_conv = {}
    for cid, meta in por_id.items():
        por_conv.setdefault(meta.get("conversation_title") or T["sin_conversacion"], []).append(cid)
    lineas.append(f"{T['idx_conversaciones']} ({len(por_conv)})")
    lineas.append("")
    for conv in sorted(por_conv):
        lineas.append(f"### {conv} ({len(por_conv[conv])})")
        for c in sorted(por_conv[conv], key=lambda i: por_id[i].get("created_at") or ""):
            lineas.append(f"- [[{nombres[c]}]]")
        lineas.append("")

    por_tipo = {}
    for cid, meta in por_id.items():
        por_tipo.setdefault(badges_de(meta)[0], []).append(cid)
    lineas.append(f"{T['idx_por_tipo']} ({len(por_tipo)})")
    lineas.append("")
    for tipo in sorted(por_tipo, key=lambda t: -len(por_tipo[t])):
        lineas.append(f"### {tipo} ({len(por_tipo[tipo])})")
        for c in sorted(por_tipo[tipo], key=lambda i: por_id[i].get("created_at") or ""):
            lineas.append(f"- [[{nombres[c]}]]")
        lineas.append("")

    return "\n".join(lineas) + "\n"


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        description="Construye un vault de Obsidian desde un backup de Flow Music.")
    ap.add_argument("--backup-dir", required=True,
                    help="Carpeta con _index.json y los ficheros de backup_flowmusic.py")
    ap.add_argument("--vault-dir", required=True, help="Carpeta de salida del vault")
    ap.add_argument("--no-copy-audio", action="store_true",
                    help="No copiar m4a ni portadas: solo las notas.")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    backup_dir = Path(args.backup_dir)
    vault_dir = Path(args.vault_dir)
    if not backup_dir.exists():
        print(f"[error] no existe {backup_dir}")
        sys.exit(1)

    canciones_dir = vault_dir / T["carpeta_canciones"]
    audio_dir = vault_dir / T["carpeta_audio"]
    portadas_dir = vault_dir / T["carpeta_portadas"]
    for d in (canciones_dir, audio_dir, portadas_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("[info] cargando el indice del backup...")
    por_id = cargar_indice(backup_dir)
    print(f"[info] {len(por_id)} pistas")

    print("[info] calculando arbol genealogico (codigos Dewey)...")
    codigos, hijos, raices = calcular_dewey(por_id)
    print(f"[info] {len(raices)} arboles, "
          f"{sum(1 for h in hijos.values() if h)} pistas con descendencia")

    nombres = calcular_nombres(por_id, codigos)

    audio_copiado = audio_ausente = portadas_copiadas = 0
    for cid, meta in por_id.items():
        base_backup = f"{safe_filename(meta.get('title'), cid)}_{cid}"
        destino_stem = nombres[cid]

        m4a_origen = backup_dir / f"{base_backup}.m4a"
        tiene_audio = m4a_origen.is_file()
        if not tiene_audio:
            audio_ausente += 1

        if not args.no_copy_audio:
            if tiene_audio:
                destino = audio_dir / f"{destino_stem}.m4a"
                if not destino.exists():
                    shutil.copy2(m4a_origen, destino)
                audio_copiado += 1
            jpg_origen = backup_dir / f"{base_backup}.jpg"
            if jpg_origen.is_file():
                destino = portadas_dir / f"{destino_stem}.jpg"
                if not destino.exists():
                    shutil.copy2(jpg_origen, destino)
                portadas_copiadas += 1

        carpeta = canciones_dir / safe_folder_name(meta.get("conversation_title"))
        carpeta.mkdir(parents=True, exist_ok=True)
        nota = construir_nota(meta, por_id, nombres, codigos, hijos,
                              con_audio=tiene_audio and not args.no_copy_audio)
        (carpeta / f"{destino_stem}.md").write_text(nota, encoding="utf-8")

    (vault_dir / f"{T['fichero_indice']}.md").write_text(
        construir_indice(por_id, nombres, hijos, raices), encoding="utf-8")
    (vault_dir / f"{T['fichero_linaje']}.md").write_text(
        construir_linaje(por_id, nombres, hijos, raices), encoding="utf-8")

    print(f"[info] notas escritas: {len(por_id)}")
    if not args.no_copy_audio:
        print(f"[info] m4a copiados: {audio_copiado} | portadas: {portadas_copiadas}")
    if audio_ausente:
        print(f"[aviso] {audio_ausente} pista(s) sin m4a en el backup")
    print(f"\n[hecho] vault en: {vault_dir.resolve()}")


if __name__ == "__main__":
    main()
