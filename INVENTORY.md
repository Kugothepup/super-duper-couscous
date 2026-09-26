# Inventory: the interview-synthesis skill (Phase 0)

Source: `.claude/skills/interview-synthesis/` as committed in `dd8e629` (SKILL.md, `references/coding_guide.md`, 18 scripts in `scripts/`).

**The main finding: most of the counting is already in code.** The build plan assumes a skill that does everything in the chat. This skill already hands sampling, the bootstrap, driver ranking, hypothesis scoring, keyness, report and dashboard numbers to Python. The AI transcribes captures, codes nuggets and sentiment, synthesises, and writes prose. So Phases 1–6 are mostly a port of existing scripts into `crp/`, with tests. The old scripts can act as the reference implementation for known-answer tests.

What is *not* yet in code: seeds are fixed defaults rather than logged; nothing records a run manifest; coding is not blind; agreement is typed in by hand (`validation.json`); nothing checks numbers in the AI's chat summary or prose; nothing resamples threads or runs leave-one-out.

## Every step the skill performs

Type: **JUDGEMENT** stays with the AI; **COMPUTATION** and **CHECK** move to code. "(new)" marks a `crp` command the build plan doesn't list yet (see Question 1).

| # | Step | What it does now | Type | Moves to |
|---|---|---|---|---|
| 1 | Ask about the study | Asks once for research questions and, for interviews, the interviewer's name | JUDGEMENT | `SKILL.md` stage 1 |
| 2 | Set up the study | `init_study.py` writes `study.json`: subject, type (product, brand, news, topic), questions, stance target, event date, population. Type picks the lens (`_common.LENSES`) | COMPUTATION | `crp new` → `study.yaml` |
| 3 | Record the user's prior belief | Written as a `stated` hypothesis in `hypotheses.json` before reading posts | JUDGEMENT (user) | Steeve writes `sealed/prior.md`; `crp unseal` |
| 4 | Log searches | AI writes `collection_log.json`: site, query, date, results_seen, kept, why_excluded. Suggests neutral searches if the user only searched for their view | JUDGEMENT + record | `collection_log.csv` (Question 9: columns differ) |
| 5 | Parse interviews | `parse_transcripts.py`: .txt/.md/.docx/.vtt/.srt into turns. Guesses the interviewer as the speaker who asks most questions; warns on single speaker or unlabelled text | COMPUTATION | `crp ingest` (source_type interview) |
| 6 | Parse Reddit exports | `parse_reddit.py`: thread JSON, NDJSON or CSV into reply trees. Drops bots, quoted parent lines and markdown; masks `u/` mentions; flags collapsed "load more" comments | COMPUTATION | `crp ingest` |
| 7 | Transcribe pastes and screenshots | AI writes `capture/<name>.json` per source file, verbatim, `[?]` for unreadable, `[cut off]` for truncated | JUDGEMENT | stays with AI; guidance to `reference/capture.md` |
| 8 | Check captures | `parse_forum.py`: paste text must appear in the source (normalised); OCR word overlap; parents exist; date format; duplicate and near-duplicate removal; promotional flag | CHECK | `crp verify` (quote and OCR) + `crp ingest` (dedupe, promo) |
| 9 | Anonymise | Sequential ids by first appearance: `A001` named, `U001` unnamed (each counts as a person), `D001` deleted. Map kept in `authors_private.json`. Interview speaker names are **not** anonymised | COMPUTATION | `crp anonymise` (salted HMAC, per plan) |
| 10 | Warn on a dominant site | Prints a warning if one site supplies over 50% of posts | CHECK | `crp verify` and `sensitivity.py` |
| 11 | Flag language signals | `signals.py`: hedges, fillers, repairs, pauses, constraint, request, workaround, switching; hesitation clusters (interviews only); response gaps; echo replies; high engagement | COMPUTATION | `crp signals` (new) |
| 12 | Select posts for detailed reading | `triage.py`: budget-limited selection by code, with a reason per pick, capped per author. **Code picks these, not the AI** (the plan assumes AI picks) | COMPUTATION | `crp sample` (detail) |
| 13 | Draw the measurement sample | `triage.py`: simple random sample of 150 from the candidate pool, seed 7, no caps | COMPUTATION | `crp sample` (measurement) |
| 14 | Review the selection | Shows the triage summary; user can raise the budget if a topic got few picks | JUDGEMENT (stop point) | `SKILL.md` stop point |
| 15 | Show text for coding | `view_transcript.py`: whole transcripts, triage batches or sentiment batches, with flags, scores and parent context | COMPUTATION | `crp batch` (blinded) + `crp view` (new) for detail reading |
| 16 | Settle the aspect list | 8–20 aspects agreed in the first sentiment batch; synonyms merged using `validate.py`'s counts | JUDGEMENT | codebook draft → `crp codebook freeze` |
| 17 | Code the measurement sample | Each comment: `overall` −2..+2, `aspects` {name: −2..+2}, `stance` −2..+2 or null (news/topic) | JUDGEMENT | `blind-coder` agent on `crp batch` files |
| 18 | Code nuggets | Per transcript or thread: quote, observation, JTBD force, evidence type, friction and severity, speech act, tags (incl. `product:<name>`), aspect, sentiment, success, frame, stance | JUDGEMENT | Question 4: split between blind coder and main session |
| 19 | Validate nuggets | Quote in the cited turn (first turn only for forums; `...` elisions); allowed values; severity when friction; warnings for short quotes, "observed" in forums, observation repeating the quote | CHECK | `crp labels validate` + `crp verify` |
| 20 | Validate sentiment records | Refs exist and are in the sample; values in range; duplicates; missing stance; overall vs aspects pointing opposite ways; uncoded count | CHECK | `crp labels validate` |
| 21 | Measure sentiment and drivers | `drivers.py`: shares, intervals, driver ranking, author bootstrap, top-driver probability, direction, stance, before/after, split by source | COMPUTATION | `stats.py` → `crp analyse` |
| 22 | Explain the top drivers | AI makes sure triaged nuggets cover each top driver; finds more with `kwic.py`. The report flags drivers with no coded explanation | JUDGEMENT + CHECK | `SKILL.md` + `crp build` warning |
| 23 | Cluster nuggets | `themes.py`: TF-IDF + LSA (or MiniLM), k-means with k picked by silhouette, dominance flag | COMPUTATION | `crp themes` (new) |
| 24 | Look things up | `list_nuggets.py` (filter by force, tag, evidence, severity) and `kwic.py` (term in context) | COMPUTATION | `crp nuggets`, `crp kwic` (new) |
| 25 | Synthesise insights | Groups nuggets, searches for counter-evidence, keeps rare severity-3 friction, sets confidence, writes `insights.json` | JUDGEMENT | stays with AI |
| 26 | Check insight confidence | Warns if "high" lacks coverage or strong evidence, on single-voice insights, and when no counter-evidence is listed | CHECK | `crp validate` (new) |
| 27 | Write the outlook | `outlook.json` with ICD 203 likelihood words and review dates | **CUT** | removed (see DECISIONS.md) |
| 28 | Mark success moments | `"success": true` on nuggets where something clearly worked | JUDGEMENT | stays with AI |
| 29 | Write jobs | `jobs.json` in job-story form; warns on wrong form or fewer than two forces | JUDGEMENT + CHECK | AI writes; `crp validate` checks |
| 30 | Write opportunities | `opportunities.json` as "How might we"; kind must be one of five; needs nugget ids | JUDGEMENT + CHECK | AI writes; `crp validate` checks |
| 31 | Write hypotheses | Statement, importance, 2–4 signals with tests, not-distinguishing evidence, next step | JUDGEMENT | stays with AI |
| 32 | Score hypotheses | `hypotheses.py`: probability per signal from bootstrap replicates, leans, strength, priority, warnings | COMPUTATION | `crp hypotheses` (new) |
| 33 | Describe language | `language.py`: keyness (G², log ratio), shared phrases by reach, signal-language rates | COMPUTATION | `keyness.py` + `crp language` (new) |
| 34 | Build the report | `build_report.py`: `report.md` and `nuggets.csv` from the JSON files; quote-free by default for forums | COMPUTATION | `crp build` (Jinja template) |
| 35 | Build the dashboard | `build_dashboard.py` + `dashboard.js`: one HTML file with data embedded as JSON. Verdict words, safe wording and hatching are all computed in JS | COMPUTATION | `crp build` |
| 36 | Review report gaps | AI rereads "flagged moments with no nugget" and "possible synthesis gaps"; adds nuggets or insights | JUDGEMENT | stays with AI; lists computed by `crp build` |
| 37 | Record agreement | User drops in `validation.json` (`{"alpha", "n"}`) by hand; dashboard reports it | manual | `crp agreement export` / `score` |
| 38 | Deliver | Chat summary: headline insights, limitations, paraphrase not quotes, suggest a spot-check | JUDGEMENT | stays; numbers only via placeholders, `crp check-numbers` |
| 39 | Remind about ethics and terms | Reddit terms before collecting; keep `authors_private.json` private | JUDGEMENT | `SKILL.md` + `CLAUDE.md` |

