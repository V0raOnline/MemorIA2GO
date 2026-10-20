# Cartography

> **What question does this document answer?**
> *What does the Cartography tab do, what doesn't it do, and how does it decide which conversation goes in which theme?*

To install and start it, go to the [README](README.md). For the overall design, see [ARCHITECTURE.md](ARCHITECTURE.md). This is only about Cartography.

---

## In one sentence

Cartography helps you tidy the conversations that **belong to no project**, without moving or tagging them: you write rules per theme, M3M0R·IA generates one index note per theme with links to its conversations, and Obsidian's graph draws the rest.

## Does it decide by heuristics?

**No.** There is no AI, no embeddings, no "similarity of meaning" and no relevance score. It is **deterministic text matching with rules you write yourself**: the same note and the same rules always give the same result, and you can always tell why a note landed in a theme.

A note goes into a theme if:

- it contains, **literally**, one of its words or phrases, or
- its frontmatter has the value a `field=value` rule asks for.

The only thing with a whiff of heuristics is the **cloud** (the words it *suggests* to you): it filters by frequency and drops filler words. But the cloud only suggests. What goes into a theme is decided by your rules, and nothing else.

---

## What it does and doesn't do

| It does | It doesn't |
| ------- | ---------- |
| Looks at **orphan** conversations (no project) | Doesn't look at conversations that already have a project, nor other vaults (music, images, Substack…) |
| Shows you what they talk about, as a word cloud | Doesn't understand meaning: "dog" doesn't find "hound", and "organoid" doesn't find "organoids" |
| Groups them by **your** rules, into themes | Doesn't classify on its own: with no rules of yours there are no themes |
| Generates an index note per theme, with links | **Doesn't change any conversation**: it doesn't move it, rename it, or add tags or `Project_name` to it |
| Tells you what's left uncovered and how much your themes cover | Doesn't create projects or touch `PRJ_VAULT`: a theme isn't a project, and a note can be in several |
| Lets you name the ChatGPT projects the export ships without a name | Doesn't rank by relevance: a word mentioned in passing counts the same as if it were the subject |
| Works offline | Doesn't delete anything of yours (see "What it deletes and what it doesn't") |

---

## Which notes it looks at

Only the **orphans** in `MERGED_VAULT/Conversations`: those with `Project_name: none`, empty, or without that line. Index files are excluded.

- A conversation **stops being an orphan** when it gets a project, for instance by naming a gizmo (see below). Then it disappears from the cloud and from the themes.
- Claude Code and Codex session conversations come in through their **parent note**; the child notes (reasoning, tools) are left out on purpose, because their vocabulary (`git`, paths, commands) would pollute the cloud.
- Orphans sit in the `none` folder of `PRJ_VAULT`. Cartography doesn't move them from there.

---

## 1. The cloud

It's a **spyglass, read-only**: it doesn't classify or modify anything.

How it's computed:

