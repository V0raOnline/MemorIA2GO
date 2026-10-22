# Recover images

> **What question does this document answer?**
> *What does `recuperar_imagenes.py` do, what doesn't it do, and why is it needed if you already imported your exports?*

To install and start it, go to the [README](README.md). For the overall design, see [ARCHITECTURE.md](ARCHITECTURE.md). This is only about recovering ChatGPT images.

---

## In one sentence

`recuperar_imagenes.py` puts back into your notes the ChatGPT images that were left as `*[imagen no disponible en el export: …]*` ("image not available in the export"), attaches to their conversation the generated images that the new export carries loose, and records what each one was generated with. **Without reimporting anything**: it changes each note in place, with a backup and a way back.

## Why it exists

In 2026 OpenAI changed the ChatGPT export, without notice:

- **Images are now called `file_XXXX.dat`.** Up to v3.1.0, M3M0R·IA didn't recognise them: it indexed none, and every image came out as "image not available in the export", **without a single error**. From v3.2.0 the import reads them, but the notes you already had still carry the notice.
- **Generated images no longer travel inside the conversations.** They only come loose in `library_files.json` (the "library"), each with the id of the conversation it came from. Unless they're attached to it, they appear in no note.
- **The generation prompt no longer travels.** Old exports kept it; new ones don't. That can't be recovered.

## Why isn't reimporting enough?

Because **it would duplicate your conversations**. The merge (`MERGED_VAULT`) compares messages by their text: a note with the notice and the same note with the link are, to it, **different** messages, and it would keep both. Measured on a copy of the real vault: one conversation went from 187 to 217 of your turns and kept its 44 notices on top of the 44 links.

That's why this tool **replaces the notice with the link inside each note**, with **exactly the same text** the new import would write. That way, when your next export arrives, the merge sees the same message and duplicates nothing.

---

## What it does and doesn't do

| Does | Doesn't |
| ---- | ------- |
| Replaces the notice with the link to the image, in `RAW_VAULT`, `MERGED_VAULT` and `PRJ_VAULT` | Doesn't reimport or merge anything again |
| Copies each image to its bank, with the same name (its hash) the import would give it | Doesn't make up images: what your export doesn't carry stays as a notice |
| With `--biblioteca`, attaches the library's generated images to **their** conversation | Doesn't know at which exact point of the conversation they were: they go **at the end** |
| With `--metadatos`, records what each image was generated with (to filter in the [gallery](GALLERY.md)) | Doesn't recover the prompt of recent images: the export no longer carries it |
| Saves an exact copy of each note before touching it, and undoes with `--deshacer` | **Deletes nothing.** Images copied to the banks stay even if you undo |
| Keeps each note's modification date | Doesn't change the number of turns of any conversation |
| **By default it only counts** (dry run) | Without `--aplicar` it doesn't write a single note or image |

---

## How to use it

From a console, in the program folder (in the Windows package, the `app` folder, with `python\python.exe` instead of `python`). First, **always**, the dry run:

```bash
python recuperar_imagenes.py --export "D:\Exports\chatgpt-2026-10-18.zip"
```

It tells you how many notices there are, how many that export recovers, how many it doesn't, and how many notes it would change. If the numbers look right, the same with `--aplicar`:

```bash
python recuperar_imagenes.py --export "D:\Exports\chatgpt-2026-10-18.zip" --aplicar
```

| Option | What it does |
| ------ | ------------ |
| `--export <zip>` | the ChatGPT export that has the images. Required except with `--deshacer` |
| `--base-vault <folder>` | another base folder (otherwise, the one in `memoria_config.yaml`) |
| `--aplicar` | make the changes for real. Without it, it only counts |
| `--biblioteca` | also copy the library's generated images to `GENERATED` and attach them to their conversation |
| `--metadatos` | instead of repairing notes: complete in the `GENERATED` manifest what each image was generated with |
| `--deshacer <folder>` | restore from the backup of an `--aplicar` run |

**With several exports**, run them one after another: each recovers what it carries, and what's already recovered isn't touched again. Order doesn't matter.

---

## The three jobs

### 1. The notices (no options)

1. Looks for the notices `*[imagen no disponible en el export: <pointer>]*` in the `.md` notes of `RAW_VAULT/Conversations`, `MERGED_VAULT/Conversations` and `PRJ_VAULT`.
2. For each image the export **does** carry, copies it to its bank: `CHATGPT/GENERATED` if it was generated, `CHATGPT/ATTACHMENTS` if you uploaded it, with the same name, the same criteria and the same manifest as the import.
3. Replaces the notice with `![](CHATGPT/<bank>/<hash>.<ext>)`.

### 2. The library (`--biblioteca`)

The generated images the export carries in `library_files.json` that **no conversation links**:

1. They're copied to `CHATGPT/GENERATED`, with their title and date in the manifest.
2. They're attached to their conversation: at the **end of each note** of that thread (in RAW, MERGED and PRJ) a block like this is added, the same format old exports used to leave:

```markdown
### Tool

*Sparrow chick in graphite* · 2026-10-17 23:12

![](CHATGPT/GENERATED/5f7fa7a14d883163.png)
```

