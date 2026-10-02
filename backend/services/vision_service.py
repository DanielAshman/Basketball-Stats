import logging
import threading

from ultralytics import YOLO

logger = logging.getLogger(__name__)

# Stock YOLOv8 COCO weights only know "person" (0) and "sports ball" (32) as
# basketball-relevant classes - there is no hoop/rim class in COCO, so hoop
# detection needs a custom-trained model (tracked as a future accuracy step).
TRACKED_CLASSES = {0: "person", 32: "sports_ball"}
CONFIDENCE_THRESHOLD = 0.25

# ByteTrack: assigns a persistent track_id to each person/ball across the
# per-frame detect_objects() calls made while processing one game (frames are
# fed to model.track(..., persist=True) one at a time, in frame order, rather
# than handing it a video - persist=True is what tells ByteTrack these calls
# are one continuous sequence instead of independent single frames). At this
# pipeline's 2fps frame sampling, verified against a real game clip: most
# tracks survive one frame-to-frame gap (0.5s) but a track can still drop and
# a new one spawn within 1-2s as players move fast between sampled frames -
# so this cuts down re-tagging the same player, it doesn't eliminate it.
TRACKER_CONFIG = "bytetrack.yaml"

_model = None
_model_lock = threading.Lock()

# Uploads run as FastAPI BackgroundTasks on a threadpool, so two uploads
# processed close together can call into the model concurrently. Ultralytics'
# Predictor isn't documented as thread-safe, so inference calls (not just
# model creation) are serialized through this lock.
_inference_lock = threading.Lock()


MODEL_NAME = "yolov8s.pt"


def get_model() -> YOLO:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                logger.info(f"Loading {MODEL_NAME} model...")
                _model = YOLO(MODEL_NAME)
                logger.info(f"{MODEL_NAME} model loaded")
    return _model


def reset_tracker(model: YOLO):
    """Clear ByteTrack's in-memory state before starting a new game's frame
    loop, so track_ids restart at 1 instead of continuing from whatever game
    was last processed on this shared model instance. Ultralytics has no
    public reset API for this; dropping the lazily-created predictor forces
    model.track() to build a fresh one (and a fresh tracker) on its next
    call - verified this produces the same track_id sequence as a brand-new
    YOLO instance would."""
    model.predictor = None


def detect_objects(frame_path: str):
    """Run YOLOv8 + ByteTrack on a frame and return basketball-relevant
    detections, tagged with a track_id where the tracker could assign one.
    Must be called in frame order for a single game, with reset_tracker()
    called first - see TRACKER_CONFIG above."""
    model = get_model()
    with _inference_lock:
        results = model.track(frame_path, persist=True, tracker=TRACKER_CONFIG, verbose=False)

    detections = []
    for result in results:
        box_ids = result.boxes.id
        for i, box in enumerate(result.boxes):
            class_id = int(box.cls[0])
            if class_id not in TRACKED_CLASSES:
                continue

            confidence = float(box.conf[0])
            if confidence < CONFIDENCE_THRESHOLD:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append({
                "object_type": TRACKED_CLASSES[class_id],
                "confidence_score": round(confidence, 3),
                "bbox_x": int(x1),
                "bbox_y": int(y1),
                "bbox_width": int(x2 - x1),
                "bbox_height": int(y2 - y1),
                "track_id": int(box_ids[i]) if box_ids is not None else None,
            })

    return detections
