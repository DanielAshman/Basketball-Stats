from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from dotenv import load_dotenv
import logging

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# App setup
app = FastAPI(title="Basketball Analytics - Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://basketball_user:dev_password_123@localhost:5432/basketball_analytics")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Paths
VIDEOS_PATH = Path(os.getenv("VIDEOS_PATH", "./videos"))
VIDEOS_PATH.mkdir(exist_ok=True)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "environment": "local"}

@app.post("/api/games")
async def create_game(
    title: str,
    date_played: str,
    video: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Upload a game video and queue for processing"""
    try:
        # Save video file locally
        video_filename = f"{title.replace(' ', '_')}_{date_played}.mp4"
        video_path = VIDEOS_PATH / video_filename

        with open(video_path, "wb") as buffer:
            content = await video.read()
            buffer.write(content)

        logger.info(f"Video saved: {video_path}")

        # Queue processing task
        background_tasks.add_task(process_video_task, str(video_path), title, date_played)

        return {
            "status": "queued",
            "title": title,
            "message": "Video uploaded. Processing started..."
        }
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/games")
async def list_games():
    """List all games"""
    try:
        session = SessionLocal()
        # TODO: Query games from database
        return {"games": []}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

async def process_video_task(video_path: str, title: str, date_played: str):
    """Background task to process video"""
    logger.info(f"Processing video: {video_path}")
    # Vision processing logic will go here
    logger.info(f"Processing complete for: {title}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
