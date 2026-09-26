---
name: interview-synthesis
description: Agentic research pipeline that turns interview transcripts, Reddit threads, or posts pasted or screenshotted from any forum into an evidence-checked synthesis and interactive dashboard about a product, brand, news story or topic - themes, pain points, success moments, jobs to be done, opportunities, sentiment and its drivers, stance and framing, direction over time, language used, a calibrated outlook, and prioritised hypotheses to take into discovery. Use whenever the user shares or points to interviews, Reddit or forum posts, or screenshots of discussions and wants them analysed, synthesised or "churned", or mentions interview or research synthesis, thematic coding, nuggets, JTBD, social listening, community or brand sentiment, reaction to a news story, pre-discovery for a pitch, or forming hypotheses to test. For open discussion without source material, use ux-discovery-deep-think.
---

# Interview synthesis

Modes share one pipeline:
- **Interview mode** (below): 6–20 interview transcripts.
- **Reddit mode**: 200–1,000 posts and comments. Follow the "Reddit mode" section,
  which replaces steps 1–3 and changes a few rules.
- **Pasted posts and screenshots from any forum**, often for pitch pre-discovery with
  competing hypotheses: follow "Pitch pre-discovery".

Every study starts with `python $S/init_study.py --work WORK --subject "..." --type
product|brand|news|topic`. The type sets the lens: what gets coded (jobs to be done for
products; associations for brands; stance, framing and questions for news and topics)
and which dashboard sections appear. News and topic studies need `--stance-target` (the
proposition people are for or against) and usually `--event-date`.

Turns interview transcripts into a traceable synthesis. Scripts do the
mechanical passes; you do the interpretive coding and synthesis. Every claim in the
final report links back to a verbatim quote that the validator has checked.

The key constraint is context: never load all transcripts at once. Code one
transcript at a time, write its nuggets to disk, and synthesise from the nuggets.

## Setup

Scripts live in this skill's `scripts/` folder (call it `$S`). Pick a working folder
(`WORK`, e.g. `./synthesis`) next to the user's transcripts. Requirements:
Python 3.9+, `scikit-learn`, `numpy`; `python-docx` for .docx; optionally
`sentence-transformers` for better clustering.

```bash
pip install scikit-learn numpy python-docx   # add --break-system-packages if pip refuses
```

Before starting, ask the user (once, briefly) for anything you can't infer:
what the study was about / the research questions, and the interviewer's name if
speaker labels are just names. The research questions shape what counts as a
useful nugget.

Read `references/coding_guide.md` before coding the first transcript.

## Pipeline

### 1. Parse

```bash
python $S/parse_transcripts.py path/to/transcripts/ --work WORK [--interviewer "Ana"]
```

Check the printed I/P role assignment for every transcript. The heuristic guesses the
interviewer as the speaker who asks the most questions; it can be wrong for short or
unusual interviews. If any are wrong, re-run with `--interviewer`. Tell the user about
any parse warnings (single speaker, UNKNOWN text).

### 2. Signal pass

```bash
python $S/signals.py --work WORK
```

If it warns that transcripts look cleaned (no fillers or repairs), tell the user
hesitation signals will be weak and a verbatim export would help. Continue anyway.

### 3. Code each transcript (one at a time)

For each transcript id in `WORK/manifest.json`:

1. `python $S/view_transcript.py --work WORK --id T01` (use `--range 1-120` chunks
   for long interviews)
2. Write `WORK/nuggets/T01.json` following the coding guide. Pay attention to
   flagged turns, but only code what the content supports.
3. `python $S/validate.py --work WORK --id T01` and fix every ERROR. The usual
   error is a quote that was paraphrased instead of copied; the validator names
   the right turn when the quote exists elsewhere.
4. Move to the next transcript. Keep a running tag list (read tags from earlier
   nugget files) so tags stay consistent.

Give the user a one-line progress update every few transcripts.

### 4. Cluster

```bash
python $S/themes.py --work WORK            # clusters nuggets
python $S/themes.py --work WORK --embed    # if sentence-transformers is installed
```

Clusters are a second opinion. Clusters marked "mostly Txx" come from one talkative
participant. A low silhouette means the grouping is loose.

### 5. Synthesise

