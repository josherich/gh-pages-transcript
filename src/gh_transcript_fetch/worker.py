import json
import os
import asyncio
from datetime import datetime
import argparse
import traceback
import boto3
from xml.etree.ElementTree import ParseError

from .pocket_casts import get_pocketcasts_history
from .youtube import YouTubeAuthorizationRequired, get_youtube_liked_videos
from .captions import download_caption
from .transcription import transcribe_from_url
from .publishing import create_branch_and_pr, format_pr_content
from .formatting import format_transcript, extract_toc, extract_faq
from .episode_queue import open_episode_db

async def get_caption_worker(url: str, show_notes: str, type='pocketcasts'):
    print(f"Processing caption for URL {type}: {url}")
    transcription = None
    if type == 'pocketcasts':
        transcription = await transcribe_from_url(url, show_notes)
    elif type == 'youtube':
        transcription = await download_caption(url)

    print(f"Processed caption for URL {type}: {url}")
    return transcription

def pull_history(db):
    print("Fetching new Podcasts episode URLs...")
    urls, _ = get_pocketcasts_history()
    added = 0
    for item in urls:
        added += db.add({
            "type": "pocketcasts",
            "url": item["url"],
            "status": "todo",
            "title": item["title"],
            "prog_slug": item["podcastSlug"],
            "author": item["author"],
            "pod_notes": item["pod_notes"],
            "episode_notes": item["episode_notes"],
            "published_date": item["published"].split("T")[0],
        }, only_if_new_url=True)
    print(f"Added {added} new Pocketcasts URLs to queue")

    pull_youtube_history(db)


def pull_youtube_history(db):
    print("Fetching new Youtube liked video URLs...")
    added = 0
    for item in get_youtube_liked_videos():
        added += db.add({
            "type": "youtube",
            "url": item["url"],
            "status": "todo",
            "title": item["title"],
            "prog_slug": item["prog_slug"],
            "published_date": item["published_date"],
        }, only_if_new_url=True)
    print(f"Added {added} new Youtube URLs to queue")


async def producer(db):
    """Producer that fetches URLs and adds them to the queue"""
    print("Starting producer...")

    while True:
        now = datetime.now()
        print(f"{now.hour}:{now.minute}")

        # Run at 12:00
        if now.hour == 12 and now.minute == 0:
            try:
                pull_history(db)
            except YouTubeAuthorizationRequired:
                print("YouTube authorization required. Open the transcript web app and select Pull History.")
            except Exception as e:
                print(f"Error in producer: {e}")
                await asyncio.sleep(60)

        await asyncio.sleep(60)

async def sqs_consumer(name, db, sqs, queue_url):
    print(f"Starting sqs consumer {name}...")
    while True:
        processing_id = None
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
                episode = db.get(item["_id"])
                if episode is None:
                    raise LookupError(f"Episode {item['_id']} is missing from the queue")
                if episode["status"] == "done":
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                    continue
                db.set_status(item["_id"], "processing")
                processing_id = item["_id"]
                print(f"Consumer {name}: Processing message {item}")
                try:
                    show_notes = ''
                    if item['type'] == 'pocketcasts':
                        show_notes = f"Podcast title: {item['pod_notes']}\nShow notes: {item['episode_notes']}"

                    result = await get_caption_worker(item["url"], show_notes, item['type'])
                    if result == None:
                        raise Exception(f"Failed to fetch raw transcription for {item['url']}")

                    formatted_result = await format_transcript(result) # format using llm
                    blog_post = ''
                    toc = extract_toc(formatted_result) # extract table of contents
                    faq = extract_faq(formatted_result) # extract faq
                    pr_url, _ = create_branch_and_pr(
                        item["title"],
                        format_pr_content(item['title'], item['url'], formatted_result, blog_post, toc, faq),
                        item['published_date'],
                        item["prog_slug"] if 'prog_slug' in item else None
                    )
                    print(f"Consumer {name}: Created PR: {pr_url}")

                    db.set_status(processing_id, "done")
                    processing_id = None
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
            if processing_id is not None:
                db.set_status(processing_id, "error")
            await asyncio.sleep(60)


async def local_consumer(name, db):
    """Consumer that processes URLs from the queue"""
    print(f"Starting local consumer {name}...")

    while True:
        try:
            claim = db.claim_next()
            if claim is None:
                print(f"Consumer {name}: No URLs to process, sleeping...")
                await asyncio.sleep(60)
                continue

            item, claim_token = claim
            episode_id = item["_id"]
            print(f"Consumer {name}: Processing {item['url']}")
            try:
                if "transcript" not in item:
                    show_notes = ''
                    if item['type'] == 'pocketcasts':
                        show_notes = f"Podcast title: {item['pod_notes']}\nShow notes: {item['episode_notes']}"

                    result = await get_caption_worker(item["url"], show_notes, item['type'])
                    if result == None:
                        raise Exception(f"Failed to fetch raw transcription for {item['url']}")
                    if not db.save_transcript(episode_id, result, claim_token):
                        continue
                    print(f"Consumer: Completed fetching raw transcription {item['url']}: {result[0:20]}")
                else:
                    result = item["transcript"]
                    print(f"Consumer {name}: Fetching saved raw transcription {item['url']}: {result[0:20]}")

                formatted_result = await format_transcript(result) # format using llm
                blog_post = ''
                toc = extract_toc(formatted_result) # extract table of contents
                faq = extract_faq(formatted_result) # extract faq
                if not db.owns_claim(episode_id, claim_token):
                    continue
                pr_url, _ = create_branch_and_pr(
                    item["title"],
                    format_pr_content(item['title'], item['url'], formatted_result, blog_post, toc, faq),
                    item['published_date'],
                    item["prog_slug"] if 'prog_slug' in item else None
                )
                print(f"Consumer {name}: Created PR: {pr_url}")

                db.set_status(episode_id, "done", claim_token=claim_token)

            except asyncio.CancelledError:
                db.set_status(episode_id, "queued", claim_token=claim_token)
                raise
            except Exception as e:
                print(f"Consumer {name}: Error processing {item['url']}: {e}")
                traceback.print_exc()
                # mark error and skip, e.g. yt fail to download subtitle
                db.set_status(episode_id, "error", claim_token=claim_token)
                await asyncio.sleep(60)

        except Exception as e:
            print(f"Consumer {name}: error: {e}")
            await asyncio.sleep(60)

async def main(mode='local'):
    print('Mode: ', mode)

    db = open_episode_db()
    if mode == "local":
        consumers = [local_consumer(name, db) for name in (1, 2)]
    else:
        sqs = boto3.client("sqs", region_name="us-west-1")
        queue_url = os.environ["QUEUE_URL"]
        consumers = [sqs_consumer(name, db, sqs, queue_url) for name in (1, 2)]

    producer_task = asyncio.create_task(producer(db))
    consumer_task1, consumer_task2 = [asyncio.create_task(consumer) for consumer in consumers]

    try:
        await asyncio.gather(producer_task, consumer_task1, consumer_task2)
    except asyncio.CancelledError:
        producer_task.cancel()
        consumer_task1.cancel()
        consumer_task2.cancel()
        await asyncio.gather(producer_task, consumer_task1, consumer_task2, return_exceptions=True)

def cli():
    try:
        parser = argparse.ArgumentParser(description="Transcript Queue")
        parser.add_argument("--mode", choices=["local", "sqs"], default='local', help="local queue or SQS queue")
        args = parser.parse_args()

        asyncio.run(main(mode=args.mode))
    except KeyboardInterrupt:
        print("Shutting down job queue...")


if __name__ == "__main__":
    cli()
