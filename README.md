# GitHub Pages Transcript

Fetch transcripts for Pocket Casts listening history and liked YouTube videos, format them, and publish them through GitHub pull requests.

## Setup

Install Python 3.11 or newer and run `uv sync --locked`. Install `ffmpeg` for audio transcription. Set the environment variables your workflow uses in your shell or in a private `.env` file.

| Settings | Purpose |
| --- | --- |
| `PCUSER`, `PCPW` | Pocket Casts credentials and web UI login |
| `GH_TOKEN` | GitHub token with Contents and Pull requests write access to `josherich/gh-pages-transcript` |
| `OPENAI_API_KEY` | Hosted Whisper transcription and OpenAI-compatible formatting for the OpenAI and Basement providers |
| `G_TOKEN` | Gemini formatting, table of contents, and FAQ |
| `LM_PROVIDER` | Formatting provider. Defaults to `google`; also supports `openai`, `ollama`, and `basement`. Google and OpenAI models are accessed through OpenRouter. |
| `OPENROUTER_API_KEY` | OpenRouter API key for Google and OpenAI models. |
| `GOOGLE_LM_MODEL` | Gemini model for formatting, table of contents, and FAQ. Defaults to `gemini-4-hydrogen`. |
| `OPENAI_LM_MODEL` | OpenAI formatting model. Defaults to `gpt-6-luna`. |
| `OLLAMA_LM_MODEL` | Ollama formatting model. Defaults to `qwen3.5:4b`. |
| `BASEMENT_LM_MODEL` | Model ID served by your Basement endpoint. Defaults to `deepseek-ai/deepseek-llm-7b-chat`. |
| `WHISPER_LOCAL` | Optional path to a built whisper.cpp checkout |
| `WHISPER_MODEL_NAME` | Model filename in the checkout's `models/` directory. Defaults to `ggml-large-v3-turbo.bin`. |
| `OLLAMA_URL`, `BASEMENT_URL` | Base URLs for those formatting providers |
| `BILIBILI_SESSDATA`, `BILIBILI_BUVID3`, `BILIBILI_BILI_JCT` | Optional Bilibili cookies |
| `PORT`, `QUEUE_URL` | Web port (defaults to 5001) and SQS URL (for `--mode sqs`) |

For Ollama, pull the selected model on the server first. For the default, run `ollama pull qwen3.5:4b`.

For YouTube history and playlist access, place the Google OAuth client JSON at the path below or set its override. With the default callback, set `PORT=5002`, open the app at `http://localhost:5002`, and select **Pull History** to authorize YouTube. For a remote deployment, set `GH_TRANSCRIPT_YOUTUBE_REDIRECT_URI` to the app's HTTPS URL ending in `/oauth` and register that exact URL on the Google OAuth web client. Start authorization from that same app origin. Use the same state root for the web app and worker so the worker can reuse the saved authorization.

## Run

```sh
uv run --env-file .env transcript-web
uv run --env-file .env transcript-worker
uv run python -m unittest discover -s tests
```

Omit `--env-file .env` if the variables are already exported. Both commands accept `--mode local` (the default) or `--mode sqs`. The web and worker commands replace `python main.py` and `python q.py` respectively.

## Publish transcripts

When the worker finishes generating a transcript, it opens a pull request against `main` with the Markdown in `site/transcripts/`. The pull request runs an Astro build. Merging it triggers the GitHub Pages workflow, which builds the archive, updates the generated `gh-pages` branch, and publishes that build at [podcast.josherich.me](https://podcast.josherich.me/).

The repository's Pages source is **GitHub Actions**. The custom domain points to `josherich.github.io` through a DNS-only CNAME. The built files on `gh-pages` are generated from `main` on each release.

To preview the archive locally with Node.js 24:

```sh
cd site
npm ci
npm run dev
```

## Paths

| Purpose | Default | Override |
| --- | --- | --- |
| State root | `~/.local/state/gh-transcript-fetch/` | `GH_TRANSCRIPT_STATE_DIR` or `XDG_STATE_HOME` |
| SQLite queue | `<state root>/queue/episodes.sqlite3` | `GH_TRANSCRIPT_QUEUE_DIR` |
| Web session key | `<state root>/session.key` | `GH_TRANSCRIPT_SESSION_KEY_FILE` |
| YouTube OAuth client JSON | `~/.config/gh-transcript-fetch/client_secret.json` | `GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS` or `XDG_CONFIG_HOME` |
| YouTube authorization | `<state root>/youtube-token.json` | Follows the state root |
| RAG notebook’s Chroma store | `<state root>/chroma/` | Follows the state root |
| Downloaded audio, conversion output, and chunks | A unique system temporary directory per job, cleaned up when the job ends | `TMPDIR` |
| Published Markdown | `site/transcripts/` in this repository | |

For an existing checkout, stop the old web app and worker before starting the new commands. Use the same queue directory in both processes. On first startup, the app imports `transcript_queue.episodes_items.json` from that directory, falling back to `queue.json` if the items file is absent. It leaves the original JSON in place. The legacy upserts and removes files are bookkeeping. You can point to the old directory or copy the items file to the default queue directory before first startup. Transfer settings from your old `env.py` to your environment or `.env`.

The following settings reuse an existing checkout’s queue directory, session key, and OAuth client file.

```dotenv
GH_TRANSCRIPT_QUEUE_DIR=/absolute/path/to/checkout/data
GH_TRANSCRIPT_SESSION_KEY_FILE=/absolute/path/to/checkout/.sesskey
GH_TRANSCRIPT_YOUTUBE_CLIENT_SECRETS=/absolute/path/to/checkout/client_secret.json
```

If your current queue is the `queue.json` in the repository root, run this from the checkout before the SQLite database is initialized. The explicit file takes precedence when both legacy formats are available.

```sh
export GH_TRANSCRIPT_LEGACY_QUEUE_FILE="$PWD/queue.json"
```

Local workers claim jobs atomically. If a worker is forcibly terminated while an episode is processing, select **queued** for that episode after the old worker has stopped.

Application code and the read-only Whisper context are in `src/gh_transcript_fetch/`. Database checks and sample transcripts live under `tests/`, the formatting example lives under `examples/`, and the RAG experiment lives under `notebooks/`.
