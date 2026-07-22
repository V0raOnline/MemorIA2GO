# -*- coding: utf-8 -*-
"""Tests de regresion de preflight.validate_export_file (backlog CONTEXT.md #1).

Cubre los 4 tipos de export soportados (por estructura, no por nombre de
archivo) y los dos casos de fallo explicito que el modulo esta pensado para
gritar: zip corrupto y estructura desconocida.
"""
import zipfile
from pathlib import Path

import preflight

FIXTURES = Path(__file__).parent / "fixtures"


def _make_zip(tmp_path, name, entries: dict) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in entries.items():
            zf.writestr(arcname, content)
    return path


def test_chatgpt_zip_clasico(tmp_path):
    data = (FIXTURES / "chatgpt_classic.json").read_bytes()
    zpath = _make_zip(tmp_path, "chatgpt_classic.zip", {"conversations.json": data})
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip"


def test_chatgpt_zip_fragmentado(tmp_path):
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    entries = {f.name: f.read_bytes() for f in sorted(frag_dir.glob("conversations-*.json"))}
    zpath = _make_zip(tmp_path, "chatgpt_frag.zip", entries)
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip_fragmentado"


def test_claude_zip():
    result = preflight.validate_export_file(FIXTURES / "claude_export.zip")
    assert result["valido"] is True
    assert result["tipo"] == "claude_zip"


def test_grok_zip():
    result = preflight.validate_export_file(FIXTURES / "grok_export.zip")
    assert result["valido"] is True
    assert result["tipo"] == "grok_zip"


def test_zip_corrupto(tmp_path):
    bad = tmp_path / "corrupto.zip"
    bad.write_bytes(b"esto no es un zip valido, son bytes cualquiera" * 5)
    result = preflight.validate_export_file(bad)
    assert result["valido"] is False
    assert "CORRUPTO" in result["mensaje"]


def test_zip_estructura_desconocida(tmp_path):
    zpath = _make_zip(tmp_path, "raro.zip", {"readme.txt": "esto no es un export de nada reconocible"})
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is False
    assert "ESTRUCTURA DESCONOCIDA" in result["mensaje"]
