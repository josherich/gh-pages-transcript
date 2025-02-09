from youtube_transcript_api import YouTubeTranscriptApi

def format_caption(caption):
    return "\n".join([f"{line['start']} - {line['duration']}: {line['text']}" for line in caption])

def download_caption(video_url):
    video_id = video_url.split("v=")[1]
    captions = YouTubeTranscriptApi.get_transcript(video_id)
    caption_lines = format_caption(captions)
    return caption_lines

if __name__ == "__main__":
    video_url = "https://www.youtube.com/watch?v=a-1xJmfYxyU"
    print(download_caption(video_url))
