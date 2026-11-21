import hashlib
import json
import os
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import RefreshError
from starlette.testclient import TestClient

from gh_transcript_fetch.episode_queue import open_episode_db
from gh_transcript_fetch.web import create_app
from gh_transcript_fetch.worker import pull_youtube_history
from gh_transcript_fetch.youtube import YouTubeAuthorizationRequired


class YouTubeOAuthTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.token_path = root / "youtube-token.json"
        client_path = root / "client.json"
        client_path.write_text(json.dumps({"web": {
            "client_id": "test-client",
            "client_secret": "test-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}))
        self.enterContext(patch.dict(os.environ, {
            "GH_TRANSCRIPT_STATE_DIR": str(root),
            "GH_TRANSCRIPT_QUEUE_DIR": "",
            "GH_TRANSCRIPT_SESSION_KEY_FILE": "",
            "GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS": str(client_path),
            "GH_TRANSCRIPT_YOUTUBE_REDIRECT_URI": "https://transcripts.example.com/oauth",
            "PCUSER": "test-user",
            "PCPW": "test-password",
        }))
        self.podcasts = self.enterContext(patch(
            "gh_transcript_fetch.worker.get_pocketcasts_history", return_value=([], None),
        ))
        self.client = self.enterContext(TestClient(
            create_app(), base_url="https://transcripts.example.com", follow_redirects=False,
        ))
        self.client.post("/login", data={"username": "test-user", "password": "test-password"})

    def test_pull_redirects_to_consent_and_resumes_with_saved_credentials(self):
        response = self.client.post("/pull", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 204)
        consent_url = urlparse(response.headers["HX-Redirect"])
        self.assertEqual(consent_url.hostname, "accounts.google.com")
        query = parse_qs(consent_url.query)
        self.assertEqual(query["redirect_uri"], ["https://transcripts.example.com/oauth"])
        self.assertEqual(query["access_type"], ["offline"])

        def exchange(flow, *, code, timeout):
            self.assertEqual(code, "accepted")
            digest = hashlib.sha256(flow.code_verifier.encode()).digest()
            self.assertEqual(query["code_challenge"], [urlsafe_b64encode(digest).decode().rstrip("=")])
            flow.oauth2session.token = {
                "access_token": "test-access",
                "refresh_token": "test-refresh",
                "expires_at": time.time() + 3600,
            }

        with (
            patch("gh_transcript_fetch.youtube.Flow.fetch_token", autospec=True, side_effect=exchange) as fetch,
            patch("gh_transcript_fetch.youtube.build") as build,
        ):
            rejected = self.client.get("/oauth", params={"code": "unexpected", "state": "wrong"})
            self.assertEqual(rejected.status_code, 303)
            fetch.assert_not_called()

            items = build.return_value.playlistItems.return_value
            items.list.return_value.execute.return_value = {"items": [{"snippet": {
                "videoOwnerChannelTitle": "Example Channel",
                "title": "Example video",
                "publishedAt": "2026-11-21T00:00:00Z",
                "resourceId": {"videoId": "example"},
            }}]}
            accepted = self.client.get("/oauth", params={"code": "accepted", "state": query["state"][0]})
            self.assertEqual(accepted.headers["location"], "/")
            self.podcasts.assert_called_once()
            fetch.assert_called_once()
            self.assertEqual(self.token_path.stat().st_mode & 0o777, 0o600)

            db = open_episode_db()
            pull_youtube_history(db)
            self.assertEqual(build.call_count, 2)
            self.assertEqual(build.call_args.kwargs["credentials"].refresh_token, "test-refresh")
            episode, = db.list_episodes()
            self.assertEqual(episode["title"], "Example video")

            items.list.return_value.execute.side_effect = RefreshError("revoked", {"error": "invalid_grant"})
            with self.assertRaises(YouTubeAuthorizationRequired):
                pull_youtube_history(db)
            self.assertEqual(self.client.post("/pull").status_code, 303)

    def test_denied_consent_returns_to_queue(self):
        response = self.client.post("/pull")
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        response = self.client.get("/oauth", params={"error": "access_denied", "state": state})
        self.assertEqual(response.headers["location"], "/")
        self.assertIn("YouTube authorization was not completed", self.client.get("/").text)
        self.assertFalse(self.token_path.exists())
