"""Seed the database with publication sources supplied at runtime.

The script accepts either JSON (preferred) or newline-delimited text. Examples:

JSON array:
    [
      {"label": "Beamline", "url": "https://example"},
      "https://example-two"
    ]

Plain text (label optional, separated by "|"):
    Beamline A|https://example
    https://example-two
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

from db import get_connection, init_db, upsert_source


def _parse_json_payload(text: str) -> List[Tuple[str, str | None]]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON payload must be a list of strings or objects")
    entries: List[Tuple[str, str | None]] = []
    for item in data:
        if isinstance(item, str):
            entries.append((item.strip(), None))
        elif isinstance(item, dict) and "url" in item:
            entries.append((str(item["url"]).strip(), item.get("label")))
        else:
            raise ValueError(f"Unsupported entry: {item!r}")
    return entries


def _parse_plaintext(text: str) -> List[Tuple[str, str | None]]:
    entries: List[Tuple[str, str | None]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            label, url = line.split("|", 1)
            entries.append((url.strip(), label.strip() or None))
        else:
            entries.append((line, None))
    return entries


def load_sources(payload: str) -> List[Tuple[str, str | None]]:
    payload = payload.strip()
    if not payload:
        return []
    try:
        return _parse_json_payload(payload)
    except json.JSONDecodeError:
        return _parse_plaintext(payload)


def seed(sources: List[Tuple[str, str | None]]):
    init_db()
    with get_connection() as conn:
        inserted = 0
        for url, label in sources:
            if not url:
                continue
            upsert_source(conn, url, label)
            inserted += 1
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Seed publication sources from stdin or a file")
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default="-",
        help="Path to a file containing sources (default: stdin)",
    )
    args = parser.parse_args()

    if args.file == "-":
        payload = sys.stdin.read()
    else:
        payload = Path(args.file).read_text(encoding="utf-8")

    sources = load_sources(payload)
    total = seed(sources)
    print(f"Seeded {total} sources")


if __name__ == "__main__":
    main()
