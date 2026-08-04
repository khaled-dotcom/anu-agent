#!/usr/bin/env python3
"""Rebuild data/knowledge.json from the live ANU site.

Usage:
    python scripts/ingest.py              # crawl the default page list
    python scripts/ingest.py --merge      # keep hand-written seed chunks too

Run it weekly from cron. Admission announcements and fees change every intake,
and a stale knowledge base is the main way a bot like this starts lying.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "knowledge.json"
BASE = "https://anu.edu.eg"

SEED_PATHS = [
    "/ar/home",
    "/ar/about",
    "/ar/programs",
    "/ar/admission",
    "/ar/tuition",
    "/ar/scholarship-aid",
    "/ar/handbook",
    "/ar/academic_catalogs",
    "/ar/articles",
    "/ar/contact",
    "/en/about",
    "/en/programs",
    "/en/admission",
    "/en/tuition",
]

# Follow links that stay inside these sections (programs and news have numeric
# sub-pages that carry the details students actually ask about).
FOLLOW = re.compile(r"^/(ar|en)/(programs|study_fields|articles)/\d+$")

CHUNK_CHARS = 900
BOILERPLATE = re.compile(
    r"(جامعة الإسكندرية الأهلية، جامعة تعتمد على البرامج، تأسست عام 2022)"
)


def clean(soup: BeautifulSoup) -> tuple[str, str]:
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return title, text


def split(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries, never mid-sentence."""
    parts, current = [], ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(current) + len(line) + 1 > size and current:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return [p for p in parts if len(p) > 80]


def crawl(paths: list[str], max_pages: int = 120) -> list[dict]:
    seen: set[str] = set()
    queue = list(paths)
    chunks: list[dict] = []

    with httpx.Client(
        timeout=25.0, follow_redirects=True, headers={"User-Agent": "ANU-Agent/1.0"}
    ) as client:
        while queue and len(seen) < max_pages:
            path = queue.pop(0)
            if path in seen:
                continue
            seen.add(path)

            url = BASE + path
            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {path}: {exc}", file=sys.stderr)
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            for anchor in soup.find_all("a", href=True):
                href = anchor["href"].split("#")[0].split("?")[0].rstrip("/")
                if href.startswith(BASE):
                    href = href[len(BASE) :]
                if FOLLOW.match(href) and href not in seen:
                    queue.append(href)

            title, text = clean(soup)
            body = BOILERPLATE.sub("", text)
            pieces = split(body)
            print(f"  {path}: {len(pieces)} chunk(s)")
            for i, piece in enumerate(pieces):
                chunks.append(
                    {
                        "id": f"{path.strip('/').replace('/', '-')}-{i}",
                        "title": title or path,
                        "url": url,
                        "text": piece,
                    }
                )
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merge", action="store_true", help="keep existing chunks")
    args = parser.parse_args()

    print(f"crawling {BASE} ...")
    chunks = crawl(SEED_PATHS)

    if args.merge and OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8")).get("chunks", [])
        known = {c["id"] for c in chunks}
        chunks += [c for c in existing if c["id"] not in known]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"last_sync": date.today().isoformat(), "chunks": chunks},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {len(chunks)} chunks to {OUT}")


if __name__ == "__main__":
    main()
