import logging
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import Frame, Game
from services.frame_extraction import extract_frames

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

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).replace(" ", "_")
    video_filename = f"{safe_title}_{date_played}{Path(video.filename or '').suffix or '.mp4'}"
    video_path = VIDEOS_PATH / video_filename

    with open(video_path, "wb") as buffer:
        buffer.write(await video.read())

    logger.info(f"Video saved: {video_path}")

    game = Game(
        title=title,
        date_played=parsed_date,
        video_file_path=str(video_path),
        processing_status="pending",
    )
    db.add(game)
    db.commit()
    db.refresh(game)

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
async def get_game(game_id: str, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return serialize_game(game)


@app.get("/api/games/{game_id}/frames")
async def list_frames(game_id: str, db: Session = Depends(get_db)):
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


def serialize_game(game: Game) -> dict:
    return {
        "id": str(game.id),
        "title": game.title,
        "date_played": game.date_played.isoformat() if game.date_played else None,
        "processing_status": game.processing_status,
        "processing_error": game.processing_error,
        "frame_count": game.frame_count,
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

        for f in frames:
            db.add(Frame(game_id=game_id, **f))

        game.frame_count = len(frames)
        game.video_duration_seconds = int(duration_seconds) if duration_seconds else None
        game.processing_status = "completed"
        game.processing_completed_at = datetime.utcnow()
        db.commit()

        logger.info(f"Processing complete for game {game_id}: {len(frames)} frames extracted")
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
