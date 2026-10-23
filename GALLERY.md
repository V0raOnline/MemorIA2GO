# Gallery

> **What question does this document answer?**
> *What does the image gallery do, what doesn't it do, and where does it get what it shows about each image?*

To install and start it, go to the [README](README.md). For the overall design, see [ARCHITECTURE.md](ARCHITECTURE.md). This is only about the gallery.

---

## In one sentence

The gallery gathers **in a single HTML page** all the images and videos from your AIs (ChatGPT, Grok and Copilot), with one strip per conversation, search and filters, and you open it in your browser. It doesn't touch your vault: it reads what's already there and writes only to its own folder.

## Is it part of the pipeline?

**No.** It's an **add-on**: it's built whenever you want, never during an import. That's why **it doesn't update itself**: it's a snapshot of the vault at the moment you build it. If you import something new, build it again. Rebuilding is quick, because existing thumbnails are reused.

Nor does it decide anything by heuristics. Everything it shows about an image **comes from a specific place in the vault** (below, "Where each thing comes from"), and whatever isn't anywhere is not made up: it stays blank.

---

## What it does and doesn't do

| Does | Doesn't |
| ---- | ------- |
| Gathers the images and videos from the ChatGPT, Grok and Copilot banks | Doesn't look at Claude, Suno/Flow or Substack: there are no image banks there |
| Groups each image with **its conversation**: title, date, project, what you asked for and the prompt | **Doesn't change anything in the vault**: no notes, no banks, no manifests |
| Searches by words and filters by source, type, provider, generator, project and month | Doesn't search the full text of the conversations, only what it shows |
| Makes small thumbnails, once, and reuses them | Doesn't update itself: it's rebuilt when you ask |
| Uses the same colour themes as the app | Doesn't need the app open or the Internet: it's a file you open in the browser |
| Takes you to each note in Obsidian and to the original file | Doesn't recover missing images: that's [RECOVER_IMAGES.md](RECOVER_IMAGES.md) |

---

## How to build it

From a console, in the program folder:

```bash
python galeria.py
```

In the Windows package, the folder is `app` (inside the one you unzipped), and the Python is its own:

```bash
python\python.exe galeria.py
```

With no options it uses the base folder from your configuration and writes the gallery to `<base>/.gallery/index.html`. Open that file in your browser.

| Option | What it does |
| ------ | ------------ |
| `--base-vault <folder>` | another base folder (otherwise, the one in `memoria_config.yaml`) |
| `--salida <folder>` | write the gallery somewhere else (otherwise, `<base>/.gallery`) |
| `--sin-miniaturas` | no thumbnails: the page loads the originals (much heavier) |
| `--tema warm\|cool\|light` | the theme it opens with (otherwise, the one in your configuration) |
| `--copilot-vault <folder>` | the Copilot images vault (otherwise, `copilot_images_vault` in your configuration) |

