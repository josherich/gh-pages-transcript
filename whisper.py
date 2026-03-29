import os
import json
import subprocess
import asyncio
import traceback
import tempfile
import requests
from openai import OpenAI
from pydub import AudioSegment
from pydub.utils import make_chunks
from env import *

client = OpenAI()
whisper_local = os.getenv("WHISPER_LOCAL", None)
fireredasr2s_local = os.getenv("FIREREDASR2S_LOCAL", None)

def download_audio(url, filename):
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 6.1; WOW64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/56.0.2924.76 Safari/537.36'
        )
    }
    url_extension = url.split(".")[-1]
    filename_with_ext = f"{filename}.{url_extension}"

    response = requests.get(url, allow_redirects=True, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to download file: {response.status_code}")

    with open(filename_with_ext, "wb") as file:
        file.write(response.content)
    if whisper_local or fireredasr2s_local:
        return filename_with_ext
    else:
        return split_mp3(filename_with_ext)

def transcribe_audio(file_path):
    print(f"Transcribing {file_path}")
    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        print(f"Transcription for {file_path}: {response.text}")
        return response.text

async def transcribe_audio_with_local_whisper(file_path, show_notes):
    print(f"Transcribing w/ local whisper {file_path} with show notes {show_notes}")

    if not file_path.endswith(".wav"):
        convert_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "temp_audio.wav"
        ]
        subprocess.run(convert_cmd, check=True)
        file_path = "temp_audio.wav"

    whisper_cmd = [
        f"{whisper_local}/build/bin/whisper-cli",
        "-f", file_path,
        "-m", f"{whisper_local}/models/ggml-large-v3-turbo-q5_0.bin",
        "--prompt", f'"{show_notes}"',
        "-t", "8",
        "--output-txt"
    ]

    proc = await asyncio.create_subprocess_exec(
        *whisper_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    print(f'[{whisper_cmd!r} exited with {proc.returncode}]')
    if stdout:
        print(f"[stdout]\n{stdout.decode('utf-8', errors='ignore')}")
    if stderr:
        print(f"[stderr]\n{stderr.decode('utf-8', errors='ignore')}")

    # FIXME: Race condition: might be overwritten by the other process
    with open("temp_audio.wav.txt", "r") as f:
        transcription = f.read()

    return [transcription]

async def transcribe_audio_with_fireredasr2s(file_path):
    print(f"Transcribing w/ FireRedASR2S {file_path}")

    if not file_path.endswith(".wav"):
        convert_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "temp_audio.wav"
        ]
        subprocess.run(convert_cmd, check=True)
        file_path = "temp_audio.wav"

    outdir = tempfile.mkdtemp()
    cli_path = os.path.join(fireredasr2s_local, "fireredasr2s", "fireredasr2s-cli")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{fireredasr2s_local}:{env.get('PYTHONPATH', '')}"
    env["PATH"] = f"{os.path.join(fireredasr2s_local, 'fireredasr2s')}:{env.get('PATH', '')}"

    fireredasr2s_cmd = [
        "python", cli_path,
        "--wav_paths", file_path,
        "--outdir", outdir
    ]

    proc = await asyncio.create_subprocess_exec(
        *fireredasr2s_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env
    )
    stdout, stderr = await proc.communicate()

    print(f'[{fireredasr2s_cmd!r} exited with {proc.returncode}]')
    if stdout:
        print(f"[stdout]\n{stdout.decode('utf-8', errors='ignore')}")
    if stderr:
        print(f"[stderr]\n{stderr.decode('utf-8', errors='ignore')}")

    result_path = os.path.join(outdir, "result.jsonl")
    with open(result_path, "r") as f:
        results = [json.loads(line) for line in f if line.strip()]
    transcription = " ".join(r.get("text", "") for r in results)
    return [transcription]

async def transcribe_from_url(audio_url, show_notes):
    local_filename = "temp_audio"
    try:
        part_names = download_audio(audio_url, local_filename)
        if fireredasr2s_local:
            transcriptions = await transcribe_audio_with_fireredasr2s(part_names)
        elif whisper_local:
            transcriptions = await transcribe_audio_with_local_whisper(part_names, show_notes)
        else:
            transcriptions = [transcribe_audio(part_name) for part_name in part_names]
        transcription_lines = "/n".join(transcriptions)
        return transcription_lines
    except Exception as e:
        print(f"Error during transcription: {e}")
        print(f"stack trace: {traceback.format_exc()}")
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
    print(transcribe_from_url("http://alioss.gcores.com/uploads/audio/9451ecf4-5800-4325-b5c5-8df13608c18b.mp3", 'gcores'))
