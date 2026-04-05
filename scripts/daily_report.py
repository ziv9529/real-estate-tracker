"""
daily_report.py — Morning Telegram brief sent once per day.

Sends a structured Hebrew summary of:
  - Your apartment vs current market comparables
  - 3-3.5 room market stats
  - 4-4.5 room market stats
  - Top upgrade opportunities

Called by morning_report.yml workflow at 07:30 IL.
"""

import os
import sys
import datetime
import logging
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import (
    init_db, get_my_apartment, get_comparable_stats,
    get_market_stats, get_active_listings
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")

TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

CITY = "ראשון לציון"


def fmt(price: int) -> str:
    """Format price as ₪X,XXX,XXX"""
    try:
        return f"₪{int(price):,}"
    except Exception:
        return str(price)


def get_yesterday_stats(rooms_category: str) -> dict:
    """Return the most recent market snapshot for a room category."""
    stats = get_market_stats(rooms_category, CITY, days=2)
    if stats:
        return stats[0]  # Most recent
    return {}


def build_report() -> str:
    today = datetime.date.today().strftime("%d/%m/%Y")
    lines = [f"📊 *דוח בוקר* — {today}"]
    lines.append(f"עיר: {CITY}\n")

    # ── My apartment section ──────────────────────────────────────────────
    my_apt = get_my_apartment()
    if my_apt:
        comp = get_comparable_stats(my_apt["rooms"], CITY, my_apt["neighborhood"])
        lines.append(f"🏠 *הנכס שלך* ({my_apt['rooms']} חדרים, {my_apt['neighborhood']}):")
        if comp:
            lines.append(f"  מודעות דומות בשוק: {comp['count']}")
            lines.append(f"  ממוצע: {fmt(comp['avg'])}")
            lines.append(f"  טווח: {fmt(comp['min'])} — {fmt(comp['max'])}")
            if my_apt.get("purchase_price"):
                diff = comp["avg"] - my_apt["purchase_price"]
                sign = "▲" if diff >= 0 else "▼"
                lines.append(f"  מחיר קנייה: {fmt(my_apt['purchase_price'])} → {sign} {fmt(abs(diff))}")
        else:
            lines.append("  אין נתוני השוואה זמינים")
        lines.append("")

    # ── 3-3.5 rooms ──────────────────────────────────────────────────────
    snap3 = get_yesterday_stats("3-3.5")
    lines.append("📈 *3-3.5 חדרים*:")
    if snap3:
        lines.append(f"  מודעות פעילות: {snap3.get('listing_count', '?')}")
        lines.append(f"  ממוצע: {fmt(snap3['avg_price'])} | חציון: {fmt(snap3['median_price'])}")
        lines.append(f"  חדשות אתמול: +{snap3.get('new_listings_today', 0)} | הורדות מחיר: -{snap3.get('price_drops_today', 0)}")
    else:
        lines.append("  אין נתונים")
    lines.append("")

    # ── 4-4.5 rooms ──────────────────────────────────────────────────────
    snap4 = get_yesterday_stats("4-4.5")
    lines.append("📈 *4-4.5 חדרים*:")
    if snap4:
        lines.append(f"  מודעות פעילות: {snap4.get('listing_count', '?')}")
        lines.append(f"  ממוצע: {fmt(snap4['avg_price'])} | חציון: {fmt(snap4['median_price'])}")
        lines.append(f"  חדשות אתמול: +{snap4.get('new_listings_today', 0)} | הורדות מחיר: -{snap4.get('price_drops_today', 0)}")
    else:
        lines.append("  אין נתונים")
    lines.append("")

    # ── Top 3 upgrade opportunities ──────────────────────────────────────
    upgrades = get_active_listings(4.0, 4.5, CITY, order_by="price ASC", limit=3)
    if upgrades:
        lines.append("💰 *הזדמנויות שדרוג (4+ חדרים, זולות ביותר)*:")
        for apt in upgrades:
            parts = []
            if apt.get("rooms"):
                parts.append(f"{apt['rooms']} חד'")
            if apt.get("sqm"):
                parts.append(f"{apt['sqm']} מ\"ר")
            if apt.get("neighborhood"):
                parts.append(apt["neighborhood"])
            if apt.get("price"):
                parts.append(fmt(apt["price"]))
            lines.append(f"  • {' | '.join(parts)}")
            if apt.get("url"):
                lines.append(f"    {apt['url']}")
    else:
        lines.append("💰 *הזדמנויות שדרוג*: אין נתונים")

    return "\n".join(lines)


def send_telegram(text: str):
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(TELEGRAM_SEND_URL, json=payload, timeout=20)
        r.raise_for_status()
        logger.info("Daily report sent to Telegram")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise


def main():
    init_db()
    report = build_report()
    logger.info("Generated daily report")
    send_telegram(report)


if __name__ == "__main__":
    main()
