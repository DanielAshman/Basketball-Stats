"""Heuristic rebound detection: which person (if any) ends up near the loose
ball shortly after a missed shot.

Scope: this identifies *that* someone rebounded and roughly *where*, and
which specific person *detection* was closest - not which player, unless a
coach has already manually tagged that exact detection (see
player_attribution.py and PlayerTagForm.jsx). Most rebounds won't have a
tagged detection at the right frame, and that's expected.
"""

from services.player_attribution import closest_person_to_ball, proximity_radius

# How many frames after the shot's closest approach to search for someone
# converging on the loose ball.
LOOKAHEAD_FRAMES = 6


def _distance(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def detect_rebounds(missed_shots, frames_by_number, frame_width):
    """missed_shots: shot event dicts with event_details.made == False and
    event_details.closest_frame set.
    frames_by_number: dict of frame_number -> {"timestamp_seconds": float,
    "persons": [{"id","x","y","player_id"}...], "balls": [{"x","y"}...]}.
    Returns a list of rebound event dicts, at most one per missed shot."""
    radius = proximity_radius(frame_width)

    events = []
    for shot in missed_shots:
        anchor_frame = shot["event_details"]["closest_frame"]

        candidates = []
        for fn in range(anchor_frame + 1, anchor_frame + LOOKAHEAD_FRAMES + 1):
            frame = frames_by_number.get(fn)
            if not frame or not frame["persons"] or not frame["balls"]:
                continue

            ball = frame["balls"][0]
            person = closest_person_to_ball(frame["persons"], ball["x"], ball["y"], radius)
            if person is not None:
                dist = _distance(person["x"], person["y"], ball["x"], ball["y"])
                candidates.append((fn, frame, ball, person, dist))

        if not candidates:
            continue

        # Report the closest convergence in the window, not just the first
        # frame that happened to qualify - a player can be near the radius
        # boundary for a frame or two before actually closing in on the ball.
        fn, frame, ball, person, dist = min(candidates, key=lambda c: c[4])

        events.append({
            "event_type": "rebound",
            "start_frame": fn,
            "end_frame": fn,
            "start_timestamp": frame["timestamp_seconds"],
            "end_timestamp": frame["timestamp_seconds"],
            "confidence_score": round(max(0.0, 1 - dist / radius), 3),
            "event_details": {
                "position_x": ball["x"],
                "position_y": ball["y"],
                "person_distance_px": round(dist, 1),
                "missed_shot_frame": anchor_frame,
                "rebounder_detection_id": person["id"],
                "rebounder_player_id": person.get("player_id"),
            },
        })

    return events
