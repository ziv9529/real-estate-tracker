"""
ai_analysis.py — Weekly AI-powered real estate market analysis via Claude API.

Runs every Sunday morning (weekly_analysis.yml workflow).
Sends a Hebrew summary to Telegram and saves the full Markdown report to the DB.

Cost: ~$0.001/week using claude-haiku-4-5. Cost guard prevents double-billing.
"""

import os
import sys
import json
import datetime
import logging
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import (
    init_db, get_my_apartment, get_market_stats, get_comparable_stats,
    get_active_listings, get_gov_transactions, get_latest_ai_report,
    days_since_last_report, save_ai_report
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CITY = "ראשון לציון"
MIN_DAYS_BETWEEN_REPORTS = 6  # Cost guard: skip if last report < 6 days ago


def fmt(price) -> str:
    try:
        return f"₪{int(price):,}"
    except Exception:
        return str(price)


def build_data_payload() -> dict:
    """
    Assemble aggregated market data for the Claude prompt.
    Uses statistics, NOT raw listings — keeps the prompt small and cheap.
    """
    my_apt = get_my_apartment()

    # 4-week trend for 3-3.5 and 4-4.5 rooms
    trend_3 = get_market_stats("3-3.5", CITY, days=28)
    trend_4 = get_market_stats("4-4.5", CITY, days=28)

    # Current active listings stats
    comp_3 = {}
    comp_4 = {}
    if my_apt:
        comp_3 = get_comparable_stats(my_apt["rooms"], CITY, my_apt["neighborhood"])

    # Top 5 cheapest 4-room upgrade options
    upgrades = get_active_listings(4.0, 4.5, CITY, order_by="price ASC", limit=5)
    upgrade_summaries = [
        {
            "rooms": u.get("rooms"),
            "sqm": u.get("sqm"),
            "neighborhood": u.get("neighborhood"),
            "price": u.get("price"),
            "floor": u.get("floor"),
            "is_private": u.get("is_private"),
        }
        for u in upgrades
    ]

    # Recent government transactions (last 12 months)
    gov_transactions_3 = get_gov_transactions(CITY, 2.5, 3.5, months=12)
    gov_transactions_4 = get_gov_transactions(CITY, 3.5, 4.5, months=12)

    # Recent price drops in 4-4.5 segment
    from scripts.db_utils import get_connection
    conn = get_connection()
    recent_drops = conn.execute("""
        SELECT l.neighborhood, l.street, l.rooms, l.sqm, l.price,
               ph.previous_price, ph.delta_pct, ph.recorded_at
        FROM price_history ph
        JOIN listings l ON ph.token = l.token
        WHERE ph.change_type = 'decrease'
          AND l.rooms >= 4 AND l.rooms <= 4.5
          AND l.city = ?
          AND DATE(ph.recorded_at) >= DATE('now', '-7 days')
        ORDER BY ph.delta_pct ASC
        LIMIT 5
    """, (CITY,)).fetchall()
    conn.close()

    recent_drops_list = [dict(r) for r in recent_drops]

    return {
        "analysis_date": datetime.date.today().isoformat(),
        "city": CITY,
        "my_apartment": my_apt,
        "comparable_market_3rooms": comp_3,
        "market_trend_3_3_5_rooms": trend_3[:7] if trend_3 else [],  # Last 7 days
        "market_trend_4_4_5_rooms": trend_4[:7] if trend_4 else [],
        "top_upgrade_candidates": upgrade_summaries,
        "recent_price_drops_4rooms": recent_drops_list,
        "gov_transactions_3rooms_last12m": gov_transactions_3[:10] if gov_transactions_3 else [],
        "gov_transactions_4rooms_last12m": gov_transactions_4[:10] if gov_transactions_4 else [],
    }


SYSTEM_PROMPT = """You are an Israeli real estate market analyst specializing in Rishon Lezion (ראשון לציון).
You help a property owner monitor the real estate market in their city.

The user owns a 3-room apartment in one of the monitored neighborhoods and is:
1. Tracking the current value of their apartment vs. the market
2. Monitoring 4-4.5 room apartments as potential future upgrade targets
3. Following market trends in Rishon Lezion

You will receive a JSON data payload with market statistics, trends, and listings.
All prices are in Israeli Shekels (₪ / ILS).
Neighborhoods are in Hebrew.

IMPORTANT: Respond EXACTLY in this structure (do not deviate):

---HEBREW_SUMMARY---
(2-3 sentences in Hebrew summarizing the most important insight for this week. This goes to Telegram.)

---MARKET_TRENDS---
(3-4 bullet points in English about price trends for 3-3.5 and 4-4.5 rooms. Include % changes if data allows.)

---MY_APARTMENT---
(2-3 sentences comparing the owner's 3-room apartment to current market comparables. Note if values are rising/falling.)

---UPGRADE_OPPORTUNITIES---
(Analyze the top upgrade candidates. Which offers the best value? Any neighborhoods to prefer/avoid? 2-3 sentences.)

---GOV_TRANSACTIONS---
(Summarize what actual sold prices (government data) tell us vs. current asking prices. Skip if no gov data.)

---PREDICTION---
(1 paragraph: short-term directional outlook for the Rishon Lezion market based on the data.)
"""


def call_claude_api(data_payload: dict) -> dict:
    """Call Claude API and return parsed sections."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("Missing ANTHROPIC_API_KEY in environment")

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = f"Here is this week's market data for analysis:\n\n```json\n{json.dumps(data_payload, ensure_ascii=False, indent=2)}\n```"

    logger.info(f"Calling Claude API ({CLAUDE_MODEL})...")
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    content = response.content[0].text
    usage = response.usage

    logger.info(f"Claude response: {usage.input_tokens} input tokens, {usage.output_tokens} output tokens")

    return {
        "raw": content,
        "prompt_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }


def parse_sections(raw: str) -> dict:
    """Parse the structured Claude response into named sections."""
    sections = {}
    current_key = None
    current_lines = []

    section_markers = {
        "---HEBREW_SUMMARY---": "hebrew_summary",
        "---MARKET_TRENDS---": "market_trends",
        "---MY_APARTMENT---": "my_apartment",
        "---UPGRADE_OPPORTUNITIES---": "upgrade_opportunities",
        "---GOV_TRANSACTIONS---": "gov_transactions",
        "---PREDICTION---": "prediction",
    }

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in section_markers:
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = section_markers[stripped]
            current_lines = []
        elif current_key:
            current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def build_markdown_report(sections: dict, data: dict) -> str:
    """Assemble the full Markdown report for the dashboard."""
    today = datetime.date.today().strftime("%d/%m/%Y")
    week = datetime.date.today().strftime("שבוע %W, %Y")

    parts = [
        f"# ניתוח שוק נדל\"ן שבועי — {today}",
        f"_{week} | ראשון לציון_\n",
        "## סיכום (עברית)",
        sections.get("hebrew_summary", "_אין נתונים_"),
        "",
        "## Market Trends",
        sections.get("market_trends", "_No data_"),
        "",
        "## Your Apartment",
        sections.get("my_apartment", "_No data_"),
        "",
        "## Upgrade Opportunities",
        sections.get("upgrade_opportunities", "_No data_"),
    ]

    gov = sections.get("gov_transactions", "").strip()
    if gov:
        parts += ["", "## Government Transaction Data", gov]

    parts += [
        "",
        "## Market Prediction",
        sections.get("prediction", "_No data_"),
        "",
        "---",
        f"_Generated by Claude ({CLAUDE_MODEL}) on {today}_",
    ]

    return "\n".join(parts)


def send_telegram(text: str):
    """Send message to Telegram."""
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=20
        )
        r.raise_for_status()
        logger.info("AI report summary sent to Telegram")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def main():
    init_db()

    # Cost guard
    days_since = days_since_last_report()
    if days_since < MIN_DAYS_BETWEEN_REPORTS:
        logger.info(f"Last report was {days_since} days ago (< {MIN_DAYS_BETWEEN_REPORTS}). Skipping.")
        return

    # Build data payload
    data = build_data_payload()
    logger.info("Data payload assembled")

    # Call Claude
    result = call_claude_api(data)

    # Parse and save
    sections = parse_sections(result["raw"])
    report_md = build_markdown_report(sections, data)
    summary_he = sections.get("hebrew_summary", "")

    week_label = datetime.date.today().strftime("%Y-W%W")
    save_ai_report(
        week_label=week_label,
        report_md=report_md,
        summary_he=summary_he,
        model=CLAUDE_MODEL,
        prompt_tokens=result["prompt_tokens"],
        output_tokens=result["output_tokens"],
    )

    # Send Hebrew summary to Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and summary_he:
        today_str = datetime.date.today().strftime("%d/%m/%Y")
        telegram_msg = (
            f"🤖 *ניתוח שוק שבועי* — {today_str}\n\n"
            f"{summary_he}\n\n"
            f"_דוח מלא זמין בדשבורד_"
        )
        send_telegram(telegram_msg)

    logger.info("Weekly AI analysis complete")


if __name__ == "__main__":
    main()
