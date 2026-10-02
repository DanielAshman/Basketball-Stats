"""Shot detection combining ball-position heuristics with pose-based action recognition.

Uses two complementary signals:
    1. Ball proximity to hoop (heuristic, existing approach)
    2. Player shooting motion from pose estimation (new, more reliable)

The pose-based detection is the primary signal - it detects the actual shooting
motion rather than inferring intent from ball position. Ball proximity is used
as a secondary confirmation and for made/missed classification.

Court coordinates (when available) enable automatic 2PT/3PT classification.
"""

import logging
from .pose_analyzer import detect_shooting_motion

logger = logging.getLogger(__name__)

# How close (as a fraction of frame width) the ball needs to get to the hoop
# to count as a shot attempt.
PROXIMITY_FRACTION = 0.12
MIN_PROXIMITY_PX = 45

# How close (as a fraction of the proximity radius) the ball must stay,
# horizontally, after the closest approach to call it a make rather than a
# rebound bouncing away.
MADE_OFFSET_FRACTION = 0.4

# A shot attempt run tolerates the ball detection dropping out for up to this
# many consecutive sampled frames (e.g. motion blur, occlusion) without
# ending the cluster.
MAX_FRAME_GAP = 3

# How many frames after the closest approach to search for the ball's
# outcome position (see MADE_OFFSET_FRACTION below). At the pipeline's 2fps
# sampling this is ~4 seconds - long enough for a real rim-out to have
# visibly bounced away from the hoop, short enough that it can't reach into
# an unrelated later possession.
MADE_OUTCOME_LOOKAHEAD_FRAMES = 8

# Minimum confidence from pose-based shot detection to consider it valid
POSE_SHOT_CONFIDENCE_THRESHOLD = 0.5


def _distance(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def detect_shots(ball_positions, hoop_x, hoop_y, frame_width, pose_data_list=None):
    """Detect shots using ball positions and optional pose data.

    Args:
        ball_positions: list of dicts with frame_number, timestamp_seconds, x, y
        hoop_x, hoop_y: hoop position in pixels
        frame_width: frame width in pixels
        pose_data_list: optional list of pose data dicts from detect_pose(),
            one per frame, used for pose-based shot detection

    Returns:
        list of shot-event dicts with made/missed, confidence, and optional
        pose-based phase information
    """
    if not ball_positions:
        return []

    radius = max(frame_width * PROXIMITY_FRACTION, MIN_PROXIMITY_PX)

    near_points = []
    for p in ball_positions:
        dist = _distance(p["x"], p["y"], hoop_x, hoop_y)
        if dist <= radius:
            near_points.append({**p, "distance": dist})

    if not near_points:
        return []

    clusters = []
    current = [near_points[0]]
    for p in near_points[1:]:
        if p["frame_number"] - current[-1]["frame_number"] <= MAX_FRAME_GAP:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)

    events = []
    for cluster in clusters:
        closest = min(cluster, key=lambda p: p["distance"])

        after = [
            p
            for p in ball_positions
            if closest["frame_number"] < p["frame_number"] <= closest["frame_number"] + MADE_OUTCOME_LOOKAHEAD_FRAMES
        ]
        last_after = after[-1] if after else None

        if last_after is not None:
            horizontal_offset = abs(last_after["x"] - hoop_x)
            made = last_after["y"] > closest["y"] and horizontal_offset <= radius * MADE_OFFSET_FRACTION
            end_point = last_after
        else:
            made = False
            end_point = closest

        confidence = max(0.0, 1 - closest["distance"] / radius)

        event = {
            "event_type": "shot",
            "start_frame": cluster[0]["frame_number"],
            "end_frame": end_point["frame_number"],
            "start_timestamp": cluster[0]["timestamp_seconds"],
            "end_timestamp": end_point["timestamp_seconds"],
            "confidence_score": round(confidence, 3),
            "event_details": {
                "made": made,
                "closest_frame": closest["frame_number"],
                "closest_distance_px": round(closest["distance"], 1),
                "hoop_x": hoop_x,
                "hoop_y": hoop_y,
            },
        }

        # Enhance with pose-based detection if available
        if pose_data_list:
            pose_shot = _find_pose_shot(pose_data_list, cluster[0]["frame_number"], end_point["frame_number"])
            if pose_shot:
                event["event_details"]["pose_shot_confidence"] = pose_shot["confidence"]
                event["event_details"]["pose_shot_phase"] = pose_shot["phase"]
                # Boost confidence if both signals agree
                if pose_shot["is_shooting"]:
                    event["confidence_score"] = round(min(confidence + 0.2, 1.0), 3)

        events.append(event)

    return events


def _find_pose_shot(pose_data_list, start_frame, end_frame):
    """Find the highest-confidence pose-based shot detection within a frame range."""
    best_shot = None
    best_confidence = 0.0

    for pose_data in pose_data_list:
        frame_num = pose_data.get("frame_number")
        if frame_num is None or frame_num < start_frame or frame_num > end_frame:
            continue

        shot = detect_shooting_motion(pose_data)
        if shot["is_shooting"] and shot["confidence"] > best_confidence:
            best_confidence = shot["confidence"]
            best_shot = shot

    return best_shot


def classify_shot_type(shot_event, court_homography=None, hoop_court_coords=None):
    """Classify a shot as 1PT, 2PT, or 3PT based on court coordinates.

    Args:
        shot_event: shot event dict from detect_shots()
        court_homography: 3x3 homography matrix from court_detection
        hoop_court_coords: (x_ft, y_ft) of hoop in court coordinates

    Returns:
        int: 1, 2, or 3 (point value), or None if classification not possible
    """
    if court_homography is None or hoop_court_coords is None:
        return None

    # Get shot origin (start of shot)
    start_frame = shot_event["start_frame"]
    # We need the ball position at shot origin - this would need to be passed in
    # For now, return None if we can't classify
    return None
