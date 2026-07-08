"""Create all tables registered on Base.metadata. Run once (or after adding
a model) with: python -m app.init_db
"""

from sqlalchemy import text

from app.db import Base, engine
from app.models import (  # noqa: F401 — registers tables on Base
    Company,
    CompanyAlias,
    Filing,
    FilingChunk,
    FinancialMetric,
    NewsArticle,
    NewsChunk,
    NewsFetchLog,
    PriceHistory,
)

if __name__ == "__main__":
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
