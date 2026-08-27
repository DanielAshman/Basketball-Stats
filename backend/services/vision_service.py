import logging
import threading

from ultralytics import YOLO

logger = logging.getLogger(__name__)

# Stock YOLOv8 COCO weights only know "person" (0) and "sports ball" (32) as
# basketball-relevant classes - there is no hoop/rim class in COCO, so hoop
# detection needs a custom-trained model (tracked as a future accuracy step).
TRACKED_CLASSES = {0: "person", 32: "sports_ball"}
CONFIDENCE_THRESHOLD = 0.25

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


def detect_objects(frame_path: str):
    """Run YOLOv8 on a frame and return basketball-relevant detections."""
    model = get_model()
    with _inference_lock:
        results = model(frame_path, verbose=False)

    detections = []
    for result in results:
        for box in result.boxes:
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
            })

    return detections
