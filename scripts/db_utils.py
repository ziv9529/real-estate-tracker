"""
db_utils.py — SQLite abstraction layer for real estate market monitor.
All database operations go through this module.
"""

import sqlite3
import os
import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Database file path (relative to project root)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database.db")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    try:
        c = conn.cursor()

        c.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                token         TEXT PRIMARY KEY,
                url           TEXT NOT NULL,
                source        TEXT DEFAULT 'yad2',
                price         INTEGER,
                rooms         REAL,
                street        TEXT,
                neighborhood  TEXT,
                city          TEXT,
                floor         INTEGER,
                sqm           INTEGER,
                phone         TEXT,
                is_private    INTEGER,
                cover_image   TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at  TEXT NOT NULL,
                is_active     INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_listings_neighborhood ON listings(neighborhood);
            CREATE INDEX IF NOT EXISTS idx_listings_rooms ON listings(rooms);
            CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
            CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);

            CREATE TABLE IF NOT EXISTS price_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                token          TEXT NOT NULL,
                price          INTEGER NOT NULL,
                recorded_at    TEXT NOT NULL,
                change_type    TEXT NOT NULL,
                previous_price INTEGER,
                delta          INTEGER,
                delta_pct      REAL,
                FOREIGN KEY (token) REFERENCES listings(token)
            );

            CREATE INDEX IF NOT EXISTS idx_ph_token ON price_history(token);
            CREATE INDEX IF NOT EXISTS idx_ph_recorded_at ON price_history(recorded_at);

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date         TEXT NOT NULL,
                rooms_category        TEXT NOT NULL,
                neighborhood          TEXT,
                city                  TEXT NOT NULL,
                listing_count         INTEGER,
                avg_price             INTEGER,
                median_price          INTEGER,
                avg_price_per_sqm     INTEGER,
                new_listings_today    INTEGER DEFAULT 0,
                delisted_today        INTEGER DEFAULT 0,
                price_drops_today     INTEGER DEFAULT 0,
                UNIQUE(snapshot_date, rooms_category, neighborhood, city)
            );

            CREATE INDEX IF NOT EXISTS idx_ms_date ON market_snapshots(snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_ms_rooms ON market_snapshots(rooms_category);

            CREATE TABLE IF NOT EXISTS my_apartment (
                id             INTEGER PRIMARY KEY DEFAULT 1,
                neighborhood   TEXT NOT NULL,
                city           TEXT NOT NULL,
                rooms          REAL NOT NULL,
                sqm            INTEGER,
                floor          INTEGER,
                purchase_price INTEGER,
                purchase_date  TEXT,
                notes          TEXT
            );

            CREATE TABLE IF NOT EXISTS gov_transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_date     TEXT,
                city          TEXT,
                neighborhood  TEXT,
                street        TEXT,
                rooms         REAL,
                sqm           INTEGER,
                floor         INTEGER,
                price         INTEGER,
                price_per_sqm INTEGER,
                source_url    TEXT,
                fetched_at    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_gov_city ON gov_transactions(city);
            CREATE INDEX IF NOT EXISTS idx_gov_date ON gov_transactions(deal_date);

            CREATE TABLE IF NOT EXISTS ai_reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date  TEXT NOT NULL,
                week_label   TEXT NOT NULL,
                model        TEXT,
                prompt_tokens INTEGER,
                output_tokens INTEGER,
                report_md    TEXT NOT NULL,
                summary_he   TEXT,
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS phone_cache (
                token      TEXT PRIMARY KEY,
                phone      TEXT,
                fetched_at TEXT NOT NULL
            );
        """)

        conn.commit()
        logger.debug(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def today_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


# ─── Listings ────────────────────────────────────────────────────────────────

def upsert_listing(token: str, data: dict, source: str = "yad2") -> tuple[bool, bool, Optional[int]]:
    """
    Insert or update a listing.
    Returns (is_new, price_changed, old_price).
    """
    url = data.get("url") or f"https://www.yad2.co.il/item/{token}"
    now = now_iso()

    conn = get_connection()
    try:
        c = conn.cursor()
        existing = c.execute(
            "SELECT price, is_active FROM listings WHERE token = ?", (token,)
        ).fetchone()

        if existing is None:
            # New listing
            c.execute("""
                INSERT INTO listings
                    (token, url, source, price, rooms, street, neighborhood, city,
                     floor, sqm, phone, is_private, cover_image, first_seen_at, last_seen_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                token, url, source,
                data.get("price"), data.get("rooms"), data.get("street"),
                data.get("neighborhood"), data.get("city"), data.get("floor"),
                data.get("sqm"), data.get("phone"), 1 if data.get("is_private") else 0,
                data.get("cover_image"), now, now
            ))
            conn.commit()
            _record_price_change(conn, token, data.get("price"), None, "initial")
            return True, False, None
        else:
            old_price = existing["price"]
            price_changed = old_price != data.get("price")

            c.execute("""
                UPDATE listings SET
                    price = ?, rooms = ?, street = ?, neighborhood = ?, city = ?,
                    floor = ?, sqm = ?, phone = COALESCE(?, phone),
                    is_private = ?, cover_image = COALESCE(?, cover_image),
                    last_seen_at = ?, is_active = 1
                WHERE token = ?
            """, (
                data.get("price"), data.get("rooms"), data.get("street"),
                data.get("neighborhood"), data.get("city"), data.get("floor"),
                data.get("sqm"), data.get("phone"),
                1 if data.get("is_private") else 0,
                data.get("cover_image"), now, token
            ))
            conn.commit()

            if price_changed:
                new_price = data.get("price")
                change_type = "increase" if new_price > old_price else "decrease"
                _record_price_change(conn, token, new_price, old_price, change_type)

            return False, price_changed, old_price if price_changed else None
    finally:
        conn.close()


