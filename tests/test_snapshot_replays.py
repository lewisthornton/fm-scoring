"""Invented import replay and legacy-schema migration regressions."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from test_rangers_integration import watcher, bridge


DATE = "2027-01-01"
CAREER = "replay-fixture"


def player(uid, pace, club="100"):
    return {"uid": uid, "unique_id": uid, "name": "Invented " + uid, "birth_date": "2000-01-01",
            "age": "27", "club_uid": club, "club_name": "Rangers" if club == "100" else "Invented FC",
            "attributes_pace": str(pace)}


def ingest(db, save, selection, squad, target=None, date=DATE):
    rows = {watcher.identity(squad): squad}
    membership = {watcher.identity(squad): {"squad"}}
    if target:
        rows[watcher.identity(target)] = target
        membership[watcher.identity(target)] = {"target"}
    return watcher.import_selection(db, CAREER, Path("invented.fm"), save, selection,
                                    {"game_date": date}, rows, membership, Path(selection + ".csv"), ("100", "800"))


def latest_pace(db, p):
    record = db.execute("""SELECT v.record_json FROM player_latest l JOIN player_versions v
        ON v.snapshot_id=l.snapshot_id AND v.player_key=l.player_key AND v.career=l.career
        WHERE l.career=? AND l.player_key=?""", (CAREER, watcher.identity(p))).fetchone()
    return json.loads(record[0])["attributes_pace"]


def active_targets(db):
    return {r[0] for r in db.execute("SELECT player_key FROM cohort_membership WHERE career=? AND cohort='target' AND active=1", (CAREER,))}


def history(db):
    return db.execute("SELECT * FROM snapshots ORDER BY id").fetchall(), db.execute("SELECT * FROM player_versions ORDER BY snapshot_id,player_key").fetchall()


def old_schema():
    return watcher.SCHEMA.replace("changed_count INTEGER NOT NULL\n)", "changed_count INTEGER NOT NULL,\n    UNIQUE(career,source_sha256,selection_sha256)\n)").replace(
        "CREATE INDEX IF NOT EXISTS ix_snapshots_pair ON snapshots(career,source_sha256,selection_sha256);", "")


class SnapshotReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "invented.sqlite3"
        self.a = player("1", 10)
        self.b = player("1", 15)
        self.target_a = player("2", 12, "200")
        self.target_b = player("3", 13, "300")

    def connect(self):
        db = watcher.connect(self.path)
        self.addCleanup(db.close)
        return db

    def test_first_exact_repeat_and_replay(self):
        db = self.connect()
        self.assertEqual(ingest(db, "A", "filter-a", self.a, self.target_a), (2, 2))
        before = list(db.iterdump())
        self.assertEqual(ingest(db, "A", "filter-a", self.a, self.target_a), (2, 0))
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(ingest(db, "B", "filter-b", self.b, self.target_b), (2, 2))
        original = history(db)
        self.assertEqual(ingest(db, "A", "filter-a", self.a, self.target_a), (2, 1))
        snapshots, versions = history(db)
        self.assertEqual(snapshots[:2], original[0])
        self.assertEqual(versions[:4], original[1])
        self.assertEqual([r[3:5] for r in snapshots], [("A", "filter-a"), ("B", "filter-b"), ("A", "filter-a")])
        self.assertEqual(latest_pace(db, self.a), "10")
        self.assertEqual(active_targets(db), {watcher.identity(self.target_a)})
        people, date, _ = bridge.get_database(self.path, CAREER)
        self.assertEqual(date, DATE)
        self.assertEqual({p["raw"]["uid"]: p["raw"]["attributes_pace"] for p in people}, {"1": "10", "2": "12"})
        self.assertEqual(db.execute("SELECT snapshot_id FROM player_latest WHERE career=? AND player_key=?", (CAREER, watcher.identity(self.a))).fetchone()[0], snapshots[-1][0])
        self.assertEqual(ingest(db, "A", "filter-a", self.a, self.target_a), (2, 0))
        self.assertEqual(history(db), (snapshots, versions))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_same_save_filter_reactivation_and_older_save_guard(self):
        db = self.connect()
        ingest(db, "A", "filter-a", self.a, self.target_a)
        ingest(db, "A", "filter-b", self.a, self.target_b)
        original = history(db)
        self.assertEqual(ingest(db, "A", "filter-a", self.a, self.target_a), (2, 0))
        self.assertEqual(history(db), original)
        self.assertEqual(active_targets(db), {watcher.identity(self.target_a)})
        self.assertEqual(ingest(db, "A", "empty-filter", self.a, None), (1, 0))
        self.assertEqual(active_targets(db), set())
        ingest(db, "C", "filter-b", self.b, self.target_b, "2027-01-02")
        before = list(db.iterdump())
        self.assertIsNone(ingest(db, "A", "filter-a", self.a, self.target_a))
        self.assertEqual(list(db.iterdump()), before)

    def test_sparse_legacy_migration_preserves_rows_ids_indexes_and_triggers(self):
        db = sqlite3.connect(self.path)
        with db:
            db.executescript(old_schema())
            ingest(db, "A", "filter-a", self.a, self.target_a)
            ingest(db, "B", "filter-b", self.b, self.target_b)
            db.execute("CREATE INDEX fixture_snapshot_index ON snapshots(game_build)")
            db.execute("CREATE TRIGGER fixture_snapshot_trigger AFTER INSERT ON snapshots BEGIN SELECT 1; END")
        original = history(db)
        pointers = db.execute("SELECT * FROM player_latest ORDER BY player_key").fetchall()
        db.close()
        migrated = self.connect()
        self.assertEqual(history(migrated), original)
        self.assertEqual(migrated.execute("SELECT * FROM player_latest ORDER BY player_key").fetchall(), pointers)
        self.assertEqual(migrated.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(migrated.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual({r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE name LIKE 'fixture_snapshot_%'")}, {"fixture_snapshot_index", "fixture_snapshot_trigger"})
        self.assertEqual(ingest(migrated, "A", "filter-a", self.a, self.target_a), (2, 1))
        after = history(migrated)
        reopened = self.connect()
        self.assertEqual(history(reopened), after)
        self.assertEqual(latest_pace(reopened, self.a), "10")

    def test_replay_failure_rolls_back_snapshot_latest_membership_and_watermark(self):
        db = self.connect()
        ingest(db, "A", "filter-a", self.a, self.target_a)
        ingest(db, "B", "filter-b", self.b, self.target_b)
        db.execute("CREATE TRIGGER fail_replay BEFORE UPDATE ON career_chronology BEGIN SELECT RAISE(ABORT, 'invented replay failure'); END")
        before = list(db.iterdump())
        with self.assertRaisesRegex(sqlite3.IntegrityError, "invented replay failure"):
            ingest(db, "A", "filter-a", self.a, self.target_a)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(latest_pace(db, self.a), "15")
        self.assertEqual(active_targets(db), {watcher.identity(self.target_b)})

    def test_concurrent_replay_appends_one_revision(self):
        db = self.connect()
        ingest(db, "A", "filter-a", self.a, self.target_a)
        ingest(db, "B", "filter-b", self.b, self.target_b)
        barrier = threading.Barrier(2)
        def replay():
            conn = watcher.connect(self.path)
            try:
                barrier.wait(timeout=10)
                return ingest(conn, "A", "filter-a", self.a, self.target_a)
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(replay) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [(2, 0), (2, 1)])
        self.assertEqual(len(history(db)[0]), 3)
        self.assertEqual(active_targets(db), {watcher.identity(self.target_a)})
        self.assertEqual(latest_pace(db, self.a), "10")

    def test_concurrent_legacy_open_and_replay(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(old_schema())
        ingest(db, "A", "filter-a", self.a, self.target_a)
        ingest(db, "B", "filter-b", self.b, self.target_b)
        original = history(db)
        db.close()
        barrier = threading.Barrier(2)
        def replay():
            barrier.wait(timeout=10)
            conn = watcher.connect(self.path)
            try:
                return ingest(conn, "A", "filter-a", self.a, self.target_a)
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(replay) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [(2, 0), (2, 1)])
        reopened = self.connect()
        snapshots, versions = history(reopened)
        self.assertEqual(snapshots[:2], original[0])
        self.assertEqual(versions[:4], original[1])
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(reopened.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_failure_reverts_legacy_table(self):
        db = sqlite3.connect(self.path)
        db.executescript(old_schema())
        ingest(db, "A", "filter-a", self.a)
        # Simulate a pre-existing unrelated foreign-key violation in a legacy DB.
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("UPDATE player_latest SET snapshot_id=999")
        db.commit()
        db.execute("PRAGMA foreign_keys=ON")
        before = list(db.iterdump())
        with self.assertRaisesRegex(sqlite3.IntegrityError, "foreign-key validation"):
            watcher.migrate_snapshot_pairs(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
