# -*- coding: utf-8 -*-
"""Tests del adaptador de sesiones locales de Claude Code (paso 1: el parser).

El .jsonl sintetico reproduce las trampas medidas contra las sesiones reales de
V0ra el 2026-08-31:
  - texto del asistente y tool_use en MENSAJES SEPARADOS -> deben agruparse en
    un solo turno,
  - tool_result llega como turno de usuario y hay que casarlo por id,
  - user sinteticos (comandos, hooks) que NO deben abrir turno,
  - ramas laterales (isSidechain) que se descartan,
  - thinking vacio (no estaba visible) que no se anota, y con texto que si.
"""
import json
from pathlib import Path

from providers import claudecode_adapter as cc


def _jsonl(*eventos) -> list:
    return [json.dumps(e, ensure_ascii=False) for e in eventos]


def _sesion_base():
    """Un prompt humano, el asistente responde con texto + una herramienta en
    mensajes separados, y cierra con mas texto. Lo normal de una sesion."""
    return _jsonl(
        {"type": "queue-operation", "sessionId": "S1"},          # ruido
        {"type": "user", "sessionId": "S1", "cwd": "/repo",
         "gitBranch": "main", "timestamp": "2026-08-27T10:00:00Z",
         "origin": {"kind": "human"},
         "message": {"role": "user", "content": "arregla el bug"}},
        {"type": "assistant", "sessionId": "S1",
         "timestamp": "2026-08-27T10:00:05Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "el bug esta en la linea 40",
              "signature": "xxx"},
             {"type": "text", "text": "Voy a mirar el fichero."},
         ]}},
        # tool_use en un mensaje assistant SEPARADO del texto de arriba
        {"type": "assistant", "sessionId": "S1",
         "timestamp": "2026-08-27T10:00:06Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "foo.py"}},
         ]}},
        # el resultado llega como turno de usuario
        {"type": "user", "sessionId": "S1",
         "timestamp": "2026-08-27T10:00:07Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": "linea 40: return None"}]}},
        {"type": "assistant", "sessionId": "S1",
         "timestamp": "2026-08-27T10:00:08Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Encontrado. Era un return de mas."},
         ]}},
        {"type": "ai-title", "sessionId": "S1", "aiTitle": "Arreglo del bug"},
    )


def test_agrupa_el_trabajo_del_asistente_en_un_solo_turno():
    ses = cc.parse_lineas(_sesion_base())
    assert ses is not None
    assert [t["role"] for t in ses["turns"]] == ["user", "assistant"]

    resp = ses["turns"][1]
    # El texto de los dos mensajes assistant separados queda concatenado.
    assert "Voy a mirar el fichero." in resp["text"]
    assert "Era un return de mas." in resp["text"]
    # La herramienta y su resultado, casados por id.
    assert len(resp["tools"]) == 1
    assert resp["tools"][0]["name"] == "Read"
    assert resp["tools"][0]["result"] == "linea 40: return None"


def test_el_thinking_con_texto_se_anota():
    ses = cc.parse_lineas(_sesion_base())
    assert ses["turns"][1]["thinking"] == ["el bug esta en la linea 40"]


def test_el_thinking_vacio_no_se_anota():
    """En la mayoria de sesiones el pensamiento no estaba visible: solo firma,
    texto vacio. Eso no es contenido y no debe crear una nota de razonamientos
    fantasma."""
    lineas = _jsonl(
        {"type": "user", "sessionId": "S", "origin": {"kind": "human"},
         "timestamp": "2026-08-27T10:00:00Z",
         "message": {"role": "user", "content": "hola"}},
        {"type": "assistant", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "", "signature": "solo-firma"},
             {"type": "text", "text": "hola que tal"},
         ]}},
    )
    ses = cc.parse_lineas(lineas)
    assert ses["turns"][1]["thinking"] == []
    assert ses["turns"][1]["text"] == "hola que tal"


