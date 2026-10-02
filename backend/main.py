import logging
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import DetectedObject, Frame, Game, GameEvent, Player
from services.player_migration import migrate_players
from services.frame_extraction import extract_frames
from services.jersey_ocr import read_jersey_number
from services.player_attribution import closest_person_to_ball, find_shooter_reference_point, proximity_radius
from services.rebound_detection import detect_rebounds
from services.shot_detection import detect_shots
from services.vision_service import detect_objects, detect_pose, get_model, get_pose_model, reset_tracker
from services.court_detection import detect_court_lines, compute_homography, pixel_to_court_coords, is_three_point_shot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Basketball Analytics - Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEOS_PATH = Path(os.getenv("VIDEOS_PATH", "./videos"))
VIDEOS_PATH.mkdir(exist_ok=True)
FRAMES_PATH = Path(os.getenv("DATA_PATH", "./data")) / "frames"
FRAMES_PATH.mkdir(parents=True, exist_ok=True)

# Tables are created by docker/init.sql on first Postgres startup; this is a
# no-op once they exist, and lets `models.py` stay the source of truth for
# columns the ORM actually uses.
Base.metadata.create_all(bind=engine)

# `games` predates the hoop_x/hoop_y columns (added for Week 3 shot
# detection) and was already created by docker/init.sql, so create_all()
# above won't add them - do it explicitly instead of pulling in Alembic for
# a single-developer local project.
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE games ADD COLUMN IF NOT EXISTS hoop_x INT"))
    conn.execute(text("ALTER TABLE games ADD COLUMN IF NOT EXISTS hoop_y INT"))
    conn.execute(text("ALTER TABLE detected_objects ADD COLUMN IF NOT EXISTS estimated_jersey_number INT"))
    conn.execute(text("ALTER TABLE detected_objects ADD COLUMN IF NOT EXISTS jersey_confidence NUMERIC(5,3)"))
    conn.execute(text("ALTER TABLE detected_objects ADD COLUMN IF NOT EXISTS player_id UUID REFERENCES players(id)"))
    conn.execute(text("ALTER TABLE detected_objects ADD COLUMN IF NOT EXISTS track_id INT"))
    conn.execute(text("ALTER TABLE games ADD COLUMN IF NOT EXISTS entry_mode VARCHAR(20) DEFAULT 'video'"))
    conn.execute(text("ALTER TABLE game_events ADD COLUMN IF NOT EXISTS player_id UUID REFERENCES players(id)"))
    conn.execute(text("ALTER TABLE games ADD COLUMN IF NOT EXISTS total_points INT DEFAULT 0"))
    conn.execute(text("""
        UPDATE games
        SET total_points = COALESCE((
            SELECT SUM(CASE
                WHEN event_type = 'shot' AND event_details->>'made' = 'true'
                THEN COALESCE((event_details->>'points')::int, 2)
                ELSE 0
            END)
            FROM game_events
            WHERE game_events.game_id = games.id
        ), 0)
    """))
    migrate_players(conn)


class HoopPosition(BaseModel):
    x: int
    y: int


class PlayerAssignment(BaseModel):
    team: Literal["home", "away"] = "home"
    jersey_number: int = Field(ge=0, le=99)
    player_name: str | None = None


class ManualGameInput(BaseModel):
    title: str
    date_played: str
    home_team: str | None = None
    away_team: str | None = None


class PlayerInput(BaseModel):
    game_id: uuid.UUID
    team: Literal["home", "away"] = "home"
    jersey_number: int = Field(ge=0, le=99)
    player_name: str | None = None


class ManualEventInput(BaseModel):
    player_id: uuid.UUID
    event_type: str  # "shot" | "rebound" | "turnover" | "assist"
    made: bool | None = None  # only meaningful for event_type == "shot"
    points: Literal[1, 2, 3] | None = None  # only meaningful for a made shot


def serialize_player(player):
    return {"id": str(player.id), "jersey_number": player.jersey_number,
            "player_name": player.player_name, "team": player.team}


def get_or_create_player(db: Session, game_id, team, jersey_number, player_name=None) -> Player:
    player = db.query(Player).filter(
        Player.game_id == game_id, Player.team == team, Player.jersey_number == jersey_number
    ).first()
    if not player:
        player = Player(game_id=game_id, team=team, jersey_number=jersey_number, player_name=player_name)
        db.add(player)
        db.commit()
        db.refresh(player)
    elif player_name and player.player_name != player_name:
        player.player_name = player_name
        db.commit()
    return player


