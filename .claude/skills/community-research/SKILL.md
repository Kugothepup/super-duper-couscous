---
name: community-research
description: Turns forum threads (Reddit or any forum, pasted, screenshotted or exported) and interview transcripts into a checked dashboard, a report and prioritised hypotheses for discovery, about a product, brand, news story or topic. The AI transcribes, drafts the codebook, hands coding to the blind-coder agent and writes the synthesis; the crp package does every count. Use when Steeve shares posts, threads, screenshots or transcripts to analyse, asks about community or brand sentiment, reaction to a news story, pitch pre-discovery or hypotheses to test, or asks to start, continue or build a study.
allowed-tools: Bash(python -m crp:*), Bash(.venv/bin/python -m crp:*)
---

# Community research

## The one rule

**The AI reads and labels. Code counts.**

You transcribe posts, draft the codebook, hand coding to the `blind-coder` agent, and write the synthesis in words. `crp` draws samples, checks transcriptions, anonymises, and computes every count, percentage, range and probability.

Never compute, estimate or round a number in conversation and put it in an output. When you tell Steeve a number, quote it as a `crp` command printed it. If a number is needed and no command produces it, stop and ask; don't work it out yourself.

## Ground rules

- **Never read anything under `studies/*/sealed/`**, by any means. Only `crp unseal` opens it, after the labels are locked. After that, read the copy in `results/prior.md`.
- **Coding happens only in the `blind-coder` agent.** Its prompt holds exactly two paths, the batch file and the output path. No subject, questions, aims or findings.
- **Don't change a frozen codebook.** A change means a new version and coding everything again, which is Steeve's call.
- **Method changes need Steeve.** If a stage seems wrong for a study, write it in `DECISIONS.md` and ask. Don't quietly work around it.
- Raw posts, usernames and screenshots stay in `studies/<id>/raw/`. Never print or copy the salt in `.secrets/`.
- Interview transcripts are their own source type. Never pool them into forum percentages.
- British spelling in everything Steeve sees.

## Running crp

Every command is `python -m crp <command> studies/<id> [options]`. In this project the package lives in `.venv`, so run `.venv/bin/python -m crp …` (system Python lacks the dependencies). Each command checks its inputs, records itself in `results/run_manifest.json`, and prints what to do next. When a command stops with an error, fix the input it names. Don't find a way round it.

`crp status studies/<id>` shows where a study is up to: each stage done, to do, stale, blocked, or waiting on Steeve or on you, and what comes next. Start there when picking a study back up.

## Stages

| # | Stage | You do (judgement) | crp does (computation) | Stop |
|---|---|---|---|---|
| 0 | Set up | Ask for subject, lens, neutral questions | `new` | Steeve writes his sealed prior |
| 1 | Collect | Write capture files, fill the collection log | `ingest`, `verify`, `anonymise`, `signals` | **1: is the collection complete?** |
| 2 | Sample | Explain the caps and the detail selection | `sample` | If the thread cap stops it |
| 3 | Codebook | Draft `codebook.yaml` | `codebook freeze` | **2: Steeve approves the codebook** |
| 4 | Code | Delegate each batch to `blind-coder` | `batch`, `labels validate`, `labels lock` | |
| 5 | Agreement | Nothing to judge | `unseal`, `agreement export`, `agreement score` | **3: Steeve codes the sheet** |
| 6 | Analyse | Read the output | `analyse` | |
| 7 | Synthesise | Observations, insights, jobs, opportunities, hypotheses, summary | `view`, `themes`, `validate` | |
| 8 | Build | Fix wording the checks reject | `analyse`, `build`, `check-numbers` | **4: before building** |
| 9 | Deliver | Plain-English findings and limits | | |

At a stop, show Steeve what the commands printed and wait for his answer before going on.

### 0. Set up

Ask Steeve once, briefly, for anything you can't infer:
- the subject;
- the lens: `product`, `brand`, `news` or `topic`;
- two to four neutral research questions;
- for news and topic studies, the proposition people are for or against (`--stance-target`), and usually `--event-date`.

```
crp new <id> --subject "…" --type news --question "…" --stance-target "…" --event-date YYYY-MM-DD --population "…" --owner Steeve
```

If the study has interview transcripts, ask Steeve before you read any of them, or code or batch them. Anything read in this session goes through Anthropic's cloud (D38). Forum posts are public already.

