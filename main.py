from env import *
from datetime import datetime
import uuid

from fasthtml.common import *
from fastcore.utils import *
from q import pull_history
import asyncio

from q import main
import json

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
    return Card(
        Form(
            Div(f"Type: {ep['type']}"),
            Div(f"Published: {ep['published_date']}"),
            Div(f"Title: {ep['title']}"),
            Div(
                "Status: ",
                Select(
                    Option("error", value="error", selected=(ep["status"]=="error")),
                    Option("todo",  value="todo",  selected=(ep["status"]=="todo")),
                    Option("queued",value="queued",selected=(ep["status"]=="queued")),
                    Option("done",  value="done",  selected=(ep["status"]=="done")),
                    Option("skip", value="skip", selected=(ep["status"]=="skip")),
                    name="status"
                ),
                style="margin: 0.5rem 0;"
            ),
            Div(
                "URL: ",
                Input(type="text", name="url", value=ep["url"]),
                style="margin-bottom: 0.5rem;"
            ),
            Textarea(ep["transcript"], name="transcript") if 'transcript' in ep else None,
            Hidden(name="id", value=str(i)),
            Button("Save"),
            hx_post="/update", hx_swap="outerHTML", hx_target=f"#episode-{i}"
        ),
        id=f"episode-{i}",
        style="margin-bottom:1rem; padding:1rem; border:1px solid #ccc;"
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
        Button('Pull History', hx_post='/pull', style='width: 100%; margin:1em 0; padding: 0.5em 0;'),
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

    save_episodes(episodes)
    return episode_form(id, updated_ep)

@rt("/new")
def post(title: str, url: str):
    episodes = load_episodes()
    episodes.insert(0, {
        "id": uuid.uuid4().hex,
        "title": title,
        "url": url,
        "type": "youtube" if "youtube" in url else "podcast",
        "status": "todo",
        "published_date": datetime.now().strftime("%Y-%m-%d")
    })
    save_episodes(episodes)
    return RedirectResponse('/', status_code=303)

@rt("/pull")
def post():
    pull_history()
    return RedirectResponse('/', status_code=303)

serve(port=int(os.getenv('PORT', 5001)))

# start_queue()
