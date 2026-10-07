# I'm stuck

> **What question does this document answer?**
> *What if I don't know any of this?*

M3M0R·IA takes two things for granted that not everyone has a reason to know: using a terminal, and opening your browser's developer tools. This document doesn't teach you M3M0R·IA — it teaches what comes **before**.

You don't need to read it all. Go to yours:

- [I've never used a terminal in my life](#ive-never-used-a-terminal-in-my-life) — install Python and start the app.
- [They're asking for a music token and I don't know what that is](#theyre-asking-for-a-music-token-and-i-dont-know-what-that-is) — get it from your browser, step by step. Works the same for Suno and for Flow Music.
- [They're asking for a token or a cookie for the images](#theyre-asking-for-a-token-or-a-cookie-for-the-images) — Copilot asks for a token like the music ones; Grok asks for a **cookie**, which is something else and weighs more.

---

## I've never used a terminal in my life

Did everything above sound like gibberish? This section is for you. No prior knowledge, on Windows, step by step.

**1. Install Python.**
Go to [python.org/downloads](https://www.python.org/downloads/) and click the yellow download button. When running the installer, **check the "Add Python to PATH" box** (at the very bottom, easy to miss — it is the single most important step here). Then "Install Now" and wait.

**2. Download this project.**
On this GitHub page, click the green **Code** button → **Download ZIP**. Extract the ZIP anywhere — for example `C:\M3M0RIA`. (Right-click the ZIP → "Extract all".)

**3. Open a console.**
Press the Windows key, type `powershell` and press Enter. A blue or black window with text opens: that is the console or terminal. You use it by typing commands and pressing Enter. It doesn't bite.

**4. Enter the project folder.**
Type this (or copy it and paste with right-click) and press Enter — adjust the path if you extracted somewhere else:

```
cd "C:\M3M0RIA"
```

**5. Install what the program needs.**
Copy this, paste, Enter:

```
pip install -r requirements.txt
```

A wall of text will scroll by for a while. That's normal: it is downloading the pieces the program uses. When the cursor comes back, it's done.

**6. Create your configuration.**
Copy, paste, Enter:

```
copy memoria_config.yaml.example memoria_config.yaml
notepad memoria_config.yaml
```

Notepad opens with the configuration. You only need to adjust two paths: `base_vault` (the folder where your notes vault will live — a new empty folder is fine) and `exports_dir` (the folder where you'll drop the ZIPs you download from ChatGPT/Claude/Grok). Save and close.

**7. Get your exports.**
- **ChatGPT**: Settings → Data controls → Export data. You'll get an email with a ZIP.
- **Claude**: Settings → Privacy → Export data. You'll get an email with a ZIP (sometimes several).
- **Grok**: Settings → Data → Download your data.

Drop the ZIPs as-is (do not unzip them) into the folder you set as `exports_dir`.

**8. Launch M3M0R·IA.**
In the console:

```
python launcher.py
```

Your browser opens with the interface. From here on, everything is clicks: **Configuration** tab to review paths, **Verification** to check your ZIPs are recognized, and **Construction** → "Import pending" to run the conversion. The live log tells you what it's doing. When it finishes, open your vault folder with Obsidian and enjoy.

**If something fails:**
- *"python is not recognized as a command..."* → the PATH checkbox from step 1 wasn't ticked. Reinstall Python with it checked, close the console and open a new one.
- *"pip is not recognized..."* → same as above.
- The browser window doesn't open → manually type `http://127.0.0.1:8765` in your browser.

---

## They're asking for a music token and I don't know what that is

Token, F12, headers? This section is for you. No programming needed: it's copying a long piece of text from one screen to another. The odd part is where it's hidden.

### Why this step is manual

The other providers give you an "export my data" button and a ZIP. **Suno and Flow Music don't.** Your library can only be asked for through their API, and the API wants proof that you're you.

Both work the same way: an `Authorization: Bearer …` header you pull out of your browser exactly alike. What follows works for either one — the site you start from changes, and little else.

That proof is the **token**: a temporary pass your browser has held since you signed in. It lives a few minutes and expires on its own. There's nothing to store, no credentials to put in a config file — which is why the step isn't automated, and why you do it yourself each time.

Worth saying plainly: **while it lasts, that token stands in for you.** Whoever holds it can ask the service for the same things you can. Don't paste it anywhere that isn't this app, don't send it over chat, and don't publish it in a screenshot. It expires fast, which is the good news.

M3M0R·IA treats it accordingly: it travels in the request body and not in the address bar, it's handed to the process through its environment and not on the command line, it's redacted from the log before it reaches your screen, and it isn't stored anywhere. It leaves with you when you close the tab.

### Getting it, step by step

**1. Open your library.**
Go to [suno.com](https://suno.com) or [flowmusic.app](https://flowmusic.app) signed in, to the screen where you see your songs.

**2. Open the developer tools.**
Press `F12`. If your keyboard has an `Fn` key, it may be `Fn`+`F12`. A panel opens, at the side or the bottom, full of tabs: it's the console every browser ships with. Looking around breaks nothing.

**3. Go to the «Network» tab.**
Some browsers call it «Net». It will be empty: it only records what happens *while* it's open. So **refresh the page** (`F5`) without closing the panel. A list fills up — each line is one request your browser makes to the site.

**4. Search with the magnifying glass.**
That same tab has a **magnifier** icon. Open it and type `bearer`. This search looks *inside* the requests, not just at their names, which is exactly what you need: the token is inside. It will flag the lines carrying it.

**5. Switch to the «Headers» view.**
Click one of the results. A detail panel opens with its own tabs: **Headers**, Payload, Response... **You have to be on Headers.** The token doesn't appear in the other views, and this is where most people get stuck.

**6. Copy the token — and watch out, this is where the browser plays a trick on you.**
Find the line `Authorization: Bearer eyJ...` and copy **only what comes after the word «Bearer»**: a very long string of letters and numbers starting with `eyJ`. Without the word «Bearer», without quotes, without leading spaces.

The token is so long that **both browsers cut it short when displaying it**, each in its own way, and if you copy what you see you walk away with half a token and no idea:

- **In Firefox** — tick **«raw»** in the headers view. Without it you copy a trimmed version.
- **In Chrome** — it paints an ellipsis `…` in the middle. If you see one, don't copy from there: right-click the request → Copy → **Copy as cURL**, and pull the token out of the text you get.

It's the most common failure and the one that warns you worst: it doesn't say "truncated token", it says odd things or simply blows up.

**7. Paste it into the MUSIC·0LOGY tab** and press "Download library".

### If something doesn't add up

- **I can't find any line with `Authorization`.** Refresh the page with the panel open. If the list is still empty, check you're on Network and not on Console.
- **I pasted it and it says it's invalid.** Most likely it's truncated — go back to step 6. You may also have copied the word «Bearer» along with it, or a space. And on Suno there are requests to `clerk.suno.com` that carry a token but won't work: the good ones go to `studio-api`.
- **The download stopped halfway.** Almost always the token expiring. Get a fresh one by repeating these steps and launch it again: it **resumes where it left off**, it doesn't start over.
- **I've forgotten all of this.** It's inside the app too: in the MUSIC·0LOGY tab, the fold labelled «Does this sound like cryptography? Open me».

## They're asking for a token or a cookie for the images

In **image.ia**, Copilot's and Grok Imagine's images are requested from their library, just like the music: neither brings everything in its export. It's the same gesture —copying a credential from the browser into this app— but **it isn't the same credential**.

### Copilot: a token, like the music ones

Follow the steps above with two changes:

- In step 1, go to [copilot.com](https://copilot.com) while signed in and open **Library → Images**.
- In step 4, instead of searching for «bearer», **filter by `Artifact.ashx`**. It's the request that asks for your list of images. Inside, under Headers, is the line `Authorization: Bearer eyJ...`.

The rest is identical, including the care about a truncated token (step 6). Paste it into **image.ia → Copilot**. It lasts about an hour.

### Grok Imagine: a cookie, which is something else

Grok doesn't use a `Bearer`. Its web identifies itself with the **session cookie**, and that changes two things.

**It weighs more.** A music token is a temporary pass to ask for your library. The grok.com cookie is **your whole session**: while it stays open, whoever holds it can do in your account what you would, not just see your images. Don't paste it anywhere that isn't this app, don't send it over chat and don't let it appear in a screenshot. And when you finish, **sign out of grok.com**: that's the safe way to leave it worthless.

**It comes from somewhere else.**

1. Open [grok.com/imagine](https://grok.com/imagine) while signed in, on your library.
2. `F12` → **Network** tab, and type `assets` in the filter. Refresh the page.
3. Click the request that ends in **`rest/assets`**.
4. Under **Headers**, scroll to **Request Headers** and find the `Cookie:` line. It's very long, with many `name=value;` pieces.
5. Right-click that line → **Copy value**. Paste it into **image.ia → Grok Imagine**.

**Watch out for «Copy as cURL (cmd)».** On Windows, Chrome offers several ways to copy a request, and the «cmd» one puts a **`^` in front of special characters** (`%`, `{`, `"`…). Those `^` aren't part of the cookie: if you paste them, Grok receives a broken cookie and answers as if it had expired. Use **Copy value** on the header, or «Copy as cURL (**bash**)», which doesn't carry them. If you see `^` in what you pasted, that's it.

### If something doesn't add up

- **It says the cookie or token has expired right at the start.** Either it really expired, or it's badly copied: the `^` above, or a value cut off with «…». Copy it again.
- **The download stops halfway.** Run it again with a fresh credential: it only downloads what's missing, and what was already downloaded is kept.
- **I can't find `Artifact.ashx` or `rest/assets`.** Refresh the page with the Network panel open and check you're on the image library, not in the chat.

---

*Still stuck? Whatever isn't here is probably in [ARCHITECTURE.md](ARCHITECTURE.md) (how it works inside) or [DEVLOG.md](DEVLOG.md) (what we learned building it).*
