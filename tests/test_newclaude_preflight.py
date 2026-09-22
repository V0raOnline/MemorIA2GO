# -*- coding: utf-8 -*-
"""Tests of the new-Claude-export wiring to the pipeline (Phase B).

Pins three things preflight and load_conversations must guarantee so
the rest of the pipeline doesn't notice a new format exists:

  - the manifest is recognized (informationally, not as an importable
    export);
  - the conversations-NNN.zip fragment is recognized with its own
    label, but only under its canonical name -- renaming it makes it
    fall into the chatgpt_zip branch, which still works because
    _dispatch dispatches by structure, not by label;
  - the decompressed folder is recognized as a layout, appears in
    list_pending_exports, has a stable fingerprint, and
    load_conversations ingests it by delegating to
    newclaude_adapter.parse_conversations.
"""
import json
import zipfile
from pathlib import Path

import pytest

import preflight
import split_chatgpt_export as sce


# ─────────────────────────────────────────
# Minimal fixtures
# ─────────────────────────────────────────

def _manifest_payload():
    """Valid manifest with the 5 categories of the real export."""
    cats = ["light_metadata", "projects", "memories", "frames", "conversations"]
    return {
        "instructions": "Download each file using the export_url. Note: Each export URL can only be used once.",
        "created_at": "2026-09-20T20:17:00.878412+00:00",
        "total_files": len(cats),
        "data_files": [
            {"batch_index": i, "export_url": f"https://x/download/{i}",
             "category": c, "part": 0, "filename": f"{c}-000.zip"}
            for i, c in enumerate(cats)
        ],
        "version": "1.0",
    }


def _claude_conversations_payload():
    """A minimal conversation with the exact shape of Claude's export
    (used to fill a synthetic fragmented zip)."""
    return json.dumps([{
        "uuid": "abc-def",
        "name": "Hi",
        "summary": "",
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": "2026-09-01T10:00:00+00:00",
        "account": {"uuid": "usr-1"},
        "chat_messages": [
            {"uuid": "m1", "text": "hi",
             "content": [{"type": "text", "text": "hi"}],
             "sender": "human", "created_at": "2026-09-01T10:00:00+00:00",
             "updated_at": "2026-09-01T10:00:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": None},
        ],
    }], ensure_ascii=False).encode("utf-8")


def _make_layout(base: Path, conversations: bytes | None = None) -> Path:
    """Create a folder with the minimum layout marker:
    conversations-000/conversations.json. Returns the root folder."""
    layout = base / "NewClaude"
    layout.mkdir()
    conv_dir = layout / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_bytes(
        conversations if conversations is not None else b"[]"
    )
    return layout


# ─────────────────────────────────────────
# Manifest JSON
# ─────────────────────────────────────────

def test_manifest_recognized_as_non_importable(tmp_path):
    """The manifest itself carries no conversations. What matters: the
    user gets a message telling them to download the 5 zips, not an
    'invalid JSON' that confuses them."""
    m = tmp_path / "manifest-uuid-2026-09-20-20-17-00.json"
    m.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    result = preflight.validate_export_file(m)
    assert result["valido"] is False
    assert result["tipo"] == "newclaude_manifest"
    assert "Manifest" in result["mensaje"]
    assert "5 zips" in result["mensaje"] or "5" in result["mensaje"]


def test_manifest_with_unknown_category_raises_warning(tmp_path):
    m = tmp_path / "manifest-x.json"
    payload = _manifest_payload()
    payload["data_files"].append({
        "batch_index": 5, "export_url": "https://x/download/5",
        "category": "new_category", "part": 0, "filename": "new_category-000.zip"
    })
    m.write_text(json.dumps(payload), encoding="utf-8")
    result = preflight.validate_export_file(m)
    assert result["tipo"] == "newclaude_manifest"
    assert "new_category" in result["mensaje"]


# ─────────────────────────────────────────
# conversations-NNN.zip
# ─────────────────────────────────────────

def test_conversations_zip_recognized_by_canonical_name(tmp_path):
    z = tmp_path / "conversations-000.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations.json", _claude_conversations_payload())
    result = preflight.validate_export_file(z)
    assert result["valido"] is True
    assert result["tipo"] == "newclaude_conversations_zip"


def test_conversations_zip_renamed_falls_back_to_chatgpt_zip(tmp_path):
    """If someone renames the zip, the label changes but it is STILL
    importable: _dispatch will hand it to Claude's adapter by
    structure, not by label. This test explicitly defends that
    safety net -- we don't want to be strict about the name and lose
    the export."""
    z = tmp_path / "random_name.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations.json", _claude_conversations_payload())
    result = preflight.validate_export_file(z)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip"  # correct fallback