Work from nuggets, not raw transcripts. `python $S/list_nuggets.py --work WORK`
prints one line per nugget; filter with `--force push`, `--tag export`,
`--friction --min-severity 3`, `--evidence observed,specific_incident`, and add
`--quotes` when you need the wording. Then:

1. Group nuggets into candidate insights, guided by the research questions,
   JTBD forces, friction severity and the clusters.
2. For each candidate, search for counter-evidence across all nuggets.
3. Check that low-frequency, high-severity friction (severity 3) isn't lost just
   because it's rare.
4. Write `WORK/insights.json` (format in the coding guide) and run
   `python $S/validate.py --work WORK`. Act on warnings about overconfident insights.

Aim for roughly 5–12 insights. Fewer, better-supported insights beat a long list.

### 6. Report

```bash
python $S/build_report.py --work WORK --title "Study name"
```

Read `WORK/report.md`. Look at two sections especially:
- **Flagged moments with no nugget**: re-read those turns; add nuggets if you missed
  something, then rebuild.
- **Possible synthesis gaps**: wide-coverage clusters no insight uses. Either add an
  insight or be ready to say why the cluster doesn't matter.

Then deliver `report.md` (and `nuggets.csv` for tools like Dovetail or Airtable).
In your message, give the headline insights in a few sentences and state the
limitations plainly: AI-assisted coding, which transcripts looked cleaned, any
single-source insights. Suggest the user spot-check a few nuggets from one transcript.

## Reddit mode

Same idea, three differences: a different parser, a triage step (too many comments
to read one by one), and coverage counted by distinct author. Read section 6 of the
coding guide first.

**Getting data.** The user supplies files; this skill doesn't scrape. Common sources:
a thread's JSON (the thread URL with `.json` appended, optionally `?limit=500`),
Pushshift/Arctic Shift style NDJSON dumps, or CSVs from their own API scripts. Before
collecting, remind the user once to check Reddit's terms for their use (commercial use
of Reddit data has restrictions). If the parser reports collapsed "load more" comments,
tell the user the export is incomplete.

```bash
python $S/parse_reddit.py path/to/threads/ --work WORK   # anonymises authors
python $S/signals.py --work WORK                           # flags + echo counts
python $S/triage.py --work WORK --budget 200               # picks what to code
```

With fewer candidates than the budget, triage keeps everything. Otherwise it keeps
every post, top-scored comments, flagged comments and a spread across topic clusters,
capped per author. Show the user the triage summary (clusters and counts) before
coding; if a cluster they care about got few picks, raise `--budget`.

Then two coding passes. Settle the aspect list early (coding guide section 7) and
use it in both.

**Pass A: sentiment (random sample).** Code every comment in each sentiment batch at
aspect level (coding guide section 7), then check and measure:

```bash
python $S/view_transcript.py --work WORK --sentiment-batch 1   # ... through the last batch
python $S/validate.py --work WORK                               # merge synonym aspects it lists
python $S/drivers.py --work WORK                                # sentiment, drivers, direction
```

**Pass B: explanations (triage selection).** Code the triaged comments into nuggets,
batch by batch, giving each an `aspect` and `sentiment` where it fits:

1. `python $S/view_transcript.py --work WORK --triage --batch 1`
2. Append nuggets to `WORK/nuggets/<thread id>.json` (one file per thread; a batch
   can span threads). Nugget ids stay `T01-N01` style, numbered per thread.
3. `python $S/validate.py --work WORK --id T01` for each thread touched; fix errors.
4. Next batch.

Make sure the top drivers from `drivers.py` get explained: if few triaged comments
cover a driver, find more with `kwic.py` and code them.

Steps 4–5 (cluster, synthesise) are the same. Then write `WORK/outlook.json`
(coding guide section 8): 3–6 forward-looking calls using the ICD 203 likelihood
words, each with its basis, what would change it, and a review date. Validate, then:

```bash
python $S/build_report.py --work WORK --title "..."                   # quote-free (default for Reddit)
python $S/build_report.py --work WORK --title "..." --include-quotes  # internal only
```

The Reddit report is strategic and quote-free: it opens with sentiment, its drivers,
direction of travel and outlook, and shows evidence as paraphrased observations with
ids. Verbatim quotes stay in the working files only, to check nothing was invented.
Your chat summary should also paraphrase rather than quote. Remind the user that
forum voices are self-selected and vocal, keep `WORK/authors_private.json` private,
and note when the data is a snapshot (no direction) rather than a trend. For a real
trend, advise collecting threads spread over several months.

