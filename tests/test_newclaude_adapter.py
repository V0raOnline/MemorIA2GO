# -*- coding: utf-8 -*-
"""Tests for the NEW-Claude-export adapter.

What matters, in order:
  - detect_manifest recognizes a manifest and rejects any other JSON;
  - detect_layout recognizes the decompressed folder by its minimum
    marker (conversations-NNN/conversations.json), survives NNN != 000,
    and rejects folders that are not an export;
  - parse_conversations delegates correctly to claude_adapter (same
    output contract: the new format is NOT a new model);
  - categories_from_manifest separates known from unknown (the format
    drift signal preflight will consume in Phase A/4).
"""
import json
from pathlib import Path

import pytest

from providers import newclaude_adapter as nc


# ─────────────────────────────────────────
# Fixtures: minimal synthetic manifest and variants
# ─────────────────────────────────────────

def _valid_manifest(categories=None):
    """Minimal manifest with the 5 categories of the real export. If
    the caller passes `categories`, those are used (to simulate drift)."""
    cats = categories if categories is not None else [
        "light_metadata", "projects", "memories", "frames", "conversations",
    ]
    return {
        "instructions": "Download each file using the export_url. Note: Each export URL can only be used once.",
        "created_at": "2026-09-20T20:17:00.878412+00:00",
        "total_files": len(cats),
        "data_files": [
            {"batch_index": i,
             "export_url": f"https://claude.ai/export/x/download/{i:08x}",
             "category": c,
             "part": 0,
             "filename": f"{c}-000.zip"}
            for i, c in enumerate(cats)
        ],
        "version": "1.0",
    }


# ─────────────────────────────────────────
# detect_manifest
# ─────────────────────────────────────────

def test_detect_manifest_recognizes_the_5_category_manifest():
    assert nc.detect_manifest(_valid_manifest()) is True


def test_detect_manifest_accepts_missing_known_categories():
    """If the user only exported a subset or Anthropic drops a
    category, as long as AT LEAST ONE known category is present, it's
    still the new manifest. The discipline is recognize, not require."""
    assert nc.detect_manifest(_valid_manifest(["conversations"])) is True
    assert nc.detect_manifest(_valid_manifest(["memories", "frames"])) is True


def test_detect_manifest_rejects_manifest_with_no_known_category():
    """If nothing in data_files falls into the known set, it's not
    this export -- it could be another kind of manifest (Anthropic
    has more than one; the pipeline mustn't claim things that aren't
    its own)."""
    m = _valid_manifest(["strange_thing", "another_thing"])
    assert nc.detect_manifest(m) is False


def test_detect_manifest_rejects_non_manifest_shapes():
    """Hard rejects: anything else that lands in preflight (a Claude
    conversations list, a Grok dict, a string, None) has to return
    False without exploding. That's what a detector does: separate,
    not consume."""
    assert nc.detect_manifest([{"chat_messages": []}]) is False       # legacy Claude
    assert nc.detect_manifest({"conversations": [{"responses": []}]}) is False  # Grok
    assert nc.detect_manifest({"data_files": "not_a_list"}) is False
    assert nc.detect_manifest({"data_files": []}) is False            # empty list
    assert nc.detect_manifest({}) is False
    assert nc.detect_manifest(None) is False
    assert nc.detect_manifest("string") is False


def test_detect_manifest_does_not_require_every_entry_to_have_all_keys():
    """`data_files[*]` must have at least category and filename; the
    rest (batch_index, export_url, part) are metadata that may be
    missing in an experimental manifest without invalidating
    recognition."""
    m = {"data_files": [{"category": "conversations", "filename": "conversations-000.zip"}]}
    assert nc.detect_manifest(m) is True


# ─────────────────────────────────────────
# detect_layout
# ─────────────────────────────────────────

def test_detect_layout_recognizes_folder_with_conversations_000(tmp_path):
    """Canonical scenario: decompressing the zip creates
    conversations-000/ with conversations.json inside."""
    (tmp_path / "conversations-000").mkdir()
    (tmp_path / "conversations-000" / "conversations.json").write_text("[]", encoding="utf-8")
    assert nc.detect_layout(tmp_path) is True


def test_detect_layout_accepts_NNN_other_than_000(tmp_path):
    """If someday the export ships in conversations-001,
    conversations-002... the folder is still recognizable. Detection
    is by prefix, not by exact suffix."""
    (tmp_path / "conversations-013").mkdir()
    (tmp_path / "conversations-013" / "conversations.json").write_text("[]", encoding="utf-8")
    assert nc.detect_layout(tmp_path) is True


def test_detect_layout_rejects_alien_folders(tmp_path):
    (tmp_path / "whatever").mkdir()
    (tmp_path / "conversations-000").mkdir()  # subdir present...
    # ...but without the conversations.json inside: doesn't count
    assert nc.detect_layout(tmp_path) is False


