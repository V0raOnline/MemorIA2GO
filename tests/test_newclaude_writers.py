# -*- coding: utf-8 -*-
"""Tests for the new-Claude-export writers (Phases C-E, D2-D4).

Locks the three contracts that resolve the three plan decisions:
  - D3: projects go to PRJ_VAULT/<name>/ with 00_project.md + _docs/;
  - D4: memory_files go to Claude_Mem/ preserving the literal path;
  - D2: conversations_memory and project_memories also go to Claude_Mem/,
    in their own files.

All writers are idempotent by content and tolerate partial layers (a
layout without memories, a project without docs, etc). Verified against
the real export at the end.
"""
import json
from pathlib import Path

import pytest

from providers import newclaude_adapter as nc


# ─────────────────────────────────────────
# Reusable fixtures
# ─────────────────────────────────────────

def _make_layout(tmp_path: Path, *, with_projects=None, with_memories=None,
                 with_frames=None, with_conversations=None) -> Path:
    """Build a full NewClaude layout under tmp_path with the categories
    provided. Returns the root folder."""
    layout = tmp_path / "NewClaude"
    layout.mkdir()

    # conversations always present so detect_layout passes (even if the
    # tests here don't use them).
    conv_dir = layout / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_text(
        json.dumps(with_conversations if with_conversations is not None else []),
        encoding="utf-8",
    )

    if with_projects is not None:
        pdir = layout / "projects-000" / "projects"
        pdir.mkdir(parents=True)
        for pr in with_projects:
            (pdir / f"{pr['uuid']}.json").write_text(
                json.dumps(pr, ensure_ascii=False), encoding="utf-8"
            )

    if with_memories is not None:
        mdir = layout / "memories-000" / "memories"
        mdir.mkdir(parents=True)
        (mdir / f"{with_memories.get('account_uuid', 'x')}.json").write_text(
            json.dumps(with_memories, ensure_ascii=False), encoding="utf-8"
        )

    if with_frames is not None:
        fdir = layout / "frames-000" / "artifacts"
        fdir.mkdir(parents=True)
        for fr in with_frames:
            adir = fdir / fr["id"]
            adir.mkdir()
            (adir / "artifact.json").write_text(
                json.dumps({k: v for k, v in fr.items() if k != "_versions_html" and k != "_comments"},
                           ensure_ascii=False),
                encoding="utf-8"
            )
            if fr.get("_versions_html"):
                vdir = adir / "versions"
                vdir.mkdir()
                for vid, html in fr["_versions_html"].items():
                    (vdir / f"{vid}.html").write_text(html, encoding="utf-8")
            if fr.get("_comments") is not None:
                (adir / "artifact_comments.json").write_text(
                    json.dumps(fr["_comments"], ensure_ascii=False), encoding="utf-8"
                )

    return layout


