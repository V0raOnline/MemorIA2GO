# -*- coding: utf-8 -*-
"""Tests de regresion de preflight.detect_new_keys (backlog CONTEXT.md #2,
detect_strict). Cada adaptador declara las claves de conversacion que conoce
(KNOWN_KEYS); este chequeo muestrea el export y avisa (sin bloquear) si
aparecen claves nunca vistas -- la clase de bug que ya paso una vez con
conversation_template_id (Nido_Delta, 2026-07-20).
"""
import json
import zipfile
from pathlib import Path

import preflight

FIXTURES = Path(__file__).parent / "fixtures"


def test_chatgpt_clasico_sin_claves_nuevas():
    result = preflight.detect_new_keys(FIXTURES / "chatgpt_classic.json")
    assert result["muestreado"] is True
    assert result["provider"] == "chatgpt"
    assert result["claves_nuevas"] == []
    assert result["total_items"] == 3


def test_chatgpt_fragmentado_detecta_campos_nuevos_plausibles(tmp_path):
    """El propio fixture trae async_status/voice a proposito -- este test
    prueba que el mecanismo los detecta de verdad, no solo que existan en
    el JSON."""
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    zpath = tmp_path / "chatgpt_frag.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(frag_dir.glob("conversations-*.json")):
            zf.writestr(f.name, f.read_bytes())

    result = preflight.detect_new_keys(zpath)
    assert result["muestreado"] is True
    assert result["provider"] == "chatgpt"
    assert "async_status" in result["claves_nuevas"]
    assert "voice" in result["claves_nuevas"]
    assert result["total_items"] == 2


def test_claude_export_sin_claves_nuevas():
    result = preflight.detect_new_keys(FIXTURES / "claude_export.zip")
    assert result["muestreado"] is True
    assert result["provider"] == "claude"
    assert result["claves_nuevas"] == []
    assert result["total_items"] == 2


def test_grok_export_sin_claves_nuevas():
    result = preflight.detect_new_keys(FIXTURES / "grok_export.zip")
    assert result["muestreado"] is True
    assert result["provider"] == "grok"
    assert result["claves_nuevas"] == []
    assert result["total_items"] == 2


def test_claude_con_clave_inyectada_se_detecta(tmp_path):
    """Caso sintetico minimo, aislado de los fixtures grandes: prueba el
    mecanismo de deteccion en si, no la forma real de ningun export."""
    conv = [{
        "uuid": "z1", "name": "Conversacion de prueba",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "chat_messages": [],
        "memory_snapshot_id": "algo-que-claude-no-tenia-antes",
    }]
    zpath = tmp_path / "claude_con_deriva.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conv))
        zf.writestr("users.json", "[]")

    result = preflight.detect_new_keys(zpath)
    assert result["muestreado"] is True
    assert result["provider"] == "claude"
    assert result["claves_nuevas"] == ["memory_snapshot_id"]


def test_html_no_muestreable(tmp_path):
    hpath = tmp_path / "export.html"
    hpath.write_text("<html><body>conversacion antigua sin json</body></html>", encoding="utf-8")
    result = preflight.detect_new_keys(hpath)
    assert result["muestreado"] is False


def test_zip_corrupto_no_revienta(tmp_path):
    bad = tmp_path / "corrupto.zip"
    bad.write_bytes(b"no soy un zip" * 5)
    result = preflight.detect_new_keys(bad)
    assert result["muestreado"] is False
    assert "motivo" in result


def test_list_export_candidates_deep_false_no_muestrea(tmp_path, monkeypatch):
    """Guardarraíl de rendimiento: sin deep=True, list_export_candidates NO
    debe llamar a detect_new_keys (que parsea el JSON completo) -- ese es
    justo el poll automatico del badge de la UI en cada cambio de pestaña."""
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    zpath = tmp_path / "chatgpt_frag.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(frag_dir.glob("conversations-*.json")):
            zf.writestr(f.name, f.read_bytes())

    def _boom(*a, **k):
        raise AssertionError("detect_new_keys no deberia llamarse con deep=False")

    monkeypatch.setattr(preflight, "detect_new_keys", _boom)
    candidatos = preflight.list_export_candidates(tmp_path, deep=False)
    assert len(candidatos) == 1
    assert candidatos[0]["valido"] is True
    assert candidatos[0]["aviso"] is False
    assert candidatos[0]["tipo"] == "chatgpt_zip_fragmentado"
    assert "AVISO" not in candidatos[0]["mensaje"]


def test_list_export_candidates_deep_true_anexa_aviso(tmp_path):
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    zpath = tmp_path / "chatgpt_frag.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(frag_dir.glob("conversations-*.json")):
            zf.writestr(f.name, f.read_bytes())

    candidatos = preflight.list_export_candidates(tmp_path, deep=True)
    assert len(candidatos) == 1
    assert candidatos[0]["valido"] is True
    assert candidatos[0]["aviso"] is True
    assert "AVISO" in candidatos[0]["mensaje"]
    assert "async_status" in candidatos[0]["mensaje"]
