"""Heuristic shot detection from ball-position detections.

There's no ground-truth basketball dataset here and no hoop-detection model
(see vision_service.py), so this is deliberately a simple, inspectable
proximity heuristic rather than a trained model: a "shot attempt" is a run of
frames where the tracked ball's path comes within a radius of the (manually
marked) hoop position, and "made" vs "missed" is guessed from where the ball
ends up relative to the hoop afterwards. This is good enough to demo, not to
grade a real game - see architecture_decisions.md's accuracy roadmap.

Frames are sampled at 2fps (see frame_extraction.py), so the ball's actual
closest approach to the hoop usually falls *between* two sampled points, not
on one. Checking distance from the hoop to the line *segment* joining each
consecutive pair of ball positions - not just the sampled points themselves -
catches that case; point-only checks miss most real approaches at this
sample rate.
"""

# How close (as a fraction of frame width) the ball's path needs to get to
# the hoop to count as a shot attempt.
PROXIMITY_FRACTION = 0.12
MIN_PROXIMITY_PX = 45

# A shot attempt run tolerates the ball detection dropping out for up to this
# many consecutive sampled frames (e.g. motion blur, occlusion) without
# ending the cluster.
MAX_FRAME_GAP = 3


def _distance(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def _point_segment_distance(px, py, x1, y1, x2, y2):
    """Distance from (px, py) to the segment (x1,y1)-(x2,y2), and the
    fraction t along the segment where the closest point falls."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return _distance(px, py, x1, y1), 0.0

    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest_x, closest_y = x1 + t * dx, y1 + t * dy
    return _distance(px, py, closest_x, closest_y), t


def detect_shots(ball_positions, hoop_x, hoop_y, frame_width):
    """ball_positions: list of dicts with frame_number, timestamp_seconds, x, y
    (center of the highest-confidence sports_ball detection in that frame),
    sorted by frame_number. Returns a list of shot-event dicts."""
    if len(ball_positions) < 2:
        return []

    radius = max(frame_width * PROXIMITY_FRACTION, MIN_PROXIMITY_PX)

    near_segments = []
    for prev, curr in zip(ball_positions, ball_positions[1:]):
        if curr["frame_number"] - prev["frame_number"] > MAX_FRAME_GAP:
            continue
        dist, t = _point_segment_distance(hoop_x, hoop_y, prev["x"], prev["y"], curr["x"], curr["y"])
        if dist <= radius:
            near_segments.append({"prev": prev, "curr": curr, "distance": dist, "t": t})

    if not near_segments:
        return []

    clusters = []
    current = [near_segments[0]]
    for seg in near_segments[1:]:
        if seg["prev"]["frame_number"] - current[-1]["curr"]["frame_number"] <= MAX_FRAME_GAP:
            current.append(seg)
        else:
            clusters.append(current)
            current = [seg]
    clusters.append(current)

    events = []
    for cluster in clusters:
        closest = min(cluster, key=lambda s: s["distance"])
        start_point = cluster[0]["prev"]
        last_point = cluster[-1]["curr"]

        horizontal_offset = abs(last_point["x"] - hoop_x)
        made = last_point["y"] > hoop_y and horizontal_offset <= radius * 0.75

        confidence = max(0.0, 1 - closest["distance"] / radius)

        events.append({
            "event_type": "shot",
            "start_frame": start_point["frame_number"],
            "end_frame": last_point["frame_number"],
            "start_timestamp": start_point["timestamp_seconds"],
            "end_timestamp": last_point["timestamp_seconds"],
            "confidence_score": round(confidence, 3),
            "event_details": {
                "made": made,
                "closest_distance_px": round(closest["distance"], 1),
                "hoop_x": hoop_x,
                "hoop_y": hoop_y,
            },
        })

    return events