Each thread's note is found by the `conv_id` in its header. The **import does the same** with new exports, with the same text.

### 3. What it was generated with (`--metadatos`)

For generated images imported **before** v3.2.0, which don't have it recorded. It adds to their entry in the `GENERATED` manifest, taken exactly from the export:

| Field | What it is |
| ----- | ---------- |
| `generador` | `chatgpt-imagen` (native generation), `chatgpt-dalle` or `chatgpt-biblioteca` (arrived with no conversation, through the library) |
| `modelo` | the **chat** model in that turn (gpt-4o, gpt-5…), not the image tool's |
| `edicion` | `true` if it was made from another image |

It matches each image by its **hash** (the file name), so it doesn't matter which note it's in. It doesn't touch entries that already have it, or anything else in the manifest.

---

## The fine print: what surprises people

Each row is a behaviour of `recuperar_imagenes.py`, pinned by a test (`tests/test_recuperar_documentado.py`).

| Situation | What happens | What to do |
| --------- | ------------ | ---------- |
| **Without `--aplicar`** | it writes nothing: no notes, no images, no backup | Check the numbers and repeat with `--aplicar` |
| **An export doesn't carry everything** | notices for images that export doesn't carry **stay as they are** | Run it with every export you have. The ones no export carries can't be fixed |
| **Repeating** | does no harm: a repaired note has no notice, and a library block that's already there isn't added again | Nothing |
| **The bank of an image from an old export** | if its conversation isn't in this export, the library decides: generated if it's listed there as generated; if it isn't in it, it goes to `ATTACHMENTS` | Nothing: it's the best information there is |
| **The same image in several notes** | it's copied **once** to the bank (same content, same name) and linked in all of them | Nothing |
| **The notes' dates** | the modification date is kept: the merge uses it to break ties | Nothing |
| **Where a library image goes** | at the **end** of the note, not between its turns: the export doesn't say after which message it was generated | Look at the block's time: it's ChatGPT's |
| **The block's time** | in **your local time**, the one you see in ChatGPT | Nothing |
| **The block's title** | the one ChatGPT gave it, without the extension and without asterisks. If it has none, "Generated image" | Nothing |
| **A generated image whose conversation isn't in your vault** | it's copied to `GENERATED`, but not attached to any note: in the gallery it shows as "no conversation" | Import that export and repeat `--biblioteca` |
| **Generated images with no file in the zip** | they're skipped: the library lists them, but the file doesn't travel | Nothing to do |
| **Undoing both** | if you ran notices and `--biblioteca` together there are **two** backups: undo **the library one first**, then the other. The other way round, the notes are left with the links | The console tells you when it finishes |
| **Undoing doesn't delete images** | the notes go back to how they were; images copied to the banks stay | Nothing: they're not in the way, and there are no deletions without asking |
| **Symbolic links** | they're skipped: no symbolic link is followed | Nothing |
| **`--metadatos` doesn't touch what's there** | an entry that already has `generador` stays as it is, even if the export says otherwise | Nothing |

---

## What it writes and where

| What | Where |
| ---- | ----- |
| The repaired notes | in place: `RAW_VAULT/Conversations`, `MERGED_VAULT/Conversations`, `PRJ_VAULT` |
| The images | `CHATGPT/GENERATED` and `CHATGPT/ATTACHMENTS`, with their `_image_manifest.json` |
| **The backup** | `logs/recuperar_imagenes_<date>/` (notices), `…_biblioteca/` and `…_metadatos/`, inside the program folder. Each one with a `diario.json` that says which export, which base and which files |

Each note is written atomically (to a temporary file that then replaces it): a cut halfway doesn't leave a half-written note. Backups **aren't deleted automatically**: when you no longer want them, delete them yourself.

---

## A real example

On the vault it was built with, with 16 ChatGPT exports from different dates:

- **Notices**: from 20,091 to 3,159. **4,272** distinct images recovered; **710** aren't in any export and stay as notices.
- **Library**: 387 generated images copied to `GENERATED` and 1,375 blocks in 375 notes (the same conversation lives in RAW, MERGED and PRJ).
- **Metadata**: all 1,169 generated images, with their generator (778 native, 387 from the library, 4 from DALL·E; 53 are edits).
- 9,503 notes checked: **none** changed its number of turns or its modification date.

---

## How to check it went well

- **The dry run and the real run should give the same numbers.**
- **Open a conversation that had notices** in Obsidian: where the notice was, the image is now.
- **Search the vault** for `imagen no disponible en el export`: what's left is what your exports don't carry.
- **Build the [gallery](GALLERY.md)**: recovered images appear in their conversation, and the generator filter now tells native, DALL·E and library apart.

---

## Known limits

- **ChatGPT only.**
- **What's in no export can't be recovered.** The old exports you deleted took their images with them.
- **The prompt of recent images doesn't exist** in the export.
- **The position** of library images within the conversation is approximate: at the end, with their time.
- **The notice text is always in Spanish**, in the English edition too: it's what the import writes, and it's what is searched for.
