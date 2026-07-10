import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref


class AgentAnswerCache(Base):
    """A cached FinalAnswer for a (company, Investigation Date, question)
    the agent has already fully answered (Phase 6/DESIGN.md §10) -- a past
    Investigation Date's real cause doesn't change once its filings/news
    are ingested, so re-running the full multi-round agent for a repeat
    click is pure wasted cost/latency.

    `prompt_version` guards against ever serving an answer computed under
    an older prompt/retrieval config: bump the constant in
    app.agent.cache whenever a change lands that the eval harness (Phase
    5) has validated as an improvement -- old rows with a stale version
    are simply never matched again, no manual cache purge needed.

    Deliberately keyed on the exact `question` string, not just
    (company, date): the real UI's click-to-ask is free text (DESIGN.md
    §14), not a fixed canonical question, so two genuinely different
    questions about the same date must not collide. This also means only
    the first (fresh-thread) call in an Investigation Thread is ever
    cacheable -- see app.agent.cache's follow-up bypass.
    """

    __tablename__ = "agent_answer_cache"
    __table_args__ = (
        UniqueConstraint(
            "company_cik", "investigation_date", "question", "prompt_version",
            name="uq_agent_answer_cache_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    investigation_date: Mapped[datetime.date]
    question: Mapped[str] = mapped_column(String(1000))
    prompt_version: Mapped[int]
    final_answer: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime]

    company: Mapped["Company"] = relationship()
