import os
from env import *
import asyncio
import requests

from youtube_transcript_api import YouTubeTranscriptApi
from bilibili_api import video, Credential

def format_caption(caption):
    return "\n".join([f"{line['start']} - {line['duration']}: {line['text']}" for line in caption])

async def download_caption(video_url):
    if "youtube" in video_url:
        return download_caption_youtube(video_url)
    elif "bilibili" in video_url:
        return await download_caption_bilibili(video_url)
    else:
        return "Unsupported video platform"

def download_caption_youtube(video_url):
    video_id = video_url.split("v=")[1]
    captions = YouTubeTranscriptApi.get_transcript(video_id)
    caption_lines = format_caption(captions)
    return caption_lines

SESSDATA = os.getenv("BILIBILI_SESSDATA")
BUVID3 = os.getenv("BILIBILI_BUVID3")
BILI_JCT = os.getenv("BILIBILI_BILI_JCT")
async def download_caption_bilibili(video_url):
    video_id = video_url.split("/video/")[1].split("/")[0]
    credential = Credential(sessdata=SESSDATA, bili_jct=BILI_JCT, buvid3=BUVID3)
    try:
        v = video.Video(bvid=video_id, credential=credential)
        info = await v.get_info()
        cid = info['pages'][0]['cid']
        subtitle_info = await v.get_subtitle(cid)
        subtitle_url = subtitle_info['subtitles'][0]['subtitle_url']
        subtitle_json = requests.get('https:' + subtitle_url).json()
        subittle_text = '\n'.join(map(lambda line: line['content'], subtitle_json['body']))
        return subittle_text
    except Exception as e:
        print('Runtime error while parsing bilibili video subtitle:', e)
        raise e

if __name__ == "__main__":
    video_url = "https://www.youtube.com/watch?v=a-1xJmfYxyU"
    print(download_caption(video_url))

    bilibili_video_url = "https://www.bilibili.com/video/BV1sb9ZYmESM/"
    subtitle = asyncio.run(download_caption_bilibili(bilibili_video_url))
    print(subtitle)
