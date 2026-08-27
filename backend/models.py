import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from database import Base


class Game(Base):
    __tablename__ = "games"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    date_played = Column(Date, nullable=False)
    location = Column(String(255))
    video_file_path = Column(String(512))
    video_duration_seconds = Column(Integer)
    frame_count = Column(Integer)

    processing_status = Column(String(50), default="pending")
    processing_started_at = Column(DateTime)
    processing_completed_at = Column(DateTime)
    processing_error = Column(Text)

    home_team = Column(String(100))
    away_team = Column(String(100))

    # Manually marked by the coach in the frame viewer - stock YOLOv8 (COCO
    # weights) has no hoop class, so hoop position can't be auto-detected.
    hoop_x = Column(Integer)
    hoop_y = Column(Integer)

    total_shots = Column(Integer, default=0)
    made_shots = Column(Integer, default=0)
    total_rebounds = Column(Integer, default=0)
    total_turnovers = Column(Integer, default=0)
    total_assists = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Frame(Base):
    __tablename__ = "frames"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id = Column(UUID(as_uuid=True), ForeignKey("games.id"), nullable=False)
    frame_number = Column(Integer, nullable=False)
    timestamp_seconds = Column(Numeric(10, 2))
    local_file_path = Column(String(512))
    width = Column(Integer)
    height = Column(Integer)
    processed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


class DetectedObject(Base):
    __tablename__ = "detected_objects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    frame_id = Column(UUID(as_uuid=True), ForeignKey("frames.id"), nullable=False)
    object_type = Column(String(50))
    confidence_score = Column(Numeric(5, 3))
    bbox_x = Column(Integer)
    bbox_y = Column(Integer)
    bbox_width = Column(Integer)
    bbox_height = Column(Integer)
    estimated_jersey_number = Column(Integer)
    jersey_confidence = Column(Numeric(5, 3))
    created_at = Column(DateTime, server_default=func.now())


class GameEvent(Base):
    __tablename__ = "game_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id = Column(UUID(as_uuid=True), ForeignKey("games.id"), nullable=False)
    event_type = Column(String(50))
    start_frame = Column(Integer)
    end_frame = Column(Integer)
    start_timestamp = Column(Numeric(10, 2))
    end_timestamp = Column(Numeric(10, 2))
    event_details = Column(JSONB)
    confidence_score = Column(Numeric(5, 3))
    created_at = Column(DateTime, server_default=func.now())