def test_detect_layout_rejects_non_directories(tmp_path):
    # a stray file is not a layout
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    assert nc.detect_layout(tmp_path / "manifest.json") is False
    # a non-existent path
    assert nc.detect_layout(tmp_path / "does_not_exist") is False


# ─────────────────────────────────────────
# parse_conversations
# ─────────────────────────────────────────

def test_parse_conversations_delegates_to_claude_adapter(tmp_path):
    """The new format IS the old one inside: the same conversations.json
    parsed through this adapter must yield exactly the same result as
    parsing it directly through claude_adapter. No semantic surprises."""
    from providers import claude_adapter as viejo

    # A minimal conversation with the exact shape of the real export.
    payload = [{
        "uuid": "aaaa-bbbb-cccc-dddd",
        "name": "Hello world",
        "summary": "",
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": "2026-09-01T10:05:00+00:00",
        "account": {"uuid": "usr-1"},
        "chat_messages": [
            {"uuid": "m1", "text": "hi", "content": [{"type": "text", "text": "hi"}],
             "sender": "human", "created_at": "2026-09-01T10:00:00+00:00",
             "updated_at": "2026-09-01T10:00:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": None},
            {"uuid": "m2", "text": "how's it going", "content": [{"type": "text", "text": "how's it going"}],
             "sender": "assistant", "created_at": "2026-09-01T10:01:00+00:00",
             "updated_at": "2026-09-01T10:01:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": "m1"},
        ],
    }]
    conv_dir = tmp_path / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    via_new = nc.parse_conversations(tmp_path)
    via_old = viejo.parse(payload)
    assert via_new == via_old
    assert len(via_new) == 1
    assert via_new[0]["conv_id"] == "aaaa-bbbb-cccc-dddd"
    assert via_new[0]["provider"] == "claude"


def test_parse_conversations_returns_empty_without_conversations_folder(tmp_path):
    """If the layout has no conversations-NNN/, there are no
    conversations to parse -- empty list, not exception. The other
    passes (memories, frames, projects) continue on their own path."""
    assert nc.parse_conversations(tmp_path) == []


# ─────────────────────────────────────────
# categories_from_manifest
# ─────────────────────────────────────────

def test_categories_separates_known_from_unknown():
    m = _valid_manifest(["conversations", "frames", "new_thing"])
    result = nc.categories_from_manifest(m)
    assert result["known"] == ["conversations", "frames"]
    assert result["unknown"] == ["new_thing"]


def test_categories_preserves_manifest_order():
    """The order matters because preflight warnings cite it; a set()
    would shuffle it and make it noisy in the UI."""
    m = _valid_manifest(["memories", "conversations", "frames"])
    assert nc.categories_from_manifest(m)["known"] == \
        ["memories", "conversations", "frames"]


# ─────────────────────────────────────────
# Test against the REAL export (if available in bck/NewClaude/)
# ─────────────────────────────────────────
# This is the corollary of the internal contract: the "diagnose before
# code, verify against real data before declaring done" discipline. If
# the decompressed export is around, this test exercises it -- if not,
# it skips silently in CI.

_BCK = Path(__file__).resolve().parent.parent / "bck" / "NewClaude"


@pytest.mark.skipif(not _BCK.is_dir(), reason="bck/NewClaude/ not available")
def test_real_export_is_recognized_as_layout():
    assert nc.detect_layout(_BCK) is True


@pytest.mark.skipif(not (_BCK / "conversations-000" / "conversations.json").is_file(),
                    reason="real conversations.json not available")
def test_real_export_parses_all_conversations_with_conv_id():
    convs = nc.parse_conversations(_BCK)
    assert len(convs) > 0
    # Every parsed conversation must carry conv_id (canonical
    # identity in the pipeline) and provider "claude" (not
    # "newclaude") so vault_merge merges them with the legacy export.
    for c in convs:
        assert c["conv_id"], f"conversation without conv_id: {c.get('title')!r}"
        assert c["provider"] == "claude"


def _real_manifests():
    """The real manifest may live inside bck/NewClaude/ or beside it
    (bck/), depending on where the user dropped it after download."""
    return list(_BCK.glob("manifest-*.json")) + list(_BCK.parent.glob("manifest-*.json"))


@pytest.mark.skipif(not _real_manifests(), reason="real manifest not available")
def test_real_manifest_is_recognized():
    m_path = _real_manifests()[0]
    with m_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert nc.detect_manifest(data) is True
    cats = nc.categories_from_manifest(data)
    # The real manifest carries the 5 expected categories.
    assert set(cats["known"]) == set(nc.KNOWN_CATEGORIES)
    assert cats["unknown"] == []
