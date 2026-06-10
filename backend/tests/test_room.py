import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game.room import Room, generate_room_code
from game.state import GameStage


# ---- helpers ----

def make_room(**kwargs):
    settings = {"small_blind": 10, "big_blind": 20, "starting_chips": 1000, **kwargs}
    return Room("TESTXX", settings)


def two_player_room():
    r = make_room()
    p1 = r.add_player("Alice")
    p2 = r.add_player("Bob")
    return r, p1, p2


# ---- room code generation ----

def test_generate_room_code_length():
    code = generate_room_code(set())
    assert len(code) == 6


def test_generate_room_code_avoids_collisions():
    existing = {"AAAAAA", "BBBBBB"}
    for _ in range(50):
        code = generate_room_code(existing)
        assert code not in existing


# ---- player management ----

def test_add_player():
    r = make_room()
    p = r.add_player("Alice")
    assert p.display_name == "Alice"
    assert p.chips == 1000
    assert p in r.players


def test_first_player_is_admin():
    r = make_room()
    p = r.add_player("Alice")
    assert r.admin_id == p.id


def test_second_player_not_admin():
    r, p1, p2 = two_player_room()
    assert r.admin_id == p1.id


def test_room_full_raises():
    r = make_room()
    for i in range(10):
        r.add_player(f"Player{i}")
    assert len(r.players) == 10
    with pytest.raises(ValueError, match="full"):
        r.add_player("Extra")  # 11th player rejected


def test_remove_player():
    r, p1, p2 = two_player_room()
    r.remove_player(p1.id)
    assert p1 not in r.players


def test_remove_admin_transfers_to_next():
    r, p1, p2 = two_player_room()
    r.remove_player(p1.id)
    assert r.admin_id == p2.id


def test_reconnect_player():
    r, p1, p2 = two_player_room()
    r.mark_disconnected(p1.id)
    assert not p1.is_connected
    found = r.reconnect_player(p1.reconnect_token)
    assert found is p1
    assert p1.is_connected


def test_reconnect_bad_token_returns_none():
    r, p1, _ = two_player_room()
    assert r.reconnect_player("bad-token") is None


def test_reconnect_restores_admin_when_room_adminless():
    """Sole player (the admin) disconnects — admin_id becomes None — then
    reconnects: they must get admin back (create-room page navigation flow)."""
    r = make_room()
    p1 = r.add_player("Alice")
    r.mark_disconnected(p1.id)
    r.admin_id = None  # what ws.on_disconnect does when no one is connected
    found = r.reconnect_player(p1.reconnect_token)
    assert found is p1
    assert r.admin_id == p1.id


# ---- admin operations ----

def test_transfer_admin():
    r, p1, p2 = two_player_room()
    r.transfer_admin(p1.id, p2.id)
    assert r.admin_id == p2.id


def test_transfer_admin_non_admin_raises():
    r, p1, p2 = two_player_room()
    with pytest.raises(PermissionError):
        r.transfer_admin(p2.id, p1.id)


def test_kick_player():
    r, p1, p2 = two_player_room()
    r.kick_player(p1.id, p2.id)
    assert p2 not in r.players


def test_kick_self_raises():
    r, p1, _ = two_player_room()
    with pytest.raises(ValueError):
        r.kick_player(p1.id, p1.id)


def test_add_chips():
    r, p1, p2 = two_player_room()
    r.add_chips(p1.id, p2.id, 500)
    assert p2.chips == 1500


def test_add_chips_non_admin_raises():
    r, p1, p2 = two_player_room()
    with pytest.raises(PermissionError):
        r.add_chips(p2.id, p1.id, 500)


# ---- hand lifecycle ----

def test_start_hand_requires_two_players():
    r = make_room()
    r.add_player("Alice")
    with pytest.raises(ValueError):
        r.start_hand()


def test_start_hand_sets_stage():
    r, _, _ = two_player_room()
    state = r.start_hand()
    assert state.stage == GameStage.PRE_FLOP


def test_start_hand_deals_hole_cards():
    r, p1, p2 = two_player_room()
    r.start_hand()
    for p in r.state.players:
        assert len(p.hole_cards) == 2


def test_start_hand_posts_blinds():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    total_bet = sum(p.current_bet for p in state.players)
    assert total_bet == 30  # SB(10) + BB(20)


def test_start_hand_increments_hand_number():
    r, _, _ = two_player_room()
    r.start_hand()
    assert r.state.hand_number == 1
    r.state.stage = GameStage.HAND_OVER
    r.start_hand()
    assert r.state.hand_number == 2


# ---- actions ----

def test_fold_action():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    r.apply_action(current.id, "fold")
    assert current.is_folded


def test_wrong_turn_raises():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    other = next(p for p in state.players if p.id != current.id)
    with pytest.raises(ValueError, match="not your turn"):
        r.apply_action(other.id, "fold")


def test_call_action():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    chips_before = current.chips
    result = r.apply_action(current.id, "call")
    assert result["action"] == "call"
    assert current.chips < chips_before


def test_check_when_bet_outstanding_raises():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    with pytest.raises(ValueError, match="Cannot check"):
        r.apply_action(current.id, "check")


