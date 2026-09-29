"""The shape of every file the pipeline reads or writes.

Unknown fields are rejected everywhere, so a typo fails loudly instead of being ignored.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from crp import thresholds

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
PersonCode = Annotated[str, Field(pattern=r"^P-[0-9a-f]{8}$")]
NonEmpty = Annotated[str, Field(min_length=1)]
StudyType = Literal["product", "brand", "news", "topic"]
# strict: a coder's 1 must not pass as true, or "2" as 2
LabelValue = StrictBool | StrictInt | StrictStr | dict[StrictStr, StrictInt] | None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- study setup -------------------------------------------------------------

class Study(Strict):
    """studies/<id>/study.yaml"""
    id: Slug
    subject: NonEmpty
    type: StudyType
    questions: list[NonEmpty] = []
    stance_target: NonEmpty | None = None
    event_date: dt.date | None = None
    window_start: dt.date | None = None
    window_end: dt.date | None = None
    sources: list[NonEmpty] = []
    population: NonEmpty | None = None
    owner: NonEmpty | None = None
    created: dt.date

    @model_validator(mode="after")
    def _window_in_order(self) -> Study:
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("window_end is before window_start")
        return self

    @property
    def needs_stance_target(self) -> bool:
        return self.type in ("news", "topic") and not self.stance_target


class CollectionLogRow(Strict):
    """One row of studies/<id>/collection_log.csv (D15)."""
    source: NonEmpty
    search_term: NonEmpty
    date: dt.date
    reason: NonEmpty
    neutral: bool
    results_seen: int | None = Field(default=None, ge=0)
    kept: int | None = Field(default=None, ge=0)
    why_excluded: NonEmpty | None = None

    @field_validator("neutral", mode="before")
    @classmethod
    def _yes_no(cls, v: Any) -> Any:
        if isinstance(v, bool):
            return v
        answer = str(v).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        raise ValueError(f"must be y or n (got {v!r})")

    @model_validator(mode="after")
    def _kept_within_seen(self) -> CollectionLogRow:
        if self.kept is not None and self.results_seen is not None and self.kept > self.results_seen:
            raise ValueError(f"kept ({self.kept}) is more than results_seen ({self.results_seen})")
        return self


COLLECTION_LOG_COLUMNS = list(CollectionLogRow.model_fields)


# ---- posts -------------------------------------------------------------------

class _PostBase(Strict):
    post_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]+$")]
    source_type: Literal["forum", "interview"]
    source: NonEmpty  # site or community, e.g. "reddit.com/r/notetaking"; "interview" for transcripts
    thread_id: NonEmpty  # the thread, or the interview transcript
    thread_title: str | None = None
    search_term: str | None = None  # the search that found the thread (collection log), if known
    parent_id: str | None = None
    role: Literal["participant", "interviewer", "unknown"] = "participant"  # unknown: removed, or unlabelled text
    kind: Literal["post", "comment", "turn"]
    timestamp: dt.datetime | None = None
    date_approx: bool = False
    score: int | None = None
    start_s: float | None = None  # interview recordings: seconds from the start
    end_s: float | None = None
    promotional: bool = False
    text: str
    capture_method: Literal["paste", "screenshot", "export", "transcript"]
    raw_ref: NonEmpty  # where the original sits in raw/, e.g. "forum_price.txt#p3"

    @field_validator("text")
    @classmethod
    def _has_text(cls, v: str) -> str:
        # checked, not stripped: text must stay verbatim for the quote checks
        if not v.strip():
            raise ValueError("text is empty")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> _PostBase:
        if self.source_type == "forum":
            if self.capture_method == "transcript":
                raise ValueError("forum posts are captured by paste, screenshot or export, not transcript")
            if self.kind == "turn":
                raise ValueError("forum posts are a 'post' or a 'comment', not a 'turn'")
            if self.role == "interviewer":
                raise ValueError("forum posts have no interviewer")
        else:
            if self.capture_method != "transcript":
                raise ValueError("interview turns are captured by transcript")
            if self.kind != "turn":
                raise ValueError("interview turns have kind 'turn'")
        if self.parent_id is not None and self.parent_id == self.post_id:
            raise ValueError("a post can't reply to itself")
        if self.kind == "post" and self.parent_id is not None:
            raise ValueError("an opening post has no parent")
        if self.date_approx and self.timestamp is None:
            raise ValueError("date_approx is set but there is no timestamp")
        return self


class IngestedPost(_PostBase):
    """One row of raw/ingested.jsonl: parsed but not yet anonymised. Holds real names, so it stays in raw/."""
    author: str | None = None  # None when no name is shown; each such post counts as its own person


class Post(_PostBase):
    """One row of studies/<id>/posts.jsonl: a forum post or comment, or an interview turn, anonymised."""
    person_code: PersonCode


# ---- samples -----------------------------------------------------------------

class MeasurementItem(Strict):
    """One row of samples/measurement.jsonl: a forum post in the random sample. Only these feed percentages."""
    post_id: NonEmpty
    thread_id: NonEmpty
    person_code: PersonCode
    selection: Literal["random"] = "random"


class DetailItem(Strict):
    """One row of samples/detail.jsonl: a post chosen on purpose for close reading. Never used for percentages."""
    post_id: NonEmpty
    thread_id: NonEmpty
    person_code: PersonCode
    source_type: Literal["forum", "interview"]
    selection: Literal["purposive"] = "purposive"
    reasons: list[NonEmpty] = Field(min_length=1)


# ---- codebook and labels -----------------------------------------------------

class Variable(Strict):
    """One thing the coder labels."""
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    description: NonEmpty
    applies_to: Literal["measurement", "detail"]  # measurement sample, or detail selection (D10)
    kind: Literal["single", "per_aspect"] = "single"  # per_aspect: one value for each aspect the item evaluates
    level: Literal["nominal", "ordinal"]  # sets the Krippendorff's alpha metric; ordinal values run low to high
    values: list[bool | int | str] = Field(min_length=2)
    definitions: dict[str, NonEmpty] = {}  # keyed by the value as written in values
    nullable: bool = False  # null allowed, e.g. stance when no position is expressed
    required_when: str | None = None  # name of a true/false variable that must be true, e.g. severity needs friction

    @field_validator("definitions", mode="before")
    @classmethod
    def _keys_as_text(cls, v: Any) -> Any:
        # YAML reads `-2:` or `true:` as a number or a boolean; store every key as it's written
        if isinstance(v, dict):
            return {(str(k).lower() if isinstance(k, bool) else str(k)): d for k, d in v.items()}
        return v

    @model_validator(mode="after")
    def _values_ok(self) -> Variable:
        if len({repr(v) for v in self.values}) != len(self.values):
            raise ValueError(f"variable '{self.name}' lists a value twice")
        unknown = set(self.definitions) - {str(v).lower() if isinstance(v, bool) else str(v) for v in self.values}
        if unknown:
            raise ValueError(f"variable '{self.name}' defines values it doesn't list: {sorted(unknown)}")
        return self


class Instruction(Strict):
    """A coding rule for one sample only. A plain string in the list applies to both samples."""
    text: NonEmpty
    applies_to: Literal["measurement", "detail"]


class Codebook(Strict):
    """studies/<id>/codebook.yaml"""
    version: NonEmpty
    study_type: StudyType
    aspects: list[Annotated[str, Field(pattern=r"^[a-z][a-z-]*( [a-z][a-z-]*)?$")]] = []
    aspect_definitions: dict[str, NonEmpty] = {}
    instructions: list[NonEmpty | Instruction] = []  # coding rules, e.g. the coding guide's judgement calls (D34)
    parent_context: bool = True  # show the coder the post a comment replies to (or the question a turn answers)
    variables: list[Variable] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Codebook:
        names = [v.name for v in self.variables]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"variables named more than once: {dupes}")
        if len(set(self.aspects)) != len(self.aspects):
            raise ValueError("an aspect is listed twice")
        undefined = set(self.aspect_definitions) - set(self.aspects)
        if undefined:
            raise ValueError(f"aspect_definitions has aspects not in the aspect list: {sorted(undefined)}")
        by_name = {v.name: v for v in self.variables}
        for v in self.variables:
            if v.kind == "per_aspect" and not self.aspects:
                raise ValueError(f"variable '{v.name}' is per aspect but the codebook lists no aspects")
            if v.required_when is not None:
                gate = by_name.get(v.required_when)
                if gate is None:
                    raise ValueError(f"variable '{v.name}' is required when '{v.required_when}', which doesn't exist")
                if sorted(map(repr, gate.values)) != ["False", "True"]:
                    raise ValueError(f"variable '{v.name}' is required when '{v.required_when}', which isn't true/false")
        return self

    def instructions_for(self, sample: str) -> list[str]:
        """The rules a batch of this sample carries: its own, plus those for both samples (D34)."""
        return [i if isinstance(i, str) else i.text for i in self.instructions
                if isinstance(i, str) or i.applies_to == sample]

    def variable(self, name: str) -> Variable:
        for v in self.variables:
            if v.name == name:
                return v
        raise KeyError(name)


class Label(Strict):
    """One line of labels/batch_NNN.labels.jsonl, written by the blind coder."""
    item_id: NonEmpty
    values: dict[str, LabelValue]
    rationale: str | None = None

    @field_validator("rationale")
    @classmethod
    def _short(cls, v: str | None) -> str | None:
        if v is not None and len(v.split()) > 15:
            raise ValueError("rationale must be 15 words or fewer")
        return v


class HumanLabel(Strict):
    """One human-coded item from human/human_labels.csv, for the agreement check."""
    item_id: NonEmpty
    coder: NonEmpty
    values: dict[str, LabelValue]


# ---- synthesis: what the AI writes (D10, D31) ---------------------------------

PostRef = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]+$")]
Tag = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9 _.:/+&'-]*$")]  # lowercase; product:<name> for products


class Observation(Strict):
    """One line of synthesis/observations.jsonl: the AI's reading of one coded detail post (one per post)."""
    post_id: PostRef
    observation: NonEmpty
    quote: NonEmpty  # verbatim from the post; "..." skips words
    tags: list[Tag] = []


