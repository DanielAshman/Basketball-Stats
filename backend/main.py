import logging
import os
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import DetectedObject, Frame, Game, GameEvent
from services.frame_extraction import extract_frames
from services.rebound_detection import detect_rebounds
from services.shot_detection import detect_shots
from services.vision_service import detect_objects, get_model

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


class HoopPosition(BaseModel):
    x: int
    y: int


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
    return {
        "width": frame.width,
        "height": frame.height,
        "detections": [
            {
                "object_type": o.object_type,
                "confidence_score": float(o.confidence_score) if o.confidence_score is not None else None,
                "bbox_x": o.bbox_x,
                "bbox_y": o.bbox_y,
                "bbox_width": o.bbox_width,
                "bbox_height": o.bbox_height,
            }
            for o in objects
        ],
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
            "x": d.bbox_x + d.bbox_width / 2,
            "y": d.bbox_y + d.bbox_height / 2,
            "confidence": float(d.confidence_score) if d.confidence_score is not None else 0.0,
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

    shot_events = detect_shots(ball_positions, game.hoop_x, game.hoop_y, frame_width)
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
    game.total_rebounds = len(rebound_events)
    db.commit()

    return {
        "total_shots": game.total_shots,
        "made_shots": game.made_shots,
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


def serialize_game(game: Game) -> dict:
    return {
        "id": str(game.id),
        "title": game.title,
        "date_played": game.date_played.isoformat() if game.date_played else None,
        "processing_status": game.processing_status,
        "processing_error": game.processing_error,
        "frame_count": game.frame_count,
        "hoop_x": game.hoop_x,
        "hoop_y": game.hoop_y,
        "video_duration_seconds": game.video_duration_seconds,
        "total_shots": game.total_shots,
        "made_shots": game.made_shots,
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

        logger.info(f"Running YOLOv8 detection on {len(frame_rows)} frames for game {game_id}")
        detection_count = 0
        for frame_row in frame_rows:
            for det in detect_objects(frame_row.local_file_path):
                db.add(DetectedObject(frame_id=frame_row.id, **det))
                detection_count += 1
            frame_row.processed_at = datetime.utcnow()
        db.commit()

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
