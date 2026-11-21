"""SQLite storage for the shared episode queue."""

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .paths import queue_directory


_INSERT_EPISODE = """
    INSERT INTO episodes (id, status, url, source, published_date, document)
    VALUES (?, ?, ?, ?, ?, ?)
"""


def _episode_values(episode):
    document = dict(episode)
    status = document.pop("status", None)
    return (
        document["_id"], status, document.get("url"), document.get("type"),
        document.get("published_date"), json.dumps(document, ensure_ascii=False),
    )


def _read_episode(row):
    if row is None:
        return None
    episode = json.loads(row["document"])
    if row["status"] is not None:
        episode["status"] = row["status"]
    return episode


class EpisodeQueue:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("PRAGMA user_version").fetchone()[0] == 0:
                self._initialize(connection)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def _initialize(self, connection):
        connection.execute("""
            CREATE TABLE episodes (
                id TEXT PRIMARY KEY NOT NULL,
                status TEXT,
                url TEXT,
                source TEXT,
                published_date TEXT,
                document TEXT NOT NULL,
                claim_token TEXT
            )
        """)
        connection.execute("CREATE INDEX episodes_status ON episodes(status)")
        connection.execute("CREATE INDEX episodes_url ON episodes(url)")
        self._import_legacy_items(connection)
        connection.execute("PRAGMA user_version = 1")

    def _import_legacy_items(self, connection):
        configured_path = os.getenv("GH_TRANSCRIPT_LEGACY_QUEUE_FILE")
        if configured_path:
            path = Path(configured_path).expanduser()
            contents = path.read_text(encoding="utf-8")
        else:
            path = self.path.with_name("transcript_queue.episodes_items.json")
            try:
                contents = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                path = self.path.with_name("queue.json")
                try:
                    contents = path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    return

        try:
            episodes = json.loads(contents)
            if not isinstance(episodes, list):
                raise ValueError("expected a JSON list")
            for episode in episodes:
                if "_id" not in episode and "id" in episode:
                    # The older file can repeat numeric IDs. Keep them as metadata.
                    episode["_id"] = str(uuid4())
            connection.executemany(_INSERT_EPISODE, (_episode_values(item) for item in episodes))
        except (KeyError, TypeError, ValueError, sqlite3.IntegrityError) as error:
            raise ValueError(f"Could not import the legacy episode queue at {path}: {error}") from error

    def add(self, episode, *, only_if_new_url=False):
        episode = {"_id": str(uuid4()), **episode}
        values = _episode_values(episode)
        with self._connect() as connection:
            if only_if_new_url:
                # The existence check and insert share the same SQLite write statement.
                result = connection.execute("""
                    INSERT INTO episodes (id, status, url, source, published_date, document)
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM episodes WHERE url = ?)
                """, (*values, episode["url"]))
                return result.rowcount == 1

            connection.execute(_INSERT_EPISODE, values)
            return True

    def list_episodes(self, status=None, source=None):
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT status, document
                FROM episodes
                WHERE (? IS NULL OR status = ?) AND (? IS NULL OR source = ?)
                ORDER BY published_date DESC, rowid
            """, (status, status, source, source))
            return [_read_episode(row) for row in rows]

    def get(self, episode_id):
        with self._connect() as connection:
            return _read_episode(connection.execute(
                "SELECT status, document FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone())

    def set_status(self, episode_id, status, *, claim_token=None):
        with self._connect() as connection:
            result = connection.execute("""
                UPDATE episodes
                SET status = ?, claim_token = NULL
                WHERE id = ? AND (? IS NULL OR claim_token = ?)
            """, (status, episode_id, claim_token, claim_token))
            if result.rowcount == 0:
                return None
            return _read_episode(connection.execute(
                "SELECT status, document FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone())

    def claim_next(self):
        """Claim one queued episode and return it with its ownership token."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""
                SELECT id, status, document
                FROM episodes WHERE status = 'queued'
                ORDER BY rowid LIMIT 1
            """).fetchone()
            if row is None:
                return None

            token = uuid4().hex
            connection.execute(
                "UPDATE episodes SET status = 'processing', claim_token = ? WHERE id = ?",
                (token, row["id"]),
            )
            episode = _read_episode(row)
            episode["status"] = "processing"
            return episode, token

    def save_transcript(self, episode_id, transcript, claim_token):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT document FROM episodes WHERE id = ? AND claim_token = ?",
                (episode_id, claim_token),
            ).fetchone()
            if row is None:
                return False

            document = json.loads(row["document"])
            document["transcript"] = transcript
            connection.execute(
                "UPDATE episodes SET document = ? WHERE id = ?",
                (json.dumps(document, ensure_ascii=False), episode_id),
            )
            return True

    def owns_claim(self, episode_id, claim_token):
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM episodes WHERE id = ? AND claim_token = ?", (episode_id, claim_token)
            ).fetchone() is not None


def open_episode_db():
    return EpisodeQueue(queue_directory() / "episodes.sqlite3")
