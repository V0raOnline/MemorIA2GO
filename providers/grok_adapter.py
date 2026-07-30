# -*- coding: utf-8 -*-
"""providers/grok_adapter.py — Adaptador del export de Grok (grok.com / X)
al modelo intermedio de MemorIA2GO.

Contrato de salida: idéntico al de parse_json_conversations (ver
claude_adapter.py para el detalle de campos).

Particularidades del formato (autopsia 2026-07-16 contra export real):
- El export es un zip con estructura ttl/30d/export_data/<uuid>/ que contiene
  prod-grok-backend.json (raíz: {conversations, projects, tasks, media_posts})
  y blobs binarios en prod-mc-asset-server//<uuid>/content.
- Cada conversación es un wrapper {conversation: metadatos, responses:
  [{response, share_link}]}. El mensaje es texto plano en response.message.
- Fechas: ISO 8601 a nivel de conversación; formato Mongo Extended JSON
  ({"$date": {"$numberLong": "ms"}}) a nivel de mensaje. Verificado que son
  equivalentes; el adaptador convierte ambos a epoch en segundos.
- Senders inconsistentes ('human', 'ASSISTANT', 'assistant'): se normalizan
  a minúsculas antes de mapear.
- Ramas vía parent_response_id. Existe conversation.leaf_response_id (el
  current_node de Grok) pero viene a None en el export real -> se usa si
  está poblado y, si no, misma estrategia que Claude: hoja más reciente y
  remontar por punteros a padre.
- file_attachments son UUIDs de assets cuyo binario SÍ viaja en el zip
  (ttl/30d/.../prod-mc-asset-server//<uuid>/content). Se emite un marcador
  \x00GROKFILE:<uid>\x00 que split_chatgpt_export.py resuelve con
  GrokAssetIndex/render_grok_file_tokens hacia GROK/ATTACHMENTS (extraccion
  real desde 2026-07-22; v1 solo dejaba una referencia de texto).
- media_posts (generaciones de Imagine) se procesan aparte (no son parte
  del mapping de ninguna conversacion, ver process_grok_media_posts en
  split_chatgpt_export.py) hacia GROK/GENERATED_IMAGE o
  GROK/GENERATED_VIDEO; solo ~18% trae el binario en el zip (verificado
  contra export real), el resto queda en una lista de pendientes de
  descarga. agent_thinking_traces/steps se omiten en v1.
- projects ("workspaces") existen pero las conversaciones no los referencian
  en el export -> gizmo_id None.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

ROLE_MAP = {"human": "user", "assistant": "assistant"}

# Claves del dict 'conversation' (metadatos) que este adaptador conoce y
# consume -- el wrapper {conversation, responses} en si es parte del
# contrato de deteccion (detect()) y no se espera que derive, asi que el
# muestreo de deriva de formato se centra en los metadatos, que es donde
# aparecerian campos nuevos del proveedor. Usado por preflight.detect_new_keys.
#
# Catch-up 2026-07-22 (19 claves, medidas contra los exports reales de
# V0ra): en su mayoria identidad/organizacion (organization_id, team_id,
# workspace_id, user_id, x_user_id, anon_user_id) sin relacion con la
# resolucion de proyecto de este pipeline (Grok no vincula conversaciones
# a projects/workspaces en el export, ver docstring del modulo). Nota
# aparte para la discusion de artefactos: asset_ids/media_types/
# root_asset_id apuntan a las generaciones de Imagine -- relevante para
# esa conversacion, no para este chequeo de deriva.
KNOWN_KEYS = frozenset({
    "id", "title", "create_time", "modify_time", "leaf_response_id",
    "anon_user_id", "asset_ids", "controller", "kind", "media_types",
    "organization_id", "root_asset_id", "shared_with_team",
    "shared_with_user_ids", "starred", "summary", "system_prompt_id",
    "system_prompt_name", "task_result_id", "team_id", "temporary",
    "user_id", "workspace_id", "x_user_id",
})


def detect(data: Any) -> bool:
    """True si `data` tiene la estructura del export de Grok: dict raíz con
    lista conversations cuyos items son wrappers {conversation, responses}."""
    if not isinstance(data, dict):
        return False
    convs = data.get("conversations")
    return (
        isinstance(convs, list)
        and len(convs) > 0
        and isinstance(convs[0], dict)
        and "responses" in convs[0]
    )


def _epoch_iso(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _epoch_mongo(ct: Any) -> Optional[float]:
    """{"$date": {"$numberLong": "ms"}} -> epoch en segundos."""
    try:
        return int(ct["$date"]["$numberLong"]) / 1000.0
    except (TypeError, KeyError, ValueError):
        return None


def _thread(responses: List[dict], leaf_id: Optional[str]) -> List[dict]:
    """Reconstruye el hilo vigente por parent_response_id. Usa
    leaf_response_id si el export lo trae poblado; si no, hoja con
    create_time más reciente. Ante estructura rara, degrada al orden
    original de la lista (que está verificado como cronológico)."""
    msgs = [rw.get("response") or {} for rw in responses]
    if not msgs:
        return []
    by_id = {m.get("_id"): m for m in msgs if m.get("_id")}
    if len(by_id) != len(msgs):
        return msgs
    leaf = by_id.get(leaf_id) if leaf_id else None
    if leaf is None:
        parents = {m.get("parent_response_id") for m in msgs}
        leaves = [m for m in msgs if m.get("_id") not in parents]
        if not leaves:
            return msgs
        leaf = max(leaves, key=lambda m: _epoch_mongo(m.get("create_time")) or 0.0)
    path: List[dict] = []
    seen = set()
    node: Optional[dict] = leaf
    while node is not None:
        nid = node.get("_id")
        if nid in seen:
            return msgs  # ciclo: degradar
        seen.add(nid)
        path.append(node)
        node = by_id.get(node.get("parent_response_id"))
    path.reverse()
    return path


def _render_message(m: dict) -> str:
    chunks: List[str] = []
    for uid in m.get("file_attachments") or []:
        # Marcador \x00GROKFILE:<uid>\x00, resuelto luego por
        # render_grok_file_tokens (split_chatgpt_export.py) hacia
        # GROK/ATTACHMENTS, o degradado a texto legible si no hay banco
        # configurado -- mismo patron que \x00IMG:...\x00 para ChatGPT.
        chunks.append(f"\x00GROKFILE:{uid}\x00")
    text = (m.get("message") or "").strip()
    if text:
        chunks.append(text)
    # agent_thinking_traces / steps / web_search_results: omitidos en v1
    return "\n\n".join(chunks).strip()


def parse(data: Any) -> List[Dict[str, Any]]:
    """Export de Grok (JSON ya cargado) -> modelo intermedio."""
    conversations: List[Dict[str, Any]] = []
    for cw in data.get("conversations") or []:
        if not isinstance(cw, dict):
            continue
        meta = cw.get("conversation") or {}
        messages: List[Dict[str, str]] = []
        modelos_vistos: Dict[str, int] = {}
        for m in _thread(cw.get("responses") or [], meta.get("leaf_response_id")):
            modelo = (m.get("model") or "").strip()
            if modelo:
                modelos_vistos[modelo] = modelos_vistos.get(modelo, 0) + 1
            sender = (m.get("sender") or "").strip().lower()
            role = ROLE_MAP.get(sender, sender or "unknown")
            content = _render_message(m)
            if content:
                messages.append({"role": role, "content": content})
        if not messages:
            continue
        conversations.append({
            "title": (meta.get("title") or "").strip() or "Conversación",
            "create_time": _epoch_iso(meta.get("create_time")),
            "update_time": _epoch_iso(meta.get("modify_time")),
            "messages": messages,
            "gizmo_id": None,
            "provider": "grok",
            "conv_id": meta.get("id"),
            # Modelo mas frecuente del hilo (grok-3, grok-4...); empate -> alfabetico
            "model": max(sorted(modelos_vistos), key=lambda m: modelos_vistos[m]) if modelos_vistos else None,
        })
    return conversations
