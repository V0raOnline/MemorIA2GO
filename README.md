# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> Turn your AI conversation history — ChatGPT, Claude, Grok — into a structured, MCP-ready Obsidian vault. Your context, local and yours.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## Language editions

M3M0R·IA is maintained as two parallel product lines, one per language. Both are complete and equivalent — the localization effort finished with the `i18n-content` milestone:

- **`release/en` (this branch) — English edition.** Fully localized: the web UI (`i18n-web`), everything the app prints while running (`i18n-runtime`), and the content it writes into your vault — note metadata lines, index labels and the folder names on disk (`Conversations`, `GENERATED`, `ATTACHMENTS`, `ARTIFACTS`, `_Topics`…), tags `i18n-content` phases 3a and 3b.

  **Upgrading a vault built with an earlier English release?** Those vaults have Spanish folder names, and reprocessing alone will not fix them — the pipeline never deletes, so it would write the English tree *beside* the Spanish one and leave every note duplicated in Obsidian's search and graph. Open the **Reconnection** tab: if the old layout is detected, a "Vault layout" card appears with a one-click rename that also reconnects every asset link inside your notes. Nothing is deleted, and your download triage and import history are left untouched. Reprocess afterwards to rewrite the note *content* in English.
- **`release/es` — Spanish edition.** The original, fully functional application. Receives bug fixes during the localization effort.
- **`main`** is frozen at the last common state (v2.8.0) as an immutable reference. Bug fixes land on `release/es` first and are cherry-picked to `release/en`, so both lines stay in step.

---

## What is M3M0R·IA?

M3M0R·IA converts the native exports of your AI chat providers into a clean, project-organized vault of Markdown notes, ready to be browsed in Obsidian and consumed as live context by Claude Desktop via MCP (Model Context Protocol).

Unlike generic migration tools that only transfer saved memories, M3M0R·IA brings your **full conversation history** — deduplicated, merged, organized by project and date, with images extracted and navigation indexes generated.

**Supported providers** (detected by internal JSON structure, never by filename):

| Provider | Export format | Branch handling | Attachments |
|----------|--------------|-----------------|-------------|
| ChatGPT  | zip / json / html | `current_node` tree walk | AI-generated images and user uploads extracted to separate banks (`CHATGPT/GENERATED`, `CHATGPT/ATTACHMENTS`) |
| Claude   | zip (may arrive in `batch-NNNN` parts) | most-recent-leaf reconstruction (no current_node in export) | extracted text quoted inline; uploaded binaries not shipped by the export; **generated Artifacts** (documents, code, HTML...) extracted to `CLAUDE/ARTIFACTS`, one file per artifact, sorted by type — only the final version, revision history is discarded |
| Grok     | zip (`ttl/30d/...` layout) | `leaf_response_id` when present, most-recent-leaf otherwise | file attachments extracted to `GROK/ATTACHMENTS`; Imagine generations (images and video) extracted to `GROK/GENERATED_IMAGE`/`GROK/GENERATED_VIDEO` when the export ships the binary, otherwise logged as a pending-download list (prompt + link), never auto-downloaded |

All providers coexist in a single MERGED vault. Every note carries `provider` and `source` in its frontmatter, so you can filter, color and index by origin. Every asset bank gets its own navigable index, same pattern as the classic image index.

*The detail of how it works inside — the four steps, the adapters, the sister tools — is in **[ARCHITECTURE.md](ARCHITECTURE.md)**.*

---

## Requirements

- Python **3.10+**
- Dependencies: `pip install -r requirements.txt`
  (beautifulsoup4, lxml, rich, pyyaml, flask)
- Obsidian (to browse the result) and optionally Claude Desktop with an MCP filesystem server (to use it as live context)
- Optional, for running the test suite: `pip install -r requirements-dev.txt && python -m pytest tests/`

Developed and battle-tested on Windows; the pipeline itself is cross-platform.

---

## Quick start (web UI)

M3M0R·IA ships with a local web interface — dashboard, configuration, pre-flight verification, pipeline runner with live log, and orphan-project curation.

