# -*- coding: utf-8 -*-
"""providers/claudecode_adapter.py — Adaptador de las sesiones LOCALES de
Claude Code al modelo de sesion de MemorIA2GO.

POR QUE ES DISTINTO A LOS DEMAS ADAPTADORES
───────────────────────────────────────────
Los otros adaptadores comen exports de cuenta y producen conversaciones planas
(`messages: [{role, content}]`) que van a una nota por conversacion. Una sesion
de agente no es eso: tiene pensamiento y decenas de llamadas a herramientas por
turno. Volcarlo plano da un log ilegible; tirar las herramientas tira el trabajo
que la hace valiosa.

Por eso este adaptador emite un modelo mas rico (ver `parse`), que un generador
posterior reparte en tres notas enlazadas -- madre (conversacion), razonamientos
y herramientas. Diseño cerrado en CONTEXT.md 3y.

Y es la unica fuente de la casa que NO sale de ningun export: estas sesiones
solo existen en `~/.claude/projects/<hash>/*.jsonl`, que nadie respalda. Si no
se recogen, se pierden.

ESTE FICHERO ES EL PASO 1: el parser. No genera notas ni copia la fuente
todavia -- solo convierte un `.jsonl` en el modelo de sesion. La generacion de
notas y el banco de fuente cruda vienen despues.

AUTOPSIA DEL FORMATO (medida contra las sesiones reales de V0ra, 2026-08-31)
────────────────────────────────────────────────────────────────────────────
- Una linea = un evento JSON. Muchos tipos son ruido de interfaz que este
  adaptador ignora: queue-operation, last-prompt, custom-title, ai-title,
  atis-latch, attachment, mode, y los system de hooks.
- Los eventos con contenido real llevan `message` con `role` y `content`.
- `content` del asistente es una lista de bloques: text, thinking, tool_use.
- `content` del usuario es un str (prompt) O una lista con tool_result (la
  respuesta de una herramienta, que Claude Code modela como turno de usuario).
- El texto del asistente y sus tool_use viven en MENSAJES SEPARADOS, no en el
  mismo. Por eso los turnos se agrupan por prompt humano, no por mensaje: todo
  el trabajo del asistente entre dos prompts humanos es UNA respuesta.
- Prompt humano real: `origin.kind == "human"`. Lo distingue de los user
  sinteticos (`<command-name>`, `<local-command-stdout>`, caveats de hooks),
  que se ignoran como delimitadores.
- El hilo se encadena con `parentUuid`; las ramas laterales llevan
  `isSidechain: true` y se descartan (no son la conversacion principal).
- El pensamiento (`thinking`) trae texto SOLO si estaba visible en la sesion;
  si no, queda la `signature` y el texto viene vacio. No es recuperable hacia
  atras. El adaptador lo trata como "no disponible", no como error.
- Titulo: `aiTitle` (o `customTitle`) en algun evento de la sesion.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Tipos de evento que son ruido de interfaz: nunca aportan contenido.
RUIDO = frozenset({
    "queue-operation", "last-prompt", "custom-title", "ai-title",
    "atis-latch", "attachment", "mode",
})


def _epoch(iso: Optional[str]) -> Optional[float]:
    """ISO 8601 -> epoch en segundos, como el resto de adaptadores. Tolerante:
    una fecha rara no puede tumbar el parseo de una sesion entera."""
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def detect(primera_linea: str) -> bool:
    """True si esto huele a una sesion de Claude Code. Barato: mira solo la
    primera linea, que siempre trae sessionId y, o bien un type conocido, o
    el evento de arranque. No carga el fichero entero."""
    try:
        d = json.loads(primera_linea)
    except (ValueError, TypeError):
        return False
    return isinstance(d, dict) and "sessionId" in d and (
        "type" in d or "message" in d)


def _es_prompt_humano(d: dict) -> bool:
    """Un prompt tecleado por la persona, no un user sintetico (comandos,
    salidas locales, caveats de hooks)."""
    if d.get("type") != "user":
        return False
    if not isinstance((d.get("message") or {}).get("content"), str):
        return False
    return (d.get("origin") or {}).get("kind") == "human"


def _bloques(d: dict) -> List[dict]:
    c = (d.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def _texto_tool_result(bloque: dict) -> str:
    """El resultado de una herramienta puede venir como str o como lista de
    sub-bloques {type:text}. Se normaliza a str."""
    cont = bloque.get("content")
    if isinstance(cont, str):
        return cont
    if isinstance(cont, list):
        return "\n".join(x.get("text", "") for x in cont
                         if isinstance(x, dict) and x.get("type") == "text")
    return ""


def parse_lineas(lineas: List[str]) -> Optional[Dict[str, Any]]:
    """Lista de lineas JSONL -> modelo de sesion, o None si no hay nada util.

    Modelo de salida:
        {
          "provider": "claude-code",
          "session_id": str,
          "project": str | None,     # el cwd de la sesion
          "git_branch": str | None,
          "title": str | None,       # aiTitle/customTitle si los hay
          "create_time": float | None,
          "update_time": float | None,
          "turns": [
            {"role": "user", "text": str, "ts": float | None},
            {"role": "assistant", "ts": float | None,
             "text": str,                     # texto concatenado del turno
             "thinking": [str, ...],          # vacio si no estaba visible
             "tools": [{"name", "input", "result", "id"}, ...]},
          ],
        }

    Los turnos se agrupan por prompt humano: cada prompt abre un turno de
    usuario y todo el trabajo del asistente hasta el siguiente prompt humano
    se acumula en una unica respuesta de asistente.
    """
    filas = []
    for l in lineas:
        l = l.strip()
        if not l:
            continue
        try:
            filas.append(json.loads(l))
        except (ValueError, TypeError):
            continue  # una linea corrupta no tumba la sesion
    if not filas:
        return None

    session_id = next((d.get("sessionId") for d in filas if d.get("sessionId")), None)
    cwd = next((d.get("cwd") for d in filas if d.get("cwd")), None)
    branch = next((d.get("gitBranch") for d in filas if d.get("gitBranch")), None)
    title = next((d.get("aiTitle") or d.get("customTitle")
                  for d in filas if d.get("aiTitle") or d.get("customTitle")), None)

    # Resultados de herramienta, por id de la llamada (llegan en turnos user).
    resultados: Dict[str, str] = {}
    for d in filas:
        if d.get("type") == "user":
            for b in _bloques(d):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    resultados[b.get("tool_use_id")] = _texto_tool_result(b)

    turns: List[Dict[str, Any]] = []
    abierto: Optional[Dict[str, Any]] = None  # respuesta de asistente en curso

    def cerrar():
        nonlocal abierto
        if abierto is not None:
            abierto["text"] = "\n\n".join(abierto["_textos"]).strip()
            del abierto["_textos"]
            turns.append(abierto)
            abierto = None

    for d in filas:
        if d.get("type") in RUIDO:
            continue
        if d.get("isSidechain"):
            continue  # rama lateral, no la conversacion principal

        if _es_prompt_humano(d):
            cerrar()
            turns.append({
                "role": "user",
                "text": (d.get("message") or {}).get("content", "").strip(),
                "ts": _epoch(d.get("timestamp")),
            })
            continue

        if d.get("type") == "assistant":
            bloques = _bloques(d)
            if not bloques:
                continue
            if abierto is None:
                abierto = {"role": "assistant", "ts": _epoch(d.get("timestamp")),
                           "_textos": [], "thinking": [], "tools": []}
            for b in bloques:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    t = (b.get("text") or "").strip()
                    if t:
                        abierto["_textos"].append(t)
                elif bt == "thinking":
                    t = (b.get("thinking") or "").strip()
                    if t:  # vacio = no estaba visible; no se anota
                        abierto["thinking"].append(t)
                elif bt == "tool_use":
                    abierto["tools"].append({
                        "name": b.get("name"),
                        "input": b.get("input") or {},
                        "result": resultados.get(b.get("id"), ""),
                        "id": b.get("id"),
                    })
    cerrar()

    if not turns:
        return None

    tss = [t["ts"] for t in turns if t.get("ts")]
    return {
        "provider": "claude-code",
        "session_id": session_id,
        "project": cwd,
        "git_branch": branch,
        "title": title,
        "create_time": min(tss) if tss else None,
        "update_time": max(tss) if tss else None,
        "turns": turns,
    }


def parse_fichero(path: Any) -> Optional[Dict[str, Any]]:
    """Conveniencia: lee un .jsonl de disco y lo parsea. utf-8 estricto; el
    formato es siempre UTF-8 sin BOM."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return parse_lineas(f.readlines())
