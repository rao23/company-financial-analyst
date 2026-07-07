from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.companies import router as companies_router
from app.db import get_db

app = FastAPI(title="Earnings Timeline AI")
app.include_router(companies_router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
