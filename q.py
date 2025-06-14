import json
import asyncio
from datetime import datetime
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
from db import LocalStorageDb

# Initialize database
db = LocalStorageDb({'namespace': 'transcript_queue', 'storage_path': './data'})
db.add_collection('episodes')

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

    # --------- Add Pocketcasts URLs ---------
    urls, _ = get_pocketcasts_history()
    i = 0
    for item in urls:
        if not db.episodes.find_one({'url': item['url']}):
            i += 1
            all_messages.append(PocketCast(
                url=item['url'],
                title=item['title'],
                author=item['author'],
                pod_notes=item['pod_notes'],
                episode_notes=item['episode_notes'],
                published_date=item['published'].split('T')[0]
            ))
            episode_data = {
                'type': 'pocketcasts',
                'url': item['url'],
                'status': 'todo',
                'title': item['title'],
                'author': item['author'],
                'pod_notes': item['pod_notes'],
                'episode_notes': item['episode_notes'],
                'published_date': item['published'].split('T')[0]
            }
            db.episodes.upsert(episode_data)
    print(f"Added {i} new Pocketcasts URLs to queue")

    # ----------- Add Youtube URLs -----------
    print("Fetching new Youtube liked video URLs...")
    yt_urls = get_youtube_liked_videos()
    i = 0
    for item in yt_urls:
        if not db.episodes.find_one({'url': item['url']}):
            i += 1
            all_messages.append(Youtube(
                url=item['url'],
                title=item['title'],
                published_date=item['published_date']
            ))
            episode_data = {
                'type': 'youtube',
                'url': item['url'],
                'status': 'todo',
                'title': item['title'],
                'published_date': item['published_date']
            }
            db.episodes.upsert(episode_data)

    print(f"Added {i} new Youtube URLs to queue")
    return all_messages

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
    try:
        # Find the item by URL and update its status
        item = db.episodes.find_one({'url': url})
        if not item:
            raise Exception(f"Can not find episode: ")
        item['status'] = status
        db.episodes.upsert(item)
    except Exception as e:
        print(f"Error updating status for {url}: {e}")

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
                WaitTimeSeconds=2,
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
            # FIXME: Race condition: the other consumer could grab the same item
            item = db.episodes.find_one({ 'status': 'queued' })
            if not item:
                print(f"Consumer {name}: No URLs to process, sleeping...")
                await asyncio.sleep(60)
                continue

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
                        # Update the item with transcript
                        item = db.queue.find_one({'url': item['url']})
                        item['transcript'] = result
                        db.episodes.upsert(item)
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
