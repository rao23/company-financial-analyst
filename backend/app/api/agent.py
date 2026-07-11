import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.cache import get_cached_or_run_agent
from app.agent.schemas import FinalAnswer
from app.db import get_db

router = APIRouter(prefix="/agent", tags=["agent"])


class AskRequest(BaseModel):
    ticker: str
    investigation_date: str
    question: str
    thread_id: str | None = None  # omit for a fresh Investigation Thread; pass back in for a follow-up


class AskResponse(FinalAnswer):
    thread_id: str


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    thread_id = request.thread_id or str(uuid.uuid4())
    answer = get_cached_or_run_agent(db, request.ticker, request.investigation_date, request.question, thread_id)
    return AskResponse(**answer.model_dump(), thread_id=thread_id)