def test_raise_action():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    result = r.apply_action(current.id, "raise", amount=60)
    assert result["action"] == "raise"
    assert current.current_bet == 60


def test_allin_action():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    r.apply_action(current.id, "all_in")
    assert current.is_all_in
    assert current.chips == 0


# ---- valid actions ----

def test_valid_actions_preflop():
    r, _, _ = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    valid = r.get_valid_actions(current.id)
    assert "fold" in valid["valid_actions"]
    assert "all_in" in valid["valid_actions"]


def test_valid_actions_wrong_player_returns_empty():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    other = next(p for p in state.players if p.id != current.id)
    assert r.get_valid_actions(other.id) == {}


# ---- showdown ----

def test_showdown_one_player_remaining():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    # Fold everyone until one remains
    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        current = state.players[state.current_player_index]
        active = [p for p in state.players if not p.is_folded]
        if len(active) <= 1:
            break
        r.apply_action(current.id, "fold")
    result = r.resolve_showdown()
    assert len(result["winners"]) == 1


def test_showdown_chips_awarded():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    total_chips_before = sum(p.chips + p.current_bet for p in state.players)
    # fold p1 to give p2 the win
    current = state.players[state.current_player_index]
    r.apply_action(current.id, "fold")
    result = r.resolve_showdown()
    total_chips_after = sum(p.chips for p in r.players)
    assert total_chips_before == total_chips_after


# ---- side pots ----

def test_side_pot_all_in_short_stack():
    r = make_room(starting_chips=1000)
    p1 = r.add_player("Short")
    p2 = r.add_player("Mid")
    p3 = r.add_player("Deep")
    # Simulate total contributions (build_side_pots uses total_invested)
    p1.total_invested = 100; p1.is_all_in = True
    p2.total_invested = 500; p2.is_all_in = True
    p3.total_invested = 500
    pots = r.build_side_pots([p1, p2, p3])
    assert len(pots) >= 1
    # Short stack only eligible for first pot
    first_pot = pots[0]
    assert p1.id in first_pot.eligible_player_ids


# ============================================================
# Betting round correctness
# ============================================================

def _play_preflop_all_call(r, state):
    """Drive pre-flop: every player calls, then BB checks their option."""
    # first_to_act (UTG/dealer) and SB call; BB gets option and checks
    # Works for 3-player room where BB needs the option
    while state.stage == GameStage.PRE_FLOP and state.players_to_act:
        current = state.players[state.current_player_index]
        call_amt = r._call_amount(state, current)
        if call_amt == 0:
            r.apply_action(current.id, "check")
        else:
            r.apply_action(current.id, "call")


def test_bb_gets_option_after_all_call():
    """Pre-flop: BB must get to act (check/raise) even after everyone calls."""
    r = make_room()
    r.add_player("P1")  # seat 0 — dealer in hand 1
    r.add_player("P2")  # seat 1 — SB
    r.add_player("P3")  # seat 2 — BB
    state = r.start_hand()
    assert state.stage == GameStage.PRE_FLOP

    # UTG calls
    utg = state.players[state.current_player_index]
    r.apply_action(utg.id, "call")
    # Still pre-flop — SB hasn't acted
    assert state.stage == GameStage.PRE_FLOP

    # SB calls
    sb = state.players[state.current_player_index]
    r.apply_action(sb.id, "call")
    # Still pre-flop — BB still has option
    assert state.stage == GameStage.PRE_FLOP

    # BB should now be current and able to check
    bb = state.players[state.current_player_index]
    valid = r.get_valid_actions(bb.id)
    assert "check" in valid["valid_actions"]

    # BB checks → round ends, flop dealt
    r.apply_action(bb.id, "check")
    assert state.stage == GameStage.FLOP


def test_postflop_all_three_must_check():
    """Post-flop betting round requires all three players to act before advancing."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()
    _play_preflop_all_call(r, state)
    assert state.stage == GameStage.FLOP

    seen_players = []
    for _ in range(3):
        assert state.stage == GameStage.FLOP
        current = state.players[state.current_player_index]
        assert current.id not in seen_players, "Same player acted twice without others acting"
        seen_players.append(current.id)
        r.apply_action(current.id, "check")

    assert state.stage == GameStage.TURN
    assert len(seen_players) == 3


def test_raise_forces_all_to_respond():
    """After a raise, players who already acted must act again."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()
    _play_preflop_all_call(r, state)
    assert state.stage == GameStage.FLOP

    # First player checks
    p_check = state.players[state.current_player_index]
    r.apply_action(p_check.id, "check")
    assert state.stage == GameStage.FLOP

    # Second player raises
    p_raise = state.players[state.current_player_index]
    r.apply_action(p_raise.id, "raise", amount=100)
    assert state.stage == GameStage.FLOP

    # Third player must now act
    p_third = state.players[state.current_player_index]
    assert p_third.id not in (p_check.id, p_raise.id)
    r.apply_action(p_third.id, "call")
    assert state.stage == GameStage.FLOP  # p_check must re-act

    # p_check must re-act
    p_reacting = state.players[state.current_player_index]
    assert p_reacting.id == p_check.id
    r.apply_action(p_reacting.id, "call")
    assert state.stage == GameStage.TURN  # now all have matched the raise


