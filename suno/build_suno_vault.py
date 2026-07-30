#!/usr/bin/env python3
"""
build_suno_vault.py — Convierte el backup de Suno (JSON + MP3 generados
por backup_suno.py) en un vault de Obsidian independiente, con:

  - Linaje cover/mashup resuelto como wikilinks reales entre notas.
  - Códigos de linaje estilo Dewey decimal (0, 0.1, 0.2, 0.1.1...) que
    identifican la posición de cada pista en su árbol genealógico,
    generalizables a cualquier profundidad/anchura de ramificación.
  - Nombres de nota legibles ("Título [código].md") en vez de UUIDs — el
    ID solo se añade como desambiguador si dos pistas distintas
    colisionarían en nombre+código (raro, pero pasa: hay títulos
    duplicados reales en el catálogo).
  - Linaje (antes "árbol genealógico") como archivo separado, con
    resumen por familia (pistas/favoritas/Full Song) y "cierre de ciclo"
    destacado — listas anidadas plegables, sin plugins.
  - Índice por badge (Cover, Full Song, Extend N, Mashup, Section...).

USO:
    python build_suno_vault.py --backup-dir ./suno_backup --vault-dir ./suno_vault

No toca ni depende de MemorIA2GO — funcionalidad nueva y separada.

NOTA sobre el linaje: cover_clip_id/edited_clip_id no distingue entre
"remix real de esta canción" y "reutilicé este audio/instrumental como
base para experimentar con otro título". El árbol se construye tal cual
lo registra Suno (opción honesta, sin recortar ramas por heurística de
título) — parientes por reutilización de base cuentan como parientes.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def safe_filename(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    keep = "-_.() "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned[:120] if cleaned else fallback


def safe_folder_name(name: str, fallback: str = "_Sin proyecto") -> str:
    if not name:
        return fallback
    name = name.strip()
    keep = "-_.() "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned[:80] if cleaned else fallback


def load_songs(backup_dir: Path, debug=False):
    """Carga todos los *.json del backup (excepto _index.json)."""
    songs = {}
    skipped = 0
    for jf in backup_dir.glob("*.json"):
        if jf.name == "_index.json":
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped += 1
            if debug:
                print(f"  [aviso] {jf.name} no es JSON válido, se salta")
            continue
        song_id = data.get("id")
        if not song_id:
            skipped += 1
            continue
        data["_json_path"] = jf
        data["_audio_path"] = jf.with_suffix(".mp3")
        img = jf.with_suffix(".jpg")
        data["_image_path"] = img if img.exists() else None
        songs[song_id] = data
    if skipped:
        print(f"[aviso] {skipped} archivo(s) saltado(s) por JSON inválido o sin id")
    return songs


def resolve_lineage(song: dict, songs_by_id: dict):
    """Devuelve (tipo, [ids_origen]) a partir de raw_metadata. Incluye
    TODOS los orígenes (para mostrar en la sección Familia), a diferencia
    de resolve_primary_parent que solo usa uno (para el árbol Dewey)."""
    raw = song.get("raw_metadata") or {}
    task = raw.get("task") or "gen"

    origin_ids = []
    if raw.get("cover_clip_id"):
        origin_ids.append(raw["cover_clip_id"])
    elif raw.get("edited_clip_id"):
        origin_ids.append(raw["edited_clip_id"])
    if raw.get("mashup_clip_ids"):
        origin_ids.extend(raw["mashup_clip_ids"])

    seen = set()
    origin_ids = [i for i in origin_ids if not (i in seen or seen.add(i))]

    return task, origin_ids


def resolve_primary_parent(song: dict, songs_by_id: dict):
    """Un único padre por pista, para construir el árbol Dewey (un mashup
    con 2 padres solo cuenta el primero como posición en el árbol; el
    segundo se sigue mostrando en la sección Familia de la nota)."""
    _, origin_ids = resolve_lineage(song, songs_by_id)
    for oid in origin_ids:
        if oid in songs_by_id and oid != song.get("id"):
            return oid
    return None


def compute_dewey_codes(songs_by_id: dict):
    """Construye el bosque genealógico (posiblemente varios árboles) y
    asigna a cada pista un código tipo '0', '0.1', '0.2.1'... Honesto con
    los datos de Suno: no recorta ramas aunque el título cambie."""
    children = {}
    roots = []
    for sid, song in songs_by_id.items():
        parent = resolve_primary_parent(song, songs_by_id)
        if parent:
            children.setdefault(parent, []).append(sid)
        else:
            roots.append(sid)

    roots.sort(key=lambda sid: songs_by_id[sid].get("created_at") or "")
    for kids in children.values():
        kids.sort(key=lambda k: songs_by_id[k].get("created_at") or "")

    codes = {}
    visited = set()

    def assign(sid, code):
        if sid in visited:  # guarda defensiva por si hay algun ciclo raro en los datos
            return
        visited.add(sid)
        codes[sid] = code
        for i, k in enumerate(children.get(sid, []), start=1):
            assign(k, f"{code}.{i}")

    for r in roots:
        assign(r, "0")

    return codes, children, roots


def compute_filenames(songs_by_id: dict, codes: dict):
    """'Titulo [codigo].md' por defecto; si dos pistas distintas colisionan
    en titulo+codigo (pasa: hay titulos duplicados reales), se desambigua
    anadiendo los primeros 8 caracteres del id -- solo a las que chocan."""
    proposals = {}
    for sid, song in songs_by_id.items():
        code = codes.get(sid, "0")
        title = safe_filename(song.get("title"), sid)
        base = f"{title} [{code}]"
        proposals.setdefault(base, []).append(sid)

    filenames = {}
    for base, ids in proposals.items():
        if len(ids) == 1:
            filenames[ids[0]] = base
        else:
            for sid in sorted(ids, key=lambda i: songs_by_id[i].get("created_at") or ""):
                filenames[sid] = f"{base} {sid[:8]}"
    return filenames


def badges_from(song: dict) -> list:
    raw = song.get("raw_metadata") or {}
    return [b.get("display_name") for b in raw.get("secondary_badges") or [] if b.get("display_name")]


def yaml_escape(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def build_frontmatter(song: dict, task: str, badges: list, code: str) -> str:
    lines = ["---"]
    lines.append(f"id: {yaml_escape(song.get('id'))}")
    lines.append(f"title: {yaml_escape(song.get('title'))}")
    lines.append(f"dewey_code: {yaml_escape(code)}")
    lines.append(f"created_at: {yaml_escape(song.get('created_at'))}")
    lines.append(f"model: {yaml_escape(song.get('model'))}")
    lines.append(f"major_model_version: {yaml_escape(song.get('major_model_version'))}")
    lines.append(f"task: {yaml_escape(task)}")
    lines.append(f"is_remix: {yaml_escape((song.get('raw_metadata') or {}).get('is_remix', False))}")
    lines.append(f"is_liked: {yaml_escape(song.get('is_liked', False))}")
    lines.append(f"style_tags: {yaml_escape(song.get('style_tags'))}")
    duration = song.get("duration") or (song.get("raw_metadata") or {}).get("duration")
    lines.append(f"duration_sec: {yaml_escape(duration)}")
    if song.get("project_name"):
        lines.append(f"project: {yaml_escape(song.get('project_name'))}")
        if song.get("project_is_trashed"):
            lines.append(f"project_is_trashed: {yaml_escape(song.get('project_is_trashed'))}")
    if badges:
        lines.append("badges:")
        for b in badges:
            lines.append(f"  - {yaml_escape(b)}")
    else:
        lines.append("badges: []")
    lines.append("---")
    return "\n".join(lines)


def build_family_section(origin_ids: list, songs_by_id: dict, filenames: dict) -> str:
    if not origin_ids:
        return "## Familia\n\nOriginal — sin pista de origen conocida."

    lines = ["## Familia", ""]
    for oid in origin_ids:
        origin = songs_by_id.get(oid)
        if origin:
            lines.append(f"- Origen: [[{filenames[oid]}]]")
        else:
            lines.append(f"- Origen: `{oid}` (no encontrado en este backup)")
    return "\n".join(lines)


def build_note(song: dict, songs_by_id: dict, filenames: dict, codes: dict) -> str:
    task, origin_ids = resolve_lineage(song, songs_by_id)
    badges = badges_from(song)
    audio_name = song["_audio_path"].name
    image_path = song.get("_image_path")
    code = codes.get(song["id"], "0")

    fm = build_frontmatter(song, task, badges, code)
    family = build_family_section(origin_ids, songs_by_id, filenames)
    tags = song.get("style_tags") or "_(sin tags)_"
    lyrics = song.get("lyrics") or "_(sin letra)_"

    heart = "❤️ " if song.get("is_liked") else ""
    parts = [
        fm,
        "",
        f"# {heart}{code} — {song.get('title') or song.get('id')}",
        "",
    ]
    if image_path:
        parts.append(f"![[Portadas/{image_path.name}|200]]")
        parts.append("")
    parts += [
        f"![[Audio/{audio_name}]]",
        "",
        family,
        "",
        "## Estilo",
        "",
        tags,
        "",
        "## Letra",
        "",
        lyrics,
        "",
    ]
    return "\n".join(parts)


def all_descendants(sid: str, children: dict) -> list:
    result = [sid]
    for c in children.get(sid, []):
        result.extend(all_descendants(c, children))
    return result


def node_marker(song: dict) -> str:
    heart = "❤️ " if song.get("is_liked") else ""
    full = "✅ " if "Full Song" in badges_from(song) else ""
    return heart + full


def build_family_summary(root_sid: str, songs_by_id: dict, filenames: dict, children: dict, members: list) -> str:
    n_total = len(members)
    n_liked = sum(1 for m in members if songs_by_id[m].get("is_liked"))
    full_ids = [m for m in members if "Full Song" in badges_from(songs_by_id[m])]

    root_title = songs_by_id[root_sid].get("title") or root_sid
    lines = [f"### {root_title}", "",
             f"**{n_total} pistas · {n_liked} ❤️ favoritas · {len(full_ids)} ✅ Full Song**", ""]
    if full_ids:
        lines.append("Cierre(s) de ciclo (Full Song):")
        for fid in sorted(full_ids, key=lambda i: songs_by_id[i].get("created_at") or ""):
            lines.append(f"- [[{filenames[fid]}]]")
        lines.append("")
    return "\n".join(lines)


def build_genealogy_file(songs_by_id: dict, filenames: dict, children: dict, roots: list) -> str:
    """Archivo separado con el linaje completo: resumen por
    familia (pistas/favoritas/Full Song, con las Full Song destacadas
    primero como 'cierre de ciclo') seguido del árbol plegable."""
    families = []
    singles = []
    for r in roots:
        members = all_descendants(r, children)
        if len(members) > 1:
            families.append((r, members))
        else:
            singles.append(r)

    families.sort(key=lambda x: -len(x[1]))

    lines = ["# 🧬 Linaje — Suno", "",
              "_Cada familia con más de una variación lleva un resumen; si alguna pista "
              "está marcada como Full Song aparece primero, para localizar rápido la que "
              "cerró el ciclo. El árbol completo va debajo, plegable con la flechita de "
              "cada línea en Obsidian._", ""]

    def emit(sid, depth):
        song = songs_by_id[sid]
        lines.append("\t" * depth + f"- {node_marker(song)}[[{filenames[sid]}]]")
        for k in children.get(sid, []):
            emit(k, depth + 1)

    for r, members in families:
        lines.append(build_family_summary(r, songs_by_id, filenames, children, members))
        emit(r, 0)
        lines.append("")
        lines.append("---")
        lines.append("")

    if singles:
        lines.append(f"## Pistas sin variaciones ({len(singles)})")
        lines.append("")
        for sid in sorted(singles, key=lambda i: songs_by_id[i].get("created_at") or ""):
            song = songs_by_id[sid]
            lines.append(f"- {node_marker(song)}[[{filenames[sid]}]]")
        lines.append("")

    return "\n".join(lines)


def build_full_liked_section(songs_by_id: dict, filenames: dict) -> str:
    ids = [sid for sid, s in songs_by_id.items()
           if s.get("is_liked") and "Full Song" in badges_from(s)]
    if not ids:
        return ""
    lines = [f"## ✅❤️ Full Song favoritas ({len(ids)})", ""]
    for sid in sorted(ids, key=lambda i: songs_by_id[i].get("created_at") or ""):
        lines.append(f"- [[{filenames[sid]}]]")
    lines.append("")
    return "\n".join(lines)


def build_badge_section(songs_by_id: dict, filenames: dict) -> str:
    lines = ["## Por tipo (badge)", ""]
    by_badge = {}
    for sid, song in songs_by_id.items():
        badges = badges_from(song)
        if not badges:
            by_badge.setdefault("_Sin badge", []).append(sid)
        for b in badges:
            by_badge.setdefault(b, []).append(sid)

    for badge, ids in sorted(by_badge.items(), key=lambda x: -len(x[1])):
        lines.append(f"### {badge} ({len(ids)})")
        lines.append("")
        for sid in sorted(ids, key=lambda i: songs_by_id[i].get("created_at") or ""):
            lines.append(f"- [[{filenames[sid]}]]")
        lines.append("")

    return "\n".join(lines)


def build_index(songs_by_id: dict, filenames: dict, children: dict, roots: list) -> str:
    lines = ["# Índice — Suno Vault", "", f"Total de pistas: {len(songs_by_id)}", ""]

    liked = [s for s in songs_by_id.values() if s.get("is_liked")]
    if liked:
        lines.append(f"## ❤️ Favoritas ({len(liked)})")
        lines.append("")
        for song in sorted(liked, key=lambda s: s.get("created_at") or ""):
            lines.append(f"- [[{filenames[song['id']]}]]")
        lines.append("")

    full_liked = build_full_liked_section(songs_by_id, filenames)
    if full_liked:
        lines.append(full_liked)

    lines.append("## 🧬 Linaje")
    lines.append("")
    lines.append("Ver [[_linaje]] — archivo separado (es grande, con resumen por familia).")
    lines.append("")

    by_project = {}
    for song in songs_by_id.values():
        name = song.get("project_name") or "_Sin proyecto"
        by_project[name] = by_project.get(name, 0) + 1
    lines.append(f"## Proyectos ({len(by_project)})")
    lines.append("")
    for name, count in sorted(by_project.items(), key=lambda x: -x[1]):
        lines.append(f"- {name}: {count}")
    lines.append("")

    by_task = {}
    for sid, song in songs_by_id.items():
        task, _ = resolve_lineage(song, songs_by_id)
        by_task.setdefault(task, []).append(song)
    for task in sorted(by_task):
        lines.append(f"## {task} ({len(by_task[task])})")
        lines.append("")
        for song in sorted(by_task[task], key=lambda s: s.get("created_at") or ""):
            lines.append(f"- [[{filenames[song['id']]}]]")
        lines.append("")

    lines.append(build_badge_section(songs_by_id, filenames))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Construye suno_vault desde un backup de Suno.")
    parser.add_argument("--backup-dir", required=True, help="Carpeta con los .json/.mp3 de backup_suno.py")
    parser.add_argument("--vault-dir", required=True, help="Carpeta de salida del vault de Obsidian")
    parser.add_argument("--no-copy-audio", action="store_true",
                         help="No copiar los .mp3/.jpg (solo generar notas)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    vault_dir = Path(args.vault_dir)
    canciones_dir = vault_dir / "Canciones"
    audio_dir = vault_dir / "Audio"
    portadas_dir = vault_dir / "Portadas"

    if not backup_dir.exists():
        print(f"[error] no existe {backup_dir}")
        sys.exit(1)

    canciones_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    portadas_dir.mkdir(parents=True, exist_ok=True)

    print("[info] cargando JSON del backup...")
    songs_by_id = load_songs(backup_dir, debug=args.debug)
    print(f"[info] {len(songs_by_id)} pistas cargadas")

    print("[info] calculando arbol genealogico (codigos Dewey)...")
    codes, children, roots = compute_dewey_codes(songs_by_id)
    print(f"[info] {len(roots)} arboles/raices detectados")

    print("[info] resolviendo nombres de nota...")
    filenames = compute_filenames(songs_by_id, codes)
    print(f"[info] {len(filenames)} nombres resueltos")

    audio_missing = 0
    audio_copied = 0
    images_copied = 0

    for i, (sid, song) in enumerate(songs_by_id.items(), start=1):
        stem = filenames[sid]
        project_folder = safe_folder_name(song.get("project_name"))
        note_dir = canciones_dir / project_folder
        note_dir.mkdir(parents=True, exist_ok=True)
        note_path = note_dir / f"{stem}.md"
        note_path.write_text(build_note(song, songs_by_id, filenames, codes), encoding="utf-8")

        if not args.no_copy_audio:
            src_audio = song["_audio_path"]
            dst_audio = audio_dir / src_audio.name
            if src_audio.exists():
                if not dst_audio.exists():
                    shutil.copy2(src_audio, dst_audio)
                    audio_copied += 1
            else:
                audio_missing += 1
                if args.debug:
                    print(f"  [aviso] audio no encontrado para '{stem}'")

            if song.get("_image_path"):
                dst_img = portadas_dir / song["_image_path"].name
                if not dst_img.exists():
                    shutil.copy2(song["_image_path"], dst_img)
                    images_copied += 1

        if i % 200 == 0:
            print(f"[info] {i}/{len(songs_by_id)} notas escritas")

    index_path = vault_dir / "_index_suno.md"
    index_path.write_text(build_index(songs_by_id, filenames, children, roots), encoding="utf-8")

    genealogy_path = vault_dir / "_linaje.md"
    genealogy_path.write_text(build_genealogy_file(songs_by_id, filenames, children, roots), encoding="utf-8")

    print(f"\n[hecho] {len(filenames)} notas escritas en {canciones_dir}")
    if not args.no_copy_audio:
        print(f"[hecho] {audio_copied} audios copiados a {audio_dir}")
        print(f"[hecho] {images_copied} portadas copiadas a {portadas_dir}")
        if audio_missing:
            print(f"[aviso] {audio_missing} audio(s) no encontrados en el backup")
    print(f"[hecho] indice: {index_path}")
    print(f"[hecho] linaje: {genealogy_path}")


if __name__ == "__main__":
    main()
