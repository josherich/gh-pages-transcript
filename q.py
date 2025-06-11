import json
import asyncio
from datetime import datetime
from pathlib import Path
import argparse
import traceback
from dataclasses import dataclass
import boto3
from xml.etree.ElementTree import ParseError

from env import *
from pocket_casts import get_pocketcasts_history
from yt_liked import get_youtube_liked_videos
from yt_subtitle import download_caption
from whisper import transcribe_from_url
from create_pr import create_branch_and_pr, format_pr_content
from format import format_transcript, extract_toc, extract_faq

QUEUE_FILE = Path('queue.json')
sqs = boto3.client('sqs', region_name='us-west-1')
queue_url = os.getenv('QUEUE_URL')

async def get_caption_worker(url: str, show_notes: str, type='pocketcasts'):
    print(f"Processing caption for URL {type}: {url}")
    transcription = None
    if type == 'pocketcasts':
        transcription = await transcribe_from_url(url, show_notes)
    elif type == 'youtube':
        transcription = await download_caption(url)

    print(f"Processed caption for URL {type}: {url}")
    return transcription

@dataclass
class PocketCast:
    url: str
    title: str
    author: str
    pod_notes: str
    episode_notes: str
    published_date: str
    status: str = 'todo'
    type: str = 'pocketcasts'
    def __str__(self):
        return json.dump({
            'url': self.url,
            'title': self.title,
            'author': self.author,
            'pod_notes': self.pod_notes,
            'episode_notes': self.episode_notes,
            'published_date': self.published_date,
            'status': self.status,
            'type': self.type
        })

@dataclass
class Youtube:
    url: str
    title: str
    published_date: str
    status: str = 'todo'
    type: str = 'youtube'
    def __str__(self):
        return json.dump({
            'url': self.url,
            'title': self.title,
            'published_date': self.published_date,
            'status': self.status,
            'type': self.type
        })

def pull_history():
    print("Fetching new Podcasts episode URLs...")
    all_messages = []
    urls, _ = get_pocketcasts_history()
    current_urls = load_queue()
    before_len = len(current_urls)
    current_url_set = {item['url'] for item in current_urls}

    # --------- Add Pocketcasts URLs ---------
    for item in urls:
        if item['url'] not in current_url_set:
            all_messages.append(PocketCast(
                url=item['url'],
                title=item['title'],
                author=item['author'],
                pod_notes=item['pod_notes'],
                episode_notes=item['episode_notes'],
                published_date=item['published'].split('T')[0]
            ))
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
            all_messages.append(Youtube(
                url=item['url'],
                title=item['title'],
                published_date=item['published_date']
            ))
            current_urls.append({
                'type': 'youtube',
                'url': item['url'],
                'status': 'todo',
                'title': item['title'],
                'published_date': item['published_date']})

    save_queue(current_urls)
    after_len_2 = len(current_urls)
    print(f"Added {after_len_2 - after_len} new Youtube URLs to queue")
    return all_messages

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

async def producer(mode):
    """Producer that fetches URLs and adds them to the queue"""
    print("Starting producer...")

    while True:
        now = datetime.now()
        print(f"{now.hour}:{now.minute}")

        # Run at 12:00
        if now.hour == 12 and now.minute == 0:
            try:
                all_messages = pull_history()
            except Exception as e:
                print(f"Error in producer: {e}")
                asyncio.sleep(60)

        await asyncio.sleep(60)

def move_to_status(url, status):
    urls = load_queue()
    for queue_item in urls:
        if queue_item["url"] == url:
            queue_item["status"] = status
            break
    save_queue(urls)

def move_to_processing(url):
    move_to_status(url, 'processing')

def move_to_done(url):
    move_to_status(url, 'done')

def move_to_error(url):
    move_to_status(url, 'error')