def _record_price_change(conn: sqlite3.Connection, token: str, price: int,
                         old_price: Optional[int], change_type: str):
    delta = (price - old_price) if old_price is not None else None
    delta_pct = round((delta / old_price) * 100, 2) if old_price else None
    conn.execute("""
        INSERT INTO price_history (token, price, recorded_at, change_type, previous_price, delta, delta_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (token, price, now_iso(), change_type, old_price, delta, delta_pct))
    conn.commit()


def deactivate_missing(active_tokens: set, source: str = "yad2"):
    """Mark listings not seen in the latest scrape as inactive (likely sold/removed)."""
    if not active_tokens:
        return 0
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(active_tokens))
        result = conn.execute(
            f"UPDATE listings SET is_active = 0 WHERE source = ? AND is_active = 1 AND token NOT IN ({placeholders})",
            (source, *active_tokens)
        )
        conn.commit()
        return result.rowcount
    finally:
        conn.close()


def find_possible_duplicate(data: dict) -> Optional[tuple[str, dict]]:
    """
    Check if there's an active listing with the same location + size (±3 sqm).
    Returns (token, row_dict) or (None, None).
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT token, url, city, neighborhood, street, floor, rooms, sqm, phone, price
            FROM listings
            WHERE is_active = 1
              AND city = ?
              AND neighborhood = ?
              AND street = ?
              AND floor = ?
              AND rooms = ?
              AND ABS(COALESCE(sqm, 0) - ?) <= 3
        """, (
            data.get("city"), data.get("neighborhood"), data.get("street"),
            data.get("floor"), data.get("rooms"), data.get("sqm", 0)
        )).fetchall()

        if rows:
            row = dict(rows[0])
            return row["token"], row
        return None, None
    finally:
        conn.close()


# ─── Phone Cache ─────────────────────────────────────────────────────────────

def get_cached_phone(token: str) -> Optional[str]:
    """Return cached phone (or None) for a listing token. Returns False if not in cache."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT phone FROM phone_cache WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return False  # Not in cache
        return row["phone"]  # May be None if explicitly cached as no-phone
    finally:
        conn.close()


def save_cached_phone(token: str, phone: Optional[str]):
    """Upsert phone number into the phone_cache table."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO phone_cache (token, phone, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET phone = excluded.phone, fetched_at = excluded.fetched_at
        """, (token, phone, now_iso()))
        conn.commit()
    finally:
        conn.close()