def test_single_raiser_gets_full_round():
    """A raise by P1 must give P2 and P3 a chance to respond before ending."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()
    _play_preflop_all_call(r, state)
    assert state.stage == GameStage.FLOP

    # P1 raises
    p1 = state.players[state.current_player_index]
    r.apply_action(p1.id, "raise", amount=100)
    assert state.stage == GameStage.FLOP

    # P2 calls
    p2 = state.players[state.current_player_index]
    r.apply_action(p2.id, "call")
    assert state.stage == GameStage.FLOP  # P3 must still act

    # P3 calls → round complete
    p3 = state.players[state.current_player_index]
    r.apply_action(p3.id, "call")
    assert state.stage == GameStage.TURN


# ============================================================
# Side pot correctness (uses total_invested across streets)
# ============================================================

def test_side_pot_math_two_all_ins():
    """Three-way pot: P1 all-in for 100, P2 all-in for 300, P3 covers both."""
    r = make_room()
    p1 = r.add_player("Short")
    p2 = r.add_player("Mid")
    p3 = r.add_player("Deep")
    p1.total_invested = 100; p1.is_all_in = True
    p2.total_invested = 300; p2.is_all_in = True
    p3.total_invested = 300
    pots = r.build_side_pots([p1, p2, p3])

    total = sum(pot.amount for pot in pots)
    assert total == 700  # 100+300+300

    # P1 eligible only for first slice
    assert p1.id in pots[0].eligible_player_ids
    for pot in pots[1:]:
        assert p1.id not in pot.eligible_player_ids

    # P2 and P3 share pots 0 and 1
    assert p2.id in pots[0].eligible_player_ids
    assert p3.id in pots[0].eligible_player_ids


def test_side_pot_total_chips_conserved():
    """Chips going into side pots must equal chips coming out."""
    r = make_room(starting_chips=1000)
    p1 = r.add_player("Short")
    p2 = r.add_player("Big")
    p3 = r.add_player("Big2")
    p1.chips = 200
    state = r.start_hand()

    # Drive to showdown by having P1 go all-in and others call
    # Get past pre-flop
    while state.stage == GameStage.PRE_FLOP:
        cur = state.players[state.current_player_index]
        try:
            r.apply_action(cur.id, "all_in")
        except ValueError:
            r.apply_action(cur.id, "call")

    # Track total chips before showdown
    total_before = sum(p.chips + p.total_invested for p in r.players if p.is_active or p.is_all_in)

    # Run out the board and resolve
    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        active = [p for p in state.players if not p.is_folded and not p.is_all_in]
        if not active:
            r.advance_stage()
        else:
            cur = state.players[state.current_player_index]
            r.apply_action(cur.id, "check")

    result = r.resolve_showdown()
    total_after = sum(p.chips for p in r.players)
    assert total_after == total_before


def test_side_pot_multi_street_tracking():
    """total_invested correctly accumulates across streets."""
    r = make_room(starting_chips=1000)
    p1 = r.add_player("P1")
    p2 = r.add_player("P2")
    p3 = r.add_player("P3")
    state = r.start_hand()

    # Pre-flop: everyone calls, BB checks
    _play_preflop_all_call(r, state)
    assert state.stage == GameStage.FLOP

    # Flop: P1 bets 100, others call
    cur = state.players[state.current_player_index]
    first_flop = cur
    r.apply_action(cur.id, "raise", amount=100)
    cur2 = state.players[state.current_player_index]
    r.apply_action(cur2.id, "call")
    cur3 = state.players[state.current_player_index]
    r.apply_action(cur3.id, "call")

    assert state.stage == GameStage.TURN

    # After flop, total_invested should reflect blinds + flop bets
    for p in state.players:
        assert p.total_invested > 0, f"{p.display_name} should have invested chips"

    total_in_pot = sum(pot.amount for pot in state.pots)
    total_invested = sum(p.total_invested for p in state.players)
    assert total_in_pot == total_invested


# ============================================================
# Dealer rotation
# ============================================================

def test_dealer_advances_by_seat_not_list_index():
    """Dealer button uses seat position, not list position."""
    r = make_room()
    r.add_player("P1")  # seat 0
    r.add_player("P2")  # seat 1
    r.add_player("P3")  # seat 2
    state = r.start_hand()
    first_dealer = state.players[state.dealer_index]
    first_seat = first_dealer.seat_position

    # Complete the hand by folding down to one player
    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        active = [p for p in state.players if not p.is_folded]
        if len(active) <= 1:
            break
        cur = state.players[state.current_player_index]
        r.apply_action(cur.id, "fold")
    r.resolve_showdown()

    state2 = r.start_hand()
    next_dealer = state2.players[state2.dealer_index]
    # Dealer must have advanced to the next seat clockwise
    expected_next_seat = (first_seat + 1) % 9
    # With 3 consecutive seats (0,1,2) this finds the next seat
    active_seats = sorted(p.seat_position for p in r.players if p.chips > 0)
    expected = next(s for s in active_seats if s > first_seat) if any(s > first_seat for s in active_seats) else active_seats[0]
    assert next_dealer.seat_position == expected


def test_dealer_rotation_after_player_leaves():
    """Dealer rotation is correct even after a player in the middle leaves."""
    r = make_room()
    p1 = r.add_player("P1")  # seat 0
    p2 = r.add_player("P2")  # seat 1
    p3 = r.add_player("P3")  # seat 2

    state = r.start_hand()
    dealer_before = state.players[state.dealer_index]

    # End hand
    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        active = [p for p in state.players if not p.is_folded]
        if len(active) <= 1:
            break
        cur = state.players[state.current_player_index]
        r.apply_action(cur.id, "fold")
    r.resolve_showdown()

    # Remove the player AFTER the dealer (middle of the rotation)
    dealer_seat = dealer_before.seat_position
    players_by_seat = sorted(r.players, key=lambda p: p.seat_position)
    player_to_remove = next(
        (p for p in players_by_seat if p.seat_position > dealer_seat),
        players_by_seat[0]
    )
    # Give remaining players chips in case one busted
    for p in r.players:
        p.chips = max(p.chips, 200)
    r.remove_player(player_to_remove.id)

    # Dealer must still advance cleanly to next available seat
    state2 = r.start_hand()
    assert state2.dealer_index < len(state2.players)
    new_dealer = state2.players[state2.dealer_index]
    # Dealer should not be the same player as before
    remaining_ids = {p.id for p in r.players}
    assert new_dealer.id in remaining_ids


# ============================================================
# Chip conservation (end-to-end)
# ============================================================

def test_chip_conservation_2player_fold():
    """Total chips are preserved when a hand ends by fold."""
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    total_before = p1.chips + p2.chips + sum(pot.amount for pot in state.pots)

    cur = state.players[state.current_player_index]
    r.apply_action(cur.id, "fold")
    result = r.resolve_showdown()

    total_after = sum(p.chips for p in r.players)
    assert total_after == total_before


def test_chip_conservation_2player_showdown():
    """Total chips are preserved through a contested showdown."""
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    total_start = sum(p.chips for p in r.players) + sum(pot.amount for pot in state.pots)

    # Drive to showdown: call then check all streets
    def drive_to_showdown():
        while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
            cur = state.players[state.current_player_index]
            call_amt = r._call_amount(state, cur)
            if call_amt > 0:
                r.apply_action(cur.id, "call")
            else:
                r.apply_action(cur.id, "check")

    drive_to_showdown()
    r.resolve_showdown()
    total_end = sum(p.chips for p in r.players)
    assert total_end == total_start


# ============================================================
# public_state_dict index correctness
# ============================================================

def test_public_state_current_player_index_matches_id():
    """current_player_index in public_state_dict indexes self.players, not state.players."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    r.start_hand()

    state_dict = r.public_state_dict()
    idx = state_dict["current_player_index"]
    pid = state_dict["current_player_id"]

    if idx >= 0:
        assert state_dict["players"][idx]["id"] == pid


