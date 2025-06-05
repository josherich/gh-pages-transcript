import json
import asyncio
from datetime import datetime
import pytz
from pathlib import Path
import traceback
from env import *

from pocket_casts import get_pocketcasts_history
from yt_liked import get_youtube_liked_videos
from yt_subtitle import download_caption
from whisper import transcribe_from_url
from create_pr import create_branch_and_pr, format_pr_content
from format import format_transcript, rewrite_transcript, extract_toc, extract_faq
import json

QUEUE_FILE = Path('queue.json')

async def get_caption_worker(url: str, show_notes: str, type='pocketcasts'):
    print(f"Processing caption for URL {type}: {url}")
    transcription = None
    if type == 'pocketcasts':
        transcription = transcribe_from_url(url, show_notes)
    elif type == 'youtube':
        transcription = await download_caption(url)

    print(f"Processed caption for URL {type}: {url}")
    return transcription

def pull_history():
    print("Fetching new Podcasts episode URLs...")
    urls, _ = get_pocketcasts_history()
    current_urls = load_queue()
    before_len = len(current_urls)
    current_url_set = {item['url'] for item in current_urls}

    # --------- Add Pocketcasts URLs ---------
    for item in urls:
        if item['url'] not in current_url_set:
            current_urls.append({
                'type': 'pocketcasts',
                'url': item['url'],
                'status': 'todo',
                'title': item['title'],
                'author': item['author'],
                'pod_notes': item['pod_notes'],
                'episode_notes': item['episode_notes'],
                'published_date': item['published'].split('T')[0]})

    after_len = len(current_urls)
    print(f"Added {after_len - before_len} new Pocketcasts URLs to queue")

    # ----------- Add Youtube URLs -----------
    print("Fetching new Youtube liked video URLs...")
    yt_urls = get_youtube_liked_videos()
    for item in yt_urls:
        if item['url'] not in current_url_set: # skip updating current_url_set since it's now all youtube urls
            current_urls.append({
                'type': 'youtube',
                'url': item['url'],
                'status': 'todo',
                'title': item['title'],
                'published_date': item['published_date']})

    save_queue(current_urls)
    after_len_2 = len(current_urls)
    print(f"Added {after_len_2 - after_len} new Youtube URLs to queue")

def load_queue():
    try:
        if not QUEUE_FILE.exists():
            save_queue([])
            return []

        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Error loading queue file: {QUEUE_FILE}")
        save_queue([])

def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

async def producer():
    """Producer that fetches URLs and adds them to the queue"""
    print("Starting producer...")

    while True:
        now = datetime.now(pytz.timezone('US/Eastern'))
        print(f"{now.hour}:{now.minute}")

        # Run at 12:00 ET
        if now.hour == 12 and now.minute == 0:
            try:
                pull_history()
            except Exception as e:
                print(f"Error in producer: {e}")
                asyncio.sleep(60)

        await asyncio.sleep(60)

async def consumer():
    """Consumer that processes URLs from the queue"""
    print("Starting consumer...")

    while True:
        try:
            urls = load_queue()
            todo_items = [item for item in urls if item["status"] == "queued"]

            if not todo_items:
                print("Consumer: No URLs to process, sleeping...")
                await asyncio.sleep(60)
                continue

            item = todo_items[0]
            print(f"Consumer: Processing {item['url']}")

            try:
                if "transcript" not in item:
                    show_notes = f"Podcast title: {item['pod_notes']}\nShow notes: {item['episode_notes']}" if item['type'] == 'pocketcasts' else ''
                    result = await get_caption_worker(item["url"], show_notes, item['type'])
                    if result == None:
                        urls = load_queue()
                        for queue_item in urls:
                            if queue_item["url"] == item["url"]:
                                queue_item["status"] = 'error'
                                break
                        save_queue(urls)
                        raise Exception(f"Failed to fetch raw transcription for {item['url']}")
                    else:
                        for queue_item in urls:
                            if queue_item["url"] == item["url"]:
                                queue_item["transcript"] = result
                                break
                        print(f"Consumer: Completed fetching raw transcription {item['url']}: {result[0:20]}")
                else:
                    result = item["transcript"]
                    print(f"Consumer: Fetching raw transcription from json {item['url']}: {result[0:20]}")

                formatted_result = await format_transcript(result) # format using llm
                blog_post = ''
                toc = extract_toc(formatted_result) # extract table of contents
                faq = extract_faq(formatted_result) # extract faq
                pr_url, file_path = create_branch_and_pr(item["title"], format_pr_content(item['title'], item['url'], formatted_result, blog_post, toc, faq), item['published_date'])
                print(f"Consumer: Created PR: {pr_url}")

                urls = load_queue()
                for queue_item in urls:
                    if queue_item["url"] == item["url"]:
                        queue_item["status"] = "done"
                        break
                save_queue(urls)

            except Exception as e:
                print(f"Error processing {item['url']}: {e}")
                traceback.print_exc()
                # mark error and skip, e.g. yt fail to download subtitle
                urls = load_queue()
                for queue_item in urls:
                    if queue_item["url"] == item["url"]:
                        queue_item["status"] = "error"
                        break
                save_queue(urls)
                await asyncio.sleep(60)

        except Exception as e:
            print(f"Consumer error: {e}")
            await asyncio.sleep(60)

async def main():
    producer_task = asyncio.create_task(producer())
    consumer_task = asyncio.create_task(consumer())

    try:
        await asyncio.gather(producer_task, consumer_task)
    except asyncio.CancelledError:
        producer_task.cancel()
        consumer_task.cancel()
        await asyncio.gather(producer_task, consumer_task, return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down job queue...")
