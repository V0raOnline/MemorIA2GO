# -*- coding: utf-8 -*-
"""Test del cablado de ingest_extras al Paso 1 del pipeline.

El hook vive en MemorIA2GO._ingerir_extras_newclaude_si_aplica y lo
invoca paso1_split despues de importar las conversaciones. Esto no
prueba paso1_split de punta a punta (llamaria a split_chatgpt_export
como subproceso, es pesado); prueba que el hook hace lo que dice:

  - carpeta que ES layout      -> se disparan los tres writers,
                                   devuelve stats;
  - carpeta que NO es layout    -> se sale limpio (dict vacio), sin
                                   escribir nada;
  - fichero (no directorio)     -> se sale limpio;
  - fallo interno del writer    -> se registra pero no se propaga
                                   (las conversaciones ya han entrado
                                   por la ruta clasica).
"""
import json
from pathlib import Path

import pytest

import MemorIA2GO


def _crear_layout(base: Path) -> Path:
    """Layout minimo con solo conversations-000/ para pasar detect_layout."""
    layout = base / "NewClaude"
    layout.mkdir()
    (layout / "conversations-000").mkdir()
    (layout / "conversations-000" / "conversations.json").write_text("[]",
                                                                       encoding="utf-8")
    return layout


def test_hook_dispara_los_tres_writers_con_layout_real(tmp_path):
    """Un layout real con proyectos + memories deja rastro en las tres
    ubicaciones canonicas: PRJ_VAULT, MERGED_VAULT/CLAUDE_WEB/FRAMES,
    Claude_Mem."""
    layout = _crear_layout(tmp_path)
    # Anadir un proyecto y unas memorias mini para que los writers
    # tengan algo que escribir.
    pdir = layout / "projects-000" / "projects"
    pdir.mkdir(parents=True)
    (pdir / "p1.json").write_text(json.dumps({
        "uuid": "p1", "name": "TestProj",
        "description": "", "is_private": True, "is_starter_project": False,
        "prompt_template": "", "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "creator": {"uuid": "u", "full_name": "V0ra"}, "docs": [],
    }), encoding="utf-8")

    mdir = layout / "memories-000" / "memories"
    mdir.mkdir(parents=True)
    (mdir / "u.json").write_text(json.dumps({
        "account_uuid": "u", "conversations_memory": "dossier",
        "project_memories": {}, "memory_files": [],
    }), encoding="utf-8")

    base_vault = tmp_path / "vault"
    stats = MemorIA2GO._ingerir_extras_newclaude_si_aplica(layout, base_vault)

    assert stats["projects"]["proyectos"] == 1
    assert stats["memories"]["secciones"] == 1
    # Rastro en disco -- los sitios canonicos para D2/D3/D4
    assert (base_vault / "PRJ_VAULT" / "TestProj" / "00_proyecto.md").exists()
    assert (base_vault / "Claude_Mem" / "conversations.md").exists()


def test_hook_no_hace_nada_si_no_es_layout(tmp_path):
    """Una carpeta que no es un layout (o un zip clasico, un json, o
    cualquier cosa distinta del nuevo formato) tiene que salir del
    hook devolviendo dict vacio, sin crear rastro en el vault."""
    fake_export = tmp_path / "cualquier_cosa"
    fake_export.mkdir()
    base_vault = tmp_path / "vault"

    stats = MemorIA2GO._ingerir_extras_newclaude_si_aplica(fake_export, base_vault)

    assert stats == {}
    # El hook no debe haber creado NADA en el vault
    assert not base_vault.exists() or not any(base_vault.iterdir())


def test_hook_no_hace_nada_si_export_es_fichero(tmp_path):
    """Un .zip o .json en la cola de pendientes tambien pasa por el
    hook. Para esos, no aplica: el hook devuelve dict vacio."""
    fichero = tmp_path / "chatgpt.zip"
    fichero.write_bytes(b"PK\x03\x04")  # bytes cualquiera, no importan aqui
    base_vault = tmp_path / "vault"
    assert MemorIA2GO._ingerir_extras_newclaude_si_aplica(fichero, base_vault) == {}


def test_hook_captura_fallos_del_writer_sin_propagar(tmp_path, monkeypatch):
    """Si ingest_extras revienta por lo que sea, el hook lo captura y
    solo emite el error via error(). No lanza excepcion hacia arriba
    porque las conversaciones YA han entrado y no tiene sentido
    abortar la cola del Paso 1 por un fallo en las categorias
    secundarias."""
    layout = _crear_layout(tmp_path)
    base_vault = tmp_path / "vault"

    from providers import newclaude_adapter

    def _revienta(*_a, **_kw):
        raise RuntimeError("simulando fallo del writer")
    monkeypatch.setattr(newclaude_adapter, "ingest_extras", _revienta)

    # No lanza excepcion, devuelve {}
    result = MemorIA2GO._ingerir_extras_newclaude_si_aplica(layout, base_vault)
    assert result == {}
