"""
Tests for all message schema contracts:
  - Client → Server: Pydantic model validation
  - Server → Client: builder output structure
"""
import pytest
from pydantic import ValidationError
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas.messages import (
    GameSettings, CreateRoomMsg, JoinRoomMsg, PlayerActionMsg,
    ChatMessageInMsg, AdminStartGameMsg, AdminAddChipsMsg, AdminTransferMsg,
    AdminKickPlayerMsg, AdminUpdateSettingsMsg, PingMsg,
    room_joined, room_state, player_joined, player_left, admin_changed,
    hand_started, hole_cards_dealt, action_required, player_acted,
    stage_changed, hand_result, chips_updated, player_kicked,
    chat_message_out, error, pong,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _payload(msg: dict) -> dict:
    """Extract payload from a server message dict."""
    return msg["payload"]


# ===========================================================================
# GameSettings
# ===========================================================================

class TestGameSettings:
    def test_defaults(self):
        s = GameSettings()
        assert s.small_blind == 10
        assert s.big_blind == 20
        assert s.starting_chips == 1000
        assert s.turn_timer_seconds == 30

    def test_custom_values(self):
        s = GameSettings(small_blind=25, big_blind=50, starting_chips=2000, turn_timer_seconds=60)
        assert s.small_blind == 25
        assert s.big_blind == 50
        assert s.starting_chips == 2000
        assert s.turn_timer_seconds == 60

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            GameSettings(small_blind="not_an_int")

    def test_zero_blinds_rejected(self):
        with pytest.raises(ValidationError):
            GameSettings(small_blind=0, big_blind=0)

    def test_negative_blinds_rejected(self):
        with pytest.raises(ValidationError):
            GameSettings(small_blind=-10, big_blind=20)

    def test_big_blind_below_small_blind_rejected(self):
        with pytest.raises(ValidationError):
            GameSettings(small_blind=50, big_blind=20)

    def test_zero_starting_chips_rejected(self):
        with pytest.raises(ValidationError):
            GameSettings(starting_chips=0)

    def test_turn_timer_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            GameSettings(turn_timer_seconds=0)
        with pytest.raises(ValidationError):
            GameSettings(turn_timer_seconds=601)


# ===========================================================================
# Client → Server schemas
# ===========================================================================

class TestCreateRoomMsg:
    def test_valid(self):
        m = CreateRoomMsg(type="create_room", display_name="Alice")
        assert m.type == "create_room"
        assert m.display_name == "Alice"
        assert isinstance(m.settings, GameSettings)

    def test_custom_settings(self):
        m = CreateRoomMsg(
            type="create_room",
            display_name="Bob",
            settings={"small_blind": 5, "big_blind": 10},
        )
        assert m.settings.small_blind == 5
        assert m.settings.big_blind == 10

    def test_missing_display_name_raises(self):
        with pytest.raises(ValidationError):
            CreateRoomMsg(type="create_room")

    def test_wrong_type_literal_raises(self):
        with pytest.raises(ValidationError):
            CreateRoomMsg(type="join_room", display_name="Alice")

    def test_display_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            CreateRoomMsg(type="create_room", display_name="x" * 21)


class TestJoinRoomMsg:
    def test_valid_no_token(self):
        m = JoinRoomMsg(type="join_room", room_code="ABC123", display_name="Bob")
        assert m.room_code == "ABC123"
        assert m.reconnect_token is None

    def test_valid_with_token(self):
        m = JoinRoomMsg(
            type="join_room",
            room_code="ABC123",
            display_name="Bob",
            reconnect_token="some-uuid",
        )
        assert m.reconnect_token == "some-uuid"

    def test_missing_room_code_raises(self):
        with pytest.raises(ValidationError):
            JoinRoomMsg(type="join_room", display_name="Bob")

    def test_missing_display_name_raises(self):
        with pytest.raises(ValidationError):
            JoinRoomMsg(type="join_room", room_code="ABC123")


class TestPlayerActionMsg:
    @pytest.mark.parametrize("action", ["fold", "check", "call", "raise", "all_in"])
    def test_valid_actions(self, action):
        m = PlayerActionMsg(type="player_action", action=action)
        assert m.action == action

    def test_default_amount_zero(self):
        m = PlayerActionMsg(type="player_action", action="fold")
        assert m.amount == 0

    def test_custom_amount(self):
        m = PlayerActionMsg(type="player_action", action="raise", amount=100)
        assert m.amount == 100

    def test_invalid_action_raises(self):
        with pytest.raises(ValidationError):
            PlayerActionMsg(type="player_action", action="bluff")

    def test_fractional_amount_raises(self):
        with pytest.raises(ValidationError):
            PlayerActionMsg(type="player_action", action="raise", amount=50.5)


class TestChatMessageInMsg:
    def test_valid(self):
        m = ChatMessageInMsg(type="chat_message", message="Hello!")
        assert m.message == "Hello!"

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ChatMessageInMsg(type="chat_message")


class TestAdminStartGameMsg:
    def test_valid(self):
        m = AdminStartGameMsg(type="admin_start_game")
        assert m.type == "admin_start_game"

    def test_wrong_type_raises(self):
        with pytest.raises(ValidationError):
            AdminStartGameMsg(type="start_game")


class TestAdminAddChipsMsg:
    def test_valid(self):
        m = AdminAddChipsMsg(type="admin_add_chips", target_player_id="pid-123", amount=500)
        assert m.target_player_id == "pid-123"
        assert m.amount == 500

    def test_missing_target_raises(self):
        with pytest.raises(ValidationError):
            AdminAddChipsMsg(type="admin_add_chips", amount=500)

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError):
            AdminAddChipsMsg(type="admin_add_chips", target_player_id="pid-123")


