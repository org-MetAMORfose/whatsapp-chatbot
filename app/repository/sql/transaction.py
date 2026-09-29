"""Share one SQL transaction across a message's repository operations."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

_current: ContextVar[Session | None] = ContextVar("sql_transaction", default=None)


@contextmanager
def transaction(factory: Callable[[], Session]) -> Iterator[Session]:
    with factory() as session, session.begin():
        token = _current.set(session)
        try:
            yield session
        finally:
            _current.reset(token)


@contextmanager
def session_scope(factory: Callable[[], Session]) -> Iterator[Session]:
    current = _current.get()
    if current is not None:
        yield current
    else:
        with factory() as session:
            yield session


def commit(session: Session) -> None:
    if session is _current.get():
        session.flush()
    else:
        session.commit()


def current_session() -> Session:
    session = _current.get()
    if session is None:
        raise RuntimeError("An outbox operation requires a business transaction")
    return session
