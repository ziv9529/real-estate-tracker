from aiohttp import ClientSession
from urllib.parse import urlencode
import asyncio
import os
import time
import datetime
from dotenv import load_dotenv
import requests
import logging
import sys

# Ensure project root is on path so db_utils can be imported from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import (
    init_db, upsert_listing, deactivate_missing, find_possible_duplicate,
    get_cached_phone, save_cached_phone, snapshot_today
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")

logger.info(f"Telegram Bot configured for chat ID: {TELEGRAM_CHAT_ID}")
TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

API_BASE_URL = "https://gw.yad2.co.il/realestate-feed/forsale/feed"

# Search 1: 3-3.5 rooms, 70+ sqm, max 2.35M
API_PARAMS_SEARCH_1 = {
    "city": "8300",
    "multiNeighborhood": "991420,991421,991415,325",
    "area": "9",
    "topArea": "2",
    "property": "1",
    "maxPrice": "2350000",
    "minRooms": "3",
    "maxRooms": "3.5",
    "minSquaremeter": "70",
    "minFloor": "2",
    "priceOnly": "1",
    "sort": "1"
}

# Search 2: 4-4.5 rooms, 85+ sqm, max 2.7M
API_PARAMS_SEARCH_2 = {
    "city": "8300",
    "multiNeighborhood": "991420,991421,991415,325",
    "area": "9",
    "topArea": "2",
    "property": "1",
    "maxPrice": "2700000",
    "minRooms": "4",
    "maxRooms": "4.5",
    "minSquaremeter": "85",
    "minFloor": "2",
    "priceOnly": "1",
    "sort": "1"
}

API_PARAMS = API_PARAMS_SEARCH_1


