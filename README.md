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

### MUSIC·0LOGY — a sister tool sharing the house

Suno sits apart from the four steps above, and deliberately so. It has **no export**: the only way to get your library out is to ask its API, signed in, with a token you copy from your browser and that expires within minutes. M3M0R·IA's pipeline never reaches out to the internet on its own — so Suno gets its own tab, its own pipeline, and its own manual step, rather than being bent into a provider it isn't.

What it does: downloads your library (audio, cover art and metadata), verifies the backup is intact, and builds a separate Obsidian vault with one note per track — including the **real lineage** between covers, remixes and mashups, resolved as links. Trees of 60+ variants are normal; Dewey-decimal codes keep them navigable, and the `Full Song` badge marks which one is the finished version.

It also surfaces in the Observatory: tracks, total duration, favorites, finished songs and projects.

The rule that governs it is worth stating precisely, because the short version ("the pipeline never makes outbound requests") would forbid this and shouldn't: **the app never reaches out on its own initiative — it reaches out when you hand it a token and press the button.** See [the token guide](#the-suno-token-or-the-key-to-your-own-house) if any of that sounds like cryptography.

### Inkwell — the archive of what you published

Substack **does have an export**, unlike Suno: a ZIP you download from the dashboard. So the obstacle here wasn't acquisition, it was the model — **a post is not a conversation**. Before Inkwell existed, that ZIP went through the four steps and came out as fake dialogue: all 109 posts were read as *one* conversation of 108 messages alternating "user" and "assistant" with the paragraphs of a single article, and the other 108 posts vanished without a sound. Now the pipeline recognizes it and **rejects it out loud**, and Inkwell picks it up through its own door. One input folder, two different doors.

What it does: turns each post into an Obsidian note with the body in Markdown, and tells apart **published, retired and draft** — because a draft with a date and metrics isn't a draft, it's something you published and later took down. If you hand it the stats CSV you download separately, it also recovers two things the export does **not** carry: each post's **section** and **tags**, which are what make the graph sort itself out.

```bash
python substack/build_substack_vault.py --exports-dir "YOUR_EXPORTS_FOLDER" --vault-dir "YOUR_INKWELL_VAULT" --stats "path/to/email_stats_YYYY-MM-DD.csv"
```

Metrics are **dated** inside the note, not left loose: a `views: 55` with no date lies with total confidence six months later. Each new CSV overwrites the snapshot; the history lives in the files themselves, which already carry the date in their names.

Two absences worth knowing up front, because they belong to the export and not to the tool: **comments don't travel** (none of them) and **neither do images** — only their remote URLs, which the note keeps.

And one warning the tool gives you by itself: the Substack ZIP drags along **your subscribers' personal data** — emails, and in the opens also country, city and device. Inkwell counts them so it can tell you out loud, and **never reads them**. They aren't your memory: they're other people's data in your care.

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

## The Suno token, or the key to your own house

Token, F12, headers? This section is for you. No programming needed: it's copying a long piece of text from one screen to another. The odd part is where it's hidden.

### Why this step is manual

The other providers give you an "export my data" button and a ZIP. **Suno doesn't.** Your library can only be asked for through its API, and the API wants proof that you're you.

That proof is the **token**: a temporary pass your browser has held since you signed in. It lives a few minutes and expires on its own. There's nothing to store, no credentials to put in a config file — which is why the step isn't automated, and why you do it yourself each time.

Worth saying plainly: **while it lasts, that token stands in for you.** Whoever holds it can ask Suno for the same things you can. Don't paste it anywhere that isn't this app, don't send it over chat, and don't publish it in a screenshot. It expires fast, which is the good news.

M3M0R·IA treats it accordingly: it travels in the request body and not in the address bar, it's handed to the process through its environment and not on the command line, it's redacted from the log before it reaches your screen, and it isn't stored anywhere. It leaves with you when you close the tab.

### Getting it, step by step

