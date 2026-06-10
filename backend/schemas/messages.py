from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal, Optional

MAX_DISPLAY_NAME_LENGTH = 20


# ---- Shared ----

class GameSettings(BaseModel):
    small_blind: int = Field(default=10, ge=1)
    big_blind: int = Field(default=20, ge=1)
    starting_chips: int = Field(default=1000, ge=1)
    turn_timer_seconds: int = Field(default=30, ge=1, le=600)

    @model_validator(mode="after")
    def _big_blind_covers_small_blind(self) -> "GameSettings":
        if self.big_blind < self.small_blind:
            raise ValueError("Big blind must be at least the small blind")
        return self


# ---- Client → Server ----

class CreateRoomMsg(BaseModel):
    type: Literal["create_room"]
    display_name: str = Field(max_length=MAX_DISPLAY_NAME_LENGTH)
    settings: GameSettings = Field(default_factory=GameSettings)


class JoinRoomMsg(BaseModel):
    type: Literal["join_room"]
    room_code: str
    display_name: str = Field(max_length=MAX_DISPLAY_NAME_LENGTH)
    reconnect_token: Optional[str] = None


class PlayerActionMsg(BaseModel):
    type: Literal["player_action"]
    action: Literal["fold", "check", "call", "raise", "all_in"]
    amount: int = 0


class ChatMessageInMsg(BaseModel):
    type: Literal["chat_message"]
    message: str


class AdminStartGameMsg(BaseModel):
    type: Literal["admin_start_game"]


class AdminAddChipsMsg(BaseModel):
    type: Literal["admin_add_chips"]
    target_player_id: str
    amount: int


class AdminTransferMsg(BaseModel):
    type: Literal["admin_transfer"]
    target_player_id: str


class AdminKickPlayerMsg(BaseModel):
    type: Literal["admin_kick_player"]
    target_player_id: str


class AdminUpdateSettingsMsg(BaseModel):
    type: Literal["admin_update_settings"]
    settings: GameSettings


class PingMsg(BaseModel):
    type: Literal["ping"]


# ---- Server → Client ----

def _make(type_: str, **payload) -> dict:
    return {"type": type_, "payload": payload}


def room_joined(player_id: str, reconnect_token: str, room_state: dict) -> dict:
    return {
        "type": "room_joined",
        "payload": {**room_state, "player_id": player_id, "reconnect_token": reconnect_token},
    }


def room_state(state: dict) -> dict:
    return _make("room_state", **state)


def player_joined(player: dict) -> dict:
    return _make("player_joined", player=player)


def player_left(player_id: str, new_admin_id: Optional[str] = None) -> dict:
    return _make("player_left", player_id=player_id, new_admin_id=new_admin_id)


def admin_changed(new_admin_id: str) -> dict:
    return _make("admin_changed", new_admin_id=new_admin_id)


def hand_started(
    hand_number: int,
    dealer_seat: int,
    small_blind_seat: int,
    big_blind_seat: int,
    player_ids: Optional[list] = None,
) -> dict:
    return _make(
        "hand_started",
        hand_number=hand_number,
        dealer_seat=dealer_seat,
        small_blind_seat=small_blind_seat,
        big_blind_seat=big_blind_seat,
        player_ids=player_ids or [],
    )


def hole_cards_dealt(cards: list) -> dict:
    return _make("hole_cards_dealt", cards=cards)


def action_required(
    player_id: str,
    valid_actions: list,
    min_raise: int,
    call_amount: int,
    time_limit_seconds: int,
    deadline: float,
    max_raise: int = 0,
) -> dict:
    return _make(
        "action_required",
        player_id=player_id,
        valid_actions=valid_actions,
        min_raise=min_raise,
        call_amount=call_amount,
        time_limit_seconds=time_limit_seconds,
        deadline=deadline,
        max_raise=max_raise,
    )


def player_acted(player_id: str, action: str, amount: int, pot_total: int) -> dict:
    return _make("player_acted", player_id=player_id, action=action, amount=amount, pot_total=pot_total)


def stage_changed(stage: str, community_cards: list) -> dict:
    return _make("stage_changed", stage=stage, community_cards=community_cards)


def hand_result(winners: list, pots: list, player_hands: dict, chips_delta: dict) -> dict:
    return _make("hand_result", winners=winners, pots=pots, player_hands=player_hands, chips_delta=chips_delta)


def chips_updated(player_id: str, new_total: int, reason: str) -> dict:
    return _make("chips_updated", player_id=player_id, new_total=new_total, reason=reason)


def player_kicked(player_id: str) -> dict:
    return _make("player_kicked", player_id=player_id)


def chat_message_out(sender_name: str, message: str, is_system: bool, timestamp: str) -> dict:
    return _make("chat_message", sender_name=sender_name, message=message, is_system=is_system, timestamp=timestamp)


def error(code: str, message: str) -> dict:
    return _make("error", code=code, message=message)


def pong() -> dict:
    return {"type": "pong", "payload": {}}
