import logging

from ultralytics import YOLO

logger = logging.getLogger(__name__)

# Stock YOLOv8 COCO weights only know "person" (0) and "sports ball" (32) as
# basketball-relevant classes - there is no hoop/rim class in COCO, so hoop
# detection needs a custom-trained model (tracked as a future accuracy step).
TRACKED_CLASSES = {0: "person", 32: "sports_ball"}
CONFIDENCE_THRESHOLD = 0.25

_model = None


def get_model() -> YOLO:
    global _model
    if _model is None:
        logger.info("Loading YOLOv8n model...")
        _model = YOLO("yolov8n.pt")
        logger.info("YOLOv8n model loaded")
    return _model


def detect_objects(frame_path: str):
    """Run YOLOv8 on a frame and return basketball-relevant detections."""
    model = get_model()
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
