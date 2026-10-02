import logging
import threading

from ultralytics import YOLO

logger = logging.getLogger(__name__)

# Stock YOLO COCO weights only know "person" (0) and "sports ball" (32) as
# basketball-relevant classes - there is no hoop/rim class in COCO, so hoop
# detection needs a custom-trained model (tracked as a future accuracy step).
TRACKED_CLASSES = {0: "person", 32: "sports_ball"}
CONFIDENCE_THRESHOLD = 0.25

# OC-SORT (Observation-Centric SORT): better than ByteTrack for sports because
# it handles long occlusions (players crossing behind each other) and camera
# motion (common in handheld/phone footage) more gracefully. At 2fps sampling,
# players frequently overlap or get briefly occluded - OC-SORT maintains their
# identity through those gaps better than ByteTrack.
TRACKER_CONFIG = "ocsort.yaml"

# YOLO11m: significantly better accuracy than YOLOv8s at similar speed. The
# "m" (medium) size is a good balance - large enough for reliable player/ball
# detection on fast-moving basketball footage, small enough to run at
# interactive speeds on CPU.
DETECTION_MODEL_NAME = "yolo11m.pt"

# YOLO11 pose model: detects body keypoints (shoulders, elbows, wrists, knees,
# ankles) for each player. Used for action recognition - detecting the shooting
# motion itself rather than just ball proximity to hoop.
POSE_MODEL_NAME = "yolo11m-pose.pt"

_model = None
_pose_model = None
_model_lock = threading.Lock()

# Uploads run as FastAPI BackgroundTasks on a threadpool, so two uploads
# processed close together can call into the model concurrently. Ultralytics'
# Predictor isn't documented as thread-safe, so inference calls (not just
# model creation) are serialized through this lock.
_inference_lock = threading.Lock()


def get_model() -> YOLO:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                logger.info(f"Loading {DETECTION_MODEL_NAME} model...")
                _model = YOLO(DETECTION_MODEL_NAME)
                logger.info(f"{DETECTION_MODEL_NAME} model loaded")
    return _model


def get_pose_model() -> YOLO:
    global _pose_model
    if _pose_model is None:
        with _model_lock:
            if _pose_model is None:
                logger.info(f"Loading {POSE_MODEL_NAME} pose model...")
                _pose_model = YOLO(POSE_MODEL_NAME)
                logger.info(f"{POSE_MODEL_NAME} pose model loaded")
    return _pose_model


def reset_tracker(model: YOLO):
    """Clear OC-SORT's in-memory state before starting a new game's frame
    loop, so track_ids restart at 1 instead of continuing from whatever game
    was last processed on this shared model instance. Ultralytics has no
    public reset API for this; dropping the lazily-created predictor forces
    model.track() to build a fresh one (and a fresh tracker) on its next
    call - verified this produces the same track_id sequence as a brand-new
    YOLO instance would."""
    model.predictor = None


def detect_objects(frame_path: str):
    """Run YOLO11 + OC-SORT on a frame and return basketball-relevant
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


def detect_pose(frame_path: str, person_detections: list[dict]):
    """Run YOLO11-Pose on a frame and return keypoints for each detected person.

    Returns a list of dicts with:
        - track_id: matches the track_id from detect_objects() if available
        - keypoints: list of [x, y, confidence] for each of the 17 COCO keypoints
        - bbox: [x1, y1, x2, y2] bounding box

    Keypoints follow COCO format:
        0: nose, 1-2: eyes, 3-4: ears, 5-6: shoulders, 7-8: elbows, 9-10: wrists,
        11-12: hips, 13-14: knees, 15-16: ankles
    """
    pose_model = get_pose_model()
    with _inference_lock:
        results = pose_model(frame_path, verbose=False)

    pose_results = []
    for result in results:
        if result.keypoints is None:
            continue

        boxes = result.boxes
        keypoints = result.keypoints

        for i, box in enumerate(boxes):
            class_id = int(box.cls[0])
            if class_id != 0:  # Only process persons
                continue

            confidence = float(box.conf[0])
            if confidence < CONFIDENCE_THRESHOLD:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            box_id = int(boxes.id[i]) if boxes.id is not None else None

            # Get keypoints for this person: shape (17, 3) -> [x, y, conf]
            kpts = keypoints[i].xy[0].cpu().numpy()
            kpts_conf = keypoints[i].conf[0].cpu().numpy() if keypoints[i].conf is not None else np.ones(17)

            keypoints_list = []
            for j in range(len(kpts)):
                keypoints_list.append([
                    float(kpts[j][0]),
                    float(kpts[j][1]),
                    float(kpts_conf[j]) if j < len(kpts_conf) else 0.0
                ])

            pose_results.append({
                "track_id": box_id,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "confidence_score": round(confidence, 3),
                "keypoints": keypoints_list,
            })

    return pose_results


import numpy as np  # Used in detect_pose for keypoint confidence handling
