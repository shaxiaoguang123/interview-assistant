from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, g
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def init_db(app: Flask) -> None:
    database_url = app.config["DATABASE_URL"]
    url = make_url(database_url)

    if url.get_backend_name() == "sqlite" and url.database not in (None, ":memory:"):
        Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _connection_record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    app.extensions["sqlalchemy_engine"] = engine
    app.extensions["sqlalchemy_session_factory"] = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    app.teardown_appcontext(_close_request_session)


def get_session() -> Session:
    session = g.get("sqlalchemy_session")
    if session is None:
        session_factory = current_app.extensions["sqlalchemy_session_factory"]
        session = session_factory()
        g.sqlalchemy_session = session
    return session


def _close_request_session(_error: BaseException | None = None) -> None:
    session = g.pop("sqlalchemy_session", None)
    if session is None:
        return
    if session.in_transaction():
        session.rollback()
    session.close()
