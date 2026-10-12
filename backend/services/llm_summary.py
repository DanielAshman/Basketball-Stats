import hashlib
import json
import os
import uuid
from urllib import error, request

from sqlalchemy.orm import Session

from models import Game, GameEvent, GameReviewExplanation, GameSummaryRun, Player

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
    headline = data.get("headline")
    summary = data.get("summary")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("LLM summary headline was missing or invalid")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("LLM summary text was missing or invalid")
    if len(headline.strip()) > 255 or len(summary.strip()) > 2000:
        raise ValueError("LLM summary text exceeded the supported length")

    key_performers = data.get("key_performers", [])
    caveats = data.get("data_quality_caveats", [])
    if (
        not isinstance(key_performers, list)
        or len(key_performers) > 3
        or not isinstance(caveats, list)
        or len(caveats) > 10
    ):
        raise ValueError("LLM summary lists were invalid")
    cleaned = {
        "headline": headline.strip(),
        "summary": summary.strip(),
        "key_performers": key_performers,
        "data_quality_caveats": caveats,
    }
    for performer in cleaned["key_performers"]:
        if (
            not isinstance(performer, dict)
            or not isinstance(performer.get("player_id"), str)
            or not isinstance(performer.get("observation"), str)
            or not performer["observation"].strip()
            or len(performer["observation"]) > 500
        ):
            raise ValueError("LLM key performer was invalid")
    if any(not isinstance(caveat, str) or len(caveat) > 500 for caveat in cleaned["data_quality_caveats"]):
        raise ValueError("LLM data quality caveat was invalid")
    return cleaned


def _parse_model_json(response_data):
    if not isinstance(response_data, dict):
        raise ValueError("Ollama response was not a JSON object")
    text = response_data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Ollama response text was empty")

    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace == -1 or last_brace <= first_brace:
            raise
        return json.loads(text[first_brace:last_brace + 1])


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

    try:
        parsed = _parse_model_json(response_data)
        result = _normalise_summary_result(parsed)
        player_ids = {player["player_id"] for player in payload.get("player_totals", [])}
        if any(performer["player_id"] not in player_ids for performer in result["key_performers"]):
            return _fallback_summary(payload)
        return result
    except (ValueError, TypeError):
        return _fallback_summary(payload)


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


def build_review_explanation_payload(game: Game, db: Session, event_id=None):
    events = (
        db.query(GameEvent)
        .filter(GameEvent.game_id == game.id)
        .order_by(GameEvent.start_frame.desc().nullslast(), GameEvent.created_at.desc())
        .all()
    )
    target_event = None
    if event_id is not None:
        target_event = next((event for event in events if str(event.id) == str(event_id)), None)
        if target_event is None:
            raise ValueError("Event not found for this game")
    elif events:
        target_event = events[0]

    context_events = list(events)
    if target_event is not None:
        context_events = [target_event, *(event for event in events if event.id != target_event.id)]
    event_payload = []
    for event in context_events[:5]:
        event_payload.append({
            "event_id": str(event.id),
            "event_type": event.event_type,
            "confidence_score": float(event.confidence_score) if event.confidence_score is not None else None,
            "start_frame": event.start_frame,
            "end_frame": event.end_frame,
            "event_details": event.event_details,
        })
    insight = {
        "game_id": str(game.id),
        "game_title": game.title,
        "event_id": str(target_event.id) if target_event else None,
        "event_type": target_event.event_type if target_event else None,
        "confidence_score": float(target_event.confidence_score) if target_event and target_event.confidence_score is not None else None,
        "recent_events": event_payload,
        "official_totals": {
            "points": int(game.total_points or 0),
            "shots": int(game.total_shots or 0),
            "made_shots": int(game.made_shots or 0),
            "rebounds": int(game.total_rebounds or 0),
            "turnovers": int(game.total_turnovers or 0),
            "assists": int(game.total_assists or 0),
        },
        "questions": [
            "Explain why this event is relevant to the game narrative.",
            "Focus on the source data and the exact event details.",
            "Do not invent any missing facts.",
        ],
    }
    return insight


def _call_ollama_for_review(payload):
    url = f"{OLLAMA_BASE_URL}/api/generate"
    prompt = (
        "You are a basketball review assistant. Use only the structured evidence in the JSON payload. "
        "Return valid JSON only with keys: headline, explanation, relevant_event_ids. "
        "Do not invent absent players, scores, or actions. Keep the explanation factual and brief."
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
        return _fallback_review_explanation(payload, "The local model was unavailable.")

    try:
        parsed = _parse_model_json(response_data)
        if not isinstance(parsed, dict):
            raise ValueError("LLM review response was not a JSON object")
        headline = parsed.get("headline")
        explanation = parsed.get("explanation")
        relevant_event_ids = parsed.get("relevant_event_ids")
        allowed_event_ids = {item["event_id"] for item in payload.get("recent_events", [])}
        if (
            not isinstance(headline, str)
            or not headline.strip()
            or len(headline.strip()) > 255
            or not isinstance(explanation, str)
            or not explanation.strip()
            or len(explanation.strip()) > 2000
            or not isinstance(relevant_event_ids, list)
            or len(relevant_event_ids) > 3
            or any(not isinstance(event_id, str) or event_id not in allowed_event_ids for event_id in relevant_event_ids)
        ):
            raise ValueError("LLM review response did not match the source evidence")
        target_event_id = payload.get("event_id")
        if target_event_id and target_event_id not in relevant_event_ids:
            relevant_event_ids.insert(0, target_event_id)
        return {
            "headline": headline.strip(),
            "explanation": explanation.strip(),
            "relevant_event_ids": list(dict.fromkeys(relevant_event_ids))[:3],
        }
    except (ValueError, TypeError):
        return _fallback_review_explanation(payload, "The model output was invalid or referenced events outside the source evidence.")


def _fallback_review_explanation(payload, reason):
    event_ids = [item["event_id"] for item in payload.get("recent_events", []) if item.get("event_id")]
    if not event_ids:
        return {
            "headline": "No events to review",
            "explanation": "There are no accepted event records for this game yet.",
            "relevant_event_ids": [],
        }
    return {
        "headline": "Review explanation",
        "explanation": (
            f"{reason} This explanation is limited to the available source event record; "
            "the official game data remains unchanged."
        ),
        "relevant_event_ids": event_ids[:3],
    }


def generate_game_review_explanation(db: Session, game: Game, event_id=None):
    payload = build_review_explanation_payload(game, db, event_id)
    result = _call_ollama_for_review(payload)
    prompt_hash = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()
    event_uuid = uuid.UUID(payload["event_id"]) if payload.get("event_id") else None
    record = GameReviewExplanation(
        game_id=game.id,
        event_id=event_uuid,
        headline=result.get("headline"),
        explanation=result.get("explanation"),
        relevant_event_ids=result.get("relevant_event_ids"),
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
        "explanation": result.get("explanation"),
        "relevant_event_ids": result.get("relevant_event_ids", []),
        "record_id": str(record.id),
    }
