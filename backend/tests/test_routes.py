"""
Tests for REST API endpoints.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestIndexPage:
    def test_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_returns_html(self, client):
        r = client.get("/")
        assert "text/html" in r.headers.get("content-type", "")


class TestGamePage:
    def test_returns_200(self, client):
        r = client.get("/game")
        assert r.status_code == 200

    def test_returns_html(self, client):
        r = client.get("/game")
        assert "text/html" in r.headers.get("content-type", "")


class TestRoomExists:
    def test_nonexistent_room_returns_false(self, client):
        r = client.get("/api/room/NOROOM/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": False}

    def test_existing_room_returns_true(self, client):
        # Create a room via WebSocket, then check existence
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            data = ws.receive_json()
            assert data["type"] == "room_joined"
            room_code = data["payload"]["room_code"]

        r = client.get(f"/api/room/{room_code}/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": True}

    def test_room_code_is_case_insensitive(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            data = ws.receive_json()
            room_code = data["payload"]["room_code"]  # always uppercase

        # lowercase should still match
        r = client.get(f"/api/room/{room_code.lower()}/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": True}

    def test_empty_room_code_path_not_found(self, client):
        r = client.get("/api/room/XXXXXX/exists")
        assert r.json()["exists"] is False


class TestRoomHistory:
    def test_nonexistent_room_returns_404(self, client):
        r = client.get("/api/room/NOROOM/history")
        assert r.status_code == 404

    def test_404_has_detail(self, client):
        r = client.get("/api/room/NOROOM/history")
        data = r.json()
        assert "detail" in data

    def test_room_code_case_insensitive_on_404(self, client):
        r = client.get("/api/room/noroom/history")
        assert r.status_code == 404
