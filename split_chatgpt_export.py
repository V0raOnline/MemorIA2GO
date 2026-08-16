#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_chatgpt_export.py — Export de ChatGPT → Markdown para Obsidian (Python 3.11+)

Incluye:
- --gizmo-map para mapear IDs a nombres (acepta claves g-*, g-p-* o HEX; lookup tolerante)
- --date-field create|update y --include-both-dates
- --force-project-id / --force-project y --project-tag
- Siempre escribe Project_name: "<nombre>" o "none"
- --assets-dir: extrae imágenes (subidas y generadas) a una carpeta de assets,
  deduplicadas por hash, con degradado explícito si el binario no está en el export.
- Bloques tether_quote (archivos cargados como contexto) renderizados legibles
  como "📄 Archivo cargado: **nombre**" en vez de dict crudo.

Evita statements en una sola línea con ';' para máxima compatibilidad.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile
from typing import Any, Dict, List, Optional, Tuple

# Los adaptadores multi-proveedor viven en providers/; asegurar que el paquete
# es importable aunque el script se invoque desde otro directorio de trabajo.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from providers import claude_adapter
from providers import grok_adapter

GENERIC_TITLES = {
    "", "conversación", "conversation", "new chat", "conversación nueva",
    "untitled", "sin título", "chat", "chatgpt conversation"
}

UUID_SUFFIX_RE = re.compile(
    r'^(?P<id>.+)-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.(?P<ext>\w+)$'
)
IMAGE_TOKEN_RE = re.compile(r"\x00IMG:(?P<pointer>[^\x00]+)\x00")

# Claves de nivel superior de cada conversacion que parse_json_conversations
# conoce y consume (clasico + fragmentado 2026+), MAS las que se han
# revisado y confirmado inofensivas (metadatos de sesion/UI que el parser
# no necesita). Usado por preflight.detect_new_keys para avisar (no
# bloquear) de deriva de formato: es el chequeo que hubiera detectado
# conversation_template_id antes de que se perdiera en silencio.
#
# Catch-up 2026-07-22 (21 claves, medidas contra los 47 exports reales de
# V0ra): revisadas una a una antes de anadirlas -- gizmo_type ("gpt" vs
# "snorlax" = GPT custom vs. Proyecto nativo) y conversation_origin
# preocupaban por sonar a clasificacion de proyecto, pero gizmo_type
# siempre aparece junto a gizmo_id/conversation_template_id ya poblados
# (2094 + 423 conversaciones verificadas, nunca uno sin el otro) y
# conversation_origin nunca trae valor real en los datos de V0ra. Ninguna
# de las 21 escondia un caso como el de conversation_template_id.
CHATGPT_KNOWN_KEYS = frozenset({
    "title", "create_time", "createTime", "update_time", "updateTime",
    "gizmo_id", "gizmoId", "mapping", "current_node", "messages", "items",
    "conversation_id", "id", "conversation_template_id", "memory_scope",
    "async_status", "atlas_mode_enabled", "blocked_urls", "context_scopes",
    "conversation_origin", "default_model_slug", "disabled_tool_ids",
    "gizmo_type", "is_archived", "is_do_not_remember", "is_read_only",
    "is_starred", "is_study_mode", "moderation_results", "owner",
    "pinned_time", "plugin_ids", "safe_urls", "sugar_item_id",
    "sugar_item_visible", "voice",
})


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text or "sin-titulo"


def iso_date(ts: Any) -> str:
    try:
        if ts is None:
            return datetime.datetime.now().strftime("%Y-%m-%d")
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d")


def iso_date_or_none(ts: Any):
    try:
        if ts is None:
            return None
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        return None


def word_count(t: str) -> int:
    return len(re.findall(r"\w+", t or "", flags=re.UNICODE))


def smart_title(title: str, messages: List[Dict[str, str]], max_words: int = 8) -> str:
    t = (title or "").strip().lower()
    if not t or t in GENERIC_TITLES:
        for m in messages or []:
            if (m.get("role") or "").lower() == "user":
                txt = (m.get("content") or "").strip()
                if txt:
                    words = re.findall(r"\w+(?:['’]\w+)?|[^\w\s]", txt, flags=re.UNICODE)
                    cand = " ".join([w for w in words if w.strip()][:max_words]).strip()
                    return cand or "Conversación"
    return title or "Conversación"


def content_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:n]


def contenido_identico(ruta: str, texto: str) -> bool:
    """¿El fichero que ya está en disco dice exactamente esto?

    Se compara de verdad en vez de deducirlo del nombre. Cuesta una lectura
    y evita el fallo de la familia contraria: dar por bueno algo porque el
    nombre cuadra.
    """
    try:
        with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip() == texto.strip()
    except OSError:
        return False


