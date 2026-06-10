from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

from .ws import room_registry

router = APIRouter()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


@router.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@router.get("/game")
async def game():
    return FileResponse(os.path.join(FRONTEND_DIR, "game.html"))


@router.get("/api/room/{room_code}/exists")
async def room_exists(room_code: str):
    exists = room_code.upper() in room_registry
    return {"exists": exists}


@router.get("/api/room/{room_code}/history")
async def room_history(room_code: str):
    from db.database import get_session
    from db.models import GameSession, HandRecord, PlayerHandRecord
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(GameSession).where(GameSession.room_code == room_code.upper())
        )
        game_session = result.scalar_one_or_none()
        if not game_session:
            raise HTTPException(status_code=404, detail="Room not found")

        hands_result = await session.execute(
            select(HandRecord).where(HandRecord.game_session_id == game_session.id)
        )
        hands = hands_result.scalars().all()

        hands_data = []
        for hand in hands:
            players_result = await session.execute(
                select(PlayerHandRecord).where(PlayerHandRecord.hand_record_id == hand.id)
            )
            players = players_result.scalars().all()
            hands_data.append({
                "hand_number": hand.hand_number,
                "community_cards": hand.community_cards,
                "pot_total": hand.pot_total,
                "players": [
                    {
                        "display_name": p.display_name,
                        "seat": p.seat,
                        "chips_start": p.chips_start,
                        "chips_end": p.chips_end,
                        "result": p.result,
                        "winnings": p.winnings,
                    }
                    for p in players
                ],
            })

        return {"room_code": room_code.upper(), "hands": hands_data}
