"""Format a local transcript and print its table of contents."""

import argparse
import asyncio
from pathlib import Path

from gh_transcript_fetch.formatting import extract_toc, format_transcript


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args()
    formatted = await format_transcript(args.transcript.read_text(encoding="utf-8"))
    print(formatted)
    print(extract_toc(formatted))


if __name__ == "__main__":
    asyncio.run(main())
