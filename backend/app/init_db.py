"""Create all tables registered on Base.metadata. Run once (or after adding
a model) with: python -m app.init_db
"""

from app.db import Base, engine
from app.models import Company, CompanyAlias  # noqa: F401 — registers tables on Base

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
