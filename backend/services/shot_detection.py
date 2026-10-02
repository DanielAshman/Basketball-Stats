"""Heuristic shot detection from ball-position detections.

There's no ground-truth basketball dataset here and no hoop-detection model
(see vision_service.py), so this is deliberately a simple, inspectable
proximity heuristic rather than a trained model: a "shot attempt" is a run of
frames where the tracked ball comes within a radius of the (manually marked)
hoop position, and "made" vs "missed" is guessed from where the ball ends up
relative to the hoop afterwards. This is good enough to demo, not to grade a
real game - see architecture_decisions.md's accuracy roadmap.

Made/missed uses the LAST ball sample within a short window after the
closest approach, not just the next one: on real footage (verified against
an actual rim-out), the ball's horizontal distance from the hoop increases
steadily frame over frame as it bounces away - a single next-frame check can
land on a point that hasn't diverged far yet and misclassify a miss as a
make. That window is bounded (MADE_OUTCOME_LOOKAHEAD_FRAMES below) rather
than searching all the way to the end of the ball-position list: an earlier,
unbounded version of this picked the ball's position at literally the last
frame of the whole video for every shot, however early in the game the shot
happened, which reliably classified every shot in a real test video as
"missed" regardless of what actually happened right after it. An earlier
version of this also tried interpolating the closest point along the segment
between two sampled positions (to catch approaches sparse 2fps sampling
missed entirely), but the segment's *far* endpoint could get pulled into the
"last position" used for made/missed - exactly the same class of bug.
Point-only detection with the radius below already catches every approach in
this project's test clips, so that interpolation was dropped rather than
fixed; a very fast, brief approach between two samples could still be missed.
"""

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


def _distance(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def detect_shots(ball_positions, hoop_x, hoop_y, frame_width):
    """ball_positions: list of dicts with frame_number, timestamp_seconds, x, y
    (center of the highest-confidence sports_ball detection in that frame),
    sorted by frame_number. Returns a list of shot-event dicts."""
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
            # Ball not seen again after the closest approach (e.g. it left
            # frame, or is occluded by the net). Default to "missed" rather
            # than assume a make with no supporting evidence.
            made = False
            end_point = closest

        confidence = max(0.0, 1 - closest["distance"] / radius)

        events.append({
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
        })

    return events