There's no button in the app yet: it's on the [roadmap](README.md#roadmap).

---

## Where each thing comes from

| What you see | Where it comes from |
| ------------ | ------------------- |
| **The images and videos** | the banks: `CHATGPT/GENERATED`, `CHATGPT/ATTACHMENTS`, `GROK/GENERATED_IMAGE`, `GROK/GENERATED_VIDEO`, `GROK/IMAGINE`, `GROK/ATTACHMENTS` and the Copilot vault |
| **The conversation** (title, date, project, provider) | the header of the note in `MERGED_VAULT/Conversations` that links the image |
| **What you asked for** | your last message before the image, in that note (up to 300 characters, without the links) |
| **The prompt** | in ChatGPT, the one the assistant sent to the image tool, if the note keeps it; in DALL·E and Grok, the one their bank keeps; in Copilot, the one in each image's note |
| **The title and time** of the generated images from the ChatGPT library | the block left by the import (or by `recuperar_imagenes.py --biblioteca`): `*Title* · date time` |
| **Generated or uploaded** | the bank it's in (`GENERATED` versus `ATTACHMENTS`) |
| **The generator** (native generation, DALL·E, library, Grok chat, Imagine, Copilot) | the bank's manifest (`_image_manifest.json`); in Grok, the bank itself |
| **The model** (gpt-4o, gpt-5…) | the manifest: it's the **chat** model in that turn, not the image tool's |
| **"Edit of another image"** | the manifest, when the image was made from another one |

---

## How it groups

- **One strip per conversation.** All the images a note links, together, the uploaded one and the generated one included.
- **Copilot has no conversations**: it has one note per image. They're grouped by **prompt and day**, because Copilot makes several variants of each request.
- **What no note links** (Grok Imagine, loose images) goes in **one strip per day and provider**, titled "Grok · no conversation".
- Strips go from **newest to oldest**, in sections by month.

---

## The fine print: what surprises people

Each row is a behaviour of `galeria.py` or of its page, pinned by a test (`tests/test_galeria_documentada.py`).

| Situation | What happens | What to do |
| --------- | ------------ | ---------- |
| **Only MERGED is read** | an image linked only from `RAW_VAULT` or `PRJ_VAULT` shows up as "no conversation" | Run the pipeline (step 2): MERGED is the merged view |
| **An image in two conversations** | it shows **once**, in the first note **by folder and name order**, not by date | Nothing: it's not repeated on purpose |
| **The ChatGPT prompt** | only exists for images from old exports (up to March 2026). New exports no longer carry it and **it can't be recovered** | Nothing to do: OpenAI removed it from the export |
| **The prompt isn't inherited** | if you write another request after an image, the next image does **not** take the previous one's prompt | Nothing: this way there are no false prompts |
| **No generator** | images imported before this version don't have one: they show without a generator and don't match that filter | Run `recuperar_imagenes.py --metadatos` with your exports ([RECOVER_IMAGES.md](RECOVER_IMAGES.md)) |
| **Date of what has no conversation** | the manifest's; if there's none, the **file's modification date**, which may be the day it was copied | Nothing: it's the best there is |
| **Formats** | only `.png .jpg .jpeg .webp .gif` and videos `.mp4 .webm .mov`. A `.heic` or an `.svg` don't show up; nor does anything starting with `_` | Convert them if you want to see them |
| **Search** | it searches **pieces of text** (`cat` finds "catalogue"), ignoring case and accents, and requires **all** the words you type | Fewer words, more results |
| **Where it searches** | the conversation title, the project, the image title, the prompt, what you asked for, the provider, the generator and the model. **Not** the rest of the conversation or the file name | To search the conversations, use Obsidian |
| **"Open in Obsidian"** | opens the note in the vault **named like your base folder**. If you only have `MERGED_VAULT` open as a vault in Obsidian, the link can't find it | Open the base folder as a vault in Obsidian |
| **Copilot outside the base folder** | it's in the gallery, but **without** "Open in Obsidian": it's another vault | Nothing: the original file does open |
| **Your own thumbnails** | if `CHATGPT/GENERATED_Thmbnails/thmbnail_<name>.png` exists, the thumbnail comes from there (faster). But if you **retouch** one of your own thumbnails, the gallery does **not** remake it while the original is unchanged | Delete `.gallery/thumbnails` and rebuild |
| **Videos** | they have no thumbnail: the strip loads the first frame of the original | Nothing |
| **A broken file** | stops nothing: it shows "no thumbnail" and there's a warning in the console | Check the warning: the file is damaged |
| **No Pillow** | it makes no thumbnails and stops with a warning | `pip install pillow`, or build with `--sin-miniaturas` (the Windows package already has it) |
| **Moving the vault** | links are **relative**: the gallery keeps working if you move the whole base folder. If the output is on another drive, they're absolute and break when you move it | Keep the gallery inside the base (the normal case) |

---

## What it writes and what it doesn't

It only writes inside its own folder (`<base>/.gallery`, or the `--salida` one):

| File | What it is |
| ---- | ---------- |
| `index.html` | the page, with all the data inside |
| `thumbnails/` | one JPEG thumbnail per image (480 px on the long side), with the same folder structure as the banks |
| `thumbnails/.version` | the thumbnail version: if the way they're made changes, they're all remade |
| `imageIA.png` | the image.ia little brain, for the header and the browser tab |
| `estado.json` | when it was built and what it holds: it's what the app reads to tell you the gallery's state without opening the page |

Outside that folder **it touches nothing**. The dot in front of `.gallery` keeps Obsidian from indexing it: thousands of thumbnails in the vault tree would just be noise.

It's **derived and rebuildable**: you can delete the whole folder and build it again. The only thing that takes time to redo is the thumbnails.

---

## A real example

On the vault it was built with (four years of ChatGPT, Grok and Copilot):

- **5,986** images and videos in **1,221** strips.
- **5,782** thumbnails: the folder takes about **174 MB** (the originals, several GB).
- The first time takes a few minutes, because of the thumbnails. After that, seconds.
- The page opens quickly because each strip **is drawn when you expand it**: with thousands of images, drawing them all at once would freeze it.

---

## Where everything lives

| What | Where |
| ---- | ----- |
| **The gallery** | `<base>/.gallery/index.html` |
| The builder | `galeria.py` |
| The page template | `galeria_plantilla.html` (the colours are copied from `web/style.css` when building) |
| The theme it remembers | the one you choose on the page is saved **in that browser** |

---

## How to check you're seeing what's there

- **The console** ends with the count: how many images and videos, in how many groups, by provider, and how many thumbnails are new, reused or failed.
- **The counter at the top** of the page says how many you see out of how many there are. If it doesn't add up, look at the **Filters** button: it carries a number with the active filters.
- **An image with no conversation** that you expected to have one: search for its file name in `MERGED_VAULT/Conversations`. If it doesn't appear, no merged note links it.

---

## Known limits

- **It's a snapshot**: it doesn't update itself.
- **Only ChatGPT, Grok and Copilot.**
- **Only `MERGED_VAULT/Conversations` is read** for the context.
- **The prompt of recent ChatGPT images doesn't exist**: the export no longer carries it.
- **Search is by text**, not by meaning: searching "dog" won't find "hound".
