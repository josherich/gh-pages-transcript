"""Exercise SQLite migration and visibility across independent queue connections."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from gh_transcript_fetch.episode_queue import EpisodeQueue


class EpisodeQueueTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "episodes.sqlite3"
        self.legacy = self.path.with_name("transcript_queue.episodes_items.json")
        self.enterContext(patch.dict(os.environ, {"GH_TRANSCRIPT_LEGACY_QUEUE_FILE": ""}))

    def test_imports_legacy_items_once(self):
        episode = {
            "_id": "legacy",
            "status": "queued",
            "type": "pocketcasts",
            "url": "https://example.com/episode",
            "published_date": "2026-01-01",
            "pod_notes": "示例",
            "transcript": "saved text",
        }
        original = json.dumps([episode], ensure_ascii=False)
        self.legacy.write_text(original, encoding="utf-8")
        queue = EpisodeQueue(self.path)
        self.assertEqual(queue.get("legacy"), episode)
        queue.set_status("legacy", "done")

        reopened = EpisodeQueue(self.path)
        self.assertEqual(reopened.list_episodes("done", "pocketcasts"), [{**episode, "status": "done"}])
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), original)

    def test_imports_explicit_queue_json_with_repeated_legacy_ids(self):
        self.legacy.write_text('[{"_id": "other", "status": "todo"}]', encoding="utf-8")
        old_queue = self.path.with_name("queue.json")
        original = [
            {"id": 1, "status": "todo", "title": "First"},
            {"id": 1, "status": "done", "title": "Second", "transcript": "saved"},
        ]
        old_queue.write_text(json.dumps(original), encoding="utf-8")

        with patch.dict(os.environ, {"GH_TRANSCRIPT_LEGACY_QUEUE_FILE": str(old_queue)}):
            queue = EpisodeQueue(self.path)
        episodes = queue.list_episodes()
        self.assertEqual(len({episode.pop("_id") for episode in episodes}), 2)
        self.assertEqual(episodes, original)

    def test_failed_import_rolls_back_and_can_be_retried(self):
        self.legacy.write_text('[{"_id": "first"}, {"status": "todo"}]')
        with self.assertRaisesRegex(ValueError, "Could not import the legacy episode queue"):
            EpisodeQueue(self.path)

        self.legacy.write_text('[{"_id": "first", "status": "todo"}]')
        queue = EpisodeQueue(self.path)
        self.assertEqual(queue.list_episodes(), [{"_id": "first", "status": "todo"}])

    def test_concurrent_claims_only_return_each_episode_once(self):
        queue = EpisodeQueue(self.path)
        for index in range(4):
            queue.add({"_id": str(index), "status": "queued"})
        barrier = Barrier(8)

        def claim():
            worker_queue = EpisodeQueue(self.path)
            barrier.wait(timeout=10)
            return worker_queue.claim_next()

        with ThreadPoolExecutor(max_workers=8) as pool:
            attempts = list(pool.map(lambda _: claim(), range(8)))

        claims = [claim for claim in attempts if claim is not None]
        self.assertCountEqual([episode["_id"] for episode, _ in claims], ["0", "1", "2", "3"])
        self.assertEqual(len(queue.list_episodes(status="processing")), 4)
        self.assertIsNone(queue.claim_next())

    def test_requeued_episode_rejects_writes_from_stale_claim(self):
        web = EpisodeQueue(self.path)
        worker = EpisodeQueue(self.path)
        web.add({"_id": "episode", "status": "queued", "title": "Example"})

        _, old_token = worker.claim_next()
        web.set_status("episode", "queued")
        _, token = worker.claim_next()
        self.assertFalse(worker.owns_claim("episode", old_token))
        self.assertFalse(worker.save_transcript("episode", "stale", old_token))
        self.assertIsNone(worker.set_status("episode", "done", claim_token=old_token))
        self.assertTrue(worker.save_transcript("episode", "fresh", token))
        worker.set_status("episode", "done", claim_token=token)
        self.assertEqual(web.get("episode"), {
            "_id": "episode", "status": "done", "title": "Example", "transcript": "fresh",
        })

    def test_history_import_deduplicates_by_url_without_replacing_existing_episode(self):
        queue = EpisodeQueue(self.path)
        url = "https://example.com/episode"
        queue.add({"_id": "original", "url": url, "status": "done"})
        self.assertFalse(queue.add({"url": url, "status": "todo"}, only_if_new_url=True))
        self.assertEqual(queue.list_episodes(), [{"_id": "original", "url": url, "status": "done"}])
