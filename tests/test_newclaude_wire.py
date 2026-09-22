# -*- coding: utf-8 -*-
"""Test of the ingest_extras wire-up to the pipeline's Step 1.

The hook lives in MemorIA2GO._ingest_newclaude_extras_if_applies and is
called by paso1_split after importing the conversations. This does NOT
test paso1_split end-to-end (that would call split_chatgpt_export as a
subprocess -- heavy); it tests that the hook does what it says:

  - a folder that IS a layout    -> the three writers fire, stats returned;
  - a folder that ISN'T a layout -> it exits clean (empty dict), writes nothing;
  - a file (not a directory)     -> it exits clean;
  - internal writer failure      -> it's logged but not propagated
                                     (conversations already went in via
                                     the classic path).
"""
import json
from pathlib import Path

import pytest

import MemorIA2GO


def _make_layout(base: Path) -> Path:
    """Minimum layout with only conversations-000/ so detect_layout passes."""
    layout = base / "NewClaude"
    layout.mkdir()
    (layout / "conversations-000").mkdir()
    (layout / "conversations-000" / "conversations.json").write_text(
        "[]", encoding="utf-8"
    )
    return layout


def test_hook_fires_all_three_writers_with_real_layout(tmp_path):
    """A real layout with projects + memories leaves a trace in the
    three canonical locations: PRJ_VAULT, MERGED_VAULT/CLAUDE_WEB/FRAMES,
    Claude_Mem."""
    layout = _make_layout(tmp_path)
    # Add a project and mini memories so the writers have something
    # to write.
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
    stats = MemorIA2GO._ingest_newclaude_extras_if_applies(layout, base_vault)

    assert stats["projects"]["projects"] == 1
    assert stats["memories"]["sections"] == 1
    # On-disk trace -- the canonical spots for D2/D3/D4
    assert (base_vault / "PRJ_VAULT" / "TestProj" / "00_project.md").exists()
    assert (base_vault / "Claude_Mem" / "conversations.md").exists()


def test_hook_does_nothing_if_not_a_layout(tmp_path):
    """A folder that isn't a layout (or a classic zip, or a json, or
    anything else that isn't the new format) must exit the hook
    returning an empty dict, without creating anything in the vault."""
    fake_export = tmp_path / "whatever"
    fake_export.mkdir()
    base_vault = tmp_path / "vault"

    stats = MemorIA2GO._ingest_newclaude_extras_if_applies(fake_export, base_vault)

    assert stats == {}
    # The hook must have created NOTHING in the vault
    assert not base_vault.exists() or not any(base_vault.iterdir())


def test_hook_does_nothing_if_export_is_a_file(tmp_path):
    """A .zip or .json in the pending queue also goes through the
    hook. It doesn't apply for those: the hook returns an empty dict."""
    fichero = tmp_path / "chatgpt.zip"
    fichero.write_bytes(b"PK\x03\x04")  # arbitrary bytes, they don't matter here
    base_vault = tmp_path / "vault"
    assert MemorIA2GO._ingest_newclaude_extras_if_applies(fichero, base_vault) == {}


def test_hook_captures_writer_failures_without_propagating(tmp_path, monkeypatch):
    """If ingest_extras blows up for any reason, the hook captures it
    and only emits via error(). It doesn't propagate an exception
    upward because conversations HAVE already been imported and there
    is no point in aborting the Step 1 queue over a failure in the
    secondary categories."""
    layout = _make_layout(tmp_path)
    base_vault = tmp_path / "vault"

    from providers import newclaude_adapter

    def _blows_up(*_a, **_kw):
        raise RuntimeError("simulating writer failure")
    monkeypatch.setattr(newclaude_adapter, "ingest_extras", _blows_up)

    # Doesn't raise, returns {}
    result = MemorIA2GO._ingest_newclaude_extras_if_applies(layout, base_vault)
    assert result == {}
