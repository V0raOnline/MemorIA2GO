# -*- coding: utf-8 -*-
"""providers/newclaude_adapter.py -- Adapter for the NEW Claude (claude.ai)
export format, feeding MemorIA2GO's intermediate model.

Anthropic quietly changed the export format in August/September 2026
(memory unification between chat and Cowork, see
https://support.claude.com/en/articles/12123587). What used to be ONE
zip with conversations.json + users.json + projects.json is now a
JSON MANIFEST + 5 SINGLE-USE ZIPS, one per category:

    manifest-<uuid>-<ts>-<sig>-<YYYY-MM-DD-HH-MM-SS>.json
    ├── light_metadata-000.zip  (users.json + login_history.json)
    ├── projects-000.zip        (projects/<uuid>.json, one per project)
    ├── memories-000.zip        (memories/<user_uuid>.json, persistent memory)
    ├── frames-000.zip          (artifacts/<uuid>/... versions + comments)
    └── conversations-000.zip   (monolithic conversations.json, same shape)

No official announcement (checked against the Privacy Center and public
changelogs, 2026-09-21). The only public trail is a third-party issue:
https://github.com/ukogan/claude-migration-assistant/issues/4

DESIGN DECISIONS (see bck/NewClaude/PLAN.md):

- The inner `conversations.json` HAS the same shape as the old export.
  Verified against a real export (264 conversations, 13,935 messages):
  conversation and message keys identical to claude_adapter's
  KNOWN_KEYS. This adapter delegates to `claude_adapter.parse` for
  conversations and reimplements nothing.
- The emitted `source` is `claude_export`, NOT `newclaude_export`.
  Reason: the pipeline uses `conv_id` as the conversation identity in
  vault_merge (verified in vault_merge.py:199, `key = f"id:{cid}"`);
  if `source` diverged, variants of the same `conv_id` across the
  old and the new export wouldn't be merged coherently. With the same
  `source`, vault_merge merges them and recovers any new messages.
- `memories`, `frames`, `projects` and `light_metadata` are handled by
  the writers at the bottom of this file (write_projects, write_frames,
  write_memories). `light_metadata` is preserved raw but not ingested
  (account metadata, no vault value).
"""
from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers import claude_adapter

# Characters Windows doesn't allow in file/folder names. They get
# replaced with "_"; accents and spaces are kept (Obsidian handles
# them fine and they belong to the human name the user wants to see).
_WIN_UNSAFE_RX = re.compile(r'[\\/:*?"<>|]')


