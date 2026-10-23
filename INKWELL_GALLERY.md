# Inkwell gallery

> **What question does this document answer?**
> *What does the gallery of your Substack posts do, what doesn't it do, and where does it get each one's cover?*

To install and start it, go to the [README](README.md). For the image gallery, see [GALLERY.md](GALLERY.md). This is only about the Inkwell gallery.

---

## In one sentence

The Inkwell gallery gathers **in a single HTML page** all the posts Inkwell built from your Substack publications: one card per post with its cover, its title, its subtitle and its first words, with search and filters, and you open it in your browser. It doesn't touch your vault: it reads the notes and writes only to its own folder.

## Is it part of Inkwell?

**It's its add-on**, just as the [image gallery](GALLERY.md) is for the conversations vault. It's built whenever you want, never when the vault is built, and so **it doesn't update itself**: if you rebuild Inkwell with a new export, build it again. Rebuilding is quick, because covers already downloaded are reused.

---

## What it does and doesn't do

| Does | Doesn't |
| ---- | ------- |
| One card per post from all your publications, by month | Doesn't look at other vaults: only Inkwell's |
| Gives each post **its Substack cover**, or the first image in its text | **Doesn't change any note** |
| Searches by words and filters by status, type, publication, section, tag and month | Doesn't search the full text: only what the card shows |
| Downloads each cover **once**, small, and reuses it | Doesn't download the images in the posts' text: only the one used as cover |
| Hides drafts by default | Doesn't delete or hide anything in your vault: drafts show up with their filter |
| Uses the same colour themes as the app | Doesn't need the app open |

---

## How to build it

**From the app**: Tools → Galleries → **Substack posts** → "Build and open". The "Don't go online" checkbox is the `--sin-red` option. It shows the log live and, when it finishes, opens it in your browser; "Open the latest" opens the one you already have. The folded title says when you built it and how many posts it holds.

**From a console**, in the program folder (in the Windows package, the `app` folder, with `python\python.exe` instead of `python`):

```bash
python galeria_tintero.py
```

With no options it uses the Inkwell vault from your configuration (`substack_vault`) and writes the gallery to `<Inkwell vault>/.gallery/index.html`. Open that file in your browser.

| Option | What it does |
| ------ | ------------ |
| `--vault <folder>` | another Inkwell vault (otherwise, `substack_vault` in `memoria_config.yaml`) |
| `--salida <folder>` | write the gallery somewhere else (otherwise, `<vault>/.gallery`) |
| `--sin-red` | don't go online: only the covers already downloaded |
| `--tema warm\|cool\|light` | the theme it opens with (otherwise, the one in your configuration) |

---

## The cover: where it comes from

**The Substack export doesn't carry the cover**: `posts.csv` has no such column, and the images in the text are links to Substack's servers, not files. So, in order:

1. **The Substack cover**, the one you see on your publication. It's requested from the public API of each publication's archive (`https://<publication>.substack.com/api/v1/archive`), **with no credential**: it's the same information anyone visiting your Substack sees. It only exists for what's **published**.
2. **If there's none, the first image in the post's text.**
3. **If there isn't one either, the title's initial**, large. It's not a file: the page draws it.

The gallery **goes online when it's built**, to ask for the covers and download the missing ones. Nothing else: it sends nothing of yours and stores no credentials, because it uses none. With `--sin-red` it doesn't go online.

---

## The card

| What you see | Where it comes from |
| ------------ | ------------------- |
| **The publication** (badge) | the publication's folder in the Inkwell vault |
| **"retired", "draft", "🎙 podcast"** | the note's `status` and `type` |
| **The date and the section** | the note's `date` and `section` |
| **The title and the subtitle** | the note's `title` and `subtitle` |
| **The first words** | the first 50 of the post's text, without the title, the subtitle, Inkwell's notices, the images or their captions |
| **Views, likes, comments** | the note's stats, if Inkwell had the stats CSV |
| **Obsidian ↗** | the note, in its Obsidian vault |
| **Substack ↗** | the post on your publication (published ones only) |

