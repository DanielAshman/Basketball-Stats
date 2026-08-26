from pathlib import Path

import cv2

TARGET_FPS = 2.0


def extract_frames(video_path: str, output_dir: Path, target_fps: float = TARGET_FPS):
    """Extract frames from a video at roughly `target_fps` and save them as JPEGs.

    Returns (frames, duration_seconds) where frames is a list of dicts matching
    the `frames` table columns (minus id/game_id).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(int(round(source_fps / target_fps)), 1)

    frames = []
    frame_index = 0
    saved_index = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_index % frame_interval == 0:
                filename = f"frame_{saved_index:06d}.jpg"
                filepath = output_dir / filename
                cv2.imwrite(str(filepath), frame)

                height, width = frame.shape[:2]
                frames.append({
                    "frame_number": saved_index,
                    "timestamp_seconds": round(frame_index / source_fps, 2),
                    "local_file_path": str(filepath),
                    "width": width,
                    "height": height,
                })
                saved_index += 1

            frame_index += 1
    finally:
        cap.release()

    duration_seconds = frame_index / source_fps if source_fps else None
    return frames, duration_seconds
