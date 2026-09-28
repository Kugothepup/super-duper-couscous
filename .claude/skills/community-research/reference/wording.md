# Wording

How findings are worded in the outputs, in your synthesis and in conversation. The templates in `crp/templates/` and `crp/wording.py` already follow these rules. Your prose must too.

## Numbers

- **Never compute, estimate or round a number in conversation.** In outputs, numbers come only from results.json, through placeholders. In chat, quote a number exactly as a `crp` command printed it, and say which command.
- If Steeve asks for a figure no command gives, say so and offer to add a command with a test. Don't work it out.
- **One unit per sentence** (D8). A percentage is of comments or of people, never both in one claim. The headline is per comment. The share of people who are net negative is the secondary figure.
- **Ranges describe this collection**: "likely 38–52% within this collection". They say nothing about a wider population.
- A probability is "in N% of re-draws". It's the one of the two resampling methods nearer 50% (D29), and it's never a certainty.
- The figure without caps is always called an **estimate** (D27).

## Thresholds

These are the method's, and not yours to change:

| Condition | What it means for wording |
|---|---|
| Fewer than 20 distinct people | Counts only ("7 of 15 comments"): no percentages, ranges or probabilities |
| Fewer than 60 sampled comments | Every result carries "early signal". Say "leaning", not "mostly" |
| Agreement alpha 0.80 or above | Verified |
| Agreement alpha 0.667 to 0.80 | Tentative (amber) |
| Agreement below 0.667, or not run | Unverified (red banner): the AI's coding hasn't been checked by a person |

Each section carries the status of the variables it rests on (D25). Don't describe a tentative or unverified section as settled.

## Claims

- Say whose voices these are: "people posting in r/notetaking between June and August", not "users" or "the public". Forum voices are self-selected and vocal.
- A snapshot shows what people said, not where opinion is heading. Speak of a trend only when the direction section finds one across periods.
- Coverage is reported honestly ("4 of 12 participants"). Never write "users said".
- Never write "proves", "confirms" or "disproves". Write "leans for", "leans against", "mixed" or "can't tell from this data".
- A result a single thread or source carried (the leave-one-out check) says so.
- Interviews are described on their own, in counts. They never go into forum percentages (D14).

## Quotes and privacy

- The default build has **no verbatim quotes, no thread titles and no person codes**, and refuses any six-word run copied from a post (D33). Your observations and summary must be in your own words.
- In conversation, paraphrase posts too. Quote only when Steeve is checking a specific post in the internal build.
- Never write usernames, the salt, or anything from `raw/` into outputs or commits.

## Style

- British spelling (analyse, organisation, colour, programme).
- Plain words and short sentences. Name the thing, not the category ("pricing", not "monetisation factors").
- Numbers you put in prose for non-data quantities are written in words ("four threads"), so `crp check-numbers` can tell them from data.