class TestAdminTransferMsg:
    def test_valid(self):
        m = AdminTransferMsg(type="admin_transfer", target_player_id="pid-456")
        assert m.target_player_id == "pid-456"

    def test_missing_target_raises(self):
        with pytest.raises(ValidationError):
            AdminTransferMsg(type="admin_transfer")


class TestAdminKickPlayerMsg:
    def test_valid(self):
        m = AdminKickPlayerMsg(type="admin_kick_player", target_player_id="pid-789")
        assert m.target_player_id == "pid-789"


class TestAdminUpdateSettingsMsg:
    def test_valid(self):
        m = AdminUpdateSettingsMsg(
            type="admin_update_settings",
            settings=GameSettings(small_blind=25, big_blind=50),
        )
        assert m.settings.small_blind == 25

    def test_settings_from_dict(self):
        m = AdminUpdateSettingsMsg(
            type="admin_update_settings",
            settings={"small_blind": 5, "big_blind": 10, "starting_chips": 500, "turn_timer_seconds": 20},
        )
        assert m.settings.small_blind == 5

    def test_missing_settings_raises(self):
        with pytest.raises(ValidationError):
            AdminUpdateSettingsMsg(type="admin_update_settings")


class TestPingMsg:
    def test_valid(self):
        m = PingMsg(type="ping")
        assert m.type == "ping"


# ===========================================================================
# Server → Client message builders
# ===========================================================================

class TestRoomJoinedBuilder:
    def test_structure(self):
        state = {"room_code": "ABC123", "players": [], "stage": "waiting"}
        msg = room_joined("pid-1", "tok-1", state)
        assert msg["type"] == "room_joined"
        p = msg["payload"]
        assert p["player_id"] == "pid-1"
        assert p["reconnect_token"] == "tok-1"
        assert p["room_code"] == "ABC123"
        assert p["players"] == []

    def test_state_merged_into_payload(self):
        state = {"room_code": "XY1234", "admin_id": "a", "pot_total": 100}
        msg = room_joined("p", "t", state)
        p = msg["payload"]
        assert p["admin_id"] == "a"
        assert p["pot_total"] == 100


