import os
import requests

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
    return history["episodes"]
