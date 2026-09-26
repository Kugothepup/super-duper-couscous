# Decisions

Method decisions for the community research pipeline, oldest first. Each says what changed from the `interview-synthesis` skill, why, and who decided. Where `BUILD_PLAN.md` and this file differ, this file wins.

## Decided in the review (2026-09-26)

| # | Decision | Was (skill) | Now | Why |
|---|---|---|---|---|
| D1 | Outlook section cut | `outlook.json` with ICD 203 likelihood words and review dates; validated in `validate.py`; shown in `build_report.py`, `build_dashboard.py` and `dashboard.js`; coding guide §8; `LIKELIHOOD` in `_common.py` | Removed from the method, outputs and code. Brier scoring dropped from the plan | Forecasts from a forum snapshot can't be calibrated from this data. The write-up no longer offers them |
| D2 | Per-thread cap added | No thread cap; per-author cap of 5 on the detail selection only | No thread contributes more than 10% of the measurement sample (plan default). How the caps apply: D9 | One pile-on thread shouldn't look like a trend |
| D3 | Ranges from people and threads | Bootstrap over authors only | Cluster bootstrap run twice, over people and over threads; the wider range is the headline | Posts in a thread are related, as are posts by one person |
| D4 | Leave-one-out sensitivity added | Only a warning when one source supplies over 50% | Headline recomputed with each source, each search term and each of the 5 largest threads left out. Report the min–max and the removal that moved it most | Shows when the collection, not the people, carries the finding |
| D5 | Agreement check gates results | `validation.json` typed in by hand; wording only, nothing gated | `crp agreement score` computes Krippendorff's alpha. At 0.80 or above, results are verified. From 0.667 to 0.80 they are tentative (amber). Below 0.667 or not yet run, they are unverified (red banner on every page) | Evidence that exists but was read wrongly is the main unmeasured risk |
| D6 | Keyness gets a minimum frequency and FDR correction | Frequency ≥ 3, reach ≥ 2, G² ≥ 3.84 per term, no correction, always shown | Frequency ≥ 5, used by ≥ 3 people, Benjamini–Hochberg at q = 0.05, section hidden below the early-signal threshold | Testing hundreds of words at p < .05 finds "significant" noise |

## Decided on the Phase 0 inventory (2026-09-26)

Steeve's answers to the questions in `INVENTORY.md`. Q1–Q9 follow the recommendations there.

| # | Question | Decision | Why |
|---|---|---|---|
| D7 | Q1 Scope | Port the skill's 18 scripts into `crp/` rather than rewrite. This adds modules for signals, themes, hypotheses, language, validate and view (mapping in `BUILD_PLAN.md`). The old scripts are the reference for comparison tests on the same inputs | Most counting already exists and works; tests can compare old and new directly |
| D8 | Q2 Headline unit | Per comment, as the skill measures it. The per-person share of net-negative authors is the secondary figure. Every sentence and template uses one unit throughout | The random sample is a sample of comments; the old safe wording mixed people and comments |
| D9 | Q3 Caps on the measurement sample | The sampling frame is capped at 5 comments per person (the skill's detail cap) and 10% of the sample per thread (D2). The sensitivity check also reports the headline without caps | Keeps prolific posters and pile-ons from carrying the headline, while showing what the caps did |
| D10 | Q4 What the blind coder codes | The blind coder codes the measurement sample (overall, aspects, stance). On the detail selection it codes the categorical nugget fields: force, evidence grade, friction and severity, aspect, sentiment. The main session writes observations and insights from the neutral research questions, and never sees the sealed prior before labels are locked | Categorical labels can be coded blind; interpretation needs the research questions |
| D11 | Q5 Below 20 people | Counts only: no ranges and no probabilities (was: Wilson ranges still shown) | Wilson ranges assume independent comments, which fails exactly when a few people post a lot |
| D12 | Q6 Bootstrap details | B = 5000 (was 2000). Before/after uses the same cluster bootstrap (was Newcombe). "Top driver" in a re-draw considers only ranked aspects (≥ 3 mentions), and a re-draw with no negative mentions counts as no top driver. Old and new figures for each change are logged here once the test fixture runs | Consistent handling of clustering; removes two edge-case artefacts |
| D13 | Q7 Sentiment and stance | `overall` is the writer's evaluation of the subject, labelled "sentiment" everywhere (the dashboard said "tone"). `stance` is the position on the study's proposition, −2 against to +2 for, null if none is expressed. Mood is not coded. Both definitions, and `frame`, are written into `reference/` before any codebook freeze | The coding guide, dashboard and coder brief used three different meanings |
| D14 | Q8 Mixed studies | Source type is set per post. All forum statistics use forum posts only. Interviews get their own section with counts and no percentages (was: one interview switched the whole study to interview rules) | Interviews are recruited and prompted; pooling them distorts forum figures |
| D15 | Q9 Collection log | Columns: source, search_term, date, reason, neutral (y/n), results_seen, kept, why_excluded | Keeps the skill's record of what each search yielded, plus the plan's neutral flag |
| D16 | Q10 Demo study | No demo study in the core: not in `crp/`, not in `tests/`, not required by any phase check. Tests use small synthetic fixtures built for the tests. The Notion demo can live outside the core as a showcase | Steeve: "can use it to showcase, but it shouldn't exist in the core" |
| D17 | Q11 Interview anonymising | Interview speaker names get the same salted-HMAC person codes as forum authors (was: names kept as-is) | Interview transcripts are personal data too |

## Decided while building

| # | Phase | Decision | Why |
|---|---|---|---|
| D18 | 1 | `Post` keeps the plan's fields and adds the skill's turn fields the port needs: `role` (participant or interviewer), `kind` (post, comment or turn), `score` and `date_approx`. `capture_method` adds `export` for Reddit exports. `scikit-learn` is a pinned dependency | Follows from D7: the ported parsers, triage and clustering use these |