def load_phone_cache_to_dict() -> dict:
    """Load all cached phones into a dict {token: phone} for bulk access."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT token, phone FROM phone_cache").fetchall()
        return {row["token"]: row["phone"] for row in rows}
    finally:
        conn.close()


# ─── Market Snapshots ────────────────────────────────────────────────────────

def snapshot_today(rooms_category: str, city: str, neighborhood: Optional[str] = None):
    """
    Compute and upsert today's market snapshot for the given segment.
    Idempotent — safe to call multiple times per day.
    """
    today = today_str()
    rooms_min, rooms_max = _parse_rooms_category(rooms_category)

    conn = get_connection()
    try:
        base_filters = [city, rooms_min, rooms_max]
        neigh_filter = ""
        if neighborhood:
            neigh_filter = "AND neighborhood = ?"
            base_filters.append(neighborhood)

        rows = conn.execute(f"""
            SELECT price, sqm
            FROM listings
            WHERE is_active = 1 AND city = ?
              AND rooms >= ? AND rooms <= ?
              {neigh_filter}
              AND price > 0
        """, base_filters).fetchall()

        if not rows:
            return

        prices = sorted([r["price"] for r in rows])
        sqm_prices = [r["price"] / r["sqm"] for r in rows if r["sqm"] and r["sqm"] > 0]
        count = len(prices)
        avg_price = int(sum(prices) / count)
        median_price = prices[count // 2]
        avg_ppsqm = int(sum(sqm_prices) / len(sqm_prices)) if sqm_prices else None

        # Count new listings today
        new_today = conn.execute(f"""
            SELECT COUNT(*) as cnt FROM listings
            WHERE is_active = 1 AND city = ? AND rooms >= ? AND rooms <= ?
              {neigh_filter}
              AND DATE(first_seen_at) = ?
        """, (*base_filters, today)).fetchone()["cnt"]

        # Count delistings today (became inactive today)
        delisted = conn.execute(f"""
            SELECT COUNT(*) as cnt FROM listings
            WHERE is_active = 0 AND city = ? AND rooms >= ? AND rooms <= ?
              {neigh_filter}
              AND DATE(last_seen_at) = ?
        """, (*base_filters, today)).fetchone()["cnt"]

        # Count price drops today
        drops = conn.execute("""
            SELECT COUNT(DISTINCT ph.token) as cnt
            FROM price_history ph
            JOIN listings l ON ph.token = l.token
            WHERE ph.change_type = 'decrease'
              AND l.city = ? AND l.rooms >= ? AND l.rooms <= ?
              AND DATE(ph.recorded_at) = ?
        """, (city, rooms_min, rooms_max, today)).fetchone()["cnt"]

        conn.execute("""
            INSERT INTO market_snapshots
                (snapshot_date, rooms_category, neighborhood, city, listing_count,
                 avg_price, median_price, avg_price_per_sqm,
                 new_listings_today, delisted_today, price_drops_today)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date, rooms_category, neighborhood, city)
            DO UPDATE SET
                listing_count = excluded.listing_count,
                avg_price = excluded.avg_price,
                median_price = excluded.median_price,
                avg_price_per_sqm = excluded.avg_price_per_sqm,
                new_listings_today = excluded.new_listings_today,
                delisted_today = excluded.delisted_today,
                price_drops_today = excluded.price_drops_today
        """, (today, rooms_category, neighborhood, city, count, avg_price, median_price,
              avg_ppsqm, new_today, delisted, drops))
        conn.commit()
        logger.debug(f"Snapshot saved: {today} | {rooms_category} | {neighborhood or 'city-wide'} | n={count}")
    finally:
        conn.close()


def _parse_rooms_category(category: str) -> tuple[float, float]:
    parts = category.split("-")
    return float(parts[0]), float(parts[1])


def get_market_stats(rooms_category: str, city: str, days: int = 30) -> dict:
    """Return trend data for charting and reporting."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT snapshot_date, avg_price, median_price, listing_count,
                   new_listings_today, price_drops_today, avg_price_per_sqm
            FROM market_snapshots
            WHERE rooms_category = ? AND city = ? AND neighborhood IS NULL
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (rooms_category, city, days)).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_comparable_stats(rooms: float, city: str, neighborhood: str) -> dict:
    """Return current market stats for apartments comparable to the user's apartment."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT price, sqm FROM listings
            WHERE is_active = 1
              AND city = ?
              AND neighborhood = ?
              AND rooms >= ? AND rooms <= ?
              AND price > 0
        """, (city, neighborhood, rooms - 0.5, rooms + 0.5)).fetchall()

        if not rows:
            return {}

        prices = sorted([r["price"] for r in rows])
        count = len(prices)
        return {
            "count": count,
            "avg": int(sum(prices) / count),
            "min": prices[0],
            "max": prices[-1],
            "median": prices[count // 2],
        }
    finally:
        conn.close()


def get_active_listings(rooms_min: float, rooms_max: float, city: str,
                        order_by: str = "price ASC", limit: int = 200) -> list[dict]:
    """Return active listings for a rooms range, ordered and limited."""
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT token, url, source, price, rooms, street, neighborhood,
                   city, floor, sqm, phone, is_private, cover_image, first_seen_at
            FROM listings
            WHERE is_active = 1 AND city = ?
              AND rooms >= ? AND rooms <= ?
            ORDER BY {order_by}
            LIMIT ?
        """, (city, rooms_min, rooms_max, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── My Apartment ────────────────────────────────────────────────────────────

def get_my_apartment() -> Optional[dict]:
    """Return the user's apartment configuration, or None if not set."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM my_apartment WHERE id = 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_my_apartment(neighborhood: str, city: str, rooms: float, sqm: int = None,
                     floor: int = None, purchase_price: int = None,
                     purchase_date: str = None, notes: str = None):
    """Upsert the user's apartment configuration (only one row, id=1)."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO my_apartment (id, neighborhood, city, rooms, sqm, floor, purchase_price, purchase_date, notes)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                neighborhood = excluded.neighborhood,
                city = excluded.city,
                rooms = excluded.rooms,
                sqm = excluded.sqm,
                floor = excluded.floor,
                purchase_price = excluded.purchase_price,
                purchase_date = excluded.purchase_date,
                notes = excluded.notes
        """, (neighborhood, city, rooms, sqm, floor, purchase_price, purchase_date, notes))
        conn.commit()
        logger.info(f"my_apartment configured: {rooms} rooms in {neighborhood}, {city}")
    finally:
        conn.close()


