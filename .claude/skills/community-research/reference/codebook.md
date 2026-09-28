# Designing the codebook

The codebook is everything the blind coder knows. Each batch file's header carries the codebook and its rules, and nothing about the study's aims. So write it to be complete on its own. Define what to code, never what you hope to find. Keep Steeve's views and any early findings out of it.

`crp codebook freeze` checks the design and locks it. After that, any change is a new version (`--new-version`) and everything is coded again. That is Steeve's call, so get the draft right and show it to him first (stop 2).

## Shape

```yaml
version: '1'
study_type: product            # must match study.yaml
aspects: [pricing, search, sync, templates, offline]
aspect_definitions:
  pricing: what it costs, plans and discounts
instructions:
- Code every item, including dull ones.
- text: 'But-clauses: the clause after "but" usually carries the overall score, while each aspect keeps its own score.'
  applies_to: measurement
parent_context: true           # show the coder the post a comment replies to
variables:
- name: overall
  description: The writer's evaluation of Quillnote, not their mood
  applies_to: measurement
  kind: single
  level: ordinal
  values: [-2, -1, 0, 1, 2]
  definitions:
    -2: 'strongly negative: strong language, lost work, cancelled or switched'
    -1: 'negative: a plain complaint'
    0: neutral, mixed, unclear or off-topic
    1: positive
    2: 'strongly positive: strong language or a clear benefit'
```

`tests/fixtures/quillnote-fixture/codebook.yaml` is a complete product example.

## Which variables, by lens

The **measurement sample** is random and gives every percentage. The **detail selection** is purposive and gives the explanations, never percentages (D10).

| Variable | Sample | Product | Brand | News | Topic |
|---|---|---|---|---|---|
| `overall`: single, ordinal, -2 to 2, not nullable (required) | measurement | ✓ | ✓ | ✓ | ✓ |
| `stance`: single, ordinal, -2 to 2, `nullable: true` (required) | measurement | | | ✓ | ✓ |
| `aspect_scores`: per aspect, ordinal, -2 to 2 | measurement | ✓ | ✓ | ✓ | ✓ |
| `evidence_type` | detail | ✓ | ✓ | ✓ | ✓ |
| `aspect` (the aspects plus `not_applicable`) and `sentiment` (-2 to 2) | detail | ✓ | ✓ | ✓ | ✓ |
| `friction` (true/false) and `severity` (`required_when: friction`) | detail | ✓ | ✓ | if concerns matter | ✓ |
| `jtbd_force` | detail | ✓ | if comparisons matter | | |
| `success` (true/false) | detail | ✓ | ✓ | | |
| `frame` | detail | | | ✓ | ✓ |

Each dashboard section rests on the variables it needs. A section whose variables aren't in the codebook stays empty and says so. The meanings of `overall`, `stance` and `frame` are in `sentiment-stance-frame.md`. Use them word for word in the variable descriptions, adapted to the subject.

## Aspects

Aspects become the drivers in the report, so keep the list short and stable.
- 8 to 20 aspects, found by reading a spread of posts across threads (`crp view thread`, `crp view kwic`).
- One or two lowercase words about the thing, not the feeling: `pricing`, not `too expensive`; `offline`, not `offline broken`. Hyphens are allowed (`follow-through`).
- No synonyms side by side (`price` and `pricing`).
- Give each aspect a one-line definition. The coder sees only the name and the definition.
- What an aspect is depends on the lens:
  - product: a feature or aspect;
  - brand: a brand association;
  - news: a sub-topic, claim or actor;
  - topic: a sub-topic or argument.

## Coding rules (`instructions`)

These are the judgement calls from aspect-based sentiment practice. Adapt the examples to the subject:
- Code every item, including dull ones. Skipping neutral comments would inflate negativity.
- **Negation and shifters:** "not bad" is mildly positive; "hardly works" is negative.
- **But-clauses:** the clause after "but" usually carries the overall score, while each aspect keeps its own.
- **Implied opinions count:** "search takes 10 seconds" is negative on search with no sentiment word.
- **Sarcasm:** "great, another price rise" is negative. If you can't tell, score 0.
- **Intensity:** -2 and 2 need strong language, a severe consequence or emphasis. Plain complaints are -1.
- **Questions** and help requests are usually 0 overall unless they carry a complaint or a view.
- **Aspects:** score only aspects the text evaluates. A bare mention isn't an evaluation.
- For news and topic studies, say how to keep `overall` and `stance` apart for this subject, and that doubt something will happen isn't a stance.

A rule about one sample carries `applies_to: measurement` or `applies_to: detail`, so each batch sees only its own rules (D34). A plain string applies to both.

## Detail variables

**evidence_type** (ordinal, weakest first): `hypothetical`, `opinion`, `habitual`, `specific_incident`, `observed`.
- `hypothetical`: a prediction or wish ("I would definitely use…").
- `opinion`: an evaluation or preference ("it's confusing").
- `habitual`: a general practice ("every Friday I…").
- `specific_incident`: a concrete, located past event ("last week when we migrated…").
- `observed`: behaviour seen in a session. It almost never applies in a forum.

Forum posts are mostly opinion and habitual. When a writer gives a general claim and then an example, the example is what gets coded. When torn, the lower grade applies.

**jtbd_force** (Moesta and Spiek's forces of progress):
- `push`: pain with the current way of doing the job.
- `pull`: attraction to a new or better solution.
- `anxiety`: worry about switching or adopting (risk, effort, trust, cost).
- `habit`: comfort with the status quo ("it works well enough").
- `none`: context that isn't a force. It's valid and common.

**friction**: the writer hit an obstacle, workaround, error, confusion or unmet need. **severity**, only when there's friction:
- `1` minor, recovered easily;
- `2` moderate: a workaround, lost time or real frustration;
- `3` severe: blocked the goal, lost data, or drove switching.

**success**: something clearly worked for the writer, such as a goal met or a feature that changed how they work. Liking it isn't enough, and a post is rarely both friction and success.

**frame** (Entman): which function of a frame the post mainly performs. `problem` says what the problem is. `cause` says what caused it or who is responsible. `moral` judges who is to blame or deserves credit. `remedy` proposes what should be done. `none` is none of these.

## Before showing Steeve

- Every value has a definition wherever the difference isn't obvious.
- `overall` and `stance` descriptions name the subject and the proposition exactly.
- Nothing in the codebook hints at an expected answer.
- The aspect list covers the threads without an obvious catch-all. Posts about nothing on the list go to `not_applicable`, so a large "other" later means the list missed something.
