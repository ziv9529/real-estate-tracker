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
# OPTION 1: Filter by neighborhood NAMES (post-API filtering) - slower
# Set to empty list [] to accept ALL neighborhoods
WANTED_NEIGHBORHOODS = [
    'הרקפות',
    'נרקיסים',
    'נוריות',
    'נחלת יהודה',
]

# OPTION 2: Filter by neighborhood IDS (API-level filtering) - MUCH FASTER
# Use discover_neighborhoods.py to find IDs for your city first!
# Leave empty [] to disable this filter and get all neighborhoods
WANTED_NEIGHBORHOOD_IDS = []
# (Name-based filtering is enabled above, so API-level filtering is disabled)

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
    return {
        "price": item.get("price", 0),
        "rooms": item.get("additionalDetails", {}).get("roomsCount"),
        "street": address.get("street", {}).get("text", "לא ידוע"),
        "neighborhood": address.get("neighborhood", {}).get("text", "לא ידוע"),
        "floor": address.get("house", {}).get("floor", "לא ידוע"),
        "sqm": item.get("additionalDetails", {}).get("squareMeter", 0),
        "phone": None,  # Will be filled async
        "token": token,
    }

def is_possible_duplicate(new_item_data):
    """Check if listing is a repost by the same seller"""
    for url, old in seen.items():
        if (
            old.get("street") == new_item_data.get("street")
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
            
            # Add neighborhood IDs to API call if specified
            if WANTED_NEIGHBORHOOD_IDS:
                params["multiNeighborhood"] = ",".join(map(str, WANTED_NEIGHBORHOOD_IDS))
                logger.debug(f"Using neighborhood filter: {WANTED_NEIGHBORHOOD_IDS}")
            
            url = f"{API_BASE_URL}?{urlencode(params)}"
            
            logger.debug(f"Fetching page {page} (attempt {attempt + 1}/{MAX_RETRIES}): {url}")
            response = await client.get(url, timeout=20, headers=headers)
            logger.debug(f"Page {page} response status: {response.status}")
            
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
            
            # Get all results from all categories (private, agency, etc.)
            data_container = data.get("data", {})
            logger.debug(f"Page {page}: Available data keys: {list(data_container.keys())}")
            
            results = []
            
            # Try to get results from all possible keys (not just "markers")
            for key, value in data_container.items():
                if isinstance(value, list):
                    logger.debug(f"Page {page}: Found {len(value)} listings in '{key}'")
                    results.extend(value)
            
            logger.info(f"Page {page}: Retrieved {len(results)} listings total (from all categories)")
            
            if len(results) == 0:
                logger.warning(f"Page {page}: No listings returned")
            
            return results
            
        except asyncio.TimeoutError:
            logger.warning(f"Page {page} attempt {attempt + 1}: Timeout. Retrying...")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                logger.error(f"Page {page}: Timeout after {MAX_RETRIES} attempts")
                return []
        except Exception as e:
            logger.warning(f"Page {page} attempt {attempt + 1}: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                logger.error(f"Page {page}: Failed after {MAX_RETRIES} attempts")
                return []
    
    return []

async def check_yad2_listings(max_pages: int = 1):
    """Check for new listings and price changes"""
    logger.info(f"Starting check for new listings and price changes (max pages: {max_pages})")
    
    changes = 0
    all_listings = []
    neighborhoods_found = set()  # Track unique neighborhoods
    
    async with ClientSession() as client:
        # Fetch all pages
        logger.info(f"Fetching {max_pages} page(s)...")
        tasks = []
        for page in range(1, max_pages + 1):
            tasks.append(fetch_listings(client, page))
        
        results = await asyncio.gather(*tasks)
        for page_results in results:
            all_listings.extend(page_results)
        
        logger.info(f"Total listings fetched: {len(all_listings)}")
        
        if len(all_listings) == 0:
            logger.warning("No listings fetched! This might indicate an API issue or no results match your criteria.")
            return
        
        # Apply neighborhood filter if configured (post-API filtering by name)
        if WANTED_NEIGHBORHOODS:
            logger.info(f"Filtering to only wanted neighborhoods: {WANTED_NEIGHBORHOODS}")
            filtered_listings = [item for item in all_listings if item.get("address", {}).get("neighborhood", {}).get("text") in WANTED_NEIGHBORHOODS]
            logger.info(f"Filtered from {len(all_listings)} to {len(filtered_listings)} listings")
            all_listings = filtered_listings
            
            if len(all_listings) == 0:
                logger.warning("No listings match your wanted neighborhoods. Skipping this check.")
                return
        elif WANTED_NEIGHBORHOOD_IDS:
            logger.info(f"Neighborhood IDs filter already applied at API level: {WANTED_NEIGHBORHOOD_IDS}")
        else:
            logger.info("No neighborhood filter applied - processing all listings")
        
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
                floor = item_data["floor"]
                sqm = item_data["sqm"]
                phone_str = item_data["phone"]
                
                # Track neighborhoods
                if neighborhood != "לא ידוע":
                    neighborhoods_found.add(neighborhood)
                
                logger.debug(f"Processing {index}/{len(all_listings)}: {street} - {neighborhood} - {rooms} rooms - קומה {floor} - {price}₪")
                
                # Check if listing is already tracked
                if url in seen:
                    if seen[url]["price"] != price:
                        old_price = seen[url]["price"]
                        seen[url] = item_data
                        save_seen()
                        
                        message = (
                            f"💸 שינוי במחיר מודעה קיימת:\n"
                            f"רחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\n"
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
                            f"רחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\nמ\"ר: {sqm}\n"
                            f"מחיר קודם: {format_price(old_data['price'])} ₪\n"
                            f"מחיר חדש: {format_price(price)} ₪\n"
                            f"טלפון: {phone_str}\n"
                            f"קישור חדש: {url}\n"
                            f"קישור קודם: {old_url}"
                        )
                        logger.info(f"Potential repost detected: {street} - {phone_str}")
                        send_telegram(message)
                    else:
                        message = (
                            f"🔔 דירה חדשה ביד2!\nרחוב: {street}\nשכונה: {neighborhood}\nקומה: {floor}\nחדרים: {rooms}\n"
                            f"מ\"ר: {sqm}\nמחיר: {format_price(price)} ₪\nטלפון: {phone_str}\n{url}"
                        )
                        logger.info(f"New listing found: {street} - {price}₪")
                        send_telegram(message)
                    
                    seen[url] = item_data
                    save_seen()
                    changes += 1
    
    logger.info(f"Check complete: {changes} changes detected. Total tracked listings: {len(seen)}")
    
    # Log all unique neighborhoods found
    if neighborhoods_found:
        logger.info(f"Neighborhoods found in this check ({len(neighborhoods_found)} unique): {sorted(neighborhoods_found)}")
    else:
        logger.info("No neighborhoods found in this check")

async def main_loop(check_interval: int = 120, run_once: bool = False):
    """Main monitoring loop - runs both searches"""
    global API_PARAMS
    load_or_initialize_seen()
    
    # Initial load - don't send alerts on first run
    if len(seen) == 0:
        logger.info("First run: Loading all current listings without sending alerts...")
        # Load from both searches
        API_PARAMS = API_PARAMS_SEARCH_1
        await check_yad2_listings(max_pages=1)
        API_PARAMS = API_PARAMS_SEARCH_2
        await check_yad2_listings(max_pages=1)
        logger.info(f"Initial load complete: {len(seen)} listings saved. Waiting for next check...")
    
    # For GitHub Actions: run once and exit
    # For local: run continuously with check_interval
    if run_once:
        logger.info("Running single check cycle (GitHub Actions mode)")
        try:
            # Run Search 1: 3-3.5 rooms
            logger.info("\n" + "="*60)
            logger.info("Running Search 1: 3-3.5 rooms, 70+ sqm, max 2.35M")
            logger.info("="*60)
            API_PARAMS = API_PARAMS_SEARCH_1
            await check_yad2_listings(max_pages=1)
            
            # Add delay between searches to avoid bot detection
            logger.debug("Waiting 10 seconds between searches...")
            await asyncio.sleep(10)
            
            # Run Search 2: 4-4.5 rooms
            logger.info("\n" + "="*60)
            logger.info("Running Search 2: 4-4.5 rooms, 80+ sqm, max 2.6M")
            logger.info("="*60)
            API_PARAMS = API_PARAMS_SEARCH_2
            await check_yad2_listings(max_pages=1)
            
            logger.info("Single check cycle complete. Exiting.")
        except Exception as e:
            logger.exception(f"Error during check cycle: {e}")
    else:
        logger.info(f"Starting monitoring loop (checking every {check_interval} seconds)")
        while True:
            try:
                # Run Search 1: 3-3.5 rooms
                logger.info("\n" + "="*60)
                logger.info("Running Search 1: 3-3.5 rooms, 70+ sqm, max 2.35M")
                logger.info("="*60)
                API_PARAMS = API_PARAMS_SEARCH_1
                await check_yad2_listings(max_pages=1)
                
                # Add delay between searches to avoid bot detection
                logger.debug("Waiting 10 seconds between searches...")
                await asyncio.sleep(10)
                
                # Run Search 2: 4-4.5 rooms
                logger.info("\n" + "="*60)
                logger.info("Running Search 2: 4-4.5 rooms, 80+ sqm, max 2.6M")
                logger.info("="*60)
                API_PARAMS = API_PARAMS_SEARCH_2
                await check_yad2_listings(max_pages=1)
            except Exception as e:
                logger.exception(f"Error during check cycle: {e}")
            
            logger.debug(f"Both searches complete. Waiting {check_interval} seconds before next check...")
            await asyncio.sleep(check_interval)

if __name__ == "__main__":
    from sys import platform
    if platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    logger.info("="*60)
    logger.info("Starting Yad2 Apartment Monitor with Telegram Alerts")
    logger.info(f"API: {API_BASE_URL}")
    logger.info(f"Search filters: {API_PARAMS}")
    logger.info("="*60)
    
    # Check if running in GitHub Actions (via environment variable)
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    
    if is_github_actions:
        logger.info("Running in GitHub Actions - single run mode")
        asyncio.run(main_loop(run_once=True))
    else:
        logger.info("Running locally - continuous loop mode (every 120 seconds)")
        asyncio.run(main_loop(check_interval=120, run_once=False))
