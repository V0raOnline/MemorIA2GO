# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> Turn your AI conversation history — ChatGPT, Claude, Grok — into a structured, MCP-ready Obsidian vault. Your context, local and yours.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## Language editions

M3M0R·IA is maintained as two parallel product lines while the English localization is completed:

- **`release/en` (this branch) — English edition.** The web UI is fully translated (milestone tag `i18n-web`). Two known limitations remain, by design, until the next localization phases land:
  - **Runtime messages are still in Spanish**: the live pipeline log, verification result messages, CLI output and error text come from the backend and haven't been translated yet (phase 2, `i18n-runtime`).
  - **Generated vault content is in Spanish**: note metadata headers ("Archivo adjunto:", "Artefacto:"…), index note labels and folder names (`GENERADAS`, `ADJUNTOS`, `_Temas`…) are written in Spanish. Translating persisted content is phase 3 (`i18n-content`), deliberately deferred until a compatibility strategy for existing Spanish vaults is decided.
- **`release/es` — Spanish edition.** The original, fully functional application. Receives bug fixes during the localization effort.
- **`main`** is frozen at the last common state (v2.8.0) as an immutable reference until both editions reach feature parity.

---

## What is M3M0R·IA?

M3M0R·IA converts the native exports of your AI chat providers into a clean, project-organized vault of Markdown notes, ready to be browsed in Obsidian and consumed as live context by Claude Desktop via MCP (Model Context Protocol).

Unlike generic migration tools that only transfer saved memories, M3M0R·IA brings your **full conversation history** — deduplicated, merged, organized by project and date, with images extracted and navigation indexes generated.

**Supported providers** (detected by internal JSON structure, never by filename):

| Provider | Export format | Branch handling | Attachments |
|----------|--------------|-----------------|-------------|
| ChatGPT  | zip / json / html | `current_node` tree walk | AI-generated images and user uploads extracted to separate banks (`CHATGPT/GENERADAS`, `CHATGPT/ADJUNTOS`) |
| Claude   | zip (may arrive in `batch-NNNN` parts) | most-recent-leaf reconstruction (no current_node in export) | extracted text quoted inline; uploaded binaries not shipped by the export; **generated Artifacts** (documents, code, HTML...) extracted to `CLAUDE/ARTEFACTOS`, one file per artifact, sorted by type — only the final version, revision history is discarded |
| Grok     | zip (`ttl/30d/...` layout) | `leaf_response_id` when present, most-recent-leaf otherwise | file attachments extracted to `GROK/ADJUNTOS`; Imagine generations (images and video) extracted to `GROK/GENERADAS_IMAGEN`/`GROK/GENERADAS_VIDEO` when the export ships the binary, otherwise logged as a pending-download list (prompt + link), never auto-downloaded |

All providers coexist in a single MERGED vault. Every note carries `provider` and `source` in its frontmatter, so you can filter, color and index by origin. Every asset bank gets its own navigable index, same pattern as the classic image index.

---

## How it works

The pipeline runs in 4 non-destructive steps:

**Step 1 — Import** (`split_chatgpt_export.py` + `providers/` adapters)
Each valid, pending export in your exports folder is detected by structure and dispatched to its adapter. One Markdown note per conversation lands in `RAW_VAULT`, with YAML frontmatter (title, date, provider, source, project mapping). Discarded regeneration branches are excluded — only the thread you actually kept.

**Step 2 — Merge** (`vault_merge.py`)
Consolidates variants of the same conversation across exports into `MERGED_VAULT` without losing messages: the longest variant wins as champion and any message missing from it is recovered from the others.

**Step 3 — Projects** (`project_organizer.py`)
Builds `PRJ_VAULT` as a project/year/month view of MERGED. Refreshed on every run (symlinks where the OS allows them, real copies on Windows).

**Step 4 — Indexes** (`tree_index.py`, `scaffolding_index.py`, `image_index.py`, `vault_stats.py`)
Navigation indexes (project/year/month), attachment usage index, image index, and the statistics cache that powers the dashboard.

### When to run what

