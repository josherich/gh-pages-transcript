# Github Pages Transcript

A Python tool to fetch audio transcripts for my Pocketcasts listening history and Youtube liked video, process them, and create blog posts via GitHub pull requests.

## Setup

1. Create a client_secret.json file with your Google API credentials
2. Create a env.py file with the following environment variables:

```python
import os
os.environ['PCUSER'] = '' # Pocketcasts username
os.environ['PCPW'] = '' # Pocketcasts password
os.environ['GH_TOKEN'] = '' # GitHub token
os.environ['WHISPER_LOCAL'] = '~/whisper.cpp' # optional: whisper.cpp repo path

os.environ['LM_PROVIDER'] = 'openai' # optional: language model provider. openai|google|ollama|basement
os.environ["OPENAI_API_KEY"] = '' # OpenAI API key
os.environ['G_TOKEN'] = '' # Google API key
os.environ['BASEMENT_URL'] = '' # optional: basement API URL
os.environ['OLLAMA_URL'] = '' # optional: ollama API URL

os.environ['BILIBILI_SESSDATA'] = '' # optional: Bilibili cookies SESSDATA
os.environ['BILIBILI_BUVID3'] = '' # optional: Bilibili cookies BUVID3
os.environ['BILIBILI_BILI_JCT'] = '' # optional: Bilibili cookies BILI_JCT
```

3. Install dependencies

```sh
pip install pytz python-fasthtml PyGithub openai google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client youtube-transcript-api
```

## Usage

```sh
python q.py
```

```sh
python main.py
```

## Files

```sh
├── create_pr.py       # Handle GitHub PR creation
├── whisper.py        # Audio transcription
├── yt_subtitle.py    # YouTube subtitle processing
├── pocket_casts.py   # Podcast processing
└── env.py           # Environment configuration
```
