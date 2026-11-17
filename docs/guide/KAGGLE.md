# The free Kaggle GPU

Kaggle gives every phone-verified account about **30 GPU hours a week** (2x T4, 16 GB each). CodeMitra can run its
model there at full 256K context, about 3-4x faster than an 8 GB laptop, without you opening Kaggle.

## Set it up (once, ~3 minutes)
`codemitra setup` does this with you (step 3); on its own: `codemitra kaggle setup`. Two things only you can do on
Kaggle's website:
1. **A free account:** [kaggle.com](https://www.kaggle.com) → Register (Google or email). Skip if you have one.
2. **Verify your phone:** your picture → **Settings** → **Phone verification**. Kaggle gives GPUs and internet in
   notebooks only to verified accounts.

Then the key for CodeMitra: **Settings** → **API** → **Generate New Token**, copy it and paste it when the setup asks
(or run `codemitra kaggle setup <the token>`). If your browser downloaded a `kaggle.json` instead, just press Enter
(or run `codemitra kaggle setup`): it finds it in Downloads. CodeMitra saves it where Kaggle looks, signs in and
shows your hours.

Then CodeMitra shows the **setup checklist**, every step checked now, the ones you have done marked ✓:
```
Kaggle setup
  ✓ 1. Kaggle account  yourname
  ✓ 2. API key         ~/.kaggle/access_token
  ✗ 3. Phone verified  its notebooks get no internet, checked just now
       → kaggle.com → your picture → Settings → Phone verification
  ✓ 4. GPU hours       0.0 h used of 30 · 30.0 h left
  · 5. First GPU run   not yet: `codemitra kaggle start` (4-8 min)
```
Step 3 is checked with a small CPU-only notebook (about 30 s, no GPU hours). CodeMitra offers to open the page, waits
for you to type `done`, and checks again. See the list any time: `codemitra kaggle check` (or `/kaggle check`).

## Use it
- **Start:** `/kaggle start` in CodeMitra (or `codemitra kaggle start`). It uploads a private notebook to your
  account and waits until the model is loaded (4-8 minutes; it shows each step). Every `codemitra` window then uses it.
- **Stop:** `/kaggle stop` when you are done. It also stops by itself after 30 minutes unused.
- **Hours left:** `/kaggle` or `codemitra kaggle status`.
- **When it starts:** `/kaggle use when-needed` (the default: on your first change work), `now` (with CodeMitra),
  `never`. CodeMitra asks once per session before starting it.

## How CodeMitra switches
- **Web search** runs on Kaggle too (SearXNG in your notebook): while it is up, searches cover the whole web.
- **No internet on your machine:** the turn runs on the laptop, Kaggle keeps running and is used again when you
  are back online (the status line says `offline`).
- The status line shows where the model runs: `☁ kaggle · qwen3.5 256K · 28.1 h left` or `💻 laptop · …`.
- Talking runs on the laptop; work (edits, tests, builds) runs on Kaggle when it is up. It switches between turns,
  never in the middle of one.
- **When Kaggle ends** (30 minutes unused, the 12-hour limit, your hours run out, the tunnel drops), CodeMitra moves to
  the laptop model, writes a short report of what was done (`.codemitra/reports/kaggle-ended-….md`) and stops, so you
  decide how to go on.

## Privacy
While you use Kaggle, your prompts and code pass through your Kaggle notebook and Cloudflare's tunnel (protected by a
random token): use it for code you may share, not secrets. Kaggle's terms do not mention tunnels; CodeMitra keeps it
to one private notebook, used by you and stopped when idle, but it is your account and your call. Technical details:
[remote/kaggle/README.md](../../remote/kaggle/README.md).

## Problems
| | |
|---|---|
| 0 GPU hours | verify your phone (Settings → Phone verification) |
| "its notebooks get no internet" | verify your phone, then `codemitra kaggle check`; Kaggle can take a while to turn internet on after it |
| "key expired" / "401" | Settings → API → Generate New Token, then `codemitra kaggle setup <token>` |
| Start takes over 10 minutes | Kaggle is busy: `codemitra kaggle status`; try again later |
| Hours used up | they reset weekly (the status shows when); CodeMitra uses the laptop meanwhile |
