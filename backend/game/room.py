import random
import string
import time
import uuid
from typing import Optional

from .deck import Deck
from .evaluator import HandResult, evaluate_hand, find_winners
from .state import GameStage, GameState, Player, Pot


def generate_room_code(existing: set[str]) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=6))
        if code not in existing:
            return code


class Room:
    def __init__(self, room_code: str, settings: dict):
        self.room_code = room_code
        self.small_blind: int = settings.get("small_blind", 10)
        self.big_blind: int = settings.get("big_blind", 20)
        self.starting_chips: int = settings.get("starting_chips", 1000)
        self.turn_timer_seconds: int = settings.get("turn_timer_seconds", 30)

        self.players: list[Player] = []
        self.admin_id: Optional[str] = None
        self.state: Optional[GameState] = None
        self._hand_number: int = 0

    # -------------------------
    # Player management
    # -------------------------

    def add_player(self, display_name: str) -> Player:
        if len(self.players) >= 10:
            raise ValueError("Room is full (max 10 players)")
        taken_seats = {p.seat_position for p in self.players}
        seat = next(s for s in range(10) if s not in taken_seats)
        player = Player(
            id=str(uuid.uuid4()),
            display_name=display_name,
            chips=self.starting_chips,
            seat_position=seat,
            reconnect_token=str(uuid.uuid4()),
            connected_at=time.time(),
        )
        self.players.append(player)
        if self.admin_id is None:
            self.admin_id = player.id
        return player

    def remove_player(self, player_id: str) -> None:
        was_admin = self.admin_id == player_id
        self.players = [p for p in self.players if p.id != player_id]
        if was_admin:
            elected = self._elect_admin()
            self.admin_id = elected.id if elected else None

    def reconnect_player(self, reconnect_token: str) -> Optional[Player]:
        for p in self.players:
            if p.reconnect_token == reconnect_token:
                p.is_connected = True
                p.disconnect_time = None
                # A room must not stay adminless once someone is connected
                # (happens when the sole player — the admin — reconnects after
                # a page navigation closed their previous socket).
                if self.admin_id is None:
                    self.admin_id = p.id
                return p
        return None

    def get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == player_id), None)

    def get_player_by_token(self, token: str) -> Optional[Player]:
        return next((p for p in self.players if p.reconnect_token == token), None)

    def mark_disconnected(self, player_id: str) -> None:
        p = self.get_player(player_id)
        if p:
            p.is_connected = False
            p.disconnect_time = time.time()

    # -------------------------
    # Admin management
    # -------------------------

    def _elect_admin(self) -> Optional[Player]:
        connected = [p for p in self.players if p.is_connected]
        if not connected:
            return None
        return min(connected, key=lambda p: p.connected_at)

    def transfer_admin(self, from_id: str, to_id: str) -> None:
        if self.admin_id != from_id:
            raise PermissionError("Only the current admin can transfer admin rights")
        target = self.get_player(to_id)
        if not target:
            raise ValueError("Target player not found")
        self.admin_id = to_id

    def kick_player(self, admin_id: str, target_id: str) -> Player:
        if self.admin_id != admin_id:
            raise PermissionError("Only admin can kick players")
        target = self.get_player(target_id)
        if not target:
            raise ValueError("Player not found")
        if target_id == admin_id:
            raise ValueError("Admin cannot kick themselves")
        self.remove_player(target_id)
        return target

    def add_chips(self, admin_id: str, target_id: str, amount: int) -> Player:
        if self.admin_id != admin_id:
            raise PermissionError("Only admin can add chips")
        if self.state and self.state.stage not in (GameStage.WAITING, GameStage.HAND_OVER):
            raise ValueError("Cannot adjust chips during a hand")
        target = self.get_player(target_id)
        if not target:
            raise ValueError("Player not found")
        target.chips += amount
        return target

    def update_settings(self, admin_id: str, settings: dict) -> dict:
        """Apply new room settings. Allowed at any time, even mid-hand: each
        hand snapshots blinds/timer into its GameState at start_hand, so
        changes only take effect from the next hand.

        If starting_chips changes before the first hand has been dealt, every
        seated player's stack is reset to the new amount.

        Returns {"changes": {key: new_value}, "stacks_reset": bool}.
        """
        if self.admin_id != admin_id:
            raise PermissionError("Only admin can update settings")
        changes: dict = {}
        for key in ("small_blind", "big_blind", "starting_chips", "turn_timer_seconds"):
            if key in settings and settings[key] != getattr(self, key):
                changes[key] = settings[key]
                setattr(self, key, settings[key])
        stacks_reset = False
        if "starting_chips" in changes and self.state is None:
            for p in self.players:
                p.chips = self.starting_chips
            stacks_reset = True
        return {"changes": changes, "stacks_reset": stacks_reset}

    # -------------------------
    # Game flow
    # -------------------------

    def start_hand(self) -> GameState:
        active_players = [p for p in self.players if p.chips > 0 and p.is_connected]
        if len(active_players) < 2:
            raise ValueError("Need at least 2 players with chips to start")

        self._hand_number += 1
        deck = Deck()
        deck.shuffle()

        for p in active_players:
            p.hole_cards = []
            p.is_folded = False
            p.is_all_in = False
            p.is_active = True
            p.current_bet = 0
            p.total_invested = 0

        # Determine dealer position (rotate by seat, not list index)
        if self.state is None:
            dealer_idx = 0
        else:
            # Find previous dealer by identity, then advance to next seat clockwise
            prev_dealer_id = self.state.players[self.state.dealer_index].id
            prev_dealer = next((p for p in self.players if p.id == prev_dealer_id), None)
            prev_seat = prev_dealer.seat_position if prev_dealer else -1
            by_seat = sorted(active_players, key=lambda p: p.seat_position)
            next_dealer = next(
                (p for p in by_seat if p.seat_position > prev_seat),
                by_seat[0],  # wrap around to lowest seat
            )
            dealer_idx = active_players.index(next_dealer)

        n = len(active_players)
        sb_idx = (dealer_idx + 1) % n if n > 2 else dealer_idx
        bb_idx = (dealer_idx + 2) % n if n > 2 else (dealer_idx + 1) % n

        # Deal 2 hole cards each (standard order: 1 each then 2nd each)
        for p in active_players:
            p.hole_cards.append(deck.deal(1)[0])
        for p in active_players:
            p.hole_cards.append(deck.deal(1)[0])

        # Post blinds
        sb_player = active_players[sb_idx]
        bb_player = active_players[bb_idx]

        sb_amount = min(self.small_blind, sb_player.chips)
        sb_player.chips -= sb_amount
        sb_player.current_bet = sb_amount
        sb_player.total_invested = sb_amount  # blinds bypass _add_to_pot
        if sb_player.chips == 0:
            sb_player.is_all_in = True

        bb_amount = min(self.big_blind, bb_player.chips)
        bb_player.chips -= bb_amount
        bb_player.current_bet = bb_amount
        bb_player.total_invested = bb_amount
        if bb_player.chips == 0:
            bb_player.is_all_in = True

        # First to act pre-flop is UTG (seat after BB)
        first_to_act = (bb_idx + 1) % n

        pots = [Pot(amount=sb_amount + bb_amount, eligible_player_ids=[p.id for p in active_players])]

        state = GameState(
            room_code=self.room_code,
            players=active_players,
            deck=deck,
            community_cards=[],
            pots=pots,
            stage=GameStage.PRE_FLOP,
            dealer_index=dealer_idx,
            current_player_index=first_to_act,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            min_raise=self.big_blind,
            hand_number=self._hand_number,
            last_aggressor_index=bb_idx,
            turn_timer_seconds=self.turn_timer_seconds,
            starting_chips=self.starting_chips,
            # Everyone (including BB) must act pre-flop; BB gets the option
            players_to_act=[p.id for p in active_players if not p.is_all_in],
        )
        self.state = state
        return self.state

    def apply_action(self, player_id: str, action: str, amount: int = 0) -> dict:
        """
        Process a player action. Returns a dict with action details.
        action: fold | check | call | raise | all_in
        """
        state = self.state
        if state is None or state.stage in (GameStage.WAITING, GameStage.HAND_OVER, GameStage.SHOWDOWN):
            raise ValueError("No active hand")

        players = state.players
        current = players[state.current_player_index]
        if current.id != player_id:
            raise ValueError("It is not your turn")

        player = current
        call_amount = self._call_amount(state, player)
        result = {"player_id": player_id, "action": action, "amount": 0}

        if action == "fold":
            player.is_folded = True
            if player.id in state.players_to_act:
                state.players_to_act.remove(player.id)

        elif action == "check":
            if call_amount > 0:
                raise ValueError(f"Cannot check — call amount is {call_amount}")
            if player.id in state.players_to_act:
                state.players_to_act.remove(player.id)

        elif action == "call":
            actual = min(call_amount, player.chips)
            player.chips -= actual
            player.current_bet += actual
            self._add_to_pot(state, player, actual)
            if player.chips == 0:
                player.is_all_in = True
            if player.id in state.players_to_act:
                state.players_to_act.remove(player.id)
            result["amount"] = actual

        elif action == "raise":
            # amount is the TOTAL bet this player wants to have this round.
            # Clamp to the player's stack so the claimed amount can't inflate
            # min_raise or reopen the round beyond what they actually wager.
            total_bet = min(amount, player.current_bet + player.chips)
            add = total_bet - player.current_bet
            if add <= 0:
                raise ValueError("Raise amount must be greater than current bet")
            raise_amount = total_bet - self._current_max_bet(state)
            if raise_amount > 0 and not self._raise_reopened(state, player):
                raise ValueError("Cannot re-raise — the all-in was less than a full raise; call or fold")
            if raise_amount < state.min_raise and player.chips > add:
                raise ValueError(f"Minimum raise is {state.min_raise}")
            actual = add
            player.chips -= actual
            player.current_bet += actual
            self._add_to_pot(state, player, actual)
            if player.chips == 0:
                player.is_all_in = True
            if raise_amount > 0:
                # Genuine raise above the current bet — everyone else must respond
                state.min_raise = max(state.min_raise, raise_amount)
                state.last_aggressor_index = state.current_player_index
                state.players_to_act = [
                    p.id for p in state.players
                    if p.id != player.id and not p.is_folded and not p.is_all_in and p.is_active
                ]
            else:
                # All-in that only matches the current bet — treat as a call,
                # don't reopen the round for players who already acted
                if player.id in state.players_to_act:
                    state.players_to_act.remove(player.id)
            result["amount"] = actual

        elif action == "all_in":
            # An all-in that exceeds the current bet is a raise and requires
            # raising rights; all-in for less is always allowed (it's a call).
            if (
                player.current_bet + player.chips > self._current_max_bet_excluding(state, player)
                and not self._raise_reopened(state, player)
            ):
                raise ValueError("Cannot re-raise — the all-in was less than a full raise; call or fold")
            actual = player.chips
            player.chips = 0
            player.current_bet += actual
            player.is_all_in = True
            self._add_to_pot(state, player, actual)
            # Determine if this all-in constitutes a raise over the current bet.
            increment = player.current_bet - self._current_max_bet_excluding(state, player)
            if increment > 0:
                # A full raise raises the bar for subsequent re-raises; a short
                # all-in (increment < min_raise) does not change min_raise.
                if increment >= state.min_raise:
                    state.min_raise = increment
                state.last_aggressor_index = state.current_player_index
                state.players_to_act = [
                    p.id for p in state.players
                    if p.id != player.id and not p.is_folded and not p.is_all_in and p.is_active
                ]
            else:
                if player.id in state.players_to_act:
                    state.players_to_act.remove(player.id)
            result["amount"] = actual

        else:
            raise ValueError(f"Unknown action: {action}")

        if not player.is_folded:
            # Remember the bet level faced after acting — a later all-in only
            # reopens this player's raising rights if it grows the bet from
            # here by at least a full raise.
            state.acted_at_bet[player.id] = self._current_max_bet(state)

        self._advance_turn(state)
        result["pot_total"] = sum(p.amount for p in state.pots)
        return result

    def _current_max_bet(self, state: GameState) -> int:
        return max((p.current_bet for p in state.players), default=0)

    def _current_max_bet_excluding(self, state: GameState, exclude: Player) -> int:
        return max((p.current_bet for p in state.players if p.id != exclude.id), default=0)

    def _call_amount(self, state: GameState, player: Player) -> int:
        return max(0, self._current_max_bet(state) - player.current_bet)

    def _raise_reopened(self, state: GameState, player: Player) -> bool:
        """Whether the player currently holds the right to raise.

        A player who has not yet acted this round may always raise. One who
        has acted may re-raise only if the bet has since grown by at least a
        full raise — a short all-in does not reopen betting for them, though
        multiple short all-ins count cumulatively (TDA rules).
        """
        acted_at = state.acted_at_bet.get(player.id)
        if acted_at is None:
            return True
        return self._current_max_bet(state) - acted_at >= state.min_raise

    def _add_to_pot(self, state: GameState, player: Player, amount: int) -> None:
        player.total_invested += amount  # track cumulative investment across all streets
        if state.pots:
            state.pots[0].amount += amount
        else:
            state.pots.append(Pot(amount=amount, eligible_player_ids=[p.id for p in state.players]))

    def _active_not_folded(self, state: GameState) -> list[Player]:
        return [p for p in state.players if not p.is_folded and p.is_active]

    def _return_uncalled_bet(self, state: GameState) -> Optional[dict]:
        """Return an uncalled portion of the current street's bet to the bettor.

        When a betting round closes, at most one player can have wagered more
        than anyone able to call it (everyone else folded or is all-in for less).
        That excess was never matched, so per Texas Hold'em rules it is returned
        to the bettor rather than left in the pot to be contested.
        """
        contenders = [p for p in state.players if not p.is_folded]
        if not contenders:
            return None
        bets = sorted((p.current_bet for p in contenders), reverse=True)
        highest = bets[0]
        second = bets[1] if len(bets) > 1 else 0
        if highest <= second:
            return None  # the top bet was matched (or tied) — nothing uncalled
        top_players = [p for p in contenders if p.current_bet == highest]
        if len(top_players) != 1:
            return None
        top = top_players[0]
        refund = highest - second
        top.chips += refund
        top.current_bet -= refund
        top.total_invested -= refund
        if state.pots:
            state.pots[0].amount -= refund
        return {"player_id": top.id, "amount": refund}

    def _advance_turn(self, state: GameState) -> None:
        active = self._active_not_folded(state)

        # Only one player left — they win
        if len(active) == 1:
            self._return_uncalled_bet(state)
            state.stage = GameStage.SHOWDOWN
            return

        # Check if betting round is complete
        if self._betting_round_complete(state):
            self._return_uncalled_bet(state)
            self.advance_stage()
            return

        # Move to next eligible player
        n = len(state.players)
        idx = state.current_player_index
        for _ in range(n):
            idx = (idx + 1) % n
            p = state.players[idx]
            if not p.is_folded and not p.is_all_in and p.is_active:
                state.current_player_index = idx
                return

        # Everyone else is all-in or folded — advance stage
        self._return_uncalled_bet(state)
        self.advance_stage()

    def _betting_round_complete(self, state: GameState) -> bool:
        eligible = [p for p in state.players if not p.is_folded and not p.is_all_in and p.is_active]
        if not eligible:
            return True
        max_bet = self._current_max_bet(state)
        # If any eligible player still owes chips, round is not over
        if any(p.current_bet < max_bet for p in eligible):
            return False
        # Round ends when every player who needs to act has acted
        return not state.players_to_act

    def advance_stage(self) -> None:
        state = self.state
        if state is None:
            return

        active = self._active_not_folded(state)
        if len(active) <= 1:
            state.stage = GameStage.SHOWDOWN
            return

        # Reset per-street bets
        for p in state.players:
            p.current_bet = 0
        state.min_raise = state.big_blind
        state.acted_at_bet = {}

        if state.stage == GameStage.PRE_FLOP:
            state.community_cards.extend(state.deck.deal(3))
            state.stage = GameStage.FLOP
        elif state.stage == GameStage.FLOP:
            state.community_cards.extend(state.deck.deal(1))
            state.stage = GameStage.TURN
        elif state.stage == GameStage.TURN:
            state.community_cards.extend(state.deck.deal(1))
            state.stage = GameStage.RIVER
        elif state.stage == GameStage.RIVER:
            state.stage = GameStage.SHOWDOWN
            return

        # When at most one player can still act (everyone else is all-in), there
        # is no betting on this street — deal the rest of the board out.
        can_act = [
            p for p in state.players
            if not p.is_folded and not p.is_all_in and p.is_active
        ]
        if len(can_act) <= 1:
            self.advance_stage()
            return

        # Set first to act (first active non-all-in player after dealer)
        n = len(state.players)
        idx = state.dealer_index
        for _ in range(n + 1):
            idx = (idx + 1) % n
            p = state.players[idx]
            if not p.is_folded and not p.is_all_in and p.is_active:
                state.current_player_index = idx
                # Everyone who can act must act this new street
                state.players_to_act = [q.id for q in can_act]
                state.last_aggressor_index = idx
                return

    def build_side_pots(self, players: list[Player]) -> list[Pot]:
        """Build correct side pots from all-in players using total_invested.

        Folded players' chips are included in pot amounts (already in the pot)
        but those players are not eligible to win any slice.
        """
        active = [p for p in players if not p.is_folded]
        if not active:
            return []

        # Separate eligibility (non-folded only) from pot amounts (everyone who invested)
        active_contributions = {p.id: p.total_invested for p in active}
        all_contributions = {p.id: p.total_invested for p in players if p.total_invested > 0}

        # Side-pot levels are determined by non-folded all-in players
        all_in_amounts = sorted(set(active_contributions[p.id] for p in active if p.is_all_in))

        pots: list[Pot] = []
        prev_level = 0

        for level in all_in_amounts:
            eligible = [p.id for p in active if active_contributions[p.id] >= level]
            # Each contributor adds the slice of their investment that falls within
            # [prev_level, level]. Clamp at 0 so contributors who put in less than
            # prev_level (e.g. folded short of a later all-in) don't subtract chips.
            pot_amount = sum(max(0, min(invested, level) - prev_level) for invested in all_contributions.values())
            if pot_amount > 0:
                pots.append(Pot(amount=pot_amount, eligible_player_ids=eligible))
            prev_level = level

        # Remaining pot above the highest all-in level
        max_level = max(all_contributions.values()) if all_contributions else 0
        if max_level > prev_level:
            eligible = [p.id for p in active if active_contributions[p.id] >= max_level]
            pot_amount = sum(invested - prev_level for invested in all_contributions.values() if invested > prev_level)
            if pot_amount > 0 and eligible:
                pots.append(Pot(amount=pot_amount, eligible_player_ids=eligible))

        return pots if pots else [Pot(amount=sum(all_contributions.values()), eligible_player_ids=list(active_contributions.keys()))]

    def _order_left_of_dealer(self, state: GameState, player_ids: list[str]) -> list[str]:
        """Order players by seat starting from the first seat left of the dealer.

        Used for odd-chip distribution in split pots: the extra chip(s) go to the
        player(s) closest to the dealer's left (worst position).
        """
        dealer_seat = state.players[state.dealer_index].seat_position

        def key(pid: str) -> int:
            p = self.get_player(pid)
            seat = p.seat_position if p else 0
            return (seat - dealer_seat - 1) % 10  # dealer+1 first, dealer last

        return sorted(player_ids, key=key)

    def resolve_showdown(self) -> dict:
        """Evaluate hands, distribute pots, return result dict."""
        state = self.state
        if state is None:
            raise ValueError("No active game state")

        active = self._active_not_folded(state)

        # If only one player remains (everyone else folded)
        if len(active) == 1:
            winner = active[0]
            total_pot = sum(p.amount for p in state.pots)
            winner.chips += total_pot
            state.stage = GameStage.HAND_OVER

            # Snapshot before reset so callers can read hole cards
            hole_cards_snapshot = {p.id: [c.to_dict() for c in p.hole_cards] for p in state.players}

            result = {
                "winners": [{"player_id": winner.id, "amount": total_pot, "reason": "last_player"}],
                "player_hands": {},
                "chips_delta": {winner.id: total_pot},
                "pots": [p.to_dict() for p in state.pots],
                "hole_cards_snapshot": hole_cards_snapshot,
            }
            self._reset_for_next_hand(state)
            return result

        # Evaluate hands for remaining players
        player_hands: dict[str, HandResult] = {}
        for p in active:
            cards = p.hole_cards + state.community_cards
            player_hands[p.id] = evaluate_hand(cards)

        # Snapshot hole cards before the reset clears them
        hole_cards_snapshot = {p.id: [c.to_dict() for c in p.hole_cards] for p in state.players}

        # Build side pots from total contributions
        pots = self.build_side_pots(state.players)
        if not pots:
            pots = state.pots

        chips_delta: dict[str, int] = {p.id: 0 for p in state.players}
        winners_detail = []

        for pot in pots:
            eligible_hands = {pid: player_hands[pid] for pid in pot.eligible_player_ids if pid in player_hands}
            if not eligible_hands:
                continue
            pot_winners = find_winners(eligible_hands)
            share = pot.amount // len(pot_winners)
            remainder = pot.amount % len(pot_winners)
            # Odd chips go to the winners closest to the left of the dealer.
            ordered_winners = self._order_left_of_dealer(state, pot_winners)
            for i, wid in enumerate(ordered_winners):
                award = share + (1 if i < remainder else 0)
                p = self.get_player(wid)
                if p:
                    p.chips += award
                chips_delta[wid] = chips_delta.get(wid, 0) + award
                winners_detail.append({"player_id": wid, "amount": award, "pot": pot.amount})

        state.stage = GameStage.HAND_OVER

        result = {
            "winners": winners_detail,
            "player_hands": {pid: hand.to_dict() for pid, hand in player_hands.items()},
            "chips_delta": chips_delta,
            "pots": [p.to_dict() for p in pots],
            "hole_cards_snapshot": hole_cards_snapshot,
        }
        self._reset_for_next_hand(state)
        return result

    def _reset_for_next_hand(self, state: GameState) -> None:
        for p in state.players:
            p.hole_cards = []
            p.is_folded = False
            p.is_all_in = False
            p.current_bet = 0
            p.total_invested = 0
        state.community_cards = []
        state.pots = []

    def get_valid_actions(self, player_id: str) -> dict:
        """Return valid actions and amounts for the current player."""
        state = self.state
        if state is None:
            return {}
        players = state.players
        if state.current_player_index >= len(players):
            return {}
        current = players[state.current_player_index]
        if current.id != player_id:
            return {}

        call_amount = self._call_amount(state, current)
        max_bet = self._current_max_bet(state)

        actions = ["fold"]
        if call_amount == 0:
            actions.append("check")
        else:
            actions.append("call")

        min_raise_total = max_bet + state.min_raise
        can_raise = self._raise_reopened(state, current)
        # Only offer "raise" if the player holds raising rights and can reach
        # a full min-raise; otherwise their only aggressive option is all_in.
        if can_raise and current.chips + current.current_bet >= min_raise_total:
            actions.append("raise")
        # all_in above the current bet is a raise; a player whose raising
        # rights are closed may only go all-in as a call for less.
        if can_raise or current.chips + current.current_bet <= max_bet:
            actions.append("all_in")

        return {
            "valid_actions": actions,
            "call_amount": min(call_amount, current.chips),
            "min_raise": min_raise_total,
            "max_raise": current.chips + current.current_bet,
            "current_chips": current.chips,
        }

    def public_state_dict(self, for_player_id: Optional[str] = None) -> dict:
        """Return serializable game state, including hole cards only for for_player_id."""
        state = self.state
        players_data = []
        for p in self.players:
            pd = p.to_dict(include_hole_cards=(p.id == for_player_id))
            players_data.append(pd)

        community = [c.to_dict() for c in state.community_cards] if state else []
        pots = [p.to_dict() for p in state.pots] if state else []
        pot_total = sum(p.amount for p in state.pots) if state else 0

        # current_player_id is derived from state.players (active subset);
        # current_player_index must be relative to self.players (full list sent to clients)
        current_player_id = (
            state.players[state.current_player_index].id
            if state and state.players and 0 <= state.current_player_index < len(state.players)
            else None
        )
        current_player_index = (
            next((i for i, p in enumerate(self.players) if p.id == current_player_id), -1)
            if current_player_id
            else -1
        )

        # Seat of the dealer button, so clients can render it after a refresh
        # or reconnect (hand_started is the only other place that carries it)
        dealer_seat = (
            state.players[state.dealer_index].seat_position
            if state and state.players and 0 <= state.dealer_index < len(state.players)
            else None
        )

        return {
            "room_code": self.room_code,
            "players": players_data,
            "admin_id": self.admin_id,
            "community_cards": community,
            "pots": pots,
            "pot_total": pot_total,
            "stage": state.stage.value if state else GameStage.WAITING.value,
            "current_player_index": current_player_index,
            "current_player_id": current_player_id,
            "dealer_index": state.dealer_index if state else 0,
            "dealer_seat": dealer_seat,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "hand_number": state.hand_number if state else 0,
            "settings": {
                "small_blind": self.small_blind,
                "big_blind": self.big_blind,
                "starting_chips": self.starting_chips,
                "turn_timer_seconds": self.turn_timer_seconds,
            },
        }
