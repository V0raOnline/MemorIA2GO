# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> **Memory doesn't live in one place any more.**
>
> It's scattered across the conversations where we thought out loud, the pieces we published, the music we made — on servers that aren't ours, that can shut down, change hands, or quietly stop keeping it.
>
> **M3M0R·IA brings it back.** To your disk, in Markdown, yours.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## What is M3M0R·IA?

It isn't just an export converter. It's the place where the knowledge and the things you made come back together after being left scattered.

Three **tools sharing one house**, with deliberately separate pipelines: a conversation, an article and a song are not the same thing, and treating them alike ruins all three.

The pact is the same for all three: **nothing is lost.** Nothing is ever deleted, the originals outrank anything generated from them, and whatever the tool can't read it says out loud instead of making it up.

| What you have out there | From | Where it lands |
|---|---|---|
| **Your conversations** | ChatGPT · Claude · Grok | a browsable Obsidian vault, organized by project and date, ready to serve as context over MCP or to trace connections |
| **What you published** | Substack | **Inkwell** — your editorial archive, telling published, retired and draft apart |
| **What you composed** | Suno · Flow Music | **MUSIC·0LOGY** — with the lineage between versions, covers and remixes resolved as links |

You don't have to use them all. Each one works on its own, and the ones you don't configure never show up.

Unlike generic migration tools that only transfer saved memories, M3M0R·IA brings **the full history**: deduplicated, merged, with images and attachments extracted to their own banks, and navigation indexes generated. Providers are recognized by the internal structure of their export, never by filename.

The conversations from all three providers live together in a single merged vault; every note carries `provider` and `source` in its frontmatter, so you can filter, colour and index by origin, and follow a whole line of thinking end to end. Inkwell and MUSIC·0LOGY build vaults of their own: it made no sense to treat an editorial archive the same as a music library.

Want to know how each flow works inside, what each adapter does, and why the sister tools aren't "just another provider"? It's all in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Language editions

M3M0R·IA is maintained as two parallel product lines, one per language. Both are complete and equivalent — the localization effort finished with the `i18n-content` milestone:

- **`release/en` (this branch) — English edition.** Fully localized: the web UI (`i18n-web`), everything the app prints while running (`i18n-runtime`), and the content it writes into your vault — note metadata lines, index labels and the folder names on disk (`Conversations`, `GENERATED`, `ATTACHMENTS`, `ARTIFACTS`, `_Topics`…), tags `i18n-content` phases 3a and 3b.

  **Upgrading a vault built with an earlier English release?** Those vaults have Spanish folder names, and reprocessing alone will not fix them — the pipeline never deletes, so it would write the English tree *beside* the Spanish one and leave every note duplicated in Obsidian's search and graph. Open the **Reconnection** tab: if the old layout is detected, a "Vault layout" card appears with a one-click rename that also reconnects every asset link inside your notes. Nothing is deleted, and your download triage and import history are left untouched. Reprocess afterwards to rewrite the note *content* in English.
- **`release/es` — Spanish edition.** The original, fully functional application. Receives bug fixes during the localization effort.
- **`main`** is frozen at the last common state (v2.8.0) as an immutable reference. Bug fixes land on `release/es` first and are cherry-picked to `release/en`, so both lines stay in step.

---

## Requirements

**If you use the Windows package, none.** It carries its own Python inside.

- **Obsidian**, to browse the result. And optionally Claude Desktop with an MCP filesystem server, if you want your vault as live context.

If you'd rather run it from the source, then yes: Python **3.10+** and `pip install -r requirements.txt` (beautifulsoup4, lxml, rich, pyyaml, flask, requests). For the test suite, `pip install -r requirements-dev.txt && python -m pytest tests/`.

Developed and battle-tested on Windows; the pipeline itself is cross-platform.

---

## Quick start (web UI)

M3M0R·IA ships with a local web interface of seven sections: Observatory, Configuration, Verification, Construction, Cartography and Reconnection for the conversations, plus MUSIC·0LOGY and Inkwell as tools with a life of their own, inside the same house.

### Step 0: get your material

This starts **outside** the tool, and it's the one thing it can't do for you. You only need to bring the sources you're actually going to use:

| Where from | How to get it |
|---|---|
| **ChatGPT** | Settings → Data controls → Export data. A ZIP arrives by email |
| **Claude** | Settings → Privacy → Export data. Arrives by email, sometimes as several ZIPs |
| **Grok** | Settings → Data → Download your data |
| **Substack** | Dashboard → Settings → Import/Export |
| **Substack**, stats *(optional)* | Dashboard → Stats → Posts → Show, **ticking every column**, then download the CSV |
| **Suno · Flow Music** | There's no export: the library is downloaded from inside the tool through their API, with a token you copy from your browser — see **[IM_STUCK.md](IM_STUCK.md)** |