```bash
git clone <this repo>
cd MemorIA2GO
pip install -r requirements.txt

# 1. Create your config from the template and set your paths
copy memoria_config.yaml.example memoria_config.yaml   # Windows
cp memoria_config.yaml.example memoria_config.yaml     # Linux / macOS

# 2. Launch
python launcher.py     # on Linux, depending on your distro: python3 launcher.py
```

Your browser opens at `http://127.0.0.1:8765`. The server binds to localhost only — it has no authentication and can run the pipeline, so keep it that way.

Options:

```bash
python launcher.py --port 80 --no-browser   # for a persistent local server
```

Optional pretty URL: add `127.0.0.1  m3m0ria` to your hosts file (Windows: `C:\Windows\System32\drivers\etc\hosts`; Linux/macOS: `/etc/hosts`, with `sudo`) and run on port 80 → `http://m3m0ria/`. On Windows you can register a logon Scheduled Task running `pythonw launcher.py --port 80 --no-browser` from the repo folder; on Linux, a systemd user service or an autostart entry running `python3 launcher.py --port 8765 --no-browser` does the same job (port 80 on Linux needs privileges: stay on 8765 or put a proxy in front).

First dashboard load computes statistics once and caches them next to your vault (`.m3m0ria_stats.json`); after that, loads are instant. The pipeline refreshes the cache at the end of step 4, and the dashboard offers a manual *recalcular* link.

### CLI (no web)

```bash
python MemorIA2GO.py                  # interactive, full pipeline
python MemorIA2GO.py --reprocess-all  # re-parse every valid export from scratch
```

---

> ### Are you stuck?
>
> If you've never used a terminal, or they're asking you for a Suno token and you don't know what that is, don't keep fighting it: **[IM_STUCK.md](IM_STUCK.md)** explains it from scratch, taking nothing for granted.

## Configuration

- `memoria_config.yaml` — your paths (base vault, exports folder, gizmo map) and options (by-year/by-month folders, index generation). Created from `memoria_config.yaml.example`; never committed.
- `gizmo_map.json` — maps ChatGPT project (gizmo) IDs to human names. Curated from the web UI (Cartography tab); never committed.
- `topic_map.json` — your themes for unassigned conversations: `{"theme": ["words", "phrases", "field=value"]}`. Curated from the UI; generates linked index notes in `MERGED_VAULT/_Topics`. Never committed.
- `substack_vault` (in `memoria_config.yaml`) — where the Inkwell vault gets built. It's the **only** path it needs: the Substack export and its stats CSV live in your usual exports folder, because the conversation pipeline rejects them and Inkwell picks them up from there. One folder, two doors.
- `suno_backup` and `suno_vault` (in `memoria_config.yaml`) — MUSIC·0LOGY's two paths: where the raw Suno backup lives, and where its Obsidian vault is built. Both optional: without `suno_backup` the Observatory card simply doesn't appear — it isn't drawn as zero, because claiming "0 tracks" about a library you never downloaded is a lie, not information.

Claude and Grok exports do not link conversations to projects: those notes are organized by themes (many-to-many), not folders.

---

## The documentation, by question

Each document answers **one** question. If you're looking for something that isn't here, it's probably in another:

| | Answers |
|---|---|
| **README** (you are here) | What is it and how do I start it? |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | How does it work inside and why this way? |
| **[IM_STUCK.md](IM_STUCK.md)** | What if I don't know any of this? |
| **[DEVLOG.md](DEVLOG.md)** | What did we learn building it? |

---

## Roadmap

- Manual conversation↔project selector for residual cases (`manual:` namespace in gizmo_map, designed and deferred until the unassigned-conversations pile shrinks further)
- Asset extraction for the fragmented 2026+ ChatGPT export's `.dat` attachments (a separate binary layout from the one already handled)
- Distinguishing "never had a project" from "has a project nobody's named yet" in `Project_name` — both currently collapse to `none`

---

## License

CC BY-NC-SA 4.0 — see badge above.