## Method, as the skill defines it

### Sentiment unit and scale

- **Scale:** integers −2 to +2 for `overall`, each aspect, and `stance`. −2/+2 need strong language, a severe consequence or emphasis; plain complaints are −1 (coding guide §7).
- **Headline unit: per comment.** `negative_pct` = share of sampled comments with `overall` < 0. The demo headline (64.7%, 150 comments) is this.
- **Secondary, per person:** `authors_net_negative_pct` = share of sampled authors whose mean `overall` is below 0 (demo: 68.8% of 96 authors). The report prints it; the dashboard doesn't.
- **Scope:** measurement happens only in forum mode. Interview studies produce no sentiment figures.

### Drivers, "top driver" and "% of re-draws" (`drivers.py`)

- **Driver metric:** an aspect's `share_of_negative` = its negative mentions ÷ all negative aspect mentions in the sample.
- Also computed per aspect: `negative_rate` (negative ÷ its mentions), `mention_rate` (its mentions ÷ comments), mean score, count of −2s, distinct authors.
- **Ranking:** aspects with at least 3 mentions and a share above 0, sorted by share (descending), then mean (ascending).
- **Top driver in a re-draw:** the aspect with the most negative mentions in that replicate. Ties go to the alphabetically first aspect.
- **"% of re-draws":** replicates where the aspect is top ÷ B × 100, rounded to 1 decimal.
- Two quirks, both part of Question 6:
  - The replicate "top" considers every aspect, including those under the 3-mention floor.
  - A replicate with no negative mentions at all still names the alphabetically first aspect as top.

