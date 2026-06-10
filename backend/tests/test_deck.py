import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game.deck import Card, Deck, RANKS, SUITS, RANK_VALUE


def test_card_value():
    assert Card("2", "clubs").value == 2
    assert Card("A", "spades").value == 14
    assert Card("K", "hearts").value == 13


def test_card_invalid_rank():
    with pytest.raises(ValueError):
        Card("1", "clubs")


def test_card_invalid_suit():
    with pytest.raises(ValueError):
        Card("A", "jokers")


def test_card_str():
    c = Card("A", "spades")
    assert "A" in str(c)
    assert "♠" in str(c)


def test_card_to_dict_roundtrip():
    c = Card("Q", "diamonds")
    assert Card.from_dict(c.to_dict()) == c


def test_deck_has_52_cards():
    d = Deck()
    assert d.remaining == 52


def test_deck_deal():
    d = Deck()
    d.shuffle()
    cards = d.deal(5)
    assert len(cards) == 5
    assert d.remaining == 47


def test_deck_deal_one_by_one():
    d = Deck()
    d.shuffle()
    for _ in range(52):
        d.deal(1)
    assert d.remaining == 0


def test_deck_overdeal_raises():
    d = Deck()
    d.shuffle()
    d.deal(52)
    with pytest.raises(ValueError):
        d.deal(1)


def test_deck_all_unique():
    d = Deck()
    d.shuffle()
    cards = d.deal(52)
    assert len(set(cards)) == 52


def test_deck_contains_all_ranks_and_suits():
    d = Deck()
    cards = d.deal(52)
    for rank in RANKS:
        for suit in SUITS:
            assert Card(rank, suit) in cards
