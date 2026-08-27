"""Shared helper: which detected person (if any) is nearest a ball position,
within a given pixel radius. Used to attribute a shot to its shooter and a
rebound to its rebounder (see rebound_detection.py and main.py's
analyze_game). This only finds which existing person *detection* is
closest - it never assigns a player. A shot/rebound only becomes attributed
to a specific player if a coach has already manually tagged that exact
detection via the frame viewer (see PlayerTagForm.jsx); most won't be.
"""

PROXIMITY_FRACTION = 0.15
MIN_PROXIMITY_PX = 60


def proximity_radius(frame_width):
    return max(frame_width * PROXIMITY_FRACTION, MIN_PROXIMITY_PX)


def closest_person_to_ball(persons, ball_x, ball_y, radius):
    """persons: list of dicts with at least x, y (center coordinates).
    Returns the closest one within radius, or None."""
    if not persons:
        return None

    def distance(p):
        return ((p["x"] - ball_x) ** 2 + (p["y"] - ball_y) ** 2) ** 0.5

    closest = min(persons, key=distance)
    return closest if distance(closest) <= radius else None


# How many frames of gap in ball tracking is still "recent enough" to trust
# as a stand-in for the shooter's actual release position.
MAX_SHOOTER_LOOKBACK_GAP = 4


def find_shooter_reference_point(ball_positions, before_frame):
    """A shot's tracked approach to the hoop starts once the ball is already
    near the rim - by then the shooter who released it is normally long gone
    from that spot, so checking who's near the ball *there* almost always
    finds nobody relevant. This looks for the most recent ball position
    strictly before the approach began instead, which is far more likely to
    still be near the shooter. Returns None if tracking is too sparse
    (nothing within MAX_SHOOTER_LOOKBACK_GAP frames) to trust as a proxy."""
    earlier = [p for p in ball_positions if p["frame_number"] < before_frame]
    if not earlier:
        return None
    latest = max(earlier, key=lambda p: p["frame_number"])
    if before_frame - latest["frame_number"] > MAX_SHOOTER_LOOKBACK_GAP:
        return None
    return latest
