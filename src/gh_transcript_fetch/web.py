import argparse
from datetime import datetime
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import parse_qs, urlparse
import uuid

import boto3
import uvicorn
from fasthtml.common import (
    A, B, Body, Beforeware, Button, Card, Container, Div, FastHTML, Form, Head,
    Hidden, Html, HTTPException, Input, NotStr, RedirectResponse, Script, Span, Textarea, Title, picolink,
)
from oauthlib.oauth2 import OAuth2Error
from requests import RequestException
from starlette.responses import Response

from .episode_queue import open_episode_db
from .paths import load_session_key
from .worker import pull_history, pull_youtube_history
from .youtube import (
    YouTubeAuthorizationRequired, get_youtube_playlist_videos, save_youtube_credentials, youtube_oauth_flow,
)


def create_app(mode="local"):
    db = open_episode_db()
    session_secret = load_session_key()
    login_username = os.getenv("PCUSER")
    login_password = os.getenv("PCPW")
    if mode == "sqs":
        queue_url = os.environ["QUEUE_URL"]
        sqs = boto3.client("sqs", region_name="us-west-1")

    def make_session_token(username):
        return hmac.new(session_secret.encode(), username.encode(), hashlib.sha256).hexdigest()

    def check_auth(req, sess):
        token = sess.get("auth_token", "")
        user = sess.get("username", "")
        if not token or not user or token != make_session_token(user):
            return RedirectResponse("/login", status_code=303)

    beforeware = Beforeware(check_auth, skip=[r"/login"])
    app = FastHTML(before=beforeware, secret_key=session_secret, hdrs=(picolink,))

    def redirect(request, url):
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=204, headers={"HX-Redirect": url})
        return RedirectResponse(url, status_code=303)

    def youtube_notice(request, sess, message):
        sess["youtube_notice"] = message
        return redirect(request, "/")

    def start_youtube_authorization(request, sess, playlist_id=None):
        try:
            flow = youtube_oauth_flow(autogenerate_code_verifier=True)
            url, state = flow.authorization_url(prompt="consent")
        except (OAuth2Error, OSError, ValueError):
            return youtube_notice(request, sess, "YouTube authorization is unavailable. Check the OAuth client configuration.")
        sess["youtube_oauth"] = {
            "state": state,
            "code_verifier": flow.code_verifier,
            "playlist_id": playlist_id,
        }
        return redirect(request, url)

    def login_page(error=''):
        return Html(
            Head(Title("Login")),
            Body(
                NotStr('''<dialog id="login-modal" style="border:1px solid #ccc; border-radius:8px; padding:1.5rem; max-width:340px; width:90%;">
  <h3 style="margin:0 0 1rem 0; font-size:1rem;">Login</h3>
  <form method="post" action="/login">
    <div style="margin-bottom:0.75rem;">
      <label for="username" style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Username</label>
      <input type="text" id="username" name="username" required autofocus
        style="width:100%; padding:0.4rem; font-size:0.85rem; border:1px solid #ccc; border-radius:4px; box-sizing:border-box;">
    </div>
    <div style="margin-bottom:0.75rem;">
      <label for="password" style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Password</label>
      <input type="password" id="password" name="password" required
        style="width:100%; padding:0.4rem; font-size:0.85rem; border:1px solid #ccc; border-radius:4px; box-sizing:border-box;">
    </div>
    <div id="error-msg" style="color:red; font-size:0.8rem; margin-bottom:0.5rem;">''' + error + '''</div>
    <button type="submit" style="width:100%; padding:0.5rem; font-size:0.85rem; cursor:pointer;">Log in</button>
  </form>
</dialog>
<script>document.getElementById('login-modal').showModal();</script>'''),
                style="margin:0; padding:0; background:#f5f5f5;"
            )
        )

    @app.get("/login")
    def show_login():
        return login_page()

    @app.post("/login")
    def login(username: str, password: str, sess):
        if username == login_username and password == login_password:
            sess['username'] = username
            sess['auth_token'] = make_session_token(username)
            return RedirectResponse('/', status_code=303)
        return login_page(error='Invalid username or password')

    def episode_form(i, ep):
        def status_button(status, label):
            is_active = ep["status"] == status
            return Button(
                label,
                hx_post="/update",
                hx_swap="outerHTML",
                hx_target=f"#episode-{i}",
                name="status",
                value=status,
                style=f"margin-right: 0.25rem; background-color: {'#4CAF50' if is_active else '#f0f0f0'}; color: {'white' if is_active else 'black'}; border: 1px solid #ccc; padding: 2px 6px; border-radius: 2px; font-size: 0.8rem;"
            )

        return Card(
            Form(
                Div(f"Type: {ep['type']}", style="font-size: 0.8rem; margin-bottom: 0.25rem;"),
                Div(f"Published: {ep['published_date']}", style="font-size: 0.8rem; margin-bottom: 0.25rem;"),
                Div(f"Title: {ep['title']}", style="font-size: 0.9rem; font-weight: bold; margin-bottom: 0.25rem;"),
                Div(
                    "Status: ",
                    status_button("error", "error"),
                    status_button("todo", "todo"),
                    status_button("queued", "queued"),
                    status_button("done", "done"),
                    status_button("skip", "skip"),
                    style="margin: 0.25rem 0; font-size: 0.8rem;"
                ),
                Div(
                    Input(type="text", name="url", value=ep["url"], id=f"url-{i}", style="font-size: 0.8rem; margin: 0; padding: 0.5em 1em; height: initial; flex:1;"),
                    Button("▶", type="button",
                        onclick=f"playEpisodeUrl(document.getElementById('url-{i}').value, {repr(ep.get('title',''))})",
                        style="margin-left:0.25rem; padding:2px 7px; font-size:0.8rem; height:initial; cursor:pointer; background:#f0f0f0; border:1px solid #ccc; border-radius:2px;"),
                    style="display:flex; align-items:center; margin-bottom: 0.25rem; font-size: 0.8rem;"
                ),
                Textarea(ep["transcript"], name="transcript", style="font-size: 0.8rem; padding: 4px;") if 'transcript' in ep else None,
                Hidden(name="id", value=str(i)),
                id=f"episode-{i}"
            ),
            id=f"episode-{i}",
            style="margin-bottom:0.5rem; padding:0.5rem; border:1px solid #ccc; font-size: 0.8rem;"
        )

    def new_episode_form():
        return Card(
            Form(
                Div(
                    Input(type="text", name="title", placeholder="Title", style="font-size:0.8rem; padding:2px 6px; height:initial; margin-right:0.25rem; flex:1;"),
                    Input(type="text", name="url", placeholder="URL", style="font-size:0.8rem; padding:2px 6px; height:initial; margin-right:0.25rem; flex:2;"),
                    Button("Add", style="font-size:0.8rem; padding:2px 8px; height:initial;"),
                    style="display:flex; align-items:center;"
                ),
                hx_post="/new", hx_swap="none", hx_target=f"#episodes"
            ),
            id=f"episode-new",
            style="margin-bottom:0.5rem; padding:0.35rem 0.5rem; border:1px solid #ccc; font-size:0.8rem;"
        )

    @app.get("/")
    def list_episodes(sess, status: str = 'todo', source: str = ''):
        episodes = db.list_episodes(status or None, source or None)
        forms = [episode_form(ep['_id'], ep) for ep in episodes]
        notice = sess.pop("youtube_notice", None)

        def status_link(s, label):
            href = f"/?status={s}" + (f"&source={source}" if source else "")
            return A(B(label) if status == s else label, href=href)

        def source_link(s, label):
            href = f"/?status={status}" + (f"&source={s}" if s else "")
            return A(B(label) if source == s else label, href=href)

        return Container(
            Div(notice, role="alert") if notice else None,
            Div(
                Span(
                    status_link('todo', 'todo'), " | ",
                    status_link('queued', 'queued'), " | ",
                    status_link('processing', 'processing'), " | ",
                    status_link('done', 'done'), " | ",
                    status_link('error', 'error'), " | ",
                    status_link('skip', 'skip'),
                    style="font-size:0.85rem;"
                ),
                Span(
                    " \u2502 ",
                    source_link('', 'all'), " | ",
                    source_link('youtube', 'youtube'), " | ",
                    source_link('pocketcasts', 'pocketcasts'),
                    style="font-size:0.85rem; color:#555;"
                ),
                style="margin-bottom:0.5rem;"
            ),
            Button('Pull History', hx_post='/pull', hx_swap='none', style='width: 100%; margin:0.5em 0; padding: 0.35em 0; font-size:0.85rem;'),
            new_episode_form(),
            Div(*forms, id="episodes"),
            # Floating audio player
            Div(
                Div(
                    Span("▶ Audio Player", style="font-size:0.8rem; font-weight:bold;"),
                    Button("✕", type="button", onclick="document.getElementById('floating-player').style.display='none'", style="float:right; background:none; border:none; cursor:pointer; font-size:0.9rem; padding:0; line-height:1;"),
                    style="margin-bottom:0.5rem; overflow:hidden;"
                ),
                NotStr('<audio id="player-audio" controls style="width:280px; height:32px;"></audio>'),
                Div(id="player-title", style="font-size:0.75rem; color:#555; margin-top:0.35rem; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"),
                id="floating-player",
                style="display:none; position:fixed; right:1rem; bottom:1rem; background:white; border:1px solid #ccc; border-radius:8px; padding:0.75rem; box-shadow:0 2px 12px rgba(0,0,0,0.18); z-index:9999; min-width:310px;"
            ),
            Script("""
function playEpisodeUrl(url, title) {
    var audio = document.getElementById('player-audio');
    var player = document.getElementById('floating-player');
    var titleEl = document.getElementById('player-title');
    audio.src = url;
    titleEl.textContent = title || url;
    player.style.display = 'block';
    audio.play().catch(function(){});
}
"""),
            style="max-width:800px; margin:auto; padding:1rem;"
        )

    @app.post("/update")
    def update_episode(id: str, status: str, url: str):
        ep = db.set_status(id, status)
        if ep is None:
            raise HTTPException(status_code=404, detail="Episode not found")

        if mode == 'sqs' and status == 'queued':
            print(f"Sending message to queue {queue_url}: {ep}")
            response = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(ep))
            print("SQS MessageId: ", response['MessageId'])

        return episode_form(id, ep)

    def add_youtube_playlist(playlist_id):
        for video in get_youtube_playlist_videos(playlist_id):
            db.add({
                "id": uuid.uuid4().hex,
                "title": video["title"],
                "url": video["url"],
                "type": "youtube",
                "status": "todo",
                "published_date": video["published_date"],
            })

    @app.post("/new")
    def add_episode(title: str, url: str, request, sess):
        is_playlist = "youtube.com/playlist" in url

        parsed_url = urlparse(url)
        query_string = parsed_url.query
        query_params = parse_qs(query_string)

        if is_playlist:
            if not query_params.get("list"):
                raise HTTPException(status_code=400, detail="YouTube playlist ID is missing")
            playlist_id = query_params["list"][0]
            try:
                add_youtube_playlist(playlist_id)
            except YouTubeAuthorizationRequired:
                return start_youtube_authorization(request, sess, playlist_id)
        else:
            db.add({
                "id": uuid.uuid4().hex,
                "title": title,
                "url": url,
                "type": "youtube" if ("youtube" in url or "bilibili" in url) else "pocketcasts",
                "status": "todo",
                "published_date": datetime.now().strftime("%Y-%m-%d")
            })
        return redirect(request, "/")

    @app.post("/pull")
    def pull_episodes(request, sess):
        try:
            pull_history(db)
        except YouTubeAuthorizationRequired:
            return start_youtube_authorization(request, sess)
        return redirect(request, "/")

    @app.get("/oauth")
    def youtube_callback(request, sess):
        pending = sess.get("youtube_oauth")
        state = request.query_params.get("state", "")
        code = request.query_params.get("code")
        if not pending or not secrets.compare_digest(state.encode(), pending["state"].encode()):
            return youtube_notice(request, sess, "YouTube authorization session expired. Start the import again.")
        sess.pop("youtube_oauth")
        sess.pop("youtube_notice", None)
        if request.query_params.get("error") or not code:
            return youtube_notice(request, sess, "YouTube authorization was not completed. Start the import again to retry.")
        try:
            flow = youtube_oauth_flow(code_verifier=pending["code_verifier"])
            flow.fetch_token(code=code, timeout=15)
            save_youtube_credentials(flow.credentials)
        except (OAuth2Error, RequestException, OSError, ValueError, YouTubeAuthorizationRequired):
            return youtube_notice(request, sess, "Could not save YouTube authorization. Start the import again to retry.")
        try:
            if pending["playlist_id"] is None:
                pull_youtube_history(db)
            else:
                add_youtube_playlist(pending["playlist_id"])
        except YouTubeAuthorizationRequired:
            return youtube_notice(request, sess, "YouTube rejected the connection. Start the import again to reconnect.")
        return redirect(request, "/")

    return app


def cli():
    parser = argparse.ArgumentParser(description="Transcript queue web interface")
    parser.add_argument("--mode", choices=["local", "sqs"], default="local")
    args = parser.parse_args()
    uvicorn.run(create_app(mode=args.mode), host="0.0.0.0", port=int(os.getenv("PORT", 5001)))


if __name__ == "__main__":
    cli()
