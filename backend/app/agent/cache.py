"""Caches agent answers per (company, Investigation Date, question) --
Phase 6 (DESIGN.md §10). A past Investigation Date's real cause doesn't
change once its filings/news are ingested, so re-running the full
multi-round agent for a repeat click of the same question is pure wasted
LLM cost and latency.

Bump PROMPT_VERSION whenever a prompt/retrieval-logic/model change lands
that the eval harness (Phase 5, CLAUDE.md's merge gate) has validated as
an improvement -- old cache rows keyed on a stale version are simply
never matched again, no manual purge needed.

Deliberately NOT used by the eval harness (app.eval.harness), which calls
run_agent directly: an eval run needs a fresh, unbiased agent invocation
every time, not a cached answer from a prior run of the same
prompt_version.

Deliberately only caches the *first* call in an Investigation Thread.
Follow-up questions (ADR-0009) depend on that thread's accumulated
Grounding Set, so the same question text could legitimately produce a
different answer as a follow-up than as a fresh investigation -- a flat
(company, date, question) key can't capture that, so follow-ups always
bypass the cache and go straight to run_agent.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import COMPILED_GRAPH, run_agent
from app.agent.schemas import FinalAnswer
from app.models import AgentAnswerCache, Company

PROMPT_VERSION = 1


def get_cached_or_run_agent(
    db: Session, ticker: str, investigation_date: str, question: str, thread_id: str
) -> FinalAnswer:
    config = {"configurable": {"thread_id": thread_id}}
    is_follow_up = bool(COMPILED_GRAPH.get_state(config).values)
    if is_follow_up:
        return run_agent(ticker, investigation_date, question, thread_id)

    company = db.execute(select(Company).where(Company.ticker == ticker.upper())).scalar_one()
    date = datetime.date.fromisoformat(investigation_date)

    cached = db.execute(
        select(AgentAnswerCache).where(
            AgentAnswerCache.company_cik == company.cik,
            AgentAnswerCache.investigation_date == date,
            AgentAnswerCache.question == question,
            AgentAnswerCache.prompt_version == PROMPT_VERSION,
        )
    ).scalar_one_or_none()
    if cached is not None:
        return FinalAnswer.model_validate(cached.final_answer)

    answer = run_agent(ticker, investigation_date, question, thread_id)
    db.add(
        AgentAnswerCache(
            company_cik=company.cik,
            investigation_date=date,
            question=question,
            prompt_version=PROMPT_VERSION,
            final_answer=answer.model_dump(mode="json"),
            created_at=datetime.datetime.now(tz=datetime.UTC),
        )
    )
    db.commit()
    return answer