class TestRoomStateBuilder:
    def test_structure(self):
        state = {"room_code": "AAA111", "stage": "pre_flop", "players": []}
        msg = room_state(state)
        assert msg["type"] == "room_state"
        p = _payload(msg)
        assert p["room_code"] == "AAA111"
        assert p["stage"] == "pre_flop"

    def test_all_state_keys_present(self):
        state = {
            "room_code": "R", "players": [], "admin_id": "a",
            "community_cards": [], "pots": [], "pot_total": 0,
            "stage": "waiting", "current_player_index": -1,
            "current_player_id": None, "dealer_index": 0,
            "small_blind": 10, "big_blind": 20, "hand_number": 0, "settings": {},
        }
        msg = room_state(state)
        p = _payload(msg)
        for key in state:
            assert key in p, f"Key '{key}' missing from room_state payload"


class TestPlayerJoinedBuilder:
    def test_structure(self):
        player = {"id": "p1", "display_name": "Alice", "chips": 1000, "seat_position": 0}
        msg = player_joined(player)
        assert msg["type"] == "player_joined"
        p = _payload(msg)
        assert p["player"]["id"] == "p1"
        assert p["player"]["display_name"] == "Alice"

    def test_player_dict_preserved(self):
        player = {"id": "x", "chips": 500, "is_folded": False}
        msg = player_joined(player)
        assert _payload(msg)["player"]["chips"] == 500


class TestPlayerLeftBuilder:
    def test_with_new_admin(self):
        msg = player_left("pid-gone", "pid-admin")
        assert msg["type"] == "player_left"
        p = _payload(msg)
        assert p["player_id"] == "pid-gone"
        assert p["new_admin_id"] == "pid-admin"

    def test_without_new_admin(self):
        msg = player_left("pid-gone", None)
        p = _payload(msg)
        assert p["new_admin_id"] is None


class TestAdminChangedBuilder:
    def test_structure(self):
        msg = admin_changed("new-pid")
        assert msg["type"] == "admin_changed"
        assert _payload(msg)["new_admin_id"] == "new-pid"


class TestHandStartedBuilder:
    def test_structure(self):
        msg = hand_started(hand_number=3, dealer_seat=0, small_blind_seat=1, big_blind_seat=2)
        assert msg["type"] == "hand_started"
        p = _payload(msg)
        assert p["hand_number"] == 3
        assert p["dealer_seat"] == 0
        assert p["small_blind_seat"] == 1
        assert p["big_blind_seat"] == 2

    def test_required_keys_present(self):
        msg = hand_started(1, 2, 0, 1)
        p = _payload(msg)
        for key in ("hand_number", "dealer_seat", "small_blind_seat", "big_blind_seat"):
            assert key in p


class TestHoleCardsDealtBuilder:
    def test_structure(self):
        cards = [{"rank": "A", "suit": "spades"}, {"rank": "K", "suit": "hearts"}]
        msg = hole_cards_dealt(cards)
        assert msg["type"] == "hole_cards_dealt"
        assert _payload(msg)["cards"] == cards

    def test_empty_cards(self):
        msg = hole_cards_dealt([])
        assert _payload(msg)["cards"] == []


class TestActionRequiredBuilder:
    def test_structure(self):
        msg = action_required(
            player_id="p1",
            valid_actions=["fold", "call", "raise"],
            min_raise=40,
            call_amount=20,
            time_limit_seconds=30,
            deadline=9999.0,
            max_raise=980,
        )
        assert msg["type"] == "action_required"
        p = _payload(msg)
        assert p["player_id"] == "p1"
        assert p["valid_actions"] == ["fold", "call", "raise"]
        assert p["min_raise"] == 40
        assert p["call_amount"] == 20
        assert p["time_limit_seconds"] == 30
        assert p["deadline"] == 9999.0
        assert p["max_raise"] == 980

    def test_max_raise_defaults_to_zero(self):
        msg = action_required("p", ["fold"], 0, 0, 30, 0.0)
        assert _payload(msg)["max_raise"] == 0

    def test_all_required_keys_present(self):
        msg = action_required("p", ["fold", "all_in"], 0, 0, 30, 0.0)
        p = _payload(msg)
        for key in ("player_id", "valid_actions", "min_raise", "call_amount",
                    "time_limit_seconds", "deadline", "max_raise"):
            assert key in p, f"Key '{key}' missing from action_required payload"


