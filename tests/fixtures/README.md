# Test fixtures

`quillnote-fixture/` is a small synthetic study about Quillnote, a fictional notes app. It exists for tests only. It is not a demo study (D16), and its text is invented.

`make_fixtures.py` writes it. After changing the script, regenerate from the project root with `python tests/fixtures/make_fixtures.py` and commit both. `tests/test_fixtures.py` fails if the committed files and the script disagree.

## What's in it

| File | Contents |
|---|---|
| `study.yaml` | Product study, two research questions, event date 2026-06-09 (the fictional 4.2 update) |
| `collection_log.csv` | 5 searches, 2 of them neutral, one that kept nothing |
| `codebook.yaml` | Version 1: 6 aspects; `overall` and `aspect_scores` for the measurement sample; force, evidence grade, friction, severity and aspect for the detail selection |
| `posts.jsonl` | 70 forum posts in 4 threads, and 8 interview turns |

## Facts the tests check

| Fact | Value |
|---|---|
| Forum threads | T1 (forum, pasted), T2 (Reddit export), T3 (Reddit export), T4 (forum, screenshot, approximate dates) |
| Forum posts per thread | T1: 10, T2: 12, T3: 41, T4: 7 |
| Distinct people in forum posts | 55 |
| Pile-on | T3: 1 opening post and 40 replies, all posted on 2026-06-10 |
| Prolific poster | `night_owl_notes` has 12 posts: 4 in T1, 4 in T2, 2 in T3, 2 in T4 |
| Promotional post | 1, in T1 ("use my code …") |
| Short echo reply | 1, in T2 ("Same, it's painful.") |
| Interview | I01: 8 turns, 4 by the interviewer and 4 by the participant |

Person codes use the fixed test salt in `make_fixtures.py`, which is not a secret.