**1. Open your library on Suno.**
Go to [suno.com](https://suno.com) signed in, to the screen where you see your songs.

**2. Open the developer tools.**
Press `F12`. If your keyboard has an `Fn` key, it may be `Fn`+`F12`. A panel opens, at the side or the bottom, full of tabs: it's the console every browser ships with. Looking around breaks nothing.

**3. Go to the «Network» tab.**
Some browsers call it «Net». It will be empty: it only records what happens *while* it's open. So **refresh the page** (`F5`) without closing the panel. A list fills up — each line is one request your browser makes to Suno.

**4. Search with the magnifying glass.**
That same tab has a **magnifier** icon. Open it and type `bearer`. This search looks *inside* the requests, not just at their names, which is exactly what you need: the token is inside. It will flag the lines carrying it.

**5. Switch to the «Headers» view.**
Click one of the results. A detail panel opens with its own tabs: **Headers**, Payload, Response... **You have to be on Headers.** The token doesn't appear in the other views, and this is where most people get stuck.

**6. Copy the token.**
Find the line `Authorization: Bearer eyJ...` and copy **only what comes after the word «Bearer»**: a very long string of letters and numbers starting with `eyJ`. Without the word «Bearer», without quotes, without leading spaces.

**7. Paste it into the MUSIC·0LOGY tab** and press "Download library".

### If something doesn't add up

- **I can't find any line with `Authorization`.** Refresh the page with the panel open. If the list is still empty, check you're on Network and not on Console.
- **I pasted it and it says it's invalid.** You may have copied the word «Bearer» along with it, or a space. You may also have picked a request to `clerk.suno.com`: those carry a token but won't work. The good ones go to `studio-api`.
- **The download stopped halfway.** Almost always the token expiring. Get a fresh one by repeating these steps and launch it again: it **resumes where it left off**, it doesn't start over.
- **I've forgotten all of this.** It's inside the app too: in the MUSIC·0LOGY tab, the fold labelled «Does this sound like cryptography? Open me».

---

## Configuration

- `memoria_config.yaml` — your paths (base vault, exports folder, gizmo map) and options (by-year/by-month folders, index generation). Created from `memoria_config.yaml.example`; never committed.
- `gizmo_map.json` — maps ChatGPT project (gizmo) IDs to human names. Curated from the web UI (Cartography tab); never committed.
- `topic_map.json` — your themes for unassigned conversations: `{"theme": ["words", "phrases", "field=value"]}`. Curated from the UI; generates linked index notes in `MERGED_VAULT/_Topics`. Never committed.
- `suno_backup` and `suno_vault` (in `memoria_config.yaml`) — MUSIC·0LOGY's two paths: where the raw Suno backup lives, and where its Obsidian vault is built. Both optional: without `suno_backup` the Observatory card simply doesn't appear — it isn't drawn as zero, because claiming "0 tracks" about a library you never downloaded is a lie, not information.

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
  - **New taxonomy.** Assets are no longer dumped into one shared `IMAGE_BANK`. Each provider gets banks split by *what the content actually is*: `CHATGPT/GENERATED` vs `CHATGPT/ATTACHMENTS`, `GROK/GENERATED_IMAGE` / `GROK/GENERATED_VIDEO` / `GROK/ATTACHMENTS`, `CLAUDE/ARTIFACTS/<type>` (markdown, html, code by language, and so on). Each bank has its own navigable index.
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

- **v2.9 finished the English edition and, in doing so, uncovered two silent bugs**:
  - **Everything is now English**: the web UI, every message the app prints, and the content it writes into your vault — note metadata lines, index labels, and the folder names on disk. The riskiest part was not the translating: four of those lines are *parsed back* by the app (the attachment index reads "Attached file:", the Claude index reads "Artifact:", the topic-note cleanup reads its own `generated_by:` marker). Translate one side without the other and things break with no error, no exception and no failing test. Each pair moved in a single commit, and a new round-trip test suite now starts from the real renderer output rather than hand-copied literals, so a one-sided change shows up.
  - **The asset relinker only ever rewrote image links.** Written back when the asset banks held nothing but images, its pattern matched `![](path)` and nothing else. Claude artifacts — which always use `[text](path)` — arrived later and left it quietly insufficient: moving that bank would have left every artifact link pointing at the old folder. Measured against a real 1641-note vault, it rewrote 0 of 32 links. Fixed in both editions.
  - **Every artifact link in the Claude index was dead.** The index builder stripped the filename from its path and then rebuilt the link without the type subfolder, so all 16 artifacts pointed at files that do not exist — clicking one in Obsidian did nothing. It had been that way since artifacts existed. No test caught it because every test checked the generated markdown, never whether the paths inside it resolve on disk. Fixed in both editions, with a test that walks each link to the filesystem.
  - **Upgrading an existing vault is one click.** See "Language editions" above: Reconnection detects the old Spanish layout, renames the folders and reconnects every asset link, without deleting anything or disturbing your download triage.

- **v2.10 brought a sister tool into the house: MUSIC·0LOGY.** Suno had lived in a separate repo, because it looked like it didn't fit — M3M0R·IA assumes conversations, and a track is a generation event with parent→child lineage. That reasoning was half right: it judged step 1. The decisive obstacle turned out to be different. M3M0R·IA eats files sitting in a folder; Suno has no export at all, only an authenticated API. So it was integrated **at the interface, not in the pipeline**: its own tab, its own pipeline, its own manual step. The product rule survives, stated more precisely — the app never reaches out on its own initiative, it reaches out when you hand it a token and press the button. The library also shows up in the Observatory, and there's a step-by-step guide for anyone who has never opened DevTools.

Design principles throughout: diagnose before implementing, validate against real exports, never destroy data, and make failures loud and honest rather than silent.

---

## Roadmap

- Manual conversation↔project selector for residual cases (`manual:` namespace in gizmo_map, designed and deferred until the unassigned-conversations pile shrinks further)
- Asset extraction for the fragmented 2026+ ChatGPT export's `.dat` attachments (a separate binary layout from the one already handled)
- Distinguishing "never had a project" from "has a project nobody's named yet" in `Project_name` — both currently collapse to `none`

---

## License

CC BY-NC-SA 4.0 — see badge above.
