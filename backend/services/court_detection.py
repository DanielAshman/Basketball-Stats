"""Court line detection and homography transformation.

Detects court lines in a frame using computer vision techniques and computes
a homography matrix to transform pixel coordinates to real-world court
coordinates. This enables:
    - Automatic 2PT/3PT shot classification
    - Real-world distance measurements (feet/meters)
    - Player speed calculation in real units

The detection uses color segmentation and Hough line transform to find
court boundaries and key lines (baseline, sideline, three-point line).
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Standard NBA court dimensions in feet (used for homography target)
COURT_LENGTH_FT = 94.0
COURT_WIDTH_FT = 50.0
THREE_POINT_LINE_FT = 23.75  # Distance from basket to top of three-point line
THREE_POINT_LINE_CORNER_FT = 22.0  # Distance from basket to corner three-point line
FREE_THROW_LINE_FT = 15.0  # Distance from baseline to free throw line


def detect_court_lines(frame_path: str):
    """Detect court lines in a frame using color segmentation and Hough transform.

    Returns a dict with:
        - success: bool, whether enough lines were detected
        - lines: list of detected lines, each as [x1, y1, x2, y2]
        - court_mask: binary mask of detected court area
        - key_points: dict with detected key court points (corners, free throw, etc.)
    """
    img = cv2.imread(frame_path)
    if img is None:
        return {"success": False, "error": "Could not read image"}

    h, w = img.shape[:2]

    # Convert to HSV for color-based court detection
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Detect court floor (typically brown/orange wood or green/blue synthetic)
    # Wood court: hue around 10-30, moderate saturation
    lower_wood = np.array([5, 40, 40])
    upper_wood = np.array([35, 255, 255])
    wood_mask = cv2.inRange(hsv, lower_wood, upper_wood)

    # Synthetic court: green/blue hues
    lower_synthetic = np.array([35, 30, 30])
    upper_synthetic = np.array([95, 255, 255])
    synthetic_mask = cv2.inRange(hsv, lower_synthetic, upper_synthetic)

    # Combine masks
    court_mask = cv2.bitwise_or(wood_mask, synthetic_mask)

    # Clean up mask
    kernel = np.ones((5, 5), np.uint8)
    court_mask = cv2.morphologyEx(court_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    court_mask = cv2.morphologyEx(court_mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # Detect white lines on the court
    # White lines have low saturation and high value
    lower_white = np.array([0, 0, 180])
    upper_white = np.array([180, 50, 255])
    white_mask = cv2.inRange(hsv, lower_white, upper_white)

    # Only keep white lines within the court area
    white_lines = cv2.bitwise_and(white_mask, court_mask)

    # Edge detection for line finding
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(white_lines, 50, 150)

    # Hough line transform
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=w // 6,
        maxLineGap=20
    )

    detected_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            detected_lines.append([int(x1), int(y1), int(x2), int(y2)])

    # Find court corners and key points
    key_points = _find_key_points(detected_lines, w, h)

    success = len(detected_lines) >= 4  # Need at least 4 lines for a reasonable court

    return {
        "success": success,
        "lines": detected_lines,
        "court_mask": court_mask,
        "key_points": key_points,
    }


def _find_key_points(lines, img_width, img_height):
    """Extract key court points from detected lines.

    Finds intersections of lines to locate:
    - Court corners
    - Free throw line endpoints
    - Three-point line position
    """
    if len(lines) < 2:
        return {}

    # Calculate line angles to categorize them
    horizontal_lines = []
    vertical_lines = []

    for line in lines:
        x1, y1, x2, y2 = line
        angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi

        if abs(angle) < 20 or abs(angle) > 160:
            horizontal_lines.append(line)
        elif abs(angle - 90) < 20 or abs(angle + 90) < 20:
            vertical_lines.append(line)

    key_points = {
        "horizontal_lines": len(horizontal_lines),
        "vertical_lines": len(vertical_lines),
        "total_lines": len(lines),
    }

    # Find the lowest horizontal line (likely the baseline)
    if horizontal_lines:
        # Sort by y position (lowest in image = highest y value)
        sorted_h = sorted(horizontal_lines, key=lambda l: (l[1] + l[3]) / 2, reverse=True)
        key_points["baseline"] = sorted_h[0]

    # Find vertical lines (sidelines)
    if vertical_lines:
        sorted_v = sorted(vertical_lines, key=lambda l: (l[0] + l[2]) / 2)
        key_points["left_sideline"] = sorted_v[0] if len(sorted_v) > 0 else None
        key_points["right_sideline"] = sorted_v[-1] if len(sorted_v) > 1 else None

    return key_points


def compute_homography(court_detection_result, target_court_width_ft=COURT_WIDTH_FT, target_court_length_ft=COURT_LENGTH_FT):
    """Compute homography matrix from detected court lines to real-world court coordinates.

    Maps pixel coordinates to court coordinates in feet, with origin at center court.

    Returns a dict with:
        - success: bool
        - homography: 3x3 numpy array (or None if failed)
        - court_bounds: dict with pixel coordinates of court boundaries
    """
    if not court_detection_result["success"]:
        return {"success": False, "homography": None}

    key_points = court_detection_result["key_points"]
    lines = court_detection_result["lines"]

    # Need at least 4 points to compute homography
    # Use court corners if available, otherwise estimate from lines
    src_points = []

    # Try to find court corners from line intersections
    if "baseline" in key_points and "left_sideline" in key_points and "right_sideline" in key_points:
        # Estimate corners from baseline and sidelines
        baseline = key_points["baseline"]
        left_side = key_points["left_sideline"]
        right_side = key_points["right_sideline"]

        # Simple estimation: use line endpoints
        src_points = [
            [baseline[0], baseline[1]],  # Left baseline
            [baseline[2], baseline[3]],  # Right baseline
            [left_side[0], left_side[1]],  # Left sideline top
            [right_side[0], right_side[1]],  # Right sideline top
        ]

    if len(src_points) < 4:
        return {"success": False, "homography": None}

    # Target points: standard court dimensions (feet)
    # Origin at center court, x along width, y along length
    dst_points = [
        [-target_court_width_ft / 2, 0],  # Left baseline
        [target_court_width_ft / 2, 0],   # Right baseline
        [-target_court_width_ft / 2, target_court_length_ft / 2],  # Left far end
        [target_court_width_ft / 2, target_court_length_ft / 2],   # Right far end
    ]

    src = np.array(src_points, dtype=np.float32)
    dst = np.array(dst_points, dtype=np.float32)

    H, mask = cv2.findHomography(src, dst)

    if H is None:
        return {"success": False, "homography": None}

    return {
        "success": True,
        "homography": H,
        "court_bounds": {
            "width_ft": target_court_width_ft,
            "length_ft": target_court_length_ft,
        }
    }


def pixel_to_court_coords(x, y, homography):
    """Transform pixel coordinates to court coordinates in feet.

    Returns (x_ft, y_ft) or None if homography is invalid.
    """
    if homography is None:
        return None

    pt = np.array([[[x, y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(pt, homography)

    return float(transformed[0][0][0]), float(transformed[0][0][1])


def is_three_point_shot(shot_x_ft, shot_y_ft, hoop_x_ft=0, hoop_y_ft=0):
    """Determine if a shot is a three-pointer based on court coordinates.

    Args:
        shot_x_ft: X coordinate of shot origin in feet (from center court)
        shot_y_ft: Y coordinate of shot origin in feet (from center court)
        hoop_x_ft: X coordinate of hoop in feet (default 0 = center)
        hoop_y_ft: Y coordinate of hoop in feet (default 0 = baseline)

    Returns:
        bool: True if the shot is beyond the three-point line
    """
    # Distance from hoop in feet
    dist_ft = np.sqrt((shot_x_ft - hoop_x_ft) ** 2 + (shot_y_ft - hoop_y_ft) ** 2)

    # NBA three-point line is 23.75 ft from hoop at top, 22 ft in corners
    # Use 22 ft as conservative threshold
    return dist_ft > THREE_POINT_LINE_CORNER_FT
