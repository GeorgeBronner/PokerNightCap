import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from game.room import Room, generate_room_code
from schemas import messages as msg


def _first_error(e: ValidationError) -> str:
    """Render the first validation error as a short human-readable string."""
    err = e.errors()[0]
    loc = ".".join(str(part) for part in err["loc"])
    return f"{loc}: {err['msg']}" if loc else err["msg"]

router = APIRouter()

# In-memory singleton registry: room_code -> Room
room_registry: dict[str, Room] = {}

# connection map: player_id -> WebSocket
_connections: dict[str, WebSocket] = {}

# Pending auto-fold timers: player_id -> asyncio.Task
_timer_tasks: dict[str, asyncio.Task] = {}

# Reconnect grace tasks: player_id -> asyncio.Task
_reconnect_tasks: dict[str, asyncio.Task] = {}

RECONNECT_GRACE_SECONDS = 60


class ConnectionManager:
    def connect(self, websocket: WebSocket, player_id: str) -> None:
        _connections[player_id] = websocket

    def disconnect(self, player_id: str) -> None:
        _connections.pop(player_id, None)

    async def send(self, player_id: str, data: dict) -> None:
        ws = _connections.get(player_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass

    async def broadcast(self, room_code: str, data: dict, exclude_player_id: Optional[str] = None) -> None:
        room = room_registry.get(room_code)
        if not room:
            return
        for player in room.players:
            if player.id == exclude_player_id:
                continue
            if player.is_connected:
                await self.send(player.id, data)


manager = ConnectionManager()


async def broadcast_system_message(room_code: str, room: Room, text: str) -> None:
    """Send a system line to every player's Hand Log and persist it to the DB
    so admin actions (chip adjustments, setting changes) leave a record."""
    timestamp = datetime.now(UTC).isoformat()
    await manager.broadcast(
        room_code,
        msg.chat_message_out("System", text, is_system=True, timestamp=timestamp),
    )
    asyncio.create_task(persist_chat(room_code, room, "System", text, is_system=True))


# -------------------------
# WebSocket endpoint
# -------------------------

@router.websocket("/ws/{room_code}")
async def websocket_endpoint(websocket: WebSocket, room_code: str):
    await websocket.accept()
    player_id: Optional[str] = None
    current_room_code: Optional[str] = None

    try:
        # First message must be join_room or create_room
        raw = await websocket.receive_text()
        data = json.loads(raw)
        msg_type = data.get("type")

        if msg_type == "create_room":
            player_id, current_room_code = await handle_create_room(websocket, data)
        elif msg_type == "join_room":
            player_id, current_room_code = await handle_join_room(websocket, data, room_code)
        else:
            await websocket.send_json(msg.error("invalid_message", "First message must be create_room or join_room"))
            await websocket.close()
            return

        if player_id is None:
            return

        manager.connect(websocket, player_id)

        # Main message loop — a malformed message gets an error reply instead
        # of tearing down the connection mid-hand.
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Message must be a JSON object")
                await dispatch(websocket, player_id, current_room_code, data)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                await websocket.send_json(msg.error("invalid_message", str(e)))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json(msg.error("internal_error", str(e)))
        except Exception:
            pass
    finally:
        if player_id and current_room_code:
            await on_disconnect(player_id, current_room_code, websocket)


async def handle_create_room(websocket: WebSocket, data: dict):
    try:
        parsed = msg.CreateRoomMsg.model_validate(data)
    except ValidationError as e:
        await websocket.send_json(msg.error("invalid_message", _first_error(e)))
        return None, None

    display_name = parsed.display_name.strip()
    if not display_name:
        await websocket.send_json(msg.error("invalid_name", "Display name required"))
        return None, None

    settings = parsed.settings.model_dump()
    room_code = generate_room_code(set(room_registry.keys()))
    room = Room(room_code, settings)
    room_registry[room_code] = room

    # Create DB game session
    try:
        from db.database import get_session
        from db.models import GameSession
        async with get_session() as session:
            gs = GameSession(room_code=room_code, settings=settings)
            session.add(gs)
    except Exception:
        pass

    player = room.add_player(display_name)
    state = room.public_state_dict(for_player_id=player.id)
    await websocket.send_json(
        msg.room_joined(
            player_id=player.id,
            reconnect_token=player.reconnect_token,
            room_state=state,
        )
    )
    return player.id, room_code


async def handle_join_room(websocket: WebSocket, data: dict, url_room_code: str):
    try:
        parsed = msg.JoinRoomMsg.model_validate(
            {**data, "room_code": data.get("room_code") or url_room_code}
        )
    except ValidationError as e:
        await websocket.send_json(msg.error("invalid_message", _first_error(e)))
        return None, None

    room_code = parsed.room_code.upper()
    display_name = parsed.display_name.strip()
    reconnect_token = parsed.reconnect_token

    room = room_registry.get(room_code)
    if not room:
        await websocket.send_json(msg.error("room_not_found", f"Room {room_code} not found"))
        return None, None

    # Reconnect path
    if reconnect_token:
        admin_before = room.admin_id
        player = room.reconnect_player(reconnect_token)
        if player:
            if room.admin_id != admin_before:
                await manager.broadcast(room_code, msg.admin_changed(room.admin_id))
            # Cancel pending removal task
            task = _reconnect_tasks.pop(player.id, None)
            if task:
                task.cancel()
            state = room.public_state_dict(for_player_id=player.id)
            await websocket.send_json(
                msg.room_joined(
                    player_id=player.id,
                    reconnect_token=player.reconnect_token,
                    room_state=state,
                )
            )
            await manager.broadcast(room_code, msg.player_joined(player.to_dict()), exclude_player_id=player.id)
            # If it was their turn, send action_required again
            await maybe_send_action_required(room, player.id)
            return player.id, room_code

    # New join
    if not display_name:
        await websocket.send_json(msg.error("invalid_name", "Display name required"))
        return None, None

    try:
        player = room.add_player(display_name)
    except ValueError as e:
        await websocket.send_json(msg.error("join_failed", str(e)))
        return None, None

    state = room.public_state_dict(for_player_id=player.id)
    await websocket.send_json(
        msg.room_joined(
            player_id=player.id,
            reconnect_token=player.reconnect_token,
            room_state=state,
        )
    )
    await manager.broadcast(room_code, msg.player_joined(player.to_dict()), exclude_player_id=player.id)
    return player.id, room_code


async def on_disconnect(player_id: str, room_code: str, websocket: Optional[WebSocket] = None) -> None:
    # Ignore stale closes: if the player already reconnected on a newer
    # socket, this event is for the old one and must not mark them offline
    # (or clobber the new connection in the registry).
    if websocket is not None and _connections.get(player_id) is not websocket:
        return
    manager.disconnect(player_id)
    room = room_registry.get(room_code)
    if not room:
        return

    room.mark_disconnected(player_id)
    old_admin = room.admin_id

    # Re-elect admin immediately when the admin goes offline; mark_disconnected
    # does not change admin_id itself so we must do it here.
    if old_admin == player_id:
        new_admin = room._elect_admin()
        room.admin_id = new_admin.id if new_admin else None

    await manager.broadcast(room_code, msg.player_left(player_id, room.admin_id))

    if room.admin_id != old_admin:
        await manager.broadcast(room_code, msg.admin_changed(room.admin_id))

    # Grace period — remove if not reconnected within 60s
    async def remove_after_grace():
        await asyncio.sleep(RECONNECT_GRACE_SECONDS)
        p = room.get_player(player_id)
        if p and not p.is_connected:
            room.remove_player(player_id)
            await manager.broadcast(room_code, msg.player_left(player_id, room.admin_id))
            if not room.players:
                room_registry.pop(room_code, None)

    task = asyncio.create_task(remove_after_grace())
    _reconnect_tasks[player_id] = task

    # If it was this player's turn, auto-fold after grace
    state = room.state
    if (
        state
        and state.players
        and 0 <= state.current_player_index < len(state.players)
        and state.players[state.current_player_index].id == player_id
    ):
        await auto_fold_disconnected(room, player_id, room_code)


async def auto_fold_disconnected(room: Room, player_id: str, room_code: str) -> None:
    """Auto-fold a disconnected player's turn."""
    try:
        pre_stage = room.state.stage.value if room.state else None
        result = room.apply_action(player_id, "fold")
        await manager.broadcast(room_code, msg.player_acted(player_id, "fold", 0, result["pot_total"]))
        await after_action(room, room_code, pre_stage)
    except Exception:
        pass


# -------------------------
# Message dispatch
# -------------------------

async def dispatch(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    msg_type = data.get("type")
    handlers = {
        "player_action": handle_player_action,
        "chat_message": handle_chat,
        "admin_start_game": handle_admin_start_game,
        "deal_next_hand": handle_deal_next_hand,
        "admin_add_chips": handle_admin_add_chips,
        "admin_transfer": handle_admin_transfer,
        "admin_kick_player": handle_admin_kick_player,
        "admin_update_settings": handle_admin_update_settings,
        "ping": handle_ping,
    }
    handler = handlers.get(msg_type)
    if handler:
        await handler(websocket, player_id, room_code, data)
    else:
        await websocket.send_json(msg.error("unknown_type", f"Unknown message type: {msg_type}"))


# -------------------------
# Handlers
# -------------------------

async def handle_player_action(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return

    try:
        parsed = msg.PlayerActionMsg.model_validate(data)
    except ValidationError as e:
        await websocket.send_json(msg.error("invalid_action", _first_error(e)))
        return

    action = parsed.action
    amount = parsed.amount

    pre_stage = room.state.stage.value if room.state else None

    try:
        result = room.apply_action(player_id, action, amount)
    except (ValueError, PermissionError) as e:
        await websocket.send_json(msg.error("invalid_action", str(e)))
        return

    # Cancel the pending auto-act timer only once the action succeeded —
    # a rejected action must not disarm the timeout (stall prevention).
    task = _timer_tasks.pop(player_id, None)
    if task:
        task.cancel()

    await manager.broadcast(room_code, msg.player_acted(player_id, action, result["amount"], result["pot_total"]))

    # Persist action to DB
    asyncio.create_task(persist_action(room_code, player_id, room, action, amount))

    await after_action(room, room_code, pre_stage)


async def after_action(room: Room, room_code: str, pre_stage: Optional[str] = None) -> None:
    """Handle post-action: check for showdown, next turn, or stage change."""
    from game.state import GameStage

    state = room.state
    if not state:
        return

    if state.stage == GameStage.SHOWDOWN:
        result = room.resolve_showdown()
        await manager.broadcast(
            room_code,
            msg.hand_result(result["winners"], result["pots"], result["player_hands"], result["chips_delta"]),
        )
        asyncio.create_task(persist_hand_result(room_code, room, result))
        return

    if state.stage == GameStage.HAND_OVER:
        return

    # Only broadcast stage_changed when the stage actually advanced
    if pre_stage is not None and state.stage.value != pre_stage:
        await manager.broadcast(
            room_code,
            msg.stage_changed(state.stage.value, [c.to_dict() for c in state.community_cards]),
        )

    # Send action_required to current player
    await send_action_required(room, room_code)


async def send_action_required(room: Room, room_code: str) -> None:
    from game.state import GameStage

    state = room.state
    if not state or state.stage in (GameStage.WAITING, GameStage.HAND_OVER, GameStage.SHOWDOWN):
        return

    if not state.players or state.current_player_index >= len(state.players):
        return

    current = state.players[state.current_player_index]
    if current.is_folded or current.is_all_in:
        return

    valid = room.get_valid_actions(current.id)
    deadline = time.time() + state.turn_timer_seconds

    await manager.send(
        current.id,
        msg.action_required(
            player_id=current.id,
            valid_actions=valid.get("valid_actions", []),
            min_raise=valid.get("min_raise", 0),
            call_amount=valid.get("call_amount", 0),
            time_limit_seconds=state.turn_timer_seconds,
            deadline=deadline,
            max_raise=valid.get("max_raise", 0),
        ),
    )

    # Also broadcast to all (so other players know whose turn it is)
    await manager.broadcast(
        room_code,
        {
            "type": "turn_changed",
            "payload": {
                "player_id": current.id,
                "deadline": deadline,
            },
        },
        exclude_player_id=current.id,
    )

    # Schedule auto-fold timer
    task = _timer_tasks.pop(current.id, None)
    if task:
        task.cancel()

    async def auto_act_on_timeout():
        await asyncio.sleep(state.turn_timer_seconds + 2)  # +2s buffer
        p = room.get_player(current.id)
        cur_state = room.state
        is_still_their_turn = (
            cur_state is not None
            and cur_state.players
            and 0 <= cur_state.current_player_index < len(cur_state.players)
            and cur_state.players[cur_state.current_player_index].id == current.id
        )
        if (
            p and not p.is_folded and
            cur_state and
            cur_state.stage not in (GameStage.WAITING, GameStage.HAND_OVER) and
            is_still_their_turn
        ):
            try:
                pre_stage = cur_state.stage.value
                # Check when free to do so; only fold if facing a bet
                valid_now = room.get_valid_actions(current.id).get("valid_actions", [])
                action = "check" if "check" in valid_now else "fold"
                result = room.apply_action(current.id, action)
                await manager.broadcast(room_code, msg.player_acted(current.id, action, 0, result["pot_total"]))
                await after_action(room, room_code, pre_stage)
            except Exception:
                pass

    _timer_tasks[current.id] = asyncio.create_task(auto_act_on_timeout())


async def maybe_send_action_required(room: Room, player_id: str) -> None:
    state = room.state
    if not state:
        return
    if state.players and state.players[state.current_player_index].id == player_id:
        room_code = room.room_code
        await send_action_required(room, room_code)


async def _start_hand(room: Room, room_code: str, websocket: WebSocket) -> None:
    """Deal a new hand and notify all players. Shared by admin start and the
    everyone-can-click "deal next hand" flow."""
    try:
        state = room.start_hand()
    except ValueError as e:
        await websocket.send_json(msg.error("start_failed", str(e)))
        return

    players = state.players
    n = len(players)
    dealer_seat = players[state.dealer_index].seat_position
    sb_idx = (state.dealer_index + 1) % n if n > 2 else state.dealer_index
    bb_idx = (state.dealer_index + 2) % n if n > 2 else (state.dealer_index + 1) % n

    await manager.broadcast(
        room_code,
        msg.hand_started(
            state.hand_number,
            dealer_seat,
            players[sb_idx].seat_position,
            players[bb_idx].seat_position,
            player_ids=[p.id for p in players],
        ),
    )

    # Send private hole cards to each player
    for p in players:
        await manager.send(p.id, msg.hole_cards_dealt([c.to_dict() for c in p.hole_cards]))

    # Send action_required to first player
    await send_action_required(room, room_code)


async def handle_admin_start_game(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    if room.admin_id != player_id:
        await websocket.send_json(msg.error("not_admin", "Only admin can start the game"))
        return
    await _start_hand(room, room_code, websocket)


async def handle_deal_next_hand(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    """Any player may deal the next hand once the previous one is over."""
    from game.state import GameStage

    room = room_registry.get(room_code)
    if not room:
        return
    # Ignore if a hand is already in progress (guards against double-clicks /
    # two players clicking at once — start_hand runs before the next await).
    if room.state and room.state.stage not in (GameStage.WAITING, GameStage.HAND_OVER):
        return
    await _start_hand(room, room_code, websocket)


async def handle_chat(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    player = room.get_player(player_id)
    if not player:
        return

    try:
        parsed = msg.ChatMessageInMsg.model_validate(data)
    except ValidationError:
        return

    message = parsed.message.strip()[:200]
    if not message:
        return

    timestamp = datetime.now(UTC).isoformat()
    await manager.broadcast(
        room_code,
        msg.chat_message_out(player.display_name, message, is_system=False, timestamp=timestamp),
    )

    asyncio.create_task(persist_chat(room_code, room, player.display_name, message, is_system=False))


async def handle_admin_add_chips(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    try:
        parsed = msg.AdminAddChipsMsg.model_validate(data)
    except ValidationError as e:
        await websocket.send_json(msg.error("chips_failed", _first_error(e)))
        return
    try:
        target = room.add_chips(player_id, parsed.target_player_id, parsed.amount)
        await manager.broadcast(room_code, msg.chips_updated(target.id, target.chips, "admin_add"))
        admin = room.get_player(player_id)
        admin_name = admin.display_name if admin else "Admin"
        verb = "added" if parsed.amount >= 0 else "removed"
        prep = "to" if parsed.amount >= 0 else "from"
        await broadcast_system_message(
            room_code, room,
            f"{admin_name} {verb} ${abs(parsed.amount):,} {prep} {target.display_name} — stack now ${target.chips:,}.",
        )
    except (ValueError, PermissionError) as e:
        await websocket.send_json(msg.error("chips_failed", str(e)))


async def handle_admin_transfer(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    try:
        parsed = msg.AdminTransferMsg.model_validate(data)
    except ValidationError as e:
        await websocket.send_json(msg.error("transfer_failed", _first_error(e)))
        return
    try:
        room.transfer_admin(player_id, parsed.target_player_id)
        await manager.broadcast(room_code, msg.admin_changed(room.admin_id))
    except (ValueError, PermissionError) as e:
        await websocket.send_json(msg.error("transfer_failed", str(e)))


async def handle_admin_kick_player(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    try:
        parsed = msg.AdminKickPlayerMsg.model_validate(data)
    except ValidationError as e:
        await websocket.send_json(msg.error("kick_failed", _first_error(e)))
        return
    try:
        target = room.kick_player(player_id, parsed.target_player_id)
        # Send directly to the kicked player first — kick_player removes them from
        # room.players so broadcast() won't reach them, but the WS is still open.
        await manager.send(target.id, msg.player_kicked(target.id))
        await manager.broadcast(room_code, msg.player_kicked(target.id))
        manager.disconnect(target.id)
        admin = room.get_player(player_id)
        admin_name = admin.display_name if admin else "Admin"
        await broadcast_system_message(
            room_code, room,
            f"{target.display_name} was kicked from the table by {admin_name} (had ${target.chips:,}).",
        )
    except (ValueError, PermissionError) as e:
        await websocket.send_json(msg.error("kick_failed", str(e)))


async def handle_admin_update_settings(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    room = room_registry.get(room_code)
    if not room:
        return
    incoming = data.get("settings") or {}
    if not isinstance(incoming, dict):
        await websocket.send_json(msg.error("settings_failed", "settings must be an object"))
        return
    # Merge onto current room settings so partial updates validate as a whole
    # (e.g. raising small_blind above the existing big_blind is rejected).
    merged = {
        "small_blind": room.small_blind,
        "big_blind": room.big_blind,
        "starting_chips": room.starting_chips,
        "turn_timer_seconds": room.turn_timer_seconds,
        **incoming,
    }
    try:
        settings = msg.GameSettings.model_validate(merged)
    except ValidationError as e:
        await websocket.send_json(msg.error("settings_failed", _first_error(e)))
        return
    try:
        result = room.update_settings(player_id, settings.model_dump())
    except (ValueError, PermissionError) as e:
        await websocket.send_json(msg.error("settings_failed", str(e)))
        return

    await manager.broadcast(room_code, {"type": "settings_updated", "payload": settings.model_dump()})

    changes = result["changes"]
    if not changes:
        return
    admin = room.get_player(player_id)
    admin_name = admin.display_name if admin else "Admin"
    if {"small_blind", "big_blind"} & changes.keys():
        await broadcast_system_message(
            room_code, room,
            f"{admin_name} set blinds to ${room.small_blind}/${room.big_blind} (takes effect next hand).",
        )
    if "starting_chips" in changes:
        if result["stacks_reset"]:
            await broadcast_system_message(
                room_code, room,
                f"{admin_name} set starting chips to ${room.starting_chips:,} — all stacks updated.",
            )
            # Stacks changed: push a full state refresh so every client shows
            # the new chip counts.
            await manager.broadcast(room_code, msg.room_state(room.public_state_dict()))
        else:
            await broadcast_system_message(
                room_code, room,
                f"{admin_name} set starting chips to ${room.starting_chips:,} for players joining from now on.",
            )
    if "turn_timer_seconds" in changes:
        await broadcast_system_message(
            room_code, room,
            f"{admin_name} set the turn timer to {room.turn_timer_seconds}s (takes effect next hand).",
        )


async def handle_ping(websocket: WebSocket, player_id: str, room_code: str, data: dict) -> None:
    await websocket.send_json(msg.pong())


# -------------------------
# DB persistence helpers (fire-and-forget)
# -------------------------

async def persist_action(room_code: str, player_id: str, room: Room, action: str, amount: int) -> None:
    try:
        from db.database import get_session
        from db.models import GameSession, HandRecord, ActionRecord
        from sqlalchemy import select

        player = room.get_player(player_id)
        state = room.state
        if not player or not state:
            return

        async with get_session() as session:
            gs_result = await session.execute(select(GameSession).where(GameSession.room_code == room_code))
            gs = gs_result.scalar_one_or_none()
            if not gs:
                return
            hand_result = await session.execute(
                select(HandRecord).where(
                    HandRecord.game_session_id == gs.id,
                    HandRecord.hand_number == state.hand_number,
                )
            )
            hand = hand_result.scalar_one_or_none()
            if not hand:
                hand = HandRecord(
                    game_session_id=gs.id,
                    hand_number=state.hand_number,
                    community_cards=[],
                    pot_total=0,
                )
                session.add(hand)
                await session.flush()

            session.add(ActionRecord(
                hand_record_id=hand.id,
                player_display_name=player.display_name,
                stage=state.stage.value,
                action_type=action,
                amount=amount,
            ))
    except Exception:
        pass


async def persist_hand_result(room_code: str, room: Room, result: dict) -> None:
    try:
        from db.database import get_session
        from db.models import GameSession, HandRecord, PlayerHandRecord
        from sqlalchemy import select

        state = room.state
        if not state:
            return

        async with get_session() as session:
            gs_result = await session.execute(select(GameSession).where(GameSession.room_code == room_code))
            gs = gs_result.scalar_one_or_none()
            if not gs:
                return

            pot_total = sum(p["amount"] for p in result.get("winners", []))
            hand = HandRecord(
                game_session_id=gs.id,
                hand_number=state.hand_number,
                community_cards=[c.to_dict() for c in state.community_cards],
                pot_total=pot_total,
                ended_at=datetime.now(UTC),
            )
            session.add(hand)
            await session.flush()

            chips_delta = result.get("chips_delta", {})
            # hole_cards_snapshot is captured before _reset_for_next_hand clears them
            hole_cards_snapshot = result.get("hole_cards_snapshot", {})
            for p in room.players:
                winnings = chips_delta.get(p.id, 0)
                result_str = "won" if winnings > 0 else "lost"
                session.add(PlayerHandRecord(
                    hand_record_id=hand.id,
                    display_name=p.display_name,
                    seat=p.seat_position,
                    hole_cards=hole_cards_snapshot.get(p.id, []),
                    chips_start=p.chips - winnings,
                    chips_end=p.chips,
                    result=result_str,
                    winnings=winnings,
                ))
    except Exception:
        pass


async def persist_chat(room_code: str, room: Room, sender_name: str, message: str, is_system: bool) -> None:
    try:
        from db.database import get_session
        from db.models import GameSession, ChatMessage
        from sqlalchemy import select

        async with get_session() as session:
            gs_result = await session.execute(select(GameSession).where(GameSession.room_code == room_code))
            gs = gs_result.scalar_one_or_none()
            if gs:
                hand_num = room.state.hand_number if room.state else None
                session.add(ChatMessage(
                    game_session_id=gs.id,
                    hand_number=hand_num,
                    sender_name=sender_name,
                    message=message,
                    is_system=is_system,
                ))
    except Exception:
        pass
