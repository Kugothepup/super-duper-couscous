# Hypotheses for discovery

Hypotheses are the last part of the findings and the handover to proper research. This data can suggest and prioritise them. It can't prove them. `crp analyse` scores each one from the locked labels. You write the claims, signals and test plans, and never the probabilities or leans.

## Two origins, kept apart

- **`stated`**: Steeve's own belief, from his sealed prior. It's written only after `crp unseal`, from `results/prior.md`, and `crp validate` refuses a stated hypothesis before then (D31). Write it as he stated it, without reshaping it to fit the data. If the prior was changed after the first ingest, `crp unseal` says so and the report shows it.
- **`formed`**: suggested by the findings. The same data can't also test them, so they're always "test first" when important.
- Studies can have either or both. With no prior, every hypothesis is formed.
- Always write at least one formed hypothesis that competes with each stated one. If the data fits several explanations, write each.

## Format

```json
{"hypotheses": [
 {"id": "H1", "origin": "formed", "owner": null,
  "statement": "We believe research teams leave mainly because price rises outpace the value of new features",
  "importance": "high",
  "signals": [
    {"id": "S1", "text": "Pricing is the top driver of negative comments", "test": {"type": "top_driver", "aspect": "pricing"}},
    {"id": "S2", "text": "Pricing draws more negative mentions than sync", "test": {"type": "greater", "a": "pricing", "b": "sync"}},
    {"id": "S3", "text": "People who describe leaving name price", "for": ["T01-p04", "T03-p09"], "against": ["T02-p11"]}
  ],
  "not_distinguishing": ["T02-p02"],
  "next_step": {"method": "interviews with people who cancelled in the last quarter",
                "recruit": "research-team admins who downgraded or cancelled",
                "confirm": "most name price before any missing feature when describing the decision",
                "disconfirm": "most name a missing feature or a rival product first, and price only when prompted",
                "questions": ["Walk me through the week you decided to cancel."]}}
]}
```

- **statement**: "We believe [who] [does what] because [why]". It's a claim about people, not a decision ("teams leave over price", not "we should cut prices").
- **importance**: how much the strategy or pitch rests on it (`high`, `medium`, `low`). Low importance parks it.
- **signals**: two to four. Each has either a `test` or `for`/`against` post ids, not both.
  - `top_driver {aspect}`: how often the aspect is the top driver across re-draws.
  - `greater {a, b, measure}`: how often a's measure beats b's.
  - `above {aspect, measure, threshold}`: how often the measure is above a threshold, in percent.
  - `proportion {k_ids, n_ids}`: k of n people, with a range.
  - `for` and `against` count the people on each side.
  - Measures are `share_of_negative`, `negative_rate` or `mention_rate`.
  - Prefer tests to voice tallies. Include at least one signal that could go against the hypothesis.
  - A test's aspects must be in the codebook and mentioned in the sample. Every `k_id` must also be in `n_ids`. Cited posts need observations.
- **not_distinguishing**: evidence that fits this hypothesis and its rivals equally (Heuer's Analysis of Competing Hypotheses). It's listed so nobody mistakes it for support.
- **next_step**: the test plan.
  - `method`: interviews, a survey, usage data or an experiment.
  - `recruit`: who to recruit.
  - `confirm`: what result would support it.
  - `disconfirm`: what would count against it, specific enough that it could really happen.
  - `questions`: one to three questions to start with.

## Language

Never "proves", "confirms" or "disproves". The scores come out as "leans for", "leans against", "mixed" or "can't tell from this data", with a strength and a priority. Use those words. A strong lean from forum data still means "worth testing first", not "true". Be as plain about Steeve's own hypothesis as about any other, whichever way it leans.
