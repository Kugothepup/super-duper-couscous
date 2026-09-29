# Test fixtures

`quillnote-fixture/` is a small synthetic study about Quillnote, a fictional notes app. It exists for tests only. It is not a demo study (D16), and its text is invented.

`make_fixtures.py` writes the raw sources, then runs `crp ingest`, `crp verify` and `crp anonymise` on a copy to produce `posts.jsonl`. After changing the script or the pipeline, regenerate from the project root with `python tests/fixtures/make_fixtures.py` and commit the result. `tests/test_fixtures.py` fails if the committed files and the script disagree.

`fixture-secrets/salt` is a fixed salt for the fixture's person codes. It is not a secret.

## What's in it

| File | Contents |
|---|---|
| `study.yaml` | Product study, two research questions, event date 2026-06-09 (the fictional 4.2 update) |
| `collection_log.csv` | 5 searches, 2 of them neutral, one that kept nothing |
| `codebook.yaml` | Version 1: 6 aspects; `overall` and `aspect_scores` for the measurement sample; force, evidence grade, friction, severity and aspect for the detail selection |
| `raw/pro_price.txt` + `raw/capture/pro_price.json` | A pasted forum page with names, dates and buttons around each post, and the AI's capture of it. One post has a curly apostrophe on the page |
| `raw/love.png` + `raw/capture/love.json` | A screenshot of a forum thread with approximate dates, and its capture |
| `raw/reddit/search_thread.json` | A Reddit thread export with nested replies and 3 collapsed "load more" comments |
| `raw/reddit/sync_export.csv` | A Reddit CSV export of the pile-on thread, including one AutoModerator comment |
| `raw/interviews/interview_01.txt` | An interview transcript with name labels |
| `posts.jsonl` | The pipeline's output: 70 forum posts in 4 threads, and 8 interview turns |

## Facts the tests check

| Fact | Value |
|---|---|
| Forum threads, by first post | T01 (pasted page), T02 (Reddit JSON), T03 (Reddit CSV), T04 (screenshot, approximate dates) |
| Forum posts per thread | T01: 10, T02: 12, T03: 41, T04: 7 |
| Distinct people in forum posts | 55 |
| Pile-on | T03: 1 opening post and 40 replies, all posted on 2026-06-10 |
| Prolific poster | `night_owl_notes` has 12 posts: 4 in T01, 4 in T02, 2 in T03, 2 in T04 |
| Promotional post | 1: T01-p09 ("use my code …") |
| Short echo reply | 1, in T02 ("Same, it's painful.") |
| Bot comment removed | 1, from T03 |
| Interview | I01: 8 turns, 4 by the interviewer and 4 by the participant; the interviewer is found by the question-ratio heuristic |
| Transcription checks | T01: 9 exact and 1 normalised; T04: 7 unverified without OCR |
| Measurement frame | 68 eligible forum posts: the promotional post and the echo reply are left out |
| Thread cap | Only 4 threads, so the default 10% cap stops `crp sample` (D22); tests loosen it to 30% |
| Coding (seed 11, 30% thread cap) | 30 measurement items in 1 batch, and 72 detail items (68 forum, 4 interview) in 2 batches: 102 in all |
