from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import get_application_settings


class ORMBase(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""

    pass


application_settings = get_application_settings()

database_engine = create_engine(application_settings.database_url, pool_pre_ping=True)
database_session_factory = sessionmaker(
    bind=database_engine,
    autoflush=False,
    autocommit=False,
    class_=Session,
)


def get_database_session() -> Generator[Session, None, None]:
    """Yield a database session for request-scoped persistence work."""
    database_session = database_session_factory()
    try:
        yield database_session
    finally:
        database_session.close()
