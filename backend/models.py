import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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

    # "video" (default) processes an uploaded recording through the vision
    # pipeline; "manual" is a live-entry game with no video at all - a coach
    # taps stats in during play (see /api/games/manual and manual_events.py).
    entry_mode = Column(String(20), default="video")

    # Manually marked by the coach in the frame viewer - stock YOLOv8 (COCO
    # weights) has no hoop class, so hoop position can't be auto-detected.
    hoop_x = Column(Integer)
    hoop_y = Column(Integer)

    total_shots = Column(Integer, default=0)
    made_shots = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
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


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("game_id", "team", "jersey_number", name="uq_player_game_team_jersey"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id = Column(UUID(as_uuid=True), ForeignKey("games.id"))
    jersey_number = Column(Integer, nullable=False)
    player_name = Column(String(255))
    team = Column(String(100))
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
    # ByteTrack ID from vision_service.detect_objects, unique within a game
    # (the tracker is reset before each game's frame loop - see
    # vision_service.reset_tracker) but not across games. Null if the
    # tracker couldn't associate this detection with any track. Lets a coach
    # tag a player once per track instead of once per frame - see
    # assign_player_to_track below.
    track_id = Column(Integer)
    estimated_jersey_number = Column(Integer)
    jersey_confidence = Column(Numeric(5, 3))
    # Manually assigned by a coach correcting the (unreliable) OCR guess -
    # see jersey_ocr.py. Never set automatically.
    player_id = Column(UUID(as_uuid=True), ForeignKey("players.id"))
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
    # Set directly for manual entries (the coach picks the player). Video-
    # derived shot/rebound events instead carry shooter_player_id /
    # rebounder_player_id inside event_details, since attribution there is a
    # guess resolved at analyze time, not a direct assignment.
    player_id = Column(UUID(as_uuid=True), ForeignKey("players.id"))
    created_at = Column(DateTime, server_default=func.now())
