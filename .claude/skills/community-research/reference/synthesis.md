# Writing the synthesis

The synthesis is your reading of the coded detail posts. It goes in `studies/<id>/synthesis/`. Code counts everything in it: people, strong evidence, severity, forces and reach. You write words and post ids, never numbers. `crp validate` checks each file, and `crp analyse` refuses to run while there are errors.

| File | Holds |
|---|---|
| `observations.jsonl` | one line per coded detail post you have something to say about |
| `insights.json` | `{"insights": [...]}`: claims about people, citing posts, with counter-evidence |
| `jobs.json` | `{"jobs": [...]}`: job stories (product studies) |
| `opportunities.json` | `{"opportunities": [...]}`: "How might we" statements, or implications for news and topics |
| `hypotheses.json` | `{"hypotheses": [...]}`: see `hypotheses.md` |
| `summary.md` | a short paragraph for the top of the report and dashboard |

Every post cited in an insight, job, opportunity or hypothesis needs an observation, so write observations first.

## Observations

```json
{"post_id": "T02-p14", "observation": "Works around the missing region filter with a weekly manual export, now routine.", "quote": "I ended up exporting it to Excel every Friday", "tags": ["reporting", "workaround", "product:excel"]}
```

- **At most one per coded detail post** (D31). Each sits on exactly one set of blind codes, so nothing is counted twice. Observations can only be made on posts in the detail selection.
- **quote**: copied exactly from that post, with `...` to skip words. Only spacing and quote marks may differ. A tidied or invented quote is an error (D31).
- **observation**: what the quote alone doesn't say, such as the underlying need, the workaround, the mental model or the contradiction. Never just paraphrase the quote, and **never repeat six or more words of the post**: the default build refuses text that does. The observation may hold only its own post's numbers.
- **tags**: short lowercase nouns for the topic, plus pattern tags where they fit (`workaround`, `request`, `mental-model`, `contradiction`, `trust`, `question`). Tag every named product as `product:<name>`, and every organisation or person in a news or topic study as `entity:<name>`. Reuse tags: look at earlier observations before inventing one.
- The categories (force, evidence grade, friction, severity, aspect, sentiment, success, frame) are the blind coder's. Don't restate or second-guess them.
- Flags from `crp signals` (hesitation, constraint language, implicit requests) are prompts to read closely, not findings. If hesitation is itself the point, say so and tag `mental-model`.

**Forum posts.** The unit is the person, not the thread.
- Echo replies ("same", "this", "+1") aren't in the detail selection. They're counted as engagement.
- The opening post frames the question. Replies that describe the writer's own experience are usually better evidence.
- Score reflects visibility and timing as well as agreement. Use it to decide what to read, not as a vote.
- When a reply contests a claim with its own experience, it's counter-evidence. Make an observation of it.
- If you can't tell whether a post is sincere, leave it without an observation.

## Insights

```json
{"id": "I01", "statement": "Regional managers rebuild reports outside the product because filtering stops at team level",
 "post_ids": ["T01-p04", "T03-p11"], "counter_post_ids": ["T02-p07"], "confidence": "medium",
 "recommendations": ["Add region as a report filter and test it with regional managers"]}
```

- Write the statement as a claim about people and their situation, not a feature. "Managers do Y because Z" is stronger than "Users need X".
- Aim for roughly five to twelve. Fewer, better-supported insights beat a long list.
- Search for counter-evidence before finalising: people who didn't have the problem, or who said the opposite. List them in `counter_post_ids`.
- Check that rare but severe friction (severity 3) isn't lost because it's rare.
- **confidence**:
  - `high` needs five or more forum people, or interviews covering at least three transcripts and a third of them, plus observed or specific-incident evidence, and counter-evidence that's weak or explained;
  - `medium` needs two or more people, or strong evidence from fewer;
  - `low` is one person, or mostly opinion and hypothetical evidence. It's still worth reporting when severity is high, framed as a lead.
  - `crp validate` warns when the evidence doesn't support the level you chose. Act on it.
- Recommendations are optional: one or two, concrete, following from the insight.
- Don't let a cluster from `crp themes` become an insight without reading its posts. Clusters marked "mostly" one person, or with a low silhouette, are loose.

## Jobs (product studies)

```json
{"id": "J1", "job": "When I'm reviewing a large body of literature, I want to find and connect earlier notes quickly, so I can build arguments without re-reading papers", "post_ids": ["T01-p13", "T02-p06"]}
```

- Use Klement's form: "When …, I want …, so I can …". `crp validate` checks it.
- Describe the progress people want, not a feature ("find earlier notes", not "better search").
- Cite posts across forces (push, pull, anxiety, habit) where they exist. A job with evidence for one force only is under-evidenced, and the validator says so.
- Aim for three to six.

## Opportunities

```json
{"id": "OP1", "statement": "How might we keep search fast in very large workspaces?", "kind": "fix a pain",
 "aspect": "search", "insight_ids": ["I02"], "post_ids": ["T01-p15", "T02-p01"]}
```

- `kind` is `fix a pain`, `reduce anxiety`, `amplify a strength`, `serve an unmet job`, or `implication` for news and topics.
- Keep statements open enough to allow several solutions. The dashboard orders them by a stated heuristic, not a score. Forum data can't measure importance the way a survey can.

## Summary (`summary.md`)

A paragraph in plain words that opens the report and dashboard:
- Say whose voices these are (which forums, self-selected).
- Give the verdict and the main explanations.
- End with what it can't tell you.

**No typed digits.** A number comes in only as a placeholder filled from results.json, such as `{{ headline.negative.k }}`, `{{ headline.negative.n }}`, `{{ headline.negative.pct }}` or `{{ drivers[0] }}`. Write non-data quantities in words ("four threads"). `crp check-numbers` checks this at the source. Follow `wording.md`.

## Common mistakes

- Treating frequency as importance: a severity-3 incident from one person can matter more than a mild complaint from ten.
- Counting someone who merely agreed with a leading post as strong support.
- Crediting a person with words they only replied to.
- Quoting a post in an observation instead of saying what it means.
- Mixing interview participants into forum counts. Code keeps them apart; your prose should too (D14).