# ─────────────────────────────────────────
# Folder layout
# ─────────────────────────────────────────

def test_folder_layout_recognized_by_validate_export_directory(tmp_path):
    layout = _make_layout(tmp_path, _claude_conversations_payload())
    result = preflight.validate_export_directory(layout)
    assert result["valido"] is True
    assert result["tipo"] == "newclaude_layout"
    assert "conversations" in result["categorias_presentes"]


def test_incomplete_layout_still_valid_with_only_conversations(tmp_path):
    """The user may have only downloaded the conversations zip and
    not the others. A partial layout is accepted -- only what's
    there gets processed. The message reports it via
    'categorias_presentes'."""
    layout = _make_layout(tmp_path)
    result = preflight.validate_export_directory(layout)
    assert result["valido"] is True
    assert result["categorias_presentes"] == ["conversations"]


def test_layout_rejects_alien_folders(tmp_path):
    (tmp_path / "any_folder").mkdir()
    (tmp_path / "any_folder" / "no_conversations_here.txt").write_text("x")
    result = preflight.validate_export_directory(tmp_path / "any_folder")
    assert result["valido"] is False


# ─────────────────────────────────────────
# Enumeration in exports_dir (files + directories)
# ─────────────────────────────────────────

def test_list_pending_includes_layouts_as_folders(tmp_path):
    """The new export arrives as a FOLDER. list_pending_exports must
    enumerate them alongside the usual .zip/.json so MemorIA2GO.py
    (step 1) processes them like any other export."""
    exports = tmp_path / "exports"
    exports.mkdir()
    raw = tmp_path / "RAW"
    raw.mkdir()

    _make_layout(exports, _claude_conversations_payload())

    pending = preflight.list_pending_exports(exports, raw)
    assert len(pending) == 1
    assert pending[0].is_dir()
    assert pending[0].name == "NewClaude"


def test_list_pending_mixes_files_and_folders(tmp_path):
    """The same exports_dir may hold a classic zip and a new-format
    folder side by side. Both come out as pending."""
    exports = tmp_path / "exports"
    exports.mkdir()
    raw = tmp_path / "RAW"
    raw.mkdir()

    # A classic ChatGPT zip
    zpath = exports / "chatgpt.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("conversations.json", b'[{"title":"x","mapping":{}}]')
    # And a layout folder
    _make_layout(exports, _claude_conversations_payload())

    pending = preflight.list_pending_exports(exports, raw)
    names = sorted(p.name for p in pending)
    assert names == ["NewClaude", "chatgpt.zip"]


def test_folder_export_fingerprint_uses_conversations_json_size(tmp_path):
    """The fingerprint must change when content changes, not when
    irrelevant metadata (mtime) does. For directories, the size of
    conversations.json is the proxy used."""
    layout = _make_layout(tmp_path, b'[{"chat_messages":[]}]')
    fp1 = preflight.export_fingerprint(layout)
    assert "|dir|" in fp1
    # Change content -> change fingerprint
    (layout / "conversations-000" / "conversations.json").write_bytes(
        b'[{"chat_messages":[]}, {"chat_messages":[]}]'
    )
    fp2 = preflight.export_fingerprint(layout)
    assert fp1 != fp2


# ─────────────────────────────────────────
# split_chatgpt_export.load_conversations from a folder
# ─────────────────────────────────────────

def test_load_conversations_from_folder_yields_claude_convs(tmp_path):
    """End-to-end: load_conversations on a layout folder returns
    conversations with provider='claude' and conv_id -- the two
    pieces that make write_md emit the same source as the legacy
    export and let vault_merge group them by conv_id (dedup gratis)."""
    layout = _make_layout(tmp_path, _claude_conversations_payload())
    convs, zf = sce.load_conversations(str(layout))
    assert zf is None  # no zip attached to the layout
    assert len(convs) == 1
    assert convs[0]["provider"] == "claude"
    assert convs[0]["conv_id"] == "abc-def"


def test_load_conversations_folder_without_layout_yells(tmp_path):
    """A stray folder must fail LOUD, same as a corrupt zip: if the
    user points to the wrong place, better they hear it now than
    lose conversations silently."""
    (tmp_path / "any_thing").mkdir()
    with pytest.raises(RuntimeError):
        sce.load_conversations(str(tmp_path / "any_thing"))