def _minimal_project(**overrides):
    base = {
        "uuid": "019a-proj-uuid",
        "name": "A project",
        "description": "Project description",
        "is_private": True,
        "is_starter_project": False,
        "prompt_template": "",
        "created_at": "2026-01-15T10:00:00+00:00",
        "updated_at": "2026-06-20T15:00:00+00:00",
        "creator": {"uuid": "usr-1", "full_name": "V0ra"},
        "docs": [],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────
# write_projects
# ─────────────────────────────────────────

def test_write_projects_creates_folder_with_index_note_and_docs(tmp_path):
    """A project with 2 docs -> folder with 00_project.md + _docs/*."""
    layout = _make_layout(tmp_path, with_projects=[
        _minimal_project(name="MemorIA2GO", docs=[
            {"uuid": "d1", "filename": "guide.md", "content": "# Guide\ntext",
             "created_at": "2026-02-01T00:00:00+00:00"},
            {"uuid": "d2", "filename": "notes.md", "content": "flat notes",
             "created_at": "2026-02-02T00:00:00+00:00"},
        ]),
    ])
    prj = tmp_path / "PRJ_VAULT"
    stats = nc.write_projects(layout, prj)
    assert stats["projects"] == 1
    assert stats["docs"] == 2
    folder = prj / "MemorIA2GO"
    note = (folder / "00_project.md").read_text(encoding="utf-8")
    assert 'name: "MemorIA2GO"' in note
    assert 'uuid: "019a-proj-uuid"' in note
    assert "Project description" in note
    # The docs are literal files under _docs/
    assert (folder / "_docs" / "guide.md").read_text(encoding="utf-8") == "# Guide\ntext"
    assert (folder / "_docs" / "notes.md").read_text(encoding="utf-8") == "flat notes"


def test_write_projects_includes_prompt_template_as_code_block(tmp_path):
    """The prompt_template is the project's system prompt. It goes into
    a code block so it reads verbatim, without interpreting any markdown
    it might contain."""
    layout = _make_layout(tmp_path, with_projects=[
        _minimal_project(name="X", prompt_template="You are an assistant that...")
    ])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    note = (prj / "X" / "00_project.md").read_text(encoding="utf-8")
    assert "Project instructions" in note
    assert "You are an assistant that..." in note
    assert "```" in note


def test_write_projects_is_idempotent(tmp_path):
    """Reingest with identical content: zero new writes."""
    layout = _make_layout(tmp_path, with_projects=[_minimal_project()])
    prj = tmp_path / "PRJ_VAULT"
    s1 = nc.write_projects(layout, prj)
    s2 = nc.write_projects(layout, prj)
    assert s1["written"] > 0
    assert s2["written"] == 0
    assert s2["skipped"] == s1["written"]


def test_write_projects_sanitizes_windows_forbidden_names(tmp_path):
    """Windows rejects \\ / : * ? " < > | in names. They're replaced by
    '_' but accents, case and spaces are preserved."""
    layout = _make_layout(tmp_path, with_projects=[
        _minimal_project(uuid="pu1", name='One/weird"project?', docs=[]),
        _minimal_project(uuid="pu2", name="Tiro Parabólico", docs=[]),
    ])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    # The first one has forbidden chars substituted
    assert (prj / "One_weird_project_" / "00_project.md").exists()
    # The second one keeps accent and case
    assert (prj / "Tiro Parabólico" / "00_project.md").exists()


def test_write_projects_links_to_claude_mem_by_uuid(tmp_path):
    """The index note must link to Claude_Mem/projects/<uuid>/ so the
    user sees Claude's memory about THAT project without having to
    hunt for it."""
    layout = _make_layout(tmp_path, with_projects=[_minimal_project(uuid="019a")])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    note = (prj / "A project" / "00_project.md").read_text(encoding="utf-8")
    assert "Claude_Mem/projects/019a/" in note


# ─────────────────────────────────────────
# write_frames
# ─────────────────────────────────────────

def test_write_frames_creates_note_and_copies_versions(tmp_path):
    layout = _make_layout(tmp_path, with_frames=[{
        "id": "art-1", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-b",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [
            {"id": "v-a", "title": "First", "description": "",
             "created_at": "2026-07-01T00:00:00+00:00"},
            {"id": "v-b", "title": "Second", "description": "accent improvement",
             "created_at": "2026-08-01T10:00:00+00:00"},
        ],
        "_versions_html": {"v-a": "<html>1</html>", "v-b": "<html>2 better</html>"},
    }])
    banco = tmp_path / "FRAMES"
    stats = nc.write_frames(layout, banco)
    assert stats["frames"] == 1
    assert stats["versions"] == 2
    note = (banco / "art-1" / "00_frame.md").read_text(encoding="utf-8")
    assert 'id: "art-1"' in note
    assert "active" in note  # the active-version marker appears
    assert "Second" in note
    # Versions are copied as-is, unmodified
    assert (banco / "art-1" / "versions" / "v-a.html").read_text(encoding="utf-8") == "<html>1</html>"
    assert (banco / "art-1" / "versions" / "v-b.html").read_text(encoding="utf-8") == "<html>2 better</html>"


