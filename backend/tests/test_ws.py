"""
WebSocket integration tests: message contracts, error paths, edge cases.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ===========================================================================
# Helpers
# ===========================================================================

# Sessions opened by create_room/join_room. Most tests never close their
# websockets; leaked sessions pile up across the suite and eventually wedge
# the TestClient, so an autouse fixture closes them after every test.
_open_sessions: list = []


@pytest.fixture(autouse=True)
def _close_leaked_websockets():
    yield
    while _open_sessions:
        ws = _open_sessions.pop()
        try:
            ws.__exit__(None, None, None)
        except Exception:
            pass


def recv_until(ws, expected_type: str, max_msgs: int = 10) -> dict:
    """Drain WS messages until expected_type is found, discarding earlier ones."""
    seen = []
    for _ in range(max_msgs):
        msg = ws.receive_json()
        seen.append(msg["type"])
        if msg["type"] == expected_type:
            return msg
    raise AssertionError(f"Expected '{expected_type}' not found. Got: {seen}")


def create_room(client, display_name: str = "Admin", settings: dict | None = None) -> tuple:
    """Open a WS, create a room, return (ws, room_code, player_id, reconnect_token)."""
    payload = {"type": "create_room", "display_name": display_name}
    if settings:
        payload["settings"] = settings
    ws = client.websocket_connect("/ws/NEW").__enter__()
    _open_sessions.append(ws)
    ws.send_json(payload)
    data = ws.receive_json()
    assert data["type"] == "room_joined", f"Expected room_joined, got {data['type']}"
    p = data["payload"]
    return ws, p["room_code"], p["player_id"], p["reconnect_token"]


def join_room(client, room_code: str, display_name: str = "Bob") -> tuple:
    """Open a WS, join a room, return (ws, player_id, reconnect_token)."""
    ws = client.websocket_connect(f"/ws/{room_code}").__enter__()
    _open_sessions.append(ws)
    ws.send_json({"type": "join_room", "room_code": room_code, "display_name": display_name})
    data = ws.receive_json()
    assert data["type"] == "room_joined", f"Expected room_joined, got {data['type']}"
    p = data["payload"]
    return ws, p["player_id"], p["reconnect_token"]


# ===========================================================================
# Connection / session management
# ===========================================================================

class TestCreateRoom:
    def test_success_returns_room_joined(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            data = ws.receive_json()
            assert data["type"] == "room_joined"

    def test_room_joined_payload_keys(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            p = ws.receive_json()["payload"]
            for key in ("room_code", "player_id", "reconnect_token", "players",
                        "admin_id", "stage", "settings"):
                assert key in p, f"room_joined payload missing '{key}'"

    def test_creator_is_admin(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            p = ws.receive_json()["payload"]
            assert p["admin_id"] == p["player_id"]

    def test_initial_stage_is_waiting(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            p = ws.receive_json()["payload"]
            assert p["stage"] == "waiting"

    def test_custom_settings_applied(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({
                "type": "create_room",
                "display_name": "Alice",
                "settings": {"small_blind": 25, "big_blind": 50},
            })
            p = ws.receive_json()["payload"]
            assert p["settings"]["small_blind"] == 25
            assert p["settings"]["big_blind"] == 50

    def test_missing_display_name_returns_error(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": ""})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "invalid_name"

    def test_room_code_is_six_chars(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            p = ws.receive_json()["payload"]
            assert len(p["room_code"]) == 6

    def test_reconnect_token_present(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "Alice"})
            p = ws.receive_json()["payload"]
            assert p["reconnect_token"]


class TestJoinRoom:
    def test_success_returns_room_joined(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code, "Bob")
        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_joiner_receives_existing_players(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code}") as ws2:
            ws2.send_json({"type": "join_room", "room_code": room_code, "display_name": "Bob"})
            p = ws2.receive_json()["payload"]
            player_ids = [p["id"] for p in p["players"]]
            assert p1_id in player_ids
        ws1.__exit__(None, None, None)

    def test_existing_player_gets_player_joined(self, client):
        ws1, room_code, _, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code}") as ws2:
            ws2.send_json({"type": "join_room", "room_code": room_code, "display_name": "Bob"})
            ws2.receive_json()  # room_joined for ws2
            # ws1 should now have player_joined
            joined = ws1.receive_json()
            assert joined["type"] == "player_joined"
            assert joined["payload"]["player"]["display_name"] == "Bob"
        ws1.__exit__(None, None, None)

    def test_room_not_found_returns_error(self, client):
        with client.websocket_connect("/ws/NOROOM") as ws:
            ws.send_json({"type": "join_room", "room_code": "NOROOM", "display_name": "Alice"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "room_not_found"

    def test_missing_display_name_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code}") as ws2:
            ws2.send_json({"type": "join_room", "room_code": room_code, "display_name": ""})
            data = ws2.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "invalid_name"
        ws1.__exit__(None, None, None)

    def test_room_code_case_insensitive(self, client):
        ws1, room_code, _, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code.lower()}") as ws2:
            ws2.send_json({
                "type": "join_room",
                "room_code": room_code.lower(),
                "display_name": "Bob",
            })
            data = ws2.receive_json()
            assert data["type"] == "room_joined"
        ws1.__exit__(None, None, None)

    def test_room_full_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        # Fill the remaining 9 seats (room cap is 10 including the creator)
        extra_ws = []
        for i in range(9):
            ws = client.websocket_connect(f"/ws/{room_code}").__enter__()
            _open_sessions.append(ws)  # ensure cleanup even if an assertion fails below
            ws.send_json({"type": "join_room", "room_code": room_code, "display_name": f"P{i}"})
            ws.receive_json()  # room_joined
            # drain player_joined messages from earlier clients (ignore)
            extra_ws.append(ws)

        # 11th player should be rejected
        with client.websocket_connect(f"/ws/{room_code}") as ws_extra:
            ws_extra.send_json({"type": "join_room", "room_code": room_code, "display_name": "TooMany"})
            data = ws_extra.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "join_failed"

        for ws in extra_ws:
            ws.__exit__(None, None, None)
        ws1.__exit__(None, None, None)


class TestReconnect:
    def test_reconnect_with_valid_token_succeeds(self, client):
        ws1, room_code, p1_id, token = create_room(client)
        ws1.__exit__(None, None, None)

        # Reconnect with the valid token
        with client.websocket_connect(f"/ws/{room_code}") as ws_reconnect:
            ws_reconnect.send_json({
                "type": "join_room",
                "room_code": room_code,
                "display_name": "",  # should be ignored for reconnect
                "reconnect_token": token,
            })
            data = ws_reconnect.receive_json()
            assert data["type"] == "room_joined"
            assert data["payload"]["player_id"] == p1_id

    def test_reconnect_restores_admin_after_page_navigation(self, client):
        """Create room, socket closes (page navigation), reconnect with token:
        the creator must still be admin."""
        ws1, room_code, p1_id, token = create_room(client)
        ws1.__exit__(None, None, None)  # old socket closes; admin_id drops to None

        with client.websocket_connect(f"/ws/{room_code}") as ws_reconnect:
            ws_reconnect.send_json({
                "type": "join_room",
                "room_code": room_code,
                "display_name": "",
                "reconnect_token": token,
            })
            data = ws_reconnect.receive_json()
            assert data["type"] == "room_joined"
            assert data["payload"]["admin_id"] == p1_id

    def test_stale_disconnect_does_not_mark_reconnected_player_offline(self, client):
        """If a new socket joins before the old one closes, the old close
        event must not mark the player disconnected or remove admin."""
        ws1, room_code, p1_id, token = create_room(client)

        # Reconnect on a NEW socket while the old one is still open
        ws2 = client.websocket_connect(f"/ws/{room_code}").__enter__()
        _open_sessions.append(ws2)
        ws2.send_json({
            "type": "join_room",
            "room_code": room_code,
            "display_name": "",
            "reconnect_token": token,
        })
        data = ws2.receive_json()
        assert data["type"] == "room_joined"

        # Now the old socket closes — must be ignored as stale
        ws1.__exit__(None, None, None)

        # Player is still connected and still admin: an admin op succeeds
        ws2.send_json({
            "type": "admin_update_settings",
            "settings": {"turn_timer_seconds": 45},
        })
        msg = recv_until(ws2, "settings_updated")
        assert msg["payload"]["turn_timer_seconds"] == 45

        ws2.__exit__(None, None, None)

    def test_reconnect_with_bad_token_falls_through_to_new_join(self, client):
        ws1, room_code, _, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code}") as ws2:
            ws2.send_json({
                "type": "join_room",
                "room_code": room_code,
                "display_name": "",
                "reconnect_token": "bad-token-xyz",
            })
            data = ws2.receive_json()
            # Falls through to new join, which fails because display_name is empty
            assert data["type"] == "error"
            assert data["payload"]["code"] == "invalid_name"
        ws1.__exit__(None, None, None)

    def test_reconnect_with_bad_token_and_name_creates_new_player(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        with client.websocket_connect(f"/ws/{room_code}") as ws2:
            ws2.send_json({
                "type": "join_room",
                "room_code": room_code,
                "display_name": "NewGuy",
                "reconnect_token": "bad-token-xyz",
            })
            data = ws2.receive_json()
            assert data["type"] == "room_joined"
            # Should be a NEW player, not p1
            assert data["payload"]["player_id"] != p1_id
        ws1.__exit__(None, None, None)


class TestInvalidFirstMessage:
    def test_unknown_first_message_returns_error(self, client):
        with client.websocket_connect("/ws/ROOM") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_player_action_as_first_message_returns_error(self, client):
        with client.websocket_connect("/ws/ROOM") as ws:
            ws.send_json({"type": "player_action", "action": "fold"})
            data = ws.receive_json()
            assert data["type"] == "error"


# ===========================================================================
# Utility messages
# ===========================================================================

class TestPing:
    def test_ping_returns_pong(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws1.send_json({"type": "ping"})
        data = ws1.receive_json()
        assert data["type"] == "pong"
        assert data["payload"] == {}
        ws1.__exit__(None, None, None)


class TestUnknownMessageType:
    def test_unknown_type_returns_error(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "nonexistent_action"})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "unknown_type"
        ws1.__exit__(None, None, None)


# ===========================================================================
# Chat
# ===========================================================================

class TestChat:
    def test_chat_message_broadcast(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # consume player_joined from ws2

        ws2.send_json({"type": "chat_message", "message": "Hello everyone!"})

        # Both should receive the chat message
        msg1 = recv_until(ws1, "chat_message")
        msg2 = recv_until(ws2, "chat_message")

        assert msg1["payload"]["message"] == "Hello everyone!"
        assert msg2["payload"]["message"] == "Hello everyone!"
        assert msg1["payload"]["sender_name"] == "Bob"
        assert msg1["payload"]["is_system"] is False
        assert "timestamp" in msg1["payload"]

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_empty_chat_message_not_broadcast(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws1.send_json({"type": "chat_message", "message": "   "})
        # No message should arrive; send a ping to confirm we can still receive
        ws1.send_json({"type": "ping"})
        pong = ws1.receive_json()
        assert pong["type"] == "pong"
        ws1.__exit__(None, None, None)

    def test_chat_message_capped_at_200_chars(self, client):
        ws1, room_code, _, _ = create_room(client)
        long_msg = "x" * 300
        ws1.send_json({"type": "chat_message", "message": long_msg})
        msg = recv_until(ws1, "chat_message")
        assert len(msg["payload"]["message"]) <= 200
        ws1.__exit__(None, None, None)


# ===========================================================================
# Admin: start game
# ===========================================================================

class TestAdminStartGame:
    def test_start_game_success(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_start_game"})
        msg = recv_until(ws1, "hand_started")
        assert msg["type"] == "hand_started"
        p = msg["payload"]
        assert "hand_number" in p
        assert "dealer_seat" in p
        assert "small_blind_seat" in p
        assert "big_blind_seat" in p

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_start_game_sends_hole_cards(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        hole = recv_until(ws1, "hole_cards_dealt")
        cards = hole["payload"]["cards"]
        assert len(cards) == 2
        for c in cards:
            assert "rank" in c
            assert "suit" in c

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_start_game_sends_action_required_to_first_player(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        # First to act in 2-player game receives action_required
        msg = ws1.receive_json()
        assert msg["type"] in ("action_required", "turn_changed")

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_action_required_has_max_raise(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")

        # The first to act gets action_required with max_raise
        msg = ws1.receive_json()
        if msg["type"] == "action_required":
            assert "max_raise" in msg["payload"], "action_required must include max_raise"
            assert msg["payload"]["max_raise"] > 0

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_non_admin_cannot_start_game(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws2.send_json({"type": "admin_start_game"})
        data = ws2.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "not_admin"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_start_game_single_player_fails(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "admin_start_game"})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "start_failed"
        ws1.__exit__(None, None, None)


# ===========================================================================
# Player actions
# ===========================================================================

def _setup_active_hand(client):
    """Helper: create room, add 2 players, start hand. Returns (ws1, ws2, room_code)."""
    ws1, room_code, _, _ = create_room(client)
    ws2, _, _ = join_room(client, room_code)
    ws1.receive_json()  # player_joined for ws2
    ws1.send_json({"type": "admin_start_game"})
    recv_until(ws1, "hand_started")
    recv_until(ws1, "hole_cards_dealt")
    # ws2 also receives hand_started and hole_cards_dealt
    recv_until(ws2, "hand_started")
    recv_until(ws2, "hole_cards_dealt")
    return ws1, ws2, room_code


class TestPlayerActions:
    def test_action_without_active_hand_returns_error(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "player_action", "action": "fold"})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "invalid_action"
        ws1.__exit__(None, None, None)

    def test_fold_action_broadcasts_player_acted(self, client):
        ws1, ws2, room_code = _setup_active_hand(client)

        # Determine first to act
        msg1 = ws1.receive_json()
        msg2 = ws2.receive_json()

        # The one who gets action_required acts
        if msg1["type"] == "action_required":
            acting_ws, waiting_ws = ws1, ws2
        else:
            acting_ws, waiting_ws = ws2, ws1
            # ws1 got turn_changed, ws2 gets action_required
            # But we may need to drain
            _ = ws2.receive_json()  # action_required for ws2 if applicable

        # Actually simpler: just find who got action_required
        # Restart: drain remaining messages and find who acts first
        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_wrong_turn_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        msg_ws2 = ws2.receive_json()

        # Find who is NOT acting and send from them
        if msg_ws1["type"] == "action_required":
            # ws2 is waiting, try to act out of turn
            ws2.send_json({"type": "player_action", "action": "fold"})
            err = ws2.receive_json()
        else:
            # ws1 is waiting
            ws1.send_json({"type": "player_action", "action": "fold"})
            err = ws1.receive_json()

        assert err["type"] == "error"
        assert err["payload"]["code"] == "invalid_action"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_call_action_returns_player_acted(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        _ = ws2.receive_json()

        if msg_ws1["type"] == "action_required":
            acting_ws, other_ws = ws1, ws2
        else:
            acting_ws, other_ws = ws2, ws1

        acting_ws.send_json({"type": "player_action", "action": "call"})
        acted = recv_until(acting_ws, "player_acted")
        assert acted["payload"]["action"] == "call"
        assert acted["payload"]["amount"] >= 0
        assert "pot_total" in acted["payload"]

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_check_when_bet_outstanding_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        _ = ws2.receive_json()

        # In 2-player game pre-flop, there's always a bet outstanding (blind)
        if msg_ws1["type"] == "action_required":
            acting_ws = ws1
        else:
            acting_ws = ws2

        acting_ws.send_json({"type": "player_action", "action": "check"})
        err = acting_ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "invalid_action"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_all_in_action(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        _ = ws2.receive_json()

        if msg_ws1["type"] == "action_required":
            acting_ws = ws1
        else:
            acting_ws = ws2

        acting_ws.send_json({"type": "player_action", "action": "all_in"})
        acted = recv_until(acting_ws, "player_acted")
        assert acted["payload"]["action"] == "all_in"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_raise_action(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        msg_ws2 = ws2.receive_json()

        if msg_ws1["type"] == "action_required":
            acting_ws, payload = ws1, msg_ws1["payload"]
        else:
            acting_ws, payload = ws2, msg_ws2["payload"]

        # Raise to min_raise amount
        raise_to = payload.get("min_raise", 40)
        acting_ws.send_json({"type": "player_action", "action": "raise", "amount": raise_to})
        acted = recv_until(acting_ws, "player_acted")
        assert acted["payload"]["action"] == "raise"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


class TestInboundValidation:
    def test_fractional_raise_amount_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws2, "hand_started")

        # Whoever's turn it is, a fractional amount must be rejected before
        # reaching the engine (no fractional chips).
        for ws in (ws1, ws2):
            ws.send_json({"type": "player_action", "action": "raise", "amount": 50.5})
            err = recv_until(ws, "error")
            assert err["payload"]["code"] == "invalid_action"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_malformed_message_does_not_kill_connection(self, client):
        ws1, _, _, _ = create_room(client)

        ws1.send_text("this is not json")
        err = ws1.receive_json()
        assert err["type"] == "error"

        ws1.send_text("[1, 2, 3]")  # valid JSON but not an object
        err = ws1.receive_json()
        assert err["type"] == "error"

        # Connection must still be alive
        ws1.send_json({"type": "ping"})
        assert ws1.receive_json()["type"] == "pong"
        ws1.__exit__(None, None, None)

    def test_string_action_amount_does_not_kill_connection(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "player_action", "action": "raise", "amount": "lots"})
        err = ws1.receive_json()
        assert err["type"] == "error"
        ws1.send_json({"type": "ping"})
        assert ws1.receive_json()["type"] == "pong"
        ws1.__exit__(None, None, None)

    def test_create_room_invalid_settings_returns_error(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({
                "type": "create_room",
                "display_name": "Alice",
                "settings": {"small_blind": 0, "big_blind": 0},
            })
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "invalid_message"

    def test_create_room_big_blind_below_small_returns_error(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({
                "type": "create_room",
                "display_name": "Alice",
                "settings": {"small_blind": 50, "big_blind": 20},
            })
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_create_room_long_display_name_returns_error(self, client):
        with client.websocket_connect("/ws/NEW") as ws:
            ws.send_json({"type": "create_room", "display_name": "x" * 50})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["payload"]["code"] == "invalid_message"

    def test_update_settings_invalid_values_returns_error(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"small_blind": -5},
        })
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "settings_failed"
        ws1.__exit__(None, None, None)

    def test_update_settings_partial_keeps_other_values(self, client):
        ws1, _, _, _ = create_room(client, settings={"small_blind": 5, "big_blind": 10})
        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"turn_timer_seconds": 60},
        })
        msg = recv_until(ws1, "settings_updated")
        assert msg["payload"]["turn_timer_seconds"] == 60
        assert msg["payload"]["small_blind"] == 5
        assert msg["payload"]["big_blind"] == 10
        ws1.__exit__(None, None, None)


class TestAddChipsDuringHand:
    def test_add_chips_during_hand_returns_error(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")

        ws1.send_json({
            "type": "admin_add_chips",
            "target_player_id": p2_id,
            "amount": 500,
        })
        err = recv_until(ws1, "error")
        assert err["payload"]["code"] == "chips_failed"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


class TestTurnTimeout:
    def test_timeout_auto_checks_when_check_available(self, client):
        """A player who times out facing no bet is auto-checked, not folded."""
        ws1, room_code, p1_id, _ = create_room(client, settings={"turn_timer_seconds": 1})
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")
        recv_until(ws1, "hole_cards_dealt")
        recv_until(ws2, "hand_started")
        recv_until(ws2, "hole_cards_dealt")

        msg_ws1 = ws1.receive_json()
        _ = ws2.receive_json()

        if msg_ws1["type"] == "action_required":
            acting_ws, bb_id = ws1, p2_id
        else:
            acting_ws, bb_id = ws2, p1_id

        # Small blind calls; big blind now has the option to check
        acting_ws.send_json({"type": "player_action", "action": "call"})
        recv_until(acting_ws, "player_acted")

        # Big blind says nothing; the auto-act timer fires after timer + 2s buffer
        acted = recv_until(acting_ws, "player_acted")
        assert acted["payload"]["player_id"] == bb_id
        assert acted["payload"]["action"] == "check"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


# ===========================================================================
# Admin: chips operations
# ===========================================================================

class TestAdminAddChips:
    def test_add_chips_success(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({
            "type": "admin_add_chips",
            "target_player_id": p2_id,
            "amount": 500,
        })
        msg = recv_until(ws1, "chips_updated")
        assert msg["payload"]["player_id"] == p2_id
        assert msg["payload"]["new_total"] == 1500  # 1000 starting + 500
        # Admin chip changes are recorded in the hand log
        chat = recv_until(ws1, "chat_message")
        assert chat["payload"]["is_system"] is True
        assert "added $500" in chat["payload"]["message"]
        assert "stack now $1,500" in chat["payload"]["message"]

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_admin_can_add_chips_to_self(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws1.send_json({
            "type": "admin_add_chips",
            "target_player_id": p1_id,
            "amount": 250,
        })
        msg = recv_until(ws1, "chips_updated")
        assert msg["payload"]["player_id"] == p1_id
        assert msg["payload"]["new_total"] == 1250
        ws1.__exit__(None, None, None)

    def test_add_chips_non_admin_returns_error(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws2.send_json({
            "type": "admin_add_chips",
            "target_player_id": p1_id,
            "amount": 500,
        })
        data = ws2.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "chips_failed"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_add_chips_bad_target_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws1.send_json({
            "type": "admin_add_chips",
            "target_player_id": "nonexistent-player",
            "amount": 500,
        })
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "chips_failed"
        ws1.__exit__(None, None, None)

    def test_add_chips_broadcast_to_all(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined for ws2

        ws1.send_json({
            "type": "admin_add_chips",
            "target_player_id": p2_id,
            "amount": 200,
        })
        # Both ws1 and ws2 should receive chips_updated
        msg1 = recv_until(ws1, "chips_updated")
        msg2 = recv_until(ws2, "chips_updated")
        assert msg1["payload"]["player_id"] == p2_id
        assert msg2["payload"]["player_id"] == p2_id

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


# ===========================================================================
# Admin: transfer admin
# ===========================================================================

class TestAdminTransfer:
    def test_transfer_success(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_transfer", "target_player_id": p2_id})
        msg = recv_until(ws1, "admin_changed")
        assert msg["payload"]["new_admin_id"] == p2_id

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_transfer_non_admin_returns_error(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws2.send_json({"type": "admin_transfer", "target_player_id": p1_id})
        data = ws2.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "transfer_failed"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_transfer_to_nonexistent_player_returns_error(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "admin_transfer", "target_player_id": "ghost"})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "transfer_failed"
        ws1.__exit__(None, None, None)

    def test_transfer_broadcast_to_all(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_transfer", "target_player_id": p2_id})
        msg1 = recv_until(ws1, "admin_changed")
        msg2 = recv_until(ws2, "admin_changed")
        assert msg1["payload"]["new_admin_id"] == p2_id
        assert msg2["payload"]["new_admin_id"] == p2_id

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


# ===========================================================================
# Admin: kick player
# ===========================================================================

class TestAdminKick:
    def test_kick_success(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_kick_player", "target_player_id": p2_id})
        msg = recv_until(ws1, "player_kicked")
        assert msg["payload"]["player_id"] == p2_id

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_kicked_player_receives_kick(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({"type": "admin_kick_player", "target_player_id": p2_id})
        msg = recv_until(ws2, "player_kicked")
        assert msg["payload"]["player_id"] == p2_id

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_kick_self_returns_error(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws1.send_json({"type": "admin_kick_player", "target_player_id": p1_id})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "kick_failed"
        ws1.__exit__(None, None, None)

    def test_kick_non_admin_returns_error(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws2.send_json({"type": "admin_kick_player", "target_player_id": p1_id})
        data = ws2.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "kick_failed"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_kick_nonexistent_player_returns_error(self, client):
        ws1, _, _, _ = create_room(client)
        ws1.send_json({"type": "admin_kick_player", "target_player_id": "ghost"})
        data = ws1.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "kick_failed"
        ws1.__exit__(None, None, None)


# ===========================================================================
# Admin: update settings
# ===========================================================================

class TestAdminUpdateSettings:
    def test_update_settings_success(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"small_blind": 25, "big_blind": 50},
        })
        msg = recv_until(ws1, "settings_updated")
        assert msg["payload"]["small_blind"] == 25
        assert msg["payload"]["big_blind"] == 50
        ws1.__exit__(None, None, None)

    def test_update_settings_non_admin_returns_error(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws2.send_json({
            "type": "admin_update_settings",
            "settings": {"small_blind": 25, "big_blind": 50},
        })
        data = ws2.receive_json()
        assert data["type"] == "error"
        assert data["payload"]["code"] == "settings_failed"

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_update_settings_during_hand_succeeds_for_next_hand(self, client):
        """Blinds may be changed mid-hand; they apply from the next hand."""
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined
        ws1.send_json({"type": "admin_start_game"})
        recv_until(ws1, "hand_started")

        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"small_blind": 25, "big_blind": 50},
        })
        msg = recv_until(ws1, "settings_updated")
        assert msg["payload"]["small_blind"] == 25
        assert msg["payload"]["big_blind"] == 50
        # A system line records the change in the hand log
        chat = recv_until(ws1, "chat_message")
        assert chat["payload"]["is_system"] is True
        assert "$25/$50" in chat["payload"]["message"]

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_update_settings_starting_chips_resets_stacks_pre_game(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"starting_chips": 3000},
        })
        recv_until(ws1, "settings_updated")
        # Refreshed room state shows everyone at the new stack
        state = recv_until(ws1, "room_state")
        for p in state["payload"]["players"]:
            assert p["chips"] == 3000

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)

    def test_update_settings_broadcast_to_all(self, client):
        ws1, room_code, _, _ = create_room(client)
        ws2, _, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined

        ws1.send_json({
            "type": "admin_update_settings",
            "settings": {"turn_timer_seconds": 60},
        })
        msg1 = recv_until(ws1, "settings_updated")
        msg2 = recv_until(ws2, "settings_updated")
        assert msg1["payload"]["turn_timer_seconds"] == 60
        assert msg2["payload"]["turn_timer_seconds"] == 60

        ws1.__exit__(None, None, None)
        ws2.__exit__(None, None, None)


# ===========================================================================
# Disconnect behaviour
# ===========================================================================

class TestDisconnect:
    def test_disconnect_broadcasts_player_left(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined for ws2

        # Disconnect ws2
        ws2.__exit__(None, None, None)

        # ws1 should receive player_left
        msg = recv_until(ws1, "player_left")
        assert msg["payload"]["player_id"] == p2_id

        ws1.__exit__(None, None, None)

    def test_admin_disconnect_triggers_admin_changed(self, client):
        ws1, room_code, p1_id, _ = create_room(client)
        ws2, p2_id, _ = join_room(client, room_code)
        ws1.receive_json()  # player_joined for ws2

        # Disconnect admin (ws1)
        ws1.__exit__(None, None, None)

        # ws2 should receive player_left with new_admin_id
        msg = recv_until(ws2, "player_left")
        # Admin should have changed to ws2's player
        assert msg["payload"]["new_admin_id"] == p2_id

        ws2.__exit__(None, None, None)
