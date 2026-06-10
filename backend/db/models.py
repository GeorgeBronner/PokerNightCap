from datetime import UTC, datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    hands: Mapped[list["HandRecord"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class HandRecord(Base):
    __tablename__ = "hand_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id"))
    hand_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    community_cards: Mapped[list] = mapped_column(JSON, default=list)
    pot_total: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped["GameSession"] = relationship(back_populates="hands")
    player_records: Mapped[list["PlayerHandRecord"]] = relationship(back_populates="hand", cascade="all, delete-orphan")
    actions: Mapped[list["ActionRecord"]] = relationship(back_populates="hand", cascade="all, delete-orphan")


class PlayerHandRecord(Base):
    __tablename__ = "player_hand_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hand_record_id: Mapped[int] = mapped_column(ForeignKey("hand_records.id"))
    display_name: Mapped[str] = mapped_column(String(50))
    seat: Mapped[int] = mapped_column(Integer)
    hole_cards: Mapped[list] = mapped_column(JSON, default=list)
    chips_start: Mapped[int] = mapped_column(Integer)
    chips_end: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(10))  # won / lost / split
    winnings: Mapped[int] = mapped_column(Integer, default=0)

    hand: Mapped["HandRecord"] = relationship(back_populates="player_records")


class ActionRecord(Base):
    __tablename__ = "action_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hand_record_id: Mapped[int] = mapped_column(ForeignKey("hand_records.id"))
    player_display_name: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(20))
    action_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    hand: Mapped["HandRecord"] = relationship(back_populates="actions")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id"))
    hand_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sender_name: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped["GameSession"] = relationship(back_populates="chat_messages")