class Insight(Strict):
    id: Annotated[str, Field(pattern=r"^I\d{2,}$")]
    statement: NonEmpty
    post_ids: list[PostRef] = Field(min_length=1)
    counter_post_ids: list[PostRef] = []
    confidence: Literal["high", "medium", "low"]
    recommendations: list[NonEmpty] = []


class Job(Strict):
    id: Annotated[str, Field(pattern=r"^J\d+$")]
    job: NonEmpty  # "When <situation>, I want to <motivation>, so I can <outcome>"
    post_ids: list[PostRef] = Field(min_length=1)


OPPORTUNITY_KINDS = ("fix a pain", "reduce anxiety", "amplify a strength", "serve an unmet job", "implication")


class Opportunity(Strict):
    id: Annotated[str, Field(pattern=r"^OP\d+$")]
    statement: NonEmpty
    kind: Literal[OPPORTUNITY_KINDS]
    aspect: str | None = None
    insight_ids: list[str] = []
    post_ids: list[PostRef] = Field(min_length=1)


class TopDriverTest(Strict):
    type: Literal["top_driver"]
    aspect: NonEmpty


class GreaterTest(Strict):
    type: Literal["greater"]
    a: NonEmpty
    b: NonEmpty
    measure: Literal["share_of_negative", "negative_rate", "mention_rate"] = "share_of_negative"


