# -*- coding: utf-8 -*-
"""providers/newclaude_adapter.py -- Adaptador del NUEVO formato de export
de Claude (claude.ai) al modelo intermedio de MemorIA2GO.

Anthropic cambio silenciosamente el formato del export en agosto/septiembre
de 2026 (unificacion de memoria entre chat y Cowork, ver
https://support.claude.com/en/articles/12123587). Lo que antes era UN zip
con conversations.json + users.json + projects.json ahora es un
MANIFIESTO JSON + 5 ZIPS DE UN SOLO USO, cada uno con su categoria:

    manifest-<uuid>-<ts>-<sig>-<AAAA-MM-DD-HH-MM-SS>.json
    ├── light_metadata-000.zip  (users.json + login_history.json)
    ├── projects-000.zip        (projects/<uuid>.json, uno por proyecto)
    ├── memories-000.zip        (memories/<user_uuid>.json, memoria persistente)
    ├── frames-000.zip          (artifacts/<uuid>/... versiones + comentarios)
    └── conversations-000.zip   (conversations.json monolitico, mismo formato)

No hay anuncio oficial (comprobado en el Privacy Center y en changelogs
publicos, 2026-09-21). El unico rastro publico es un issue de terceros:
https://github.com/ukogan/claude-migration-assistant/issues/4

DECISIONES DE DISEÑO (ver bck/NewClaude/PLAN.md):

- `conversations.json` interno TIENE la misma forma que el export viejo.
  Verificado contra el export real de V0ra 2026-09-20 (264 convs, 13.935
  mensajes): claves de conversacion y de mensaje identicas a KNOWN_KEYS
  del claude_adapter. Este adaptador delega en `claude_adapter.parse`
  para las conversaciones y no re-implementa nada.
- El `source` que se emite es `claude_export`, NO `newclaude_export`.
  Motivo: el pipeline usa `conv_id` como identidad de conversacion en
  vault_merge (verificado en vault_merge.py:199, `key = f"id:{cid}"`);
  si el `source` divergiera, las variantes del mismo `conv_id` de dos
  exports (viejo y nuevo) no se fusionarian coherentemente. Con el
  mismo `source`, vault_merge las fusiona y recupera mensajes nuevos.
- `memories`, `frames`, `projects` y `light_metadata` NO se ingestan en
  esta version del adaptador. Se preservan en su banco crudo y se
  atacan por fases (ver plan).

Este adaptador NO se conecta al detector automatico
(split_chatgpt_export._dispatch) todavia: la Fase A del plan es
fundacional (parseo + tests), la Fase B lo cablea al pipeline.
"""
from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers import claude_adapter

# Caracteres que Windows no acepta en nombres de fichero/carpeta. Se
# sustituyen por "_"; los acentos y espacios se conservan (Obsidian
# los maneja bien y son parte del nombre humano que V0ra quiere ver).
_WIN_UNSAFE_RX = re.compile(r'[\\/:*?"<>|]')


