"""FastAPI dependencies shared by the routers."""
from __future__ import annotations

from fastapi import Request

from ..config import Config
from ..db import connect
from ..settings import get_config
from .state import AppState


def config() -> Config:
    return get_config()


def get_conn():
    """One database connection per request, committed on success."""
    conn = connect(get_config().db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def app_state(request: Request) -> AppState:
    return request.app.state.photo_state
