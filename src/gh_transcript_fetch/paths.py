"""Paths for persistent application state and user-provided configuration."""

import os
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory


APP_NAME = "gh-transcript-fetch"


def state_directory() -> Path:
    xdg_state = os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    default = Path(xdg_state) / APP_NAME
    return Path(os.getenv("GH_TRANSCRIPT_STATE_DIR") or default).expanduser()


def queue_directory() -> Path:
    default = state_directory() / "queue"
    return Path(os.getenv("GH_TRANSCRIPT_QUEUE_DIR") or default).expanduser()


def session_key_path() -> Path:
    default = state_directory() / "session.key"
    return Path(os.getenv("GH_TRANSCRIPT_SESSION_KEY_FILE") or default).expanduser()


def youtube_client_secrets_path() -> Path:
    xdg_config = os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config"
    default = Path(xdg_config) / APP_NAME / "client_secret.json"
    return Path(os.getenv("GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS") or default).expanduser()


def load_session_key() -> str:
    """Load the existing key or publish a private key without a partial write."""
    path = session_key_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=path.parent) as temporary_dir:
        candidate = Path(temporary_dir) / "session.key"
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(secrets.token_hex(32))
        try:
            path.hardlink_to(candidate)
        except FileExistsError:
            pass

    return path.read_text(encoding="utf-8").strip()
