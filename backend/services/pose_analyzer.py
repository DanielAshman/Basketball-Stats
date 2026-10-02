"""Pose-based action recognition for basketball.

Uses body keypoints from YOLO11-Pose to detect shooting motions and other
actions. This is more reliable than ball-proximity heuristics because it
detects the player's actual movement rather than inferring intent from ball
position.

Key actions detected:
    - Shot preparation (arms raised, ball held above head)
    - Shot release (arms extended upward, wrist flick)
    - Rebound position (arms raised, jumping)
    - Dribbling (arm extended downward, rhythmic motion)
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)

# COCO keypoint indices
NOSE = 0
LEFT_EYE = 1
RIGHT_EYE = 2
LEFT_EAR = 3
RIGHT_EAR = 4
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_ELBOW = 7
RIGHT_ELBOW = 8
LEFT_WRIST = 9
RIGHT_WRIST = 10
LEFT_HIP = 11
RIGHT_HIP = 12
LEFT_KNEE = 13
RIGHT_KNEE = 14
LEFT_ANKLE = 15
RIGHT_ANKLE = 16

# Minimum confidence for keypoints to be considered valid
KEYPOINT_CONFIDENCE_THRESHOLD = 0.3


def _get_keypoint(keypoints, idx):
    """Get a keypoint as (x, y, conf) or None if invalid."""
    if idx >= len(keypoints):
        return None
    kp = keypoints[idx]
    if kp[2] < KEYPOINT_CONFIDENCE_THRESHOLD:
        return None
    return kp


def _distance(kp1, kp2):
    """Euclidean distance between two keypoints."""
    if kp1 is None or kp2 is None:
        return None
    return np.sqrt((kp1[0] - kp2[0]) ** 2 + (kp1[1] - kp2[1]) ** 2)


def _angle(p1, p2, p3):
    """Calculate angle at p2 formed by p1-p2-p3 in degrees."""
    if p1 is None or p2 is None or p3 is None:
        return None

    a = np.array([p1[0], p1[1]])
    b = np.array([p2[0], p2[1]])
    c = np.array([p3[0], p3[1]])

    ba = a - b
    bc = c - b

    cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))

    return np.degrees(angle)


def detect_shooting_motion(pose_data):
    """Detect if a player is in a shooting motion based on body keypoints.

    Looks for:
        - Arms raised above shoulders (preparation)
        - Elbows extended upward (release)
        - Wrists above head (follow-through)

    Args:
        pose_data: dict with 'keypoints' list from detect_pose()

    Returns:
        dict with:
            - is_shooting: bool
            - confidence: float (0-1)
            - phase: str ('preparation', 'release', 'follow_through', or None)
            - details: dict with measurements
    """
    keypoints = pose_data.get("keypoints", [])
    if not keypoints:
        return {"is_shooting": False, "confidence": 0.0, "phase": None, "details": {}}

    # Get relevant keypoints
    left_shoulder = _get_keypoint(keypoints, LEFT_SHOULDER)
    right_shoulder = _get_keypoint(keypoints, RIGHT_SHOULDER)
    left_elbow = _get_keypoint(keypoints, LEFT_ELBOW)
    right_elbow = _get_keypoint(keypoints, RIGHT_ELBOW)
    left_wrist = _get_keypoint(keypoints, LEFT_WRIST)
    right_wrist = _get_keypoint(keypoints, RIGHT_WRIST)
    nose = _get_keypoint(keypoints, NOSE)

    if not all([left_shoulder, right_shoulder, left_elbow, right_elbow]):
        return {"is_shooting": False, "confidence": 0.0, "phase": None, "details": {}}

    # Calculate shoulder width for normalization
    shoulder_width = _distance(left_shoulder, right_shoulder)
    if shoulder_width is None or shoulder_width < 1:
        shoulder_width = 1.0

    # Check if arms are raised (wrists above shoulders)
    left_wrist_above = left_wrist is not None and left_wrist[1] < left_shoulder[1]
    right_wrist_above = right_wrist is not None and right_wrist[1] < right_shoulder[1]

    # Check elbow angles (extended = shooting, bent = dribbling/holding)
    left_elbow_angle = _angle(left_shoulder, left_elbow, left_wrist) if left_wrist else None
    right_elbow_angle = _angle(right_shoulder, right_elbow, right_wrist) if right_wrist else None

    # Shooting indicators
    wrists_above_head = (left_wrist_above and right_wrist_above) or \
                        (left_wrist and nose and left_wrist[1] < nose[1]) or \
                        (right_wrist and nose and right_wrist[1] < nose[1])

    elbows_extended = (left_elbow_angle and left_elbow_angle > 140) or \
                      (right_elbow_angle and right_elbow_angle > 140)

    # Determine phase
    phase = None
    if wrists_above_head and elbows_extended:
        phase = "release"
    elif wrists_above_head:
        phase = "preparation"
    elif left_wrist_above or right_wrist_above:
        phase = "follow_through"

    # Calculate confidence
    confidence = 0.0
    if wrists_above_head:
        confidence += 0.4
    if elbows_extended:
        confidence += 0.3
    if left_wrist_above and right_wrist_above:
        confidence += 0.3

    is_shooting = confidence > 0.5

    return {
        "is_shooting": is_shooting,
        "confidence": round(min(confidence, 1.0), 3),
        "phase": phase,
        "details": {
            "wrists_above_head": wrists_above_head,
            "elbows_extended": elbows_extended,
            "left_elbow_angle": round(left_elbow_angle, 1) if left_elbow_angle else None,
            "right_elbow_angle": round(right_elbow_angle, 1) if right_elbow_angle else None,
            "shoulder_width_px": round(shoulder_width, 1),
        }
    }


def detect_rebound_motion(pose_data):
    """Detect if a player is in a rebounding position.

    Looks for:
        - Arms raised high (above head)
        - Body extended (jumping reach)

    Returns:
        dict with is_rebounding, confidence, and details
    """
    keypoints = pose_data.get("keypoints", [])
    if not keypoints:
        return {"is_rebounding": False, "confidence": 0.0}

    left_wrist = _get_keypoint(keypoints, LEFT_WRIST)
    right_wrist = _get_keypoint(keypoints, RIGHT_WRIST)
    left_shoulder = _get_keypoint(keypoints, LEFT_SHOULDER)
    right_shoulder = _get_keypoint(keypoints, RIGHT_SHOULDER)
    nose = _get_keypoint(keypoints, NOSE)

    if not all([left_wrist, right_wrist, left_shoulder, right_shoulder]):
        return {"is_rebounding": False, "confidence": 0.0}

    # Wrists well above shoulders indicates reaching for a rebound
    left_reach = left_shoulder[1] - left_wrist[1]  # Positive if wrist above shoulder
    right_reach = right_shoulder[1] - right_wrist[1]

    shoulder_width = _distance(left_shoulder, right_shoulder) or 1.0

    # Normalize reach by shoulder width
    normalized_reach = (left_reach + right_reach) / (2 * shoulder_width)

    is_rebounding = normalized_reach > 0.5  # Wrists at least half shoulder-width above shoulders
    confidence = min(normalized_reach, 1.0)

    return {
        "is_rebounding": is_rebounding,
        "confidence": round(confidence, 3),
        "normalized_reach": round(normalized_reach, 3),
    }


def analyze_player_actions(pose_data_list):
    """Analyze a sequence of pose data to detect actions over time.

    Args:
        pose_data_list: list of pose_data dicts from detect_pose(), in frame order

    Returns:
        list of detected actions with frame ranges
    """
    actions = []

    for i, pose_data in enumerate(pose_data_list):
        shooting = detect_shooting_motion(pose_data)
        rebound = detect_rebound_motion(pose_data)

        if shooting["is_shooting"]:
            actions.append({
                "frame_index": i,
                "action": "shot",
                "phase": shooting["phase"],
                "confidence": shooting["confidence"],
            })

        if rebound["is_rebounding"]:
            actions.append({
                "frame_index": i,
                "action": "rebound",
                "confidence": rebound["confidence"],
            })

    return actions