The ZIPs go in **exactly as they are, without unzipping**, into whatever folder you set as `exports_dir`. The Substack one goes into that same folder: the conversation pipeline recognizes it and turns it away, and Inkwell picks it up from there. One folder, two doors.

**Don't delete the zips** — we're always finding new things to pull out of them, and if you keep them you'll be able to reprocess and grow your m3m0rIA later.

The stats CSV is optional, but it's the only source carrying each post's **section** and **tags** — without it Inkwell still builds a working vault, just with no taxonomy. **You have to tick every column when you request it:** downloaded with the defaults, those two fields don't travel.

### Installation — the Windows package

**If you've never opened a console in your life, this is your path.** Download
the zip, unpack it wherever you like, and double-click **`M3M0R-IA.bat`**.
That's it: your browser opens with M3M0R·IA inside.

> **One step before unpacking, and it saves you a scare.** Windows marks
> everything that arrives from the internet. **Right-click the zip →
> Properties →** tick **Unblock → OK**, and then unpack it.
>
> Nothing bad happens if you skip it, but the mark gets copied onto all two
> thousand-odd files inside, and clicking the `.bat` will make Windows warn
> you that it can't verify who created this file. That's true: the package
> isn't signed, signing costs money, and this is free software. Unblocking
> the zip first avoids that screen entirely.

It carries its own Python, so it **installs nothing on your system** — it
can't break anything you already had working, it doesn't ask for admin
rights, and it uninstalls by dragging the folder to the bin. On first launch
a shortcut with an icon appears beside it, so you can pin it or move it to
your desktop.

The first screen will tell you the base folder isn't configured yet. That's
done in the **Configuration** tab, with a path browser; no file to edit by
hand.

### Installation — from the source

For anyone who's going to work on it, or isn't on Windows:

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

#### Pretty URL (optional)

If typing the address with the port gets old, add this line to your hosts file (Windows: `C:\Windows\System32\drivers\etc\hosts`; Linux/macOS: `/etc/hosts`, with `sudo`):

```
127.0.0.1  m3m0ria
```

And start it on port 80:

```bash
python launcher.py --port 80 --no-browser
```

Now you can get in by typing `http://m3m0ria/`. The `--no-browser` is there because in this mode you normally leave it running in the background: on Windows, with a logon Scheduled Task launching `pythonw launcher.py --port 80 --no-browser`; on Linux, with a systemd user service. Careful: on Linux port 80 needs privileges — stay on 8765 or put a proxy in front.

First dashboard load computes statistics once and caches them next to your vault (`.m3m0ria_stats.json`); after that, loads are instant. The pipeline refreshes the cache at the end of step 4, and the dashboard offers a manual *recalcular* link.

### Building the package (only if you maintain this)

```bash
python installer/build.py
```

It downloads the embedded Python from python.org and checks **its published MD5 and a pinned SHA-256** before unpacking it: whatever goes in there ends up running on somebody else's computer. Before zipping, it sweeps the result
and refuses if it finds paths belonging to the machine that built it — a
package with absolute paths inside starts nowhere else, and that already
happened once.

There are two test benches for what only fails on a fresh install:

```bash
python installer/prueba_instalacion_nueva.py   # the API across the 4 startup states
python installer/prueba_botones.py             # every POST with empty and broken bodies
```

### CLI (no web)

You can run everything from a terminal. No web server.

```bash
python MemorIA2GO.py                  # interactive, full pipeline
python MemorIA2GO.py --reprocess-all  # re-parse every valid export from scratch
```

---

> ### Are you stuck?
>
> If you've never used a terminal, or you don't know what a token is, keep reading here: **[IM_STUCK.md](IM_STUCK.md)** tells it from scratch, taking nothing for granted.

## Configuration

- `memoria_config.yaml` — your paths (base vault, exports folder, gizmo map) and options (by-year/by-month folders, index generation). Created from `memoria_config.yaml.example`; never committed.
- `gizmo_map.json` — maps ChatGPT project (gizmo) IDs to human names. Curated from the web UI (Cartography tab); never committed.
- `topic_map.json` — your themes for unassigned conversations: `{"theme": ["words", "phrases", "field=value"]}`. Curated from the UI; generates linked index notes in `MERGED_VAULT/_Topics`. Never committed.
- `substack_vault` (in `memoria_config.yaml`) — where the Inkwell vault gets built. It's the **only** path it needs: the Substack export and its stats CSV live in your usual exports folder, because the conversation pipeline rejects them and Inkwell picks them up from there. One folder, two doors.
- `suno_backup` / `suno_vault` and `flowmusic_backup` / `flowmusic_vault` (in `memoria_config.yaml`) — MUSIC·0LOGY's paths, one pair per source: where the raw backup lives, and where its Obsidian vault is built. All four optional and independent: use one source, both, or neither. With no backup path configured, that source's Observatory card simply doesn't appear — it isn't drawn as zero, because claiming "0 tracks" about a library you never downloaded is a lie, not information.

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