async def sqs_consumer(name):
    print(f"Starting sqs consumer {name}...")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
            )
            messages = response.get('Messages', [])
            message = messages[0] if messages else None
            if not message:
                print(f"Consumer {name}: No messages to process, sleeping...")
                await asyncio.sleep(10)
            else:
                print(message['Body'])
                item = json.loads(message['Body'])
                move_to_processing(item["url"])
                print(f"Consumer {name}: Processing message {item}")
                try:
                    show_notes = ''
                    if item['type'] == 'pocketcasts':
                        show_notes = f"Podcast title: {item['pod_notes']}\nShow notes: {item['episode_notes']}"

                    result = await get_caption_worker(item["url"], show_notes, item['type'])
                    if result == None:
                        move_to_error(item["url"])
                        raise Exception(f"Failed to fetch raw transcription for {item['url']}")

                    formatted_result = await format_transcript(result) # format using llm
                    blog_post = ''
                    toc = extract_toc(formatted_result) # extract table of contents
                    faq = extract_faq(formatted_result) # extract faq
                    pr_url, _ = create_branch_and_pr(
                        item["title"],
                        format_pr_content(item['title'], item['url'], formatted_result, blog_post, toc, faq),
                        item['published_date']
                    )
                    print(f"Consumer {name}: Created PR: {pr_url}")

                    move_to_done(item["url"])

                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
                except ParseError as e:
                    print(f"Excepted no element found in xml.etree.ElementTree.ParseError: {e}")
                    print(f"SQS message will be visibile after 30 minutes.")
                    continue
        except Exception as e:
            print(f"Consumer {name}: error: {e}")
            traceback.print_exc()
            move_to_error(item["url"])
            await asyncio.sleep(60)


async def local_consumer(name):
    """Consumer that processes URLs from the queue"""
    print(f"Starting local consumer {name}...")

    while True:
        try:
            urls = load_queue()
            todo_items = [item for item in urls if item["status"] == "queued"]

            if not todo_items:
                print(f"Consumer {name}: No URLs to process, sleeping...")
                await asyncio.sleep(60)
                continue

            # FIXME: Race condition: the other consumer could grab the same item
            item = todo_items[0]

            move_to_processing(item["url"])

            print(f"Consumer {name}: Processing {item['url']}")

            try:
                if "transcript" not in item:
                    show_notes = ''
                    if item['type'] == 'pocketcasts':
                        show_notes = f"Podcast title: {item['pod_notes']}\nShow notes: {item['episode_notes']}"

                    result = await get_caption_worker(item["url"], show_notes, item['type'])
                    if result == None:
                        move_to_error(item["url"])
                        raise Exception(f"Failed to fetch raw transcription for {item['url']}")
                    else:
                        for queue_item in urls:
                            if queue_item["url"] == item["url"]:
                                queue_item["transcript"] = result
                                break
                        print(f"Consumer: Completed fetching raw transcription {item['url']}: {result[0:20]}")
                else:
                    result = item["transcript"]
                    print(f"Consumer {name}: Fetching raw transcription from json {item['url']}: {result[0:20]}")

                formatted_result = await format_transcript(result) # format using llm
                blog_post = ''
                toc = extract_toc(formatted_result) # extract table of contents
                faq = extract_faq(formatted_result) # extract faq
                pr_url, _ = create_branch_and_pr(
                    item["title"],
                    format_pr_content(item['title'], item['url'], formatted_result, blog_post, toc, faq),
                    item['published_date']
                )
                print(f"Consumer {name}: Created PR: {pr_url}")

                move_to_done(item["url"])

            except Exception as e:
                print(f"Consumer {name}: Error processing {item['url']}: {e}")
                traceback.print_exc()
                # mark error and skip, e.g. yt fail to download subtitle
                move_to_error(item["url"])
                await asyncio.sleep(60)

        except Exception as e:
            print(f"Consumer {name}: error: {e}")
            await asyncio.sleep(60)

async def main(mode='local'):
    print('Mode: ', mode)

    producer_task = asyncio.create_task(producer(mode))
    consumer_task1 = asyncio.create_task(local_consumer(1) if mode == 'local' else sqs_consumer(1))
    consumer_task2 = asyncio.create_task(local_consumer(2) if mode == 'local' else sqs_consumer(2))

    try:
        await asyncio.gather(producer_task, consumer_task1, consumer_task2)
    except asyncio.CancelledError:
        producer_task.cancel()
        consumer_task1.cancel()
        consumer_task2.cancel()
        await asyncio.gather(producer_task, consumer_task1, consumer_task2, return_exceptions=True)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Transcript Queue")
        parser.add_argument("--mode", choices=["local", "sqs"], default='local', help="local queue or SQS queue")
        args = parser.parse_args()

        asyncio.run(main(mode=args.mode))
    except KeyboardInterrupt:
        print("Shutting down job queue...")
