# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> Turn your AI conversation history — ChatGPT, Claude, Grok — into a structured, MCP-ready Obsidian vault. Your context, local and yours.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## What is M3M0R·IA?

M3M0R·IA converts the native exports of your AI chat providers into a clean, project-organized vault of Markdown notes, ready to be browsed in Obsidian and consumed as live context by Claude Desktop via MCP (Model Context Protocol).

Unlike generic migration tools that only transfer saved memories, M3M0R·IA brings your **full conversation history** — deduplicated, merged, organized by project and date, with images extracted and navigation indexes generated.

**Supported providers** (detected by internal JSON structure, never by filename):

| Provider | Export format | Branch handling | Attachments |
|----------|--------------|-----------------|-------------|
| ChatGPT  | zip / json / html | `current_node` tree walk | text inline, images extracted to IMAGE_BANK |
| Claude   | zip (may arrive in `batch-NNNN` parts) | most-recent-leaf reconstruction (no current_node in export) | extracted text quoted inline; binaries not shipped by the export |
| Grok     | zip (`ttl/30d/...` layout) | `leaf_response_id` when present, most-recent-leaf otherwise | referenced by asset id (binary extraction planned) |

All providers coexist in a single MERGED vault. Every note carries `provider` and `source` in its frontmatter, so you can filter, color and index by origin.

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
- **Generate themes index** (Cartografía tab) — whenever you edit themes; no restart needed. Step 4 also regenerates it automatically on every pipeline run.

---

## Requirements

- Python **3.10+**
- Dependencies: `pip install -r requirements.txt`
  (beautifulsoup4, lxml, rich, pyyaml, flask)
- Obsidian (to browse the result) and optionally Claude Desktop with an MCP filesystem server (to use it as live context)

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

Your browser opens with the interface. From here on, everything is clicks: **Configuración** tab to review paths, **Verificación** to check your ZIPs are recognized, and **Pipeline** → "Importar pendientes" to run the conversion. The live log tells you what it's doing. When it finishes, open your vault folder with Obsidian and enjoy.

**If something fails:**
- *"python is not recognized as a command..."* → the PATH checkbox from step 1 wasn't ticked. Reinstall Python with it checked, close the console and open a new one.
- *"pip is not recognized..."* → same as above.
- The browser window doesn't open → manually type `http://127.0.0.1:8765` in your browser.

---

## Configuration

- `memoria_config.yaml` — your paths (base vault, exports folder, gizmo map) and options (by-year/by-month folders, index generation). Created from `memoria_config.yaml.example`; never committed.
- `gizmo_map.json` — maps ChatGPT project (gizmo) IDs to human names. Curated from the web UI (Cartografía tab); never committed.
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

Design principles throughout: diagnose before implementing, validate against real exports, never destroy data, and make failures loud and honest rather than silent.

---

## Roadmap

- Manual conversation↔project selector for residual cases (`manual:` namespace in gizmo_map, designed and deferred)
- Grok asset extraction to IMAGE_BANK (binaries do ship in its export)
- Fixture-based regression tests per provider
- `model` field in frontmatter where the export records it (Grok, ChatGPT)

---

## License

CC BY-NC-SA 4.0 — see badge above.
