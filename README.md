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

### ⬇ **[Download M3M0R·IA for Windows](https://github.com/V0raOnline/MemorIA2GO/releases/download/v2.12.1-en/M3M0R-IA-2.12.1-en.zip)** · 21 MB

Unpack it and double-click. **No programming, nothing installed** — it carries
its own Python inside. The details are under *Installation — the Windows
package*, further down; the history is in
**[Releases](https://github.com/V0raOnline/MemorIA2GO/releases)**.

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

### New — Claude export format (2026-09+)

Anthropic quietly changed the Claude export format in September 2026:
it's no longer a single ZIP holding `conversations.json` +
`users.json` + `projects.json`, but a **JSON manifest + five
single-use ZIPs**, one per category: `light_metadata`, `projects`,
`memories`, `frames` and `conversations`. No changelog entry, no
notice on the help center; the only public signal is a [third-party
issue](https://github.com/ukogan/claude-migration-assistant/issues/4)
from people caught off guard by the change.

M3M0R·IA recognizes the new format and takes advantage of what it
brings that the old one didn't:

- **`memories`** → a new vault `Claude_Mem/` (sibling of MERGED_VAULT
  and PRJ_VAULT). Holds the personal dossier Claude has built about
  you, the per-project textual summaries, and the **persistent memory
  notes** Claude uses internally — 71 files with a hierarchical
  structure `/areas /people /projects /topics /profile.md` preserved
  as-is, because the structure IS information.
- **`frames`** (the artifacts) → `MERGED_VAULT/CLAUDE_WEB/FRAMES/`
  with **version history and comments**. The old export lost the
  intermediate revisions; the new one carries every version with its
  timestamp, description and full HTML, and M3M0R·IA copies them
  verbatim next to an index note that also rescues the comment
  threads.
- **`projects`** → a per-project index note in `PRJ_VAULT/<name>/`
  with `description`, `prompt_template` (the project's system
  prompt), metadata, and `_docs/` for the inline project knowledge
  you uploaded.
- **`conversations`** → internal shape identical to the old export,
  same adapter. Conversations that also appeared in an earlier export
  **are not duplicated**: `vault_merge` groups them by `conv_id` and
  fuses whatever's new in the thread. Only the packaging changed.

Ingest is done from the decompressed folder (the five ZIPs can sit
loose in `exports_dir` or inside a sibling folder). The JSON manifest
is recognized but not imported on its own — it's just an index.
`light_metadata` is preserved but not ingested (account metadata, no
vault value).

Rather see it working before installing anything? **[Test de recuperación de extracto conversacional](https://v0raonline.substack.com/p/test-de-recuperacion-de-extracto)** *(in Spanish)* — a walkthrough with screenshots, written up as a clinical report by an institution that studies biological organisms and their inability to find their own conversations.

And **don't forget to collect your diploma** once you complete your first successful extraction. It goes on record.

Want to know how each flow works inside, what each adapter does, and why the sister tools aren't "just another provider"? It's all in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### Refresh visual — paleta warm (2026-09)

La interfaz web ha pasado de un dark cool con acento magenta ("IDE
oscuro") a un dark warm con acentos en ámbar y rosa palo — el registro
que buscabas cuando abrías el vault por la tarde con un café al lado.
Los roles cromáticos se han separado:

- **Ámbar `#e99641`** hace todo lo estructural: pestaña activa,
  cabecera de sección, botón primario, borde de foco, línea del chart.
- **Magenta `#FC4FB1`** se reserva a la identidad — el wordmark
  `M3M0R·IA` y sus repeticiones. Aparece poco, y por eso pesa.
- **Rosa palo `#c47c9a`** cubre los indicadores y enlaces (stats,
  hovers, links) — misma familia magenta que la marca pero un stop
  más apagado, así el wordmark sigue siendo el punto más saturado de
  la pantalla.
- Neutros stone (`#171717` fondo, `#2e2c29` panel, `#1f1c1b` fila
  interna) leen como papel oscuro/archivo en vez de terminal.

El pipeline no cambia: es solo `web/style.css`. Si prefieres la paleta
anterior, el commit está atrás en el historial (`git show
release/es~N -- web/style.css`).

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
| **Claude** | Settings → Privacy → Export data. Arrives by email. Since 2026-09 the new export is **five single-use ZIPs** (`conversations`, `projects`, `memories`, `frames`, `light_metadata`) described by a JSON manifest — download all of them to the exports folder; the old format (a single ZIP) still works. See the *New* section above |
| **Grok** | Settings → Data → Download your data. The export includes conversations and part of your Imagine generations; some arrive only as a link and M3M0R·IA downloads them separately with the pending-downloads tool (Reconnection tab) |
| **Substack** | Dashboard → Settings → Import/Export |
| **Substack**, stats *(optional)* | Dashboard → Stats → Posts → Show, **ticking every column**, then download the CSV |
| **Suno · Flow Music** | There's no export: the library is downloaded from inside the tool through their API, with a token you copy from your browser — see **[IM_STUCK.md](IM_STUCK.md)** |
| **Claude Code · Codex** *(sessions)* | Nothing to bring: your agent sessions already live on your disk (`~/.claude/projects`, `~/.codex/sessions`) and no account export includes them. They're ingested straight from the Reconnection tab |

The ZIPs go in **exactly as they are, without unzipping**, into whatever folder you set as `exports_dir`. The Substack one goes into that same folder: the conversation pipeline recognizes it and turns it away, and Inkwell picks it up from there. One folder, two doors.

**Don't delete the zips.** They're the original source and the only complete copy of what each platform gave you: we're always finding new ways to pull more out of them, so keeping them lets you reprocess and grow your m3m0rIA as the tool learns to read more. And if you update M3M0R·IA, having the zips lets you rebuild the vault from scratch with the new version, without depending on what got written with the old one.

The stats CSV is optional, but it's the only source carrying each post's **section** and **tags** — without it Inkwell still builds a working vault, just with no taxonomy. **You have to tick every column when you request it:** downloaded with the defaults, those two fields don't travel.

### Installation — the Windows package

**If you've never opened a console in your life, this is your path.** Download
**[`M3M0R-IA-2.12.1-en.zip`](https://github.com/V0raOnline/MemorIA2GO/releases/download/v2.12.1-en/M3M0R-IA-2.12.1-en.zip)**
(21 MB), unpack it wherever you like, and double-click **`M3M0R-IA.bat`**.
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

Claude and Grok exports do not link conversations to projects: those notes are organized by themes (many-to-many), not folders. **Claude does bring projects as first-class entities from the new format** (2026-09+): each project has its folder in `PRJ_VAULT/<name>/` with metadata and project knowledge, though the conversations themselves still can't be linked to them automatically for lack of a bridge in the export.

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

- **Imagine (Grok) library as a sibling tool**, in the style of MUSIC·0LOGY: bringing in the generations the export leaves out, straight from your library, with the lineage between an image and its edits resolved as links. Already works for personal use; pending UI integration.
- Manual conversation↔project selector for residual cases (`manual:` namespace in gizmo_map, designed and deferred until the unassigned-conversations pile shrinks further)
- Asset extraction for the fragmented 2026+ ChatGPT export's `.dat` attachments (a separate binary layout from the one already handled)
- Distinguishing "never had a project" from "has a project nobody's named yet" in `Project_name` — both currently collapse to `none`

---

## License

CC BY-NC-SA 4.0 — see badge above.
