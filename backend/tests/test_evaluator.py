import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game.deck import Card
from game.evaluator import evaluate_hand, compare_hands, find_winners


def cards(*specs):
    """Helper: cards("Ah", "Kh") → [Card("A","hearts"), Card("K","hearts")]"""
    suit_map = {"h": "hearts", "d": "diamonds", "c": "clubs", "s": "spades"}
    result = []
    for spec in specs:
        rank, suit_char = spec[:-1], spec[-1]
        result.append(Card(rank, suit_map[suit_char]))
    return result


# ---- hand type detection ----

def test_royal_flush():
    hand = evaluate_hand(cards("Ah", "Kh", "Qh", "Jh", "10h", "2c", "3d"))
    assert hand.hand_name == "Royal Flush"


def test_straight_flush():
    hand = evaluate_hand(cards("9h", "8h", "7h", "6h", "5h", "2c", "Ad"))
    assert hand.hand_name == "Straight Flush"


def test_four_of_a_kind():
    hand = evaluate_hand(cards("As", "Ah", "Ad", "Ac", "Kh", "2c", "3d"))
    assert hand.hand_name == "Four of a Kind"


def test_full_house():
    hand = evaluate_hand(cards("As", "Ah", "Ad", "Kh", "Kc", "2c", "3d"))
    assert hand.hand_name == "Full House"


def test_flush():
    hand = evaluate_hand(cards("Ah", "Jh", "9h", "7h", "5h", "2c", "3d"))
    assert hand.hand_name == "Flush"


def test_straight():
    hand = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "10h", "2c", "3d"))
    assert hand.hand_name == "Straight"


def test_wheel_straight():
    hand = evaluate_hand(cards("Ah", "2d", "3c", "4s", "5h", "9c", "Kd"))
    assert hand.hand_name == "Straight"
    assert hand.tiebreaker == (5,)


def test_three_of_a_kind():
    hand = evaluate_hand(cards("As", "Ah", "Ad", "Kh", "Qc", "2c", "3d"))
    assert hand.hand_name == "Three of a Kind"


def test_two_pair():
    hand = evaluate_hand(cards("As", "Ah", "Kd", "Kh", "Qc", "2c", "3d"))
    assert hand.hand_name == "Two Pair"


def test_pair():
    hand = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    assert hand.hand_name == "Pair"


def test_high_card():
    hand = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "9h", "2c", "3d"))
    assert hand.hand_name == "High Card"


def test_best_five_has_five_cards():
    hand = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "9h", "2c", "3d"))
    assert len(hand.best_five) == 5


def test_needs_five_cards():
    with pytest.raises(ValueError):
        evaluate_hand(cards("Ah", "Kd", "Qc", "Js"))


# ---- comparison ----

def test_higher_hand_rank_wins():
    flush = evaluate_hand(cards("Ah", "Jh", "9h", "7h", "5h", "2c", "3d"))
    straight = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "10h", "2c", "3d"))
    assert compare_hands(flush, straight) == 1


def test_same_hand_rank_tiebreak():
    high_ace_pair = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    high_king_pair = evaluate_hand(cards("Ks", "Kh", "Ad", "Qh", "Jc", "2c", "3d"))
    assert compare_hands(high_ace_pair, high_king_pair) == 1


def test_identical_hands_tie():
    a = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    b = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    assert compare_hands(a, b) == 0


# ---- find_winners ----

def test_single_winner():
    flush = evaluate_hand(cards("Ah", "Jh", "9h", "7h", "5h", "2c", "3d"))
    straight = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "10h", "2c", "3d"))
    winners = find_winners({"p1": flush, "p2": straight})
    assert winners == ["p1"]


def test_split_pot_tie():
    a = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    b = evaluate_hand(cards("As", "Ah", "Kd", "Qh", "Jc", "2c", "3d"))
    winners = find_winners({"p1": a, "p2": b})
    assert set(winners) == {"p1", "p2"}


def test_three_way_winner():
    best = evaluate_hand(cards("Ah", "Kh", "Qh", "Jh", "10h", "2c", "3d"))
    mid = evaluate_hand(cards("Ah", "Jh", "9h", "7h", "5h", "2c", "3d"))
    low = evaluate_hand(cards("Ah", "Kd", "Qc", "Js", "10h", "2c", "3d"))
    winners = find_winners({"p1": best, "p2": mid, "p3": low})
    assert winners == ["p1"]
