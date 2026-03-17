"""SQLite-based challenge database for Mission Control."""
import json
import logging
import sqlite3
import uuid
from pathlib import Path

from challenges import Challenge, Difficulty, PreSetup, Target

logger = logging.getLogger("mission_control.challenge_db")


class ChallengeDB:
    def __init__(self, path: str = "/app/data/challenges.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Create tables and seed defaults if needed."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS challenges (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    announcement TEXT NOT NULL,
                    hint TEXT NOT NULL,
                    success_message TEXT NOT NULL,
                    targets TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    announce_speaker TEXT NOT NULL,
                    success_speaker TEXT NOT NULL,
                    room TEXT NOT NULL,
                    pre_setup TEXT NOT NULL DEFAULT '[]',
                    multi_target INTEGER NOT NULL DEFAULT 0,
                    funny_announcements TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'generated',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS blacklist (
                    entity_id TEXT PRIMARY KEY
                );
            """)

            # Migration: add floor column if missing
            try:
                conn.execute("ALTER TABLE challenges ADD COLUMN floor TEXT NOT NULL DEFAULT ''")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

            conn.commit()
        finally:
            conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a challenge dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "announcement": row["announcement"],
            "hint": row["hint"],
            "success_message": row["success_message"],
            "targets": json.loads(row["targets"]),
            "difficulty": row["difficulty"],
            "announce_speaker": row["announce_speaker"],
            "success_speaker": row["success_speaker"],
            "room": row["room"],
            "pre_setup": json.loads(row["pre_setup"]),
            "multi_target": bool(row["multi_target"]),
            "funny_announcements": json.loads(row["funny_announcements"]),
            "source": row["source"],
            "floor": row["floor"],
        }

    def load(self) -> list[dict]:
        """Load all challenges."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM challenges ORDER BY source, created_at").fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def add(self, challenge: dict) -> str:
        """Add a challenge, return its ID."""
        challenge_id = challenge.get("id") or str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO challenges
                   (id, name, announcement, hint, success_message, targets, difficulty,
                    announce_speaker, success_speaker, room, pre_setup, multi_target,
                    funny_announcements, source, floor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    challenge_id,
                    challenge.get("name", ""),
                    challenge.get("announcement", ""),
                    challenge.get("hint", ""),
                    challenge.get("success_message", ""),
                    json.dumps(challenge.get("targets", [])),
                    challenge.get("difficulty", "easy"),
                    challenge.get("announce_speaker", ""),
                    challenge.get("success_speaker", ""),
                    challenge.get("room", ""),
                    json.dumps(challenge.get("pre_setup", [])),
                    1 if challenge.get("multi_target") else 0,
                    json.dumps(challenge.get("funny_announcements", [])),
                    challenge.get("source", "generated"),
                    challenge.get("floor", ""),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return challenge_id

    def update(self, challenge_id: str, fields: dict):
        """Update specific fields of a challenge by ID."""
        # Map of allowed field names to column names
        allowed = {
            "name", "announcement", "hint", "success_message", "difficulty",
            "announce_speaker", "success_speaker", "room", "floor",
        }
        # JSON fields need serialization
        json_fields = {"targets", "pre_setup", "funny_announcements"}

        sets = []
        values = []
        for key, val in fields.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(val)
            elif key in json_fields:
                sets.append(f"{key} = ?")
                values.append(json.dumps(val))
            elif key == "multi_target":
                sets.append("multi_target = ?")
                values.append(1 if val else 0)

        if not sets:
            return

        values.append(challenge_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE challenges SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    def remove(self, challenge_id: str):
        """Remove a challenge by ID."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
            conn.commit()
        finally:
            conn.close()

    def count(self) -> int:
        """Return the total number of challenges."""
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
        finally:
            conn.close()


    # --- Entity Blacklist ---

    def load_blacklist(self) -> list[str]:
        """Load blacklisted entity IDs."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT entity_id FROM blacklist ORDER BY entity_id").fetchall()
            return [r["entity_id"] for r in rows]
        finally:
            conn.close()

    def add_to_blacklist(self, entity_ids: list[str]):
        """Add entity IDs to the blacklist."""
        conn = self._connect()
        try:
            for eid in entity_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO blacklist (entity_id) VALUES (?)", (eid,)
                )
            conn.commit()
        finally:
            conn.close()

    def remove_from_blacklist(self, entity_ids: list[str]):
        """Remove entity IDs from the blacklist."""
        conn = self._connect()
        try:
            for eid in entity_ids:
                conn.execute("DELETE FROM blacklist WHERE entity_id = ?", (eid,))
            conn.commit()
        finally:
            conn.close()

    def clear_blacklist(self):
        """Clear the entire blacklist."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM blacklist")
            conn.commit()
        finally:
            conn.close()

    # --- Engine integration ---

    def to_challenge_objects(self) -> list[Challenge]:
        """Convert stored challenges to Challenge dataclass instances for the engine."""
        challenges = self.load()
        result = []
        for c in challenges:
            try:
                targets = [
                    Target(entity_id=t["entity_id"], target_state=t["target_state"])
                    for t in c.get("targets", [])
                ]
                pre_setup = [
                    PreSetup(
                        domain=p["domain"],
                        service=p["service"],
                        entity_id=p["entity_id"],
                    )
                    for p in c.get("pre_setup", [])
                ]
                difficulty = Difficulty(c.get("difficulty", "easy"))
                result.append(
                    Challenge(
                        name=c["name"],
                        announcement=c["announcement"],
                        hint=c["hint"],
                        success_message=c["success_message"],
                        targets=targets,
                        difficulty=difficulty,
                        announce_speaker=c["announce_speaker"],
                        success_speaker=c["success_speaker"],
                        room=c["room"],
                        pre_setup=pre_setup,
                        multi_target=c.get("multi_target", False),
                        funny_announcements=c.get("funny_announcements", []),
                        floor=c.get("floor", ""),
                    )
                )
            except (KeyError, ValueError):
                continue
        return result