def _sanitize_windows_name(name: str) -> str:
    """Sanitize a name for use as a Windows folder/file without slugging
    it aggressively. Only substitutes the 9 forbidden characters and
    collapses duplicate whitespace; leaves case, accents, dashes and
    single spaces alone."""
    s = _WIN_UNSAFE_RX.sub("_", name or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Trailing dots and spaces are also invalid (Windows trims them
    # when creating the path and produces invisible collisions).
    s = s.rstrip(". ")
    return s or "unnamed"


def _yaml_val(v: Any) -> str:
    """Serialize a Python value to the minimal YAML needed for note
    frontmatter: strings in double quotes with inner quotes escaped to
    single quotes, bool/None unquoted, numbers as-is."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace('"', "'") + '"'


# The five categories the manifest must list. If a category outside
# this set shows up, or if an expected one is missing, that's the sign
# that Anthropic moved the format again -- preflight warns, doesn't
# block (same discipline as KNOWN_KEYS in the older adapter and Grok).
KNOWN_CATEGORIES = frozenset({
    "light_metadata", "projects", "memories", "frames", "conversations",
})

# Keys expected in the manifest JSON. `version` may bump without
# breaking compatibility; it's inspected, not required at a specific
# value.
MANIFEST_KEYS = frozenset({
    "instructions", "created_at", "total_files", "data_files", "version",
})

# Keys expected in each entry of the manifest's `data_files`.
DATA_FILE_KEYS = frozenset({
    "batch_index", "export_url", "category", "part", "filename",
})


def detect_manifest(data: Any) -> bool:
    """True if `data` (already-loaded JSON) is the new export's manifest.

    Identified by the combination: root dict with `data_files` (list),
    each entry a dict with `category` and `filename`, and at least one
    category from the known set. Deliberately PERMISSIVE with the
    optional keys (`instructions`, `version`, `total_files`,
    `created_at`) so that a minor format change doesn't break
    detection; drift warnings are the caller's responsibility."""
    if not isinstance(data, dict):
        return False
    dfs = data.get("data_files")
    if not isinstance(dfs, list) or not dfs:
        return False
    if not all(isinstance(d, dict) and "category" in d and "filename" in d
               for d in dfs):
        return False
    cats = {d.get("category") for d in dfs}
    return bool(cats & KNOWN_CATEGORIES)


def detect_layout(folder: Any) -> bool:
    """True if `folder` (Path or str) is a decompressed directory of the
    new export.

    Recognizes the layout that results from decompressing the 5 zips:
    five sibling subfolders `<category>-NNN/` (usually `-000`), each
    holding the contents of its zip. A missing category is tolerated
    (e.g. if the user only decompressed conversations-000.zip to try
    it): the minimum signal is that `conversations-NNN/` exists with
    a `conversations.json` inside."""
    p = Path(folder)
    if not p.is_dir():
        return False
    # Look for the conversations subfolder (the minimum viable marker).
    for sub in p.iterdir():
        if not sub.is_dir():
            continue
        name = sub.name.lower()
        if name.startswith("conversations-") and (sub / "conversations.json").is_file():
            return True
    return False


def _find_subdir(folder: Path, category: str) -> Optional[Path]:
    """Find the `<category>-NNN/` subfolder inside `folder`. Returns the
    first one found (usually `-000`); None if it doesn't exist."""
    prefix = category.lower() + "-"
    for sub in folder.iterdir():
        if sub.is_dir() and sub.name.lower().startswith(prefix):
            return sub
    return None


def parse_conversations(folder: Any) -> List[Dict[str, Any]]:
    """Read conversations.json from a decompressed new-export folder and
    return it already parsed by `claude_adapter.parse`.

    Delegates ALL semantic work to the older adapter: the internal
    shape of conversations.json didn't change, and re-implementing it
    here would duplicate 230 lines of tested logic (threading by
    parent_message_uuid, artifact resolution, attachments, rendering,
    ...)."""
    p = Path(folder)
    conv_dir = _find_subdir(p, "conversations")
    if conv_dir is None:
        return []
    conv_json = conv_dir / "conversations.json"
    if not conv_json.is_file():
        return []
    import json
    with conv_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return claude_adapter.parse(data)


def categories_from_manifest(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Given a valid manifest (`detect_manifest(data)` True), return
    `{"known": [...], "unknown": [...]}` in the order they appear in
    `data_files`. Used by preflight to warn when Anthropic adds a new
    category (same signal as newly seen keys)."""
    known, unknown = [], []
    for d in data.get("data_files") or []:
        cat = d.get("category")
        if cat in KNOWN_CATEGORIES:
            known.append(cat)
        elif cat:
            unknown.append(cat)
    return {"known": known, "unknown": unknown}


# ─────────────────────────────────────────
# projects: one JSON per project in projects-NNN/projects/<uuid>.json
# ─────────────────────────────────────────
# Keys observed against a real export (24 projects, 2026-09-20). Same
# KNOWN_KEYS discipline as the other adapters: if a key outside this
# set appears, that's drift and preflight says so. Doesn't block ingest.

KNOWN_PROJECT_KEYS = frozenset({
    "uuid", "name", "description", "is_private", "is_starter_project",
    "prompt_template", "created_at", "updated_at", "creator", "docs",
})

KNOWN_DOC_KEYS = frozenset({
    "uuid", "filename", "content", "created_at",
})


def parse_projects(folder: Any) -> List[Dict[str, Any]]:
    """Walk projects-NNN/projects/*.json and return a normalized dict
    per project. Writes NOTHING to the vault: the location decision
    (D3 in the PLAN) lives in write_projects.

    Output shape:
        {"uuid": str,
         "name": str,
         "description": str,
         "prompt_template": str,       # project instructions (system prompt)
         "is_private": bool,
         "is_starter_project": bool,
         "created_at": float | None,   # epoch seconds (pipeline convention)
         "updated_at": float | None,
         "creator": {"uuid": str, "full_name": str},
         "docs": [{"uuid","filename","content","created_at"}, ...],
         "provider": "claude"}

    An empty project (no docs) is still emitted: it's still a real
    project in the account; downstream code decides if it deserves a
    note."""
    p = Path(folder)
    proj_dir = _find_subdir(p, "projects")
    if proj_dir is None:
        return []
    inner = proj_dir / "projects"
    if not inner.is_dir():
        return []
    import json
    out: List[Dict[str, Any]] = []
    for fp in sorted(inner.glob("*.json")):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unreadable project shouldn't take down the rest; skip it.
            continue
        docs_out: List[Dict[str, Any]] = []
        for doc in d.get("docs") or []:
            if not isinstance(doc, dict):
                continue
            docs_out.append({
                "uuid": doc.get("uuid"),
                "filename": (doc.get("filename") or "").strip(),
                "content": doc.get("content") or "",
                "created_at": claude_adapter._epoch(doc.get("created_at")),
            })
        creator = d.get("creator") or {}
        out.append({
            "uuid": d.get("uuid"),
            "name": (d.get("name") or "").strip(),
            "description": (d.get("description") or "").strip(),
            "prompt_template": (d.get("prompt_template") or "").strip(),
            "is_private": bool(d.get("is_private")),
            "is_starter_project": bool(d.get("is_starter_project")),
            "created_at": claude_adapter._epoch(d.get("created_at")),
            "updated_at": claude_adapter._epoch(d.get("updated_at")),
            "creator": {
                "uuid": creator.get("uuid"),
                "full_name": (creator.get("full_name") or "").strip(),
            },
            "docs": docs_out,
            "provider": "claude",
        })
    return out


# ─────────────────────────────────────────
# frames = artifacts, with version history and comments
# ─────────────────────────────────────────
# Per-artifact structure (verified against a real export 2026-09-20):
#   frames-NNN/artifacts/<artifact_id>/
#     artifact.json          -- metadata: id, kind, visibility, versions[],
#                               owner_account, updated_at, active_version
#     artifact_comments.json -- OPTIONAL (2/10 in the real export): dict
#                               with "threads": [{comments:[...], resolved,
#                               carried, created_at}]
#     versions/<ver_id>.html -- the file for each version, served as
#                               self-contained HTML
#
# The adapter only *inventories* the versions (id, title, size, disk
# path). It does NOT read the HTML content here: there are 118 files
# in the real export and the consumer opens them as needed.

KNOWN_FRAME_KEYS = frozenset({
    "id", "kind", "visibility", "versions", "owner_account",
    "updated_at", "active_version",
})

KNOWN_VERSION_KEYS = frozenset({
    "id", "title", "description", "created_at",
})

KNOWN_THREAD_KEYS = frozenset({
    "created_at", "resolved", "carried", "comments",
})

KNOWN_COMMENT_KEYS = frozenset({
    "author_index", "author_role", "author_is_artifact_owner",
    "text", "created_at", "to_claude_at",
})


def parse_frames(folder: Any) -> List[Dict[str, Any]]:
    """Walk frames-NNN/artifacts/<uuid>/ and return a normalized
    inventory per artifact. Writes nothing.

    Per-artifact output shape:
        {"id": str,
         "kind": str,               # 'artifact' so far, leaves room
         "visibility": str,         # 'private'/'public'/...
         "owner_account": str,      # user's uuid
         "updated_at": float | None,
         "active_version": str,     # id of the active version
         "versions": [               # metadata + on-disk HTML path
             {"id": str, "title": str, "description": str,
              "created_at": float | None, "path": Path, "size": int}, ...
         ],
         "threads": [                # comments (empty if no file)
             {"created_at","resolved","carried",
              "comments":[{"author_index","author_role",
                           "author_is_artifact_owner","text",
                           "created_at","to_claude_at"}]}
         ],
         "provider": "claude"}

    Versions come back in the same order artifact.json lists them; that
    list usually runs oldest-to-newest but isn't reordered here (the
    consumer decides how to render it)."""
    p = Path(folder)
    frames_dir = _find_subdir(p, "frames")
    if frames_dir is None:
        return []
    inner = frames_dir / "artifacts"
    if not inner.is_dir():
        return []
    import json
    out: List[Dict[str, Any]] = []
    for adir in sorted(inner.iterdir()):
        if not adir.is_dir():
            continue
        art_json = adir / "artifact.json"
        if not art_json.is_file():
            continue
        try:
            a = json.loads(art_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        versions_out: List[Dict[str, Any]] = []
        versions_dir = adir / "versions"
        for v in a.get("versions") or []:
            if not isinstance(v, dict):
                continue
            vid = v.get("id")
            # Locate the HTML on disk by its id (filename = <id>.html).
            vpath = None
            vsize = 0
            if vid and versions_dir.is_dir():
                cand = versions_dir / f"{vid}.html"
                if cand.is_file():
                    vpath = cand
                    vsize = cand.stat().st_size
            versions_out.append({
                "id": vid,
                "title": (v.get("title") or "").strip(),
                "description": (v.get("description") or "").strip(),
                "created_at": claude_adapter._epoch(v.get("created_at")),
                "path": vpath,
                "size": vsize,
            })

        threads_out: List[Dict[str, Any]] = []
        cpath = adir / "artifact_comments.json"
        if cpath.is_file():
            try:
                cdata = json.loads(cpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cdata = None
            if isinstance(cdata, dict):
                for th in cdata.get("threads") or []:
                    if not isinstance(th, dict):
                        continue
                    comments = []
                    for co in th.get("comments") or []:
                        if not isinstance(co, dict):
                            continue
                        comments.append({
                            "author_index": co.get("author_index"),
                            "author_role": (co.get("author_role") or "").strip(),
                            "author_is_artifact_owner": bool(co.get("author_is_artifact_owner")),
                            "text": co.get("text") or "",
                            "created_at": claude_adapter._epoch(co.get("created_at")),
                            "to_claude_at": claude_adapter._epoch(co.get("to_claude_at")),
                        })
                    threads_out.append({
                        "created_at": claude_adapter._epoch(th.get("created_at")),
                        "resolved": bool(th.get("resolved")),
                        "carried": bool(th.get("carried")),
                        "comments": comments,
                    })

        out.append({
            "id": a.get("id"),
            "kind": (a.get("kind") or "").strip(),
            "visibility": (a.get("visibility") or "").strip(),
            "owner_account": a.get("owner_account"),
            "updated_at": claude_adapter._epoch(a.get("updated_at")),
            "active_version": a.get("active_version"),
            "versions": versions_out,
            "threads": threads_out,
            "provider": "claude",
        })
    return out


# ─────────────────────────────────────────
# memories: personal dossier + vault-style memory + per-project summaries
# ─────────────────────────────────────────
# This JSON is sensitive: it holds the personal profile Claude has
# accumulated. It lives outside the main vault (in Claude_Mem/).

def parse_memories(folder: Any) -> Optional[Dict[str, Any]]:
    """Read the single JSON inside memories-NNN/memories/ and return the
    four sections:
        {"conversations_memory": str,   # personal dossier
         "project_memories": {uuid: str, ...},  # per-project summary
         "memory_files": [{"path", "content", "updated_at"}, ...],
         "account_uuid": str}

    Returns None if there's no JSON (partial layout without memories).
    Individual fields can be missing from the JSON: they default to
    empty so the consumer doesn't have to defend each one."""
    p = Path(folder)
    mem_dir = _find_subdir(p, "memories")
    if mem_dir is None:
        return None
    inner = mem_dir / "memories"
    if not inner.is_dir():
        return None
    import json
    files = sorted(inner.glob("*.json"))
    if not files:
        return None
    # The real export only has ONE file (named by account_uuid). If
    # Anthropic ever ships several, we process the first one and the
    # rest waits on a future decision -- nothing is lost (the raw zip
    # is preserved).
    try:
        d = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mfs = []
    for m in d.get("memory_files") or []:
        if not isinstance(m, dict):
            continue
        mfs.append({
            "path": (m.get("path") or "").strip(),
            "content": m.get("content") or "",
            "updated_at": claude_adapter._epoch(m.get("updated_at")),
        })
    return {
        "conversations_memory": d.get("conversations_memory") or "",
        "project_memories": dict(d.get("project_memories") or {}),
        "memory_files": mfs,
        "account_uuid": (d.get("account_uuid") or "").strip(),
    }


# ─────────────────────────────────────────
# WRITERS: three writers, one per category
# ─────────────────────────────────────────
# All are idempotent by content: they re-read the target file before
# rewriting it and skip if unchanged. They never delete pre-existing
# files (a reingest doesn't destroy the user's hand-edits in the vault
# between runs).


def _write_if_changed(p: Path, text: str) -> bool:
    """Write `text` to `p` only if the content differs from what's
    there. Returns True if it wrote, False if it skipped. Creates the
    parent directory if needed. UTF-8 encoding, LF newlines (same rule
    as write_md)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if p.exists():
        try:
            if p.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def _copy_if_changed(src: Path, dst: Path) -> bool:
    """Binary copy of a file to the destination only if the destination
    does not exist or its size does not match. Comparison is by size,
    not by hash, to avoid reading 100 MB of HTML on every pass; the
    adverse case (different content with same size) is theoretical --
    the HTML filename embeds timestamp+hash, so it always changes."""
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def _fmt_date(epoch: Optional[float]) -> str:
    """Epoch -> YYYY-MM-DD HH:MM for the frontmatter. No timezone: the
    rest of the vault is implicit local tz (see iso_date in
    split_chatgpt_export)."""
    if not epoch:
        return ""
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def write_projects(folder: Any, prj_vault: Any) -> Dict[str, Any]:
    """Write the new export's projects to `<prj_vault>/<name>/`.
    See D3 in bck/NewClaude/PLAN.md.

    Per project:
        <prj_vault>/<name>/00_project.md
        <prj_vault>/<name>/_docs/<filename>   (one per doc, if any)

    Returns stats {"projects": n, "docs": n, "written": n, "skipped": n}."""
    prj_vault = Path(prj_vault)
    stats = {"projects": 0, "docs": 0, "written": 0, "skipped": 0}
    for pr in parse_projects(folder):
        folder_name = _sanitize_windows_name(pr["name"])
        root = prj_vault / folder_name
        # 00_project.md
        pairs = [
            ("type", "claude-project"),
            ("name", pr["name"]),
            ("uuid", pr["uuid"]),
            ("provider", "claude"),
            ("visibility", "private" if pr["is_private"] else "public"),
            ("starter", pr["is_starter_project"]),
            ("creator", pr["creator"].get("full_name") or ""),
            ("creator_uuid", pr["creator"].get("uuid") or ""),
            ("created_at", _fmt_date(pr["created_at"])),
            ("updated_at", _fmt_date(pr["updated_at"])),
            ("source", "claude_export"),
        ]
        L = ["---"]
        for k, v in pairs:
            L.append(f"{k}: {_yaml_val(v)}")
        L += ["---", "", f"# {pr['name']}", ""]
        if pr["description"]:
            L += ["> " + pr["description"].replace("\n", "\n> "), ""]
        if pr["prompt_template"]:
            L += ["## Project instructions", "",
                  "```", pr["prompt_template"], "```", ""]
        # Link to Claude's memory about this project (D4).
        L += ["## Claude's memory of this project", "",
              f"See `Claude_Mem/projects/{pr['uuid']}/index.md` and "
              f"`Claude_Mem/projects/{pr['uuid']}/overview.md` (if present).",
              ""]
        # Docs list
        if pr["docs"]:
            L += [f"## Project knowledge docs ({len(pr['docs'])})", ""]
            for d in pr["docs"]:
                fn = _sanitize_windows_name(d["filename"]) or "unnamed"
                L.append(f"- [[_docs/{fn}]]")
            L.append("")
        else:
            L += ["## Project knowledge docs", "",
                  "*(this project has no project knowledge in the export)*", ""]
        text = "\n".join(L).rstrip() + "\n"
        if _write_if_changed(root / "00_project.md", text):
            stats["written"] += 1
        else:
            stats["skipped"] += 1
        # _docs/<filename>
        for d in pr["docs"]:
            fn = _sanitize_windows_name(d["filename"]) or "unnamed"
            # The doc goes as-is: these are knowledge files uploaded to
            # the project, not vault notes. No frontmatter or headings
            # are added -- they're preserved verbatim.
            if _write_if_changed(root / "_docs" / fn, d["content"]):
                stats["written"] += 1
            else:
                stats["skipped"] += 1
            stats["docs"] += 1
        stats["projects"] += 1
    return stats


def write_frames(folder: Any, banco_dir: Any) -> Dict[str, Any]:
    """Write the new export's artifacts to `<banco_dir>/<id>/`.
    Typical banco_dir: `<base_vault>/MERGED_VAULT/CLAUDE_WEB/FRAMES/`.

    Per artifact:
        <banco>/<id>/00_frame.md          (metadata + comments)
        <banco>/<id>/versions/<ver>.html  (binary copy of each version)

    Returns stats {"frames": n, "versions": n, "comments": n,
                   "written": n, "skipped": n}."""
    banco_dir = Path(banco_dir)
    stats = {"frames": 0, "versions": 0, "comments": 0,
             "written": 0, "skipped": 0}
    for fr in parse_frames(folder):
        aid = fr["id"] or "no_id"
        root = banco_dir / aid
        # Human title: the active version usually has a readable one.
        title = ""
        for v in fr["versions"]:
            if v["id"] == fr["active_version"] and v["title"]:
                title = v["title"]
                break
        if not title and fr["versions"]:
            title = fr["versions"][-1]["title"] or aid
        title = title or aid

        pairs = [
            ("type", "claude-frame"),
            ("id", aid),
            ("kind", fr["kind"]),
            ("visibility", fr["visibility"]),
            ("owner_account", fr["owner_account"]),
            ("active_version", fr["active_version"]),
            ("updated_at", _fmt_date(fr["updated_at"])),
            ("provider", "claude"),
            ("source", "claude_export"),
        ]
        L = ["---"]
        for k, v in pairs:
            L.append(f"{k}: {_yaml_val(v)}")
        L += ["---", "", f"# {title}", ""]

        # Version list (most recent first)
        L += [f"## Versions ({len(fr['versions'])})", ""]
        for v in sorted(fr["versions"], key=lambda x: x["created_at"] or 0, reverse=True):
            marker = "  ← active" if v["id"] == fr["active_version"] else ""
            date = _fmt_date(v["created_at"])
            size_kb = f"{v['size']/1024:.1f} KB" if v["size"] else ""
            L.append(f"- `{v['id']}` · {v['title'] or '(no title)'} · {date} · {size_kb}{marker}")
            if v["description"] and v["description"] != v["title"]:
                L.append(f"  {v['description']}")
        L.append("")

        # Comments (if any)
        if fr["threads"]:
            L += [f"## Comments ({sum(len(t['comments']) for t in fr['threads'])})", ""]
            for th in sorted(fr["threads"], key=lambda t: t["created_at"] or 0):
                status = "resolved" if th["resolved"] else "open"
                L += [f"### Thread from {_fmt_date(th['created_at'])} · {status}", ""]
                for co in th["comments"]:
                    author = co["author_role"] or "user"
                    owner_mark = " (owner)" if co["author_is_artifact_owner"] else ""
                    L += [f"**{author}{owner_mark}** — {_fmt_date(co['created_at'])}", ""]
                    L += [co["text"], ""]
                    stats["comments"] += 1
        text = "\n".join(L).rstrip() + "\n"
        if _write_if_changed(root / "00_frame.md", text):
            stats["written"] += 1
        else:
            stats["skipped"] += 1

        # Binary copy of each HTML version
        for v in fr["versions"]:
            if v["path"] is None:
                continue
            dst = root / "versions" / f"{v['id']}.html"
            if _copy_if_changed(v["path"], dst):
                stats["written"] += 1
            else:
                stats["skipped"] += 1
            stats["versions"] += 1

        stats["frames"] += 1
    return stats


def write_memories(folder: Any, claude_mem_dir: Any) -> Dict[str, Any]:
    """Write memories to `<claude_mem_dir>/`. Typical claude_mem_dir:
    `<base_vault>/Claude_Mem/`. See D2 and D4 in bck/NewClaude/PLAN.md.

    Structure preserved (D4, literal path):
        <claude_mem>/profile.md            (short personal dossier)
        <claude_mem>/conversations.md      (long conversations_memory)
        <claude_mem>/projects/<uuid>/…     (per-project memory)
        <claude_mem>/areas/…               (work topics)
        <claude_mem>/people/…              (close people)
        <claude_mem>/topics/…              (personal topics)
        <claude_mem>/project_summaries.md  (textual per-project summaries)

    Returns stats {"sections", "memory_files", "written", "skipped"}."""
    claude_mem_dir = Path(claude_mem_dir)
    stats = {"sections": 0, "memory_files": 0, "written": 0, "skipped": 0}
    mem = parse_memories(folder)
    if mem is None:
        return stats

    # 1) conversations_memory: the long personal dossier. Written as
    # a single file with a heading, not folded into profile.md,
    # because it can get long (6.7 KB in the real export) and deserves
    # its own note with a change history via reingests.
    if mem["conversations_memory"]:
        L = ["---",
             'type: "conversation-memory"',
             'provider: "claude"',
             f'account_uuid: "{mem["account_uuid"]}"',
             'source: "claude_export"',
             "---", "",
             "# Claude's memory of conversations", "",
             "> Personal dossier Claude has accumulated from the user's "
             "conversations. It's regenerated by the provider on each "
             "export; to edit or delete it, use the claude.ai UI.",
             "",
             mem["conversations_memory"].strip(), ""]
        if _write_if_changed(claude_mem_dir / "conversations.md",
                             "\n".join(L).rstrip() + "\n"):
            stats["written"] += 1
        else:
            stats["skipped"] += 1
        stats["sections"] += 1

    # 2) project_memories: textual per-project summary (dict
    # uuid->text). Written as a single note with all of them, so the
    # aggregate view Claude has of the user's projects is easy to scan.
    if mem["project_memories"]:
        L = ["---",
             'type: "project-memory"',
             'provider: "claude"',
             f'account_uuid: "{mem["account_uuid"]}"',
             'source: "claude_export"',
             "---", "",
             "# Claude's memory by project", "",
             f"> {len(mem['project_memories'])} projects with a text "
             "summary. The UUID connects to the projects in `PRJ_VAULT/` "
             "and to the `projects/<uuid>/` folders in this same vault.",
             ""]
        for uuid_, text in sorted(mem["project_memories"].items()):
            L += [f"## {uuid_}", "", text.strip(), ""]
        if _write_if_changed(claude_mem_dir / "project_summaries.md",
                             "\n".join(L).rstrip() + "\n"):
            stats["written"] += 1
        else:
            stats["skipped"] += 1
        stats["sections"] += 1

    # 3) memory_files: 71 notes with a literal path. The structure is
    # replicated as-is (D4). Each file already carries its own
    # frontmatter inside the content -- nothing is added, just
    # preserved.
    for m in mem["memory_files"]:
        # The path arrives as '/areas/foo.md'. lstrip('/') to turn it
        # into a relative path. Each segment is then sanitized
        # separately (in case any segment held Windows-forbidden chars
        # -- not seen in the real export but robust).
        rel = m["path"].lstrip("/").lstrip("\\")
        if not rel:
            continue
        segments = [_sanitize_windows_name(s) for s in rel.replace("\\", "/").split("/")]
        # Guard against path traversal ("..") even if the export
        # never carries it: never write outside claude_mem_dir.
        segments = [s for s in segments if s and s != ".."]
        if not segments:
            continue
        dst = claude_mem_dir.joinpath(*segments)
        # Final check: dst must be under claude_mem_dir.
        try:
            dst.resolve().relative_to(claude_mem_dir.resolve())
        except ValueError:
            continue
        if _write_if_changed(dst, m["content"]):
            stats["written"] += 1
        else:
            stats["skipped"] += 1
        stats["memory_files"] += 1

    return stats


# ─────────────────────────────────────────
# Orchestrator: ingest the four non-conversation categories
# ─────────────────────────────────────────
# Conversations go through the existing path (load_conversations +
# write_md + vault_merge). This function covers the rest: projects,
# frames, memories. light_metadata remains uningested (account
# metadata, no vault value).

def ingest_extras(folder: Any, base_vault: Any,
                  prj_vault_name: str = "PRJ_VAULT") -> Dict[str, Any]:
    """Ingest the categories in the new layout that are not
    conversations. Idempotent: safe to rerun without duplicating.

    Fixed paths (per D2/D3/D4 in bck/NewClaude/PLAN.md):
        base_vault/PRJ_VAULT/<name>/…               (D3)
        base_vault/MERGED_VAULT/CLAUDE_WEB/FRAMES/…  (own bank)
        base_vault/Claude_Mem/…                     (D2, new vault)

    Returns {"projects": stats, "frames": stats, "memories": stats}."""
    base_vault = Path(base_vault)
    return {
        "projects": write_projects(folder, base_vault / prj_vault_name),
        "frames": write_frames(folder, base_vault / "MERGED_VAULT" / "CLAUDE_WEB" / "FRAMES"),
        "memories": write_memories(folder, base_vault / "Claude_Mem"),
    }
