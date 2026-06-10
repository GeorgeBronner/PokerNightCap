from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from .deck import Card, Deck


class GameStage(str, Enum):
    WAITING = "waiting"
    PRE_FLOP = "pre_flop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    HAND_OVER = "hand_over"


@dataclass
class Player:
    id: str
    display_name: str
    chips: int
    seat_position: int
    reconnect_token: str
    connected_at: float

    hole_cards: list[Card] = field(default_factory=list)
    is_active: bool = True
    is_all_in: bool = False
    is_folded: bool = False
    is_connected: bool = True
    current_bet: int = 0
    total_invested: int = 0  # cumulative chips put in across all streets this hand
    disconnect_time: Optional[float] = None

    def to_dict(self, include_hole_cards: bool = False) -> dict:
        d = {
            "id": self.id,
            "display_name": self.display_name,
            "chips": self.chips,
            "seat_position": self.seat_position,
            "is_active": self.is_active,
            "is_all_in": self.is_all_in,
            "is_folded": self.is_folded,
            "is_connected": self.is_connected,
            "current_bet": self.current_bet,
            "has_cards": len(self.hole_cards) > 0,
        }
        if include_hole_cards:
            d["hole_cards"] = [c.to_dict() for c in self.hole_cards]
        return d


@dataclass
class Pot:
    amount: int
    eligible_player_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"amount": self.amount, "eligible_player_ids": self.eligible_player_ids}


@dataclass
class GameState:
    room_code: str
    players: list[Player]
    deck: Deck
    community_cards: list[Card]
    pots: list[Pot]
    stage: GameStage
    dealer_index: int
    current_player_index: int
    small_blind: int
    big_blind: int
    min_raise: int
    hand_number: int
    last_aggressor_index: int = -1
    action_deadline: Optional[float] = None
    turn_timer_seconds: int = 30
    starting_chips: int = 1000
    players_to_act: list[str] = field(default_factory=list)  # ids of players who still must act this round
    # Bet level each player faced after their last action this round; used to
    # decide whether a later all-in reopens their right to raise (TDA rule:
    # a short all-in does not reopen betting for players who already acted)
    acted_at_bet: dict[str, int] = field(default_factory=dict)