# ============================================================
# Room edge cases not covered above
# ============================================================

def test_update_settings_mid_hand_takes_effect_next_hand():
    """Blinds may change mid-hand; the live hand keeps its snapshot and the
    next hand posts the new blinds."""
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    assert state.stage == GameStage.PRE_FLOP

    result = r.update_settings(p1.id, {"small_blind": 50, "big_blind": 100})
    assert result["changes"] == {"small_blind": 50, "big_blind": 100}
    # Current hand unaffected
    assert state.small_blind == 10
    assert state.big_blind == 20
    assert state.min_raise == 20

    # Finish the hand, then the next one posts the new blinds
    cur = state.players[state.current_player_index]
    r.apply_action(cur.id, "fold")
    r.resolve_showdown()
    state2 = r.start_hand()
    assert state2.small_blind == 50
    assert state2.big_blind == 100
    total_blinds = sum(p.current_bet for p in state2.players)
    assert total_blinds == 150


def test_update_settings_starting_chips_resets_stacks_before_first_hand():
    r, p1, p2 = two_player_room()
    result = r.update_settings(p1.id, {"starting_chips": 2500})
    assert result["stacks_reset"] is True
    assert p1.chips == 2500
    assert p2.chips == 2500
    # New joiners also get the new amount
    p3 = r.add_player("Late")
    assert p3.chips == 2500


def test_update_settings_starting_chips_after_game_started_keeps_stacks():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    cur = state.players[state.current_player_index]
    r.apply_action(cur.id, "fold")
    r.resolve_showdown()

    chips_before = {p.id: p.chips for p in r.players}
    result = r.update_settings(p1.id, {"starting_chips": 5000})
    assert result["stacks_reset"] is False
    for p in r.players:
        assert p.chips == chips_before[p.id]
    # Only future joiners start with the new amount
    p3 = r.add_player("Late")
    assert p3.chips == 5000


def test_update_settings_non_admin_raises():
    r, p1, p2 = two_player_room()
    with pytest.raises(PermissionError):
        r.update_settings(p2.id, {"small_blind": 50})


def test_update_settings_partial_update():
    r = make_room(small_blind=10, big_blind=20, starting_chips=1000, turn_timer_seconds=30)
    r.add_player("Alice")
    r.update_settings(r.admin_id, {"small_blind": 5})
    assert r.small_blind == 5
    assert r.big_blind == 20  # unchanged


