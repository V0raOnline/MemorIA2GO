# -*- coding: utf-8 -*-
"""providers/codex_adapter.py — Adaptador de las sesiones locales de Codex
(OpenAI) al MISMO modelo de sesion que claudecode_adapter.

Emite el modelo comun {provider, session_id, project, git_branch, title,
create_time, update_time, turns:[...]} para que session_notes y session_ingest
lo reusen sin cambios. La unica diferencia entre proveedores vive aqui.

AUTOPSIA DEL FORMATO (medida contra las sesiones reales de V0ra, 2026-08-31)
────────────────────────────────────────────────────────────────────────────
`~/.codex/sessions/AAAA/MM/DD/rollout-<ts>-<uuid>.jsonl`. Una linea =
`{timestamp, type, payload}`. Cuatro `type`:
- `session_meta`: cabecera (id, cwd, cli_version, originator).
- `response_item`: el hilo real. Su `payload.type` es lo que importa:
    · `message` (role user/assistant/developer) -- content es lista de bloques
      {type: input_text|output_text, text}.
    · `reasoning` -- el pensamiento, pero SIEMPRE cifrado (`encrypted_content`,
      sin texto plano). No recuperable: la nota de razonamientos nunca se crea
      para Codex. Coherente con lo medido.
    · `function_call` + `function_call_output` -- una herramienta y su
      resultado, casados por `call_id`.
    · `custom_tool_call` + `custom_tool_call_output` -- otra clase de
      herramienta (p.ej. apply_patch), igual patron.
- `event_msg`: eventos de interfaz. La mayoria DUPLICAN contenido (agent_message
  repite el message del asistente) o son ruido (token_count, task_*). Se
  ignoran TODOS menos `user_message`, que es el prompt humano LIMPIO -- sin los
  tags de contexto que lleva el message role=user (`<environment_context>`...).
- `turn_context`: metadatos por turno (modelo, cwd). Se ignora.

CLAVE DE DISEÑO: los turnos de usuario salen de `event_msg/user_message` (texto
limpio), el resto de `response_item`. Un unico recorrido ordenado por linea, sin
heuristicas de "esto parece contexto": cada cosa de su fuente. Medido: 37
user_message = 37 prompts humanos; los message role=user traen 2 de contexto de
mas que asi no se cuelan.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def detect(primera_linea: str) -> bool:
    """True si esto huele a una sesion de Codex. La primera linea util es el
    session_meta con originator de Codex; se acepta tambien cualquier linea
    {timestamp, type, payload} por si el meta no fuera la primera."""
    try:
        d = json.loads(primera_linea)
    except (ValueError, TypeError):
        return False
    if not isinstance(d, dict):
        return False
    if d.get("type") == "session_meta":
        return True
    return "payload" in d and "type" in d and "timestamp" in d


def _texto_de_bloques(content: Any) -> str:
    """content de un message -> texto plano. Los bloques son {type, text} con
    type input_text (entrada) u output_text (salida)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("text"))
    return ""


def _input_de_call(p: dict) -> dict:
    """Normaliza los argumentos de una herramienta a dict, para que
    session_notes._primer_arg saque un resumen legible. function_call trae
    `arguments` como JSON string; custom_tool_call trae `input` como texto."""
    args = p.get("arguments")
    if isinstance(args, str):
        try:
            d = json.loads(args)
            if isinstance(d, dict):
                return d
        except (ValueError, TypeError):
            pass
        return {"command": args}
    inp = p.get("input")
    if isinstance(inp, str):
        return {"command": inp}
    if isinstance(inp, dict):
        return inp
    return {}


def parse_lineas(lineas: List[str]) -> Optional[Dict[str, Any]]:
    """Lista de lineas JSONL de Codex -> modelo de sesion comun, o None."""
    filas = []
    for l in lineas:
        l = l.strip()
        if not l:
            continue
        try:
            filas.append(json.loads(l))
        except (ValueError, TypeError):
            continue
    if not filas:
        return None

    session_id = cwd = None
    for d in filas:
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            session_id = p.get("id")
            cwd = p.get("cwd")
            break

    # Resultados de herramienta por call_id (las dos clases).
    resultados: Dict[str, str] = {}
    for d in filas:
        if d.get("type") != "response_item":
            continue
        p = d.get("payload") or {}
        if p.get("type") in ("function_call_output", "custom_tool_call_output"):
            out = p.get("output")
            resultados[p.get("call_id")] = out if isinstance(out, str) else json.dumps(out)

    turns: List[Dict[str, Any]] = []
    abierto: Optional[Dict[str, Any]] = None

    def cerrar():
        nonlocal abierto
        if abierto is not None:
            abierto["text"] = "\n\n".join(abierto["_textos"]).strip()
            del abierto["_textos"]
            turns.append(abierto)
            abierto = None

    def abrir_asistente(ts):
        nonlocal abierto
        if abierto is None:
            abierto = {"role": "assistant", "ts": ts, "_textos": [],
                       "thinking": [], "tools": []}

    for d in filas:
        t = d.get("type")
        p = d.get("payload") or {}
        ts = _epoch(d.get("timestamp"))

        # Prompt humano: viene limpio en event_msg/user_message.
        if t == "event_msg" and p.get("type") == "user_message":
            cerrar()
            turns.append({"role": "user",
                          "text": (p.get("message") or "").strip(), "ts": ts})
            continue

        if t != "response_item":
            continue
        pt = p.get("type")

        if pt == "message":
            # El asistente aporta texto; user/developer se ignoran (el prompt
            # limpio ya vino por event_msg; developer es el system prompt).
            if p.get("role") == "assistant":
                txt = _texto_de_bloques(p.get("content")).strip()
                if txt:
                    abrir_asistente(ts)
                    abierto["_textos"].append(txt)
        elif pt == "reasoning":
            # Siempre cifrado en Codex: no hay texto que anotar. Se deja el
            # gancho por si algun dia trajera `summary`/`content` legibles.
            resumen = _texto_de_bloques(p.get("summary")) or _texto_de_bloques(p.get("content"))
            if resumen.strip():
                abrir_asistente(ts)
                abierto["thinking"].append(resumen.strip())
        elif pt in ("function_call", "custom_tool_call"):
            abrir_asistente(ts)
            abierto["tools"].append({
                "name": p.get("name"),
                "input": _input_de_call(p),
                "result": resultados.get(p.get("call_id"), ""),
                "id": p.get("call_id"),
            })
    cerrar()

    if not turns:
        return None

    tss = [t["ts"] for t in turns if t.get("ts")]
    return {
        "provider": "codex",
        "session_id": session_id,
        "project": cwd,
        "git_branch": None,        # Codex no lo trae en session_meta
        "title": None,             # sin aiTitle; session_notes usa el 1er prompt
        "create_time": min(tss) if tss else None,
        "update_time": max(tss) if tss else None,
        "turns": turns,
    }


def parse_fichero(path: Any) -> Optional[Dict[str, Any]]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return parse_lineas(f.readlines())
