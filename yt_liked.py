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
        code = input('Enter the authorization code: ')
        token = flow.fetch_token(code=code)
        print(f"Obtained token: {token}")
        credential = flow.credentials

    return build("youtube", "v3", credentials=credential)

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

def get_youtube_liked_videos():
    youtube = authenticate_youtube()
    return get_liked_videos(youtube)

if __name__ == "__main__":
    youtube = authenticate_youtube()
    liked_videos = get_liked_videos(youtube)
    print(liked_videos)