def test_resolve_showdown_without_state_raises():
    r = make_room()
    with pytest.raises(ValueError):
        r.resolve_showdown()


def test_get_valid_actions_no_state_returns_empty():
    r, p1, p2 = two_player_room()
    assert r.get_valid_actions(p1.id) == {}


def test_apply_action_no_state_raises():
    r, p1, p2 = two_player_room()
    with pytest.raises(ValueError, match="No active hand"):
        r.apply_action(p1.id, "fold")


def test_add_chips_negative_reduces_chips():
    r, p1, p2 = two_player_room()
    r.add_chips(p1.id, p2.id, -200)
    assert p2.chips == 800


def test_add_chips_nonexistent_player_raises():
    r, p1, _ = two_player_room()
    with pytest.raises(ValueError, match="Player not found"):
        r.add_chips(p1.id, "ghost-id", 100)


def test_kick_nonexistent_player_raises():
    r, p1, _ = two_player_room()
    with pytest.raises(ValueError, match="Player not found"):
        r.kick_player(p1.id, "ghost-id")


def test_transfer_admin_to_nonexistent_player_raises():
    r, p1, _ = two_player_room()
    with pytest.raises(ValueError, match="Target player not found"):
        r.transfer_admin(p1.id, "ghost-id")


def test_public_state_dict_includes_dealer_seat():
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    # Before any hand there is no dealer
    assert r.public_state_dict()["dealer_seat"] is None
    state = r.start_hand()
    expected = state.players[state.dealer_index].seat_position
    assert r.public_state_dict()["dealer_seat"] == expected


def test_public_state_dict_without_game_state():
    r = make_room()
    p = r.add_player("Alice")
    state = r.public_state_dict(for_player_id=p.id)
    assert state["stage"] == GameStage.WAITING.value
    assert state["community_cards"] == []
    assert state["pots"] == []
    assert state["pot_total"] == 0
    assert state["current_player_index"] == -1


def test_start_hand_skips_bankrupt_player():
    r = make_room(starting_chips=1000)
    p1 = r.add_player("Rich")
    p2 = r.add_player("Broke")
    p2.chips = 0  # bankrupt
    p3 = r.add_player("Also Rich")
    state = r.start_hand()
    active_ids = {p.id for p in state.players}
    assert p2.id not in active_ids
    assert p1.id in active_ids
    assert p3.id in active_ids


def test_start_hand_requires_two_with_chips():
    r = make_room(starting_chips=1000)
    p1 = r.add_player("Rich")
    p2 = r.add_player("Broke")
    p2.chips = 0
    with pytest.raises(ValueError, match="Need at least 2"):
        r.start_hand()


def test_two_player_heads_up_blind_structure():
    """In heads-up, dealer posts SB and acts first pre-flop."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    state = r.start_hand()
    assert len(state.players) == 2
    # Dealer index should match the SB in heads-up
    dealer = state.players[state.dealer_index]
    sb_bet = r.small_blind
    assert dealer.current_bet == sb_bet


def test_advance_stage_from_none_does_nothing():
    r = make_room()
    r.advance_stage()  # should not raise


def test_all_in_blind_posting():
    """A player with fewer chips than the blind goes all-in when posting."""
    r = make_room(small_blind=100, big_blind=200)
    p1 = r.add_player("Short")
    p1.chips = 50  # less than small blind
    r.add_player("Normal")
    state = r.start_hand()
    # The short player (dealer/SB in heads-up) should be all-in
    short = next(p for p in state.players if p.id == p1.id)
    assert short.is_all_in
    assert short.chips == 0


def test_build_side_pots_single_pot_no_allins():
    """With no all-ins, build_side_pots returns a single pot with all players."""
    r = make_room()
    p1 = r.add_player("P1")
    p2 = r.add_player("P2")
    p1.total_invested = 200
    p2.total_invested = 200
    pots = r.build_side_pots([p1, p2])
    assert len(pots) == 1
    assert pots[0].amount == 400


def test_build_side_pots_folded_player_chips_in_pot():
    """A folded player's chips stay in the pot but they are not eligible to win."""
    r = make_room()
    p1 = r.add_player("P1")
    p2 = r.add_player("P2")
    p3 = r.add_player("P3")
    p1.total_invested = 300; p1.is_folded = True
    p2.total_invested = 300
    p3.total_invested = 300
    pots = r.build_side_pots([p1, p2, p3])
    total = sum(pot.amount for pot in pots)
    # P1 folded but their 300 chips must remain in the pot
    assert total == 900
    # P1 must not be eligible to win
    for pot in pots:
        assert p1.id not in pot.eligible_player_ids
    # P2 and P3 are eligible
    assert any(p2.id in pot.eligible_player_ids for pot in pots)
    assert any(p3.id in pot.eligible_player_ids for pot in pots)


