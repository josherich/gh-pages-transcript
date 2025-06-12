import os
import google.auth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from env import *

credential = None
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

def authenticate_youtube():
    global credential
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    if credential is None:
        flow.redirect_uri = 'http://localhost:5002/oauth'
        auth_url, __ = flow.authorization_url(prompt="consent")

        print(f"Open this URL in your browser: {auth_url}")
        return None

    return build("youtube", "v3", credentials=credential)

def authenticate_youtube_from_code(code):
    global credential
    if credential is not None:
        return
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    flow.redirect_uri = 'http://localhost:5002/oauth'
    token = flow.fetch_token(code=code)
    print(f"Obtained token: {token}")
    credential = flow.credentials

def get_liked_videos(youtube):
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId="LL",  # 'LL' is the default playlist ID for Liked Videos
        maxResults=10  # Adjust as needed
    )
    response = request.execute()

    video_list = []
    for item in response.get("items", []):
        video_title = item["snippet"]["title"]
        published_date = item["snippet"]["publishedAt"].split("T")[0]
        video_id = item["snippet"]["resourceId"]["videoId"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Title: {video_title}, URL: https://www.youtube.com/watch?v={video_id}")
        video_list.append({'title': video_title, 'id': video_id, 'url': video_url, 'published_date': published_date})

    return video_list

def get_playlist_videos(youtube, playlist_id):
    print(f"playlist_id: {playlist_id}")
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=100
    )
    response = request.execute()

    video_list = []
    for item in response.get("items", []):
        print(item["snippet"])
        video_title = item["snippet"]["title"]
        published_date = item["snippet"]["publishedAt"].split("T")[0]
        video_id = item["snippet"]["resourceId"]["videoId"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Title: {video_title}, URL: https://www.youtube.com/watch?v={video_id}")
        video_list.append({'title': video_title, 'id': video_id, 'url': video_url, 'published_date': published_date})

    return video_list

def get_youtube_liked_videos():
    youtube = authenticate_youtube()
    return get_liked_videos(youtube)

def get_youtube_playlist_videos(playlist_id):
    youtube = authenticate_youtube()
    return get_playlist_videos(youtube, playlist_id)

if __name__ == "__main__":
    youtube = authenticate_youtube()
    liked_videos = get_liked_videos(youtube)
    print(liked_videos)
