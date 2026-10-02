"""Preserve old stats while separating legacy global players by game.

Legacy records have no team information, so they start on the home roster.
Original players are retained; all game references point at scoped copies.
The caller runs this migration in one transaction.
"""
from sqlalchemy import text


def migrate_players(conn):
    conn.execute(text("ALTER TABLE players ADD COLUMN IF NOT EXISTS game_id UUID REFERENCES games(id)"))
    conn.execute(text("""
        CREATE TEMP TABLE player_scope_map ON COMMIT DROP AS
        SELECT DISTINCT refs.game_id, refs.player_id AS old_id, gen_random_uuid() AS new_id
        FROM (
            SELECT DISTINCT game_id, player_id FROM game_events WHERE player_id IS NOT NULL
            UNION
            SELECT DISTINCT f.game_id, d.player_id FROM detected_objects d
                JOIN frames f ON f.id = d.frame_id WHERE d.player_id IS NOT NULL
            UNION
            SELECT game_id, (event_details->>'shooter_player_id')::uuid FROM game_events
                WHERE event_details->>'shooter_player_id' IS NOT NULL
            UNION
            SELECT game_id, (event_details->>'rebounder_player_id')::uuid FROM game_events
                WHERE event_details->>'rebounder_player_id' IS NOT NULL
        ) refs JOIN players p ON p.id = refs.player_id WHERE p.game_id IS NULL
    """))
    conn.execute(text("""
        INSERT INTO players (id, game_id, team, jersey_number, player_name)
        SELECT m.new_id, m.game_id, 'home', p.jersey_number, p.player_name
        FROM player_scope_map m JOIN players p ON p.id = m.old_id
    """))
    conn.execute(text("""
        UPDATE game_events e SET player_id = m.new_id FROM player_scope_map m
        WHERE e.game_id = m.game_id AND e.player_id = m.old_id
    """))
    conn.execute(text("""
        UPDATE detected_objects d SET player_id = m.new_id
        FROM player_scope_map m, frames f
        WHERE d.frame_id = f.id AND f.game_id = m.game_id AND d.player_id = m.old_id
    """))
    for key in ("shooter_player_id", "rebounder_player_id"):
        conn.execute(text(f"""
            UPDATE game_events e SET event_details = jsonb_set(e.event_details, '{{{key}}}', to_jsonb(m.new_id::text))
            FROM player_scope_map m WHERE e.game_id = m.game_id AND e.event_details->>'{key}' = m.old_id::text
        """))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_player_game_team_jersey ON players(game_id, team, jersey_number)"))