class AboveTest(Strict):
    type: Literal["above"]
    aspect: NonEmpty
    measure: Literal["share_of_negative", "negative_rate", "mention_rate"] = "share_of_negative"
    threshold: float = Field(ge=0, le=100)


class ProportionTest(Strict):
    type: Literal["proportion"]
    k_ids: list[PostRef]
    n_ids: list[PostRef] = Field(min_length=1)


class Signal(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: NonEmpty
    text: NonEmpty
    test: Annotated[TopDriverTest | GreaterTest | AboveTest | ProportionTest, Field(discriminator="type")] | None = None
    for_ids: list[PostRef] = Field(default=[], alias="for")
    against_ids: list[PostRef] = Field(default=[], alias="against")

    @model_validator(mode="after")
    def _one_kind(self) -> Signal:
        if self.test is not None and (self.for_ids or self.against_ids):
            raise ValueError("a signal has either a test or for/against posts, not both")
        return self


class NextStep(Strict):
    method: NonEmpty
    recruit: str | None = None
    confirm: NonEmpty
    disconfirm: NonEmpty
    questions: list[NonEmpty] = []


class Hypothesis(Strict):
    id: Annotated[str, Field(pattern=r"^H\d+$")]
    origin: Literal["stated", "formed"]  # stated: Steeve's belief, from the unsealed prior (D31)
    owner: str | None = None
    statement: NonEmpty
    importance: Literal["high", "medium", "low"]
    signals: list[Signal] = []
    not_distinguishing: list[PostRef] = []
    next_step: NextStep


# ---- results -----------------------------------------------------------------

Status = Literal["full", "early-signal", "counts-only"]
Range = tuple[float, float]
Resample = Literal["people", "threads"]


class Share(Strict):
    """k of n, with the people and items it rests on and how it was worked out. The status must match the
    thresholds (D11): counts-only carries k and n only. pct is always round(100k/n, 1), so a number typed in
    by hand can't pass. range is the wider of the two resampled ranges (D3, D28)."""
    k: int = Field(ge=0)
    n: int = Field(ge=0)
    n_people: int = Field(ge=0)
    n_items: int = Field(ge=0)
    status: Status
    method: NonEmpty
    pct: float | None = None
    range: Range | None = None
    range_from: Resample | None = None
    range_people: Range | None = None
    range_threads: Range | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Share:
        expected = thresholds.result_status(self.n_people, self.n_items)
        if self.status != expected:
            raise ValueError(f"status is '{self.status}' but {self.n_people} people and "
                             f"{self.n_items} items make it '{expected}'")
        if self.k > self.n:
            raise ValueError(f"k ({self.k}) is more than n ({self.n})")
        ranges = ("range", "range_from", "range_people", "range_threads")
        if self.status == "counts-only":
            given = [f for f in ("pct",) + ranges if getattr(self, f) is not None]
            if given:
                raise ValueError(f"counts-only results can't carry {', '.join(given)}")
            return self
        want = round(100 * self.k / self.n, 1) if self.n else None
        if self.pct != want:
            raise ValueError(f"pct is {self.pct}, but {self.k} of {self.n} is {want}")
        for f in ranges[2:] + ("range",):
            r = getattr(self, f)
            if r is not None and r[0] > r[1]:
                raise ValueError(f"{f} runs high to low")
        if self.range is not None and self.range != getattr(self, f"range_{self.range_from}", None):
            raise ValueError("range must be the range_people or range_threads that range_from names")
        return self


class Probability(Strict):
    """% of re-draws in which something held. pct is whichever of the two is nearer 50% (D29)."""
    pct: float = Field(ge=0, le=100)
    source: Resample
    pct_people: float | None = Field(default=None, ge=0, le=100)
    pct_threads: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _picked(self) -> Probability:
        if self.pct != getattr(self, f"pct_{self.source}"):
            raise ValueError("pct must be the pct_people or pct_threads that source names")
        return self


class Comparison(Strict):
    """Before and after (or first and last period), with the change in points and its resampled range."""
    measure: NonEmpty
    before: Share
    after: Share
    diff_pts: float | None = None
    range: Range | None = None
    range_from: Resample | None = None
    range_people: Range | None = None
    range_threads: Range | None = None
    verdict: Literal["rose", "fell", "no clear change", "insufficient data", "worsening", "improving"]


class SampleInfo(Strict):
    n_items: int = Field(ge=0)
    n_people: int = Field(ge=0)
    n_threads: int = Field(ge=0)
    status: Status
    target: int
    eligible: int
    person_cap: int
    thread_cap_pct: int
    thread_cap_loosened: bool


class Headline(Strict):
    negative: Share
    neutral: Share
    positive: Share
    mean: float | None = None
    people_net_negative: Share  # secondary, per person (D8)


class AspectResult(Strict):
    aspect: NonEmpty
    mentions: int = Field(ge=0)
    people: int = Field(ge=0)
    mean: float | None = None
    strong_negative: int = Field(ge=0)
    ranked: bool
    negative_rate: Share
    share_of_negative: Share
    share_of_positive: Share
    mention_rate: Share
    top_driver: Probability | None = None


class StanceResult(Strict):
    target: str | None = None
    expressing: Share
    in_favour: Share
    against: Share
    neither: Share
    talks_about: dict[Literal["in_favour", "against"], dict[str, Share]]


class EventResult(Strict):
    date: dt.date
    measures: list[Comparison]
    aspect_shifts: list[Comparison]
    note: NonEmpty


class Period(Strict):
    period: NonEmpty
    negative: Share
    top_aspects: dict[str, Share]


class Direction(Strict):
    status: Literal["no timestamps", "single window", "ok"]
    unit: Literal["week", "month"] | None = None
    span_days: int | None = None
    periods: list[Period] = []
    usable_periods: list[str] = []
    trend: Comparison | None = None
    switching: dict[str, Share] = {}
    note: str | None = None


class SourceRow(Strict):
    source: NonEmpty
    share_of_sample: Share
    negative: Share


class Removal(Strict):
    kind: Literal["source", "search_term", "thread"]
    removed: NonEmpty
    negative: Share


class WeightedEstimate(Strict):
    """A share estimated with weights (D27), so it has no whole-number k."""
    pct: float | None = Field(default=None, ge=0, le=100)
    n_people: int = Field(ge=0)
    n_items: int = Field(ge=0)
    status: Status
    method: NonEmpty

    @model_validator(mode="after")
    def _status_fits(self) -> WeightedEstimate:
        expected = thresholds.result_status(self.n_people, self.n_items)
        if self.status != expected:
            raise ValueError(f"status is '{self.status}' but should be '{expected}'")
        if self.status == "counts-only" and self.pct is not None:
            raise ValueError("counts-only results can't carry pct")
        return self


class Sensitivity(Strict):
    removals: list[Removal]
    removals_with_pct: int = Field(default=0, ge=0)  # the rest leave too few people for a percentage (D11)
    min_pct: float | None = None
    max_pct: float | None = None
    most_moved: dict[str, str | float] | None = None
    without_caps: WeightedEstimate | None = None


class Interviews(Strict):
    """Interviews, counted on their own and never pooled with forum figures (D14)."""
    transcripts: int = Field(ge=0)
    participants: int = Field(ge=0)
    turns: int = Field(ge=0)
    coded_turns: int = Field(ge=0)
    codes: dict[str, dict[str, int]] = {}


class KeyTerm(Strict):
    term: NonEmpty
    freq: int
    other_freq: int
    reach: int
    g2: float
    log_ratio: float
    p: float
    q: float | None = None


class Keyness(Strict):
    shown: bool
    reason: str | None = None
    method: NonEmpty
    basis: dict[str, int] = {}
    negative: list[KeyTerm] = []
    positive: list[KeyTerm] = []


class Reach(Strict):
    """How many coded posts and people support something. Interview participants are counted apart (D14)."""
    n: int = Field(ge=0)
    voices: int = Field(ge=0)
    forum_people: int = Field(ge=0)
    interview_participants: int = Field(ge=0)
    post_ids: list[str] = []


class AspectGroup(Reach):
    aspect: NonEmpty
    max_sev: int = 0
    mean_sev: float = 0.0
    strong: int = 0


class InsightResult(Reach):
    id: NonEmpty
    confidence: Literal["high", "medium", "low"]
    strong: int
    counter_n: int
    counter_voices: int
    aspects: list[str] = []
    counter_post_ids: list[str] = []


class JobResult(Reach):
    id: NonEmpty
    forces: dict[str, int]
    aspects: list[str] = []


class OpportunityResult(Reach):
    id: NonEmpty
    kind: NonEmpty
    aspect: str | None = None
    mean_sev: float
    negative_rate_pct: float | None = None
    rank_score: float
    insight_ids: list[str] = []


class ProductResult(Strict):
    name: NonEmpty
    push: int
    pull: int
    anxiety: int
    habit: int
    n: int
    voices: int
    mean_sentiment: float | None = None


class FrameResult(Reach):
    frame: NonEmpty
    aspects: list[str] = []


class SynthesisResult(Strict):
    observations: int
    forces: dict[str, Reach] = {}
    tag_pairs: list[TagPair] = []
    driver_evidence: dict[str, list[str]] = {}  # top drivers -> observed posts that explain them
    unexplained_drivers: list[str] = []
    unexamined: list[str] = []  # flagged detail posts with no observation (up to 12)
    evidence_mix: dict[str, int] = {}
    insights: list[InsightResult] = []
    pains: list[AspectGroup] = []
    successes: list[AspectGroup] = []
    jobs: list[JobResult] = []
    opportunities: list[OpportunityResult] = []
    products: list[ProductResult] = []
    frames: list[FrameResult] = []
    questions: list[AspectGroup] = []


class SignalResult(Strict):
    id: NonEmpty
    kind: Literal["top_driver", "greater", "above", "proportion", "voices"]
    lean: Literal["for", "against", "unclear"]
    probability: Probability | None = None
    share: Share | None = None
    voices_for: int | None = None
    voices_against: int | None = None
    note: str | None = None


class HypothesisResult(Strict):
    id: NonEmpty
    origin: Literal["stated", "formed"]
    importance: Literal["high", "medium", "low"]
    lean: Literal["leans for", "leans against", "mixed", "can't tell from this data"]
    strength: Literal["weak", "moderate", "strong"]
    voices: int
    small_sample: bool
    priority: Literal["test first", "build on it, keep checking", "park for now"]
    signals: list[SignalResult] = []


class Phrase(Strict):
    phrase: NonEmpty
    reach: int
    freq: int


class LanguageResult(Strict):
    phrases: list[Phrase] = []
    signal_rates: dict[str, Share] = {}
    threads: dict[str, dict[str, int]] = {}  # signal flag counts per forum thread


class SourceCount(Strict):
    source: NonEmpty
    threads: int
    posts: int
    capture: list[str] = []
    search_terms: list[str] = []
    searches_logged: int = 0


class SearchLog(Strict):
    logged: int
    neutral: int
    results_seen: int | None = None
    kept: int | None = None
    kept_nothing: int


class DetailSummary(Strict):
    candidates: int
    selected: int
    budget: int
    per_person: int
    all_kept: bool
    echo_replies: int
    interview_turns: int


class CollectionSummary(Strict):
    """How the material was found and checked, for the trust section. Counts only."""
    forum_posts: int
    forum_people: int
    forum_threads: int
    interview_turns: int
    window: tuple[dt.date, dt.date] | None = None
    sources: list[SourceCount] = []
    searches: SearchLog | None = None
    transcription: dict[str, int] = {}  # crp verify statuses
    ingest: dict[str, int] = {}  # duplicates dropped, promotional posts flagged, bot comments removed
    detail: DetailSummary | None = None


class ThemeCluster(Strict):
    cluster_id: NonEmpty
    size: int
    coverage: int
    top_terms: list[str]
    dominated: bool
    linked_insights: list[str] = []
    representative: list[str] = []


class ThemesSummary(Strict):
    source: NonEmpty
    method: NonEmpty
    silhouette: float
    n_items: int
    clusters: list[ThemeCluster] = []
    gaps: list[str] = []  # wide clusters (5+ people) no insight draws on


class TagPair(Strict):
    a: NonEmpty
    b: NonEmpty
    n: int


class RoundRow(Strict):
    """An earlier round, from its own results.json (D35)."""
    round: int
    reason: NonEmpty
    n_items: int | None = None
    n_people: int | None = None
    n_threads: int | None = None
    negative: Share | None = None
    top_driver: str | None = None
    reused_items: int = 0


class Rounds(Strict):
    current: int = Field(ge=2)
    reason: NonEmpty
    earlier: list[RoundRow] = Field(min_length=1)
    change_pts: float | None = None  # this round's negative share minus the last round's, in points


class HeardEnough(Strict):
    """Topics found as coded forum detail posts are read, averaged over random reading orders (D39)."""
    posts: int = Field(ge=2)
    topics: int = Field(ge=1)
    orders: int = Field(ge=1)
    mean: list[float]
    low: list[float]
    high: list[float]
    last_posts: int = Field(ge=1)
    last_new: float = Field(ge=0)

    @model_validator(mode="after")
    def _one_point_per_post(self) -> HeardEnough:
        if not len(self.mean) == len(self.low) == len(self.high) == self.posts:
            raise ValueError("the curve needs one point per post read")
        return self


class Results(Strict):
    """studies/<id>/results/results.json: every number the outputs show, made by crp analyse."""
    study_id: Slug
    seed: int
    bootstrap_draws: int = Field(ge=0)
    inputs: dict[str, str]  # sha256 of every input; no timestamp, so the same seed gives the same file
    codebook_version: NonEmpty
    coder_model: NonEmpty
    agreement_status: dict[str, Literal["verified", "tentative", "unverified"]] = {}  # per variable (D25)
    alpha: dict[str, float | None] = {}
    sample: SampleInfo
    headline: Headline | None = None
    aspects: list[AspectResult] = []
    drivers: list[str] = []
    strengths: list[str] = []
    rare: list[str] = []
    stance: StanceResult | None = None
    event: EventResult | None = None
    direction: Direction | None = None
    by_source: list[SourceRow] = []
    dominant_source: str | None = None
    sensitivity: Sensitivity | None = None
    interviews: Interviews | None = None
    keyness: Keyness | None = None
    language: LanguageResult | None = None
    collection: CollectionSummary | None = None
    themes: ThemesSummary | None = None
    synthesis: SynthesisResult | None = None
    hypotheses: list[HypothesisResult] = []
    rounds: Rounds | None = None
    heard_enough: HeardEnough | None = None
