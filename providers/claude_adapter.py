# -*- coding: utf-8 -*-
"""providers/claude_adapter.py — Adaptador del export de Claude (claude.ai)
al modelo intermedio de MemorIA2GO.

Contrato de salida (idéntico al de parse_json_conversations en
split_chatgpt_export.py):

    [{"title":       str,
      "create_time": float | None,   # epoch en segundos (iso_date lo espera así)
      "update_time": float | None,
      "messages":    [{"role": str, "content": str}],
      "gizmo_id":    None,           # el export de Claude no vincula proyectos
      "provider":    "claude"}]

Particularidades del formato (autopsia 2026-07-16 contra export real):
- conversations.json es una lista plana de conversaciones con chat_messages
  en orden cronológico. Los mensajes traen parent_message_uuid pero NO hay
  current_node: el hilo vigente se reconstruye eligiendo la hoja con
  created_at más reciente y remontando por los punteros a padre. Consumir
  chat_messages tal cual re-infla los conteos con regeneraciones descartadas
  (misma enfermedad que el mapping de ChatGPT, distinta sintaxis).
- Bloques content tipados: text / thinking / tool_use / tool_result /
  token_budget / flag. v1: solo se vuelcan los text. thinking y tool_* se
  omiten; si un mensaje queda vacío tras el filtrado, se descarta.
- attachments (subidas de usuario) traen extracted_content inline: se
  incluye citado, truncado a ATTACH_MAX_CHARS para no hinchar la nota.
- files son solo referencias (file_name + file_uuid); los binarios NO viajan
  en el zip de Claude -> línea legible, sin extracción a IMAGE_BANK.
- Los exports grandes llegan troceados en varios zips (batch-0000, ...);
  cada zip se parsea por separado y vault_merge reconcilia después.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

# Los attachments con extracted_content son 100% de usuario (verificado contra
# export real: 212/212 en mensajes human) y V0ra conserva los zips originales,
# así que el truncado puede ser agresivo sin pérdida real.
ATTACH_MAX_CHARS = 800

ROLE_MAP = {"human": "user", "assistant": "assistant"}

# Claves de nivel superior de cada conversacion que este adaptador conoce y
# consume. Usado por preflight.detect_new_keys para avisar (no bloquear) si
# el export trae claves nunca vistas -- la senal de que Claude cambio de
# formato antes de que un campo se pierda en silencio por el pipeline.
# Catch-up 2026-07-22: account y summary revisadas contra los exports
# reales de V0ra -- metadatos de cuenta/resumen, no referencian nada que
# el pipeline necesite resolver.
KNOWN_KEYS = frozenset({"uuid", "name", "created_at", "updated_at", "chat_messages", "account", "summary"})


def detect(data: Any) -> bool:
    """True si `data` (el JSON ya cargado de conversations.json) tiene la
    estructura del export de Claude: lista de dicts con chat_messages."""
    return (
        isinstance(data, list)
        and len(data) > 0
        and isinstance(data[0], dict)
        and "chat_messages" in data[0]
    )


def _epoch(iso: Optional[str]) -> Optional[float]:
    """ISO 8601 con Z -> epoch en segundos (lo que espera iso_date())."""
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _thread(msgs: List[dict]) -> List[dict]:
    """Reconstruye el hilo vigente: hoja con created_at más reciente ->
    remontar por parent_message_uuid hasta la raíz. Si algo no cuadra
    (uuids rotos, ciclos), degrada al orden original de la lista."""
    if not msgs:
        return []
    by_uuid = {m.get("uuid"): m for m in msgs if m.get("uuid")}
    parents = {m.get("parent_message_uuid") for m in msgs}
    leaves = [m for m in msgs if m.get("uuid") not in parents]
    if not leaves or len(by_uuid) != len(msgs):
        return msgs  # estructura rara: mejor no inventar
    leaf = max(leaves, key=lambda m: m.get("created_at") or "")
    path: List[dict] = []
    seen = set()
    node: Optional[dict] = leaf
    while node is not None:
        uid = node.get("uuid")
        if uid in seen:
            return msgs  # ciclo: degradar al orden original
        seen.add(uid)
        path.append(node)
        node = by_uuid.get(node.get("parent_message_uuid"))
    path.reverse()
    return path


def _render_attachments(m: dict) -> List[str]:
    """attachments (con contenido extraído) + files (solo referencia).

    Claude lista cada subida de usuario en AMBOS arrays: attachments (con
    extracted_content) y files (solo uuid). Verificado contra export real:
    el 100% de los nombres de attachments reaparece en files. Los files cuyo
    nombre ya salió como attachment del mismo mensaje se omiten para no
    duplicar; el resto (imágenes y binarios sin contenido) sí se referencia."""
    out: List[str] = []
    ya_renderizados = set()
    for a in m.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        name = a.get("file_name") or "archivo sin nombre"
        ya_renderizados.add(name)
        ftype = a.get("file_type") or "tipo desconocido"
        size = a.get("file_size")
        size_txt = f", {size:,} bytes" if isinstance(size, int) else ""
        out.append(f"📎 Archivo adjunto: **{name}** ({ftype}{size_txt})")
        content = (a.get("extracted_content") or "").strip()
        if content:
            if len(content) > ATTACH_MAX_CHARS:
                recorte = len(content) - ATTACH_MAX_CHARS
                content = content[:ATTACH_MAX_CHARS] + f"\n[... contenido truncado: {recorte:,} caracteres más]"
            quoted = "\n".join("> " + ln for ln in content.splitlines())
            out.append(quoted)
    for fl in m.get("files") or []:
        if not isinstance(fl, dict):
            continue
        name = fl.get("file_name") or "archivo sin nombre"
        if name in ya_renderizados:
            continue
        out.append(f"📎 Archivo referenciado (no incluido en el export de Claude): **{name}**")
    return out


def _resolve_artifacts(threaded_msgs: List[dict]) -> Dict[str, dict]:
    """Recorre el hilo YA resuelto (ramas descartadas fuera, ver _thread)
    buscando tool_use de nombre 'artifacts', y devuelve {id: {type, title,
    language, content}} con el ESTADO FINAL tras aplicar create/update/
    rewrite en orden. Decision V0ra 2026-07-22: solo se conserva la version
    final, las revisiones intermedias se descartan -- un artefacto real se
    vio revisado 14 veces en una sola conversacion.

    Formas de 'input' verificadas contra export real:
      create:  {id, type, title, content, language?}
      update:  {id, old_str, new_str}               -- parche sobre el actual
      rewrite: {id, content}                        -- reemplazo completo
    update/rewrite heredan type/title/language de la creacion; si old_str
    no aparece en el contenido actual (deriva/orden inesperado), el update
    se ignora en vez de reventar -- mejor una version algo desactualizada
    que una excepcion a mitad de export."""
    artifacts: Dict[str, dict] = {}
    for m in threaded_msgs:
        for b in m.get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use" or b.get("name") != "artifacts":
                continue
            inp = b.get("input") or {}
            aid = inp.get("id")
            if not aid:
                continue
            cmd = inp.get("command")
            if cmd == "create":
                artifacts[aid] = {
                    "type": inp.get("type") or "text/plain",
                    "title": (inp.get("title") or aid).strip(),
                    "language": inp.get("language"),
                    "content": inp.get("content") or "",
                }
            elif aid not in artifacts:
                continue  # update/rewrite sin create previo en este hilo: no hay base, se ignora
            elif cmd == "rewrite":
                artifacts[aid]["content"] = inp.get("content") or artifacts[aid]["content"]
            elif cmd == "update":
                old, new = inp.get("old_str"), inp.get("new_str")
                if old is not None and new is not None and old in artifacts[aid]["content"]:
                    artifacts[aid]["content"] = artifacts[aid]["content"].replace(old, new, 1)
    return artifacts


def _render_message(m: dict, seen_artifacts: set) -> str:
    chunks: List[str] = _render_attachments(m)
    for b in m.get("content") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            t = (b.get("text") or "").strip()
            if t:
                chunks.append(t)
        elif b.get("type") == "tool_use" and b.get("name") == "artifacts":
            # Un solo marcador por artefacto, en su primer touch (create
            # normalmente) -- las revisiones posteriores no repiten el
            # marcador; el contenido que acaba resolviendo el marcador es
            # siempre el FINAL (ver _resolve_artifacts), no el de este punto.
            aid = (b.get("input") or {}).get("id")
            if aid and aid not in seen_artifacts:
                seen_artifacts.add(aid)
                chunks.append(f"\x00CLAUDEARTIFACT:{aid}\x00")
        # thinking / tool_result / token_budget / flag: omitidos en v1
    return "\n\n".join(chunks).strip()


def parse(data: Any) -> List[Dict[str, Any]]:
    """Export de Claude (JSON ya cargado) -> modelo intermedio."""
    conversations: List[Dict[str, Any]] = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        threaded = _thread(conv.get("chat_messages") or [])
        artifacts = _resolve_artifacts(threaded)
        seen_artifacts: set = set()
        messages: List[Dict[str, str]] = []
        for m in threaded:
            role = ROLE_MAP.get(m.get("sender"), m.get("sender") or "unknown")
            content = _render_message(m, seen_artifacts)
            if content:
                messages.append({"role": role, "content": content})
        if not messages:
            # Conversaciones sin contenido textual (solo bloques thinking/tool):
            # se saltan; no aportan nada al vault y el backup conserva el original.
            continue
        conversations.append({
            "title": (conv.get("name") or "").strip() or "Conversación",
            "create_time": _epoch(conv.get("created_at")),
            "update_time": _epoch(conv.get("updated_at")),
            "messages": messages,
            "gizmo_id": None,
            "provider": "claude",
            "conv_id": conv.get("uuid"),
            "artifacts": artifacts,
        })
    return conversations
