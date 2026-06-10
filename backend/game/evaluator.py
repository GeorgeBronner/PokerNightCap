from dataclasses import dataclass
from itertools import combinations
from .deck import Card, RANK_VALUE


HAND_RANKS = {
    "high_card": 0,
    "pair": 1,
    "two_pair": 2,
    "three_of_a_kind": 3,
    "straight": 4,
    "flush": 5,
    "full_house": 6,
    "four_of_a_kind": 7,
    "straight_flush": 8,
    "royal_flush": 9,
}


@dataclass
class HandResult:
    hand_rank: int
    hand_name: str
    best_five: list[Card]
    tiebreaker: tuple

    def __gt__(self, other: "HandResult") -> bool:
        return (self.hand_rank, self.tiebreaker) > (other.hand_rank, other.tiebreaker)

    def __lt__(self, other: "HandResult") -> bool:
        return (self.hand_rank, self.tiebreaker) < (other.hand_rank, other.tiebreaker)

    def __eq__(self, other: "HandResult") -> bool:
        return (self.hand_rank, self.tiebreaker) == (other.hand_rank, other.tiebreaker)

    def __ge__(self, other: "HandResult") -> bool:
        return not self.__lt__(other)

    def __le__(self, other: "HandResult") -> bool:
        return not self.__gt__(other)

    def to_dict(self) -> dict:
        return {
            "hand_rank": self.hand_rank,
            "hand_name": self.hand_name,
            "best_five": [c.to_dict() for c in self.best_five],
        }


def _card_values(cards: list[Card]) -> list[int]:
    return sorted([c.value for c in cards], reverse=True)


def _is_flush(cards: list[Card]) -> bool:
    return len({c.suit for c in cards}) == 1


def _is_straight(values: list[int]) -> tuple[bool, int]:
    """Returns (is_straight, high_card_value). Handles A-2-3-4-5 wheel."""
    unique = sorted(set(values), reverse=True)
    for i in range(len(unique) - 4):
        window = unique[i : i + 5]
        if window[0] - window[4] == 4 and len(window) == 5:
            return True, window[0]
    # Wheel: A-2-3-4-5
    if set([14, 2, 3, 4, 5]).issubset(set(values)):
        return True, 5
    return False, 0


def _evaluate_five(cards: list[Card]) -> HandResult:
    assert len(cards) == 5
    values = sorted([c.value for c in cards], reverse=True)
    flush = _is_flush(cards)
    is_str, str_high = _is_straight(values)

    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1

    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    group_counts = [g[1] for g in groups]
    group_vals = [g[0] for g in groups]

    if flush and is_str:
        if str_high == 14:
            return HandResult(HAND_RANKS["royal_flush"], "Royal Flush", cards, (str_high,))
        return HandResult(HAND_RANKS["straight_flush"], "Straight Flush", cards, (str_high,))

    if group_counts[0] == 4:
        return HandResult(HAND_RANKS["four_of_a_kind"], "Four of a Kind", cards, tuple(group_vals))

    if group_counts[0] == 3 and group_counts[1] == 2:
        return HandResult(HAND_RANKS["full_house"], "Full House", cards, tuple(group_vals))

    if flush:
        return HandResult(HAND_RANKS["flush"], "Flush", cards, tuple(values))

    if is_str:
        return HandResult(HAND_RANKS["straight"], "Straight", cards, (str_high,))

    if group_counts[0] == 3:
        return HandResult(HAND_RANKS["three_of_a_kind"], "Three of a Kind", cards, tuple(group_vals))

    if group_counts[0] == 2 and group_counts[1] == 2:
        return HandResult(HAND_RANKS["two_pair"], "Two Pair", cards, tuple(group_vals))

    if group_counts[0] == 2:
        return HandResult(HAND_RANKS["pair"], "Pair", cards, tuple(group_vals))

    return HandResult(HAND_RANKS["high_card"], "High Card", cards, tuple(values))


def evaluate_hand(cards: list[Card]) -> HandResult:
    """Find best 5-card hand from up to 7 cards."""
    if len(cards) < 5:
        raise ValueError("Need at least 5 cards to evaluate")
    best: HandResult | None = None
    for combo in combinations(cards, 5):
        result = _evaluate_five(list(combo))
        if best is None or result > best:
            best = result
    return best  # type: ignore[return-value]


def compare_hands(a: HandResult, b: HandResult) -> int:
    """Return 1 if a wins, -1 if b wins, 0 if tie."""
    if a > b:
        return 1
    if b > a:
        return -1
    return 0


def find_winners(player_hands: dict[str, HandResult]) -> list[str]:
    """Return list of player_ids that won (multiple = split pot)."""
    if not player_hands:
        return []
    best = max(player_hands.values())
    return [pid for pid, hand in player_hands.items() if hand == best]