- **Import pending (step 1→4)** — the everyday mode: you dropped new exports in your folder and want them in. Only processes what wasn't imported yet.
- **Update only (step 2→4)** — no new data, but how things consolidate or organize changed: after naming gizmos, or after an M3M0R·IA update touching the merge, the project view or the indexes.
- **Reprocess all** — after an M3M0R·IA version that adds or changes frontmatter fields (`provider`, `conv_id`, `model`...) or modifies the parsers: existing notes only gain new fields by re-importing from the exports. Safe (exports are the source of truth, nothing is destroyed) but takes time proportional to your history — coffee recommended.
- **Generate themes index** (Cartography tab) — whenever you edit themes; no restart needed. Step 4 also regenerates it automatically on every pipeline run.

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

## I've never used a terminal: step-by-step guide

Did everything above sound like gibberish? This section is for you. No prior knowledge, on Windows, step by step.

**1. Install Python.**
Go to [python.org/downloads](https://www.python.org/downloads/) and click the yellow download button. When running the installer, **check the "Add Python to PATH" box** (at the very bottom, easy to miss — it is the single most important step here). Then "Install Now" and wait.

**2. Download this project.**
On this GitHub page, click the green **Code** button → **Download ZIP**. Extract the ZIP anywhere — for example `C:\M3M0RIA`. (Right-click the ZIP → "Extract all".)

**3. Open a console.**
Press the Windows key, type `powershell` and press Enter. A blue or black window with text opens: that is the console or terminal. You use it by typing commands and pressing Enter. It doesn't bite.

**4. Enter the project folder.**
Type this (or copy it and paste with right-click) and press Enter — adjust the path if you extracted somewhere else:

```
cd "C:\M3M0RIA"
```

**5. Install what the program needs.**
Copy this, paste, Enter:

```
pip install -r requirements.txt
```

A wall of text will scroll by for a while. That's normal: it is downloading the pieces the program uses. When the cursor comes back, it's done.

**6. Create your configuration.**
Copy, paste, Enter:

```
copy memoria_config.yaml.example memoria_config.yaml
notepad memoria_config.yaml
```

Notepad opens with the configuration. You only need to adjust two paths: `base_vault` (the folder where your notes vault will live — a new empty folder is fine) and `exports_dir` (the folder where you'll drop the ZIPs you download from ChatGPT/Claude/Grok). Save and close.

**7. Get your exports.**
- **ChatGPT**: Settings → Data controls → Export data. You'll get an email with a ZIP.
- **Claude**: Settings → Privacy → Export data. You'll get an email with a ZIP (sometimes several).
- **Grok**: Settings → Data → Download your data.

Drop the ZIPs as-is (do not unzip them) into the folder you set as `exports_dir`.

**8. Launch M3M0R·IA.**
In the console:

```
python launcher.py
```

Your browser opens with the interface. From here on, everything is clicks: **Configuration** tab to review paths, **Verification** to check your ZIPs are recognized, and **Construction** → "Import pending" to run the conversion. The live log tells you what it's doing. When it finishes, open your vault folder with Obsidian and enjoy.

**If something fails:**
- *"python is not recognized as a command..."* → the PATH checkbox from step 1 wasn't ticked. Reinstall Python with it checked, close the console and open a new one.
- *"pip is not recognized..."* → same as above.
- The browser window doesn't open → manually type `http://127.0.0.1:8765` in your browser.

---

## Configuration

- `memoria_config.yaml` — your paths (base vault, exports folder, gizmo map) and options (by-year/by-month folders, index generation). Created from `memoria_config.yaml.example`; never committed.
- `gizmo_map.json` — maps ChatGPT project (gizmo) IDs to human names. Curated from the web UI (Cartography tab); never committed.
- `topic_map.json` — your themes for unassigned conversations: `{"theme": ["words", "phrases", "field=value"]}`. Curated from the UI; generates linked index notes in `MERGED_VAULT/_Temas`. Never committed.

Claude and Grok exports do not link conversations to projects: those notes are organized by themes (many-to-many), not folders.

---

## How this project evolved

- **v1** was a CLI-only, ChatGPT-only, 3-step pipeline: import, organize by project, index.
- **v2** (current) grew in four directions, each driven by a real failure or a real need:
  - **Merge became its own step.** Deduplication used to be destructive; now variants are consolidated without losing a single message, and the champion's provenance is preserved.
  - **Multi-provider adapters.** Claude and Grok exports were dissected against real data before writing any code. Detection is structural — a Claude zip also contains a `conversations.json`, and Grok's root also has a `conversations` key, so filename-based detection would silently produce garbage. Each adapter reconstructs the active conversation thread from its provider's own branch model.
  - **A web UI (M3M0R·IA).** Dashboard with evolution charts, per-provider and per-project stats, pre-flight verification that names each export's provider (and rejects what it can't parse yet, honestly), pipeline runner with live log, and orphan-project curation.
  - **Performance by design.** Statistics are computed once per pipeline run and cached atomically; the dashboard reads the cache in milliseconds regardless of vault size.
  - **Cartography instead of forced taxonomy.** Unassigned conversations aren't shoehorned into folders: a vocabulary cloud (seeded with project names from all three providers) feeds a many-to-many Themes system — words, phrases and `field=value` metadata rules — that generates linked indexes in Obsidian. Curation lives in one entry per theme, the derived index is regenerable, the notes stay untouched.
  - **Identity via `conv_id`.** Each conversation's native ID travels to the frontmatter and the merge groups by it: thread renames across exports (measured: 21 of 593 real conversations) fuse under the latest title while preserving `titulo_original`, instead of duplicating as ghosts.
- **v2.5** made the project testable instead of just tested-by-hand:
  - **A real regression suite.** Synthetic fixtures for all three providers (no personal data) cover adapters, pre-flight detection, thread-rename merging, and the themes system — every real bug caught during development now has a test that would have caught it sooner. Run with `pip install -r requirements-dev.txt && python -m pytest tests/`.
  - **Format-drift detection.** Each adapter now declares the fields it actually reads. An opt-in deep check samples an export's real conversations and flags fields it's never seen before — the same kind of change that once made a whole batch of ChatGPT projects vanish silently. Off by default (it has to read the full export, which isn't free on a large one); one click in Verification turns it on.
  - **A path autocomplete that doesn't truncate.** The browser's native path suggestions cut off long Windows paths with no way to see the rest. Replaced with a small dropdown that wraps instead of clipping.
  - **Collapsible pre-flight checks.** The exports folder check used to dump every file's status on screen at once. Now it's a single line — status light plus a one-line summary — that expands into the per-file list only when you want to look, and each file expands again into its full detail.
- **v2.6 rebuilt how images and generated content are stored**, after a routine check turned up a real classification bug:
  - **The bug**: ChatGPT's *newer* native image generation (the in-context "generate an image" flow, as opposed to the classic DALL·E tool call) doesn't fill in the field the pipeline was checking for a prompt. Result: **5,117 AI-generated images across a real 47-export history were being filed as user uploads.** Confirmed and fixed by checking for the generation ID instead of the prompt text.
  - **New taxonomy.** Assets are no longer dumped into one shared `IMAGE_BANK`. Each provider gets banks split by *what the content actually is*: `CHATGPT/GENERADAS` vs `CHATGPT/ADJUNTOS`, `GROK/GENERADAS_IMAGEN` / `GROK/GENERADAS_VIDEO` / `GROK/ADJUNTOS`, `CLAUDE/ARTEFACTOS/<type>` (markdown, html, code by language, and so on). Each bank has its own navigable index.
  - **Grok attachments and Imagine generations are now actually extracted** (previously just a text reference — see the provider table above). Imagine generations without a shipped binary (most of them, in practice: only ~18% of a real export's generations travel in the zip) are logged with their prompt and original link for manual download later, on purpose — this tool never reaches out to the network on your behalf.
  - **Claude Artifacts are now extracted**, resolved to their *final* state: an artifact revised a dozen times in one conversation used to be invisible; now it's one clean file, not a pile of near-duplicate revisions.
  - **A reusable relink tool** (`relink_assets.py`) rewrites asset links across the whole vault when a bank moves or gets renamed — this is the second time that's happened, and it won't be the last, so it's a proper tool now instead of a one-off script.
  - **A dormant bug in six different scripts**, found while running this exact migration: a leftover compatibility shortcut from an earlier reorganization could point nowhere (e.g. after clearing out the old shared image folder), and the file-scanning code used everywhere had no graceful way to handle that — it just stopped scanning entirely, mid-vault, with no explanation. Fixed once, centrally, and now covered by a test that reproduces the exact broken-shortcut scenario rather than trusting it won't happen again.
- **v2.7 replaced the old per-bank image indexes with one content index per provider**:
  - **One file per provider** (`_index_chatgpt.md`, `_index_claude.md`, `_index_grok.md`) instead of one per bank. Each bank inside is its own collapsed branch, and each conversation inside that branch collapses too — native Obsidian `<details>`, no plugins required.
  - **Grok's pending-download list lives in its own note** (`_grok_pendientes.md`), sorted newest first, kept separate from the main index so it doesn't clutter what's already downloaded.
  - **Claude's index shows a link and a short summary only** — never the artifact's full content inline, since that already lives in the artifact file and the conversation note.
  - **A bug caught in its own verification**: bank folders live next to `MERGED_VAULT`/`PRJ_VAULT` under the base vault, not inside them — a default that assumed otherwise silently produced empty captions and, for banks with no matching notes to scan (Grok's Imagine generations), an empty catalog despite real files on disk. Fixed with an explicit base-vault path, with a test that puts the two apart on purpose so the gap can't reopen unnoticed.
  - **The three old per-bank index files are now retired automatically** on every run, since the new provider index replaces them outright.

- **v2.8 retired `IMAGE_BANK` for good and gave the web UI a real identity**:
  - **The dashboard's asset card was quietly measuring an empty folder.** `IMAGE_BANK` had been fully migrated away in v2.6, but the stats code never stopped pointing at it — the card just read 0/0 B forever. Rebuilt to count the real banks (including Claude artifacts and Grok video, not just images), with a total plus a per-provider, per-type breakdown.
  - **`IMAGE_BANK` itself is gone**, not just unused: the junction mechanism that once linked it into every vault (`ensure_image_bank_junction`) is removed from the pipeline, and the three leftover junctions plus the empty folder were cleared from the live vault after confirming zero real notes still depended on them. The old standalone `image_index.py` tool it existed for is gone too, superseded by `content_index.py`.
  - **The interface got a name, not just a UI.** "Pipeline" and "Dashboard" were generic — the rest of the app talks about reconstructing memory from export files, and those two didn't. Renamed to **Observatory**, **Configuration**, **Verification**, **Construction**, **Cartography** (Observatorio, Configuración, Verificación, Construcción, Cartografía in the Spanish edition), each with its own header: a one-line "what you do here," a consistent brand line underneath, and a small illustrated mascot per section.
  - **A new tab, Reconnection, closes a real gap.** Regenerating indexes alone was never going to surface a manually downloaded Grok file — the catalog reads off the asset *manifest*, not the folder, so a file dropped in by hand with no manifest entry stayed invisible. Reconnection lists Grok's pending downloads, accepts the file by upload (never a hand-typed path — the server picks the bank and computes the same hash-based filename the automated extractor would), and a separate "Rebuild indexes" button reruns just the indexing step (`--reindex-only`) without a full reprocess.

Design principles throughout: diagnose before implementing, validate against real exports, never destroy data, and make failures loud and honest rather than silent.

---

## Roadmap

- Manual conversation↔project selector for residual cases (`manual:` namespace in gizmo_map, designed and deferred until the unassigned-conversations pile shrinks further)
- Asset extraction for the fragmented 2026+ ChatGPT export's `.dat` attachments (a separate binary layout from the one already handled)
- Distinguishing "never had a project" from "has a project nobody's named yet" in `Project_name` — both currently collapse to `none`
- **Localization phase 2 (`i18n-runtime`)**: translate CLI output, backend messages, live pipeline log, errors and warnings — the Spanish text still visible in this English edition. Extra care required: some backend messages are pattern-matched by tests and code, not just displayed.
- **Localization phase 3 (`i18n-content`)**: translate generated vault content (note metadata headers, index labels). Deferred until a compatibility strategy for existing Spanish vaults is decided (keep both formats, migrate, or generate per-language).
- A ChatGPT `image_group` tool-call type isn't recognized by the parser yet and leaks raw into note text — needs a real export sample to pin down the exact code path before fixing

---

## License

CC BY-NC-SA 4.0 — see badge above.
