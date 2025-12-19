from aiohttp import ClientSession, ClientConnectorError
from urllib.parse import urlencode
import asyncio
import json
import os
import time
import datetime
from dotenv import load_dotenv
import requests
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants for error handling
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds (increased from 2 for better resilience)

load_dotenv()

# === Telegram Credentials ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")

logger.info(f"Telegram Bot configured for chat ID: {TELEGRAM_CHAT_ID}")
TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# === API Configuration ===
API_BASE_URL = "https://gw.yad2.co.il/realestate-feed/forsale/feed"

# Search 1: 3-3.5 rooms, 70+ sqm, max 2.35M
API_PARAMS_SEARCH_1 = {
    "city": "8300",
    "multiNeighborhood": "991420,991421,991415,325",
    "area": "9",
    "topArea": "2",
    "property": "1",  # apartment
    "maxPrice": "2350000",
    "minRooms": "3",
    "maxRooms": "3.5",
    "minSquaremeter": "70",
    "minFloor": "2",
    "priceOnly": "1",
    "sort": "1"
}

# Search 2: 4-4.5 rooms, 80+ sqm, max 2.6M
API_PARAMS_SEARCH_2 = {
    "city": "8300",
    "multiNeighborhood": "991420,991421,991415,325",
    "area": "9",
    "topArea": "2",
    "property": "1",  # apartment
    "maxPrice": "2700000",
    "minRooms": "4",
    "maxRooms": "4.5",
    "minSquaremeter": "85",
    "minFloor": "2",
    "priceOnly": "1",
    "sort": "1"
}

# Keep original API_PARAMS for backward compatibility
API_PARAMS = API_PARAMS_SEARCH_1

# === Neighborhood Filter ===
# Filtering is now done at API level via multiNeighborhood parameter
WANTED_NEIGHBORHOODS = []

# === Seen Ads ===
SEEN_FILE = "seen.json"
seen = {}

def format_price(price):
    """Format price with commas (e.g., 2200000 -> 2,200,000)"""
    try:
        return f"{int(price):,}"
    except:
        return str(price)

def send_telegram(text: str):
    """
    Sends a Hebrew message to Telegram via Bot API sendMessage.
    """
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        }
        r = requests.post(TELEGRAM_SEND_URL, json=payload, timeout=20)
        r.raise_for_status()
        logger.debug("Telegram message sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")

def load_or_initialize_seen():
    global seen
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = json.load(f)
        logger.info(f"Loaded {len(seen)} existing listings from {SEEN_FILE}")
    else:
        logger.info(f"First run: {SEEN_FILE} does not exist. Will create after fetching initial data...")

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved {len(seen)} listings to {SEEN_FILE}")

async def get_contact_info(client, ads_id):
    """Fetch contact info from customer endpoint"""
    try:
        response = await client.get(f'https://gw.yad2.co.il/realestate-item/{ads_id}/customer')
        data = await response.json()
        phone = data.get("data", {}).get("brokerPhone") or data.get("data", {}).get("phone")
        return phone
    except Exception as e:
        logger.debug(f"Failed to fetch phone for listing {ads_id}: {e}")
        return None

def extract_listing_data(item):
    """Extract relevant data from listing item"""
    token = item.get("token")
    address = item.get("address", {})
    # Check if listing is private (from data.private) or agency
    is_private = "private" in item  # or item.get("source") == "private"
    return {
        "price": item.get("price", 0),
        "rooms": item.get("additionalDetails", {}).get("roomsCount"),
        "street": address.get("street", {}).get("text", "לא ידוע"),
        "neighborhood": address.get("neighborhood", {}).get("text", "לא ידוע"),
        "city": address.get("city", {}).get("text", "לא ידוע"),
        "floor": address.get("house", {}).get("floor", "לא ידוע"),
        "sqm": item.get("additionalDetails", {}).get("squareMeter", 0),
        "phone": None,  # Will be filled async
        "token": token,
        "is_private": is_private,
    }

