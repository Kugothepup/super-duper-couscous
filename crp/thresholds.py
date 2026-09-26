"""The method's thresholds, in one place. Values come from CLAUDE.md and DECISIONS.md (D5, D11)."""

MIN_PEOPLE_FOR_RANGES = 20  # below this: counts only, no ranges or probabilities
MIN_ITEMS_FOR_FULL = 60  # below this many sampled comments: "early signal"
ALPHA_VERIFIED = 0.80
ALPHA_TENTATIVE = 0.667


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
