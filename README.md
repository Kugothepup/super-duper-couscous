# Part 2: Move the pipeline into Claude Code

This pack sets up a Claude Code project. Claude Code runs your existing skill, and the skill hands every counting, sampling and statistics step to Python.

**The rule the whole project follows:** *the AI reads and labels; code counts.*

## What's in the pack

| File | What it is |
|---|---|
| `README.md` | This file: setup steps for you |
| `CLAUDE.md` | Standing rules Claude Code reads at the start of every session |
| `BUILD_PLAN.md` | The phased build, with a check at the end of each phase |
| `.claude/agents/blind-coder.md` | A separate agent that codes posts without seeing your hypotheses |
| `.claude/settings.json` | Blocks Claude from reading sealed files and secrets |
| `gitignore.txt` | Rename to `.gitignore`: keeps raw posts, usernames and secrets out of git |

## How the pieces fit

```
You ── /community-research ──▶ Skill (SKILL.md)
                                 │  judgement: transcribe, write codebook, explain themes, write prose
                                 │
                                 ├──▶ python -m crp …   (sample, verify, anonymise, analyse, build)
                                 │
                                 └──▶ blind-coder agent  (labels posts from a blinded batch file)
                                          │
                                          ▼
                                 results.json ──▶ dashboard + report (numbers filled in by code)
```

## Setup (about 20 minutes)

1. **Install Claude Code** if you haven't already (see docs.claude.com → Claude Code → Quickstart). You'll also need **Python 3.11 or newer** and **git**.

2. **Make the project folder:**
   ```
   mkdir community-research && cd community-research
   git init
   ```

3. **Copy this pack in.** Put `CLAUDE.md`, `BUILD_PLAN.md`, `README.md` and the `.claude/` folder at the top level. Rename `gitignore.txt` to `.gitignore`. Folders starting with a dot are hidden by default: press Cmd+Shift+. in Finder, or turn on "Hidden items" in Windows File Explorer, to see `.claude/`.

4. **Copy your existing skill in** at `.claude/skills/community-research/SKILL.md`, along with any files that sit beside it (templates, reference files, the dashboard HTML, demo data). If your skill has a different name, use that name for the folder. Claude Code turns the folder name into the slash command. Keep the synthetic demo study out of the project: it's for showcasing only, and tests use their own fixtures.

5. **Commit the starting point** so you can always see what changed:
   ```
   git add -A && git commit -m "Starting point: existing skill + handoff pack"
   ```

6. **Open Claude Code** in the folder (`claude`) and paste this as your first message:

   > Read CLAUDE.md and BUILD_PLAN.md, then do Phase 0 only. Read the skill at .claude/skills/community-research/ and write INVENTORY.md as the plan describes. Don't change any other file. Stop and show me the inventory when it's done.

## How to work through the build

- **One phase per session**, or at least one phase per go. At the end of each phase Claude should stop, show you the "Done when" checks passing, and commit. Read the diff before saying "next phase".
- **Phase 0 is your decision point.** The inventory lists every step in your skill and whether it stays as AI judgement or moves to code. Correct anything that's wrong before Phase 1. It's much cheaper to fix there than later.
- **If Claude wants to change the method** (the driver metric, thresholds, codebook structure), it should raise it with you rather than just doing it. CLAUDE.md tells it to.
- Useful prompt for every later phase:
  > Do Phase N from BUILD_PLAN.md. Follow CLAUDE.md. Run the tests, show me the "Done when" checks, commit, then stop.

## Running a study once it's built

1. `/community-research` and describe the study (topic, type, dates). Claude scaffolds `studies/<id>/`.
2. **Write your prior belief yourself** in `studies/<id>/sealed/prior.md`, in your own editor. Claude is blocked from reading this folder until coding is locked.
3. Fill in `collection_log.csv` as you search (forum, search term, date, why).
4. Paste posts and screenshots into `studies/<id>/raw/`. Claude transcribes them, and code checks them.
5. Claude runs the stages. At the coding-check stage, **you code the blind sheet** (`human/agreement_sheet.csv`). This is the one manual step, and it gates the results.
6. Claude builds the dashboard and report into `studies/<id>/results/`.

## Things to know

- **The skill becomes Claude Code-specific.** Once it calls Python, it won't run in the Claude app chat the same way. Keep a copy of the current skill as the chat version until the code version has run a real study.
- **Blinding is strong but not perfect.** The coder agent gets a fresh context, no CLAUDE.md and no hypotheses. The settings file blocks reads of `sealed/`, but a shell command could still reach it. CLAUDE.md forbids that, and `crp unseal` records when the prior was opened. For fully repeatable coding, the plan includes an optional later phase that codes through the API with a pinned model.
- **Platform terms:** check Reddit's and other platforms' terms for each commercial project before collecting.