def is_possible_duplicate(new_item_data):
    """Check if listing is a repost by the same seller"""
    for url, old in seen.items():
        # Compare ALL attributes to identify the same apartment
        if (
            old.get("city") == new_item_data.get("city")
            and old.get("neighborhood") == new_item_data.get("neighborhood")
            and old.get("street") == new_item_data.get("street")
            and old.get("floor") == new_item_data.get("floor")
            and old.get("rooms") == new_item_data.get("rooms")
            and abs(old.get("sqm", 0) - new_item_data.get("sqm", 0)) <= 3
            and old.get("price") != new_item_data.get("price")
            and old.get("phone")
            and new_item_data.get("phone")
            and old.get("phone") == new_item_data.get("phone")
        ):
            return url, old
    return None, None

async def fetch_listings(client: ClientSession, page: int = 1):
    """Fetch listings from the API for a specific page with retry logic"""
    
    # Enhanced headers to mimic real browser and avoid bot detection
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
            
            # Check if we got HTML instead of JSON (bot detection)
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                logger.warning(f"Page {page} attempt {attempt + 1}: Got HTML response (bot detection). Retrying...")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Page {page}: Failed after {MAX_RETRIES} attempts - API is blocking requests")
                    return []
            
            data = await response.json()
            
            # Get all results from all categories (private, agency, etc.), excluding yad1
            data_container = data.get("data", {})
            results = []
            
            # Try to get results from all possible keys, excluding yad1
            for key, value in data_container.items():
                if key != "yad1" and isinstance(value, list):
                    results.extend(value)
            
            # Extract pagination info
            pagination = data.get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            
            logger.info(f"Page {page}/{total_pages}: Retrieved {len(results)} listings")
            
            return results, total_pages
            
        except asyncio.TimeoutError:
            logger.warning(f"Page {page} attempt {attempt + 1}: Timeout. Retrying...")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                logger.error(f"Page {page}: Timeout after {MAX_RETRIES} attempts")
                return [], 0
        except Exception as e:
            logger.warning(f"Page {page} attempt {attempt + 1}: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                logger.error(f"Page {page}: Failed after {MAX_RETRIES} attempts")
                return [], 0
    
    return [], 0

async def check_yad2_listings():
    """Check for new listings and price changes"""
    changes = 0
    all_listings = []
    neighborhoods_found = set()  # Track unique neighborhoods
    
    async with ClientSession() as client:
        # Fetch all pages based on pagination
        page = 1
        total_pages = 1
        
        while page <= total_pages:
            page_results, total_pages = await fetch_listings(client, page)
            all_listings.extend(page_results)
            page += 1
        
        if len(all_listings) == 0:
            logger.warning("No listings fetched!")
            return
        
        # Fetch contact info for each listing
        logger.info(f"Fetching contact info for {len(all_listings)} listings...")
        for index, item in enumerate(all_listings, 1):
            token = item.get("token")
            if token:
                phone = await get_contact_info(client, token)
                item_data = extract_listing_data(item)
                item_data["phone"] = phone
                
                url = f"https://www.yad2.co.il/item/{token}"
                
                price = item_data["price"]
                rooms = item_data["rooms"]
                street = item_data["street"]
                neighborhood = item_data["neighborhood"]
                city = item_data["city"]
                floor = item_data["floor"]
                sqm = item_data["sqm"]
                phone_str = item_data["phone"]
                
                # Track neighborhoods
                if neighborhood != "לא ידוע":
                    neighborhoods_found.add(neighborhood)
                
                # Check if listing is already tracked
                if url in seen:
                    if seen[url]["price"] != price:
                        old_price = seen[url]["price"]
                        seen[url] = item_data
                        save_seen()
                        
                        message = (
                            f"💸 שינוי במחיר מודעה קיימת:\n"
                            f"עיר: {city}\nרחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\n"
                            f"מחיר קודם: {format_price(old_price)} ₪\n"
                            f"מחיר חדש: {format_price(price)} ₪\n{url}"
                        )
                        logger.info(f"Price change detected: {street} - {old_price}₪ → {price}₪")
                        send_telegram(message)
                        changes += 1
                else:
                    # New listing - check if it's a duplicate repost
                    old_url, old_data = is_possible_duplicate(item_data)
                    if old_url:
                        message = (
                            f"🔁 יתכן שזו אותה דירה שפורסמה מחדש ע\"י אותו מפרסם(מניאק):\n"
                            f"עיר: {city}\nרחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\nמ\"ר: {sqm}\n"
                            f"מחיר קודם: {format_price(old_data['price'])} ₪\n"
                            f"מחיר חדש: {format_price(price)} ₪\n"
                            f"טלפון: {phone_str}\n"
                            f"קישור חדש: {url}\n"
                            f"קישור קודם: {old_url}"
                        )
                        logger.info(f"Potential repost detected: {street} - {phone_str}")
                        send_telegram(message)
                    else:
                        # Build neighborhood line only if it's not "לא ידוע"
                        neighborhood_line = f"שכונה: {neighborhood}, " if neighborhood != "לא ידוע" else ""
                        # Determine if private or agency
                        listing_type = "פרטי" if item_data.get("is_private") else "תיווך"
                        message = (
                            f"🔔 דירה חדשה ביד2!\n"
                            f"עיר: {city}, {neighborhood_line}רחוב: {street}\n"
                            f"חדרים: {rooms}, קומה: {floor}\n"
                            f"שטח בנוי: {sqm} מ\"ר\n"
                            f"מחיר: {format_price(price)} ₪\n"
                            f"({listing_type})\n"
                            f"טלפון: {phone_str}\n"
                            f"{url}"
                        )
                        logger.info(f"New listing found: {street} - {price}₪")
                        send_telegram(message)
                    
                    seen[url] = item_data
                    save_seen()
                    changes += 1
    
    logger.info(f"Check complete: {changes} changes detected. Total tracked listings: {len(seen)}")

async def main_loop(check_interval: int = 120, run_once: bool = False):
    """Main monitoring loop - runs both searches"""
    global API_PARAMS
    load_or_initialize_seen()
    
    # Initial load - don't send alerts on first run
    if len(seen) == 0:
        logger.info("First run: Loading all current listings without sending alerts...")
        # Load from both searches
        API_PARAMS = API_PARAMS_SEARCH_1
        await check_yad2_listings()
        API_PARAMS = API_PARAMS_SEARCH_2
        await check_yad2_listings()
        logger.info(f"Initial load complete: {len(seen)} listings saved. Waiting for next check...")
    
    # For GitHub Actions: run once and exit
    # For local: run continuously with check_interval
    if run_once:
        logger.info("Running single check cycle (GitHub Actions mode)")
        try:
            # Run Search 1: 3-3.5 rooms
            logger.info("Running Search 1: 3-3.5 rooms")
            API_PARAMS = API_PARAMS_SEARCH_1
            await check_yad2_listings()
            
            await asyncio.sleep(10)
            
            # Run Search 2: 4-4.5 rooms
            logger.info("Running Search 2: 4-4.5 rooms")
            API_PARAMS = API_PARAMS_SEARCH_2
            await check_yad2_listings()
            
            logger.info("Single check cycle complete. Exiting.")
        except Exception as e:
            logger.exception(f"Error during check cycle: {e}")
    else:
        logger.info(f"Starting monitoring loop (checking every {check_interval} seconds)")
        while True:
            try:
                # Run Search 1: 3-3.5 rooms
                logger.info("Running Search 1: 3-3.5 rooms")
                API_PARAMS = API_PARAMS_SEARCH_1
                await check_yad2_listings()
                
                await asyncio.sleep(10)
                
                # Run Search 2: 4-4.5 rooms
                logger.info("Running Search 2: 4-4.5 rooms")
                API_PARAMS = API_PARAMS_SEARCH_2
                await check_yad2_listings()
            except Exception as e:
                logger.exception(f"Error during check cycle: {e}")
            
            await asyncio.sleep(check_interval)

if __name__ == "__main__":
    from sys import platform
    if platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    logger.info("Starting Yad2 Apartment Monitor with Telegram Alerts")
    
    # Check if running in GitHub Actions (via environment variable)
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    
    if is_github_actions:
        logger.info("Running in GitHub Actions - single run mode")
        asyncio.run(main_loop(run_once=True))
    else:
        logger.info("Running locally - continuous loop mode (every 120 seconds)")
        asyncio.run(main_loop(check_interval=120, run_once=False))
