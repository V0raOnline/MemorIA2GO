# Architecture

> **What question does this document answer?**
> *How does it work inside, and why this way and not another?*

To install and run it, go to the [README](README.md). This is for whoever wants to understand the design.

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

## The sister tools

## MUSIC·0LOGY — a sister tool sharing the house

Suno sits apart from the four steps above, and deliberately so. It has **no export**: the only way to get your library out is to ask its API, signed in, with a token you copy from your browser and that expires within minutes. M3M0R·IA's pipeline never reaches out to the internet on its own — so Suno gets its own tab, its own pipeline, and its own manual step, rather than being bent into a provider it isn't.

What it does: downloads your library (audio, cover art and metadata), verifies the backup is intact, and builds a separate Obsidian vault with one note per track — including the **real lineage** between covers, remixes and mashups, resolved as links. Trees of 60+ variants are normal; Dewey-decimal codes keep them navigable, and the `Full Song` badge marks which one is the finished version.

It also surfaces in the Observatory: tracks, total duration, favorites, finished songs and projects.

The rule that governs it is worth stating precisely, because the short version ("the pipeline never makes outbound requests") would forbid this and shouldn't: **the app never reaches out on its own initiative — it reaches out when you hand it a token and press the button.** See [the token guide](IM_STUCK.md) if any of that sounds like cryptography.

## Inkwell — the archive of what you published

Substack **does have an export**, unlike Suno: a ZIP you download from the dashboard. So the obstacle here wasn't acquisition, it was the model — **a post is not a conversation**. Before Inkwell existed, that ZIP went through the four steps and came out as fake dialogue: all 109 posts were read as *one* conversation of 108 messages alternating "user" and "assistant" with the paragraphs of a single article, and the other 108 posts vanished without a sound. Now the pipeline recognizes it and **rejects it out loud**, and Inkwell picks it up through its own door. One input folder, two different doors.

What it does: turns each post into an Obsidian note with the body in Markdown, and tells apart **published, retired and draft** — because a draft with a date and metrics isn't a draft, it's something you published and later took down. If you hand it the stats CSV you download separately, it also recovers two things the export does **not** carry: each post's **section** and **tags**, which are what make the graph sort itself out.

It has its own tab, with two steps: **verify** — what the export brings, how much the CSV matches, how many subscriber CSV files are ignored and, above all, **what doesn't come** — and **build**. It also surfaces in the Observatory with posts, words, published and drafts: all four figures come from the ZIP, so the card is complete even if you never downloaded the CSV, and when there's no export it isn't painted at all rather than lying with zeros.

And from the terminal, if you'd rather:

```bash
python substack/build_substack_vault.py --exports-dir "YOUR_EXPORTS_FOLDER" --vault-dir "YOUR_INKWELL_VAULT" --stats "path/to/email_stats_YYYY-MM-DD.csv"
```

Metrics are **dated** inside the note, not left loose: a `views: 55` with no date lies with total confidence six months later. Each new CSV overwrites the snapshot; the history lives in the files themselves, which already carry the date in their names.

The vault is built with two indexes of its own: `_index.md`, with the figures and the archive in reverse chronology by year and month, plus separate blocks for retired posts and drafts; and `_sections.md`, with your taxonomy. That second one **only exists if you handed it the CSV** — without it, no "unclassified" bucket gets invented, because that would paint as data what is really a source you didn't download.

One detail you'll notice looking at the vault: tags are normalized as they're written (`bitácora glitch` → `bitácora-glitch`). Obsidian doesn't allow spaces inside a tag and, without that change, they sit in the file but dead — no tag pane, no graph. Accents are kept.

Two absences worth knowing up front, because they belong to the export and not to the tool: **comments don't travel** (none of them) and **neither do images** — only their remote URLs, which the note keeps.

And one warning the tool gives you by itself: the Substack ZIP drags along **your subscribers' personal data** — emails, and in the opens also country, city and device. Inkwell counts them so it can tell you out loud, and **never reads them**. They aren't your memory: they're other people's data in your care.

---

*Design decisions with their reasoning and the alternatives dropped along the way live in [DEVLOG.md](DEVLOG.md).*
