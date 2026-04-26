from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from .config import Config


engine = create_engine(
    Config.DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)


def get_db():
    return SessionLocal()


def close_db(exception=None):
    SessionLocal.remove()
