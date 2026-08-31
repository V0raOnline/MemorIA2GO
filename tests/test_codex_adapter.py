# -*- coding: utf-8 -*-
"""Tests del adaptador de Codex (providers/codex_adapter.py, paso 4).

El .jsonl sintetico reproduce las trampas medidas contra las sesiones reales de
V0ra el 2026-08-31:
  - el prompt humano viene LIMPIO en event_msg/user_message; los message
    role=user traen contexto inyectado (<environment_context>) que no debe
    colarse,
  - message role=developer es el system prompt y se ignora,
  - reasoning esta cifrado (sin texto): nunca crea nota de razonamientos,
  - las herramientas son de dos clases (function_call, custom_tool_call) y su
    resultado se casa por call_id,
  - emite el MISMO modelo que claudecode_adapter, para reusar session_notes.
"""
import json

from providers import codex_adapter as cx


def _jsonl(*eventos):
    return [json.dumps(e, ensure_ascii=False) for e in eventos]


def _sesion():
    return _jsonl(
        {"timestamp": "2026-04-06T18:00:00Z", "type": "session_meta",
         "payload": {"id": "SES-1", "cwd": "/repo/DriftCompass",
                     "originator": "Codex Desktop"}},
        # contexto inyectado como message user: NO es un prompt humano
        {"timestamp": "2026-04-06T18:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "<permissions>...</permissions>"}]}},
        {"timestamp": "2026-04-06T18:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "<environment_context><cwd>/repo</cwd></environment_context>"}]}},
        # el prompt humano LIMPIO
        {"timestamp": "2026-04-06T18:00:03Z", "type": "event_msg",
         "payload": {"type": "user_message", "message": "compara los dos ficheros"}},
        # reasoning cifrado: sin texto
        {"timestamp": "2026-04-06T18:00:04Z", "type": "response_item",
         "payload": {"type": "reasoning", "summary": [], "content": None,
                     "encrypted_content": "gAAAA..."}},
        {"timestamp": "2026-04-06T18:00:05Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Voy a mirarlos."}]}},
        # herramienta clasica
        {"timestamp": "2026-04-06T18:00:06Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell_command",
                     "arguments": '{"command":"ls -la"}', "call_id": "c1"}},
        {"timestamp": "2026-04-06T18:00:07Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "c1",
                     "output": "foo.html\nbar.html"}},
        # herramienta custom (apply_patch)
        {"timestamp": "2026-04-06T18:00:08Z", "type": "response_item",
         "payload": {"type": "custom_tool_call", "name": "apply_patch",
                     "input": "*** Begin Patch...", "call_id": "c2"}},
        {"timestamp": "2026-04-06T18:00:09Z", "type": "response_item",
         "payload": {"type": "custom_tool_call_output", "call_id": "c2",
                     "output": "patch aplicado"}},
        {"timestamp": "2026-04-06T18:00:10Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Listo, son distintos."}]}},
        # ruido que se ignora
        {"timestamp": "2026-04-06T18:00:11Z", "type": "event_msg",
         "payload": {"type": "agent_message", "message": "Listo, son distintos."}},
        {"timestamp": "2026-04-06T18:00:12Z", "type": "event_msg",
         "payload": {"type": "token_count", "info": {}}},
    )


def test_emite_el_modelo_comun():
    s = cx.parse_lineas(_sesion())
    assert s["provider"] == "codex"
    assert s["session_id"] == "SES-1"
    assert s["project"] == "/repo/DriftCompass"
    assert [t["role"] for t in s["turns"]] == ["user", "assistant"]


def test_el_prompt_humano_viene_limpio_no_el_contexto():
    s = cx.parse_lineas(_sesion())
    assert s["turns"][0]["text"] == "compara los dos ficheros"
    # el <environment_context> del message role=user NO se cuela
    assert "environment_context" not in s["turns"][0]["text"]
    assert "<cwd>" not in s["turns"][0]["text"]


def test_texto_del_asistente_concatenado():
    s = cx.parse_lineas(_sesion())
    resp = s["turns"][1]
    assert "Voy a mirarlos." in resp["text"]
    assert "Listo, son distintos." in resp["text"]


def test_las_dos_clases_de_herramienta_con_su_resultado():
    s = cx.parse_lineas(_sesion())
    tools = s["turns"][1]["tools"]
    assert [t["name"] for t in tools] == ["shell_command", "apply_patch"]
    assert tools[0]["result"] == "foo.html\nbar.html"
    assert tools[1]["result"] == "patch aplicado"
    # arguments JSON se normaliza a dict para el resumen de session_notes
    assert tools[0]["input"] == {"command": "ls -la"}


def test_reasoning_cifrado_no_crea_pensamiento():
    s = cx.parse_lineas(_sesion())
    assert s["turns"][1]["thinking"] == []


def test_el_developer_system_prompt_se_ignora():
    s = cx.parse_lineas(_sesion())
    # ni el developer ni el message role=user aparecen como turnos
    assert len([t for t in s["turns"] if t["role"] == "user"]) == 1


def test_detect():
    assert cx.detect(json.dumps(
        {"timestamp": "x", "type": "session_meta", "payload": {"id": "S"}}))
    assert cx.detect(json.dumps(
        {"timestamp": "x", "type": "response_item", "payload": {"type": "message"}}))
    # un .jsonl de Claude Code NO es Codex
    assert not cx.detect(json.dumps({"sessionId": "S", "type": "user", "message": {}}))
    assert not cx.detect("no es json")


def test_sesion_vacia_da_none():
    assert cx.parse_lineas([]) is None
    assert cx.parse_lineas([json.dumps(
        {"timestamp": "x", "type": "event_msg", "payload": {"type": "token_count"}})]) is None


def test_reasoning_con_summary_legible_si_apareciera():
    """Gancho: si algun dia Codex trajera el resumen en claro, se anota."""
    lineas = _jsonl(
        {"timestamp": "x", "type": "session_meta", "payload": {"id": "S"}},
        {"timestamp": "x", "type": "event_msg",
         "payload": {"type": "user_message", "message": "hola"}},
        {"timestamp": "x", "type": "response_item",
         "payload": {"type": "reasoning",
                     "summary": [{"type": "text", "text": "pienso esto"}],
                     "content": None}},
        {"timestamp": "x", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "respondo"}]}},
    )
    s = cx.parse_lineas(lineas)
    assert s["turns"][1]["thinking"] == ["pienso esto"]
