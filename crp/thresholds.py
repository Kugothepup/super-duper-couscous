"""The method's thresholds, in one place. Values come from CLAUDE.md and DECISIONS.md (D5, D11) and triage.py."""

MIN_PEOPLE_FOR_RANGES = 20  # below this: counts only, no ranges or probabilities
MIN_ITEMS_FOR_FULL = 60  # below this many sampled comments: "early signal"
ALPHA_VERIFIED = 0.80
ALPHA_TENTATIVE = 0.667

# Sampling (triage.py defaults; caps from D2, D9, D22, D23)
MEASUREMENT_SIZE = 150  # random sample for measuring sentiment
PERSON_CAP = 5  # items per person in the measurement frame, opening posts included
THREAD_CAP_PCT = 10  # no thread supplies more than this % of the measurement sample drawn
DETAIL_BUDGET = 200  # posts in the purposive detail selection
DETAIL_PER_PERSON = 5  # comments per person in the detail selection; own opening posts exempt
MIN_WORDS = 8  # comments shorter than this are left out of both (opening posts are kept)


def result_status(n_people: int, n_items: int) -> str:
    """The status every result must carry, given how many people and sampled items it rests on."""
    if n_people < MIN_PEOPLE_FOR_RANGES:
        return "counts-only"
    if n_items < MIN_ITEMS_FOR_FULL:
        return "early-signal"
    return "full"


def agreement_status(alpha: float | None) -> str:
    """Verified, tentative or unverified, from Krippendorff's alpha (None = not yet run)."""
    if alpha is None or alpha < ALPHA_TENTATIVE:
        return "unverified"
    if alpha < ALPHA_VERIFIED:
        return "tentative"
    return "verified"
