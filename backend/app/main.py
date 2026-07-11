from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.agent import router as agent_router
from app.api.companies import router as companies_router
from app.db import get_db

app = FastAPI(title="Earnings Timeline AI")

# Dev-only: the Next.js dev server runs on a different origin (localhost:3000
# vs this app's 8000). Tighten this to a real deployed frontend origin before
# shipping anywhere past local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(companies_router)
app.include_router(agent_router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