def _sanear_nombre_windows(nombre: str) -> str:
    """Sanea un nombre para uso como carpeta/fichero en Windows sin
    aplanarlo a slug agresivo. Solo sustituye los 9 caracteres
    prohibidos y colapsa espacios en blanco duplicados; no toca
    mayusculas, acentos, guiones ni espacios sueltos."""
    s = _WIN_UNSAFE_RX.sub("_", nombre or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Puntos y espacios finales tampoco valen (Windows los recorta al
    # crear la ruta y produce colisiones invisibles).
    s = s.rstrip(". ")
    return s or "sin_nombre"


def _yaml_val(v: Any) -> str:
    """Serializa un valor Python a un YAML minimo suficiente para el
    frontmatter de las notas: string entre comillas dobles con las
    comillas escapadas a simples, bool/None sin comillas, numeros
    directos."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace('"', "'") + '"'

# Las cinco categorias que el manifiesto debe listar. Si aparece una
# categoria fuera de este conjunto, o si falta alguna esperada, es señal
# de que Anthropic volvio a mover el formato -- preflight avisa, no
# bloquea (misma disciplina que KNOWN_KEYS en el adaptador viejo).
KNOWN_CATEGORIES = frozenset({
    "light_metadata", "projects", "memories", "frames", "conversations",
})

# Claves esperadas en el manifiesto JSON. `version` puede subir sin
# romper compatibilidad; se mira, no se exige valor concreto.
MANIFEST_KEYS = frozenset({
    "instructions", "created_at", "total_files", "data_files", "version",
})

# Claves esperadas en cada entrada de `data_files` del manifiesto.
DATA_FILE_KEYS = frozenset({
    "batch_index", "export_url", "category", "part", "filename",
})


def detect_manifest(data: Any) -> bool:
    """True si `data` (JSON ya cargado) es el manifiesto del nuevo export.

    Se identifica por la combinacion: dict raiz con `data_files` (lista),
    cada entrada un dict con `category` y `filename`, y por lo menos una
    categoria del conjunto conocido. Deliberadamente PERMISIVO en las
    claves opcionales (`instructions`, `version`, `total_files`,
    `created_at`) para que un cambio menor del formato no rompa la
    deteccion; el aviso de deriva es responsabilidad del que llame."""
    if not isinstance(data, dict):
        return False
    dfs = data.get("data_files")
    if not isinstance(dfs, list) or not dfs:
        return False
    if not all(isinstance(d, dict) and "category" in d and "filename" in d
               for d in dfs):
        return False
    cats = {d.get("category") for d in dfs}
    return bool(cats & KNOWN_CATEGORIES)


def detect_layout(carpeta: Any) -> bool:
    """True si `carpeta` (Path o str) es una carpeta descomprimida del
    nuevo export.

    Reconoce la estructura resultante de descomprimir los 5 zips: cinco
    subcarpetas hermanas `<categoria>-NNN/` (habitualmente `-000`), cada
    una con el contenido de su zip. Se admite que falte alguna categoria
    (por ejemplo, si el usuario solo descomprimio conversations-000.zip
    para probar): la señal minima es que exista `conversations-NNN/` con
    un `conversations.json` dentro."""
    p = Path(carpeta)
    if not p.is_dir():
        return False
    # Buscar la subcarpeta de conversaciones (el minimo viable).
    for sub in p.iterdir():
        if not sub.is_dir():
            continue
        nombre = sub.name.lower()
        if nombre.startswith("conversations-") and (sub / "conversations.json").is_file():
            return True
    return False


def _find_subdir(carpeta: Path, categoria: str) -> Optional[Path]:
    """Busca la subcarpeta `<categoria>-NNN/` dentro de `carpeta`. Devuelve
    la primera que encuentre (habitualmente `-000`); None si no existe."""
    prefijo = categoria.lower() + "-"
    for sub in carpeta.iterdir():
        if sub.is_dir() and sub.name.lower().startswith(prefijo):
            return sub
    return None


def parse_conversations(carpeta: Any) -> List[Dict[str, Any]]:
    """Lee conversations.json de una carpeta descomprimida del nuevo
    export y lo devuelve ya parseado por `claude_adapter.parse`.

    Delega TODO el trabajo semantico al adaptador viejo: el formato
    interno de conversations.json no cambio, y re-implementarlo aqui
    seria duplicar 230 lineas de logica (threading por
    parent_message_uuid, resolucion de artefactos, attachments,
    rendering...) que ya estan probadas."""
    p = Path(carpeta)
    conv_dir = _find_subdir(p, "conversations")
    if conv_dir is None:
        return []
    conv_json = conv_dir / "conversations.json"
    if not conv_json.is_file():
        return []
    import json
    with conv_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return claude_adapter.parse(data)


def categorias_del_manifiesto(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Dado un manifiesto valido (`detect_manifest(data)` True), devuelve
    `{"conocidas": [...], "desconocidas": [...]}` en el orden en que
    aparecen en `data_files`. Util para que preflight avise si Anthropic
    añade una categoria nueva (misma señal que las claves nuevas)."""
    conocidas, desconocidas = [], []
    for d in data.get("data_files") or []:
        cat = d.get("category")
        if cat in KNOWN_CATEGORIES:
            conocidas.append(cat)
        elif cat:
            desconocidas.append(cat)
    return {"conocidas": conocidas, "desconocidas": desconocidas}


# ─────────────────────────────────────────
# projects: un JSON por proyecto en projects-NNN/projects/<uuid>.json
# ─────────────────────────────────────────
# Claves observadas contra el export real de V0ra (24 proyectos,
# 2026-09-20). Mismo criterio de KNOWN_KEYS que el resto de adaptadores:
# si aparece una clave fuera de este set, es señal de deriva y preflight
# lo dira. No bloquea la ingesta.

KNOWN_PROJECT_KEYS = frozenset({
    "uuid", "name", "description", "is_private", "is_starter_project",
    "prompt_template", "created_at", "updated_at", "creator", "docs",
})

KNOWN_DOC_KEYS = frozenset({
    "uuid", "filename", "content", "created_at",
})


def parse_projects(carpeta: Any) -> List[Dict[str, Any]]:
    """Recorre projects-NNN/projects/*.json y devuelve un dict normalizado
    por proyecto. NO escribe nada al vault: la decision de ubicacion (D3
    del PLAN) queda para cuando V0ra elija entre `Proyectos/` (existente)
    o `CLAUDE_WEB/PROJECTS/` (banco propio).

    Forma de salida:
        {"uuid": str,
         "name": str,
         "description": str,
         "prompt_template": str,       # instrucciones del proyecto (system prompt)
         "is_private": bool,
         "is_starter_project": bool,
         "created_at": float | None,   # epoch en segundos (formato del pipeline)
         "updated_at": float | None,
         "creator": {"uuid": str, "full_name": str},
         "docs": [{"uuid","filename","content","created_at"}, ...],
         "provider": "claude"}

    Un proyecto vacio (sin docs) tambien se emite: sigue siendo un
    proyecto real de la cuenta de la persona; el pipeline decide luego
    si merece nota."""
    p = Path(carpeta)
    proj_dir = _find_subdir(p, "projects")
    if proj_dir is None:
        return []
    inner = proj_dir / "projects"
    if not inner.is_dir():
        return []
    import json
    out: List[Dict[str, Any]] = []
    for fp in sorted(inner.glob("*.json")):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Un proyecto ilegible no debe tumbar el resto; se salta.
            continue
        docs_out: List[Dict[str, Any]] = []
        for doc in d.get("docs") or []:
            if not isinstance(doc, dict):
                continue
            docs_out.append({
                "uuid": doc.get("uuid"),
                "filename": (doc.get("filename") or "").strip(),
                "content": doc.get("content") or "",
                "created_at": claude_adapter._epoch(doc.get("created_at")),
            })
        creator = d.get("creator") or {}
        out.append({
            "uuid": d.get("uuid"),
            "name": (d.get("name") or "").strip(),
            "description": (d.get("description") or "").strip(),
            "prompt_template": (d.get("prompt_template") or "").strip(),
            "is_private": bool(d.get("is_private")),
            "is_starter_project": bool(d.get("is_starter_project")),
            "created_at": claude_adapter._epoch(d.get("created_at")),
            "updated_at": claude_adapter._epoch(d.get("updated_at")),
            "creator": {
                "uuid": creator.get("uuid"),
                "full_name": (creator.get("full_name") or "").strip(),
            },
            "docs": docs_out,
            "provider": "claude",
        })
    return out


# ─────────────────────────────────────────
# frames = artifacts, con historial de versiones y comentarios
# ─────────────────────────────────────────
# Estructura por artifact (verificada contra el export real 2026-09-20):
#   frames-NNN/artifacts/<artifact_id>/
#     artifact.json          -- metadatos: id, kind, visibility, versions[],
#                               owner_account, updated_at, active_version
#     artifact_comments.json -- OPCIONAL (2/10 en el export real): dict
#                               con "threads": [{comments:[...], resolved,
#                               carried, created_at}]
#     versions/<ver_id>.html -- fichero real de cada version, servido
#                               como HTML autocontenido
#
# El adaptador solo *inventaria* las versiones (id, titulo, tamaño,
# ruta a disco). NO lee el contenido HTML aqui: son 118 ficheros en
# el export real y el consumidor los abrira segun necesite.

KNOWN_FRAME_KEYS = frozenset({
    "id", "kind", "visibility", "versions", "owner_account",
    "updated_at", "active_version",
})

KNOWN_VERSION_KEYS = frozenset({
    "id", "title", "description", "created_at",
})

KNOWN_THREAD_KEYS = frozenset({
    "created_at", "resolved", "carried", "comments",
})

KNOWN_COMMENT_KEYS = frozenset({
    "author_index", "author_role", "author_is_artifact_owner",
    "text", "created_at", "to_claude_at",
})


def parse_frames(carpeta: Any) -> List[Dict[str, Any]]:
    """Recorre frames-NNN/artifacts/<uuid>/ y devuelve un inventario
    normalizado por artifact. NO escribe nada.

    Forma de salida por artifact:
        {"id": str,
         "kind": str,               # 'artifact' hasta ahora, deja el hueco
         "visibility": str,         # 'private'/'public'/...
         "owner_account": str,      # uuid de la persona
         "updated_at": float | None,
         "active_version": str,     # id de la version activa
         "versions": [               # metadatos + ruta al HTML en disco
             {"id": str, "title": str, "description": str,
              "created_at": float | None, "path": Path, "size": int}, ...
         ],
         "threads": [                # comentarios (vacio si no hay fichero)
             {"created_at","resolved","carried",
              "comments":[{"author_index","author_role",
                           "author_is_artifact_owner","text",
                           "created_at","to_claude_at"}]}
         ],
         "provider": "claude"}

    Las versiones se devuelven en el mismo orden que artifact.json las
    lista; esa lista suele ir de mas antigua a mas reciente pero no se
    reordena aqui (el consumidor decide como pintarlo)."""
    p = Path(carpeta)
    frames_dir = _find_subdir(p, "frames")
    if frames_dir is None:
        return []
    inner = frames_dir / "artifacts"
    if not inner.is_dir():
        return []
    import json
    out: List[Dict[str, Any]] = []
    for adir in sorted(inner.iterdir()):
        if not adir.is_dir():
            continue
        art_json = adir / "artifact.json"
        if not art_json.is_file():
            continue
        try:
            a = json.loads(art_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        versions_out: List[Dict[str, Any]] = []
        versions_dir = adir / "versions"
        for v in a.get("versions") or []:
            if not isinstance(v, dict):
                continue
            vid = v.get("id")
            # Localizar el HTML en disco por su id (nombre = <id>.html).
            vpath = None
            vsize = 0
            if vid and versions_dir.is_dir():
                cand = versions_dir / f"{vid}.html"
                if cand.is_file():
                    vpath = cand
                    vsize = cand.stat().st_size
            versions_out.append({
                "id": vid,
                "title": (v.get("title") or "").strip(),
                "description": (v.get("description") or "").strip(),
                "created_at": claude_adapter._epoch(v.get("created_at")),
                "path": vpath,
                "size": vsize,
            })

        threads_out: List[Dict[str, Any]] = []
        cpath = adir / "artifact_comments.json"
        if cpath.is_file():
            try:
                cdata = json.loads(cpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cdata = None
            if isinstance(cdata, dict):
                for th in cdata.get("threads") or []:
                    if not isinstance(th, dict):
                        continue
                    comentarios = []
                    for co in th.get("comments") or []:
                        if not isinstance(co, dict):
                            continue
                        comentarios.append({
                            "author_index": co.get("author_index"),
                            "author_role": (co.get("author_role") or "").strip(),
                            "author_is_artifact_owner": bool(co.get("author_is_artifact_owner")),
                            "text": co.get("text") or "",
                            "created_at": claude_adapter._epoch(co.get("created_at")),
                            "to_claude_at": claude_adapter._epoch(co.get("to_claude_at")),
                        })
                    threads_out.append({
                        "created_at": claude_adapter._epoch(th.get("created_at")),
                        "resolved": bool(th.get("resolved")),
                        "carried": bool(th.get("carried")),
                        "comments": comentarios,
                    })

        out.append({
            "id": a.get("id"),
            "kind": (a.get("kind") or "").strip(),
            "visibility": (a.get("visibility") or "").strip(),
            "owner_account": a.get("owner_account"),
            "updated_at": claude_adapter._epoch(a.get("updated_at")),
            "active_version": a.get("active_version"),
            "versions": versions_out,
            "threads": threads_out,
            "provider": "claude",
        })
    return out


# ─────────────────────────────────────────
# memories: dossier personal + memoria vault-style + resumenes por proyecto
# ─────────────────────────────────────────
# Este JSON es sensible: contiene el perfil personal que Claude ha
# acumulado (V0ra: 25 anios en infra/identity, BNP Paribas, familia,
# perfil ND...). Va aparte del vault principal.

def parse_memories(carpeta: Any) -> Optional[Dict[str, Any]]:
    """Lee el unico JSON dentro de memories-NNN/memories/ y devuelve las
    cuatro secciones:
        {"conversations_memory": str,   # dossier personal
         "project_memories": {uuid: str, ...},  # resumen por proyecto
         "memory_files": [{"path", "content", "updated_at"}, ...],
         "account_uuid": str}

    Devuelve None si no hay JSON (layout parcial sin memories). Los
    campos individuales pueden faltar del JSON: se rellenan a valor
    vacio para que el consumidor no tenga que defenderse por cada uno."""
    p = Path(carpeta)
    mem_dir = _find_subdir(p, "memories")
    if mem_dir is None:
        return None
    inner = mem_dir / "memories"
    if not inner.is_dir():
        return None
    import json
    files = sorted(inner.glob("*.json"))
    if not files:
        return None
    # En el export real solo hay UN fichero (nombrado por account_uuid).
    # Si Anthropic diera algun dia varios, procesamos el primero y el
    # resto queda para una futura decision -- no se pierde nada (el
    # zip crudo esta preservado).
    try:
        d = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mfs = []
    for m in d.get("memory_files") or []:
        if not isinstance(m, dict):
            continue
        mfs.append({
            "path": (m.get("path") or "").strip(),
            "content": m.get("content") or "",
            "updated_at": claude_adapter._epoch(m.get("updated_at")),
        })
    return {
        "conversations_memory": d.get("conversations_memory") or "",
        "project_memories": dict(d.get("project_memories") or {}),
        "memory_files": mfs,
        "account_uuid": (d.get("account_uuid") or "").strip(),
    }


# ─────────────────────────────────────────
# ESCRITURA: los tres writers, uno por categoria
# ─────────────────────────────────────────
# Todos son idempotentes por contenido: releen el fichero destino antes
# de reescribirlo y saltan si no ha cambiado. No borran ficheros
# preexistentes (una reingesta no destruye ediciones a mano de V0ra en
# el vault entre pasadas).


def _escribe_si_cambio(p: Path, texto: str) -> bool:
    """Escribe `texto` en `p` solo si el contenido difiere del actual.
    Devuelve True si escribio, False si salto. Crea el directorio padre
    si hace falta. Encoding UTF-8, newline LF (mismo criterio que
    write_md)."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    if p.exists():
        try:
            if p.read_text(encoding="utf-8") == texto:
                return False
        except OSError:
            pass
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return True


def _copia_si_cambio(origen: Path, destino: Path) -> bool:
    """Copia binaria de un fichero al destino solo si el destino no
    existe o su tamaño no coincide. Se compara por tamaño y no por
    hash para no leer 100 MB de HTML en cada pasada; el caso adverso
    (contenido distinto con mismo tamaño) es teorico -- el HTML lleva
    timestamp+hash en el nombre, cambia siempre."""
    if destino.exists() and destino.stat().st_size == origen.stat().st_size:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)
    return True


def _fmt_fecha(epoch: Optional[float]) -> str:
    """Epoch -> AAAA-MM-DD HH:MM para el frontmatter. Sin timezone: el
    resto del vault es tz-local implicito (ver iso_date en
    split_chatgpt_export)."""
    if not epoch:
        return ""
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def write_projects(carpeta: Any, prj_vault: Any) -> Dict[str, Any]:
    """Escribe los proyectos del export nuevo a `<prj_vault>/<name>/`.
    Ver D3 en bck/NewClaude/PLAN.md.

    Por cada proyecto:
        <prj_vault>/<name>/00_proyecto.md
        <prj_vault>/<name>/_docs/<filename>   (uno por doc, si los hay)

    Devuelve stats {"proyectos": n, "docs": n, "escritas": n, "saltadas": n}."""
    prj_vault = Path(prj_vault)
    stats = {"proyectos": 0, "docs": 0, "escritas": 0, "saltadas": 0}
    for pr in parse_projects(carpeta):
        nombre_carp = _sanear_nombre_windows(pr["name"])
        raiz = prj_vault / nombre_carp
        # 00_proyecto.md
        pares = [
            ("tipo", "proyecto-claude"),
            ("name", pr["name"]),
            ("uuid", pr["uuid"]),
            ("provider", "claude"),
            ("visibility", "private" if pr["is_private"] else "public"),
            ("starter", pr["is_starter_project"]),
            ("creator", pr["creator"].get("full_name") or ""),
            ("creator_uuid", pr["creator"].get("uuid") or ""),
            ("created_at", _fmt_fecha(pr["created_at"])),
            ("updated_at", _fmt_fecha(pr["updated_at"])),
            ("source", "claude_export"),
        ]
        L = ["---"]
        for k, v in pares:
            L.append(f"{k}: {_yaml_val(v)}")
        L += ["---", "", f"# {pr['name']}", ""]
        if pr["description"]:
            L += ["> " + pr["description"].replace("\n", "\n> "), ""]
        if pr["prompt_template"]:
            L += ["## Instrucciones del proyecto", "",
                  "```", pr["prompt_template"], "```", ""]
        # Enlace a la memoria de Claude sobre este proyecto (D4).
        L += ["## Memoria de Claude sobre este proyecto", "",
              f"Ver `Claude_Mem/projects/{pr['uuid']}/index.md` y "
              f"`Claude_Mem/projects/{pr['uuid']}/overview.md` (si existen).",
              ""]
        # Lista de docs
        if pr["docs"]:
            L += [f"## Docs del project knowledge ({len(pr['docs'])})", ""]
            for d in pr["docs"]:
                fn = _sanear_nombre_windows(d["filename"]) or "sin_nombre"
                L.append(f"- [[_docs/{fn}]]")
            L.append("")
        else:
            L += ["## Docs del project knowledge", "",
                  "*(este proyecto no tiene project knowledge en el export)*", ""]
        texto = "\n".join(L).rstrip() + "\n"
        if _escribe_si_cambio(raiz / "00_proyecto.md", texto):
            stats["escritas"] += 1
        else:
            stats["saltadas"] += 1
        # _docs/<filename>
        for d in pr["docs"]:
            fn = _sanear_nombre_windows(d["filename"]) or "sin_nombre"
            # El contenido va tal cual: son ficheros de conocimiento
            # subidos por V0ra al proyecto, no notas del vault. No
            # se anaden frontmatter ni cabeceras -- solo se preserva.
            if _escribe_si_cambio(raiz / "_docs" / fn, d["content"]):
                stats["escritas"] += 1
            else:
                stats["saltadas"] += 1
            stats["docs"] += 1
        stats["proyectos"] += 1
    return stats


def write_frames(carpeta: Any, banco_dir: Any) -> Dict[str, Any]:
    """Escribe los artifacts del export nuevo a `<banco_dir>/<id>/`.
    banco_dir tipico: `<base_vault>/MERGED_VAULT/CLAUDE_WEB/FRAMES/`.

    Por cada artifact:
        <banco>/<id>/00_frame.md          (metadatos + comentarios)
        <banco>/<id>/versions/<ver>.html  (copia binaria de cada version)

    Devuelve stats {"frames": n, "versiones": n, "comentarios": n,
                    "escritas": n, "saltadas": n}."""
    banco_dir = Path(banco_dir)
    stats = {"frames": 0, "versiones": 0, "comentarios": 0,
             "escritas": 0, "saltadas": 0}
    for fr in parse_frames(carpeta):
        aid = fr["id"] or "sin_id"
        raiz = banco_dir / aid
        # Titulo humano: la version activa suele tener uno legible.
        titulo = ""
        for v in fr["versions"]:
            if v["id"] == fr["active_version"] and v["title"]:
                titulo = v["title"]
                break
        if not titulo and fr["versions"]:
            titulo = fr["versions"][-1]["title"] or aid
        titulo = titulo or aid

        pares = [
            ("tipo", "frame-claude"),
            ("id", aid),
            ("kind", fr["kind"]),
            ("visibility", fr["visibility"]),
            ("owner_account", fr["owner_account"]),
            ("active_version", fr["active_version"]),
            ("updated_at", _fmt_fecha(fr["updated_at"])),
            ("provider", "claude"),
            ("source", "claude_export"),
        ]
        L = ["---"]
        for k, v in pares:
            L.append(f"{k}: {_yaml_val(v)}")
        L += ["---", "", f"# {titulo}", ""]

        # Lista de versiones (mas reciente arriba)
        L += [f"## Versiones ({len(fr['versions'])})", ""]
        for v in sorted(fr["versions"], key=lambda x: x["created_at"] or 0, reverse=True):
            marca = "  ← activa" if v["id"] == fr["active_version"] else ""
            fecha = _fmt_fecha(v["created_at"])
            tam_kb = f"{v['size']/1024:.1f} KB" if v["size"] else ""
            L.append(f"- `{v['id']}` · {v['title'] or '(sin titulo)'} · {fecha} · {tam_kb}{marca}")
            if v["description"] and v["description"] != v["title"]:
                L.append(f"  {v['description']}")
        L.append("")

        # Comentarios (si los hay)
        if fr["threads"]:
            L += [f"## Comentarios ({sum(len(t['comments']) for t in fr['threads'])})", ""]
            for th in sorted(fr["threads"], key=lambda t: t["created_at"] or 0):
                estado = "resuelto" if th["resolved"] else "abierto"
                L += [f"### Hilo del {_fmt_fecha(th['created_at'])} · {estado}", ""]
                for co in th["comments"]:
                    autor = co["author_role"] or "usuario"
                    marca_owner = " (owner)" if co["author_is_artifact_owner"] else ""
                    L += [f"**{autor}{marca_owner}** — {_fmt_fecha(co['created_at'])}", ""]
                    L += [co["text"], ""]
                    stats["comentarios"] += 1
        texto = "\n".join(L).rstrip() + "\n"
        if _escribe_si_cambio(raiz / "00_frame.md", texto):
            stats["escritas"] += 1
        else:
            stats["saltadas"] += 1

        # Copia binaria de cada version HTML
        for v in fr["versions"]:
            if v["path"] is None:
                continue
            destino = raiz / "versions" / f"{v['id']}.html"
            if _copia_si_cambio(v["path"], destino):
                stats["escritas"] += 1
            else:
                stats["saltadas"] += 1
            stats["versiones"] += 1

        stats["frames"] += 1
    return stats


def write_memories(carpeta: Any, claude_mem_dir: Any) -> Dict[str, Any]:
    """Escribe las memorias a `<claude_mem_dir>/`. claude_mem_dir tipico:
    `<base_vault>/Claude_Mem/`. Ver D2 y D4 en bck/NewClaude/PLAN.md.

    Estructura respetada (D4, path literal):
        <claude_mem>/profile.md            (dossier personal breve)
        <claude_mem>/conversations.md      (conversations_memory largo)
        <claude_mem>/projects/<uuid>/…     (memoria por proyecto)
        <claude_mem>/areas/…               (temas de trabajo)
        <claude_mem>/people/…              (personas cercanas)
        <claude_mem>/topics/…              (temas personales)
        <claude_mem>/project_summaries.md  (resumenes textuales por proyecto)

    Devuelve stats {"secciones", "memory_files", "escritas", "saltadas"}."""
    claude_mem_dir = Path(claude_mem_dir)
    stats = {"secciones": 0, "memory_files": 0, "escritas": 0, "saltadas": 0}
    mem = parse_memories(carpeta)
    if mem is None:
        return stats

    # 1) conversations_memory: el dossier personal largo. Se escribe
    # como fichero unico con encabezado, no como parte de profile.md,
    # porque puede ser muy largo (6.7 KB en el export real) y merece
    # su nota propia con historial de cambios via reingestas.
    if mem["conversations_memory"]:
        L = ["---",
             'tipo: "memoria-conversaciones"',
             'provider: "claude"',
             f'account_uuid: "{mem["account_uuid"]}"',
             'source: "claude_export"',
             "---", "",
             "# Memoria de Claude sobre las conversaciones", "",
             "> Dossier personal que Claude ha acumulado a partir de las "
             "conversaciones de V0ra. Se regenera desde el proveedor en cada "
             "export; para editarlo/borrarlo, usar la UI de claude.ai.",
             "",
             mem["conversations_memory"].strip(), ""]
        if _escribe_si_cambio(claude_mem_dir / "conversations.md",
                              "\n".join(L).rstrip() + "\n"):
            stats["escritas"] += 1
        else:
            stats["saltadas"] += 1
        stats["secciones"] += 1

    # 2) project_memories: resumen textual por proyecto (dict
    # uuid->texto). Se escribe una nota unica con todos, para que sea
    # facil escanear la vista de conjunto que Claude tiene de los
    # proyectos de V0ra.
    if mem["project_memories"]:
        L = ["---",
             'tipo: "memoria-proyectos"',
             'provider: "claude"',
             f'account_uuid: "{mem["account_uuid"]}"',
             'source: "claude_export"',
             "---", "",
             "# Memoria de Claude por proyecto", "",
             f"> {len(mem['project_memories'])} proyectos con resumen textual. "
             "El UUID enlaza con los proyectos en `PRJ_VAULT/` y con las "
             "carpetas `projects/<uuid>/` de este mismo vault.",
             ""]
        for uuid_, texto in sorted(mem["project_memories"].items()):
            L += [f"## {uuid_}", "", texto.strip(), ""]
        if _escribe_si_cambio(claude_mem_dir / "project_summaries.md",
                              "\n".join(L).rstrip() + "\n"):
            stats["escritas"] += 1
        else:
            stats["saltadas"] += 1
        stats["secciones"] += 1

    # 3) memory_files: 71 notas con path literal. Se replica la
    # estructura tal cual (D4). Cada fichero ya lleva su propio
    # frontmatter dentro del content -- no se aumenta, solo se
    # preserva.
    for m in mem["memory_files"]:
        # El path llega como '/areas/foo.md'. lstrip('/') para
        # convertirlo en relativo. Luego se sanea cada segmento por
        # separado (por si algun path tuviera caracteres prohibidos
        # en Windows -- no vistos en el export real pero robusto).
        rel = m["path"].lstrip("/").lstrip("\\")
        if not rel:
            continue
        segmentos = [_sanear_nombre_windows(s) for s in rel.replace("\\", "/").split("/")]
        # Defensa contra path traversal ("..") aunque el export no lo
        # traiga: nunca escribir fuera del claude_mem_dir.
        segmentos = [s for s in segmentos if s and s != ".."]
        if not segmentos:
            continue
        destino = claude_mem_dir.joinpath(*segmentos)
        # Comprobacion final: destino tiene que estar bajo claude_mem_dir.
        try:
            destino.resolve().relative_to(claude_mem_dir.resolve())
        except ValueError:
            continue
        if _escribe_si_cambio(destino, m["content"]):
            stats["escritas"] += 1
        else:
            stats["saltadas"] += 1
        stats["memory_files"] += 1

    return stats


# ─────────────────────────────────────────
# Orquestador: ingesta las cuatro categorias no-conversation
# ─────────────────────────────────────────
# Las conversaciones ya van por la ruta existente (load_conversations +
# write_md + vault_merge). Esta funcion cubre lo que sobra: projects,
# frames, memories. light_metadata sigue sin ingestar (metadatos de
# cuenta, sin valor de vault).

def ingest_extras(carpeta: Any, base_vault: Any,
                  prj_vault_name: str = "PRJ_VAULT") -> Dict[str, Any]:
    """Ingesta las categorias del layout nuevo que no son conversaciones.
    Idempotente: se puede reejecutar sin duplicar.

    Rutas fijadas (segun D2/D3/D4 en bck/NewClaude/PLAN.md):
        base_vault/PRJ_VAULT/<name>/…               (D3)
        base_vault/MERGED_VAULT/CLAUDE_WEB/FRAMES/…  (banco propio)
        base_vault/Claude_Mem/…                     (D2, vault nuevo)

    Devuelve {"projects": stats, "frames": stats, "memories": stats}."""
    base_vault = Path(base_vault)
    return {
        "projects": write_projects(carpeta, base_vault / prj_vault_name),
        "frames": write_frames(carpeta, base_vault / "MERGED_VAULT" / "CLAUDE_WEB" / "FRAMES"),
        "memories": write_memories(carpeta, base_vault / "Claude_Mem"),
    }
