import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref


class EvalCase(Base):
    """One hand-labeled ground-truth case: a known historical price move
    (or trend) with its documented real cause -- the offline eval
    harness's regression suite (DESIGN.md §9), and a merge gate for every
    prompt/retrieval/model change from here on.

    Trend cases use a tolerance range (`expected_trend_start_min`/`max`)
    instead of a single expected date, since Trend Start is a
    threshold-tuned, discovered value -- an exact-date match would be
    brittle to any minor swing-detection threshold change (ADR-0004).
    Both fields stay NULL for Move cases.

    `expected_cause_type` includes "no_clear_cause" as a legitimate value
    for the Honesty-on-no-cause cases (DESIGN.md §9) -- those aren't a
    missing label, they're the point of that case.
    """

    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    investigation_date: Mapped[datetime.date]
    query_type: Mapped[str] = mapped_column(String(10))  # "move" | "trend"
    expected_cause_type: Mapped[str] = mapped_column(String(50))  # e.g. "litigation", "partnership", "no_clear_cause"
    expected_source_ref: Mapped[str | None] = mapped_column(String(500))  # accession number or article URL grounding the expected cause
    expected_trend_start_min: Mapped[datetime.date | None]
    expected_trend_start_max: Mapped[datetime.date | None]
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped["Company"] = relationship()
    results: Mapped[list["EvalResult"]] = relationship(
        back_populates="eval_case", cascade="all, delete-orphan"
    )


class EvalResult(Base):
    """One offline-harness run's outcome for one EvalCase (DESIGN.md §9).

    `run_id` groups every EvalResult produced by the same harness
    invocation, so results can be compared run-over-run without a
    separate Run table. Metric fields are nullable since not every metric
    applies to every case -- e.g. `trend_start_accuracy` is only ever
    populated for query_type="trend" cases.

    `numeric_consistency` and `honesty_correct` extend beyond DESIGN.md
    §5's original schema snippet, which only listed 4 of the 6 metrics
    §9 actually defines -- since the whole point of this table is
    tracking every metric run-over-run as a merge gate, leaving two of
    six metrics unpersisted would defeat that.
    """

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"))
    run_id: Mapped[str] = mapped_column(String(50))
    retrieval_hit: Mapped[bool | None]
    faithfulness_score: Mapped[float | None]
    numeric_consistency: Mapped[bool | None]
    timing_correct: Mapped[bool | None]
    trend_start_accuracy: Mapped[bool | None]
    honesty_correct: Mapped[bool | None]
    run_date: Mapped[datetime.datetime]

    eval_case: Mapped["EvalCase"] = relationship(back_populates="results")