Then tell Steeve that if he believes something going in, he should write it himself in `studies/<id>/sealed/prior.md` before any posts are read. Don't ask what it says, and never open it. Going in blind is fine too. Every search goes in `collection_log.csv`, including searches that kept nothing (`reference/capture.md`). If every search looks for evidence of his view, suggest neutral ones.

### 1. Collect and capture

Steeve puts his sources under `studies/<id>/raw/`: pasted pages as `.txt`, screenshots, Reddit exports in `raw/reddit/`, and transcripts in `raw/interviews/`. Before Reddit data is collected, remind him once to check Reddit's terms for his use.

For a copied Reddit thread page, `crp paste studies/<id> page.txt --search-term "…"` saves it and writes its capture file. It reports anything it skipped, and how many replies Reddit had collapsed; tell Steeve, so he can expand them and paste again with `--replace`. For other pastes and screenshots, write `raw/capture/<name>.json` yourself following `reference/capture.md`. Copy text exactly; the checker rejects tidied wording. Exports and transcripts need no capture file. Then run:

```
crp ingest studies/<id>       # check the interviewer and participant roles it prints
crp verify studies/<id>       # fix every tidied or failed capture, then ingest and verify again
crp anonymise studies/<id>
crp signals studies/<id>
```

Look at every OCR-flagged post against its image. Without Tesseract, screenshots stay "unverified", and the outputs say so.

**Stop 1: is the collection complete?** Show Steeve, as the commands printed them:
- threads, posts and people;
- the transcription checks;
- anything dropped: duplicates, bots, promotional posts, collapsed replies;
- the collection log.

Ask whether anything is missing. Adding threads now is cheap. Once coding has started, added threads need a new round (see "Adding threads later").

### 2. Sample

```
crp sample studies/<id>
```

It draws a random measurement sample (for every percentage) and a purposive detail selection (for explanations, never for percentages).

If it stops because there are too few threads for the 10% thread cap, tell Steeve. The better fix is more threads. `--thread-cap-pct` loosens the cap, and the outputs then say so. Loosen it only if he says to.

Show him the detail selection's topic clusters. If one he cares about got few picks, re-run with a larger `--budget`. The sample can't be redrawn once batches exist.

### 3. Codebook

Read `reference/codebook.md` and `reference/sentiment-stance-frame.md`. Read a spread of posts (`crp view thread`, `crp view detail`, `crp view kwic`) to settle the aspects. Then draft `codebook.yaml`: the aspects with definitions, the lens's variables, and the coding rules.

**Stop 2: Steeve approves the codebook.** Show him in plain words:
- the aspects and what each covers;
- each variable and its values;
- the rules.

Make his changes. When he approves it:

```
crp codebook freeze studies/<id>
```

Freezing checks the design (for example, `overall`, and `stance` for news and topic studies) and locks it.

### 4. Blind coding

```
crp batch studies/<id>
```

For each batch, start a `blind-coder` agent whose whole prompt is the two paths `crp batch` printed: `studies/<id>/batches/batch_NNN.jsonl` and `studies/<id>/labels/batch_NNN.labels.jsonl`. Add nothing else. Batches can run in parallel.

```
crp labels validate studies/<id>
```

If a batch fails, run the blind coder on that batch again. Never edit a labels file yourself. When every batch passes:

```
crp labels lock studies/<id> --coder-model <the model the blind-coder agent ran on>
```

### 5. Unseal and agreement

```
crp unseal studies/<id>
crp agreement export studies/<id>
```

If `unseal` says the prior changed after the first ingest, the report must say so.
If Steeve went in blind, there's no prior: `unseal` says so, and you skip it. Every hypothesis is then `formed`.

**Stop 3: Steeve codes the agreement sheet.** He codes `human/agreement_sheet.csv` with `human/agreement_guide.md` and saves it as `human/human_labels.csv`. Never tell him what the blind coder chose for an item on the sheet. Then:

```
crp agreement score studies/<id>
```

Until it's scored, every section carries the red "unverified" banner. If Steeve says so, go on to stages 6 and 7 while he codes.

### 6. First analysis

```
crp analyse studies/<id>
```

Read what it prints:
- the headline;
- the drivers and rare aspects;
- the leave-one-out range and what moved it most;
- the estimate without caps;
- warnings.

The synthesis explains these. It never restates their numbers.

### 7. Synthesise

Read `reference/synthesis.md` and `reference/hypotheses.md`. Work from the coded detail posts, not from whole threads.

