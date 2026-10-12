import hashlib
import json
import os
from urllib import error, request

from sqlalchemy.orm import Session

from models import Game, GameEvent, GameSummaryRun, Player

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-4b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))


def _build_top_performers(player_totals):
    top_players = sorted(
        player_totals,
        key=lambda item: (item.get("points", 0), item.get("rebounds", 0), item.get("assists", 0)),
        reverse=True,
    )[:3]
    performers = []
    for item in top_players:
        title = item.get("player_name") or "Player"
        performers.append({
            "player_id": item.get("player_id"),
            "observation": f"{title} recorded {item.get('points', 0)} points, {item.get('rebounds', 0)} rebounds and {item.get('assists', 0)} assists.",
        })
    return performers


def _normalise_summary_result(data):
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    cleaned = {
        "headline": str(data.get("headline") or "Game Summary"),
        "summary": str(data.get("summary") or "Official game data was available but no narrative summary was generated."),
        "key_performers": data.get("key_performers") or [],
        "data_quality_caveats": data.get("data_quality_caveats") or [],
    }
    if not isinstance(cleaned["key_performers"], list):
        cleaned["key_performers"] = []
    if not isinstance(cleaned["data_quality_caveats"], list):
        cleaned["data_quality_caveats"] = []
    return cleaned


def build_game_summary_payload(game: Game, db: Session):
    player_rows = db.query(Player).filter(Player.game_id == game.id).all()
    player_lookup = {str(player.id): player for player in player_rows}
    events = db.query(GameEvent).filter(GameEvent.game_id == game.id).all()

    stats = {}
    for event in events:
        direct_ids = []
        if event.player_id is not None:
            direct_ids.append(str(event.player_id))
        details = event.event_details or {}
        for key in [
            "shooter_player_id",
            "rebounder_player_id",
            "assister_player_id",
            "turnover_player_id",
            "scorer_player_id",
        ]:
            value = details.get(key)
            if value is not None:
                direct_ids.append(str(value))

        for player_id in set(direct_ids):
            entry = stats.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "player_name": player_lookup.get(player_id, Player()).player_name if player_id in player_lookup else "Unknown",
                    "team": player_lookup.get(player_id, Player()).team if player_id in player_lookup else None,
                    "points": 0,
                    "rebounds": 0,
                    "assists": 0,
                    "turnovers": 0,
                    "shots_attempted": 0,
                    "shots_made": 0,
                },
            )

            if event.event_type == "shot":
                entry["shots_attempted"] += 1
                if details.get("made"):
                    entry["shots_made"] += 1
                    entry["points"] += int(details.get("points") or 2)
            elif event.event_type == "rebound":
                entry["rebounds"] += 1
            elif event.event_type == "assist":
                entry["assists"] += 1
            elif event.event_type == "turnover":
                entry["turnovers"] += 1

    player_totals = []
    for _, item in sorted(stats.items()):
        player_totals.append(item)

    payload = {
        "game_id": str(game.id),
        "game_title": game.title,
        "date_played": str(game.date_played),
        "home_team": game.home_team,
        "away_team": game.away_team,
        "official_totals": {
            "points": int(game.total_points or 0),
            "shots": int(game.total_shots or 0),
            "made_shots": int(game.made_shots or 0),
            "rebounds": int(game.total_rebounds or 0),
            "turnovers": int(game.total_turnovers or 0),
            "assists": int(game.total_assists or 0),
        },
        "player_totals": player_totals,
        "accepted_event_count": len(events),
        "unresolved_event_count": 0,
        "data_quality_notes": [
            "Official totals were generated from the deterministic game pipeline.",
            "This summary is generated only after the official event data is available.",
        ],
    }
    return payload


def _fallback_summary(payload):
    total_points = payload["official_totals"].get("points", 0)
    home_team = payload.get("home_team") or "Home"
    away_team = payload.get("away_team") or "Away"
    top_players = _build_top_performers(payload.get("player_totals", []))

    headline = f"{home_team} vs {away_team} game summary"
    summary = (
        f"{home_team} and {away_team} were recorded with {total_points} total points across the official game stats. "
        f"This is a validated summary generated from the deterministic game pipeline and should be treated as descriptive rather than authoritative."
    )
    return {
        "headline": headline,
        "summary": summary,
        "key_performers": top_players,
        "data_quality_caveats": [
            "Fallback summary generated because the local LLM service is unavailable.",
            "Official stats remain the source of truth.",
        ],
    }


def _call_ollama(payload):
    url = f"{OLLAMA_BASE_URL}/api/generate"
    prompt = (
        "You are a basketball analytics summarizer. Use only the JSON in this request. "
        "Return valid JSON only with keys: headline, summary, key_performers, data_quality_caveats. "
        "Do not invent values. Keep the summary factual and concise."
    )
    request_body = {
        "model": OLLAMA_MODEL,
        "prompt": f"{prompt}\n\n{json.dumps(payload, separators=(',', ':'))}",
        "stream": False,
        "options": {"temperature": 0.0},
    }

    payload_bytes = json.dumps(request_body).encode("utf-8")
    request_obj = request.Request(url, data=payload_bytes, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(request_obj, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (ValueError, error.URLError, TimeoutError, OSError):
        return _fallback_summary(payload)

    text = response_data.get("response") or ""
    if not isinstance(text, str) or not text.strip():
        return _fallback_summary(payload)

    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
            return _fallback_summary(payload)
        try:
            parsed = json.loads(text[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            return _fallback_summary(payload)

    return _normalise_summary_result(parsed)


def generate_game_summary(db: Session, game: Game):
    payload = build_game_summary_payload(game, db)
    result = _call_ollama(payload)

    prompt_hash = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()
    record = GameSummaryRun(
        game_id=game.id,
        headline=result.get("headline"),
        summary=result.get("summary"),
        key_performers=result.get("key_performers"),
        data_quality_caveats=result.get("data_quality_caveats"),
        model_name=OLLAMA_MODEL,
        model_version="local",
        schema_version="1.0",
        prompt_hash=prompt_hash,
        input_snapshot=payload,
        output_snapshot=result,
        status="completed",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "headline": result.get("headline"),
        "summary": result.get("summary"),
        "key_performers": result.get("key_performers", []),
        "data_quality_caveats": result.get("data_quality_caveats", []),
        "record_id": str(record.id),
    }
