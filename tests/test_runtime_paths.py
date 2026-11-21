"""Regression coverage for runtime files and concurrent audio jobs."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from gh_transcript_fetch import transcription
from gh_transcript_fetch.db import open_episode_db
from gh_transcript_fetch.paths import load_session_key, youtube_client_secrets_path
from gh_transcript_fetch.web import create_app


class RuntimePathTests(unittest.TestCase):
    def test_reopen_queue_and_session_key_from_configured_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "GH_TRANSCRIPT_STATE_DIR": str(root / "state"),
                "GH_TRANSCRIPT_QUEUE_DIR": "",
                "GH_TRANSCRIPT_SESSION_KEY_FILE": "",
                "XDG_CONFIG_HOME": str(root / "config"),
                "GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS": "",
            }):
                db = open_episode_db()
                db.episodes.upsert({"_id": "example", "status": "queued"})
                self.assertTrue(
                    (root / "state" / "queue" / "transcript_queue.episodes_items.json").is_file()
                )
                self.assertEqual(open_episode_db().episodes.find_one({"_id": "example"})["status"], "queued")
                key = load_session_key()
                self.assertEqual(load_session_key(), key)
                self.assertEqual((root / "state" / "session.key").read_text(), key)
                self.assertEqual(
                    youtube_client_secrets_path(),
                    root / "config" / "gh-transcript-fetch" / "client_secret.json",
                )


    def test_web_uses_configured_state_when_adding_an_episode(self):
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                "GH_TRANSCRIPT_STATE_DIR": directory,
                "GH_TRANSCRIPT_QUEUE_DIR": "",
                "GH_TRANSCRIPT_SESSION_KEY_FILE": "",
                "PCUSER": "test-user",
                "PCPW": "test-password",
            }):
                with TestClient(create_app()) as client:
                    response = client.get("/", follow_redirects=False)
                    self.assertEqual(response.headers["location"], "/login")
                    response = client.post(
                        "/login",
                        data={"username": "test-user", "password": "test-password"},
                        follow_redirects=False,
                    )
                    self.assertEqual(response.status_code, 303)
                    response = client.post(
                        "/new",
                        data={"title": "Example", "url": "https://example.com/item.mp3"},
                        follow_redirects=False,
                    )
                    self.assertEqual(response.status_code, 303)
                    self.assertIn("Example", client.get("/").text)
                self.assertIsNotNone(open_episode_db().episodes.find_one({"title": "Example"}))


class TemporaryAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_transcriptions_isolate_and_remove_outputs(self):
        paths = []

        def download(url, directory):
            path = directory / "audio.wav"
            path.write_text(url)
            paths.append(path)
            return path

        async def transcribe(path, show_notes, whisper_dir):
            await asyncio.sleep(0)
            return path.read_text()

        with (
            patch.dict(os.environ, {"WHISPER_LOCAL": "~/whisper.cpp"}),
            patch.object(transcription, "download_audio", side_effect=download),
            patch.object(transcription, "transcribe_audio_with_local_whisper", side_effect=transcribe),
        ):
            results = await asyncio.gather(
                transcription.transcribe_from_url("first", ""),
                transcription.transcribe_from_url("second", ""),
            )

        self.assertEqual(results, ["first", "second"])
        self.assertNotEqual(paths[0].parent, paths[1].parent)
        self.assertTrue(all(not path.parent.exists() for path in paths))
