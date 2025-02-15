from env import *

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

def load_episodes():
    episodes = []
    with open(EPISODES_FILE, "r") as f:
        episodes = json.load(f)

    # sort by published date
    episodes.sort(key=lambda x: x['published_date'], reverse=True)
    return episodes

def save_episodes(data):
    with open(EPISODES_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Load episodes on startup
episodes = load_episodes()

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

@rt("/")
def get():
    forms = [episode_form(i, ep) for i, ep in enumerate(episodes)]
    return Container(Button('Pull History', hx_post='/pull', style='width: 100%; margin:1em 0; padding: 1em 0;'), *forms, style="max-width:800px; margin:auto; padding:1rem;")

@rt("/update")
def post(id: int, status: str, url: str):

    episodes[id]["status"] = status
    episodes[id]["url"] = url
    save_episodes(episodes)
    return episode_form(id, episodes[id])

@rt("/pull")
def post():
    pull_history()
    return RedirectResponse('/', status_code=303)

serve()

# start_queue()