class TestPlayerActedBuilder:
    def test_structure(self):
        msg = player_acted("p1", "call", 20, 50)
        assert msg["type"] == "player_acted"
        p = _payload(msg)
        assert p["player_id"] == "p1"
        assert p["action"] == "call"
        assert p["amount"] == 20
        assert p["pot_total"] == 50

    def test_fold_zero_amount(self):
        msg = player_acted("p2", "fold", 0, 30)
        p = _payload(msg)
        assert p["amount"] == 0
        assert p["action"] == "fold"


class TestStageChangedBuilder:
    def test_structure(self):
        cards = [{"rank": "A", "suit": "hearts"}]
        msg = stage_changed("flop", cards)
        assert msg["type"] == "stage_changed"
        p = _payload(msg)
        assert p["stage"] == "flop"
        assert p["community_cards"] == cards

    def test_empty_community_cards(self):
        msg = stage_changed("river", [])
        assert _payload(msg)["community_cards"] == []


class TestHandResultBuilder:
    def test_structure(self):
        winners = [{"player_id": "p1", "amount": 100, "pot": 100}]
        pots = [{"amount": 100, "eligible_player_ids": ["p1", "p2"]}]
        hands = {"p1": {"hand_rank": 9, "hand_name": "Royal Flush", "best_five": []}}
        delta = {"p1": 70, "p2": -30}
        msg = hand_result(winners, pots, hands, delta)
        assert msg["type"] == "hand_result"
        p = _payload(msg)
        assert p["winners"] == winners
        assert p["pots"] == pots
        assert p["player_hands"] == hands
        assert p["chips_delta"] == delta

    def test_required_keys_present(self):
        msg = hand_result([], [], {}, {})
        p = _payload(msg)
        for key in ("winners", "pots", "player_hands", "chips_delta"):
            assert key in p


class TestChipsUpdatedBuilder:
    def test_structure(self):
        msg = chips_updated("p1", 1500, "admin_add")
        assert msg["type"] == "chips_updated"
        p = _payload(msg)
        assert p["player_id"] == "p1"
        assert p["new_total"] == 1500
        assert p["reason"] == "admin_add"


class TestPlayerKickedBuilder:
    def test_structure(self):
        msg = player_kicked("p-bad")
        assert msg["type"] == "player_kicked"
        assert _payload(msg)["player_id"] == "p-bad"


class TestChatMessageOutBuilder:
    def test_structure(self):
        msg = chat_message_out("Alice", "Hello!", False, "2026-01-01T00:00:00Z")
        assert msg["type"] == "chat_message"
        p = _payload(msg)
        assert p["sender_name"] == "Alice"
        assert p["message"] == "Hello!"
        assert p["is_system"] is False
        assert p["timestamp"] == "2026-01-01T00:00:00Z"

    def test_system_message(self):
        msg = chat_message_out("System", "Hand started", True, "2026-01-01T00:00:00Z")
        assert _payload(msg)["is_system"] is True

    def test_required_keys_present(self):
        msg = chat_message_out("x", "y", False, "t")
        p = _payload(msg)
        for key in ("sender_name", "message", "is_system", "timestamp"):
            assert key in p


class TestErrorBuilder:
    def test_structure(self):
        msg = error("room_not_found", "Room ABC does not exist")
        assert msg["type"] == "error"
        p = _payload(msg)
        assert p["code"] == "room_not_found"
        assert p["message"] == "Room ABC does not exist"

    def test_required_keys_present(self):
        msg = error("x", "y")
        p = _payload(msg)
        assert "code" in p
        assert "message" in p


class TestPongBuilder:
    def test_structure(self):
        msg = pong()
        assert msg["type"] == "pong"
        assert msg["payload"] == {}


