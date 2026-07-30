# -*- coding: utf-8 -*-
"""Tests de regresion de los artefactos de Claude (backlog CONTEXT.md
seccion 3, paso 5/6): solo se conserva la version FINAL de cada artefacto
(create + N updates/rewrites resueltos a un solo estado), nunca las
revisiones intermedias -- un artefacto real se vio revisado 14 veces en
una sola conversacion.
"""
from pathlib import Path

import split_chatgpt_export as sce
from providers import claude_adapter as ca


def _msg(uuid, sender, content, parent=None, created_at="2026-01-01T00:00:00Z"):
    return {
        "uuid": uuid, "sender": sender, "parent_message_uuid": parent,
        "created_at": created_at, "content": content,
    }


def _artifact_block(aid, command, **extra):
    inp = {"id": aid, "command": command, **extra}
    return {"type": "tool_use", "name": "artifacts", "input": inp}


def test_resolve_artifacts_create_mas_updates_da_version_final():
    msgs = [
        _msg("h1", "human", [{"type": "text", "text": "hazme un contador"}]),
        _msg("a1", "assistant", [_artifact_block(
            "contador", "create", type="application/vnd.ant.code", title="Contador",
            language="python", content="x = 0\n",
        )], parent="h1"),
        _msg("h2", "human", [{"type": "text", "text": "que sume de 2 en 2"}], parent="a1"),
        _msg("a2", "assistant", [_artifact_block(
            "contador", "update", old_str="x = 0\n", new_str="x = 0\nx += 2\n",
        )], parent="h2"),
        _msg("h3", "human", [{"type": "text", "text": "anade un print"}], parent="a2"),
        _msg("a3", "assistant", [_artifact_block(
            "contador", "update", old_str="x += 2\n", new_str="x += 2\nprint(x)\n",
        )], parent="h3"),
    ]
    threaded = ca._thread(msgs)
    artifacts = ca._resolve_artifacts(threaded)
    assert artifacts["contador"]["content"] == "x = 0\nx += 2\nprint(x)\n"
    assert artifacts["contador"]["type"] == "application/vnd.ant.code"
    assert artifacts["contador"]["language"] == "python"


def test_resolve_artifacts_rewrite_reemplaza_contenido_entero():
    msgs = [
        _msg("h1", "human", [{"type": "text", "text": "doc"}]),
        _msg("a1", "assistant", [_artifact_block(
            "doc1", "create", type="text/markdown", title="Doc", content="# Borrador\n",
        )], parent="h1"),
        _msg("h2", "human", [{"type": "text", "text": "reescribelo entero"}], parent="a1"),
        _msg("a2", "assistant", [_artifact_block(
            "doc1", "rewrite", content="# Version final\n\nContenido nuevo.\n",
        )], parent="h2"),
    ]
    threaded = ca._thread(msgs)
    artifacts = ca._resolve_artifacts(threaded)
    assert artifacts["doc1"]["content"] == "# Version final\n\nContenido nuevo.\n"
    assert artifacts["doc1"]["title"] == "Doc"  # rewrite no trae title, se hereda de create


def test_resolve_artifacts_update_con_old_str_no_encontrado_se_ignora():
    msgs = [
        _msg("h1", "human", [{"type": "text", "text": "x"}]),
        _msg("a1", "assistant", [_artifact_block(
            "a", "create", type="text/plain", title="A", content="hola\n",
        )], parent="h1"),
        _msg("h2", "human", [{"type": "text", "text": "y"}], parent="a1"),
        _msg("a2", "assistant", [_artifact_block(
            "a", "update", old_str="texto que no existe", new_str="nunca aplica",
        )], parent="h2"),
    ]
    threaded = ca._thread(msgs)
    artifacts = ca._resolve_artifacts(threaded)
    assert artifacts["a"]["content"] == "hola\n"  # sin cambios, no revento


def test_parse_emite_un_solo_marcador_por_artefacto_pese_a_multiples_revisiones():
    data = [{
        "uuid": "conv-1", "name": "Conversacion con artefacto revisado",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:10:00Z",
        "chat_messages": [
            _msg("h1", "human", [{"type": "text", "text": "hazme un contador"}]),
            _msg("a1", "assistant", [_artifact_block(
                "contador", "create", type="application/vnd.ant.code", title="Contador",
                language="python", content="x = 0\n",
            )], parent="h1"),
            _msg("h2", "human", [{"type": "text", "text": "mejoralo"}], parent="a1"),
            _msg("a2", "assistant", [_artifact_block(
                "contador", "update", old_str="x = 0\n", new_str="x = 1\n",
            ), {"type": "text", "text": "Listo, mejorado."}], parent="h2"),
        ],
    }]
    conversations = ca.parse(data)
    assert len(conversations) == 1
    conv = conversations[0]
    assert conv["artifacts"]["contador"]["content"] == "x = 1\n"
    marcadores = sum(m["content"].count("\x00CLAUDEARTIFACT:contador\x00") for m in conv["messages"])
    assert marcadores == 1, "solo debe aparecer un marcador, no uno por revision"


def test_render_claude_artifact_tokens_escribe_version_final_en_subdir_por_tipo(tmp_path):
    artifacts = {
        "contador": {
            "type": "application/vnd.ant.code", "title": "Mi Contador",
            "language": "python", "content": "x = 1\nprint(x)\n",
        },
    }
    writer = sce.AssetWriter(str(tmp_path / "ARTIFACTS"))
    content = "antes \x00CLAUDEARTIFACT:contador\x00 despues"
    rendered = sce.render_claude_artifact_tokens(
        content, artifacts, writer, "CLAUDE/ARTIFACTS", conv_id="conv-1",
    )
    assert "CLAUDE/ARTIFACTS/code/" in rendered
    assert rendered.endswith(".py)") or ".py](" in rendered
    escritos = list((tmp_path / "ARTIFACTS" / "code").glob("*.py"))
    assert len(escritos) == 1
    assert escritos[0].read_text(encoding="utf-8") == "x = 1\nprint(x)\n"


def test_render_claude_artifact_tokens_sin_banco_degrada_a_texto():
    artifacts = {"a": {"type": "text/markdown", "title": "Notas", "content": "hola"}}
    rendered = sce.render_claude_artifact_tokens(
        "\x00CLAUDEARTIFACT:a\x00", artifacts, None, None,
    )
    assert "Notas" in rendered
    assert "no artifact bank configured" in rendered


def test_render_claude_artifact_tokens_mismo_id_distinta_conversacion_no_colisiona(tmp_path):
    """El id de artefacto solo es unico dentro de su conversacion -- dos
    chats distintos pueden crear ambos un artefacto 'app'."""
    artifacts_conv1 = {"app": {"type": "text/plain", "title": "App", "content": "version conv 1"}}
    artifacts_conv2 = {"app": {"type": "text/plain", "title": "App", "content": "version conv 2"}}
    writer = sce.AssetWriter(str(tmp_path / "ARTIFACTS"))
    sce.render_claude_artifact_tokens(
        "\x00CLAUDEARTIFACT:app\x00", artifacts_conv1, writer, "CLAUDE/ARTIFACTS", conv_id="conv-1",
    )
    sce.render_claude_artifact_tokens(
        "\x00CLAUDEARTIFACT:app\x00", artifacts_conv2, writer, "CLAUDE/ARTIFACTS", conv_id="conv-2",
    )
    escritos = list((tmp_path / "ARTIFACTS" / "otros").glob("*.txt"))
    assert len(escritos) == 2
    contenidos = {p.read_text(encoding="utf-8") for p in escritos}
    assert contenidos == {"version conv 1", "version conv 2"}