1. From each orphan it takes the words of the body and the title (each word counts **once per note**, so one huge conversation can't hijack the cloud).
2. It counts how many notes each word appears in. That number is its size.
3. **Generic ranking**: filler words (articles, "but", "the"…, in Spanish and English) are dropped, along with words in fewer than 3 notes and words in more than a quarter of the orphans (those are "conversational background": what discriminates lives in the middle band). Up to 100 are shown.
4. **Project vocabulary**: words matching names of projects that already exist are shown **always**, even if rare, in **magenta**. Those names are seeded from three places: the top-level folders of `PRJ_VAULT`, the values in `gizmo_map.json`, and the projects declared inside the Claude and Grok exports.
5. Clicking a word shows the notes that contain it (up to 200, with the total). It uses **exactly the same rules as a one-word theme**: what you see there is what that rule would catch.

---

## 2. Themes: how it decides which note goes in

A theme is a **name** and a **list of rules**. There are three kinds:

| Rule | How it's written | What it requires | Example |
| ---- | ---------------- | ---------------- | ------- |
| **Word** | a single word, no spaces | that it appears as an **exact whole word**, in the body or the title | `recipe` |
| **Phrase** | with spaces | that this text appears **as is** in the body or the title, as a piece of text (no word boundary) | `workout routine` |
| **Field=value** | `field=value` | that this frontmatter field is **exactly** that | `provider=claude`, `source=claude_export` |

How they combine:

- **A single rule is enough.** The rules of a theme combine with "or".
- **A note can be in several themes**, and that's intended.
- There are no weights or thresholds: one mention and a hundred are worth the same.
- Within each theme, notes are listed from **newest to oldest**.
- Before comparing, **everything is lowercased and stripped of accents**, in the rules and in the notes: `PHYSICS`, `physics` and `Physics` are the same.
- A theme whose rules are **all** `field=value` is called **structural** ("where it comes from"). One with any word or phrase is a **content** theme ("what it talks about").

### What text is looked at

- **Yes**: the body (all messages, yours and the AI's) and the **title**.
- **No**: tags, the file name, or the rest of the frontmatter. The frontmatter only comes in through a `field=value` rule.

### The fine print: what surprises people

Each row is an engine rule, pinned by a test (`tests/test_cartografia_documentada.py`).

| Situation | What happens | What to do |
| --------- | ------------ | ---------- |
| **Singular and plural** | `organoid` and `organoids` are different words | Put both in the theme |
| **Hyphen or underscore** | they don't split words: `happypuking-lab` is **one** word and the rule `happypuking` doesn't catch it | Write the full rule, `happypuking-lab` |
| **Fewer than 3 letters** | they don't exist as words: `ai`, `ml`, `o3` catch nothing | Use a longer word or a phrase (`of the ai`) |
| **Bare numbers** | `2025` catches nothing; mixed with letters it does (`gpt4`) | Add a word with letters |
| **Phrases** | they're a piece of text: `house of` catches "house **of**ten" | Make them specific enough |
| **Filler words** | they are **not** filtered in themes (only in the cloud): a rule `but` catches almost everything | Don't use filler as a rule |
| **Pieces of a word** | a word is whole: `recipe` doesn't catch "recipes" | Add `recipes` separately |

If a theme returns **0**, it's almost always one of these rows.

---

## 3. The index: how it's generated

**When**: when you press "Generate index", and also **automatically in step 4 of every pipeline run**, if your `topic_map.json` exists. You don't need to restart anything when you edit themes.

**How**: the orphans are scanned **once**, and for each theme a note is written to `MERGED_VAULT/_Topics/`. The file name is the theme's name lowercased, without accents and with hyphens.

It's **derived and regenerable**: you can delete it and regenerate it, and the conversations aren't touched.

What gets written:

| File | What it is |
| ---- | ---------- |
| `_Topics/<theme>.md` | one note per theme: its name, its rules and the list of conversations with a `[[…]]` link, date, provider and title |
| `_Topics/_no-topic.md` | the **blind spots** (below) |
| `_Topics/.temas_stats.json` | a summary for the Observatory, hidden from Obsidian by the leading dot |

### What it deletes and what it doesn't

When regenerating, only the notes in `_Topics/` that **carry the mark `generated_by: m3m0ria`** and whose theme **is no longer in your map** are removed. A note of yours that lives in that folder, without the mark, isn't touched. The conversations are never touched.

---

## 4. Blind spots and coverage

`_no-topic.md` tells you what you're missing, in two layers:

| Layer | What it means | What it's for |
| ----- | ------------- | ------------- |
| **Caught by nothing at all** | neither a content rule nor a structural one catches them | If you've created a structural theme per provider, this should be near zero: whatever shows up is usually a frontmatter **anomaly** |
| **Caught only by structural nets** | we know where they come from, but no content theme touches them | It's **your real pending work**: the ones you don't yet know what they're about |

The **content coverage** you see in the Observatory is the percentage of orphans that fall in **at least one content theme** (by word or phrase). A conversation caught only by `provider=claude` **doesn't count**: you know where it comes from, not what it's about. It measures coverage, **not quality**: a badly written theme that catches many notes also raises the figure.

In the Observatory it reads like this: *Content coverage: 40% of 5 orphans · 1 awaiting cartography · ⚠ 2 with no theme at all (anomalies)*.

---

## A full example (real output)

Five orphans and one that already has a project, with these themes:

```json
{
  "Cooking": ["recipe"],
  "Training": ["workout routine"],
  "Claude source": ["provider=claude"],
  "Organoids": ["organoids"],
  "Artificial intelligence": ["ai"]
}
```

| Note | What it says | Result |
| ---- | ------------ | ------ |
| `bread-at-home` | "I want a **recipe** for bread." | in **Cooking** |
| `gym-plan` | "A **workout routine** for the gym, please." | in **Training** |
| `chat-with-claude` | "Let's talk about philosophy." (Claude provider) | in **Claude source**, and since it only falls there, in the *structural only* layer |
| `growing` | "My **organoid** is growing well." | **no theme**: the rule says `organoids`, the note says `organoid` |
| `about-ai` | "**AI** and me." | **no theme**: `ai` has fewer than 3 letters and catches nothing |
| `gala-dinner` | "Another recipe…" | **not even looked at**: it already has a project (`Arkinesis`) |

What gets generated, as is:

```markdown
---
title: "Topic: Cooking"
type: topic
generated_by: m3m0ria
generated: 2026-10-20T23:27:35
keywords: "recipe"
---

# Topic: Cooking

1 related orphan conversations (keywords: recipe).

- [[bread-at-home]] — 2026-06-03 · chatgpt · Homemade bread
```

And `Organoids` and `Artificial intelligence` are created anyway, with "0 related orphan conversations": that's the sign those rules catch nothing. Content coverage comes out at **40%** (2 of 5: only `bread-at-home` and `gym-plan` fall in a content theme).

---

## The other mechanism: Orphan projects (ChatGPT)

It has nothing to do with themes. It solves a different problem: the ChatGPT export identifies projects with an **internal ID (gizmo) that has no name**.

1. **They're detected on import.** A conversation with a gizmo that isn't in `gizmo_map.json` is recorded in `RAW_VAULT/_gizmos_pendientes.json`, with how many conversations it has and sample titles and dates.
2. **You name them.** The tab shows each ID with its sample titles, so you can recognise it. You type the name and press "Save and update vault".
3. **It's fixed without re-importing.** The name is saved to `gizmo_map.json`; `patch_gizmo_map.py` rewrites **only** the `Project_name` and `source_project` lines of the RAW notes (the body isn't touched); and the interface re-runs steps 2 to 4, without repeating the import.
4. **Effect.** Those conversations stop being orphans, get filed under their project in `PRJ_VAULT`, and the name starts seeding the cloud (magenta).

Rows you leave blank keep waiting. It only affects ChatGPT: Claude and Grok ship their project names in the export.

---

## Where everything lives

| What | Where |
| ---- | ----- |
| **Your themes** | `topic_map.json`, next to the program. Never committed. Saving from the interface makes a `.bak` copy first. **It's your curation and no reprocess rebuilds it: keep a copy.** |
| Gizmo names | `gizmo_map.json` (the path is in your configuration) |
| Pending gizmos | `RAW_VAULT/_gizmos_pendientes.json` |
| Theme indexes | `MERGED_VAULT/_Topics/` |
| The engine | `orphan_cloud.py` (cloud, themes, index) and `patch_gizmo_map.py` (gizmos) |

If your `topic_map.json` has an error (one extra comma is enough), the engine **ends up with no themes at all, warns on the console, and leaves the indexes that already existed untouched**. Mind where you see that warning: it appears in the **live log of Construction** (step 4 runs it), but the "Generate index" button will just say "0 theme(s)", without saying why. If it says 0 and you didn't expect 0, open `topic_map.json` and look for the JSON error. And don't press "Save themes" with the list empty: it would overwrite the file (you'd still have the `.bak` copy).

---

## How to check a theme does what you think

- **Look at what "Generate index" tells you.** It ends with "no matches: …" and the list of themes that caught nothing. Each of those names is a rule that doesn't work: check the fine-print table.
- **Open `_Topics/<theme>.md`.** The number at the top and the list say what it caught.
- **Try the word in the cloud**: clicking it shows the notes that contain it, with the same rules as a one-word theme.
- **From the console**: `python orphan_cloud.py "<your base_vault>" --term word` lists the notes that contain that word.

---

## Known limits

- **Text only, no synonyms or stems.** It doesn't understand meaning, singular/plural, or conjugations.
- **It's anchored to `MERGED_VAULT/Conversations`.** It doesn't look at other vaults.
- **The cloud's filler words are Spanish and English.** In another language you'll see more noise.
- **Coverage doesn't measure quality.**
- **Phrases are searched as text**, not as whole words.
