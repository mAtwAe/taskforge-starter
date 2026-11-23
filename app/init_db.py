from .database import Base, engine
from . import models  # noqa: F401 - register ORM models

if __name__ == "__main__":
    Base.metadata.create_all(engine)  # Bootstrap only: replace with Alembic migrations.
    print("Database initialized")
