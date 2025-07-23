import os
import re
import unicodedata
import google.auth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from env import *

credential = None
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

def slugify(text):
    # Normalize unicode characters to closest ASCII equivalent
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

    # Lowercase
    text = text.lower()

    # Replace spaces and underscores with hyphens
    text = re.sub(r'[\s_]+', '-', text)

    # Remove characters that aren't alphanumeric or hyphens
    text = re.sub(r'[^a-z0-9\-]', '', text)

    # Remove leading/trailing and multiple hyphens
    text = re.sub(r'-{2,}', '-', text).strip('-')

    return text

def authenticate_youtube(use_local=False):
    global credential
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    if credential is None:
        flow.redirect_uri = 'http://localhost:5002/oauth'
        auth_url, __ = flow.authorization_url(prompt="consent")

        print(f"Open this URL in your browser: {auth_url}")

        if use_local:
            code = input('Enter the authorization code: ')
            token = flow.fetch_token(code=code)
            print(f"Obtained token: {token}")
            credential = flow.credentials

            return build("youtube", "v3", credentials=credential)
        else:
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
        prog_slug = slugify(item["snippet"]["videoOwnerChannelTitle"])
        video_title = item["snippet"]["title"]
        published_date = item["snippet"]["publishedAt"].split("T")[0]
        video_id = item["snippet"]["resourceId"]["videoId"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        # print(f"Title: {video_title}, URL: https://www.youtube.com/watch?v={video_id}")
        # print(f"channel name slugify: {prog_slug}")
        video_list.append({
            'id': video_id,
            'url': video_url,
            'title': video_title,
            'prog_slug': prog_slug,
            'published_date': published_date
        })

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
        video_list.append({
            'id': video_id,
            'url': video_url,
            'title': video_title,
            'published_date': published_date
        })

    return video_list

def get_youtube_liked_videos():
    youtube = authenticate_youtube()
    return get_liked_videos(youtube)

def get_youtube_playlist_videos(playlist_id):
    youtube = authenticate_youtube()
    return get_playlist_videos(youtube, playlist_id)

if __name__ == "__main__":
    youtube = authenticate_youtube(use_local=True)
    liked_videos = get_liked_videos(youtube)
    print(liked_videos)
