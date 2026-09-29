# Build plan

Move the pipeline from "a skill that does everything in the chat" to "a skill that does judgement, plus Python that does the counting". Work one phase at a time. Each phase ends with its **Done when** checks passing, `pytest` green, a commit, and a stop for review.

Phase 0 found that most of the counting already lives in the skill's scripts, so the phases below port them (see "Porting the existing scripts"). Where this plan and `DECISIONS.md` differ, `DECISIONS.md` wins.

## Target layout

```
community-research/
├── CLAUDE.md  BUILD_PLAN.md  README.md  DECISIONS.md  INVENTORY.md
├── pyproject.toml
├── .claude/
│   ├── settings.json
│   ├── agents/blind-coder.md
│   └── skills/community-research/
│       ├── SKILL.md              # orchestration + judgement guidance (refactored in Phase 7)
│       └── reference/            # codebook guidance, evidence grades, wording rules, split out of SKILL.md
├── crp/                          # Python package: everything that counts
│   ├── __main__.py  cli.py
│   ├── schemas.py  io.py  manifest.py
│   ├── ingest.py  verify.py  anonymise.py
│   ├── sample.py  codebook.py  batch.py  labels.py
│   ├── agreement.py  stats.py  sensitivity.py  keyness.py
│   ├── signals.py  themes.py  hypotheses.py  language.py  validate.py  view.py
│   └── build.py  numbers.py
├── tests/
│   ├── fixtures/                 # small synthetic fixtures built for the tests (no demo study: D16)
│   └── reference/                # the skill's original scripts, unchanged, for comparison tests
└── studies/<study-id>/
    ├── study.yaml                # question, study type, dates, sources, owner
    ├── collection_log.csv        # source, search_term, date, reason, neutral(y/n), results_seen, kept, why_excluded
    ├── raw/                      # pastes, screenshots, transcriptions (gitignored)
    ├── sealed/prior.md           # Steeve's prior belief (Claude can't read)
    ├── posts.jsonl               # one row per post, anonymised
    ├── codebook.yaml  codebook.lock
    ├── samples/                  # measurement.jsonl (random), detail.jsonl (purposive)
    ├── batches/  labels/         # blinded inputs and coder outputs
    ├── human/                    # agreement_sheet.csv, human_labels.csv
    └── results/                  # results.json, dashboard.html, report.md, run_manifest.json
```

The CLI is `python -m crp <command> studies/<id> [options]`. Every command is idempotent, validates its inputs against `schemas.py`, and appends to `run_manifest.json`.

## Porting the existing scripts

The skill's scripts are ported into `crp/`, not rewritten (D7). Phase 1 copies them unchanged into `tests/reference/`, so comparison tests keep working after Phase 7 rewrites the skill folder.

| Skill script | `crp` module | Phase |
|---|---|---|
| `init_study.py` | `cli.py` (`crp new`) | 1 |
| `parse_transcripts.py`, `parse_reddit.py`, `parse_forum.py` | `ingest.py` (parsing, de-duplication, promotional flag) | 2 |
| quote checks in `parse_forum.py` and `validate.py` | `verify.py` | 2 |
| author ids in the parsers | `anonymise.py` | 2 |
| `signals.py` | `signals.py` | 2 |
| `triage.py` | `sample.py` | 3 |
| `view_transcript.py`, `list_nuggets.py`, `kwic.py` | `view.py` | 4 |
| `validate.py` (sentiment and nugget labels) | `labels.py` | 4 |
| `validate.py` (insights, jobs, opportunities) | `validate.py` | 4 |
| `drivers.py` | `stats.py`, `sensitivity.py` | 5 |
| `themes.py` | `themes.py` | 5 |
| `hypotheses.py` | `hypotheses.py` | 5 |
| `language.py` | `keyness.py`, `language.py` | 5 |
| `build_report.py`, `build_dashboard.py`, `dashboard.js` | `build.py` and templates | 6 |

---

## Phase 0: Inventory (no code)

Read the whole skill folder. Write `INVENTORY.md` with a table of every step the skill performs:

| Step | What it does now | Type | Moves to |
|---|---|---|---|

Here **Type** is one of JUDGEMENT (stays with the AI), COMPUTATION (moves to code) or CHECK (moves to code). **Moves to** names the `crp` command or the reference file it will live in.