### Sampling and caps (`triage.py`)

| Setting | Value |
|---|---|
| Measurement sample size | 150 (`--sentiment-sample`) |
| Measurement seed | 7, fixed default, not logged |
| Measurement frame | all candidates, including opening posts; excludes promotional posts, echo replies (≤ 15 words matching the echo pattern) and non-post turns under 8 words |
| Caps on the measurement sample | **none** |
| Detail budget | 200 (`--budget`) |
| Detail order | every opening post; top-scored comments up to 20% of budget; flagged comments up to 40%; the rest spread across k-means topic clusters, nearest the centre first |
| Per-person cap (detail only) | 5 comments per author, own opening posts exempt |
| Batch size | 40 |
| Margin printed | ±98/√n points |

### Bootstrap and intervals

- **Resampled unit:** authors (a cluster bootstrap). Threads are not resampled.
- **Settings:** B = 2000, seed 11, 95% percentile intervals. Runs only with 20 or more authors.
- **Replaces:** with the bootstrap on, its ranges replace the headline's Wilson ranges.
- **Otherwise:** Wilson score intervals with z = 1.96.
- **Stored per replicate:** negative %, positive %, top aspect, and per-aspect `share_of_negative`, `negative_rate`, `mention_rate` (in `drivers_boot.json`, used by `hypotheses.py`).

### Thresholds

