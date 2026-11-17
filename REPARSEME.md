# REParse·me

> **What question does this document answer?**
> *My vault was written by older versions of the import: how do I bring it up to date without losing anything and without duplicating conversations?*

To install and launch, see the [README](README.md). For the overall design, [ARCHITECTURE.md](ARCHITECTURE.md). Image recovery, which is a separate tool, is in [RECOVER_IMAGES.md](RECOVER_IMAGES.md).

---

## In one sentence

REParse·me rewrites the notes in your raw vault the way **today's import** would write them, each one faithful to **its own export**, gives each one the name the import would give it, and brings the merged and projects vaults up to date. **It simulates first, keeps an exact copy of everything it touches, and can undo.**

## Why it exists

Every improvement to the import applies to what you import **afterwards**. Notes you already had stay as they came out. Measured on the vault it was built with (7,358 notes in RAW) before the first run:

| What was wrong | Notes |
| --- | --- |
| Raw JSON blocks (`{"content_type": …}`): reasoning, tool calls, quoted files, custom instructions, Canvas documents | 3,696 |
| "Image not available" (images the old import couldn't read, or that the export didn't include) | 1,645 |
| ChatGPT notes with no `model` in the frontmatter | 261 |
| No `conv_id` in the frontmatter | 44 |
| Null bytes (unresolved image markers) | 19 |

And it will happen again: every time the import improves, there will be something new for older notes.

## Why reimporting isn't enough

Because of **fingerprints**. Every RAW note carries the fingerprint of its content in its name (`…-h4e66319e.md`). If today's import writes the same conversation differently, the fingerprint changes, the name changes, and RAW gains **another version next to the old one**. Then the merge:

- picks as champion the version with **more words** — usually the old one, because raw JSON is bulky;
- adds the other one's messages as "exclusive", because it doesn't recognise them as the same.

Result: thousands of merged notes with **both forms mixed together**. That's why REParse·me should run **before** importing new exports.

---

## How to use it

### From the app

Tools → Workshop → **REParse·me**. The folded title shows the last run and how many notes still have raw JSON (counting the rest needs a simulation).

1. **Close Obsidian** and back up your vault. Recommended, not required: REParse·me keeps its own copy.
2. **Simulate**: shows the live log and a summary in cards. It writes nothing to your vault.
3. If the numbers look right, **Apply** (it only appears after a simulation, and asks for confirmation). It takes a few minutes.
4. **Undo the last one** says which run it would undo, and leaves RAW, the merged and the projects vaults **identical** to before: names, bytes and dates. Images copied to the banks stay (named by their fingerprint, they don't duplicate anything).

### From a console

```bash
python reparseame.py                        # diagnosis and plan: writes nothing
python reparseame.py --aplicar              # for real
python reparseame.py --deshacer "logs\reparseame_YYYYMMDD-HHMMSS"
```

`--base-vault`, `--exports` and `--logs` override what `memoria_config.yaml` says; `--csv` saves one row per affected note.

---

## What it does

1. **Merges RAW as it is**, aside, to compare it with your merged vault: any merged note with lines the merge doesn't produce was **edited by hand**. It's flagged and left alone.
2. **Images from any of your exports.** Every "image not available" notice carries the pointer to its image. REParse·me looks for it in all your exports, copies it to its bank with the name the import would give it, and writes pointer → link into `<CHATGPT>/_punteros_imagenes.json`. **RAW is not touched**: if that export didn't bring the image, the notice is the truth about that export. The merge reads that map and shows the image in the merged vault if *any* export had it — the notice and the link of the **same** image become a single message; two different images stay different. The import feeds the same map, so future exports with missing images fix themselves in the merged vault.
3. **Rewrites RAW:**
   - Raw JSON is converted **with the import's own functions**: reasoning, tools and outputs folded; Canvas as a document; custom instructions once, at the top. If the import improves, REParse·me improves with it.
   - What the note alone doesn't know (`model`, `conv_id`, images its own export did have and the old import couldn't read) comes from **its own export**: the import's manifest (`logs/conversaciones_manifest.jsonl`) says which exports brought each conversation; it is regenerated from them and replaced only if the **exact version** shows up (same messages, not counting images or frontmatter). If several exports give the same version, the one most similar to the note wins: that's the trace of the export that wrote it.
   - Every note with a fingerprint is **renamed after its new content**, so the next import recognises it and skips it.
   - **Identical versions** of the same conversation are set aside (into the copy); the one that stays inherits the most recent date, because the merge titles a renamed conversation after its most recent version.
4. **Merged vault:** merges the repaired RAW aside and syncs **only the notes the merge owns** (the year folders). Session notes (Claude Code, Codex) and anything else that lives there are left alone. Orphans — notes the merge no longer produces because their conversation now has another name — go to the copy.
5. **Projects vault:** refreshed like a normal import does; stale copies of conversations that moved project go to the copy.
6. **Indexes**, as in a normal import.

## What it does and doesn't do

| Does | Doesn't |
| --- | --- |
| Rewrites RAW the way today's import would, each note from its own export | Invent what no export has: those images stay as a notice |
| Shows in the merged vault the images any of your exports has | Put into a RAW note an image its own export didn't bring |
| Renames by fingerprint so the next import doesn't duplicate | Touch hand-edited merged notes (it flags them) |
| Keeps an exact copy of everything and undoes to the byte | Delete anything: what's set aside goes into the copy |
| **Simulates by default** | Write a single note without `--aplicar` / "Apply" |

**Notes are not edited by hand.** They are the archive of your conversations and say what was said, typos included. That's why the normal merge is right to overwrite manual changes in the merged vault, and why REParse·me only flags them: the next import brings them back to their original form.

## Measured on the real vault

On a full copy first, then on the vault itself (2026-11-16), with the same numbers:

- **RAW:** 1,745 notes rewritten, 209 renamed, 3,695 identical versions set aside: 7,358 notes became 3,663 without losing a message. Later, from their own export: 10 regenerated; 985 were already faithful (what they lack, their export doesn't have either).
- **Images:** 1,721 of the 2,431 noticed images are in some export; merged notes with notices went from 602 to 194. The remaining 710 images are in no export.
- **Merged / projects:** over the three runs, 1,166, 452 and 15 merged notes brought up to date; 7 merged orphans and 24 stale project copies set aside; one hand-edited note left alone.
- **The day after:** importing two more exports and merging again creates no duplicates.

## How it's tested

- End to end: a note written the old way comes out **byte for byte** identical to the one today's import writes from the same export.
- No duplicates: after REParse·me, reimporting the same export **creates no file** in RAW.
- Undo: apply + undo leaves everything identical (content, names and dates); undoing refuses if a note changed since.
- The merge: notice and link of the same image are one message; without the file in the bank the notice stays; two different images don't merge.
- The Workshop: status, simulate, apply, undo and "a run is already in progress".

## Pending

- The diagnosis still counts as pending notes that are faithful to their export (their export doesn't have what they lack). It should tell "faithful" from "broken".
- Cover the two cases [RECOVER_IMAGES.md](RECOVER_IMAGES.md) still handles — hanging library images on old notes, and generation metadata — so that tool can be retired.
