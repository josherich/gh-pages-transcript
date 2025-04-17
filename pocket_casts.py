import os
import requests
import json
from pathlib import Path

from env import *

WHISPER_CONTEXT_FILE = Path('whisper_context.json')
whisper_context = {}
with open(WHISPER_CONTEXT_FILE, 'r') as f:
    whisper_context = json.load(f)

pocketcasts_user = os.environ['PCUSER']
pocketcasts_pw = os.environ['PCPW']

samples = [{
    "uuid": "46002fcb-8a68-4ce9-8240-43d25fdd3ec5",
    "url": "https://traffic.libsyn.com/secure/ea0f0fdd-2944-4ff3-8a00-704e8c67d58b/CGSP_01162025_Libsyn.mp3?dest-id\u003d4287628",
    "published": "2025-01-16T01:31:00Z",
    "duration": 3307,
    "fileType": "audio/mpeg",
    "title": "China and the Global South in the Trump 2.0 Era",
    "size": "79395951",
    "playingStatus": 3,
    "playedUpTo": 3307,
    "starred": False,
    "podcastUuid": "0afa1ea0-d304-013a-d98f-0acc26574db2",
    "podcastTitle": "The China-Global South Podcast",
    "episodeType": "full",
    "episodeSeason": 3,
    "episodeNumber": 2,
    "isDeleted": True,
    "author": "The China-Global South Project",
    "bookmarks": []
}]

# https://github.com/furgoose/Pocket-Casts/blob/master/pocketcasts/api.py
episode_notes_cache: dict[str, str] = {}
def get_pocketcasts_episode_notes(pod_uuid, episode_uuid):
    if episode_uuid in episode_notes_cache:
        return episode_notes_cache[episode_uuid]

    print(f'Fetching show notes for {pod_uuid} ...')
    notes_url = f'https://podcast-api.pocketcasts.com/mobile/show_notes/full/{pod_uuid}'
    response = requests.get(notes_url, allow_redirects=True)
    response_data = response.json()
    episodes = response_data['podcast']['episodes']
    for ep in episodes:
        episode_notes_cache[ep['uuid']] = ep['show_notes']

    return episode_notes_cache.get(episode_uuid, None)

def get_show_notes(pod_title, pod_uuid, episode_uuid):
    author_notes = whisper_context[pod_title] if pod_title in whisper_context else pod_title
    episode_notes = get_pocketcasts_episode_notes(pod_uuid, episode_uuid)
    return author_notes, episode_notes

def get_pocketcasts_history():
    login_url = "https://api.pocketcasts.com/user/login"
    login_payload = {
        "email": pocketcasts_user,
        "password": pocketcasts_pw,
        "scope": "webplayer"
    }
    login_headers = {"Content-Type": "application/json"}

    login_response = requests.post(login_url, json=login_payload, headers=login_headers)
    login = login_response.json()
    token = login['token']

    history_url = "https://api.pocketcasts.com/user/history"
    history_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

    history_response = requests.post(history_url, headers=history_headers)
    history = history_response.json()
    episodes = history['episodes']

    for ep in episodes:
        ep['pod_notes'], ep['episode_notes'] = get_show_notes(ep['podcastTitle'], ep['podcastUuid'], ep['uuid'])

    return episodes, token

if __name__ == "__main__":
    episodes, token = get_pocketcasts_history()
    episode = episodes[0]
    print('episode: ', episode)
    author_notes, episode_notes = get_show_notes(episode['podcastTitle'], episode['podcastUuid'], episode['uuid'])
    print('author_notes: ', author_notes)
    print('episode_notes: ', episode_notes)
