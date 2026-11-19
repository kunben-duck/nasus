"""Use the same database clock for canonical confirmation and freshness checks."""
from sqlalchemy import func, select


def confirmation_time(session):
    return session.scalar(select(func.clock_timestamp()))