Also record, exactly as the skill defines them:
- the sentiment unit (per comment or per person) and scale
- how "top driver" and "% of re-draws" are calculated
- per-person cap value, bootstrap settings, thresholds
- evidence grades, aspect lists per study type, and stance/tone definitions
- the dashboard's input format (what data it currently expects)

List anything ambiguous or inconsistent under **Questions for Steeve**. Also start `DECISIONS.md`, including these decisions from the review: Outlook section cut; per-thread cap added; ranges from both person and thread resampling with the wider shown; leave-one-out sensitivity added; agreement check gates results; keyness gets min frequency + FDR correction.

**Done when:** `INVENTORY.md` covers every step in the skill, and Steeve has answered the questions. No other files changed.

---

## Phase 1: Skeleton and schemas

- `pyproject.toml` with pinned dependencies: `numpy`, `pandas`, `pydantic`, `pyyaml`, `rapidfuzz`, `krippendorff`, `scipy`, `jinja2`, `pytest`. Add `pytesseract` + `Pillow` as an optional `ocr` extra.
- `schemas.py` (pydantic): `Study`, `CollectionLogRow`, `Post` (post_id, source_type [forum|interview], source, thread_id, parent_id, person_code, timestamp, text, capture_method [paste|screenshot|transcript], raw_ref), `Codebook`, `Label`, `HumanLabel`, `Results`.
- `manifest.py`: appends a stage record (command, start/end time, seed, sha256 of inputs, package versions, codebook version, coder model).
- `crp new <id>` scaffolds a study folder, including `collection_log.csv` headers and an empty `sealed/` folder.
- Build small synthetic fixtures in `tests/fixtures/` in the new schema: a few threads, people and posts with hand-checkable answers, including a prolific poster and a pile-on thread. No demo study in the core (D16).
- Copy the skill's scripts unchanged into `tests/reference/`.

**Done when:** `crp new` works; the fixtures validate; tests cover schema validation (a bad row is rejected with a clear message).

---

## Phase 2: Ingest, integrity and anonymising

- `crp ingest`: reads the AI's transcriptions in `raw/` (the fixed format the skill already uses) into `posts.jsonl`.
- `crp verify`:
  - **Quote check:** every quote or excerpt used anywhere (transcriptions, later the report) is matched against its source text. Exact match passes. After whitespace/quote-mark normalisation, a match passes with a note. A fuzzy match (rapidfuzz ratio ≥ 90) is flagged as "tidied", showing the diff. Below that fails. Output: `results/verify_report.json`.
  - **OCR check** (if the `ocr` extra is installed): OCR each screenshot, compare it with the AI's transcription, and flag lines below the threshold for human review.
- `crp anonymise`: replaces forum usernames and interview speaker names (D17) with `P-` + the first 8 hex characters of HMAC-SHA256(salt, username). Creates `.secrets/salt` on first run. Strips @mentions of usernames inside text.

**Done when:** tests show a tidied quote is caught, an invented quote fails, the same username always gets the same code, and the salt never appears in any output or log.

---

## Phase 3: Sampling

- `crp sample --seed <int>` (a seed is generated and logged if not given):
  - **Measurement sample:** simple random sample from all forum posts (not interviews), after applying the **per-person cap** (5 per person, D9) and a **per-thread cap** (no thread contributes more than 10% of the sample, D2). Sample size is the skill's default of 150; the frame rules (promotional posts, echo replies and very short comments left out) are ported from `triage.py`.
  - **Detail selection:** the skill's triage selection, made by code rather than the AI (budget 200, 5 per person), is recorded as `detail.jsonl` with a `reason` field. They are tagged purposive and never used for percentages.
- Record the sampling frame hash, the caps and the seed in the manifest.

**Done when:** the same seed gives an identical sample; caps are respected (test with a synthetic prolific poster and a synthetic 40-reply pile-on); detail posts can't enter the measurement stats (test).

---

## Phase 4: Codebook, blind coding and agreement

