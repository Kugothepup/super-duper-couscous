# Capturing sources

How posts get into a study. The originals stay in `studies/<id>/raw/`, which is never committed. `crp verify` checks every capture you write against its source, word for word (D20).

## Where things go

| Source | Put it in | You write |
|---|---|---|
| A pasted page | `raw/<name>.txt` | `raw/capture/<name>.json` |
| A screenshot | `raw/<name>.png` (or .jpg, .webp) | `raw/capture/<name>.json` |
| A Reddit export: the thread URL with `.json` added, an NDJSON dump or a CSV | `raw/reddit/` | nothing |
| An interview transcript (.txt, .md, .docx, .vtt, .srt) | `raw/interviews/` | nothing |

`crp ingest` numbers forum threads T01, T02 … in order of their first post, and interviews I01, I02 … by file name.

## Capture file

One per paste or screenshot:

```json
{"source_file": "pro_price.txt",
 "site": "reddit.com/r/notetaking",
 "url": null,
 "captured": "2026-09-28",
 "thread_title": "Is Quillnote Pro worth it?",
 "search_query": "quillnote pricing",
 "posts": [
   {"id": "p1", "author": "some_name", "date": "2026-09-07", "date_approx": true,
    "parent": null, "score": 412, "text": "the post exactly as written"}
 ]}
```

- **source_file**: the original's path relative to `raw/`.
- **text**: the post exactly as written, with the same words, spelling, case, punctuation and order. Only spacing and quote-mark styles may differ. Anything else counts as "tidied" and stops `crp anonymise` until it's fixed. Never tidy, correct, shorten or summarise.
- **Interface text is left out**: "Reply", "Share", vote counts, badges, "Edited", avatars, signatures, "Continue this thread", "N more replies".
- **Quoted text** from an earlier post, repeated at the top of a reply, belongs to the earlier post. Leave it out of the reply's text, and make that post the reply's `parent`.
- **author**: the display name as shown, or null. Names never leave `raw/`, because `crp anonymise` replaces them with person codes.
- **date**: YYYY-MM-DD. Convert relative times ("21d ago", "3 mo. ago") from `captured` and set `date_approx: true`. Unknown dates are null.
- **parent**: the `id` of the post it replies to, when the page shows it (indentation, "replying to", a quote). On a flat forum, it's null for everything after the first post.
- **score**: likes or upvotes if the page shows them, else null.
- **search_query**: the search that found the thread, if known. It feeds the leave-one-out check by search term.
- A comment with no text (deleted, or only an image) is skipped.
- **headline**: set `"headline": true` on the opening post when it's a link post's title, the article's headline rather than the poster's words. It stays as context for the replies but is never sampled (D41). `crp paste` sets it for you.

### Pasted Reddit pages

Use `crp paste studies/<id> page.txt` (or `-` to read the paste from standard input). It saves the page as `raw/<name>.txt` and writes its capture file, following the rules above:
- Names and links stay as shown.
- Ads, bots, deleted and image-only comments are skipped and counted.
- Quoted text at the top of a reply is left out, and the reply's parent is set to the post it quotes.
- Relative times are converted from `--captured` (default: today).
- The opening post is the post's own text, or the thread title when it links to another page, marked as a headline (context only, D41).

It also counts the replies Reddit had collapsed ("N more replies", "Continue this thread"). Tell Steeve, so he can expand them on the page and paste again with `--replace`; the earlier paste is kept in `raw/replaced/`. If a page's layout isn't recognised, write the capture by hand.

### Screenshots

Transcribe what's visible. Write `[?]` for an unreadable word. If a post is cut off at the edge, transcribe what's there and end with `[cut off]`. Never complete it from context. With Tesseract installed, `crp verify` compares the text with OCR and flags posts to look at. Without it, screenshot posts stay "unverified", and the outputs say so.

### Exports

Reddit JSON and CSV exports are read as they are. `crp ingest` reports collapsed "load more" comments (tell Steeve the export is incomplete) and removes AutoModerator and bot comments (`--keep-bots` keeps them).

### Interview transcripts

Speaker labels become person codes, the same as forum authors (D17). `crp ingest` guesses the interviewer as the speaker who asks the most questions. Check the roles it prints, and re-run with `--interviewer "Name"` if any are wrong. Interviews are their own source type: they are read in full and never enter forum percentages (D14).

## Collection log

`collection_log.csv` has one row per search, including searches that kept nothing (D15):

```
source,search_term,date,reason,neutral,results_seen,kept,why_excluded
reddit.com/r/notetaking,quillnote,2026-09-21,name-only search,y,40,3,off-topic or duplicates
```

- **neutral** is `y` for a search that doesn't assume an answer ("quillnote"), and `n` for one that does ("quillnote too expensive").
- If every search is `n`, suggest neutral ones to Steeve.

The trust section reports the log. Without it, nobody can tell how the material was chosen.