def short_ts(dt: datetime.datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


# ---------- Assets: índice de imágenes dentro del ZIP + escritor deduplicado ----------

class AssetIndex:
    """Mapea un id de asset_pointer (sin esquema) al nombre de fichero real dentro
    del ZIP, usando el patrón <id>-<uuid>.<ext> que usa el export de ChatGPT."""

    def __init__(self, zf: Optional[zipfile.ZipFile]):
        self.zf = zf
        self.by_id: Dict[str, str] = {}
        if zf is None:
            return
        for name in zf.namelist():
            base = os.path.basename(name)
            m = UUID_SUFFIX_RE.match(base)
            if m:
                self.by_id[m.group("id")] = name

    @staticmethod
    def resolve_pointer_id(asset_pointer: str) -> str:
        """'file-service://file-XXXX' -> 'file-XXXX'
           'sediment://file_XXXX'      -> 'file_XXXX'"""
        if "://" in asset_pointer:
            return asset_pointer.split("://", 1)[1]
        return asset_pointer

    def get_bytes(self, asset_pointer: str) -> Optional[Tuple[bytes, str]]:
        if self.zf is None:
            return None
        pid = self.resolve_pointer_id(asset_pointer)
        name = self.by_id.get(pid)
        if not name:
            return None
        with self.zf.open(name) as f:
            data = f.read()
        ext = os.path.splitext(name)[1] or ".png"
        return data, ext


class AssetWriter:
    """Copia binarios a la carpeta de assets, deduplicando por hash de contenido.
    Acumula tambien un manifiesto (self.manifest) con metadatos utiles que el
    JSON original trae y que de otro modo se pierden: prompt de DALL-E si la
    imagen fue generada, nombre de adjunto si coincide con una subida, ancho/alto
    y la primera conversacion donde aparecio."""

    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        self.hash_to_filename: Dict[str, str] = {}
        self.manifest: Dict[str, dict] = {}
        ensure_dir(assets_dir)

    def write(self, data: bytes, ext: str, meta: Optional[dict] = None) -> str:
        h = hashlib.sha1(data).hexdigest()[:16]
        if h in self.hash_to_filename:
            return self.hash_to_filename[h]
        fname = f"{h}{ext}"
        path = os.path.join(self.assets_dir, fname)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        self.hash_to_filename[h] = fname
        if meta:
            self.manifest[fname] = meta
        return fname

    def flush_manifest(self) -> int:
        """Fusiona self.manifest con el _image_manifest.json ya existente en
        assets_dir (si lo hay) y lo reescribe. Devuelve el total tras la
        fusion. No-op silencioso si no hay nada nuevo que anotar."""
        if not self.manifest:
            return 0
        manifest_path = os.path.join(self.assets_dir, "_image_manifest.json")
        existing: Dict[str, dict] = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        existing.update(self.manifest)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return len(existing)


class BankTarget:
    """Pareja (AssetWriter, prefijo de enlace) para UN banco de imagenes.
    render_image_tokens elige el banco por meta['origen'] (generada/subida)
    -- taxonomia por proveedor y tipo (decision V0ra 2026-07-22): las
    generaciones de IA y las subidas del usuario ya no comparten carpeta."""
    __slots__ = ("writer", "rel_prefix")

    def __init__(self, writer: AssetWriter, rel_prefix: str):
        self.writer = writer
        self.rel_prefix = rel_prefix


def render_image_tokens(content: str, asset_index: Optional[AssetIndex],
                         asset_writers: Optional[Dict[str, BankTarget]],
                         image_meta: Optional[Dict[str, dict]] = None,
                         conv_title: Optional[str] = None) -> str:
    """Sustituye los marcadores \\x00IMG:<pointer>\\x00 por markdown real,
    o por un aviso explícito si no hay banco de assets configurado para el
    origen de esa imagen o el binario no está presente en el export.

    asset_writers mapea origen ('generada'/'subida', ver image_meta) al
    BankTarget correspondiente -- cada imagen va a su banco segun de donde
    salio, no todas al mismo sitio. Si image_meta trae informacion para ese
    pointer (prompt de DALL-E, nombre de adjunto, dimensiones), se adjunta
    al manifiesto del AssetWriter junto con la conversacion."""

    def _sub(m: "re.Match[str]") -> str:
        pointer = m.group("pointer")
        meta_base = (image_meta or {}).get(pointer) or {}
        origen = meta_base.get("origen") or "subida"
        target = (asset_writers or {}).get(origen)
        if asset_index is None or target is None:
            return f"*[imagen omitida: {pointer}]*"
        found = asset_index.get_bytes(pointer)
        if not found:
            return f"*[imagen no disponible en el export: {pointer}]*"
        data, ext = found
        meta = dict(meta_base) if meta_base else None
        if meta and conv_title:
            meta["primera_conversacion"] = conv_title
        fname = target.writer.write(data, ext, meta=meta)
        rel_path = f"{target.rel_prefix}/{fname}".replace("\\", "/")
        return f"![]({rel_path})"

    return IMAGE_TOKEN_RE.sub(_sub, content)


# ---------- Assets de Grok: prod-mc-asset-server dentro del ZIP ----------
# A diferencia de ChatGPT, los blobs de Grok no traen extension en el nombre
# (.../<uuid>/content) ni la referencia (file_attachments, media_posts) trae
# mimetype -- hay que identificar el formato por los primeros bytes.

GROK_FILE_TOKEN_RE = re.compile(r"\x00GROKFILE:(?P<uid>[^\x00]+)\x00")


def sniff_ext(data: bytes) -> str:
    """Identifica el tipo de fichero por sus primeros bytes (firma/magic
    number). Verificado contra blobs reales de Grok (prod-mc-asset-server):
    ni el nombre del blob en el zip ni la referencia en el JSON traen
    extension o mimetype."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[4:8] == b"ftyp":
        return ".mp4"
    return ".bin"


class GrokAssetIndex:
    """Mapea un uuid de asset (file_attachments, media_posts.id) al nombre
    real del blob dentro del ZIP de Grok: ttl/30d/.../prod-mc-asset-server/
    /<uuid>/content. Verificado contra export real: 72/72 uuids de
    file_attachments de una conversacion casaban con un blob del zip."""

    def __init__(self, zf: Optional[zipfile.ZipFile]):
        self.zf = zf
        self.by_uuid: Dict[str, str] = {}
        if zf is None:
            return
        for name in zf.namelist():
            if "prod-mc-asset-server" not in name:
                continue
            # El path trae DOS uuids: el del usuario (antes de
            # prod-mc-asset-server) y el del asset (justo antes de
            # "content", que es el que hay que indexar). Bug real
            # 2026-07-22: tomar el primer segmento de 36 caracteres del
            # path entero cogia el uuid de usuario -- 0 aciertos en un
            # export real con 72 file_attachments verificados a mano.
            parts = name.split("/")
            if len(parts) >= 2 and parts[-1] == "content":
                uid = parts[-2]
                if len(uid) == 36 and uid.count("-") == 4:
                    self.by_uuid[uid] = name

    def get_bytes(self, uid: str) -> Optional[bytes]:
        if self.zf is None:
            return None
        name = self.by_uuid.get(uid)
        if not name:
            return None
        with self.zf.open(name) as f:
            return f.read()


def render_grok_file_tokens(content: str, asset_index: Optional[GrokAssetIndex],
                             asset_writer: Optional[AssetWriter],
                             rel_prefix: Optional[str]) -> str:
    """Sustituye los marcadores \\x00GROKFILE:<uid>\\x00 por un embed (si es
    imagen) o un enlace de archivo, o por el aviso legible de siempre si no
    hay banco configurado o el binario no esta en el export."""

    def _sub(m: "re.Match[str]") -> str:
        uid = m.group("uid")
        if asset_index is None or asset_writer is None or rel_prefix is None:
            return f"📎 Archivo adjunto del export de Grok (asset `{uid}`, binario en el zip original)"
        data = asset_index.get_bytes(uid)
        if data is None:
            return f"📎 Archivo adjunto del export de Grok (asset `{uid}`, no disponible en el export)"
        ext = sniff_ext(data)
        fname = asset_writer.write(data, ext)
        rel_path = f"{rel_prefix}/{fname}".replace("\\", "/")
        if ext in (".png", ".jpg", ".gif", ".webp"):
            return f"![]({rel_path})"
        return f"📎 [Archivo adjunto]({rel_path})"

    return GROK_FILE_TOKEN_RE.sub(_sub, content)


# ---------- Artefactos de Claude: subdirectorio por tipo dentro del banco ----------

CLAUDE_ARTIFACT_TOKEN_RE = re.compile(r"\x00CLAUDEARTIFACT:(?P<aid>[^\x00]+)\x00")

# type (Content-Type real de Claude) -> (subcarpeta, extension). "language"
# (solo presente en application/vnd.ant.code) afina la extension del codigo.
_ARTIFACT_TYPE_MAP = {
    "text/markdown": ("markdown", ".md"),
    "text/html": ("html", ".html"),
    "application/vnd.ant.code": ("codigo", ".txt"),
    "image/svg+xml": ("svg", ".svg"),
    "application/vnd.ant.react": ("react", ".jsx"),
    "application/vnd.ant.mermaid": ("mermaid", ".mmd"),
}
_LANGUAGE_EXT_MAP = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "jsx": ".jsx", "tsx": ".tsx",
    "html": ".html", "css": ".css", "json": ".json", "yaml": ".yaml", "sql": ".sql",
    "bash": ".sh", "shell": ".sh", "go": ".go", "rust": ".rs", "java": ".java",
    "c": ".c", "cpp": ".cpp", "csharp": ".cs", "ruby": ".rb", "php": ".php",
}


def _artifact_subdir_ext(art: dict) -> Tuple[str, str]:
    subdir, ext = _ARTIFACT_TYPE_MAP.get(art.get("type"), ("otros", ".txt"))
    if art.get("type") == "application/vnd.ant.code":
        ext = _LANGUAGE_EXT_MAP.get((art.get("language") or "").lower(), ".txt")
    return subdir, ext


def render_claude_artifact_tokens(content: str, artifacts: Optional[Dict[str, dict]],
                                   writer: Optional[AssetWriter], bank_prefix: Optional[str],
                                   conv_id: Optional[str] = None) -> str:
    """Sustituye \\x00CLAUDEARTIFACT:<id>\\x00 por un enlace al artefacto ya
    escrito en CLAUDE/ARTEFACTOS/<tipo>/, o por un aviso legible si no hay
    banco configurado. El contenido escrito es siempre la version FINAL
    (ver claude_adapter._resolve_artifacts), independientemente de cuantas
    revisiones tuviera en el export. conv_id entra en el nombre de fichero
    porque el id del artefacto solo es unico DENTRO de su conversacion --
    dos chats distintos pueden crear ambos un artefacto "app"."""

    def _sub(m: "re.Match[str]") -> str:
        aid = m.group("aid")
        art = (artifacts or {}).get(aid)
        if art is None:
            return f"*[artefacto no resuelto: {aid}]*"
        if writer is None or bank_prefix is None:
            return f"🧩 Artefacto: **{art.get('title') or aid}** (omitido: sin banco de artefactos configurado)"
        subdir, ext = _artifact_subdir_ext(art)
        fname = f"{slugify(art.get('title') or aid)[:60]}-{content_hash(f'{conv_id}:{aid}')}{ext}"
        full_dir = os.path.join(writer.assets_dir, subdir)
        ensure_dir(full_dir)
        path = os.path.join(full_dir, fname)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(art.get("content") or "")
        rel_path = f"{bank_prefix}/{subdir}/{fname}".replace("\\", "/")
        return f"🧩 Artefacto: **{art.get('title') or aid}** → [{fname}]({rel_path})"

    return CLAUDE_ARTIFACT_TOKEN_RE.sub(_sub, content)


def render_tether_quote(obj: dict) -> Optional[str]:
    """Convierte un bloque tether_quote (formato antiguo de archivo citado) en texto legible.
    Nota: no se ha observado tether_quote en exports recientes de ChatGPT -- el
    formato actual usa metadata.attachments a nivel de mensaje (ver render_attachments).
    Se conserva por compatibilidad con exports antiguos."""
    if str(obj.get("content_type") or "").lower() != "tether_quote":
        return None
    domain = obj.get("domain") or obj.get("title") or obj.get("file") or obj.get("url") or "archivo desconocido"
    raw = (obj.get("text") or "").strip()
    if not raw:
        return f"📄 Archivo cargado: **{domain}**\n\n> (sin contenido)\n"
    raw = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.splitlines()
    if len(lines) > 10:
        lines = lines[:10]
        quoted = "\n".join("> " + ln for ln in lines) + "\n> \n> ... (contenido truncado)"
    else:
        quoted = "\n".join("> " + ln for ln in lines)
    return f"📄 Archivo cargado: **{domain}**\n\n{quoted}\n"


def render_attachments(msg: dict) -> str:
    """Renderiza metadata.attachments (formato real observado en exports actuales
    de ChatGPT) como líneas legibles. A diferencia de tether_quote, este formato
    solo trae metadatos del archivo (nombre, tipo, tamaño) -- el export no incluye
    el contenido del archivo en si, solo la referencia de que se cargó.

    Los adjuntos de tipo imagen se omiten aquí a propósito: esas mismas imágenes
    ya llegan como image_asset_pointer dentro de 'parts' y se resuelven vía
    --assets-dir. Los IDs de ambos mecanismos no coinciden entre sí (uno usa el
    nombre de archivo original, el otro el id interno de ChatGPT), así que no se
    pueden deduplicar por id -- se evita el duplicado excluyendo imagenes aquí."""
    meta = msg.get("metadata") or {}
    atts = meta.get("attachments") or []
    lines: List[str] = []
    for a in atts:
        if not isinstance(a, dict):
            continue
        mime = a.get("mimeType") or a.get("mime_type") or ""
        if mime.lower().startswith("image/"):
            continue
        name = a.get("name") or "archivo sin nombre"
        tokens = a.get("fileSizeTokens") or a.get("file_size_tokens")
        size_txt = f", ~{tokens} tokens" if tokens else ""
        lines.append(f"📎 Archivo adjunto: **{name}** ({mime or 'tipo desconocido'}{size_txt})")
    return "\n".join(lines)


def write_md(base_out_dir: str, title: str, date_str: str,
             messages: List[Dict[str, str]], tags: List[str],
             by_year: bool = False, by_month: bool = False,
             existing_policy: Dict[str, Any] | None = None,
             extra_front: Dict[str, Any] | None = None,
             source: str = "chatgpt_export") -> Tuple[str, str]:
    y, m, _ = date_str.split("-")
    out_dir = base_out_dir
    if by_year:
        out_dir = os.path.join(out_dir, y)
    if by_month:
        out_dir = os.path.join(out_dir, m if by_year else f"{y}-{m}")
    ensure_dir(out_dir)

    fname = f"{date_str}_{slugify(title)[:80]}.md"
    path = os.path.join(out_dir, fname)

    lines: List[str] = []
    lines.append("---")
    safe_title = (title or "").replace('"', "'")
    lines.append(f'title: "{safe_title}"')
    lines.append(f"date: {date_str}")
    if tags:
        lines.append("tags: " + " ".join(tags))
    lines.append(f"source: {source}")
    if extra_front:
        for k, v in extra_front.items():
            if isinstance(v, str):
                lines.append(f'{k}: "{v}"')
            else:
                lines.append(f"{k}: {v}")
    lines.append("---\n")
    for msg in messages or []:
        role = (msg.get("role", "unknown") or "unknown").capitalize()
        content = (msg.get("content", "") or "").rstrip()
        lines.append(f"### {role}\n")
        lines.append(content + "\n")
    content_text = "\n".join(lines)
    # Normaliza CRLF/CR sueltos a LF puro ANTES de colapsar: el contenido
    # original (texto pegado desde el portapapeles, etc.) puede traer \r\n,
    # y escribir eso en modo texto sin normalizar duplica los saltos de
    # linea al pasar por la traduccion universal-newline de Python en Windows.
    content_text = content_text.replace("\r\n", "\n").replace("\r", "\n")
    # cosmetico: colapsa 3+ saltos de linea a 2 (mismo criterio que vault_merge.py)
    content_text = re.sub(r"\n{3,}", "\n\n", content_text)

    policy = existing_policy or {}
    write_path = path

    if os.path.exists(write_path) and policy.get("skip_identical"):
        try:
            with open(write_path, "r", encoding="utf-8", errors="ignore") as f:
                before = f.read().strip()
            if before == content_text.strip():
                rel = os.path.relpath(write_path, base_out_dir).replace("\\", "/")
                return write_path, rel
        except Exception:
            pass

    if os.path.exists(write_path) and policy.get("keep_versions"):
        scheme = policy.get("version_scheme", "hash")
        if scheme == "timestamp":
            dt = policy.get("conv_dt") or datetime.datetime.now()
            base, ext = os.path.splitext(path)
            write_path = f"{base}-t{short_ts(dt)}{ext}"
            i = 2
            while os.path.exists(write_path):
                write_path = f"{base}-t{short_ts(dt)}-{i}{ext}"
                i += 1
        elif scheme == "hash":
            h = content_hash(content_text)
            base, ext = os.path.splitext(path)
            write_path = f"{base}-h{h}{ext}"

            # El nombre YA es la identidad: sale del hash del contenido. Si
            # ese fichero existe, dentro está esto mismo, y no hay nada que
            # escribir. Contar encima (-2, -3...) creaba copias idénticas en
            # cada pasada: 7.134 notas y 936 MB en el vault real de V0ra,
            # todas byte a byte iguales a su canónica.
            #
            # Y no era un fallo del reproceso: salta en CUALQUIER importación
            # donde una conversación coincida con otra ya guardada -- de esas
            # 7.134, mil eran anteriores al reproceso. El reproceso solo lo
            # hizo evidente porque coincide con todas a la vez.
            #
            # Es lo que los bancos de assets llevan haciendo desde siempre:
            # nombre por hash, y si ya está no se reescribe. Aquí estaba a
            # medias.
            if os.path.exists(write_path):
                if contenido_identico(write_path, content_text):
                    rel = os.path.relpath(write_path, base_out_dir).replace("\\", "/")
                    return write_path, rel
                # Colisión real: mismo título, misma fecha, los mismos 32
                # bits de hash y contenido distinto. Haría falta que
                # coincidieran decenas de miles de notas homónimas, pero si
                # llega el día, el contador sigue aquí.
                i = 2
                candidato = f"{base}-h{h}-{i}{ext}"
                while os.path.exists(candidato):
                    i += 1
                    candidato = f"{base}-h{h}-{i}{ext}"
                write_path = candidato
        else:
            if policy.get("suffix_on_duplicate"):
                base, ext = os.path.splitext(path)
                i = 2
                while os.path.exists(write_path):
                    write_path = f"{base}-v{i}{ext}"
                    i += 1

    ensure_dir(os.path.dirname(write_path))
    with open(write_path, "w", encoding="utf-8", newline="") as f:
        f.write(content_text)

    rel = os.path.relpath(write_path, base_out_dir).replace("\\", "/")
    return write_path, rel


# ---------- parsing ----------

def norm_hex_id(s: str):
    if not s:
        return None
    s = s.strip().lower()
    m = re.search(r'(?:^g(?:-p)?-)?([0-9a-f]{32})$', s)
    return m.group(1) if m else None


class MarkerContext:
    """Estado compartido para resolver los marcadores PUA de ChatGPT
    (ver chatgpt_markers.py). Viaja por el parseo para no tener que anadir
    tres parametros sueltos a cada funcion intermedia.

    estado      -- {url: {"estado": "rescatada"|"descartada", ...}} cargado
                   de CHATGPT/_pendientes_descarga.json. Es la curacion de
                   V0ra y sobrevive a los reprocesos porque vive fuera de
                   las notas.
    pendientes  -- imagenes de busqueda web vistas en este pase, para
                   volcarlas al fichero de pendientes al terminar.
    """
    __slots__ = ("estado", "pendientes", "titulo")

    def __init__(self, estado: Optional[Dict[str, dict]] = None):
        self.estado = estado or {}
        self.pendientes: List[dict] = []
        self.titulo: Optional[str] = None


def _render_parts(c: Any, image_meta_out: Optional[Dict[str, dict]] = None,
                   att_ids: Optional[Dict[str, str]] = None,
                   refs: Optional[List[dict]] = None,
                   markers_ctx: Optional["MarkerContext"] = None) -> str:
    """Convierte el campo 'content' de un mensaje en texto.
    - Imágenes -> marcador \\x00IMG:<pointer>\\x00 (resuelto luego con --assets-dir)
    - tether_quote -> texto legible "📄 Archivo cargado: ..."
    - Otros tipos no textuales (audio, video en tiempo real...) -> aviso legible
    - Nunca vuelca el dict crudo (ese era el bug original)

    Si image_meta_out se pasa, se rellena con {pointer: {origen, prompt,
    width, height, adjunto_nombre}} para cada imagen encontrada -- el prompt
    de DALL-E y las dimensiones viven en el propio part y se perderían si no
    se capturan aquí, antes de que el token se aplane a texto. att_ids permite
    cruzar el id de asset_pointer con el nombre que trae metadata.attachments
    para el mismo mensaje (confirmado 1:1 contra datos reales).
    """
    if isinstance(c, dict) and "parts" in c:
        chunks: List[str] = []
        for p in c.get("parts") or []:
            if isinstance(p, dict):
                ctype = p.get("content_type")
                if ctype == "image_asset_pointer":
                    pointer = p.get("asset_pointer") or ""
                    chunks.append(f"\x00IMG:{pointer}\x00")
                    if image_meta_out is not None and pointer:
                        pid = AssetIndex.resolve_pointer_id(pointer)
                        meta_raw = p.get("metadata") or {}
                        dalle = meta_raw.get("dalle") or {}
                        generation = meta_raw.get("generation") or {}
                        meta: dict = {}
                        if dalle.get("prompt"):
                            meta["origen"] = "generada"
                            meta["prompt"] = dalle.get("prompt")
                        elif dalle.get("gen_id") or generation.get("gen_id"):
                            # Generacion nativa (GPT-4o/GPT-5 in-context image
                            # gen, tool "t2uay3k.sj1i4kz" en el export crudo):
                            # el prompt no viaja en la metadata de la imagen
                            # (vive en el texto de la conversacion que la
                            # origino), pero gen_id/generation confirman que SI
                            # es una imagen generada por el modelo, no una
                            # subida del usuario. Bug real 2026-07-22:
                            # comprobar solo dalle.prompt clasificaba 830
                            # imagenes generadas como "subida" porque el
                            # campo prompt viene vacio por esta via mas nueva.
                            meta["origen"] = "generada"
                        else:
                            meta["origen"] = "subida"
                        if p.get("width"):
                            meta["width"] = p.get("width")
                        if p.get("height"):
                            meta["height"] = p.get("height")
                        if att_ids and pid in att_ids:
                            meta["adjunto_nombre"] = att_ids[pid]
                        image_meta_out[pointer] = meta
                elif ctype == "tether_quote":
                    rendered = render_tether_quote(p)
                    chunks.append(rendered or "*[archivo cargado sin contenido]*")
                else:
                    chunks.append(f"*[contenido no textual omitido: {ctype or 'desconocido'}]*")
            else:
                chunks.append(str(p))
        return _resolver_marcadores("\n".join(chunks), refs, markers_ctx)
    elif isinstance(c, list):
        return _resolver_marcadores("\n".join(str(p) for p in c), refs, markers_ctx)
    elif isinstance(c, str):
        return _resolver_marcadores(c, refs, markers_ctx)
    else:
        return json.dumps(c, ensure_ascii=False)


def _cargar_estado_pendientes(path: Optional[str]) -> Dict[str, dict]:
    """Lee el triaje ya hecho por V0ra, indexado por URL. Tolerante: si el
    fichero no existe todavia o esta corrupto, se empieza de cero (perder
    el triaje es molesto, pero abortar la importacion es peor)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
    except Exception:
        return {}
    return {d["url"]: d for d in datos
            if isinstance(d, dict) and d.get("url")}


def _guardar_pendientes(path: str, vistas: List[dict], previos: Dict[str, dict]) -> int:
    """Funde las imagenes vistas en este pase con las ya conocidas,
    deduplicando por URL. Acumulativo como el de Grok: nunca pierde el
    triaje anterior ni las entradas de exports que ya no se reprocesan.
    Cuenta en cuantas notas distintas aparece cada imagen -- ese numero es
    lo que ayuda a decidir si una imagen sostenia un argumento o es ruido."""
    fusionado: Dict[str, dict] = {}
    for url, entrada in previos.items():
        fusionado[url] = dict(entrada)

    for v in vistas:
        url = v.get("url")
        if not url:
            continue
        actual = fusionado.setdefault(url, {
            "url": url, "estado": "sin_triar", "queries": [], "conversaciones": [],
        })
        for q in (v.get("queries") or []):
            if q and q not in actual.setdefault("queries", []):
                actual["queries"].append(q)
        conv = v.get("conversacion")
        if conv and conv not in actual.setdefault("conversaciones", []):
            actual["conversaciones"].append(conv)

    salida = sorted(fusionado.values(), key=lambda d: (d.get("estado") or "", d.get("url") or ""))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    return len(salida)


def _resolver_marcadores(texto: str, refs: Optional[List[dict]],
                          ctx: Optional["MarkerContext"]) -> str:
    """Ultimo paso de todo texto de mensaje: convierte los marcadores
    internos de ChatGPT (citas de fuentes, entidades, busquedas de
    imagenes) en markdown legible. Antes de 2026-07-27 se colaban en crudo
    en las notas -- 613 notas reales afectadas. Ver chatgpt_markers.py."""
    from chatgpt_markers import resolve_markers
    return resolve_markers(
        texto, refs,
        pendientes_out=(ctx.pendientes if ctx is not None else None),
        estado_imagenes=(ctx.estado if ctx is not None else None),
        conv_titulo=(ctx.titulo if ctx is not None else None),
    )


def parse_json_conversations(obj: Any, image_meta_out: Optional[Dict[str, dict]] = None,
                              markers_ctx: Optional["MarkerContext"] = None) -> List[Dict[str, Any]]:
    conversations: List[Dict[str, Any]] = []

    if isinstance(obj, dict) and "conversations" in obj and isinstance(obj["conversations"], list):
        raw = obj["conversations"]
    elif isinstance(obj, list):
        raw = obj
    else:
        raw = obj.get("items", []) if isinstance(obj, dict) else []

    for conv in raw:
        title = conv.get("title") or "Conversación"
        if markers_ctx is not None:
            # Da contexto a los pendientes de imagen: sin saber de que
            # conversacion salio, la lista es inutil para decidir.
            markers_ctx.titulo = title
        ct = conv.get("create_time") or conv.get("createTime")
        ut = conv.get("update_time") or conv.get("updateTime")
        gid = conv.get("gizmo_id") or conv.get("gizmoId")
        mapping = conv.get("mapping")
        current_node = conv.get("current_node")
        messages: List[Dict[str, str]] = []
        modelos_vistos: Dict[str, int] = {}

        if isinstance(mapping, dict):
            ordered_nodes: List[Dict[str, Any]] = []

            if current_node and current_node in mapping:
                # Camino real: camina hacia atrás por 'parent' desde current_node
                # hasta la raíz. Esto excluye ramas de regeneración/edición
                # descartadas que siguen presentes en 'mapping' pero que el
                # usuario nunca vio como parte final de la conversación.
                path_ids: List[str] = []
                node_id = current_node
                visited = set()
                while node_id and node_id not in visited and node_id in mapping:
                    visited.add(node_id)
                    path_ids.append(node_id)
                    node_id = mapping[node_id].get("parent")
                path_ids.reverse()
                ordered_nodes = [mapping[nid] for nid in path_ids if isinstance(mapping[nid], dict)]
            else:
                # Fallback: sin current_node (formato de export antiguo o
                # incompleto), se aplana todo el mapping ordenado por tiempo,
                # como antes.
                def node_time(n: Dict[str, Any]) -> float:
                    try:
                        return float(n.get("message", {}).get("create_time") or 0)
                    except Exception:
                        return 0.0

                ordered_nodes = [n for n in mapping.values() if isinstance(n, dict)]
                ordered_nodes.sort(key=node_time)

            for node in ordered_nodes:
                msg = node.get("message")
                if not msg:
                    continue
                author = (msg.get("author") or {}).get("role") or msg.get("role") or "unknown"
                slug = (msg.get("metadata") or {}).get("model_slug")
                if slug:
                    modelos_vistos[slug] = modelos_vistos.get(slug, 0) + 1
                c = msg.get("content")
                att_ids = {a.get("id"): a.get("name") for a in (msg.get("metadata") or {}).get("attachments") or [] if isinstance(a, dict)}
                content = _render_parts(c, image_meta_out=image_meta_out, att_ids=att_ids,
                                        refs=(msg.get("metadata") or {}).get("content_references"),
                                        markers_ctx=markers_ctx)
                attachments_txt = render_attachments(msg)
                if attachments_txt:
                    content = f"{attachments_txt}\n\n{content}".strip() if content.strip() else attachments_txt
                if (content or "").strip():
                    messages.append({"role": author, "content": content})
        else:
            msgs = conv.get("messages") or conv.get("items") or []
            for m in msgs:
                role = (m.get("author") or {}).get("role") or m.get("role") or "unknown"
                att_ids = {a.get("id"): a.get("name") for a in (m.get("metadata") or {}).get("attachments") or [] if isinstance(a, dict)}
                content = _render_parts(m.get("content") or "", image_meta_out=image_meta_out,
                                        att_ids=att_ids,
                                        refs=(m.get("metadata") or {}).get("content_references"),
                                        markers_ctx=markers_ctx)
                attachments_txt = render_attachments(m)
                if attachments_txt:
                    content = f"{attachments_txt}\n\n{content}".strip() if content.strip() else attachments_txt
                messages.append({"role": role, "content": content})

        conversations.append({
            "title": title,
            "create_time": ct,
            "update_time": ut,
            "messages": messages,
            "gizmo_id": gid,
            "provider": "chatgpt",
            "conv_id": conv.get("conversation_id") or conv.get("id"),
            # Campos del esquema nuevo (2026+) que el bucle principal usa
            # para resolver el proyecto cuando gizmo_id viene a None.
            # Propagarlos aqui es esencial: sin esto, load_conversations los
            # descarta y el fix del conversation_template_id ejecutaria sobre
            # un dict vacio (incidente documentado 2026-07-20).
            "conversation_template_id": conv.get("conversation_template_id"),
            "memory_scope": conv.get("memory_scope"),
            # Modelo mas frecuente de la conversacion (representativo cuando
            # el hilo cruza epocas de modelos); empate -> orden alfabetico
            "model": max(sorted(modelos_vistos), key=lambda m: modelos_vistos[m]) if modelos_vistos else None,
        })

    return conversations


def parse_html_export(html_text: str) -> List[Dict[str, Any]]:
    m = re.search(r'(\{.*?"conversations".*?\})', html_text, flags=re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return parse_json_conversations(data)
        except Exception:
            pass

    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(html_text, "html.parser")
        convs: List[Dict[str, Any]] = []
        headers = soup.find_all(["h2", "h3"])
        for h in headers:
            title = h.get_text(strip=True) or "Conversación"
            body: List[str] = []
            for sib in h.find_all_next(["p", "pre", "code"]):
                if sib.name in ("h2", "h3"):
                    break
                body.append(sib.get_text("\n", strip=True))
            if body:
                alt = ["user", "assistant"]
                msgs = [{"role": alt[i % 2], "content": t} for i, t in enumerate(body)]
                convs.append({"title": title, "create_time": None, "update_time": None, "messages": msgs, "gizmo_id": None})
        if convs:
            return convs

        text = soup.get_text("\n", strip=True)
        parts = [p for p in text.splitlines() if p.strip()]
        alt = ["user", "assistant"]
        msgs = [{"role": alt[i % 2], "content": t} for i, t in enumerate(parts)]
        return [{"title": "Conversación", "create_time": None, "update_time": None, "messages": msgs, "gizmo_id": None}]
    except Exception:
        pass

    return []


def _dispatch(data: Any, image_meta_out: Optional[Dict[str, dict]] = None,
              markers_ctx: Optional["MarkerContext"] = None) -> List[Dict[str, Any]]:
    """Despacha el JSON cargado al adaptador correcto por ESTRUCTURA interna,
    nunca por nombre de archivo: el zip de Claude tambien contiene un
    conversations.json y sin esta distincion el pipeline lo tragaria en
    silencio generando notas vacias."""
    if claude_adapter.detect(data):
        return claude_adapter.parse(data)
    if grok_adapter.detect(data):
        # Debe evaluarse ANTES que el parser de ChatGPT: ambos usan raiz
        # {conversations: [...]} pero los items de Grok son wrappers con
        # 'responses' que ChatGPT interpretaria como conversaciones vacias.
        return grok_adapter.parse(data)
    return parse_json_conversations(data, image_meta_out=image_meta_out, markers_ctx=markers_ctx)


def load_grok_media_posts(zf: Optional[zipfile.ZipFile]) -> List[dict]:
    """media_posts (generaciones de Imagine) vive en la raiz del JSON de
    Grok, fuera de cualquier conversacion -- load_conversations no lo
    expone (su contrato es solo la lista de conversaciones), asi que se
    relee aparte, una sola vez por zip. Tolerante: si no es un export de
    Grok o algo falla, lista vacia."""
    if zf is None:
        return []
    try:
        json_name = next((n for n in zf.namelist() if n.lower().endswith("prod-grok-backend.json")), None)
        if not json_name:
            return []
        with zf.open(json_name) as f:
            data = json.load(f)
        mp = data.get("media_posts")
        return mp if isinstance(mp, list) else []
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, KeyError):
        return []


def process_grok_media_posts(media_posts: List[dict], asset_index: "GrokAssetIndex",
                              imagen_writer: Optional[AssetWriter], imagen_rel_prefix: str,
                              video_writer: Optional[AssetWriter], video_rel_prefix: str) -> Tuple[int, List[dict]]:
    """Extrae a GROK/GENERADAS_IMAGEN o GROK/GENERADAS_VIDEO segun
    media_type los media_posts cuyo binario SI viaja en el zip (verificado
    contra export real: ~18%, prod-mc-asset-server indexado por el mismo
    uuid que media_post['id']). El resto (~82%, solo un link externo a
    grok.com que puede caducar o pedir sesion) se devuelve como lista de
    pendientes para --grok-pendientes-out, NUNCA se descarga solo.
    Devuelve (num_extraidas, pendientes)."""
    extraidas = 0
    pendientes: List[dict] = []
    for mp in media_posts:
        if not isinstance(mp, dict):
            continue
        mp_id = mp.get("id")
        media_type = mp.get("media_type")
        data = asset_index.get_bytes(mp_id) if mp_id else None
        if data is None:
            pendientes.append({
                "id": mp_id,
                "prompt": mp.get("original_prompt"),
                "link": mp.get("link"),
                "media_type": media_type,
                "create_time": mp.get("create_time"),
            })
            continue
        writer = video_writer if media_type == "video" else imagen_writer
        if writer is None:
            continue
        ext = sniff_ext(data)
        meta = {
            "origen": "generada", "prompt": mp.get("original_prompt"), "media_type": media_type,
            "create_time": mp.get("create_time"),
        }
        writer.write(data, ext, meta=meta)
        extraidas += 1
    return extraidas, pendientes


def load_conversations(input_path: str, image_meta_out: Optional[Dict[str, dict]] = None,
                        markers_ctx: Optional["MarkerContext"] = None) -> Tuple[List[Dict[str, Any]], Optional[zipfile.ZipFile]]:
    """Devuelve (conversaciones, zip_abierto_o_None). El zip se deja abierto para
    poder extraer imágenes de él más tarde; el llamador debe cerrarlo al terminar."""
    p = os.path.abspath(input_path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"No existe: {input_path}")

    ext = os.path.splitext(p)[1].lower()

    if ext == ".zip":
        zf = zipfile.ZipFile(p, "r")
        # Formato fragmentado de ChatGPT (2026+): conversations-000.json,
        # conversations-001.json... Fragmentos cronologicos y disjuntos
        # (verificado contra export real: 10 x 100 convs, 0 solapes). Se leen
        # TODOS en orden y se concatenan. El formato clasico de un unico
        # conversations.json se mantiene debajo por retrocompatibilidad.
        shard_rx = re.compile(r"conversations-\d+\.json$", re.IGNORECASE)
        shards = sorted(n for n in zf.namelist() if shard_rx.search(n))
        if shards:
            combinado: List[Any] = []
            for name in shards:
                with zf.open(name) as f:
                    parte = json.load(f)
                if isinstance(parte, list):
                    combinado.extend(parte)
            return _dispatch(combinado, image_meta_out=image_meta_out, markers_ctx=markers_ctx), zf

        json_name = None
        for name in zf.namelist():
            if name.lower().endswith("conversations.json"):
                json_name = name
                break
        if not json_name:
            # Export de Grok: el JSON principal vive en ttl/.../prod-grok-backend.json
            for name in zf.namelist():
                if name.lower().endswith("prod-grok-backend.json"):
                    json_name = name
                    break
        if json_name:
            with zf.open(json_name) as f:
                data = json.load(f)
            return _dispatch(data, image_meta_out=image_meta_out, markers_ctx=markers_ctx), zf
        for name in zf.namelist():
            if name.lower().endswith(".html"):
                with zf.open(name) as f:
                    html = f.read().decode("utf-8", errors="ignore")
                convs = parse_html_export(html)
                zf.close()
                return convs, None
        zf.close()
        raise RuntimeError("No se encontró conversations.json ni HTML dentro del ZIP.")

    if ext == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _dispatch(data, image_meta_out=image_meta_out, markers_ctx=markers_ctx), None

    if ext in (".html", ".htm"):
        with open(p, "r", encoding="utf-8") as f:
            html = f.read()
        return parse_html_export(html), None

    raise RuntimeError("Formato no soportado. Usa .zip, .json o .html")


def compute_out_dir(base_out_dir: str, y: str, m: str, by_year: bool, by_month: bool) -> str:
    out_dir = base_out_dir
    if by_year:
        out_dir = os.path.join(out_dir, y)
    if by_month:
        out_dir = os.path.join(out_dir, m if by_year else f"{y}-{m}")
    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Divide exportaciones de ChatGPT en Markdown para Obsidian.")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--manifest", default=None,
                    help="Directorio de logs donde anadir el manifiesto append-only de conversaciones procesadas")
    ap.add_argument("--export-name", default=None,
                    help="Nombre del export original a registrar en el manifiesto (por defecto, el basename del input)")
    ap.add_argument("--tag-map", default=None)
    ap.add_argument("--gizmo-map", default=None, help="JSON con id→nombre (g-*, g-p-* o hex) → slug/nombre")
    ap.add_argument("--make-index", action="store_true")
    ap.add_argument("--tag-indexes", action="store_true")
    ap.add_argument("--loose-html", action="store_true")
    ap.add_argument("--by-year", action="store_true")
    ap.add_argument("--by-month", action="store_true")
    ap.add_argument("--top-n", type=int, default=20)

    ap.add_argument("--date-field", choices=["create", "update"], default="create",
                    help="Elegir la fecha principal en el YAML (por defecto: create)")
    ap.add_argument("--include-both-dates", action="store_true",
                    help="Añade created/updated al YAML si existen")

    ap.add_argument("--keep-versions", action="store_true")
    ap.add_argument("--suffix-on-duplicate", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true")
    ap.add_argument("--skip-identical", action="store_true",
                    help="Si el .md ya existe y el contenido sería idéntico, no crear versión nueva")
    ap.add_argument("--version-scheme", choices=["counter", "timestamp", "hash"], default="hash",
                    help="Esquema de versionado si colisiona el nombre (por defecto: hash)")
    ap.add_argument("--use-conv-timestamp", action="store_true",
                    help="En 'timestamp', usar create_time de la conversación si está disponible")

    ap.add_argument("--force-project-id", default=None, help="Forzar source_project_id si el export no trae gizmo_id")
    ap.add_argument("--force-project", default=None, help="Forzar source_project (nombre/slug)")
    ap.add_argument("--project-tag", action="store_true", help="Añade tag #project/<slug> si hay nombre")

    ap.add_argument("--generadas-dir", default=None,
                    help="Carpeta donde extraer imagenes generadas por IA (DALL-E, generacion nativa), "
                         "deduplicadas por hash. Si se omite, esas imagenes quedan como aviso de texto.")
    ap.add_argument("--adjuntos-dir", default=None,
                    help="Carpeta donde extraer imagenes subidas por el usuario, deduplicadas por hash. "
                         "Si se omite, esas imagenes quedan como aviso de texto.")

    ap.add_argument("--grok-adjuntos-dir", default=None,
                    help="[Solo exports de Grok] Carpeta donde extraer file_attachments, deduplicados por hash.")
    ap.add_argument("--grok-generadas-imagen-dir", default=None,
                    help="[Solo exports de Grok] Carpeta donde extraer media_posts de tipo imagen (Imagine) "
                         "cuyo binario SI viaja en el zip.")
    ap.add_argument("--grok-generadas-video-dir", default=None,
                    help="[Solo exports de Grok] Carpeta donde extraer media_posts de tipo video (Imagine) "
                         "cuyo binario SI viaja en el zip.")
    ap.add_argument("--grok-pendientes-out", default=None,
                    help="[Solo exports de Grok] Ruta a un JSON donde anotar los media_posts (Imagine) SIN "
                         "binario en el zip -- prompt+link+tipo, para descargarlos a mano.")

    ap.add_argument("--chatgpt-pendientes-out", default=None,
                    help="[Solo exports de ChatGPT] Ruta a un JSON donde anotar las imagenes de busqueda "
                         "web que ChatGPT mostro en la conversacion pero no vienen en el export "
                         "(url+query+conversacion), para descargarlas a mano. Guarda tambien el triaje "
                         "(rescatada/descartada), que sobrevive a los reprocesos.")

    ap.add_argument("--claude-artefactos-dir", default=None,
                    help="[Solo exports de Claude] Carpeta donde escribir artefactos (solo version final), "
                         "organizados en subcarpetas por tipo (markdown/html/codigo/...).")

    args = ap.parse_args()

    ensure_dir(args.output)

    image_meta: Dict[str, dict] = {}

    tag_map: Dict[str, str] = {}
    if args.tag_map:
        try:
            with open(args.tag_map, "r", encoding="utf-8-sig") as f:
                tag_map = json.load(f)
        except Exception as e:
            print("Advertencia: no pude cargar tag-map:", e)

    gizmo_map: Dict[str, str] = {}
    if args.gizmo_map:
        try:
            with open(args.gizmo_map, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            for k, v in raw.items():
                m = re.search(r'(?:^g(?:-p)?-)?([0-9a-f]{32})$', k.strip().lower())
                if not m:
                    continue
                hx = m.group(1)
                gizmo_map[hx] = v
                gizmo_map["g-" + hx] = v
                gizmo_map["g-p-" + hx] = v
        except Exception as e:
            print("Advertencia: no pude cargar gizmo_map:", e)

    # Triaje previo de imagenes de busqueda web: se lee ANTES de parsear
    # para que las notas se rendericen ya con la decision tomada (rescatada
    # -> imagen real, descartada -> marca discreta). Vive fuera de las notas
    # a proposito: las notas se regeneran en cada reproceso.
    markers_ctx = MarkerContext(_cargar_estado_pendientes(args.chatgpt_pendientes_out))

    conversations, zf = load_conversations(args.input, image_meta_out=image_meta,
                                            markers_ctx=markers_ctx)
    if not conversations:
        print("No se encontraron conversaciones.")
        sys.exit(2)

    tiene_bancos = bool(args.generadas_dir or args.adjuntos_dir)
    asset_index = AssetIndex(zf) if tiene_bancos else None
    asset_writers: Dict[str, BankTarget] = {}
    if args.generadas_dir:
        asset_writers["generada"] = BankTarget(AssetWriter(args.generadas_dir), "CHATGPT/GENERADAS")
    if args.adjuntos_dir:
        asset_writers["subida"] = BankTarget(AssetWriter(args.adjuntos_dir), "CHATGPT/ADJUNTOS")
    if tiene_bancos:
        print(f"Assets indexados en el ZIP: {len(asset_index.by_id)}")

    # Assets de Grok: file_attachments (por mensaje, via token GROKFILE) y
    # media_posts/Imagine (raiz del export, se procesan aparte una sola vez).
    es_grok = bool(conversations) and conversations[0].get("provider") == "grok"
    grok_asset_index = GrokAssetIndex(zf) if (es_grok and zf is not None) else None
    grok_adjuntos_writer = AssetWriter(args.grok_adjuntos_dir) if (es_grok and args.grok_adjuntos_dir) else None

    claude_artifacts_writer = AssetWriter(args.claude_artefactos_dir) if args.claude_artefactos_dir else None
    if es_grok and grok_asset_index is not None:
        imagen_writer = AssetWriter(args.grok_generadas_imagen_dir) if args.grok_generadas_imagen_dir else None
        video_writer = AssetWriter(args.grok_generadas_video_dir) if args.grok_generadas_video_dir else None
        media_posts = load_grok_media_posts(zf)
        if media_posts:
            n_extraidas, pendientes = process_grok_media_posts(
                media_posts, grok_asset_index,
                imagen_writer, "GROK/GENERADAS_IMAGEN",
                video_writer, "GROK/GENERADAS_VIDEO",
            )
            print(f"Imagine (media_posts): {len(media_posts)} totales, {n_extraidas} extraidas, "
                  f"{len(pendientes)} pendientes de descarga")
            if imagen_writer:
                imagen_writer.flush_manifest()
            if video_writer:
                video_writer.flush_manifest()
            if args.grok_pendientes_out and pendientes:
                pend_path = args.grok_pendientes_out
                existentes: List[dict] = []
                if os.path.exists(pend_path):
                    try:
                        with open(pend_path, "r", encoding="utf-8-sig") as f:
                            existentes = json.load(f)
                    except Exception:
                        existentes = []
                vistos = {p.get("id") for p in existentes}
                for p in pendientes:
                    if p.get("id") not in vistos:
                        existentes.append(p)
                        vistos.add(p.get("id"))
                os.makedirs(os.path.dirname(pend_path) or ".", exist_ok=True)
                with open(pend_path, "w", encoding="utf-8") as f:
                    json.dump(existentes, f, ensure_ascii=False, indent=2)
                print(f"Pendientes de descarga: {len(existentes)} en {pend_path}")

    if args.chatgpt_pendientes_out and (markers_ctx.pendientes or markers_ctx.estado):
        total = _guardar_pendientes(args.chatgpt_pendientes_out,
                                     markers_ctx.pendientes, markers_ctx.estado)
        nuevas = len({p.get("url") for p in markers_ctx.pendientes} - set(markers_ctx.estado))
        print(f"Imagenes de busqueda web: {total} en la lista ({nuevas} nuevas) "
              f"-> {args.chatgpt_pendientes_out}")

    # Manifiesto append-only de trazabilidad (opcional). Silencioso ante
    # fallos de I/O: registrar es opcional, importar no.
    from manifest import ConversationManifest
    export_name = args.export_name or os.path.basename(args.input)
    manifest = ConversationManifest(args.manifest, export_name=export_name)

    records: List[Dict[str, Any]] = []
    total_images = 0
    gizmos_pendientes: Dict[str, dict] = {}
    for conv in conversations:
        title = smart_title(conv.get("title"), conv.get("messages") or [])
        ct_raw = conv.get("create_time")
        ut_raw = conv.get("update_time")
        date_primary = iso_date(ct_raw)
        if args.date_field == "update" and ut_raw is not None:
            date_primary = iso_date(ut_raw)

        msgs = conv.get("messages") or []

        full_text = (title or "") + "\n" + "\n".join(m.get("content", "") for m in msgs)
        tags = []
        if tag_map:
            low = full_text.lower()
            for kw, tg in tag_map.items():
                if (kw or "").lower() in low:
                    tags.append(tg if str(tg).startswith("#") else f"#{tg}")

        gid = conv.get("gizmo_id") or conv.get("gizmoId")
        # Fallback al esquema nuevo de ChatGPT (2026+): los proyectos han
        # migrado de gizmo_id a conversation_template_id con prefijo 'g-p-'.
        # Filtro estricto por 'g-p-' para no confundir con otros templates
        # que no son proyectos (GPTs, workflows). Solo se usa si gizmo_id no
        # viene y memory_scope confirma que es un proyecto -- doble check:
        # el prefijo por si acaso el schema cambia otra vez, memory_scope
        # como intencion explicita del proveedor.
        if not gid:
            ctid = conv.get("conversation_template_id") or ""
            if ctid.startswith("g-p-") or conv.get("memory_scope") == "project_v2":
                if ctid.startswith("g-p-"):
                    gid = ctid
        name_from_map = None
        if gid:
            hx = norm_hex_id(gid)
            name_from_map = gizmo_map.get(gid) or gizmo_map.get("g-" + (hx or "")) or gizmo_map.get("g-p-" + (hx or "")) or gizmo_map.get(hx or "")

        if gid and not name_from_map:
            key = norm_hex_id(gid) or gid
            entry = gizmos_pendientes.setdefault(key, {"count": 0, "gizmo_id": gid, "conversaciones": []})
            entry["count"] += 1
            entry["conversaciones"].append({"titulo": title, "fecha": date_primary})

        extra_front: Dict[str, Any] = {}
        extra_front["Project_name"] = name_from_map if name_from_map else "none"
        extra_front["provider"] = conv.get("provider") or "chatgpt"
        if conv.get("conv_id"):
            # Identidad estable de la conversacion (la llave de la cordura:
            # sobrevive a renombrados de hilo entre exports)
            extra_front["conv_id"] = conv["conv_id"]
        if conv.get("model"):
            extra_front["model"] = conv["model"]

        if args.force_project_id:
            extra_front["source_project_id"] = args.force_project_id
        elif gid:
            extra_front["source_project_id"] = gid

        if args.force_project:
            extra_front["source_project"] = args.force_project
        elif name_from_map:
            extra_front["source_project"] = name_from_map

        if args.include_both_dates:
            c = iso_date_or_none(ct_raw)
            u = iso_date_or_none(ut_raw)
            if c:
                extra_front["created"] = c
            if u:
                extra_front["updated"] = u

        if args.project_tag:
            slug = extra_front.get("source_project") or extra_front.get("Project_name")
            if slug and slug != "none":
                tg = f"#project/{slugify(slug)}"
                if tg not in tags:
                    tags.append(tg)

        existing_policy = {
            "keep_versions": args.keep_versions,
            "suffix_on_duplicate": args.suffix_on_duplicate,
            "skip_identical": args.skip_identical,
            "version_scheme": args.version_scheme,
            "conv_dt": datetime.datetime.fromtimestamp(float(ct_raw)) if (args.use_conv_timestamp and ct_raw) else None,
        }

        # Resolver marcadores de imagen antes de escribir. Enlaces desde la
        # RAIZ del vault de Obsidian, no relativos. Los relativos
        # ../../../_assets/ dependian del junction _assets dentro de cada
        # subvault; cuando Obsidian abre la carpeta padre (02 Obsidian_vaults)
        # los .. salen del sitio donde el junction existe y todas las
        # imagenes se rompen (bug 2026-07-20). La ruta absoluta desde el
        # vault raiz funciona en cualquier layout: va directa al banco
        # correspondiente (CHATGPT/GENERADAS o CHATGPT/ADJUNTOS, ver
        # BankTarget) sin depender de la topologia.
        rendered_msgs = []
        for msg in msgs:
            raw_content = msg.get("content", "")
            if tiene_bancos:
                total_images += len(IMAGE_TOKEN_RE.findall(raw_content))
                content = render_image_tokens(raw_content, asset_index, asset_writers,
                                               image_meta=image_meta, conv_title=title)
            else:
                # Sin bancos configurados: deja aviso de texto en vez del marcador interno
                content = render_image_tokens(raw_content, None, None)
            # Independiente de los bancos de ChatGPT: si es Grok y file_attachments
            # trae binario, se resuelve aqui tambien (o degrada a texto si no hay
            # --grok-adjuntos-dir, mismo criterio que las imagenes de ChatGPT).
            content = render_grok_file_tokens(content, grok_asset_index, grok_adjuntos_writer,
                                               "GROK/ADJUNTOS" if grok_adjuntos_writer else None)
            # Independiente de lo anterior: si es Claude y hay artefactos,
            # se resuelven aqui (o degradan a texto sin --claude-artefactos-dir).
            content = render_claude_artifact_tokens(
                content, conv.get("artifacts"), claude_artifacts_writer,
                "CLAUDE/ARTEFACTOS" if claude_artifacts_writer else None,
                conv_id=conv.get("conv_id"),
            )
            rendered_msgs.append({"role": msg.get("role"), "content": content})
        msgs = rendered_msgs

        path, rel = write_md(
            args.output, title, date_primary, msgs, tags,
            by_year=args.by_year, by_month=args.by_month,
            existing_policy=existing_policy,
            extra_front=extra_front if extra_front else None,
            source=f"{(conv.get('provider') or 'chatgpt')}_export",
        )

        words = sum(word_count(m.get("content", "")) for m in msgs)
        records.append({
            "date": date_primary, "title": title, "tags": tags,
            "relpath": rel, "count": len(msgs), "words": words
        })
        # Trazabilidad conversacion->export: una linea por nota escrita.
        # Va aqui, DESPUES del write_md exitoso, para no anotar como escrita
        # una conversacion que fallo la escritura en disco.
        manifest.record(
            conv_id=conv.get("conv_id"),
            provider=(conv.get("provider") or "chatgpt"),
            titulo=title,
            fecha_conv=date_primary,
            nota_rel=rel,
            estado="escrita",
        )

    if zf:
        zf.close()
    manifest.close()
    if manifest.path:
        print(f"Manifiesto: +{manifest.escritas} entradas en {manifest.path}"
              + (f" ({manifest.errores} con error)" if manifest.errores else ""))

    if args.make_index:
        path = os.path.join(args.output, "_index.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Índice de conversaciones\n\n")
            for r in records:
                f.write(f"- {r['date']} — [{r['title']}]({r['relpath']})\n")

    if args.tag_indexes:
        tag_dir = os.path.join(args.output, "_tags")
        ensure_dir(tag_dir)
        tag_map2: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            for t in r.get("tags", []):
                key = t[1:] if t.startswith("#") else t
                tag_map2.setdefault(key, []).append(r)
        for tag, items in sorted(tag_map2.items()):
            p = os.path.join(tag_dir, f"{tag}.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# #{tag}\n\n")
                for it in items:
                    f.write(f"- [{it['title']}]({it['relpath']}) — {it['date']}\n")

    print(f"Listo. Exportadas {len(records)} conversaciones a: {args.output}")
    if tiene_bancos:
        print(f"Referencias de imagen procesadas: {total_images}")
        for origen, target in asset_writers.items():
            writer = target.writer
            print(f"  [{origen}] binarios únicos copiados a {writer.assets_dir}: {len(writer.hash_to_filename)}")
            total = writer.flush_manifest()
            if total:
                print(f"  [{origen}] manifiesto actualizado: {total} imagenes con metadatos")

    if grok_adjuntos_writer and grok_adjuntos_writer.hash_to_filename:
        print(f"[grok adjuntos] binarios únicos copiados a {grok_adjuntos_writer.assets_dir}: "
              f"{len(grok_adjuntos_writer.hash_to_filename)}")
        grok_adjuntos_writer.flush_manifest()

    if gizmos_pendientes:
        vault_root = os.path.dirname(os.path.normpath(args.output))
        pendientes_path = os.path.join(vault_root, "_gizmos_pendientes.json")
        existing_pendientes: Dict[str, dict] = {}
        if os.path.exists(pendientes_path):
            try:
                with open(pendientes_path, "r", encoding="utf-8-sig") as f:
                    existing_pendientes = json.load(f)
            except Exception:
                existing_pendientes = {}
        for key, entry in gizmos_pendientes.items():
            if key in existing_pendientes:
                existing_pendientes[key].setdefault("conversaciones", [])
                existing_pendientes[key]["conversaciones"].extend(entry["conversaciones"])
            else:
                existing_pendientes[key] = entry
            # Dedup por (titulo, fecha): si esta conversacion ya estaba (p.ej.
            # por --reprocess-all sobre un export ya importado antes), no se
            # cuenta dos veces. count se recalcula desde la lista, nunca se suma.
            vistos = set()
            unicos = []
            for c in existing_pendientes[key]["conversaciones"]:
                clave = (c["titulo"], c["fecha"])
                if clave in vistos:
                    continue
                vistos.add(clave)
                unicos.append(c)
            existing_pendientes[key]["conversaciones"] = unicos
            existing_pendientes[key]["count"] = len(unicos)
        with open(pendientes_path, "w", encoding="utf-8") as f:
            json.dump(existing_pendientes, f, ensure_ascii=False, indent=2)
        print(f"Gizmos sin nombrar: {len(existing_pendientes)} -> {pendientes_path}")


if __name__ == "__main__":
    main()
