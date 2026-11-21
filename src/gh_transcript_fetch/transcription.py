import asyncio
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import traceback
from urllib.parse import urlsplit

import requests
from openai import OpenAI
from pydub import AudioSegment
from pydub.utils import make_chunks

def download_audio(url, directory):
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 6.1; WOW64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/56.0.2924.76 Safari/537.36'
        )
    }
    suffix = Path(urlsplit(url).path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".mp3"
    audio_path = directory / f"audio{suffix}"

    with requests.get(url, timeout=(10, 60), stream=True, headers=headers) as response:
        response.raise_for_status()
        with audio_path.open("wb") as audio_file:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                audio_file.write(chunk)
    return audio_path


def transcribe_audio(file_path, client):
    print(f"Transcribing {file_path}")
    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        print(f"Transcription for {file_path}: {response.text}")
        return response.text

async def transcribe_audio_with_local_whisper(file_path, show_notes, whisper_dir):
    print(f"Transcribing w/ local whisper {file_path} with show notes {show_notes}")

    if file_path.suffix.lower() != ".wav":
        wav_path = file_path.with_suffix(".wav")
        convert_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path
        ]
        subprocess.run(convert_cmd, check=True)
        file_path = wav_path

    model_name = os.getenv("WHISPER_MODEL_NAME", "ggml-large-v3-turbo.bin")
    whisper_cmd = [
        whisper_dir / "build" / "bin" / "whisper-cli",
        "-f", file_path,
        "-m", whisper_dir / "models" / model_name,
        "--prompt", f'"{show_notes}"',
        "-t", "8",
        "--output-txt"
    ]

    proc = await asyncio.create_subprocess_exec(
        *whisper_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.communicate()
        raise

    print(f'[{whisper_cmd!r} exited with {proc.returncode}]')
    if stdout:
        print(f"[stdout]\n{stdout.decode('utf-8', errors='ignore')}")
    if stderr:
        print(f"[stderr]\n{stderr.decode('utf-8', errors='ignore')}")

    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, whisper_cmd, stdout, stderr)
    return Path(f"{file_path}.txt").read_text(encoding="utf-8")


async def transcribe_from_url(audio_url, show_notes):
    try:
        with TemporaryDirectory(prefix="gh-transcript-audio-") as temp_dir:
            audio_path = download_audio(audio_url, Path(temp_dir))
            whisper_local = os.getenv("WHISPER_LOCAL")
            if whisper_local:
                whisper_dir = Path(whisper_local).expanduser()
                return await transcribe_audio_with_local_whisper(audio_path, show_notes, whisper_dir)

            with OpenAI() as client:
                transcriptions = [transcribe_audio(part, client) for part in split_mp3(audio_path)]
            return "\n".join(transcriptions)
    except Exception as e:
        print(f"Error during transcription: {e}")
        print(f"stack trace: {traceback.format_exc()}")
        return None


def split_mp3(input_path, target_mb=20):
    """
    Split an MP3 file into chunks smaller than specified megabytes
    Works best with constant bitrate (CBR) MP3 files

    :param input_path: Path to input MP3 file
    :param target_mb: Target maximum size in megabytes (default 20)
    """
    # Get file size and calculate target bytes
    input_path = Path(input_path)
    file_size_bytes = input_path.stat().st_size
    target_bytes = target_mb * 1024 * 1024  # Convert MB to bytes

    # Load audio file
    audio = AudioSegment.from_file(input_path)

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
        chunk_name = input_path.with_name(f"part-{i + 1}.mp3")
        with chunk.export(chunk_name, format="mp3", bitrate=bitrate_str):
            pass
        print(f"Exported {chunk_name}")
        chunk_names.append(chunk_name)

    return chunk_names