def test_los_user_sinteticos_no_abren_turno():
    """Comandos slash y salidas locales llegan como type=user pero sin
    origin.kind==human: no son prompts, no deben partir un turno."""
    lineas = _jsonl(
        {"type": "user", "sessionId": "S", "origin": {"kind": "human"},
         "timestamp": "2026-08-27T10:00:00Z",
         "message": {"role": "user", "content": "primera pregunta"}},
        {"type": "assistant", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "respondo"}]}},
        # comando slash: NO lleva origin.kind human
        {"type": "user", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:02Z",
         "message": {"role": "user",
                     "content": "<command-name>/model</command-name>"}},
        {"type": "user", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:03Z",
         "message": {"role": "user",
                     "content": "<local-command-stdout>ok</local-command-stdout>"}},
    )
    ses = cc.parse_lineas(lineas)
    # Un solo turno de usuario: los dos sinteticos no cuentan.
    assert [t["role"] for t in ses["turns"]] == ["user", "assistant"]
    assert ses["turns"][0]["text"] == "primera pregunta"


def test_las_ramas_laterales_se_descartan():
    lineas = _jsonl(
        {"type": "user", "sessionId": "S", "origin": {"kind": "human"},
         "timestamp": "2026-08-27T10:00:00Z",
         "message": {"role": "user", "content": "principal"}},
        {"type": "assistant", "sessionId": "S", "isSidechain": True,
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "esto es de una subtarea"}]}},
        {"type": "assistant", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:02Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "esto es el hilo principal"}]}},
    )
    ses = cc.parse_lineas(lineas)
    assert ses["turns"][1]["text"] == "esto es el hilo principal"
    assert "subtarea" not in ses["turns"][1]["text"]


def test_metadatos_de_sesion():
    ses = cc.parse_lineas(_sesion_base())
    assert ses["provider"] == "claude-code"
    assert ses["session_id"] == "S1"
    assert ses["project"] == "/repo"
    assert ses["git_branch"] == "main"
    assert ses["title"] == "Arreglo del bug"
    assert ses["create_time"] and ses["update_time"]
    assert ses["create_time"] <= ses["update_time"]


def test_tool_result_como_lista_de_subbloques():
    """El resultado a veces viene como [{type:text,...}] en vez de str."""
    lineas = _jsonl(
        {"type": "user", "sessionId": "S", "origin": {"kind": "human"},
         "timestamp": "2026-08-27T10:00:00Z",
         "message": {"role": "user", "content": "corre esto"}},
        {"type": "assistant", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t9", "name": "Bash",
              "input": {"command": "ls"}}]}},
        {"type": "user", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:02Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t9",
              "content": [{"type": "text", "text": "foo.py\nbar.py"}]}]}},
    )
    ses = cc.parse_lineas(lineas)
    assert ses["turns"][1]["tools"][0]["result"] == "foo.py\nbar.py"


def test_detect():
    assert cc.detect('{"sessionId":"S","type":"user","message":{}}')
    assert not cc.detect('{"conversations":[]}')       # export de Grok
    assert not cc.detect("no es json")
    assert not cc.detect('{"type":"user"}')            # sin sessionId


def test_linea_corrupta_no_tumba_la_sesion():
    lineas = ['{"roto', json.dumps(
        {"type": "user", "sessionId": "S", "origin": {"kind": "human"},
         "timestamp": "2026-08-27T10:00:00Z",
         "message": {"role": "user", "content": "sigo aqui"}})]
    ses = cc.parse_lineas(lineas)
    assert ses is not None
    assert ses["turns"][0]["text"] == "sigo aqui"


def test_sesion_vacia_o_sin_contenido_da_none():
    assert cc.parse_lineas([]) is None
    assert cc.parse_lineas(['{"type":"queue-operation","sessionId":"S"}']) is None


def test_humo_contra_una_sesion_real():
    """Si hay una sesion real en disco, el parser no revienta y produce algo
    coherente. Se salta si no la hay (CI sin el vault de V0ra)."""
    base = Path.home() / ".claude" / "projects"
    reales = list(base.glob("*/*.jsonl")) if base.exists() else []
    if not reales:
        import pytest
        pytest.skip("sin sesiones locales de Claude Code en esta maquina")
    ses = cc.parse_fichero(max(reales, key=lambda p: p.stat().st_size))
    assert ses is not None
    assert ses["provider"] == "claude-code"
    assert ses["turns"], "una sesion real tiene turnos"
    # El primer turno con contenido es del usuario (una sesion empieza por un
    # prompt humano).
    assert ses["turns"][0]["role"] == "user"
    # Toda respuesta de asistente tiene las tres listas bien formadas.
    for t in ses["turns"]:
        if t["role"] == "assistant":
            assert isinstance(t["thinking"], list)
            assert isinstance(t["tools"], list)
            assert isinstance(t["text"], str)