def test_side_pot_folded_below_allin_level_conserves_chips():
    """A player who folds short of a later all-in level must not subtract chips
    from the side pots (regression: negative slice contribution)."""
    r = make_room()
    a = r.add_player("A")
    b = r.add_player("B")
    c = r.add_player("C")
    a.total_invested = 50; a.is_all_in = True
    b.total_invested = 100; b.is_all_in = True
    c.total_invested = 20; c.is_folded = True
    pots = r.build_side_pots([a, b, c])
    total = sum(pot.amount for pot in pots)
    assert total == 170  # 50 + 100 + 20, no chips lost
    # Main pot: A, B eligible (C folded). Side pot above 50: B only.
    assert a.id in pots[0].eligible_player_ids
    assert c.id not in pots[0].eligible_player_ids
    for pot in pots[1:]:
        assert a.id not in pot.eligible_player_ids
        assert b.id in pot.eligible_player_ids


def test_allin_matching_call_does_not_reopen_round():
    """An all-in (sent as a raise) that only matches the current bet acts as a
    call and must not force already-acted players to act again."""
    r = make_room(starting_chips=1000)
    p1 = r.add_player("P1")  # seat 0 — UTG (first to act pre-flop in a 3-handed game)
    p2 = r.add_player("P2")  # seat 1 — small blind
    p3 = r.add_player("P3")  # seat 2 — big blind
    # UTG can exactly cover the big blind and nothing more.
    p1.chips = r.big_blind
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    assert utg.id == p1.id
    # Raising to the big blind is really just an all-in call; it must not reopen
    # the round for players who already (implicitly) face the same bet.
    r.apply_action(utg.id, "raise", amount=r.big_blind)
    assert utg.is_all_in
    assert utg.id not in state.players_to_act
    # Only the remaining un-acted players are left; no one was re-added.
    assert set(state.players_to_act) <= {p2.id, p3.id}


# ============================================================
# Texas Hold'em rules correctness
# ============================================================

def test_uncalled_bet_returned_when_opponent_all_in_for_less():
    """A bet larger than any opponent can call has its excess returned."""
    r = make_room(small_blind=10, big_blind=20)
    p1 = r.add_player("Big")    # seat 0 — dealer/SB heads-up, acts first
    p2 = r.add_player("Short")  # seat 1 — BB
    p1.chips = 1000
    p2.chips = 100
    state = r.start_hand()

    p1_act = state.players[state.current_player_index]
    assert p1_act.id == p1.id
    r.apply_action(p1.id, "raise", amount=500)   # over-bets Short's stack
    r.apply_action(p2.id, "all_in")              # can only cover 100 total

    # 400 of P1's 500 was never called and must be returned.
    assert p1.chips == 900
    assert sum(pot.amount for pot in state.pots) == 200  # 100 + 100, no dead money
    assert state.stage == GameStage.SHOWDOWN
    # Chip conservation across the whole hand.
    result = r.resolve_showdown()
    assert sum(p.chips for p in r.players) == 1100


def test_uncalled_bet_returned_on_fold():
    """When everyone folds to a raise, the uncalled portion is returned and the
    raiser still collects the dead blinds."""
    r = make_room(small_blind=10, big_blind=20)
    p1 = r.add_player("Raiser")  # dealer/SB heads-up
    p2 = r.add_player("Folder")  # BB
    state = r.start_hand()

    r.apply_action(p1.id, "raise", amount=100)
    r.apply_action(p2.id, "fold")

    # P1's 100 was uncalled → returned; only the BB's 20 remains to be won.
    assert p1.chips == 1000
    assert sum(pot.amount for pot in state.pots) == 20
    r.resolve_showdown()
    assert p1.chips == 1020  # won the dead big blind
    assert p2.chips == 980
    assert p1.chips + p2.chips == 2000


def test_raise_claim_beyond_stack_does_not_corrupt_min_raise():
    """A raise claiming more than the player's stack is clamped to an all-in;
    min_raise must reflect the actual chips committed, not the claim."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("P1")  # seat 0 — UTG pre-flop
    r.add_player("P2")  # seat 1 — SB
    r.add_player("P3")  # seat 2 — BB
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    utg.chips = 25
    r.apply_action(utg.id, "raise", amount=1000)

    assert utg.is_all_in
    assert utg.current_bet == 25  # all-in for the real stack, not the claim
    assert state.min_raise == 20  # a 5-chip short all-in must not move the bar


def test_raise_claim_that_cannot_cover_call_treated_as_allin_call():
    """A 'raise' whose real all-in is below the current bet acts as a call for
    less: it must not reopen the round, change min_raise, or become aggressor."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    r.apply_action(utg.id, "raise", amount=100)  # genuine raise to 100
    aggressor_before = state.last_aggressor_index

    sb = state.players[state.current_player_index]
    sb.chips = 30  # 10 posted + 30 = 40 total, well short of the 100 bet
    r.apply_action(sb.id, "raise", amount=500)

    assert sb.is_all_in
    assert sb.current_bet == 40
    assert state.min_raise == 80  # unchanged from UTG's raise
    assert state.last_aggressor_index == aggressor_before
    assert sb.id not in state.players_to_act


def test_add_chips_during_hand_raises():
    r, p1, p2 = two_player_room()
    r.start_hand()
    with pytest.raises(ValueError, match="during a hand"):
        r.add_chips(p1.id, p2.id, 500)


def test_add_chips_allowed_after_hand_over():
    r, p1, p2 = two_player_room()
    state = r.start_hand()
    cur = state.players[state.current_player_index]
    r.apply_action(cur.id, "fold")
    r.resolve_showdown()
    assert r.state.stage == GameStage.HAND_OVER
    r.add_chips(p1.id, p2.id, 500)


