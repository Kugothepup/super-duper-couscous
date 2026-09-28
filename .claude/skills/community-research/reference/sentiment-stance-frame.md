# Sentiment, stance and frame

Three different things, which the old coding guide, dashboard and coder brief used to blur (D13). Every codebook, rule and output uses these meanings.

## Sentiment (`overall`, and `sentiment` on detail posts)

**The writer's evaluation of the subject.** Not their mood, and not whether they agree with a proposition.

- It's scored -2 to 2: strongly negative, negative, neutral (or mixed, unclear, off-topic), positive, strongly positive.
- It's labelled "sentiment" everywhere. The old dashboard called it "tone".
- `overall` is the headline's variable, measured per comment in the random sample (D8).
- `aspect_scores` gives each aspect the comment evaluates its own score. On a detail post, `sentiment` is the feeling towards that post's one `aspect`.
- An angry writer who praises the product is positive. A cheerful writer who says it's useless is negative.

## Stance (`stance`, news and topic studies)

**The writer's position on the study's proposition** (`stance_target` in study.yaml), for example "The pensions triple lock should be ended".

- It's scored -2 strongly against, -1 against, 0 balanced or conditional, 1 for, 2 strongly for.
- It's **null when no position is expressed**, which is common.
- Doubt that something will happen isn't a stance. Neither is a view about the people involved.
- Sentiment and stance can point opposite ways. Someone can welcome ending the lock (stance 2) and be scornful that the government will never do it (overall -1).
- Write the proposition so that "for" and "against" are unambiguous. A proposition with two claims joined by "and" can't be coded.

## Frame (`frame`, news and topic studies, detail posts)

**Which function of a frame the post mainly performs** (Entman, 1993):

| Value | The post… |
|---|---|
| `problem` | says what the problem is |
| `cause` | says what caused it or who is responsible |
| `moral` | judges who is to blame or deserves credit |
| `remedy` | proposes what should be done |
| `none` | does none of these |

A frame is about what the post does, not whether it's right. When a post does several, code the one it mainly does.

## Mood

Not coded. How someone feels in general, as opposed to about the subject, isn't a finding this method can support.