def test_write_frames_includes_comment_threads_when_present(tmp_path):
    layout = _make_layout(tmp_path, with_frames=[{
        "id": "art-2", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-x",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [{"id": "v-x", "title": "t", "description": "",
                       "created_at": "2026-08-01T10:00:00+00:00"}],
        "_versions_html": {"v-x": "<html/>"},
        "_comments": {"threads": [
            {"created_at": "2026-08-02T09:00:00+00:00",
             "resolved": True, "carried": False,
             "comments": [
                 {"author_index": 1, "author_role": "",
                  "author_is_artifact_owner": False,
                  "text": "The green doesn't convince me",
                  "created_at": "2026-08-02T09:00:00+00:00",
                  "to_claude_at": "2026-08-02T09:00:00+00:00"},
                 {"author_index": 1, "author_role": "assistant",
                  "author_is_artifact_owner": False,
                  "text": "Changed to dark cyan",
                  "created_at": "2026-08-02T09:05:00+00:00",
                  "to_claude_at": "2026-08-02T09:05:00+00:00"},
             ]}
        ]},
    }])
    banco = tmp_path / "FRAMES"
    stats = nc.write_frames(layout, banco)
    assert stats["comments"] == 2
    note = (banco / "art-2" / "00_frame.md").read_text(encoding="utf-8")
    assert "The green doesn't convince me" in note
    assert "Changed to dark cyan" in note
    assert "resolved" in note


def test_write_frames_is_idempotent(tmp_path):
    layout = _make_layout(tmp_path, with_frames=[{
        "id": "art-3", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-x",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [{"id": "v-x", "title": "t", "description": "",
                       "created_at": "2026-08-01T10:00:00+00:00"}],
        "_versions_html": {"v-x": "<html/>"},
    }])
    banco = tmp_path / "FRAMES"
    s1 = nc.write_frames(layout, banco)
    s2 = nc.write_frames(layout, banco)
    assert s2["written"] == 0
    assert s2["skipped"] == s1["written"]


# ─────────────────────────────────────────
# write_memories
# ─────────────────────────────────────────