@app.on_event("startup")
def warm_up_vision_model():
    logger.info("Warming up YOLOv8 model...")
    get_model()


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": "local"}


@app.post("/api/games")
async def create_game(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    date_played: str = Form(...),
    video: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a game video, persist the game row, and queue frame extraction."""
    try:
        parsed_date = date.fromisoformat(date_played)
    except ValueError:
        raise HTTPException(status_code=422, detail="date_played must be YYYY-MM-DD")

    game = Game(
        title=title,
        date_played=parsed_date,
        processing_status="pending",
    )
    db.add(game)
    db.commit()
    db.refresh(game)

    # Filename includes the game id so two uploads sharing a title/date never
    # collide on the same path on disk.
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).replace(" ", "_")
    video_filename = f"{safe_title}_{date_played}_{game.id}{Path(video.filename or '').suffix or '.mp4'}"
    video_path = VIDEOS_PATH / video_filename

    with open(video_path, "wb") as buffer:
        buffer.write(await video.read())

    logger.info(f"Video saved: {video_path}")

    game.video_file_path = str(video_path)
    db.commit()

    background_tasks.add_task(process_video_task, str(game.id), str(video_path))

    return {
        "id": str(game.id),
        "status": game.processing_status,
        "title": game.title,
        "message": "Video uploaded. Processing started...",
    }


@app.post("/api/games/manual")
async def create_manual_game(payload: ManualGameInput, db: Session = Depends(get_db)):
    """Start a live-entry game: no video, no vision pipeline - a coach taps
    stats in during play instead. Ready to record events immediately."""
    try:
        parsed_date = date.fromisoformat(payload.date_played)
    except ValueError:
        raise HTTPException(status_code=422, detail="date_played must be YYYY-MM-DD")

    game = Game(
        title=payload.title,
        date_played=parsed_date,
        home_team=payload.home_team,
        away_team=payload.away_team,
        entry_mode="manual",
        processing_status="completed",
        frame_count=0,
        total_shots=0,
        made_shots=0,
        total_points=0,
        total_rebounds=0,
        total_turnovers=0,
        total_assists=0,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return serialize_game(game)


@app.post("/api/players")
async def create_or_find_player(payload: PlayerInput, db: Session = Depends(get_db)):
    """Find-or-create a player by jersey number, for the manual-entry roster
    (video games instead tag players against a specific detection - see
    assign_player)."""
    if not db.query(Game).filter(Game.id == payload.game_id).first():
        raise HTTPException(status_code=404, detail="Game not found")
    player = get_or_create_player(db, payload.game_id, payload.team, payload.jersey_number, payload.player_name)
    return serialize_player(player)


@app.get("/api/games/{game_id}/players")
async def list_game_players(game_id: uuid.UUID, db: Session = Depends(get_db)):
    return {"players": [serialize_player(p) for p in db.query(Player).filter(
        Player.game_id == game_id
    ).order_by(Player.team, Player.jersey_number).all()]}


@app.post("/api/games/{game_id}/manual-events")
async def record_manual_event(game_id: uuid.UUID, event: ManualEventInput, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.entry_mode != "manual":
        raise HTTPException(status_code=400, detail="This game isn't a manual-entry game")
    if event.event_type not in ("shot", "rebound", "turnover", "assist"):
        raise HTTPException(status_code=422, detail="event_type must be shot, rebound, turnover, or assist")
    player = db.query(Player).filter(Player.id == event.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    if player.game_id != game_id:
        raise HTTPException(status_code=400, detail="Player is not on this game roster")

    if event.points is not None and (event.event_type != "shot" or not event.made):
        raise HTTPException(status_code=422, detail="points can only be set for a made shot")

    points = event.points or 2 if event.event_type == "shot" and event.made else 0
    details = {"made": bool(event.made), "points": points} if event.event_type == "shot" else {}
    game_event = GameEvent(
        game_id=game_id,
        event_type=event.event_type,
        player_id=event.player_id,
        confidence_score=1.0,
        event_details=details,
    )
    db.add(game_event)

    if event.event_type == "shot":
        game.total_shots = (game.total_shots or 0) + 1
        if event.made:
            game.made_shots = (game.made_shots or 0) + 1
            game.total_points = (game.total_points or 0) + points
    elif event.event_type == "rebound":
        game.total_rebounds = (game.total_rebounds or 0) + 1
    elif event.event_type == "turnover":
        game.total_turnovers = (game.total_turnovers or 0) + 1
    elif event.event_type == "assist":
        game.total_assists = (game.total_assists or 0) + 1

    db.commit()
    db.refresh(game_event)

    return {
        "id": str(game_event.id),
        "event_type": game_event.event_type,
        "player_id": str(game_event.player_id),
        "jersey_number": player.jersey_number,
        "player_name": player.player_name,
        "event_details": game_event.event_details,
        "created_at": game_event.created_at.isoformat() if game_event.created_at else None,
    }


@app.get("/api/games/{game_id}/manual-events")
async def list_manual_events(game_id: uuid.UUID, db: Session = Depends(get_db)):
    events = (
        db.query(GameEvent)
        .filter(GameEvent.game_id == game_id, GameEvent.player_id.isnot(None))
        .order_by(GameEvent.created_at.desc())
        .all()
    )
    player_ids = {e.player_id for e in events}
    players = {p.id: p for p in db.query(Player).filter(Player.id.in_(player_ids)).all()} if player_ids else {}
    return {
        "events": [
            {
                "id": str(e.id),
                "player_id": str(e.player_id),
                "team": players[e.player_id].team if e.player_id in players else None,
                "event_type": e.event_type,
                "made": (e.event_details or {}).get("made"),
                "points": (e.event_details or {}).get("points"),
                "jersey_number": players[e.player_id].jersey_number if e.player_id in players else None,
                "player_name": players[e.player_id].player_name if e.player_id in players else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }


@app.delete("/api/games/{game_id}/manual-events/{event_id}")
async def delete_manual_event(game_id: uuid.UUID, event_id: uuid.UUID, db: Session = Depends(get_db)):
    """Undo a mis-tapped stat - decrements the same game totals record_manual_event incremented."""
    game_event = db.query(GameEvent).filter(GameEvent.id == event_id, GameEvent.game_id == game_id).first()
    if not game_event:
        raise HTTPException(status_code=404, detail="Event not found")
    game = db.query(Game).filter(Game.id == game_id).first()

    details = game_event.event_details or {}
    if game_event.event_type == "shot":
        game.total_shots = max(0, (game.total_shots or 0) - 1)
        if details.get("made"):
            game.made_shots = max(0, (game.made_shots or 0) - 1)
            game.total_points = max(0, (game.total_points or 0) - details.get("points", 2))
    elif game_event.event_type == "rebound":
        game.total_rebounds = max(0, (game.total_rebounds or 0) - 1)
    elif game_event.event_type == "turnover":
        game.total_turnovers = max(0, (game.total_turnovers or 0) - 1)
    elif game_event.event_type == "assist":
        game.total_assists = max(0, (game.total_assists or 0) - 1)

    db.delete(game_event)
    db.commit()
    return {"deleted": True}


@app.get("/api/games")
async def list_games(db: Session = Depends(get_db)):
    games = db.query(Game).order_by(Game.created_at.desc()).all()
    return {"games": [serialize_game(g) for g in games]}


@app.get("/api/games/{game_id}")
async def get_game(game_id: uuid.UUID, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return serialize_game(game)


@app.get("/api/games/{game_id}/frames")
async def list_frames(game_id: uuid.UUID, db: Session = Depends(get_db)):
    frames = (
        db.query(Frame)
        .filter(Frame.game_id == game_id)
        .order_by(Frame.frame_number)
        .all()
    )
    return {
        "frames": [
            {
                "frame_number": f.frame_number,
                "timestamp_seconds": float(f.timestamp_seconds) if f.timestamp_seconds is not None else None,
                "local_file_path": f.local_file_path,
                "width": f.width,
                "height": f.height,
            }
            for f in frames
        ]
    }


@app.get("/api/games/{game_id}/frames/{frame_number}/image")
async def get_frame_image(game_id: uuid.UUID, frame_number: int, db: Session = Depends(get_db)):
    frame = (
        db.query(Frame)
        .filter(Frame.game_id == game_id, Frame.frame_number == frame_number)
        .first()
    )
    if not frame or not frame.local_file_path or not os.path.exists(frame.local_file_path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(frame.local_file_path)


@app.get("/api/games/{game_id}/frames/{frame_number}/detections")
async def get_frame_detections(game_id: uuid.UUID, frame_number: int, db: Session = Depends(get_db)):
    frame = (
        db.query(Frame)
        .filter(Frame.game_id == game_id, Frame.frame_number == frame_number)
        .first()
    )
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")

    objects = db.query(DetectedObject).filter(DetectedObject.frame_id == frame.id).all()
    player_ids = {o.player_id for o in objects if o.player_id is not None}
    players = {p.id: p for p in db.query(Player).filter(Player.id.in_(player_ids)).all()} if player_ids else {}

    return {
        "width": frame.width,
        "height": frame.height,
        "detections": [
            {
                "id": str(o.id),
                "track_id": o.track_id,
                "object_type": o.object_type,
                "confidence_score": float(o.confidence_score) if o.confidence_score is not None else None,
                "bbox_x": o.bbox_x,
                "bbox_y": o.bbox_y,
                "bbox_width": o.bbox_width,
                "bbox_height": o.bbox_height,
                "estimated_jersey_number": o.estimated_jersey_number,
                "jersey_confidence": float(o.jersey_confidence) if o.jersey_confidence is not None else None,
                "player_id": str(o.player_id) if o.player_id is not None else None,
                "player_jersey_number": players[o.player_id].jersey_number if o.player_id in players else None,
                "player_name": players[o.player_id].player_name if o.player_id in players else None,
                "player_team": players[o.player_id].team if o.player_id in players else None,
            }
            for o in objects
        ],
    }


@app.post("/api/detections/{detection_id}/player")
async def assign_player(detection_id: uuid.UUID, assignment: PlayerAssignment, db: Session = Depends(get_db)):
    """Manually assign (or correct) which player a detected person is - OCR's
    guess (jersey_ocr.py) is unreliable enough that this is the primary path
    to usable per-player data, not a rare fallback."""
    detection = db.query(DetectedObject).filter(DetectedObject.id == detection_id).first()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    if detection.object_type != "person":
        raise HTTPException(status_code=400, detail="Only person detections can be assigned a player")

    frame = db.query(Frame).filter(Frame.id == detection.frame_id).one()
    player = get_or_create_player(db, frame.game_id, assignment.team, assignment.jersey_number, assignment.player_name)
    detection.player_id = player.id
    db.commit()

    return {
        "detection_id": str(detection_id),
        "player_id": str(player.id),
        "player_jersey_number": player.jersey_number,
        "player_name": player.player_name,
    }


@app.post("/api/games/{game_id}/tracks/{track_id}/player")
async def assign_player_to_track(
    game_id: uuid.UUID, track_id: int, assignment: PlayerAssignment, db: Session = Depends(get_db)
):
    """Assign a player to every detection sharing this track_id within this
    game, not just one frame's detection - see DetectedObject.track_id.
    Detections the tracker couldn't tie to a track (track_id is null) aren't
    reachable this way; use /api/detections/{id}/player for those."""
    detections = (
        db.query(DetectedObject)
        .join(Frame, Frame.id == DetectedObject.frame_id)
        .filter(Frame.game_id == game_id, DetectedObject.track_id == track_id, DetectedObject.object_type == "person")
        .all()
    )
    if not detections:
        raise HTTPException(status_code=404, detail="No person detections found for this track in this game")

    player = get_or_create_player(db, game_id, assignment.team, assignment.jersey_number, assignment.player_name)
    for detection in detections:
        detection.player_id = player.id
    db.commit()

    return {
        "track_id": track_id,
        "detections_tagged": len(detections),
        "player_id": str(player.id),
        "player_jersey_number": player.jersey_number,
        "player_name": player.player_name,
    }


@app.post("/api/games/{game_id}/hoop")
async def set_hoop_position(game_id: uuid.UUID, hoop: HoopPosition, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    game.hoop_x = hoop.x
    game.hoop_y = hoop.y
    db.commit()
    return serialize_game(game)


@app.post("/api/games/{game_id}/analyze")
async def analyze_game(game_id: uuid.UUID, db: Session = Depends(get_db)):
    """Run shot detection using the marked hoop position and stored ball detections."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.processing_status != "completed":
        raise HTTPException(status_code=400, detail="Game must finish processing before analyzing")
    if game.hoop_x is None or game.hoop_y is None:
        raise HTTPException(status_code=400, detail="Mark the hoop position before analyzing")

    frames = db.query(Frame).filter(Frame.game_id == game_id).order_by(Frame.frame_number).all()
    if not frames:
        raise HTTPException(status_code=400, detail="No frames to analyze")
    frame_width = frames[0].width

    frame_by_id = {f.id: f for f in frames}
    detections = db.query(DetectedObject).filter(DetectedObject.frame_id.in_(frame_by_id.keys())).all()

    by_frame_number = {f.frame_number: {"balls": [], "persons": []} for f in frames}
    for d in detections:
        frame_number = frame_by_id[d.frame_id].frame_number
        center = {
            "id": str(d.id),
            "x": d.bbox_x + d.bbox_width / 2,
            "y": d.bbox_y + d.bbox_height / 2,
            "confidence": float(d.confidence_score) if d.confidence_score is not None else 0.0,
            "player_id": str(d.player_id) if d.player_id is not None else None,
        }
        if d.object_type == "sports_ball":
            by_frame_number[frame_number]["balls"].append(center)
        elif d.object_type == "person":
            by_frame_number[frame_number]["persons"].append(center)
    for data in by_frame_number.values():
        data["balls"].sort(key=lambda c: c["confidence"], reverse=True)

    ball_positions = []
    frames_by_number = {}
    for frame in frames:
        ts = float(frame.timestamp_seconds) if frame.timestamp_seconds is not None else 0.0
        balls = by_frame_number[frame.frame_number]["balls"]
        if balls:
            ball_positions.append({
                "frame_number": frame.frame_number,
                "timestamp_seconds": ts,
                "x": balls[0]["x"],
                "y": balls[0]["y"],
            })
        frames_by_number[frame.frame_number] = {
            "timestamp_seconds": ts,
            "persons": by_frame_number[frame.frame_number]["persons"],
            "balls": balls,
        }

    # Detect court lines and compute homography for 2PT/3PT classification
    court_homography = None
    if frames:
        court_result = detect_court_lines(frames[0].local_file_path)
        if court_result["success"]:
            homography_result = compute_homography(court_result)
            if homography_result["success"]:
                court_homography = homography_result["homography"]

    # Build pose data list for pose-enhanced shot detection
    # This would come from the pose detection step in process_video_task
    # For now, we use ball positions only; pose data integration happens
    # when the full pipeline is connected
    pose_data_list = None  # TODO: integrate pose data from process_video_task

    shot_events = detect_shots(ball_positions, game.hoop_x, game.hoop_y, frame_width, pose_data_list)

    # Attribute each shot to whoever was nearest the ball just before its
    # approach to the hoop began - not at the approach itself, where the
    # shooter who released it is normally already long gone from that spot
    # (verified: using the approach's own start frame here found nobody for
    # a real shot, because the last tracked ball position before it was 2
    # frames earlier and well outside the hoop-proximity radius). Only
    # resolves to an actual player if a coach has already tagged that
    # specific detection.
    radius = proximity_radius(frame_width)
    for shot in shot_events:
        reference = find_shooter_reference_point(ball_positions, shot["start_frame"])
        reference_frame_data = frames_by_number.get(reference["frame_number"]) if reference else None
        shooter = (
            closest_person_to_ball(reference_frame_data["persons"], reference["x"], reference["y"], radius)
            if reference_frame_data
            else None
        )
        shot["event_details"]["shooter_detection_id"] = shooter["id"] if shooter else None
        shot["event_details"]["shooter_player_id"] = shooter.get("player_id") if shooter else None

        # Add court coordinate classification if homography is available
        if court_homography is not None and shooter:
            shooter_x = shooter["x"]
            shooter_y = shooter["y"]
            court_coords = pixel_to_court_coords(shooter_x, shooter_y, court_homography)
            if court_coords:
                shot["event_details"]["shooter_court_x_ft"] = round(court_coords[0], 2)
                shot["event_details"]["shooter_court_y_ft"] = round(court_coords[1], 2)
                # Classify as 2PT or 3PT
                hoop_court = pixel_to_court_coords(game.hoop_x, game.hoop_y, court_homography)
                if hoop_court:
                    if is_three_point_shot(court_coords[0], court_coords[1], hoop_court[0], hoop_court[1]):
                        shot["event_details"]["shot_type"] = "3PT"
                        shot["event_details"]["points"] = 3
                    else:
                        shot["event_details"]["shot_type"] = "2PT"
                        shot["event_details"]["points"] = 2

    missed_shots = [e for e in shot_events if not e["event_details"]["made"]]
    rebound_events = detect_rebounds(missed_shots, frames_by_number, frame_width)
    all_events = shot_events + rebound_events

    # Re-running analysis replaces the previous shot/rebound events rather than appending.
    db.query(GameEvent).filter(
        GameEvent.game_id == game_id, GameEvent.event_type.in_(["shot", "rebound"])
    ).delete(synchronize_session=False)
    for e in all_events:
        db.add(GameEvent(game_id=game_id, **e))

    game.total_shots = len(shot_events)
    game.made_shots = sum(1 for e in shot_events if e["event_details"]["made"])
    # Calculate total points: 2 for 2PT, 3 for 3PT (when court classification available)
    game.total_points = sum(
        e["event_details"].get("points", 2)
        for e in shot_events
        if e["event_details"]["made"]
    )
    game.total_rebounds = len(rebound_events)
    db.commit()

    return {
        "total_shots": game.total_shots,
        "made_shots": game.made_shots,
        "total_points": game.total_points,
        "total_rebounds": game.total_rebounds,
        "events": all_events,
    }


@app.get("/api/games/{game_id}/events")
async def list_events(game_id: uuid.UUID, db: Session = Depends(get_db)):
    events = db.query(GameEvent).filter(GameEvent.game_id == game_id).order_by(GameEvent.start_frame).all()
    return {
        "events": [
            {
                "event_type": e.event_type,
                "start_frame": e.start_frame,
                "end_frame": e.end_frame,
                "start_timestamp": float(e.start_timestamp) if e.start_timestamp is not None else None,
                "end_timestamp": float(e.end_timestamp) if e.end_timestamp is not None else None,
                "confidence_score": float(e.confidence_score) if e.confidence_score is not None else None,
                "event_details": e.event_details,
            }
            for e in events
        ]
    }


@app.get("/api/games/{game_id}/players/stats")
async def get_player_stats(game_id: uuid.UUID, db: Session = Depends(get_db)):
    """Per-player totals. Manual-entry events (record_manual_event) carry
    player_id directly; video-derived shot/rebound events instead carry
    shooter_player_id/rebounder_player_id inside event_details, since that
    attribution is a guess resolved at analyze time - see analyze_game."""
    events = db.query(GameEvent).filter(GameEvent.game_id == game_id).all()

    def bump(player_id, **deltas):
        s = stats.setdefault(
            player_id, {
                "shots_attempted": 0, "shots_made": 0, "one_pointers_made": 0,
                "two_pointers_made": 0, "three_pointers_made": 0, "points": 0,
                "rebounds": 0, "turnovers": 0, "assists": 0,
            }
        )
        for key, amount in deltas.items():
            s[key] += amount

    stats = {}
    for e in events:
        details = e.event_details or {}
        direct_player_id = str(e.player_id) if e.player_id is not None else None

        if e.event_type == "shot":
            player_id = direct_player_id or details.get("shooter_player_id")
            if not player_id:
                continue
            point_value = details.get("points", 2) if details.get("made") else 0
            point_key = {1: "one_pointers_made", 2: "two_pointers_made", 3: "three_pointers_made"}.get(point_value)
            deltas = {"shots_attempted": 1, "shots_made": 1 if details.get("made") else 0, "points": point_value}
            if point_key:
                deltas[point_key] = 1
            bump(player_id, **deltas)
        elif e.event_type == "rebound":
            player_id = direct_player_id or details.get("rebounder_player_id")
            if not player_id:
                continue
            bump(player_id, rebounds=1)
        elif e.event_type == "turnover" and direct_player_id:
            bump(direct_player_id, turnovers=1)
        elif e.event_type == "assist" and direct_player_id:
            bump(direct_player_id, assists=1)

    if not stats:
        return {"players": []}

    players = {
        str(p.id): p
        for p in db.query(Player).filter(Player.id.in_([uuid.UUID(pid) for pid in stats.keys()])).all()
    }

    result = [
        {
            "player_id": player_id,
            "team": players[player_id].team if player_id in players else None,
            "jersey_number": players[player_id].jersey_number if player_id in players else None,
            "player_name": players[player_id].player_name if player_id in players else None,
            **totals,
        }
        for player_id, totals in stats.items()
    ]
    result.sort(key=lambda r: r["jersey_number"] if r["jersey_number"] is not None else -1)
    return {"players": result}


def serialize_game(game: Game) -> dict:
    return {
        "id": str(game.id),
        "title": game.title,
        "date_played": game.date_played.isoformat() if game.date_played else None,
        "entry_mode": game.entry_mode,
        "processing_status": game.processing_status,
        "processing_error": game.processing_error,
        "frame_count": game.frame_count,
        "hoop_x": game.hoop_x,
        "hoop_y": game.hoop_y,
        "video_duration_seconds": game.video_duration_seconds,
        "total_shots": game.total_shots,
        "made_shots": game.made_shots,
        "total_points": game.total_points,
        "total_rebounds": game.total_rebounds,
        "total_turnovers": game.total_turnovers,
        "total_assists": game.total_assists,
        "created_at": game.created_at.isoformat() if game.created_at else None,
    }


def process_video_task(game_id: str, video_path: str):
    """Background task: extract frames from the uploaded video and store them."""
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            logger.error(f"Game {game_id} not found for processing")
            return

        game.processing_status = "processing"
        game.processing_started_at = datetime.utcnow()
        db.commit()

        logger.info(f"Extracting frames for game {game_id} from {video_path}")
        output_dir = FRAMES_PATH / game_id
        frames, duration_seconds = extract_frames(video_path, output_dir)

        frame_rows = [Frame(game_id=game_id, **f) for f in frames]
        db.add_all(frame_rows)
        game.frame_count = len(frames)
        game.video_duration_seconds = int(duration_seconds) if duration_seconds is not None else None
        db.commit()

        game.processing_status = "detecting"
        db.commit()

        logger.info(f"Running YOLO11 + OC-SORT detection on {len(frame_rows)} frames for game {game_id}")
        reset_tracker(get_model())
        detection_count = 0
        pose_data_by_frame = {}

        for frame_row in frame_rows:
            detections = detect_objects(frame_row.local_file_path)

            # Run pose estimation on the same frame
            pose_results = detect_pose(frame_row.local_file_path, detections)
            pose_data_by_frame[frame_row.frame_number] = pose_results

            for det in detections:
                obj = DetectedObject(frame_id=frame_row.id, **det)
                if det["object_type"] == "person":
                    number, confidence = read_jersey_number(
                        frame_row.local_file_path, det["bbox_x"], det["bbox_y"], det["bbox_width"], det["bbox_height"]
                    )
                    obj.estimated_jersey_number = number
                    obj.jersey_confidence = confidence
                db.add(obj)
                detection_count += 1
            frame_row.processed_at = datetime.utcnow()
        db.commit()

        # Detect court lines and compute homography for coordinate transformation
        court_homography = None
        if frame_rows:
            logger.info("Detecting court lines for coordinate transformation...")
            court_result = detect_court_lines(frame_rows[0].local_file_path)
            if court_result["success"]:
                homography_result = compute_homography(court_result)
                if homography_result["success"]:
                    court_homography = homography_result["homography"]
                    logger.info("Court lines detected - homography computed for 2PT/3PT classification")
                else:
                    logger.info("Court lines detected but homography computation failed")
            else:
                logger.info("Could not detect court lines - 2PT/3PT classification unavailable")

        game.processing_status = "completed"
        game.processing_completed_at = datetime.utcnow()
        db.commit()

        logger.info(
            f"Processing complete for game {game_id}: {len(frames)} frames, "
            f"{detection_count} detections"
        )
    except Exception as e:
        logger.exception(f"Error processing game {game_id}")
        db.rollback()
        game = db.query(Game).filter(Game.id == game_id).first()
        if game:
            game.processing_status = "failed"
            game.processing_error = str(e)
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
