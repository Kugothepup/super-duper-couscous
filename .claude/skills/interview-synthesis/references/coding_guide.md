# Coding guide

Read this before coding the first transcript. It defines the nugget and insight
formats and how to judge each field.

## Contents
1. Nugget format
2. Field rules (quote, observation, JTBD force, evidence type, friction, speech act, tags)
3. Using the signal flags
4. Insight format and confidence rules
5. Common mistakes
6. Reddit and forum data
7. Sentiment coding (random sample)
8. Outlook statements
9. Success moments, jobs and opportunities (for the dashboard)
10. Capturing pasted posts and screenshots
11. Writing and evaluating hypotheses

---

## 1. Nugget format

`WORK/nuggets/T03.json` is a JSON list:

```json
[
  {
    "id": "T03-N01",
    "transcript_id": "T03",
    "turn_ids": [14],
    "quote": "I ended up exporting it to Excel every Friday because the report view doesn't let me filter by region",
    "observation": "Works around missing region filter with a weekly manual export; the workaround is now routine",
    "jtbd_force": "push",
    "evidence_type": "habitual",
    "friction": true,
    "severity": 2,
    "speech_act": "assertive",
    "tags": ["reporting", "filtering", "workaround", "export"]
  }
]
```

A nugget is one observation backed by one piece of verbatim evidence. If a passage
contains two distinct points, make two nuggets. Aim for roughly 8–25 nuggets per
hour of interview; more usually means over-splitting.

## 2. Field rules

**quote** must be copied exactly from the cited turn(s). Case and punctuation
differences are tolerated; changed words are not. Use `...` to skip words inside a
long quote. Keep fillers if they are in the source, since they carry meaning. Only
participant speech; cite an interviewer turn only as context alongside a participant turn.

**observation** is the researcher's interpretation, in plain language. It should say
something the quote alone does not: the underlying need, the workaround, the
mental model, the contradiction. Never just paraphrase the quote.

