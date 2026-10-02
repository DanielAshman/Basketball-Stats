"""Run with DATABASE_URL pointing at a disposable PostgreSQL test database."""
import asyncio
import os
import unittest
from datetime import date

from sqlalchemy.orm import Session

if not os.environ.get("DATABASE_URL", "").endswith("/basketball_regression_tests"):
    raise RuntimeError("Run these tests against the separate basketball_regression_tests database")

import main
from database import engine
from models import DetectedObject, Frame, Game, GameEvent, Player
from services.player_migration import migrate_players


class ManualEntryTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.game = Game(title="Regression", date_played=date.today(), entry_mode="manual", processing_status="completed")
        self.other = Game(title="Other", date_played=date.today(), entry_mode="manual", processing_status="completed")
        self.db.add_all([self.game, self.other])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def player(self, game, team="home", name="Alex"):
        return asyncio.run(main.create_or_find_player(main.PlayerInput(
            game_id=game.id, team=team, jersey_number=23, player_name=name
        ), self.db))

    def test_same_jersey_is_separate_across_teams_and_games(self):
        home = self.player(self.game)
        away = self.player(self.game, "away", "Sam")
        other = self.player(self.other)
        self.assertEqual(3, len({home["id"], away["id"], other["id"]}))
        self.assertEqual(home["id"], self.player(self.game)["id"])

    def test_resume_returns_player_id_and_all_roster_players(self):
        home = self.player(self.game)
        away = self.player(self.game, "away", "Sam")
        event = asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
            player_id=home["id"], event_type="shot", made=True
        ), self.db))
        events = asyncio.run(main.list_manual_events(self.game.id, self.db))["events"]
        self.assertEqual(home["id"], events[0].get("player_id"))
        roster = asyncio.run(main.list_game_players(self.game.id, self.db))["players"]
        self.assertEqual({home["id"], away["id"]}, {p["id"] for p in roster})
        asyncio.run(main.delete_manual_event(self.game.id, event["id"], self.db))
        stats = asyncio.run(main.get_player_stats(self.game.id, self.db))["players"]
        self.assertEqual([], stats)
        self.assertEqual(0, self.game.total_shots)

    def test_other_games_player_cannot_receive_stats(self):
        player = self.player(self.other)
        with self.assertRaises(main.HTTPException) as error:
            asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
                player_id=player["id"], event_type="rebound"
            ), self.db))
        self.assertEqual(400, error.exception.status_code)

    def test_point_values_are_counted_and_undo_reverses_their_total(self):
        player = self.player(self.game)
        one = asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
            player_id=player["id"], event_type="shot", made=True, points=1
        ), self.db))
        two = asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
            player_id=player["id"], event_type="shot", made=True, points=2
        ), self.db))
        three = asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
            player_id=player["id"], event_type="shot", made=True, points=3
        ), self.db))
        asyncio.run(main.record_manual_event(self.game.id, main.ManualEventInput(
            player_id=player["id"], event_type="shot", made=False
        ), self.db))

        stats = asyncio.run(main.get_player_stats(self.game.id, self.db))["players"][0]
        self.assertEqual(1, stats["one_pointers_made"])
        self.assertEqual(1, stats["two_pointers_made"])
        self.assertEqual(1, stats["three_pointers_made"])
        self.assertEqual(6, stats["points"])
        self.assertEqual(3, stats["shots_made"])
        self.assertEqual(4, stats["shots_attempted"])

        asyncio.run(main.delete_manual_event(self.game.id, three["id"], self.db))
        stats = asyncio.run(main.get_player_stats(self.game.id, self.db))["players"][0]
        self.assertEqual(0, stats["three_pointers_made"])
        self.assertEqual(3, stats["points"])
        self.assertEqual(2, stats["shots_made"])
        self.assertEqual(3, stats["shots_attempted"])
        self.assertEqual(3, self.game.total_points)
        self.assertEqual(2, self.game.made_shots)

        # Existing made events had no point value. They remain two-pointers.
        legacy = GameEvent(game_id=self.game.id, event_type="shot", player_id=player["id"], event_details={"made": True})
        self.db.add(legacy)
        self.db.commit()
        stats = asyncio.run(main.get_player_stats(self.game.id, self.db))["players"][0]
        self.assertEqual(2, stats["two_pointers_made"])
        self.assertEqual(5, stats["points"])

    def test_legacy_migration_preserves_manual_and_video_stats_and_is_repeatable(self):
        old = Player(jersey_number=12, player_name="Legacy")
        self.db.add(old)
        self.db.flush()
        frame = Frame(game_id=self.other.id, frame_number=0)
        self.db.add(frame)
        self.db.flush()
        detection = DetectedObject(frame_id=frame.id, object_type="person", player_id=old.id)
        manual = GameEvent(game_id=self.game.id, event_type="assist", player_id=old.id)
        video = GameEvent(game_id=self.other.id, event_type="shot", event_details={"made": True, "shooter_player_id": str(old.id)})
        self.db.add_all([detection, manual, video])
        self.db.flush()
        migrate_players(self.connection)
        self.db.expire_all()
        self.assertNotEqual(manual.player_id, detection.player_id)
        self.assertEqual(str(detection.player_id), video.event_details["shooter_player_id"])
        self.assertEqual(1, asyncio.run(main.get_player_stats(self.game.id, self.db))["players"][0]["assists"])
        self.assertEqual(1, asyncio.run(main.get_player_stats(self.other.id, self.db))["players"][0]["shots_made"])
        self.assertEqual("home", self.db.get(Player, manual.player_id).team)
        original_ids = (manual.player_id, detection.player_id)
        # The migration's temporary table normally disappears at transaction commit.
        self.connection.exec_driver_sql("DROP TABLE player_scope_map")
        migrate_players(self.connection)
        self.db.expire_all()
        self.assertEqual(original_ids, (manual.player_id, detection.player_id))