## Pitch pre-discovery: pasted posts, screenshots, and hypotheses for discovery

For quick studies built from posts the user copies or screenshots across forums (any site,
not only Reddit), usually ahead of a pitch. The output is findings plus prioritised
hypotheses to take into real discovery; this data suggests, it doesn't prove.

1. **Set up.** Run `init_study.py` (subject, lens, neutral research questions). If the user
   already believes something (e.g. their strategy), write it now as a `stated` hypothesis
   in `WORK/hypotheses.json` (coding guide 11), before reading any posts. Going in blind is
   fine too. Ask for the searches they ran and write `WORK/collection_log.json`
   (coding guide 10); if they only searched for evidence of their view, suggest neutral
   searches.
2. **Capture.** Put the originals in one folder. For each paste or screenshot, write a
   capture file (coding guide 10), then check them:
   ```bash
   python $S/parse_forum.py --work WORK --sources path/to/originals --ocr
   ```
   Fix every ERROR (usually a tidied sentence). Look at every OCR warning against the image.
   Without Tesseract, screenshots stay unverified and the dashboard says so.
3. **Measure and code.** Run `signals.py` and `triage.py` (small studies keep everything;
   promotional posts are excluded), code the sentiment sample and nuggets from the neutral
   research questions, then `drivers.py`. With 20+ authors it resamples people to give
   honest ranges and the probability each aspect is the top driver.
4. **Synthesise the findings** (insights, pains, successes, jobs, opportunities, outlook).
5. **Hypotheses for discovery, last.** Add `formed` hypotheses the findings suggest,
   including rivals to any stated one, each with signals and a next step (coding guide 11):
   ```bash
   python $S/hypotheses.py --work WORK
   python $S/language.py --work WORK
   python $S/build_report.py --work WORK
   python $S/build_dashboard.py --work WORK
   ```
6. **Deliver honestly.** Lead with the findings, then hand over the hypotheses as where
   discovery should start, highest priority first. Be plain about the user's own
   hypothesis whichever way it leans. Give the dashboard's "safe wording" for decks, and
   point out a dominant source, a small sample and unverified screenshots.

## Dashboard (the main deliverable)

The dashboard is a single self-contained HTML page covering: the verdict and
sentiment (with likely ranges), drivers and strengths, direction of travel, themes,
pain points, success moments, jobs to be done, opportunities, alternatives in play,
outlook (probabilities), language used, and how much to trust the findings. Tapping
an aspect focuses every section on it; anything resting on one voice or low
confidence is drawn hatched.

To fill every section, after synthesis:
1. Mark `"success": true` on nuggets where something clearly worked (coding guide 9).
2. Write `WORK/jobs.json` and `WORK/opportunities.json` (coding guide 9).
3. Run the analysis scripts and build:

```bash
python $S/language.py --work WORK          # distinctive words, shared phrases, kinds of language
python $S/validate.py --work WORK
python $S/build_report.py --work WORK --title "..."
python $S/build_dashboard.py --work WORK --title "Subject"
```

Sections with no data show which step fills them, so the dashboard can be built at
any stage. Reddit dashboards never contain verbatim quotes. If `WORK/validation.json`
exists (`{"alpha": 0.82, "n": 120}` from a human-vs-AI agreement check), the trust
section reports it; otherwise it says agreement hasn't been measured. Deliver
`dashboard.html` as the main output and `report.md` as the written companion.

## Useful extras

- `python $S/kwic.py --work WORK --term "sync"` shows every use of a term in context,
  handy for checking mental models ("do they mean sync the way we do?").
- To re-run after adding transcripts: re-parse all files (ids follow filename order,
  so keep names stable), re-run signals, then code only the new transcripts.

## Principles

- Evidence first: a quote that fails validation is not evidence.
- Report coverage honestly ("4 of 12 participants"), not "users said".
- Hesitation and language signals are pointers, not measurements of cognitive load.
- Tag named products as `product:<name>` so the report can map what people leave,
  move to and stay with.
- Keep interpretation separate from evidence: quote in `quote`, meaning in `observation`.