**jtbd_force** (Moesta & Spiek's forces of progress):
- `push` — pain or frustration with the current way of doing the job
- `pull` — attraction to a new or better solution (including ours)
- `anxiety` — worry about switching or adopting: risk, effort, trust, cost, looking foolish
- `habit` — comfort with the status quo, sunk effort, "it works well enough"
- `none` — useful context that is not a force (goals, environment, who's involved)

Push and habit both concern the current solution: push is what's wrong with it,
habit is what keeps people there despite that. Pull and anxiety both concern the new
solution. Don't force-fit; `none` is a valid and common answer.

**evidence_type**, strongest first:
- `observed` — the behaviour happened in the session (task, screen share, demo)
- `specific_incident` — a concrete, located past event ("last Tuesday when...")
- `habitual` — generalised practice ("I usually...", "every Friday I...")
- `opinion` — evaluation or preference ("it's confusing", "I like...")
- `hypothetical` — prediction or wish ("I would definitely use...", "if it had X...")

Generalised and hypothetical statements are the ones most shaped by after-the-fact
rationalisation, so they count for less in synthesis. When a participant gives a
general claim and then a concrete example, code the example.

**friction** is true when the participant hit an obstacle, workaround, error, confusion
or unmet need. **severity** (required when friction is true):
- `1` minor: noticed, recovered easily, no real cost
- `2` moderate: needed a workaround, lost time, or felt real frustration
- `3` severe: blocked the goal, caused errors or data loss, or drove abandonment/switching

**speech_act** (optional; Searle): `assertive`, `directive`, `commissive`, `expressive`,
`declaration`. The useful one is spotting covert directives: "Is there a way to export
this?" is a request, not a question. Tag those `directive` and add a `request` tag.

**aspect** and **sentiment** (optional for interviews, expected for Reddit): the one
product aspect the nugget is mainly about (same names as in sentiment coding) and
the feeling towards it, -2 to +2. This links each driver in the report to the
coded explanations of why.

**tags**: short lowercase nouns for the product area or topic (`onboarding`,
`permissions`, `export`), plus pattern tags where they fit: `workaround`, `request`,
`mental-model`, `contradiction`, `trust`. Reuse tags across transcripts; check
earlier nuggets files before inventing a new tag.

Tag every named product, tool or competitor as `product:<name>` in lowercase
(`product:notion`, `product:excel`). The report builds a table of products by JTBD
force from these, which shows what people are leaving, moving to and stuck with.
Tags that often appear together are drawn as a connections graph, so consistent
tagging matters more than clever tagging.

## 3. Using the signal flags

`view_transcript.py` shows flags from `signals.py` in braces:
- `hesitation_cluster` — this turn has unusually many hedges, fillers, repairs or
  pause markers compared with this participant's normal. Re-read it: possible
  uncertainty, recall difficulty, discomfort or social desirability. Or nothing.
- `constraint_language` — "I had to", "it wouldn't let me", "I couldn't". Often friction.
- `implicit_request` — "is there a way", "I wish", "it would be nice if".
- `long_response_gap` — a slow reply (only when end timestamps exist; noisy).

Flags are prompts to look closer. Only code a nugget if the content supports it.
If hesitation itself is the finding (e.g. the participant cannot explain what a
setting does), say so in the observation and add the `mental-model` tag.

## 4. Insight format and confidence rules

`WORK/insights.json`:

```json
{
  "insights": [
    {
      "id": "I01",
      "statement": "Regional managers rebuild reports outside the product because filtering stops at team level",
      "nugget_ids": ["T01-N04", "T03-N01", "T07-N09"],
      "counter_nugget_ids": ["T05-N02"],
      "confidence": "medium",
      "recommendations": ["Add region as a report filter and test with regional managers"]
    }
  ]
}
```

Write the statement as a claim about people and their situation, not a feature
("Users need X" is weaker than "Managers do Y because Z").

Confidence:
- `high` — at least a third of transcripts (min 3), includes observed or specific-incident
  evidence, and counter-evidence is weak or explained
- `medium` — two or more transcripts, or strong evidence from fewer
- `low` — single transcript, or mostly opinion/hypothetical evidence. Still worth
  reporting when severity is high; frame it as a lead to investigate

Always search for counter-evidence before finalising: participants who did not have
the problem, or who said the opposite. List them in `counter_nugget_ids`. An insight
that holds up against counter-evidence is stronger than one that never faced it.

Recommendations are optional and should follow from the insight. One or two, concrete.

## 5. Common mistakes

- Quoting the interviewer's leading question as if it were the participant's view
- Counting a participant who merely agreed with a leading question ("Yeah, I guess")
  as strong support
- Merging several participants into one nugget (one nugget = one transcript)
- Treating frequency as importance: a severity-3 incident from one person can
  matter more than a mild complaint from ten
- Letting cluster labels become insight statements without reading the members

## 6. Reddit and forum data

The unit of evidence is the **author**, not the thread. Coverage counts distinct
authors, so a nugget belongs to whoever wrote its first cited turn.

- **turn_ids**: put the author's own comment first. You may add the parent turn
  after it for context (`[45, 41]`), but the quote must come from the first turn;
  the validator enforces this so no one is credited with words they only replied to.
- **Echo replies** ("same here", "this", "+1") are not coded. `signals.py` counts
  them against the comment they answer, and the report shows them as engagement.
  A comment with many agree-echoes is good corroboration, but echoes are cheap:
  they never replace independent authors describing their own experience.
- **evidence_type**: forum posts are mostly `opinion` and `habitual`. Look hard for
  `specific_incident` ("last week I...", "when we migrated...") and prefer it.
  Don't use `observed`; nothing is observed in a forum.
- **Disagreement** is valuable. When a reply contests a claim with its own
  experience, code it as its own nugget and use it as counter-evidence.
- **Score** reflects visibility, timing and community taste as well as agreement.
  Use it to decide what to read, not as a vote count for truth.
- **OP** (marked in the viewer) often frames the question. Their post sets context;
  replies that describe the repliers' own experience are usually better evidence.
- Confidence for Reddit: `high` needs 5+ distinct authors and at least one specific
  incident; `medium` needs 2+ authors; a single author is `low`.
- Posts sometimes contain sarcasm and in-jokes. If you can't tell whether a
  statement is sincere, skip it rather than guess.

## 7. Sentiment coding (random sample)

`triage.py` draws a random sample purely for measuring sentiment. Code every comment
in it, including dull ones: skipping neutral comments would inflate negativity.
Write `WORK/sentiment/batch1.json`, `batch2.json`, ...:

```json
[
  {"ref": "T01#23", "overall": -1, "aspects": {"pricing": -2, "templates": 1}},
  {"ref": "T01#31", "overall": 0, "aspects": {}}
]
```

**overall**: the comment's stance towards the product or topic under study, not
the commenter's mood. -2 strongly negative, -1 negative, 0 neutral/mixed/unclear or
off-topic, +1 positive, +2 strongly positive.

**aspects**: each aspect the comment evaluates, with its own score. Only include
aspects that are actually evaluated; a bare mention ("I use it for notes") isn't one.

**Aspect names are the drivers in the report**, so keep the list short and stable:
- one or two words, lowercase, about the thing, not the feeling (`pricing`, not
  `too expensive`; `offline`, not `offline broken`)
- settle roughly 8–20 aspects in the first batch, then reuse them. `validate.py`
  prints the current list with counts; merge synonyms (`price`/`pricing`/`cost`)
  before running `drivers.py`
- use the same names in nuggets' `aspect` field

Judgement calls, following aspect-based sentiment practice:
- **Negation and shifters**: "not bad" is mildly positive; "hardly works" is negative.
- **"But" clauses**: the clause after "but" usually carries the overall stance
  ("love the templates but I'm leaving over pricing" is overall -1 or -2), while each
  aspect keeps its own score (templates +2, pricing -2).
- **Implied opinions**: "search takes 10 seconds" is negative on `search` with no
  sentiment word. Score it.
- **Sarcasm**: "great, another price rise" is negative. If you can't tell, score 0.
- **Intensity**: -2/+2 need strong language, a severe consequence (lost work, cancelled,
  switched) or emphasis. Plain complaints are -1.
- **Questions and help requests** are usually 0 overall unless they carry a complaint.

## 8. Outlook statements

`WORK/outlook.json` turns drivers, direction and insights into forward-looking
calls. Write them after `drivers.py`, and keep them few (3–6).

```json
{"outlook": [
  {"id": "O1",
   "statement": "Pricing complaints will keep rising as annual renewals hit",
   "likelihood": "likely",
   "horizon": "next 6 months",
   "basis": ["driver:pricing", "trend", "T02-N07"],
   "would_change_if": "Pricing's share of negative mentions falls for two periods, or a discount tier launches",
   "review_by": "2027-03-31"}
]}
```

**likelihood** must be a phrase from the ICD 203 scale, never a number:
almost no chance (1–5%), very unlikely (5–20%), unlikely (20–45%), roughly even
chance (45–55%), likely (55–80%), very likely (80–95%), almost certain (95–99%).
Words with fixed ranges stop "likely" meaning 60% to one reader and 90% to another,
while not pretending to precision the data doesn't have.

Calibration rules:
- A snapshot (one short time window) shows what people feel, not where it's heading.
  Without a trend, stay at "roughly even chance" or below for claims about change,
  unless the basis is a stated plan ("our lab cancels in June").
- Forums lead some outcomes (early complaints about a change) and lag others (people
  who quietly leave don't post). Say which you think applies.
- Talk about what this community will say or do. Extending to the wider user base needs
  outside evidence (usage, churn, reviews); say so in `would_change_if` if relevant.
- **basis** entries are nugget ids, `driver:<aspect>`, `strength:<aspect>` or `trend`.
  The validator checks they exist.
- **would_change_if** names observable evidence that would move the call. If you
  can't name any, the statement isn't a forecast.
- **review_by** lets the user check the call later. Scoring past calls is the only
  real way to learn how far to trust these.

## 9. Success moments, jobs and opportunities (for the dashboard)

**Success moments.** Add `"success": true` to a nugget when something clearly worked
for the person: a goal met, a feature that changed how they work, delight they
describe. Positive opinion alone ("it's fine") isn't a success moment; look for what
it let them do. A nugget is rarely both friction and success.

**Jobs** go in `WORK/jobs.json`, written during synthesis. Use Klement's job story
form so the situation, motivation and outcome are all explicit:

```json
{"jobs": [
  {"id": "J1",
   "job": "When I'm reviewing a large body of literature, I want to find and connect earlier notes quickly, so I can build arguments without re-reading papers",
   "nugget_ids": ["T01-N13", "T02-N06", "T01-N15"]}
]}
```

- Describe the progress people want, not a feature ("find earlier notes", not "better search").
- Link nuggets across all four forces where they exist. The dashboard shows push and
  pull against anxiety and habit for each job; a job with evidence for only one force
  is under-evidenced.
- Aim for 3–6 jobs. Most studies have one or two main jobs and some smaller ones.

**Opportunities** go in `WORK/opportunities.json`. Phrase each as a "How might we"
question that follows from a pain, anxiety, strength or unmet job:

```json
{"opportunities": [
  {"id": "OP1",
   "statement": "How might we keep search fast for 3,000+ page research workspaces?",
   "kind": "fix a pain",
   "aspect": "search",
   "insight_ids": ["I02"],
   "nugget_ids": ["T01-N15", "T02-N01"]}
]}
```

`kind` is one of: `fix a pain`, `reduce anxiety`, `amplify a strength`,
`serve an unmet job`. The dashboard ranks by people affected × (1 + mean severity).
That's a transparent ordering heuristic, not an opportunity score: forum and
interview data can't measure importance and satisfaction the way a survey-based
method (such as Ulwick's Outcome-Driven Innovation) can. Keep opportunity
statements open enough to allow several solutions.

## 10. Capturing pasted posts and screenshots

Write one `WORK/capture/<name>.json` per source file (format in `parse_forum.py`).

- **text** is the post exactly as written: same words, spelling and order. Leave out
  interface text ("Reply", "Share", "14 Likes", badges, signatures). For pastes the checker
  rejects any post not found word-for-word in the file, so never tidy or summarise.
- **Screenshots**: transcribe what is visible. If a word is unreadable, write `[?]`; if a
  post is cut off at the edge, transcribe what's there and end with `[cut off]`. Never
  complete it from context.
- **author**: the display name as shown, or null. The name never leaves the working files.
- **date**: YYYY-MM-DD. Convert relative dates ("3 mo. ago", "2y") using `captured` and set
  `date_approx: true`. Unknown dates are null.
- **parent**: the id of the post it replies to, when the page shows it (indentation, "replying
  to", quoted text). Flat forums: null for everything after the first post.
- **score**: likes/upvotes if shown, else null.
- Quoted text from another post inside a reply belongs to the original post, not the reply.
  Leave it out of the reply's text.
- Record `site`, `thread_title`, `captured` and, if the user knows it, `search_query`.

Keep a `WORK/collection_log.json` of every search, including ones where nothing was kept:
`{"searches": [{"site": "reddit.com", "query": "notion pricing", "date": "2026-09-20",
"results_seen": 25, "kept": 3, "why_excluded": "off-topic or duplicates"}]}`.
The trust section reports it; without it, how material was chosen is unknown.

## 11. Hypotheses for discovery

Hypotheses are the last part of the findings: the handover to proper research. This data
can suggest and prioritise them; it can't prove them. Format and scoring rules are in
`hypotheses.py`.

**Two origins, kept apart.**
- `stated`: the user's own belief, often their strategy. If they have one, write it down in
  `hypotheses.json` before reading any data, so it can't be quietly reshaped to fit.
  Signals then show whether this data leans for or against it.
- `formed`: suggested by the findings. Write these after synthesis. Because the same data
  suggested them, it can't also test them: they are always "test first" if important,
  and always sit left of centre on the assumption map.
- Studies can have either or both. Going in blind is fine; then every hypothesis is formed.
- Always include at least one formed hypothesis that competes with the stated one. If the
  data suggests several explanations for the same thing, write each.

**Writing them.**
- "We believe [who] [does what] because [why]". A claim about people, not a feature or a
  decision ("research teams leave mainly over price", not "we should cut prices").
- `importance`: how much the user's strategy or pitch rests on it (high, medium, low).
- 2–4 `signals`: what in this data points to it. Prefer measurable tests
  (`top_driver`, `greater`, `above`: probabilities from resampling people) and counts
  (`proportion`: k of n with a likely range) over voice tallies. Include a signal that
  could go against the hypothesis, not only ones likely to agree.
- `not_distinguishing`: evidence that fits this and its rivals equally (e.g. "people
  complain" fits every explanation). It's listed so nobody mistakes it for support. This
  follows Heuer's Analysis of Competing Hypotheses: only evidence that separates
  explanations helps decide between them.
- `next_step`: the method that would actually test it (interviews, survey, usage data,
  experiment), who to recruit, what result would support it, what would count against it,
  and 1–3 starting questions. Make the disconfirming result specific enough that it could
  really happen.

**Language.** Never "proves", "confirms" or "disproves". Use "leans for", "leans against",
"mixed" and "can't tell from this data", which is what the script outputs. A strong lean
from forum data still means "worth testing first", not "true".