| Threshold | Value | Effect | Where |
|---|---|---|---|
| Authors for bootstrap and probabilities | ≥ 20 | Below: Wilson ranges still shown, no probabilities | `drivers.py`, `hypotheses.py` |
| Small sample | < 60 sampled comments | "Leaning" not "Mostly"; safe wording switches to "k of n … early signal"; hypothesis strength is weak | `drivers.py`, `dashboard.js`, `hypotheses.py` |
| Aspect minimum | ≥ 3 mentions | Below: listed as rare, not ranked | `drivers.py` |
| Period minimum | ≥ 15 comments | Only these periods count towards the trend verdict | `drivers.py` |
| Period unit (auto) | month if span > 60 days; week if > 14; else snapshot | | `drivers.py` |
| Trend verdict | first vs last usable period, Wilson intervals don't overlap | worsening / improving / no clear change | `drivers.py` |
| Before/after | ≥ 15 each side; Newcombe interval excludes 0 | rose / fell / no clear change | `drivers.py` |
| Dominant source | > 50% of sample, with more than one source | caution note | `drivers.py`, `parse_forum.py` |
| Verdict words | negative % − positive % > 15 points | "Mostly negative" (or "Leaning" when small); < −15 positive; else "Mixed". Stance uses for − against | `dashboard.js`, `build_report.py` |
| Agreement | alpha < 0.667 unreliable; < 0.8 tentative | trust section wording only; nothing is gated | `dashboard.js` |
| Hatched drawing | driver bar: < 3 authors; theme: ≤ 1 voice or low confidence; pains, successes, framing, opportunities: ≤ 1 voice; keyness term: reach < 3 | | `dashboard.js` |
| Insight "high" | forums: ≥ 5 authors and ≥ 1 observed or specific-incident nugget; interviews: ≥ max(3, a third of transcripts) | warning only | `validate.py` |
| Signal lean | probability ≥ 80% for, ≤ 20% against; proportion range wholly above/below 50%; voices: ≥ 2 and at least twice the other side | | `hypotheses.py` |
| Hypothesis strength | weak: < 5 voices or small sample; moderate: < 15; strong otherwise | | `hypotheses.py` |
| OCR check | overlap ≥ 0.6 and fewer than 2 missing words (words > 2 letters) | | `parse_forum.py` |
| Duplicates | exact match ≥ 6 words; near-duplicate: Jaccard ≥ 0.8 on 5-word shingles, ≥ 12 words | dropped | `parse_forum.py` |
| Promotional | promo pattern, or 3+ links | excluded from triage and sentiment | `parse_forum.py`, `triage.py` |
| High engagement | score ≥ max(5, thread's 90th percentile), or ≥ 2 agreeing echoes | flag | `signals.py` |
| Hesitation cluster | ≥ 8 words, ≥ 3 markers, density ≥ speaker mean + 1 SD (interviews only) | flag | `signals.py` |
| Clusters | k from 3 to min(12, n/4); needs ≥ 8 items; "dominated" if one voice > 50% of a cluster of 4+; silhouette < 0.1 loose, < 0.3 moderate | | `themes.py`, `dashboard.js` |

### Evidence grades

Strongest first: `observed` (in the session), `specific_incident` (a located past event), `habitual` (generalised practice), `opinion`, `hypothetical` (prediction or wish). `observed` and `specific_incident` count as strong. Forums shouldn't use `observed`. When a general claim is followed by a concrete example, code the example.

### Aspect lists per study type

**There are none.** Aspects are emergent: settled per study in the first sentiment batch (8–20, one or two lowercase words about the thing, not the feeling), then reused. The lens only changes the word used for them: product "feature or aspect"; brand "brand association"; news "sub-topic, claim or actor"; topic "sub-topic or argument". The lens also sets which sections appear (`_common.LENSES`).

### Stance, tone and framing

- `overall` is defined as "the comment's stance towards the product or topic under study, not the commenter's mood" (coding guide §7).
- `stance` (news and topic) is the position on the study's proposition, −2 against to +2 for, null if none is expressed. It is validated and measured but **not defined in the coding guide**.
- For news and topic studies the dashboard labels `overall` as "Tone of discussion". The blind-coder brief treats tone as mood ("an angry post can support something"). See Question 7.
- `frame` on nuggets uses Entman's four functions: problem, cause, moral, remedy (or none). It is defined in code only.
- A `question` tag feeds the news "questions people ask" section.

### Hypothesis scoring (`hypotheses.py`)

- **Signal tests:**
  - `top_driver`: P(aspect is top).
  - `greater`: P(a > b) on a measure.
  - `above`: P(measure > threshold).
  - `proportion`: k of n voices, with a Wilson range.
  - untested `for`/`against` voice tallies.
- **Overall lean:** all informative signals one way gives "leans for" or "leans against"; both ways gives "mixed"; none gives "can't tell from this data".
- **Priority:**
  - Low importance: "park for now".
  - Formed hypotheses: always "test first".
  - Stated hypotheses: "build on it, keep checking" only if not weak and leaning one way; otherwise "test first".
- The demo's "can't tell: test first" is lean "can't tell from this data" plus priority "test first".

### Keyness (`language.py`)

- Compares negative against positive comments in the measurement sample, on single words and two-word phrases, with stop words removed.
- Keeps a term if frequency ≥ 3, used by ≥ 2 people, G² ≥ 3.84 (p < .05) and log ratio > 0.
- Ranks by G² and shows the top 15 per side.
- No correction for multiple testing. It always shows when sentiment records exist.
- Shared phrases: 2–3 word phrases used by 3+ people, overlapping ones merged.

### Dashboard input format

- **Delivery:** one JSON object embedded in the page as `<script type="application/json" id="data">`. `build_data()` in `build_dashboard.py` assembles it from the working-folder files.
- **Top-level keys:**
  - `meta`: title, mode, sources, n_docs, n_items, n_people, window, n_nuggets, n_read, unit.
  - `hypotheses`: `hypotheses_result.json`.
  - `study` and `lens`.
  - `drivers`: `drivers.json` verbatim.
  - `insights`, `pains`, `successes`, `jobs`, `opportunities`, `outlook`, `products`, `frames`, `questions`, `language`.
  - `trust`: sample sizes, per-author cap, echoes, `validation`, silhouette, direction status, evidence mix, quotes, collection, collection_log, forum_checks.
- **Where the numbers come from:** the AI types none of them. It writes the statements and ids that code counts. The numbers the AI could still type are in its chat summary and in free-text fields (insight statements, observations, hypothesis statements).
- **Mixed units:** the dashboard's own safe wording mixes units: "Among {n_people} people posting in …, {x}% of a random sample of comments were negative". This is the sentence the review flagged (Question 2).

## Where the plan's layout has no home for existing code

The plan's `crp/` module list covers ingest, verify, anonymise, sample, codebook, batch, labels, agreement, stats, sensitivity, keyness, build and numbers. These existing scripts need a home too: `signals.py`, `themes.py`, `hypotheses.py`, the phrases and signal-rate parts of `language.py`, the checks in `validate.py` for insights, jobs and opportunities, and the helpers `view_transcript.py`, `list_nuggets.py` and `kwic.py`.

## Questions for Steeve

Answered 2026-09-26: see `DECISIONS.md` D7–D17. Q1–Q9 and Q11 as recommended; Q10: no demo study in the core.

1. **Scope of the port.** Most counting is already in the scripts. Should Phases 1–6 port them into `crp/`? That would add modules for signals, themes, hypotheses, language, validate and view. The old scripts would then be the reference for known-answer tests. *Recommend yes.* It is faster and lets Phase 5 match the old figures exactly on the same fixture and seed, not "within bootstrap noise".
2. **Headline unit.** The skill measures per comment, with per-person as a secondary figure. The write-up now uses comments. *Recommend* comments as the headline unit and per-person as the secondary. Rewrite the safe-wording template so it uses one unit throughout.
3. **Caps on the measurement sample.** The skill caps only the detail selection (5 per person). The measurement sample is an uncapped simple random sample, and the author bootstrap handles clustering. The plan applies a per-person cap and a per-thread cap (10%) to the measurement sample. That changes what the headline estimates: capped posters and threads get less weight. *Recommend* following the plan, as the review decided. Also report the uncapped figure in the sensitivity check, so the effect of the caps is visible. Which per-person cap value: the skill's 5?
4. **What the blind coder codes.** The measurement sample (overall, aspects, stance) fits a codebook and can be coded blind. Nuggets can't be fully blind: observations are interpretive, and the skill codes them "from the neutral research questions". *Recommend:* the blind coder codes the measurement sample, plus the categorical nugget fields (force, evidence grade, friction and severity, aspect, sentiment) on the detail selection. The main session writes observations and insights, and sees the neutral research questions but never the sealed prior.
5. **Below 20 people.** The skill still shows Wilson ranges; CLAUDE.md says "counts only, no ranges". *Recommend CLAUDE.md's rule.* Wilson ranges assume independent comments, which is wrong exactly when a few people post a lot.
6. **Bootstrap details.** The skill uses B = 2000; the plan says 5000. The before/after test uses Newcombe intervals, which ignore clustering; the plan says use the same bootstrap. There are also the two top-driver quirks above. *Recommend* B = 5000 and the bootstrap for before/after. Also: restrict "top" to the ranked aspects, and count replicates with no negatives as "no top driver". Each change gets a line in DECISIONS.md with the old and new demo figures.
7. **Stance and tone definitions.** The coding guide defines `overall` as evaluation of the subject, "not the commenter's mood". The dashboard calls it "tone", and the blind-coder brief treats tone as mood. `stance` and `frame` have no written definitions. *Recommend:* define `overall` as evaluation of the subject, labelled "sentiment" everywhere. Define `stance` as position on the proposition. Write both into `reference/` before any codebook freeze. Keep mood out of the codebook.
8. **Mixed studies.** `study_mode()` returns "interview" if any source is an interview. So a mixed study would count each forum thread as one voice and skip forum rules. *Recommend:* treat source type per post, run all forum statistics on forum posts only, and give interviews their own section with counts and no percentages.
9. **Collection log columns.** The skill logs results_seen, kept and why_excluded; the plan logs source, search_term, date, reason and neutral. *Recommend* keeping all of them: source, search_term, date, reason, neutral, results_seen, kept, why_excluded.
10. **Demo fixture.** Only the built dashboards exist (results), not the inputs: captures, sentiment batches, nuggets. *Recommend* building a new synthetic fixture in Phase 1 and running the old scripts on it as the reference. Do you have the original demo working folder? If so, it goes in `tests/fixtures/demo/` instead.
11. **Interview anonymising.** Speaker names in interview transcripts are kept as-is today. *Recommend* the same salted-HMAC codes as forum authors.
