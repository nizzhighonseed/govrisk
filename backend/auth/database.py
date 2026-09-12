from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import AUTH_DATABASE_URL

auth_engine = create_engine(AUTH_DATABASE_URL, connect_args={"check_same_thread": False})
AuthSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)
AuthBase = declarative_base()


def get_auth_db():
    db = AuthSessionLocal()
    try:
        yield db
    finally:
        db.close()