- `crp codebook freeze`: validates `codebook.yaml`, writes `codebook.lock` (sha256 + version). Later commands refuse to run if the codebook changed after freezing.
- `crp batch`: writes `batches/batch_NNN.jsonl`. Each file has a header record with the codebook text and output format, then items with **only** `item_id`, `text` and `parent_text` (if the codebook needs context). No usernames, thread titles, study question or hypotheses. Batches cover the measurement sample (overall, aspects, stance) and, separately, the categorical nugget fields on the detail selection (force, evidence grade, friction and severity, aspect, sentiment). Observations and insights are written by the main session (D10).
- **Coding:** the skill delegates each batch to the `blind-coder` agent, passing only the batch path and output path. The agent writes `labels/batch_NNN.labels.jsonl`.
- `crp labels validate`: checks every item was coded, every value is in the codebook, and nothing extra was added. Fails loudly.
- `crp labels lock`: hashes all labels. From then on, `crp unseal` may run.
- `crp unseal`: refuses unless labels are locked. Copies `sealed/prior.md` to `results/prior.md` and logs the time.
- `crp agreement export`: random blind sample (default 100 items, or all if fewer; seeded) to `human/agreement_sheet.csv` with the codebook categories as columns and **no AI labels**.
- `crp agreement score`: Krippendorff's alpha per coded variable (nominal for categories, ordinal for graded scales), plus a confusion table for sentiment. Status: verified, tentative or unverified, using the thresholds in CLAUDE.md.

**Done when:** a test proves batch files contain no field outside the allow-list; alpha matches the `krippendorff` package on its reference example; `unseal` fails before `lock`; a changed codebook blocks later stages.

---

## Phase 5: Statistics

All in `stats.py`, `sensitivity.py` and `keyness.py`. Each result carries `n_people`, `n_items`, `status` (full / early-signal / counts-only), and the method used.

- **Sentiment share** on the measurement sample, per comment, with the per-person net-negative share as the secondary figure (D8).
- **Cluster bootstrap** (default B = 5000, seeded, percentile intervals): once resampling people, once resampling threads. Report both and use the **wider** as the headline range. Apply the thresholds: counts only below 20 people; early-signal below 60 comments.
- **Aspect sentiment and drivers:** port the skill's existing driver definition exactly, apart from the two top-driver fixes in D12. Compute "% of re-draws in which each aspect is top driver" inside the same bootstrap. Map it to the skill's existing labels (e.g. "can't tell: test first").
- **Sentiment and stance** kept as separate variables (news/topic studies), as defined in D13.
- **Interviews** get their own section, counts only, and never enter forum statistics (D14).
- **Before/after** an event date where `study.yaml` sets one, with the same bootstrap.
- **Leave-one-out sensitivity:** recompute the headline with each source, each search term, and each of the 5 largest threads removed in turn. Report the min–max and which removal moved it most. Also report the headline without caps (D9).
- **Theme and pain-point reach:** distinct people supporting each, and counter-evidence counts, from labels.
- **Keyness:** log-likelihood G² (Dunning) negative vs positive posts, with effect size (log ratio). Keep terms with frequency ≥ 5 and used by ≥ 3 distinct people. Apply Benjamini–Hochberg at q = 0.05. Hide the section below the early-signal threshold.
- `crp analyse` writes everything to `results/results.json` (validated by the `Results` schema).

**Done when:** known-answer tests pass (small hand-worked examples for share, G² and BH); the same seed gives identical results.json; on the same fixture inputs, each ported calculation matches the scripts in `tests/reference/` exactly wherever DECISIONS.md hasn't changed the method, and each changed method's old and new figures are logged in DECISIONS.md.

---

## Phase 6: Outputs

- **Dashboard:** keep the existing design, but make it read `results.json` instead of numbers written in by the AI. Changes:
  - remove Outlook
  - range labelled "within this collection", with the leave-one-out range next to it
  - red/amber/green coding-verification banner on every section, from the agreement status
  - "How much to trust this" shows the collection log summary, caps, seed, agreement score and sensitivity
  - hatched drawing for single-voice and early-signal results stays
- **Report:** a Jinja template. **Every number is a placeholder** filled from results.json (e.g. `{{ headline.share_pct }}`). The AI writes the prose around the placeholders; it doesn't type numbers.
- **Safe wording:** generated from templates using results.json values and status, following the skill's wording rules (one unit throughout).
- `crp check-numbers`: scans report.md and dashboard text for any number not traceable to results.json (dates, n and years allow-listed). Fails if any are found.
- `crp build --shareable`: strips verbatim quotes and thread links, and keeps person codes out.

**Done when:** check-numbers catches a planted invented number (test); the shareable build contains no quote text found in posts.jsonl (test); a fixture study's dashboard renders from results.json alone.

---

## Phase 7: Refactor the skill

