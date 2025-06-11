from env import *
from datetime import datetime
import uuid

from fasthtml.common import *
from fastcore.utils import *
import asyncio
import json
import argparse
import boto3

from q import main
from q import pull_history
from yt_liked import authenticate_youtube_from_code, authenticate_youtube

MODE = 'local'
sqs = boto3.client('sqs', region_name='us-west-1')
queue_url = os.getenv('QUEUE_URL')

def start_queue():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down job queue...")

EPISODES_FILE = "queue.json"

def load_episodes(status = None):
    episodes = []
    with open(EPISODES_FILE, "r") as f:
        episodes = json.load(f)

    # sort by published date
    # use index as id if not present
    episodes = [{'id': i, **ep} for i, ep in enumerate(episodes)]
    episodes.sort(key=lambda x: x['published_date'], reverse=True)
    if status:
        episodes = [ep for ep in episodes if ep['status'] == status]
    return episodes

def save_episodes(data):
    with open(EPISODES_FILE, "w") as f:
        json.dump(data, f, indent=2)

app, rt = fast_app()

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
                Input(type="text", name="url", value=ep["url"], style="font-size: 0.8rem; margin: 0; padding: 0.5em 1em; height: initial;"),
                style="margin-bottom: 0.25rem; font-size: 0.8rem;"
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
                "Title: ",
                Input(type="text", name="title"),
                style="margin-bottom: 0.5rem;"
            ),
            Div(
                "URL: ",
                Input(type="text", name="url"),
                style="margin-bottom: 0.5rem;"
            ),
            Button("Submit"),
            hx_post="/new", hx_swap="none", hx_target=f"#episodes"
        ),
        id=f"episode-new",
        style="margin-bottom:1rem; padding:1rem; border:1px solid #ccc;"
    )

@rt("/")
def get(status: str = 'todo'):
    episodes = load_episodes(status)
    forms = [episode_form(ep['id'], ep) for ep in episodes]
    return Container(
        Span(
            A(B("todo") if status == 'todo' else 'todo', href="/?status=todo"), " | ",
            A(B("queued") if status == 'queued' else 'queued', href="/?status=queued"), " | ",
            A(B("done") if status == 'done' else 'done', href="/?status=done"), " | ",
            A(B("error") if status == 'error' else 'error', href="/?status=error"), " | ",
            A(B("skip") if status == 'skip' else 'skip', href="/?status=skip"),
        ),
        Button('Pull History', hx_post='/pull', hx_swap='none', style='width: 100%; margin:1em 0; padding: 0.5em 0;'),
        new_episode_form(),
        Div(*forms, id="episodes"),
        style="max-width:800px; margin:auto; padding:1rem;"
    )

@rt("/update")
def post(id: str, status: str, url: str):
    episodes = load_episodes()
    updated_ep = None
    for ep in episodes:
        if ep['url'] == url:
            ep['status'] = status
            ep['url'] = url
            updated_ep = ep
            break

    if MODE == 'sqs' and status == 'queued':
        print(f"Sending message to queue {queue_url}: {updated_ep}")
        response = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(updated_ep), MessageGroupId=updated_ep['type'])
        print("SQS MessageId: ", response['MessageId'])

    save_episodes(episodes)
    return episode_form(id, updated_ep)

@rt("/new")
def post(title: str, url: str):
    episodes = load_episodes()
    episodes.insert(0, {
        "id": uuid.uuid4().hex,
        "title": title,
        "url": url,
        "type": "youtube" if ("youtube" in url or "bilibili" in url) else "pocketcasts",
        "status": "todo",
        "published_date": datetime.now().strftime("%Y-%m-%d")
    })
    save_episodes(episodes)
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