---

## The fine print: what surprises people

Each row is a behaviour of `galeria_tintero.py` or of its page, pinned by a test (`tests/test_galeria_tintero.py`).

| Situation | What happens | What to do |
| --------- | ------------ | ---------- |
| **Drafts** | not shown by default: the summary says how many are hidden. They show up with "Drafts" or with "All" | Nothing: drafts have no date and many have no title |
| **A draft with no title** | it shows the name Inkwell gave it, usually a piece of the identifier ("084") | Give it a title on Substack and rebuild |
| **Retired posts** | their cover isn't in the API (they're no longer public): the first image in their text shows, or the initial | Nothing |
| **A repeated post** (for instance in `Drafts` and in `Borradores`, from having built with both editions) | it shows **once**: the most recently modified note | Nothing |
| **No stats** | if Inkwell didn't have that publication's stats CSV, the card shows no numbers. **It doesn't draw 0**: not knowing isn't the same as zero | Put the stats CSV in your exports folder and rebuild Inkwell |
| **A cover that can't be downloaded** | the next option is tried (the first image, then the initial) and there's a warning in the console. It's retried on the next build | Nothing: some third-party images don't allow downloading |
| **Substack changes the cover** | the new one is downloaded: each cover is remembered together with its address | Nothing |
| **The API doesn't respond** | it carries on without it, with the first image in the text, and warns | Build it again later |
| **`--sin-red`** | it doesn't go online: it uses covers already downloaded; a post with none gets the initial | Nothing |
| **Search** | it searches **pieces of text**, ignoring case and accents, and requires **all** the words | Fewer words, more results |
| **Where it searches** | the title, the subtitle, the first words, the section, the publication and the tags. **Not** the rest of the post | To search the posts, use Obsidian |
| **"Obsidian ↗"** | opens the note in the nearest folder Obsidian has as a vault (the one with `.obsidian`). If there's none, it opens it by its path | Nothing |
| **"Text" in the type filter** | it's everything that isn't a podcast | Nothing |
| **Cropped covers** | they're cropped **from the top** to fill the card: on a vertical cover you see the top part | Nothing |

---

## What it writes and what it doesn't

It only writes inside its own folder (`<Inkwell vault>/.gallery`, or the `--salida` one):

| File | What it is |
| ---- | ---------- |
| `index.html` | the page, with all the data inside |
| `covers/<publication>/<post id>.jpg` | one cover per post, a 640 px JPEG |
| `covers/_origen.json` | which address each cover came from, to know whether Substack changed it |
| `tintero.png` | Inkwell's mascot, for the header and the tab |
| `estado.json` | when it was built and how many posts it holds: it's what the app reads to tell you the gallery's state |

Outside that folder **it touches nothing**. The dot in front of `.gallery` keeps Obsidian from indexing it. It's **derived and rebuildable**: if you delete it, the next build downloads the covers again.

---

## A real example

On the vault it was built with, with three publications:

- **190 posts**: 135 from V0raOnline, 48 from BitacoraClandestina and 7 from MasAlladelPrompt; 14 are drafts.
- **Covers**: 145 from Substack, 18 from the first image and 27 with the initial. Two third-party images refused to download.
- The covers folder takes about **11 MB**. The first time takes a couple of minutes; after that, seconds, downloading nothing.

---

## Where everything lives

| What | Where |
| ---- | ----- |
| **The gallery** | `<Inkwell vault>/.gallery/index.html` |
| The builder | `galeria_tintero.py` |
| The page template | `galeria_tintero_plantilla.html` (the colours are copied from `web/style.css` when building) |

---

## Known limits

- **It's a snapshot**: it doesn't update itself.
- **It only knows what Inkwell knows.** What the Substack export doesn't carry (podcast audio, comments) isn't here either.
- **Retired posts and drafts have no public cover** on Substack.
- **Search is by text**, not by meaning.
