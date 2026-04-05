"""
migrate_history.py — One-time migration script.

Replays git history of seen.json to populate the SQLite database with:
  - All listings ever tracked (listings table)
  - Price changes over time (price_history table)

Run once locally before switching workflows to the new system:
    python scripts/migrate_history.py

This script is read-only with respect to git — it never modifies the repo.
Expect it to take 5-15 minutes for a large git history.
"""

import subprocess
import json
import os
import sys
import datetime
import sqlite3
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import init_db, DB_PATH

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def get_commits_with_seen_json():
    """Return list of (commit_hash, commit_datetime) for commits that touched seen.json."""
    result = subprocess.run(
        ["git", "log", "--format=%H %aI", "--", "seen.json"],
        capture_output=True, text=True, check=True
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            commits.append((parts[0], parts[1]))
    # Reverse so we process oldest → newest
    commits.reverse()
    return commits


def get_seen_json_at_commit(commit_hash: str) -> dict:
    """Return the parsed seen.json at a given commit, or {} on error."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_hash}:seen.json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout)
    except Exception:
        return {}


def migrate():
    init_db()

    logger.info("Fetching git history for seen.json...")
    commits = get_commits_with_seen_json()
    logger.info(f"Found {len(commits)} commits that touched seen.json")

    if not commits:
        logger.warning("No commits found — nothing to migrate")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")  # Speed up bulk insert; we'll re-enable after

    # Track price per listing across commits: {token: last_known_price}
    price_tracker: dict[str, int] = {}

    prev_seen: dict = {}
    total_inserted = 0
    total_price_changes = 0

    for i, (commit_hash, commit_dt) in enumerate(commits):
        if i % 100 == 0:
            logger.info(f"  Processing commit {i+1}/{len(commits)}...")

        current_seen = get_seen_json_at_commit(commit_hash)
        if not current_seen:
            continue

        # Normalize commit timestamp to ISO format
        try:
            recorded_at = commit_dt[:19].replace("T", " ")  # '2025-07-15 14:32:01'
        except Exception:
            recorded_at = "2025-01-01 00:00:00"

        for url, data in current_seen.items():
            token = data.get("token") or url.split("/")[-1]
            if not token:
                continue

            price = data.get("price", 0)
            rooms = data.get("rooms")
            street = data.get("street", "לא ידוע")
            neighborhood = data.get("neighborhood", "לא ידוע")
            city = data.get("city", "לא ידוע")
            floor = data.get("floor")
            sqm = data.get("sqm", 0)
            phone = data.get("phone")
            is_private = 1 if data.get("is_private") else 0
            cover_image = data.get("cover_image")

            # Insert/update listing (first_seen_at set only on first insert)
            existing = conn.execute(
                "SELECT price, first_seen_at FROM listings WHERE token = ?", (token,)
            ).fetchone()

            if existing is None:
                conn.execute("""
                    INSERT INTO listings
                        (token, url, source, price, rooms, street, neighborhood, city,
                         floor, sqm, phone, is_private, cover_image, first_seen_at, last_seen_at, is_active)
                    VALUES (?, ?, 'yad2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (token, url, price, rooms, street, neighborhood, city,
                      floor, sqm, phone, is_private, cover_image, recorded_at, recorded_at))

                # Record initial price
                conn.execute("""
                    INSERT INTO price_history (token, price, recorded_at, change_type)
                    VALUES (?, ?, ?, 'initial')
                """, (token, price, recorded_at))

                price_tracker[token] = price
                total_inserted += 1
            else:
                # Update last_seen_at and possibly price
                conn.execute(
                    "UPDATE listings SET last_seen_at = ?, price = ?, phone = COALESCE(?, phone), "
                    "cover_image = COALESCE(?, cover_image) WHERE token = ?",
                    (recorded_at, price, phone, cover_image, token)
                )

                # Check for price change
                last_price = price_tracker.get(token, existing[0])
                if price and last_price and price != last_price:
                    change_type = "increase" if price > last_price else "decrease"
                    delta = price - last_price
                    delta_pct = round((delta / last_price) * 100, 2) if last_price else None
                    conn.execute("""
                        INSERT INTO price_history
                            (token, price, recorded_at, change_type, previous_price, delta, delta_pct)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (token, price, recorded_at, change_type, last_price, delta, delta_pct))
                    price_tracker[token] = price
                    total_price_changes += 1

        # Commit every 50 commits to avoid huge transactions
        if i % 50 == 0:
            conn.commit()

        prev_seen = current_seen

    conn.commit()
    conn.close()

    logger.info(f"\nMigration complete!")
    logger.info(f"  Listings inserted: {total_inserted}")
    logger.info(f"  Price changes recorded: {total_price_changes}")
    logger.info(f"  Database: {DB_PATH}")


if __name__ == "__main__":
    migrate()
