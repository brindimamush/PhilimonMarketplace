# database/session.py
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

# Create engine
engine = create_engine(DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def db_transaction():
    """
    Atomic database context manager.
    - Commits on success (all changes land together)
    - Rolls back on any exception (nothing is saved on failure)
    - Always closes the session

    Usage:
        with db_transaction() as db:
            user = db.query(User).filter(...).first()
            user.status = 'active'
            deal.status = 'PAID'
        # commit happens automatically here

    If an exception occurs inside the block, rollback is automatic.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()