# ===========================================================================
# Frontend contract: server messages must match what game.js expects
# ===========================================================================

class TestFrontendContracts:
    """Validate that server message payloads contain every key the frontend uses."""

    def test_room_joined_has_player_id_and_reconnect_token(self):
        msg = room_joined("p", "t", {"room_code": "X"})
        p = _payload(msg)
        assert "player_id" in p
        assert "reconnect_token" in p

    def test_player_joined_payload_player_key(self):
        # game.js: payload.player.id, payload.player.display_name
        msg = player_joined({"id": "p", "display_name": "Alice"})
        p = _payload(msg)
        assert "player" in p
        assert "id" in p["player"]
        assert "display_name" in p["player"]

    def test_player_left_has_player_id_and_new_admin_id(self):
        # game.js: payload.player_id, payload.new_admin_id
        msg = player_left("p", "admin")
        p = _payload(msg)
        assert "player_id" in p
        assert "new_admin_id" in p

    def test_admin_changed_has_new_admin_id(self):
        # game.js: payload.new_admin_id
        msg = admin_changed("a")
        assert "new_admin_id" in _payload(msg)

    def test_hand_started_has_seat_fields(self):
        # game.js: payload.hand_number, dealer_seat, small_blind_seat, big_blind_seat
        msg = hand_started(1, 0, 1, 2)
        p = _payload(msg)
        assert "hand_number" in p
        assert "dealer_seat" in p
        assert "small_blind_seat" in p
        assert "big_blind_seat" in p

    def test_action_required_has_max_raise(self):
        # game.js _showActionPanel: payload.max_raise used for slider max
        msg = action_required("p", ["raise"], 40, 20, 30, 0.0, max_raise=980)
        p = _payload(msg)
        assert "max_raise" in p
        assert p["max_raise"] == 980

    def test_action_required_has_all_slider_fields(self):
        # game.js needs: valid_actions, call_amount, min_raise, max_raise, deadline, time_limit_seconds
        msg = action_required("p", ["fold", "call", "raise", "all_in"], 40, 20, 30, 9999.0, max_raise=500)
        p = _payload(msg)
        for key in ("valid_actions", "call_amount", "min_raise", "max_raise", "deadline", "time_limit_seconds"):
            assert key in p, f"Frontend needs '{key}' in action_required"

    def test_player_acted_has_all_keys(self):
        # game.js: player_id, action, amount, pot_total
        msg = player_acted("p", "call", 20, 50)
        p = _payload(msg)
        for key in ("player_id", "action", "amount", "pot_total"):
            assert key in p

    def test_hand_result_winners_structure(self):
        # game.js: w.player_id, w.amount per winner
        winners = [{"player_id": "p1", "amount": 100}]
        msg = hand_result(winners, [], {}, {"p1": 100})
        w = _payload(msg)["winners"][0]
        assert "player_id" in w
        assert "amount" in w

    def test_hand_result_has_chips_delta(self):
        # game.js: payload.chips_delta[p.id]
        msg = hand_result([], [], {}, {"p1": 100, "p2": -50})
        assert "chips_delta" in _payload(msg)

    def test_chips_updated_has_new_total(self):
        # game.js: payload.player_id, payload.new_total
        msg = chips_updated("p", 1500, "admin_add")
        p = _payload(msg)
        assert "player_id" in p
        assert "new_total" in p

    def test_player_kicked_has_player_id(self):
        # game.js: payload.player_id
        msg = player_kicked("p")
        assert "player_id" in _payload(msg)

    def test_error_has_code_and_message(self):
        # game.js: payload.code, payload.message
        msg = error("some_error", "description")
        p = _payload(msg)
        assert "code" in p
        assert "message" in p

    def test_chat_message_out_has_all_keys(self):
        # chat.js needs: sender_name, message, is_system, timestamp
        msg = chat_message_out("Alice", "Hi", False, "2026-01-01T00:00:00Z")
        p = _payload(msg)
        for key in ("sender_name", "message", "is_system", "timestamp"):
            assert key in p
