import requests
from openai import OpenAI
from pydub import AudioSegment
from pydub.utils import make_chunks
import os
from env import *

client = OpenAI()

def download_audio(url, filename):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36'}
    response = requests.get(url, allow_redirects=True, headers=headers)
    if response.status_code == 200:
        with open(filename, "wb") as file:
            file.write(response.content)
        return split_mp3(filename)
    else:
        raise Exception(f"Failed to download file: {response.status_code}")

def transcribe_audio(file_path):
    print(f"Transcribing {file_path}")
    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        print(f"Transcription for {file_path}: {response.text}")
        return response.text

def transcribe_from_url(audio_url):
    local_filename = "temp_audio.mp3"
    try:
        part_names = download_audio(audio_url, local_filename)
        transcriptions = [transcribe_audio(part_name) for part_name in part_names]
        transcription_lines = "/n".join(transcriptions)
        return transcription_lines
    except Exception as e:
        return None

def split_mp3(input_path, output_prefix="output_part_", target_mb=20):
    """
    Split an MP3 file into chunks smaller than specified megabytes
    Works best with constant bitrate (CBR) MP3 files

    :param input_path: Path to input MP3 file
    :param output_prefix: Prefix for output files
    :param target_mb: Target maximum size in megabytes (default 20)
    """
    # Get file size and calculate target bytes
    file_size_bytes = os.path.getsize(input_path)
    target_bytes = target_mb * 1024 * 1024  # Convert MB to bytes

    # Load audio file
    audio = AudioSegment.from_mp3(input_path)

    # Calculate duration and bitrate
    duration_sec = len(audio) / 1000  # Audio length in seconds
    bitrate_bps = (file_size_bytes * 8) / duration_sec  # bits per second
    print(f"Length: {duration_sec} s, Bitrate: {bitrate_bps / 1000} kbps")

    # Calculate chunk duration needed to stay under target size
    chunk_duration_sec = (target_bytes * 8) / bitrate_bps
    chunk_length_ms = chunk_duration_sec * 1000  # Convert to milliseconds

    # Create chunks
    chunks = make_chunks(audio, chunk_length_ms)

    # Export with the same calculated bitrate
    bitrate_str = f"{int(bitrate_bps // 1000)}k"
    chunk_names = []
    for i, chunk in enumerate(chunks):
        chunk_name = f"{output_prefix}{i+1}.mp3"
        chunk.export(chunk_name, format="mp3", bitrate=bitrate_str)
        print(f"Exported {chunk_name}")
        chunk_names.append(chunk_name)

    return chunk_names

if __name__ == "__main__":
    # Example Usage
    input_mp3 = "temp_audio.mp3"  # Replace with your file path
    transcribe_from_url("http://alioss.gcores.com/uploads/audio/9451ecf4-5800-4325-b5c5-8df13608c18b.mp3")
