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


def render_image_tokens(content: str, asset_index: Optional[AssetIndex],
                         asset_writer: Optional[AssetWriter],
                         rel_prefix: Optional[str],
                         image_meta: Optional[Dict[str, dict]] = None,
                         conv_title: Optional[str] = None) -> str:
    """Sustituye los marcadores \\x00IMG:<pointer>\\x00 por markdown real,
    o por un aviso explícito si no hay banco de assets configurado o el
    binario no está presente en el export. Si image_meta trae informacion
    para ese pointer (prompt de DALL-E, nombre de adjunto, dimensiones),
    se adjunta al manifiesto del AssetWriter junto con la conversacion."""

    def _sub(m: "re.Match[str]") -> str:
        pointer = m.group("pointer")
        if asset_writer is None or asset_index is None or rel_prefix is None:
            return f"*[imagen omitida: {pointer}]*"
        found = asset_index.get_bytes(pointer)
        if not found:
            return f"*[imagen no disponible en el export: {pointer}]*"
        data, ext = found
        meta = None
        if image_meta is not None:
            base_meta = image_meta.get(pointer)
            if base_meta:
                meta = dict(base_meta)
                if conv_title:
                    meta["primera_conversacion"] = conv_title
        fname = asset_writer.write(data, ext, meta=meta)
        rel_path = f"{rel_prefix}/{fname}".replace("\\", "/")
        return f"![]({rel_path})"

    return IMAGE_TOKEN_RE.sub(_sub, content)


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
            i = 2
            while os.path.exists(write_path):
                write_path = f"{base}-h{h}-{i}{ext}"
                i += 1
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


def _render_parts(c: Any, image_meta_out: Optional[Dict[str, dict]] = None,
                   att_ids: Optional[Dict[str, str]] = None) -> str:
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
                        dalle = (p.get("metadata") or {}).get("dalle") or {}
                        meta: dict = {}
                        if dalle.get("prompt"):
                            meta["origen"] = "dalle"
                            meta["prompt"] = dalle.get("prompt")
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
        return "\n".join(chunks)
    elif isinstance(c, list):
        return "\n".join(str(p) for p in c)
    elif isinstance(c, str):
        return c
    else:
        return json.dumps(c, ensure_ascii=False)


def parse_json_conversations(obj: Any, image_meta_out: Optional[Dict[str, dict]] = None) -> List[Dict[str, Any]]:
    conversations: List[Dict[str, Any]] = []

    if isinstance(obj, dict) and "conversations" in obj and isinstance(obj["conversations"], list):
        raw = obj["conversations"]
    elif isinstance(obj, list):
        raw = obj
    else:
        raw = obj.get("items", []) if isinstance(obj, dict) else []

    for conv in raw:
        title = conv.get("title") or "Conversación"
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
                content = _render_parts(c, image_meta_out=image_meta_out, att_ids=att_ids)
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
                content = _render_parts(m.get("content") or "", image_meta_out=image_meta_out, att_ids=att_ids)
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


def _dispatch(data: Any, image_meta_out: Optional[Dict[str, dict]] = None) -> List[Dict[str, Any]]:
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
    return parse_json_conversations(data, image_meta_out=image_meta_out)


def load_conversations(input_path: str, image_meta_out: Optional[Dict[str, dict]] = None) -> Tuple[List[Dict[str, Any]], Optional[zipfile.ZipFile]]:
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
            return _dispatch(combinado, image_meta_out=image_meta_out), zf

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
            return _dispatch(data, image_meta_out=image_meta_out), zf
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
        return _dispatch(data, image_meta_out=image_meta_out), None

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

    ap.add_argument("--assets-dir", default=None,
                    help="Carpeta donde extraer imágenes (subidas y generadas), deduplicadas por hash. "
                         "Si se omite, las imágenes quedan como aviso de texto, sin extraer binarios.")

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

    conversations, zf = load_conversations(args.input, image_meta_out=image_meta)
    if not conversations:
        print("No se encontraron conversaciones.")
        sys.exit(2)

    asset_index = AssetIndex(zf) if args.assets_dir else None
    asset_writer = AssetWriter(args.assets_dir) if args.assets_dir else None
    if args.assets_dir:
        print(f"Assets indexados en el ZIP: {len(asset_index.by_id)}")

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

        # Resolver marcadores de imagen antes de escribir, con la ruta relativa
        # correcta según la profundidad real de salida (year/month) de esta nota.
        if args.assets_dir:
            y, m, _ = date_primary.split("-")
            note_dir = compute_out_dir(args.output, y, m, args.by_year, args.by_month)
            # Enlaces desde la RAIZ del vault de Obsidian, no relativos.
            # Los relativos ../../../_assets/ dependian del junction _assets
            # dentro de cada subvault; cuando Obsidian abre la carpeta padre
            # (02 Obsidian_vaults) los .. salen del sitio donde el junction
            # existe y todas las imagenes se rompen (bug 2026-07-20). La ruta
            # absoluta desde el vault raiz funciona en cualquier layout:
            # va directo a IMAGE_BANK sin depender de la topologia.
            rel_prefix = "IMAGE_BANK"
            rendered_msgs = []
            for msg in msgs:
                raw_content = msg.get("content", "")
                total_images += len(IMAGE_TOKEN_RE.findall(raw_content))
                rendered = render_image_tokens(raw_content, asset_index, asset_writer, rel_prefix,
                                                image_meta=image_meta, conv_title=title)
                rendered_msgs.append({"role": msg.get("role"), "content": rendered})
            msgs = rendered_msgs
        else:
            # Sin --assets-dir: deja aviso de texto en vez del marcador interno
            msgs = [{"role": m.get("role"),
                     "content": render_image_tokens(m.get("content", ""), None, None, None)}
                    for m in msgs]

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
    if args.assets_dir:
        print(f"Referencias de imagen procesadas: {total_images}")
        print(f"Binarios únicos copiados a assets: {len(asset_writer.hash_to_filename)}")

        if asset_writer.manifest:
            manifest_path = os.path.join(args.assets_dir, "_image_manifest.json")
            existing_manifest: Dict[str, dict] = {}
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        existing_manifest = json.load(f)
                except Exception:
                    existing_manifest = {}
            existing_manifest.update(asset_writer.manifest)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(existing_manifest, f, ensure_ascii=False, indent=2)
            print(f"Manifiesto de imagenes actualizado: {manifest_path} ({len(existing_manifest)} imagenes con metadatos)")

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
