import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def _reset_ws_state():
    from api.ws import room_registry, _connections, _timer_tasks, _reconnect_tasks
    # Note: never task.cancel() from this (test) thread — the tasks live on the
    # TestClient portal's loop and cross-thread cancellation leaves zombie tasks
    # that deadlock loop shutdown. Orphaned sleeps are cancelled by the runner
    # when the portal stops.
    room_registry.clear()
    _connections.clear()
    _timer_tasks.clear()
    _reconnect_tasks.clear()


@pytest.fixture(autouse=True)
def clean_ws_state():
    """Clear all in-memory WS state before and after every test."""
    _reset_ws_state()
    yield
    _reset_ws_state()