# ─── AI Reports ──────────────────────────────────────────────────────────────

def save_ai_report(week_label: str, report_md: str, summary_he: str,
                   model: str = None, prompt_tokens: int = None, output_tokens: int = None):
    """Insert a new AI analysis report."""
    conn = get_connection()
    try:
        today = today_str()
        conn.execute("""
            INSERT INTO ai_reports
                (report_date, week_label, model, prompt_tokens, output_tokens, report_md, summary_he, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (today, week_label, model, prompt_tokens, output_tokens, report_md, summary_he, now_iso()))
        conn.commit()
        logger.info(f"AI report saved for week {week_label}")
    finally:
        conn.close()


def get_latest_ai_report() -> Optional[dict]:
    """Return the most recent AI report."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM ai_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def days_since_last_report() -> int:
    """Return number of days since the last AI report, or 999 if none."""
    report = get_latest_ai_report()
    if not report:
        return 999
    last_date = datetime.datetime.strptime(report["report_date"], "%Y-%m-%d").date()
    return (datetime.date.today() - last_date).days


# ─── Government Transactions ─────────────────────────────────────────────────

def upsert_gov_transaction(deal_date: str, city: str, neighborhood: str,
                           street: str, rooms: float, sqm: int, floor: int,
                           price: int, source_url: str = None):
    """Insert a government transaction record if it doesn't already exist."""
    price_per_sqm = int(price / sqm) if sqm and sqm > 0 else None
    conn = get_connection()
    try:
        # Avoid exact duplicates by checking key fields
        existing = conn.execute("""
            SELECT id FROM gov_transactions
            WHERE deal_date = ? AND city = ? AND street = ? AND sqm = ? AND price = ?
        """, (deal_date, city, street, sqm, price)).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO gov_transactions
                    (deal_date, city, neighborhood, street, rooms, sqm, floor, price, price_per_sqm, source_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (deal_date, city, neighborhood, street, rooms, sqm, floor,
                  price, price_per_sqm, source_url, now_iso()))
            conn.commit()
    finally:
        conn.close()


def get_gov_transactions(city: str, rooms_min: float, rooms_max: float,
                         months: int = 12) -> list[dict]:
    """Return recent government transaction records for analysis."""
    conn = get_connection()
    try:
        cutoff = (datetime.date.today() - datetime.timedelta(days=months * 30)).isoformat()
        rows = conn.execute("""
            SELECT deal_date, neighborhood, street, rooms, sqm, floor, price, price_per_sqm
            FROM gov_transactions
            WHERE city = ? AND rooms >= ? AND rooms <= ?
              AND deal_date >= ?
            ORDER BY deal_date DESC
        """, (city, rooms_min, rooms_max, cutoff)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Dashboard Data ───────────────────────────────────────────────────────────

def get_dashboard_data() -> dict:
    """
    Collect all data needed to render listings.html.
    Returns a single dict with all sections pre-computed.
    """
    conn = get_connection()
    try:
        # All active listings
        listings = conn.execute("""
            SELECT token, url, source, price, rooms, street, neighborhood,
                   city, floor, sqm, phone, is_private, cover_image, first_seen_at
            FROM listings WHERE is_active = 1
            ORDER BY price ASC
        """).fetchall()

        # 30-day trend for 3-3.5 rooms (city-wide)
        trend_3 = conn.execute("""
            SELECT snapshot_date, avg_price, median_price, listing_count
            FROM market_snapshots
            WHERE rooms_category = '3-3.5' AND neighborhood IS NULL
            ORDER BY snapshot_date ASC
            LIMIT 30
        """).fetchall()

        # 30-day trend for 4-4.5 rooms (city-wide)
        trend_4 = conn.execute("""
            SELECT snapshot_date, avg_price, median_price, listing_count
            FROM market_snapshots
            WHERE rooms_category = '4-4.5' AND neighborhood IS NULL
            ORDER BY snapshot_date ASC
            LIMIT 30
        """).fetchall()

        # Latest AI report
        ai_report = conn.execute(
            "SELECT report_date, week_label, report_md, summary_he FROM ai_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        # My apartment
        my_apt = conn.execute("SELECT * FROM my_apartment WHERE id = 1").fetchone()

        return {
            "listings": [dict(r) for r in listings],
            "trend_3": [dict(r) for r in trend_3],
            "trend_4": [dict(r) for r in trend_4],
            "ai_report": dict(ai_report) if ai_report else None,
            "my_apartment": dict(my_apt) if my_apt else None,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    print(f"Database initialized at: {DB_PATH}")
    conn = get_connection()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    print(f"Tables created: {[t['name'] for t in tables]}")
