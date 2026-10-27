# Vault layout

> **What question does this document answer?**
> *How are my vault's folders organized, what can I change, and why does M3M0R·IA sometimes refuse to continue?*

To install and launch it, go to the [README](README.md). For the overall design, [ARCHITECTURE.md](ARCHITECTURE.md). This is only about how the folders are laid out.

What this document says is watched by a test: `tests/test_organizar_vault_documentado.py`. If the code changes and the document doesn't, the test fails.

---

## In one sentence

You can choose how the merged vault is organized (all together, all together with a project vault, or one folder per provider) and where the raw source (`RAW_VAULT`) lives. M3M0R·IA **refuses to continue** rather than leave you a vault split in two without a word.

## The three organizations

They are chosen in **Settings → Organization of the merged vault** (in `memoria_config.yaml`, `options.layout_preset`).

| Organization | In the settings | Merged conversations | Project vault |
|---|---|---|---|
| **All together + projects** (default) | `proyectos` | all in `MERGED_VAULT/Conversations` | yes, `PRJ_VAULT`, one folder per project |
| **All together** | `unico` | all in `MERGED_VAULT/Conversations` | no |
| **One folder per provider** | `proveedor` | `MERGED_VAULT/ChatGPT/Conversations`, `MERGED_VAULT/Claude/Conversations`… | no |

"All together + projects" is what M3M0R·IA always did. A vault built before this option existed is of this kind.

With **one folder per provider**:
- Each note goes to the folder of its `provider` field. Claude Code sessions go with Claude and Codex sessions with ChatGPT, since Codex is OpenAI's. A provider M3M0R·IA doesn't know gets a folder with its own name instead of getting lost.
- Only the folders of providers that have notes are created. If you only import Claude, no empty `ChatGPT/` shows up.
- **Topics stay shared** (`MERGED_VAULT/_Topics`), because a topic cuts across providers.

**Without a project vault**, the projects from Claude's new export are not lost: they go to `MERGED_VAULT/CLAUDE_WEB/PROJECTS`, next to their artifacts (with one folder per provider, `MERGED_VAULT/Claude/CLAUDE_WEB/PROJECTS`).

**The raw source (`RAW_VAULT`) is never split.** Everything else comes from it, and the merge walks all of it every time.

## When you can change it and when you can't

A vault **with no merged conversations** can change organization freely. One that already has them:

| Change | Allowed? | Why |
|---|---|---|
| Between "all together" and "all together + projects" | yes | the project vault is a view that gets regenerated |
| …if Claude projects have already been written | **no** | those files are the only copy: writing new ones somewhere else would split them |
| From "all together" to "one folder per provider", or back | **no** | new notes would go to another folder and every conversation would show up twice |

When it isn't allowed, the option shows up **disabled in Settings, with the reason**, and if you set it by hand in `memoria_config.yaml` the pipeline **stops before writing anything**. Moving a vault that has notes from one organization to another needs a migration that **doesn't exist yet**.

## Where the raw source (`RAW_VAULT`) lives

By default, inside your base folder, as always. But it is the pipeline's raw material, not something meant to be opened in Obsidian, so you can take it to another folder or another drive (in the settings, `paths.raw_vault`).

**If you already have a vault, don't change the path by hand:** move it with

```
python mover_raw.py --hacia <folder>
```

- **It copies and verifies** every file: size, content (SHA-1) and modification date, which the merge uses as a tiebreaker.
- **It doesn't delete the original.** Once you've checked it, you delete it.
- With `--dry-run` it only counts and checks.
- If it gets interrupted, you can run it again: whatever is already copied and identical isn't copied again.
- It refuses a destination that already has unrelated files, that is inside the RAW, or that contains the vault.

When it's done, it tells you to set the new folder in Settings.

**The pipeline refuses to continue** if the settings say the RAW is in one place and the vault knows it's in another, or if the external source isn't there (a disconnected drive). Going ahead would write the new notes into an empty RAW and the merge wouldn't see the earlier ones, without any error.

## How it knows: the marker

The first time the pipeline works on a vault, it leaves a small file at its root, `.m3m0ria_layout.json`, with the organization and the folders it was built with. That way M3M0R·IA knows what your vault looks like without guessing from the folders that exist. The leading dot keeps Obsidian from showing it. Don't delete it or edit it by hand.

## What follows the organization

Everything that walks conversations reads the folders from the marker: the merge, the indexes, the Observatory statistics, Cartography, local sessions, **the image gallery and image recovery** (which also finds the notes of an external RAW, and puts them back where they were when undoing).

## Coming from the Spanish edition

A vault built with the Spanish edition uses Spanish folder names (`Conversaciones`, `_Temas`, `CHATGPT/GENERADAS`…). `layout_migration.py` renames them to this edition's names and rewrites the links in your notes. It works out what to rename by comparing the two editions' tables, so it also covers the Claude Code and Codex session folders.

## What it doesn't do

- **It doesn't migrate a vault that has notes from one organization to another.** That's on the roadmap.
- **It doesn't make the RAW optional.** The merge isn't incremental: it regroups every variant of each conversation from the RAW every time, and the RAW keeps the record of what was imported.
- **It doesn't move anything on its own.** Neither the RAW nor the folders: whatever changes place, you change it, with the tool or by hand.
