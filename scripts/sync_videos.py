

def download_thumb(url, target):
    if not url or not url.startswith("https://"):
        log("SKIP thumbnail: missing or invalid HTTPS URL")
        return False
    try:
        raw, content_type = fetch(url, timeout=REQUEST_TIMEOUT)
        if len(raw) > MAX_THUMB_BYTES:
            log("SKIP thumbnail: image exceeds size limit")
            return False
        if content_type and not content_type.lower().startswith("image/"):
            log(f"SKIP thumbnail: unexpected content type {content_type}")
            return False
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(raw)) as source:
            image = source.convert("RGB")
            image.thumbnail((960, 720))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "WEBP", quality=84, method=4)
        return True
    except Exception as error:
        log(f"Thumbnail unavailable {url}: {error}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="scan every WordPress post (use for initial import)")
    args = parser.parse_args()

    log("Sync script started.")
    log(f"Mode: {'FULL import' if args.full else 'recent 100 posts'}")
    log(f"Catalog path: {DATA}; exists: {DATA.exists()}")
    if not DATA.exists():
        raise RuntimeError(f"Missing catalog file: {DATA}")

    db = json.loads(DATA.read_text(encoding="utf-8"))
    if not isinstance(db, dict) or not isinstance(db.get("videos"), list):
        raise RuntimeError("Catalog JSON must contain a videos array.")

    videos = db["videos"]
    known_urls = {decode_url(v.get("video", {})) for v in videos if isinstance(v, dict)}
    known_urls.discard("")
    known_source_ids = {
        str(v.get("source", {}).get("site_id", ""))
        for v in videos
        if isinstance(v, dict) and isinstance(v.get("source"), dict)
    }
    known_source_ids.discard("")
    numeric_ids = [
        int(match.group(1))
        for video in videos
        if (match := re.fullmatch(r"video(\d+)", str(video.get("id", ""))))
    ]
    next_num = max(numeric_ids or [0]) + 1

    posts = list(get_posts(args.full))
    log(f"Posts selected for scan: {len(posts)}")
    additions = []
    seen_new_urls = set()
    seen_new_source_ids = set()

    for index, post in enumerate(posts, start=1):
        source_id = str(post.get("id", ""))
        if source_id and (source_id in known_source_ids or source_id in seen_new_source_ids):
            log(f"[{index}/{len(posts)}] SKIP known source post {source_id}")
            continue
        log(f"[{index}/{len(posts)}] Checking: {post.get('link', '(no link)')}")
        item = parse_post(post)
        if not item:
            continue
        video_url = item["video_url"]
        if video_url in known_urls or video_url in seen_new_urls:
            log(f"SKIP duplicate video: {item['title']}")
            if source_id:
                seen_new_source_ids.add(source_id)
            continue

        video_id = f"video{next_num:03d}"
        thumb_path = THUMBS / f"{video_id}.webp"
        if not download_thumb(item["thumb_url"], thumb_path):
            try:
                thumb_path.unlink(missing_ok=True)
            except OSError:
                pass
            log(f"SKIP no usable thumbnail: {item['title']}")
            continue

        additions.append({
            "id": video_id,
            "title": item["title"] or f"Video {next_num}",
            "thumb": f"assets/thumb/{video_id}.webp",
            "views": "—",
            "duration": "",
            "video": encode_url(video_url, video_id),
            "source": {"site_id": item["source_id"], "url": item["link"], "date": item["date"]},
        })
        known_urls.add(video_url)
        if source_id:
            seen_new_source_ids.add(source_id)
        next_num += 1
        log(f"FOUND new video: {item['title']}")

    if additions:
        db["videos"] = additions + videos
        db["version"] = str(db.get("version", "1.3"))
        db["updated"] = datetime.now(timezone.utc).isoformat()
        DATA.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"New MP4 videos added: {len(additions)}")
    log("Sync script finished.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FATAL: {error}", file=sys.stderr, flush=True)
        raise