1. `crp view detail studies/<id> --batch N` a batch at a time. Write `synthesis/observations.jsonl`: at most one observation per coded detail post, with a verbatim quote and tags. Run `crp validate` as you go.
2. `crp themes studies/<id>` gives a second opinion. `crp view observations studies/<id> --friction --min-severity 3` and the other filters help you find groups.
3. Write `insights.json` (with counter-evidence), then `jobs.json` for product studies, then `opportunities.json`.
4. Write `hypotheses.json`. `stated` hypotheses come only from `results/prior.md`, after unseal. `formed` ones come from the findings, including at least one rival to each stated one.
5. Write `summary.md`: a short paragraph in words. Numbers appear only as placeholders such as `{{ headline.negative.k }}`, never as typed digits.

Check each top driver has coded explanations (`crp view observations`). If one is thin, say so in the summary, and offer Steeve a top-up: find posts that explain it (`crp view kwic`) and add them in a new round with `crp topup` (see "Adding threads later", D37). Never code extra posts any other way. Run `crp validate studies/<id>` until it shows 0 errors, and act on its warnings.

`crp analyse` also draws "Have we heard enough?" from your observation tags: topics found against posts read, averaged over many random reading orders (D39). Keep tags consistent, since two names for one topic count as two. Read what it prints; don't restate its numbers.

### 8. Build

```
crp analyse studies/<id>
```

**Stop 4: before building.** Give Steeve the verdict and the main findings, quoting the analyse output and your synthesis, with the agreement status. Ask whether to build.

```
crp build studies/<id>            # no quotes, thread titles or person codes: safe to share
crp check-numbers studies/<id>
```

If `build` refuses because some text repeats six words of a post, reword that observation or summary in your own words. Never change a label. If `check-numbers` flags a number, replace it with a placeholder, or write a non-data quantity in words, then build again. `crp build --with-quotes` makes an internal version in `results/internal/`, only when Steeve asks for one. It's never shared.

### 9. Deliver

Point Steeve to `results/dashboard.html` and `results/report.md`. Lead with the findings in plain words, then give the hypotheses as where discovery should start, highest priority first. Be plain about his own hypothesis, whichever way it leans. State the limits:
- forum voices are self-selected;
- a snapshot isn't a trend;
- early-signal or count-only results;
- agreement status;
- unverified screenshots;
- a thread or source that moved the headline;
- any loosened cap.

Paraphrase posts rather than quoting them. `reference/wording.md` has the wording rules.

## Adding threads later

- **Before `crp batch`:** add the new captures and re-run from `crp ingest`. `crp sample` keeps the seed.
- **After the labels are locked:** start a new round (D35):
  1. `crp round studies/<id> --reason "added three threads from r/…"` keeps the current round in `rounds/<n>/` for comparison.
  2. Add the threads (`crp paste`, captures or exports), then run `ingest`, `verify`, `anonymise`, `signals`, and `sample` with the settings `crp round` printed. Thread and post ids stay the same, and the seed carries over, so earlier picks mostly stay picked.
  3. `crp batch` reuses the last round's labels for every item the coder would see unchanged. Only the batches it lists go to the blind coder. Lock with the same coder model; a different model means `crp batch --no-reuse`.
  4. Update the synthesis for the new posts, run a new agreement check, analyse and build. The outputs show each round, and how much the headline moved.
- **To explain a thin driver (D37):** start a round with `--reason "top-up: …"`, then `crp topup studies/<id> T03-p12 … --reason "…"`, then `crp sample` and `crp batch`. Only the named posts are coded, and no percentage changes.
- **Between rounds, a change shows what the new material did, not a change over time.** The rounds overlap. Say so.
- **`crp reset --yes`** archives every generated file and unfreezes the codebook, so the study starts again from its sources. Only run it when Steeve asks.

## Reference

- `reference/capture.md`: capture files, pasted Reddit pages, screenshots, exports, transcripts, and the collection log.
- `reference/codebook.md`: designing a codebook for each lens, aspects, coding rules, and the detail variables with evidence grades.
- `reference/sentiment-stance-frame.md`: what sentiment, stance and frame mean, and how they differ (D13).
- `reference/synthesis.md`: observations, insights and confidence, jobs, opportunities, the summary, and common mistakes.
- `reference/hypotheses.md`: stated and formed hypotheses, signals, and the test-plan format.
- `reference/wording.md`: how findings are worded in outputs and in conversation.
