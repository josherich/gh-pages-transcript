from env import *
from datetime import datetime
import uuid
import hashlib
import hmac
import secrets

from fasthtml.common import *
from fastcore.utils import *
import asyncio
import json
import argparse
from urllib.parse import urlparse, parse_qs
import boto3

from q import main
from q import pull_history
from yt_liked import authenticate_youtube_from_code, authenticate_youtube, get_youtube_playlist_videos
from db import LocalStorageDb


MODE = 'local'
sqs = boto3.client('sqs', region_name='us-west-1')
queue_url = os.getenv('QUEUE_URL')

# Session secret for signing cookies
SESSKEY_PATH = '.sesskey'
if os.path.exists(SESSKEY_PATH):
    with open(SESSKEY_PATH) as f:
        SESSION_SECRET = f.read().strip()
else:
    SESSION_SECRET = secrets.token_hex(32)
    with open(SESSKEY_PATH, 'w') as f:
        f.write(SESSION_SECRET)

LOGIN_USERNAME = os.getenv('username', '')
LOGIN_PASSWORD = os.getenv('password', '')

def make_session_token(username):
    return hmac.new(SESSION_SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()

def check_auth(req, sess):
    token = sess.get('auth_token', '')
    user = sess.get('username', '')
    if not token or not user or token != make_session_token(user):
        return RedirectResponse('/login', status_code=303)

beforeware = Beforeware(check_auth, skip=[r'/login', r'/oauth'])

def start_queue():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down job queue...")

# Initialize database
db = LocalStorageDb({'namespace': 'transcript_queue', 'storage_path': './data'})
db.add_collection('episodes')

def load_episodes(status = None):
    selector = {'status': status} if status else {}
    episodes = db.episodes.find(selector, {'sort': {'published_date': -1}}).fetch()

    return episodes

def insert_episode(ep):
    db.episodes.upsert(ep)

app, rt = fast_app(before=beforeware, secret_key=SESSION_SECRET)

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

@rt("/login")
def get():
    return login_page()

@rt("/login")
def post(username: str, password: str, sess):
    if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
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

def load_episodes_filtered(status=None, source=None):
    selector = {}
    if status:
        selector['status'] = status
    if source:
        selector['type'] = source
    return db.episodes.find(selector, {'sort': {'published_date': -1}}).fetch()

@rt("/")
def get(status: str = 'todo', source: str = ''):
    episodes = load_episodes_filtered(status, source if source else None)
    forms = [episode_form(ep['_id'], ep) for ep in episodes]

    def status_link(s, label):
        href = f"/?status={s}" + (f"&source={source}" if source else "")
        return A(B(label) if status == s else label, href=href)

    def source_link(s, label):
        href = f"/?status={status}" + (f"&source={s}" if s else "")
        return A(B(label) if source == s else label, href=href)

    return Container(
        Div(
            Span(
                status_link('todo', 'todo'), " | ",
                status_link('queued', 'queued'), " | ",
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

@rt("/update")
def post(id: str, status: str, url: str):
    ep = db.episodes.find_one({ '_id': id })
    ep['status'] = status

    if MODE == 'sqs' and status == 'queued':
        print(f"Sending message to queue {queue_url}: {ep}")
        response = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(ep))
        print("SQS MessageId: ", response['MessageId'])

    insert_episode(ep)
    return episode_form(id, ep)

@rt("/new")
def post(title: str, url: str):
    is_playlist = "youtube.com/playlist" in url

    parsed_url = urlparse(url)
    query_string = parsed_url.query
    query_params = parse_qs(query_string)

    if is_playlist:
        episodes = [{
            "id": uuid.uuid4().hex,
            "title": video['title'],
            "url": video['url'],
            "type": "youtube",
            "status": "todo",
            "published_date": video['published_date']
        } for video in get_youtube_playlist_videos(query_params['list'][0])]
    else:
        episodes = [{
            "id": uuid.uuid4().hex,
            "title": title,
            "url": url,
            "type": "youtube" if ("youtube" in url or "bilibili" in url) else "pocketcasts",
            "status": "todo",
            "published_date": datetime.now().strftime("%Y-%m-%d")
        }]

    for ep in episodes:
        insert_episode(ep)
    return RedirectResponse('/', status_code=303)

@rt("/pull")
def post():
    pull_history()
    return RedirectResponse('/', status_code=303)

@rt("/oauth")
def get(request):
    code = request.query_params.get('code')
    print('code: ', code)
    authenticate_youtube_from_code(code)
    return RedirectResponse('/', status_code=303)

serve(port=int(os.getenv('PORT', 5001)))

authenticate_youtube()

parser = argparse.ArgumentParser(description="Transcript Queue")
parser.add_argument("--mode", choices=["local", "sqs"], default='local', help="local queue or SQS queue")
args = parser.parse_args()

MODE = args.mode
print('Mode: ', MODE)


