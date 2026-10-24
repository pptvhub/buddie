#!/usr/bin/env python3
"""Import direct HTTPS MP4 videos from WordPress into the existing catalog.

Default mode scans the newest 100 posts (for scheduled updates).
Use --full for the initial import of all WordPress posts.
The catalog is only written after the selected API scan completes successfully.
"""
import argparse
import base64
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API = os.getenv("WORDPRESS_API", "https://baddiehub.com/wp-json/wp/v2/posts")
DATA = Path("assets/data/videos.json")
THUMBS = Path("assets/thumb")
USER_AGENT = "Mozilla/5.0 (compatible; VideoCatalogSync/2.0)"
REQUEST_TIMEOUT = 15
MAX_THUMB_BYTES = 8 * 1024 * 1024
PER_PAGE = 100


def log(message):
    print(message, flush=True)


def fetch(url, timeout=REQUEST_TIMEOUT):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json,*/*",
    })
    with urlopen(req, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def decode_url(video):
    try:
        raw = base64.b64decode(video["encrypted"]).decode("latin1")[::-1]
        key = video["iv"]
        if not key:
            return ""
        return "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(raw))
    except Exception:
        return ""


def direct_mp4(url):
    try:
        parsed = urlparse(html.unescape(url.strip()))
        return parsed.scheme == "https" and bool(parsed.netloc) and parsed.path.lower().endswith(".mp4")
    except Exception:
        return False


def meta(content, key):
    escaped_key = re.escape(key)
    pattern = r"<meta\b(?=[^>]*\b(?:itemprop|property|name)\s*=\s*[\"']" + escaped_key + r"[\"'])[^>]*>"
    for tag in re.findall(pattern, content, flags=re.I):
        match = re.search(r"""\bcontent\s*=\s*["']([^"']+)["']""", tag, flags=re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    match = re.search(r"""["']""" + escaped_key + r"""["']\s*:\s*["']([^"']+)["']""", content, flags=re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def find_video_url(content):
    value = meta(content, "contentUrl")
    if direct_mp4(value):
        return value
    candidates = re.findall(
        r"""https?://[^"'\s<>\\]+?\.mp4(?:\?[^"'\s<>\\]*)?""",
        content,
        flags=re.I,
    )
    for value in candidates:
        value = html.unescape(value).replace("\\/", "/").rstrip("),;")
        if direct_mp4(value):
            return value
    return ""


def parse_post(post):
    link = post.get("link", "")
    if not link:
        log("SKIP: post has no link")
        return None
    try:
        raw, _ = fetch(link)
