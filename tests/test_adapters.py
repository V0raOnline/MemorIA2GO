# -*- coding: utf-8 -*-
"""Tests de regresion de los adaptadores multi-proveedor (backlog CONTEXT.md #1).

Cada fixture blinda un bug real cazado en el proyecto: el campo
conversation_template_id que se perdia en el "embudo parser->resolver"
(Nido_Delta, 2026-07-20), las ramas de regeneracion descartadas que no deben
colarse en el hilo final, y el despacho por estructura interna (nunca por
nombre de archivo) entre ChatGPT/Claude/Grok.
"""
import json
from pathlib import Path

import pytest

import split_chatgpt_export as sce

FIXTURES = Path(__file__).parent / "fixtures"


def _assert_contract(conv):
    """El contrato de salida que el resto del pipeline da por hecho."""
    assert conv["title"]
    assert conv["conv_id"]
    assert conv["provider"]
    assert conv["messages"], "la conversacion no debe quedar vacia"
    for m in conv["messages"]:
        assert m["role"]
        assert isinstance(m["content"], str) and m["content"].strip()


@pytest.fixture(scope="module")
def chatgpt_classic_conversations():
    data = json.loads((FIXTURES / "chatgpt_classic.json").read_text(encoding="utf-8"))
    return sce.parse_json_conversations(data)


@pytest.fixture(scope="module")
def chatgpt_fragmentado_conversations():
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    combinado = []
    for shard in sorted(frag_dir.glob("conversations-*.json")):
        combinado.extend(json.loads(shard.read_text(encoding="utf-8")))
    return sce.parse_json_conversations(combinado)


@pytest.fixture(scope="module")
def claude_conversations():
    convs, zf = sce.load_conversations(str(FIXTURES / "claude_export.zip"))
    if zf:
        zf.close()
    return convs


@pytest.fixture(scope="module")
def grok_conversations():
    convs, zf = sce.load_conversations(str(FIXTURES / "grok_export.zip"))
    if zf:
        zf.close()
    return convs


class TestChatGPTClasico:
    def test_contrato_basico(self, chatgpt_classic_conversations):
        assert len(chatgpt_classic_conversations) == 3
        for conv in chatgpt_classic_conversations:
            _assert_contract(conv)
            assert conv["provider"] == "chatgpt"

    def test_gizmo_id_clasico_viaja_y_modelo_se_detecta(self, chatgpt_classic_conversations):
        conv_a = next(c for c in chatgpt_classic_conversations if c["conv_id"] == "conv-classic-a-0001")
        assert conv_a["gizmo_id"] == "g-1234567890abcdef1234567890abcdef"
        assert conv_a["model"] == "gpt-4o"

    def test_conversacion_sin_proyecto(self, chatgpt_classic_conversations):
        conv_b = next(c for c in chatgpt_classic_conversations if c["conv_id"] == "conv-classic-b-0002")
        assert conv_b["gizmo_id"] is None
        assert conv_b["model"] is None
        assert len(conv_b["messages"]) == 2

    def test_mapping_con_ramas_descarta_regeneracion(self, chatgpt_classic_conversations):
        conv_c = next(c for c in chatgpt_classic_conversations if c["conv_id"] == "conv-classic-c-0003")
        assert conv_c["model"] == "gpt-4o-mini"
        contenido = " ".join(m["content"] for m in conv_c["messages"])
        assert "RESPUESTA DESCARTADA" not in contenido
        assert len(conv_c["messages"]) == 4


class TestChatGPTFragmentado:
    def test_contrato_basico(self, chatgpt_fragmentado_conversations):
        assert len(chatgpt_fragmentado_conversations) == 2
        for conv in chatgpt_fragmentado_conversations:
            _assert_contract(conv)
            assert conv["provider"] == "chatgpt"

    def test_conversation_template_id_y_memory_scope_viajan(self, chatgpt_fragmentado_conversations):
        """Blinda el bug del embudo parser->resolver (Nido_Delta 2026-07-20):
        estos campos deben aparecer en el dict que produce el parser, no solo
        ser "sabidos" por el bucle principal."""
        con_proyecto = next(c for c in chatgpt_fragmentado_conversations if c["conv_id"] == "conv-frag-000-0001")
        assert con_proyecto["conversation_template_id"] == "g-p-aabbccddeeff00112233445566778899"
        assert con_proyecto["memory_scope"] == "project_v2"
        assert con_proyecto["gizmo_id"] is None
        assert con_proyecto["model"] == "gpt-5"

    def test_conversacion_sin_proyecto(self, chatgpt_fragmentado_conversations):
        sin_proyecto = next(c for c in chatgpt_fragmentado_conversations if c["conv_id"] == "conv-frag-001-0002")
        assert sin_proyecto["conversation_template_id"] is None
        assert sin_proyecto["memory_scope"] is None


class TestClaudeExport:
    def test_contrato_basico_y_despacho_por_estructura(self, claude_conversations):
        assert len(claude_conversations) == 2
        for conv in claude_conversations:
            _assert_contract(conv)
            assert conv["provider"] == "claude"
            assert conv["gizmo_id"] is None

    def test_rama_descartada_no_aparece(self, claude_conversations):
        conv2 = next(c for c in claude_conversations if c["conv_id"] == "c2222222-2222-2222-2222-222222222222")
        contenido = " ".join(m["content"] for m in conv2["messages"])
        assert "RESPUESTA DESCARTADA" not in contenido
        assert len(conv2["messages"]) == 4

    def test_adjuntos_extraidos_y_referenciados_sin_duplicar(self, claude_conversations):
        conv1 = next(c for c in claude_conversations if "arrendamiento" in c["title"].lower())
        contenido = " ".join(m["content"] for m in conv1["messages"])
        assert "Archivo adjunto: **contrato.pdf**" in contenido
        assert "Clausula 7" in contenido
        assert "Archivo referenciado (no incluido en el export de Claude): **anexo.pdf**" in contenido
        assert "thinking" not in contenido.lower()


class TestGrokExport:
    def test_contrato_basico_y_despacho_por_estructura(self, grok_conversations):
        assert len(grok_conversations) == 2
        for conv in grok_conversations:
            _assert_contract(conv)
            assert conv["provider"] == "grok"
            assert conv["gizmo_id"] is None

    def test_senders_mixtos_se_normalizan(self, grok_conversations):
        conv1 = next(c for c in grok_conversations if c["conv_id"] == "gconv-0001")
        assert [m["role"] for m in conv1["messages"]] == ["user", "assistant"]

    def test_fecha_mongo_a_nivel_mensaje_no_rompe_el_hilo(self, grok_conversations):
        conv1 = next(c for c in grok_conversations if c["conv_id"] == "gconv-0001")
        assert conv1["create_time"] is not None
        assert len(conv1["messages"]) == 2

    def test_file_attachments_se_referencian(self, grok_conversations):
        conv1 = next(c for c in grok_conversations if c["conv_id"] == "gconv-0001")
        contenido = " ".join(m["content"] for m in conv1["messages"])
        assert "asset-uuid-111" in contenido

    def test_leaf_response_id_poblado_se_respeta(self, grok_conversations):
        conv2 = next(c for c in grok_conversations if c["conv_id"] == "gconv-0002")
        assert conv2["model"] == "grok-3"
        assert len(conv2["messages"]) == 2
