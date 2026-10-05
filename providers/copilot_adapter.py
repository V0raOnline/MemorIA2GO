# -*- coding: utf-8 -*-
"""providers/copilot_adapter.py — Adaptador del export de Copilot (Microsoft)
al modelo intermedio de MemorIA2GO.

Contrato de salida (idéntico al de parse_json_conversations en
split_chatgpt_export.py):

    [{"title":       str,
      "create_time": float | None,   # epoch en segundos
      "update_time": float | None,
      "messages":    [{"role": str, "content": str}],
      "gizmo_id":    None,
      "provider":    "copilot"}]

Particularidades del formato (CSVs de Copilot):
- Estructura: Conversation, Time, Author, Message (con BOM UTF-8, CRLF)
- Author: "AI" | "User" (normalizar a "assistant"/"user")
- Time: ISO 8601 (2026-09-19T06:48:20)
- Message: puede tener saltos de línea dentro de comillas (CSV estándar)
- Múltiples mensajes por conversación, agrupados por Conversation
- Conversaciones vacías (solo headers) se ignoran
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

ROLE_MAP = {
    "AI": "assistant",
    "User": "user",
    "ai": "assistant",
    "user": "user",
    "assistant": "assistant",
    "human": "user",
}

# Claves del dict (fila CSV) que este adaptador conoce y consume.
KNOWN_KEYS = frozenset({"Conversation", "Time", "Author", "Message"})


def detect(data: Any) -> bool:
    """True si `data` (lista de dicts con filas del CSV parseadas)
    tiene la estructura del export de Copilot: lista con dicts que
    tienen Conversation/Time/Author/Message."""
    return (
        isinstance(data, list)
        and len(data) > 0
        and isinstance(data[0], dict)
        and all(k in data[0] for k in ["Conversation", "Time", "Author", "Message"])
    )


def _epoch(iso: Optional[str]) -> Optional[float]:
    """ISO 8601 -> epoch en segundos (lo que espera iso_date())."""
    if not iso:
        return None
    try:
        # ISO 8601 sin Z (Copilot no lo usa), o con Z si la hubiera
        iso_str = iso.strip()
        if iso_str.endswith("Z"):
            iso_str = iso_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(iso_str).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def parse(data: Any) -> List[Dict[str, Any]]:
    """CSV de Copilot (lista de filas cargadas) -> modelo intermedio.

    Agrupa mensajes por Conversation y genera una conversación por grupo.
    """
    if not data or not isinstance(data, list):
        return []

    # Agrupar por Conversation
    conversations_dict: Dict[str, List[dict]] = {}
    timestamps_by_conv: Dict[str, List[float]] = {}

    for row in data:
        if not isinstance(row, dict):
            continue

        conv_name = (row.get("Conversation") or "").strip()
        if not conv_name:
            continue  # Ignorar filas sin nombre de conversación

        if conv_name not in conversations_dict:
            conversations_dict[conv_name] = []
            timestamps_by_conv[conv_name] = []

        # Procesar este mensaje
        author = (row.get("Author") or "User").strip()
        role = ROLE_MAP.get(author, "user")

        message_text = (row.get("Message") or "").strip()
        if not message_text:
            continue  # Ignorar mensajes vacíos

        time_str = (row.get("Time") or "").strip()
        epoch = _epoch(time_str)
        if epoch:
            timestamps_by_conv[conv_name].append(epoch)

        conversations_dict[conv_name].append({
            "role": role,
            "content": message_text,
            "time": epoch,
        })

    # Convertir a conversaciones del modelo intermedio
    conversations: List[Dict[str, Any]] = []
    for conv_name, messages in conversations_dict.items():
        if not messages:
            continue  # Ignorar conversaciones vacías

        # Calcular create_time (primer mensaje) y update_time (último)
        times = timestamps_by_conv.get(conv_name, [])
        create_time = min(times) if times else None
        update_time = max(times) if times else None

        # Quitar el timestamp de cada mensaje (no es parte del contrato)
        clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        conversations.append({
            "title": conv_name,
            "create_time": create_time,
            "update_time": update_time,
            "messages": clean_messages,
            "gizmo_id": None,
            "provider": "copilot",
        })

    return conversations