def test_all_in_full_raise_updates_min_raise():
    """A full all-in raise raises the bar for subsequent re-raises."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("P1")  # seat 0 — UTG pre-flop
    r.add_player("P2")  # seat 1 — SB
    r.add_player("P3")  # seat 2 — BB
    state = r.start_hand()
    assert state.min_raise == 20  # big blind

    utg = state.players[state.current_player_index]
    utg.chips = 200  # set before acting; UTG has no blind posted
    r.apply_action(utg.id, "all_in")  # to 200, a 180 raise over the BB

    assert state.min_raise == 180


def test_short_allin_does_not_reopen_raising_for_prior_actor():
    """TDA rule: an all-in short of a full raise lets prior actors only call
    or fold — they may not re-raise."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("UTG")  # seat 0
    r.add_player("SB")   # seat 1
    r.add_player("BB")   # seat 2
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    r.apply_action(utg.id, "raise", amount=100)  # full raise; min_raise=80

    sb = state.players[state.current_player_index]
    r.apply_action(sb.id, "fold")

    bb = state.players[state.current_player_index]
    bb.chips = 110  # 20 posted + 110 = 130 total: only 30 over, short of 80
    r.apply_action(bb.id, "all_in")
    assert bb.current_bet == 130

    # Action returns to UTG who already acted: call/fold only
    back_to = state.players[state.current_player_index]
    assert back_to.id == utg.id
    valid = r.get_valid_actions(utg.id)
    assert "raise" not in valid["valid_actions"]
    assert "all_in" not in valid["valid_actions"]  # stack covers the call, so all-in = raise
    assert "call" in valid["valid_actions"]
    with pytest.raises(ValueError, match="full raise"):
        r.apply_action(utg.id, "raise", amount=300)
    with pytest.raises(ValueError, match="full raise"):
        r.apply_action(utg.id, "all_in")
    r.apply_action(utg.id, "call")  # calling the extra 30 is fine
    # BB is all-in and SB folded, so the board runs out to showdown
    assert state.stage == GameStage.SHOWDOWN
    assert utg.total_invested == 130  # matched BB's all-in exactly


def test_full_allin_raise_reopens_raising_for_prior_actor():
    """An all-in that is a full raise reopens action for everyone."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("UTG")
    r.add_player("SB")
    r.add_player("BB")
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    r.apply_action(utg.id, "raise", amount=100)  # min_raise=80

    sb = state.players[state.current_player_index]
    r.apply_action(sb.id, "fold")

    bb = state.players[state.current_player_index]
    bb.chips = 180  # 20 posted + 180 = 200 total: 100 over, a full raise
    r.apply_action(bb.id, "all_in")

    valid = r.get_valid_actions(utg.id)
    assert "raise" in valid["valid_actions"]
    r.apply_action(utg.id, "raise", amount=300)  # re-raise allowed
    # BB can't call beyond 200, so the round closes: UTG's uncalled 100 is
    # refunded and the board runs out
    assert state.stage == GameStage.SHOWDOWN
    assert utg.total_invested == 200


def test_short_allin_keeps_options_open_for_unacted_player():
    """A player who has not yet acted keeps full options after a short all-in."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("UTG")
    r.add_player("SB")
    r.add_player("BB")
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    utg.chips = 25
    r.apply_action(utg.id, "all_in")  # 25 total: 5 over the BB, a short all-in

    sb = state.players[state.current_player_index]
    valid = r.get_valid_actions(sb.id)
    assert "raise" in valid["valid_actions"]  # SB never acted; rights intact
    r.apply_action(sb.id, "raise", amount=60)
    assert sb.current_bet == 60


def test_cumulative_short_allins_reopen_raising():
    """Multiple short all-ins that together amount to a full raise reopen
    the betting for a prior actor."""
    r = make_room(small_blind=10, big_blind=20, starting_chips=1000)
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()
    _play_preflop_all_call(r, state)
    assert state.stage == GameStage.FLOP

    a = state.players[state.current_player_index]
    r.apply_action(a.id, "raise", amount=100)  # bet 100; min_raise=100

    b = state.players[state.current_player_index]
    b.chips = 150
    r.apply_action(b.id, "all_in")  # to 150: +50, short of 100

    c = state.players[state.current_player_index]
    c.chips = 220
    r.apply_action(c.id, "all_in")  # to 220: +70 more, also short on its own

    # A faces 220 vs the 100 they bet — cumulative 120 >= 100, rights reopen
    back_to = state.players[state.current_player_index]
    assert back_to.id == a.id
    valid = r.get_valid_actions(a.id)
    assert "raise" in valid["valid_actions"]


