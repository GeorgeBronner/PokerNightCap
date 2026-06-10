from dataclasses import dataclass
from typing import ClassVar
import random

SUITS = ["clubs", "diamonds", "hearts", "spades"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

SUIT_SYMBOL = {"clubs": "♣", "diamonds": "♦", "hearts": "♥", "spades": "♠"}


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    def __post_init__(self):
        if self.rank not in RANK_VALUE:
            raise ValueError(f"Invalid rank: {self.rank}")
        if self.suit not in SUITS:
            raise ValueError(f"Invalid suit: {self.suit}")

    @property
    def value(self) -> int:
        return RANK_VALUE[self.rank]

    @property
    def symbol(self) -> str:
        return SUIT_SYMBOL[self.suit]

    def __str__(self) -> str:
        return f"{self.rank}{self.symbol}"

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit}

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(rank=d["rank"], suit=d["suit"])


class Deck:
    def __init__(self):
        self._cards: list[Card] = [Card(rank, suit) for suit in SUITS for rank in RANKS]
        self._dealt: int = 0

    def shuffle(self) -> None:
        random.shuffle(self._cards)
        self._dealt = 0

    def deal(self, n: int = 1) -> list[Card]:
        if self._dealt + n > len(self._cards):
            raise ValueError("Not enough cards remaining in deck")
        cards = self._cards[self._dealt : self._dealt + n]
        self._dealt += n
        return cards

    @property
    def remaining(self) -> int:
        return len(self._cards) - self._dealt
