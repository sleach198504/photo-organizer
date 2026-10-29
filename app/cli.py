from __future__ import annotations

import argparse
import logging

from . import content_tagging
from .actions import execute_approved_recommendations
from .config import Config
from .dedupe import run_dedupe
from .db import session
from .indexer import run_index
from .paths import CONFIG_PATH
from .quality import flag_blurry_photos, run_quality_scoring



def cmd_index(args) -> None:
    config = Config.load(CONFIG_PATH)
    if not config.source_dir.exists():
        raise SystemExit(f"source_dir does not exist: {config.source_dir}")
    with session(config.db_path) as conn:
        stats = run_index(conn, config.source_dir, exclude_dir=config.quarantine_dir)
    print(
        f"Scanned: {stats['scanned']}  Indexed/updated: {stats['indexed']}  "
        f"Unchanged: {stats['skipped']}  Errors: {stats['errors']}"
    )
    if stats["errors"]:
        print(f"({stats['errors']} files could not be read - see log output above)")


def cmd_analyze(args) -> None:
    config = Config.load(CONFIG_PATH)
    with session(config.db_path) as conn:
        quality_stats = run_quality_scoring(conn)
        blurry_count = flag_blurry_photos(conn)
        dedupe_stats = run_dedupe(
            conn, config.near_duplicate_hash_distance, config.auto_quarantine_exact_duplicates
        )
        if content_tagging.models_downloaded():
            try:
                tag_stats = content_tagging.run_content_tagging(conn, content_tagging.create_backend())
            except content_tagging.ModelUnavailable as exc:
                print(exc)
                tag_stats = None
        else:
            tag_stats = None
        auto_moved = execute_approved_recommendations(conn, config)
    print(f"Scored for blur: {quality_stats['scored']}  Errors: {quality_stats['errors']}")
    print(f"Blurry photos flagged: {blurry_count}")
    print(
        f"Exact-duplicate groups: {dedupe_stats['exact_groups']}  "
        f"Near-duplicate groups: {dedupe_stats['near_groups']}"
    )
    if tag_stats is not None:
        print(f"Content-tagged: {tag_stats['tagged']}  Flagged: {tag_stats['flagged']}  Errors: {tag_stats['errors']}")
    else:
        print("Content tagging skipped - model not installed (run Setup again)")
    if auto_moved:
        print(f"Auto-moved {auto_moved} exact duplicate(s) to the review folder (auto_quarantine_exact_duplicates is on)")


def cmd_review(args) -> None:
    import webbrowser

    import uvicorn

    from .web.app import create_app

    app = create_app()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Opening Photo Organizer at {url} (Ctrl+C here to stop)")
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="photo-organizer")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("index", help="Scan the source folder and update the photo index")
    sub.add_parser("analyze", help="Score blur and find duplicate/near-duplicate photos")
    review_parser = sub.add_parser("review", help="Open the review screen in your browser")
    review_parser.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()
    if args.command == "index":
        cmd_index(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "review":
        cmd_review(args)


if __name__ == "__main__":
    main()