def test_restricted_player_can_still_allin_call_for_less():
    """A prior actor facing a short all-in may go all-in when their stack
    cannot even cover the call (that's a call, not a raise)."""
    r = make_room(small_blind=10, big_blind=20)
    r.add_player("UTG")
    r.add_player("SB")
    r.add_player("BB")
    state = r.start_hand()

    utg = state.players[state.current_player_index]
    r.apply_action(utg.id, "raise", amount=100)
    utg.chips = 20  # after raising, UTG has only 20 behind

    sb = state.players[state.current_player_index]
    r.apply_action(sb.id, "fold")

    bb = state.players[state.current_player_index]
    bb.chips = 110  # all-in to 130: short of a full raise
    r.apply_action(bb.id, "all_in")

    valid = r.get_valid_actions(utg.id)
    assert "raise" not in valid["valid_actions"]
    assert "all_in" in valid["valid_actions"]  # 20 < 30 owed: all-in is a call
    r.apply_action(utg.id, "all_in")
    assert utg.is_all_in
    assert utg.total_invested == 120  # 100 + remaining 20, still short of 130


def test_board_runs_out_when_all_but_one_all_in():
    """With everyone all-in, the remaining board is dealt with no betting."""
    r = make_room()
    p1 = r.add_player("A")
    p2 = r.add_player("B")
    p1.chips = 100
    p2.chips = 100
    state = r.start_hand()

    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        cur = state.players[state.current_player_index]
        try:
            r.apply_action(cur.id, "all_in")
        except ValueError:
            r.apply_action(cur.id, "call")

    assert state.stage == GameStage.SHOWDOWN
    assert len(state.community_cards) == 5  # full board dealt automatically


def test_odd_chip_goes_left_of_dealer():
    """Odd chips in a split pot are awarded starting left of the dealer."""
    r = make_room()
    p1 = r.add_player("P1")  # seat 0 — dealer on hand 1
    p2 = r.add_player("P2")  # seat 1
    p3 = r.add_player("P3")  # seat 2
    state = r.start_hand()
    assert state.players[state.dealer_index].seat_position == 0

    order = r._order_left_of_dealer(state, [p1.id, p2.id, p3.id])
    assert order[0] == p2.id   # first seat left of the dealer gets the odd chip
    assert order[-1] == p1.id  # the dealer is last in line


def test_valid_actions_returns_max_raise():
    r, _, _ = two_player_room()
    state = r.start_hand()
    current = state.players[state.current_player_index]
    valid = r.get_valid_actions(current.id)
    assert "max_raise" in valid
    assert valid["max_raise"] == current.chips + current.current_bet


def test_valid_actions_check_available_post_flop():
    """After all players call pre-flop, check is available post-flop."""
    r = make_room()
    r.add_player("P1")
    r.add_player("P2")
    r.add_player("P3")
    state = r.start_hand()

    # Drive pre-flop to completion (everyone calls, BB checks)
    while state.stage == GameStage.PRE_FLOP and state.players_to_act:
        cur = state.players[state.current_player_index]
        call = r._call_amount(state, cur)
        if call == 0:
            r.apply_action(cur.id, "check")
        else:
            r.apply_action(cur.id, "call")

    assert state.stage == GameStage.FLOP
    current = state.players[state.current_player_index]
    valid = r.get_valid_actions(current.id)
    assert "check" in valid["valid_actions"]


def test_chip_conservation_with_mid_hand_fold():
    """Chips from a player who folds mid-hand must appear in the winner's stack."""
    r = make_room(starting_chips=1000)
    p1 = r.add_player("P1")
    p2 = r.add_player("P2")
    p3 = r.add_player("P3")
    total_chips = sum(p.chips for p in r.players)

    state = r.start_hand()
    total_in_play = sum(p.chips for p in r.players) + sum(pot.amount for pot in state.pots)
    assert total_in_play == total_chips

    # Pre-flop: P1 folds early, P2 and P3 call/check through to showdown
    while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
        cur = state.players[state.current_player_index]
        # Have one player fold on first action, others call/check
        if cur.id == p1.id and not p1.is_folded and state.stage == GameStage.PRE_FLOP:
            r.apply_action(cur.id, "fold")
        else:
            call = r._call_amount(state, cur)
            try:
                if call > 0:
                    r.apply_action(cur.id, "call")
                else:
                    r.apply_action(cur.id, "check")
            except ValueError:
                break

    if state.stage == GameStage.SHOWDOWN:
        r.resolve_showdown()

    total_after = sum(p.chips for p in r.players)
    assert total_after == total_chips, f"Chips lost: {total_chips} → {total_after}"


def test_chip_conservation_3player_showdown():
    """Total chips are conserved through a full 3-player game to showdown."""
    r = make_room(starting_chips=500)
    p1 = r.add_player("P1")
    p2 = r.add_player("P2")
    p3 = r.add_player("P3")
    total_start = sum(p.chips for p in r.players)

    state = r.start_hand()
    total_start_in_play = sum(p.chips for p in r.players) + sum(pot.amount for pot in state.pots)
    assert total_start_in_play == total_start

    # Drive to showdown: all call/check every street
    def drive():
        while state.stage not in (GameStage.SHOWDOWN, GameStage.HAND_OVER):
            cur = state.players[state.current_player_index]
            call = r._call_amount(state, cur)
            try:
                if call > 0:
                    r.apply_action(cur.id, "call")
                else:
                    r.apply_action(cur.id, "check")
            except Exception:
                break

    drive()
    if state.stage == GameStage.SHOWDOWN:
        r.resolve_showdown()

    total_end = sum(p.chips for p in r.players)
    assert total_end == total_start
