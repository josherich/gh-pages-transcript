# GitHub Pages Transcript

Fetch transcripts for Pocket Casts listening history and liked YouTube videos, format them, and publish them through GitHub pull requests.

## Setup

Install Python 3.11 or newer and run `uv sync --locked`. Install `ffmpeg` for audio transcription. Set the environment variables your workflow uses in your shell or in a private `.env` file.

| Settings | Purpose |
| --- | --- |
| `PCUSER`, `PCPW` | Pocket Casts credentials and web UI login |
| `GH_TOKEN` | GitHub publishing |
| `OPENAI_API_KEY` | Hosted Whisper transcription and OpenAI-compatible formatting for the OpenAI and Basement providers |
| `G_TOKEN` | Gemini formatting, table of contents, and FAQ |
| `LM_PROVIDER` | Formatting provider. Defaults to `google`; also supports `openai`, `ollama`, and `basement`. |
| `WHISPER_LOCAL` | Optional path to a built whisper.cpp checkout with the `ggml-large-v3-turbo-q5_0.bin` model |
| `OLLAMA_URL`, `BASEMENT_URL` | Base URLs for those formatting providers |
| `BILIBILI_SESSDATA`, `BILIBILI_BUVID3`, `BILIBILI_BILI_JCT` | Optional Bilibili cookies |
| `PORT`, `QUEUE_URL` | Web port (defaults to 5001) and SQS URL (for `--mode sqs`) |

For YouTube history and playlist access, place the Google OAuth client JSON at the path below or set its override. The existing web OAuth callback is `http://localhost:5002/oauth`. Set `PORT=5002` when using that callback.

## Run

```sh
uv run --env-file .env transcript-web
uv run --env-file .env transcript-worker
uv run python -m unittest discover -s tests
```

Omit `--env-file .env` if the variables are already exported. Both commands accept `--mode local` (the default) or `--mode sqs`. The web and worker commands replace `python main.py` and `python q.py` respectively.

## Paths

| Purpose | Default | Override |
| --- | --- | --- |
| State root | `~/.local/state/gh-transcript-fetch/` | `GH_TRANSCRIPT_STATE_DIR` or `XDG_STATE_HOME` |
| Queue JSON | `<state root>/queue/` | `GH_TRANSCRIPT_QUEUE_DIR` |
| Web session key | `<state root>/session.key` | `GH_TRANSCRIPT_SESSION_KEY_FILE` |
| YouTube OAuth client JSON | `~/.config/gh-transcript-fetch/client_secret.json` | `GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS` or `XDG_CONFIG_HOME` |
| RAG notebook’s Chroma store | `<state root>/chroma/` | Follows the state root |
| Downloaded audio, conversion output, and chunks | A unique system temporary directory per job, cleaned up when the job ends | `TMPDIR` |
| Published Markdown | `_posts/podcast/` in the target GitHub repository | |

For an existing checkout, set these values to reuse its queue, session key, and OAuth client file. Use the same settings in both processes. You can also copy the existing files into the new default paths while both processes are stopped. Transfer the settings from your old `env.py` to your environment or `.env`.

```dotenv
GH_TRANSCRIPT_QUEUE_DIR=/absolute/path/to/checkout/data
GH_TRANSCRIPT_SESSION_KEY_FILE=/absolute/path/to/checkout/.sesskey
GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS=/absolute/path/to/checkout/client_secret.json
```

Application code and the read-only Whisper context are in `src/gh_transcript_fetch/`. Database checks and sample transcripts live under `tests/`, the formatting example lives under `examples/`, and the RAG experiment lives under `notebooks/`.