def format_price(price):
    try:
        return f"{int(price):,}"
    except Exception:
        return str(price)


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
        logger.debug("Telegram message sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


async def get_contact_info(client, ads_id, retry_count=3, delay=1):
    """Fetch contact info from customer endpoint with retry logic and caching."""
    cached = get_cached_phone(ads_id)
    if cached is not False:  # False means "not in cache"; None means "no phone"
        logger.debug(f"Cache hit for {ads_id}: {cached}")
        return cached

    for attempt in range(retry_count):
        try:
            response = await client.get(
                f'https://gw.yad2.co.il/realestate-item/{ads_id}/customer',
                timeout=15
            )
            data = await response.json()
            phone = data.get("data", {}).get("brokerPhone") or data.get("data", {}).get("phone")
            save_cached_phone(ads_id, phone)
            if phone:
                logger.debug(f"Got phone for {ads_id}: {phone}")
            else:
                logger.debug(f"No phone data for {ads_id}")
            return phone
        except asyncio.TimeoutError:
            if attempt < retry_count - 1:
                await asyncio.sleep(delay)
            else:
                logger.warning(f"Timeout fetching phone for {ads_id} after {retry_count} attempts")
        except Exception as e:
            if attempt < retry_count - 1:
                await asyncio.sleep(delay)
            else:
                logger.warning(f"Error fetching phone for {ads_id}: {e}")

    save_cached_phone(ads_id, None)
    return None


def extract_listing_data(item):
    """Extract relevant data from a Yad2 API listing item."""
    token = item.get("token")
    address = item.get("address", {})
    is_private = item.get("adType") == "private"
    cover_image = item.get("metaData", {}).get("coverImage", None)
    return {
        "url": f"https://www.yad2.co.il/item/{token}",
        "price": item.get("price", 0),
        "rooms": item.get("additionalDetails", {}).get("roomsCount"),
        "street": address.get("street", {}).get("text", "לא ידוע"),
        "neighborhood": address.get("neighborhood", {}).get("text", "לא ידוע"),
        "city": address.get("city", {}).get("text", "לא ידוע"),
        "floor": address.get("house", {}).get("floor", None),
        "sqm": item.get("additionalDetails", {}).get("squareMeter", 0),
        "phone": None,
        "token": token,
        "is_private": is_private,
        "cover_image": cover_image,
    }


async def fetch_listings(client: ClientSession, page: int = 1):
    """Fetch one page of listings from Yad2 API with retry logic."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.yad2.co.il/",
        "Origin": "https://www.yad2.co.il",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "DNT": "1"
    }

    for attempt in range(MAX_RETRIES):
        try:
            params = {**API_PARAMS, "page": str(page)}
            url = f"{API_BASE_URL}?{urlencode(params)}"
            response = await client.get(url, timeout=20, headers=headers)

            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                logger.warning(f"Page {page} attempt {attempt + 1}: HTML response (bot detection)")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                return [], 0

            data = await response.json()
            data_container = data.get("data", {})
            results = []
            for key, value in data_container.items():
                if key != "yad1" and isinstance(value, list):
                    results.extend(value)

            pagination = data.get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            logger.info(f"Page {page}/{total_pages}: Retrieved {len(results)} listings")
            return results, total_pages

        except asyncio.TimeoutError:
            logger.warning(f"Page {page} attempt {attempt + 1}: Timeout")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return [], 0
        except Exception as e:
            logger.warning(f"Page {page} attempt {attempt + 1}: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return [], 0

    return [], 0


async def check_yad2_listings(send_alerts: bool = True):
    """Fetch all pages for the current API_PARAMS and update the database."""
    changes = 0
    all_listings = []
    seen_tokens = set()

    async with ClientSession() as client:
        page = 1
        total_pages = 1
        while page <= total_pages:
            page_results, total_pages = await fetch_listings(client, page)
            all_listings.extend(page_results)
            page += 1

        if not all_listings:
            logger.warning("No listings fetched!")
            return

        logger.info(f"Fetching contact info for {len(all_listings)} listings...")
        for index, item in enumerate(all_listings, 1):
            token = item.get("token")
            if not token:
                continue

            phone = await get_contact_info(client, token)
            item_data = extract_listing_data(item)
            item_data["phone"] = phone

            seen_tokens.add(token)

            if index < len(all_listings):
                await asyncio.sleep(0.3)

            is_new, price_changed, old_price = upsert_listing(token, item_data, source="yad2")

            if not send_alerts:
                continue

            price = item_data["price"]
            rooms = item_data["rooms"]
            street = item_data["street"]
            neighborhood = item_data["neighborhood"]
            city = item_data["city"]
            floor = item_data["floor"]
            sqm = item_data["sqm"]
            url = item_data["url"]

            if price_changed and not is_new:
                message = (
                    f"💸 שינוי במחיר מודעה קיימת:\n"
                    f"עיר: {city}\nרחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\n"
                    f"מחיר קודם: {format_price(old_price)} ₪\n"
                    f"מחיר חדש: {format_price(price)} ₪\n{url}"
                )
                logger.info(f"Price change: {street} — {old_price}₪ → {price}₪")
                send_telegram(message)
                changes += 1

            elif is_new:
                # Check if it's a duplicate repost
                dup_token, dup_data = find_possible_duplicate(item_data)
                if dup_token and dup_token != token:
                    exact_sqm = dup_data.get("sqm") == item_data.get("sqm")
                    same_phone = dup_data.get("phone") == phone
                    price_diff = dup_data.get("price") != price

                    if exact_sqm and same_phone and price_diff:
                        dup_url = dup_data.get("url", f"https://www.yad2.co.il/item/{dup_token}")
                        message = (
                            f"🔁 יתכן שזו אותה דירה שפורסמה מחדש ע\"י אותו מפרסם:\n"
                            f"עיר: {city}\nרחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\nמ\"ר: {sqm}\n"
                            f"מחיר קודם: {format_price(dup_data['price'])} ₪\n"
                            f"מחיר חדש: {format_price(price)} ₪\n"
                            f"טלפון: {phone}\n"
                            f"קישור חדש: {url}\n"
                            f"קישור קודם: {dup_url}"
                        )
                        logger.info(f"Potential repost: {street}")
                        send_telegram(message)
                    else:
                        logger.info(f"Similar but not exact match: {street}")
                else:
                    neighborhood_line = f"שכונה: {neighborhood}, " if neighborhood != "לא ידוע" else ""
                    listing_type = "פרטי" if item_data.get("is_private") else "תיווך"
                    listing_type_formatted = f"*{listing_type}*" if item_data.get("is_private") else listing_type
                    message = (
                        f"🔔 דירה חדשה ביד2!\n"
                        f"עיר: {city}, {neighborhood_line}רחוב: {street}\n"
                        f"חדרים: {rooms}, קומה: {floor}\n"
                        f"שטח בנוי: {sqm} מ\"ר\n"
                        f"מחיר: {format_price(price)} ₪\n"
                        f"({listing_type_formatted})\n"
                        f"טלפון: {phone}\n"
                        f"{url}"
                    )
                    logger.info(f"New listing: {street} — {price}₪")
                    send_telegram(message)

                changes += 1

    # Mark listings not seen this run as inactive
    deactivated = deactivate_missing(seen_tokens, source="yad2")
    if deactivated:
        logger.info(f"Marked {deactivated} listings as inactive (delisted)")

    logger.info(f"Check complete: {changes} changes. Seen tokens this run: {len(seen_tokens)}")
    return seen_tokens


def take_daily_snapshots(city: str = "ראשון לציון"):
    """Compute and save today's market snapshots for all segments."""
    for category in ["3-3.5", "4-4.5"]:
        snapshot_today(category, city)
        # Also per-neighborhood snapshots for the tracked neighborhoods
        for neigh in ["הרקפות", "נרקיסים", "נוריות", "נחלת יהודה"]:
            snapshot_today(category, city, neighborhood=neigh)
    logger.info("Daily market snapshots saved")


async def main_loop(run_once: bool = False):
    """Main monitoring loop — runs both searches."""
    global API_PARAMS

    init_db()

    if run_once:
        logger.info("Running single check cycle (GitHub Actions mode)")
        try:
            logger.info("Search 1: 3-3.5 rooms")
            API_PARAMS = API_PARAMS_SEARCH_1
            await check_yad2_listings(send_alerts=True)

            await asyncio.sleep(10)

            logger.info("Search 2: 4-4.5 rooms")
            API_PARAMS = API_PARAMS_SEARCH_2
            await check_yad2_listings(send_alerts=True)

            # Save daily snapshots once per day (idempotent)
            take_daily_snapshots()

            logger.info("Single check cycle complete.")
        except Exception as e:
            logger.exception(f"Error during check cycle: {e}")
    else:
        logger.info("Starting continuous monitoring loop (every 120 seconds)")
        while True:
            try:
                logger.info("Search 1: 3-3.5 rooms")
                API_PARAMS = API_PARAMS_SEARCH_1
                await check_yad2_listings(send_alerts=True)

                await asyncio.sleep(10)

                logger.info("Search 2: 4-4.5 rooms")
                API_PARAMS = API_PARAMS_SEARCH_2
                await check_yad2_listings(send_alerts=True)

                take_daily_snapshots()
            except Exception as e:
                logger.exception(f"Error during check cycle: {e}")

            await asyncio.sleep(120)


if __name__ == "__main__":
    from sys import platform
    if platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    logger.info("Starting Yad2 Apartment Monitor")

    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    if is_github_actions:
        logger.info("GitHub Actions mode — single run")
        asyncio.run(main_loop(run_once=True))
    else:
        logger.info("Local mode — continuous loop")
        asyncio.run(main_loop(run_once=False))