Rewrite `SKILL.md` as an orchestrator:
- Frontmatter: `name: community-research`, a clear `description`, and `allowed-tools` covering `Bash(python -m crp:*)` so stages run without a prompt each time.
- Body: the study stages in order, each saying **what the AI does** (judgement) and **which `crp` command runs** (computation). Include the stop points: after collection, after codebook freeze (Steeve approves the codebook), at agreement coding (Steeve codes the sheet), and before build.
- Move long guidance (codebook design per study type, evidence grades, sentiment vs stance, wording rules, hypothesis test-plan format) into `reference/` files that SKILL.md points to.
- State the one rule at the top: never compute numbers in conversation.

**Done when:** `/community-research` on a fixture study runs end to end, stopping at each stop point, and produces the dashboard and report with check-numbers passing.

---

## Phase 7b: Paste and rounds (D35, D36)

- `crp paste`: turns a copied Reddit page into a capture file, ported from ux-t's `forum_source.py` (both page layouts, badges, votes, ads, bots, deleted and image-only posts), with tests on saved pages (D38). Names stay in `raw/` until `crp anonymise`, and `crp verify` checks every post as now. It reports how many replies Reddit had collapsed, so they can be expanded and pasted again.
- `crp anonymise` also replaces usernames mentioned in post text without `u/` or `@` (D38).
- "Have we heard enough?": `crp analyse` computes the smoothed build-up of observation tags over random reading orders, and the dashboard and report draw it (D39).
- The skill asks before reading interview transcripts, since what Claude Code reads goes to Anthropic's cloud (D38).
- `crp status studies/<id>` (brought forward from Phase 8): each stage done, waiting on Steeve, waiting on Claude, or blocked, and why.
- Stable sampling: each post's place in the draw comes from a hash of the seed and its post ID, so adding posts keeps most earlier picks.
- `crp round studies/<id>`: keeps the current round in `rounds/<n>/`, takes in new captures, redraws, and batches only the posts that need coding. Labels are reused when text, codebook version, sample and coder model all match.
- `crp analyse` adds round-to-round changes to results.json, and the dashboard and report show them.
- `crp reset studies/<id>`: archives generated files, keeps `raw/` and the sealed prior.

**Done when:** adding a thread to a fixture study keeps most earlier picks, only new picks are batched, reused labels are counted in the manifest, and a round comparison appears in the report with check-numbers passing.

---

## Phase 7c: Local page (D36)

- Follows ux-t's studio design (D38): a Next box, copy-paste prompts for Claude Code, and earlier synthesis versions kept with restore. It refuses requests from other websites (Origin and Sec-Fetch-Site) and other host names.
- `python -m crp ui` serves a page on 127.0.0.1: studies with their status, new study, paste or upload threads (runs paste, ingest, verify, anonymise and signals), approve the codebook, agreement coding one post at a time, and links to the shareable and internal builds.
- Steps done by Claude show the line to type into Claude Code.
- Tests: the server binds loopback only, refuses paths under `sealed/`, `.secrets` and anything outside the study, and each button runs the same code as its `crp` command.

**Done when:** a new study can be created, threads added, the codebook approved and the agreement sheet coded from the page, with the same files and manifest records as the command line.

---

## Phase 8: Hardening

- End-to-end test on a fixture study from `crp new` to `crp build`.
- Determinism test: run twice with the same seed and diff results.json.
- `run_manifest.json` shows time taken per stage, which gives the speed figure for the write-up.
- `crp status studies/<id>` lists which stages are done, pending or blocked, and why.

**Done when:** the full test suite passes from a clean clone with only `pip install -e .[ocr]`.

---

## Phase 9: First real study

Run one real pitch dataset. Steeve codes the agreement sheet. Record in DECISIONS.md: alpha per variable, where the AI and the human disagreed most, time per stage, and anything that broke. Fill in the placeholders in the write-up ([x–y] and [X hours]).

---

## Later (not now)

- **API coder:** `crp code --api` calls the Anthropic API directly with a pinned model and fixed settings, and logs model ID and prompt hash per batch. This gives fully repeatable labels and stronger blinding than an agent inside the session.
- **Uncoded posts near a theme:** ux-t's local embedding map lists uncoded posts close to a theme. It could suggest candidates for D37's logged top-up, but needs Ollama and a local model.
- **Held-back half:** for large datasets, seal a random 50% at sampling time to test hypotheses the data suggested.
