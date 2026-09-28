# Community research pipeline

A research tool that turns forum posts, screenshots and interview transcripts into traceable evidence: a dashboard, a report and prioritised hypotheses for discovery. Owner: Steeve. The method is described in `.claude/skills/interview-synthesis/SKILL.md` (renamed to `community-research` in Phase 7). The build is in `BUILD_PLAN.md`.

## The one rule

**The AI reads and labels. Code counts.**

- AI judgement: transcribing posts, drafting the codebook, coding posts (via the `blind-coder` agent only), explaining themes, drafting test plans, and writing prose.
- Code (`crp/`, run as `python -m crp …`): drawing samples, caps, quote and OCR checks, anonymising, every count, percentage, range and statistic, agreement scores, and filling numbers into outputs.
- **Never compute, estimate or round a number in conversation** and put it in an output. If a number is needed and no command produces it, add one (with a test) or stop and ask.
- **Never pick a "random" sample yourself.** Use `crp sample`.

## Blinding

- **Never read anything under `studies/*/sealed/`**, by any means, including `cat` or grep through Bash. Only `crp unseal` opens it, after `crp labels lock` has run.
- Coding happens only in the `blind-coder` agent, on batch files made by `crp batch`. When delegating, the prompt contains **only** the batch file path and the output path. No study aims, no hypotheses, no summary of what's been found so far.
- Don't edit a locked codebook (`codebook.lock` exists). Changing it means a new codebook version and re-coding, and that is Steeve's call.

## Method changes need Steeve

Port the existing skill's method faithfully. That covers the driver metric, sentiment unit, evidence grades, aspect lists and thresholds. If something looks wrong, or the build plan and the skill disagree, **write it in `DECISIONS.md` and ask**. Don't silently change it. Read `DECISIONS.md` before each phase: where it and `BUILD_PLAN.md` differ, `DECISIONS.md` wins.

Current thresholds (from the skill, keep unless told otherwise):
- Fewer than 20 distinct people: no probabilities or ranges; counts only.
- Fewer than 60 sampled comments: "early signal" label on every result.
- Agreement (Krippendorff's alpha): 0.80 or above is verified; 0.667 to 0.80 is tentative (amber); below 0.667, or not yet run, is unverified (red banner).

## Data handling

- Raw posts, usernames and screenshots stay in `studies/*/raw/` and are gitignored. Only anonymised data (`posts.jsonl` with person codes) is committed, if anything is.
- Person codes are salted HMACs. The salt lives in `.secrets/salt` and is never printed, logged or committed.
- Outputs contain no verbatim quotes, thread titles or person codes by default. `crp build --with-quotes` makes an internal version in `results/internal/`, which is gitignored and never shared (D33).
- Interview transcripts are a separate source type. Never pool them into forum percentages.

## Working style

- Work one phase of `BUILD_PLAN.md` at a time. At the end: run `pytest`, show the phase's "Done when" checks, commit, then stop for review.
- Python 3.11+, type hints, small modules, no notebooks. Keep dependencies minimal and pin them in `pyproject.toml`.
- Every command that produces results writes to `run_manifest.json`: command, time taken, seed, input file hashes, package versions, codebook version, and coder model.
- Use British spelling in all user-facing text.
- Commit messages say what changed and why, in plain words.

## Useful commands (once built)

```
python -m crp --help
pytest -q
python -m crp analyse studies/<id>
python -m crp check-numbers studies/<id>
```