def test_write_memories_replicates_literal_path(tmp_path):
    """D4: the 71 memory_files keep their hierarchy (/areas /people
    /projects /topics /profile.md). Flattening would destroy the
    organization Claude has built, which is information in itself."""
    layout = _make_layout(tmp_path, with_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {},
        "memory_files": [
            {"path": "/profile.md", "content": "general profile",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"path": "/areas/foo.md", "content": "area foo",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"path": "/projects/uuid-x/index.md", "content": "project index",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    assert stats["memory_files"] == 3
    assert (mem / "profile.md").read_text(encoding="utf-8") == "general profile"
    assert (mem / "areas" / "foo.md").read_text(encoding="utf-8") == "area foo"
    assert (mem / "projects" / "uuid-x" / "index.md").read_text(encoding="utf-8") == "project index"


def test_write_memories_dossier_goes_to_conversations_md(tmp_path):
    """conversations_memory is the long personal dossier (~6.7 KB in
    the real export). It's isolated into its own file so it can be
    read/edited without being diluted into profile.md."""
    layout = _make_layout(tmp_path, with_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "**Work context**\n\nThe user works...",
        "project_memories": {},
        "memory_files": [],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    assert stats["sections"] >= 1
    text = (mem / "conversations.md").read_text(encoding="utf-8")
    assert "Work context" in text
    assert "The user works" in text
    assert 'account_uuid: "usr-1"' in text  # frontmatter carries the identity


def test_write_memories_project_memories_go_to_aggregated_summary(tmp_path):
    """project_memories is a dict {uuid: text summary}. It's collected
    into a single project_summaries.md so the aggregate view is easy
    to scan without jumping between 20 files."""
    layout = _make_layout(tmp_path, with_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {
            "uuid-alpha": "Alpha project context",
            "uuid-beta": "Beta project context",
        },
        "memory_files": [],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    text = (mem / "project_summaries.md").read_text(encoding="utf-8")
    assert "uuid-alpha" in text and "Alpha project context" in text
    assert "uuid-beta" in text and "Beta project context" in text


def test_write_memories_guards_against_path_traversal(tmp_path):
    """A malicious path with '..' must not be able to write outside
    claude_mem_dir. The real export never does this, but the guard is
    cheap and prevents this from becoming an arbitrary-write vector."""
    layout = _make_layout(tmp_path, with_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {},
        "memory_files": [
            {"path": "/../../outside.md", "content": "should not be created",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    nc.write_memories(layout, mem)
    # Nothing appears outside Claude_Mem
    assert not (tmp_path.parent / "outside.md").exists()
    assert not (tmp_path / "outside.md").exists()


def test_write_memories_is_idempotent(tmp_path):
    layout = _make_layout(tmp_path, with_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "dossier",
        "project_memories": {"u1": "summary"},
        "memory_files": [
            {"path": "/areas/a.md", "content": "x",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    s1 = nc.write_memories(layout, mem)
    s2 = nc.write_memories(layout, mem)
    assert s1["written"] > 0
    assert s2["written"] == 0


def test_parse_memories_returns_none_without_memories_layout(tmp_path):
    layout = _make_layout(tmp_path)  # no memories
    assert nc.parse_memories(layout) is None


# ─────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────

def test_ingest_extras_fires_all_three_writers(tmp_path):
    """The orchestrator must call all three and return aggregated
    stats. Verified: all three destination folders exist after the run."""
    layout = _make_layout(
        tmp_path,
        with_projects=[_minimal_project(uuid="pu", name="P")],
        with_memories={"account_uuid": "u", "conversations_memory": "d",
                        "project_memories": {}, "memory_files": []},
        with_frames=[{"id": "af", "kind": "artifact", "visibility": "private",
                       "owner_account": "u", "active_version": "v",
                       "updated_at": "2026-01-01T00:00:00+00:00",
                       "versions": [{"id": "v", "title": "t", "description": "",
                                      "created_at": "2026-01-01T00:00:00+00:00"}],
                       "_versions_html": {"v": "<html/>"}}],
    )
    base = tmp_path / "vault"
    stats = nc.ingest_extras(layout, base)
    assert stats["projects"]["projects"] == 1
    assert stats["memories"]["sections"] >= 1
    assert stats["frames"]["frames"] == 1
    assert (base / "PRJ_VAULT" / "P" / "00_project.md").exists()
    assert (base / "Claude_Mem" / "conversations.md").exists()
    assert (base / "MERGED_VAULT" / "CLAUDE_WEB" / "FRAMES" / "af" / "00_frame.md").exists()


def test_ingest_extras_accepts_partial_layout(tmp_path):
    """If the layout only carries conversations, the other writers
    find nothing and return stats at zero -- without blowing up."""
    layout = _make_layout(tmp_path)  # only conversations
    base = tmp_path / "vault"
    stats = nc.ingest_extras(layout, base)
    assert stats["projects"]["projects"] == 0
    assert stats["frames"]["frames"] == 0
    assert stats["memories"]["sections"] == 0


# ─────────────────────────────────────────
# Test against V0ra's REAL export
# ─────────────────────────────────────────

_BCK = Path(__file__).resolve().parent.parent / "bck" / "NewClaude"


@pytest.mark.skipif(not _BCK.is_dir(), reason="bck/NewClaude/ not available")
def test_ingest_extras_against_real_export(tmp_path):
    """The disciplined test: against V0ra's real export, not synthetic
    fixtures. Ingest goes to a test vault under tmp_path so her real
    vault stays clean. Minimum counts checked (24 projects, 10 frames,
    71 memory_files)."""
    base = tmp_path / "vault"
    stats = nc.ingest_extras(_BCK, base)
    assert stats["projects"]["projects"] == 24
    assert stats["frames"]["frames"] == 10
    assert stats["frames"]["versions"] == 118  # measured earlier against the zip
    assert stats["memories"]["memory_files"] == 71
    # conversations_memory (dossier), project_memories (aggregate)
    assert stats["memories"]["sections"] == 2
    # 18 distinct UUIDs under /projects/ in the real export (measured:
    # uneven distribution, 2-4 files per UUID; some projects appear in
    # projects/*.json but with no memory in memory_files).
    some_proj = list((base / "Claude_Mem" / "projects").iterdir())
    assert len(some_proj) == 18
    assert (base / "Claude_Mem" / "conversations.md").exists()
    assert (base / "Claude_Mem" / "profile.md").exists()  # sits at the root of memory_files
