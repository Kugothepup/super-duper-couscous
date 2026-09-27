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


class Codebook(Strict):
    """studies/<id>/codebook.yaml"""
    version: NonEmpty
    study_type: StudyType
    aspects: list[Annotated[str, Field(pattern=r"^[a-z][a-z-]*( [a-z][a-z-]*)?$")]] = []
    aspect_definitions: dict[str, NonEmpty] = {}
    instructions: list[NonEmpty] = []  # coding rules for every variable, e.g. the coding guide's judgement calls
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


# ---- results -----------------------------------------------------------------

class Measure(Strict):
    """One number-bearing result. Its status must match the thresholds (D11): counts only below 20 people."""
    name: NonEmpty
    method: NonEmpty
    n_people: int = Field(ge=0)
    n_items: int = Field(ge=0)
    status: Literal["full", "early-signal", "counts-only"]
    k: int | None = Field(default=None, ge=0)
    share_pct: float | None = Field(default=None, ge=0, le=100)
    range_pct: tuple[float, float] | None = None
    probability_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _status_fits(self) -> Measure:
        expected = thresholds.result_status(self.n_people, self.n_items)
        if self.status != expected:
            raise ValueError(f"status is '{self.status}' but {self.n_people} people and "
                             f"{self.n_items} items make it '{expected}'")
        if self.status == "counts-only":
            given = [f for f in ("share_pct", "range_pct", "probability_pct") if getattr(self, f) is not None]
            if given:
                raise ValueError(f"counts-only results can't carry {', '.join(given)}")
            if self.k is None:
                raise ValueError("counts-only results need k")
        if self.range_pct is not None and self.range_pct[0] > self.range_pct[1]:
            raise ValueError("range_pct runs high to low")
        return self


class Results(Strict):
    """studies/<id>/results/results.json. Later phases add their sections here."""
    study_id: Slug
    generated_at: dt.datetime
    seed: int
    codebook_version: NonEmpty | None = None
    agreement_status: dict[str, Literal["verified", "tentative", "unverified"]] = {}  # per variable (D25)
    alpha: dict[str, float] = {}
    measures: list[Measure] = []
