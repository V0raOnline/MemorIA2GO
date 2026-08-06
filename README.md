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

## ⚠️ You've landed on the archive

**This branch is frozen.** `main` holds v2.8.0, the last state the two language editions shared, kept as an immutable reference. It doesn't have Inkwell, or MUSIC·0LOGY, or half of what's described below.

**The living project is in the release branches. Pick your language:**

| | |
|---|---|
| 🇬🇧 **[release/en](../../tree/release/en)** | English edition — interface, runtime messages and vault content, all in English |
| 🇪🇸 **[release/es](../../tree/release/es)** | Edición española — interfaz, mensajes de ejecución y contenido del vault, todo en español |

Both are complete and equivalent. Fixes land on `release/es` first and are carried over to `release/en`, so the two lines stay in step. Clone the branch, not this one:

```bash
git clone -b release/en https://github.com/V0raOnline/MemorIA2GO.git
```

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

Everything runs on your machine. The app never reaches out on its own initiative — it reaches out when you hand it a token and press the button.

---

## Where to read on

The documentation lives on the release branches, split so that each document answers **one** question:

| | Answers | |
|---|---|---|
| **README** | What is it and how do I start it? | [en](../../blob/release/en/README.md) · [es](../../blob/release/es/README.md) |
| **ARCHITECTURE** | How does it work inside and why this way? | [en](../../blob/release/en/ARCHITECTURE.md) · [es](../../blob/release/es/ARCHITECTURE.md) |
| **I'm stuck** | What if I don't know any of this? | [en](../../blob/release/en/IM_STUCK.md) · [es](../../blob/release/es/ME_HE_ATASCADO.md) |
| **DEVLOG** | What did we learn building it? | [en](../../blob/release/en/DEVLOG.md) · [es](../../blob/release/es/DEVLOG.md) |

---

## License

CC BY-NC-SA 4.0 — see badge above.
