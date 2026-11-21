import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .paths import state_directory, youtube_client_secrets_path

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


class YouTubeAuthorizationRequired(Exception):
    pass


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

def youtube_oauth_flow(**kwargs):
    redirect_uri = os.getenv("GH_TRANSCRIPT_YOUTUBE_REDIRECT_URI") or "http://localhost:5002/oauth"
    return Flow.from_client_secrets_file(
        str(youtube_client_secrets_path()), SCOPES, redirect_uri=redirect_uri, **kwargs
    )


def save_youtube_credentials(credentials):
    if not credentials.refresh_token:
        raise YouTubeAuthorizationRequired("Google did not grant offline access.")
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    token_file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False)
    try:
        with token_file:
            token_file.write(credentials.to_json())
        os.replace(token_file.name, directory / "youtube-token.json")
    finally:
        Path(token_file.name).unlink(missing_ok=True)


def authenticate_youtube():
    path = state_directory() / "youtube-token.json"
    try:
        credentials = Credentials.from_authorized_user_file(path, SCOPES)
    except (FileNotFoundError, ValueError) as exc:
        raise YouTubeAuthorizationRequired from exc
    return build("youtube", "v3", credentials=credentials)


def execute_youtube_request(request):
    try:
        return request.execute()
    except RefreshError as exc:
        details = exc.args[1] if len(exc.args) > 1 else None
        if isinstance(details, dict) and details.get("error") == "invalid_grant":
            raise YouTubeAuthorizationRequired from exc
        raise
    except HttpError as exc:
        if exc.resp.status == 401:
            raise YouTubeAuthorizationRequired from exc
        raise

def get_liked_videos(youtube):
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId="LL",  # 'LL' is the default playlist ID for Liked Videos
        maxResults=10  # Adjust as needed
    )
    response = execute_youtube_request(request)

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
    playlist_items = youtube.playlistItems()
    request = playlist_items.list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50,
    )
    video_list = []
    for _ in range(2):
        response = execute_youtube_request(request)
        for item in response.get("items", []):
            snippet = item["snippet"]
            video_id = snippet["resourceId"]["videoId"]
            video_list.append({
                'id': video_id,
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'title': snippet["title"],
                'published_date': snippet["publishedAt"].split("T")[0],
            })
        request = playlist_items.list_next(request, response)
        if request is None:
            break

    return video_list

def get_youtube_liked_videos():
    youtube = authenticate_youtube()
    return get_liked_videos(youtube)

def get_youtube_playlist_videos(playlist_id):
    youtube = authenticate_youtube()
    return get_playlist_videos(youtube, playlist_id)

if __name__ == "__main__":
    try:
        print(get_youtube_liked_videos())
    except YouTubeAuthorizationRequired:
        raise SystemExit("Open the transcript web app and select Pull History to connect YouTube.")
