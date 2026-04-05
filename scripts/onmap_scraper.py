"""
onmap_scraper.py — OnMap.co.il listing scraper using Playwright browser automation.

Loads the page in a real stealth browser (anti-bot config from ShamaiAI/base_scraper),
then intercepts network API responses to capture clean JSON property data — more
reliable than HTML parsing because it grabs the same data the UI uses.

If no API responses yield property data, the scraper logs clearly and exits without
deactivating existing listings (safe degradation).

Graceful fail — exits 0 on any error so it never blocks the nightly workflow.
"""

import asyncio
import os
import sys
import logging
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import init_db, upsert_listing, deactivate_missing

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# OnMap buy listings — English interface, all Israel.
# We filter to Rishon Lezion in code after capturing network responses.
ONMAP_URL = "https://www.onmap.co.il/en/listings/sale"

# All spellings/transliterations of Rishon Lezion that may appear in API data
RISHON_CITY_VARIANTS = {
    "ראשון לציון",
    "rishon le-zion",
    "rishon lezion",
    "rishon-le-zion",
    "rishon le zion",
    "rishon letzion",
}

NEIGHBORHOODS_HE = {"הרקפות", "נרקיסים", "נוריות", "נחלת יהודה"}

# Keys present in property objects (used to detect API responses that contain listings)
PROPERTY_SIGNAL_KEYS = {"price", "rooms", "floor", "sqm", "area", "askingPrice", "numberOfRooms"}


def _is_property_like(obj: dict) -> bool:
    return bool(PROPERTY_SIGNAL_KEYS & set(obj.keys()))


def _extract_items_from_response(data) -> list[dict]:
    """Try every common API response shape and return the property array, or []."""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("listings", "properties", "results", "items", "feed", "data"):
        val = data.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
        if isinstance(val, dict):
            for subkey in ("listings", "properties", "results", "items"):
                subval = val.get(subkey)
                if isinstance(subval, list) and subval and isinstance(subval[0], dict):
                    return subval
    return []


async def _launch_stealth_browser(playwright):
    """Launch Chromium with anti-bot settings (based on ShamaiAI base_scraper)."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, context


async def _capture_network_listings(page, url: str) -> list[dict]:
    """
    Navigate to url, intercept all JSON responses, and return any items
    that look like property listings.
    """
    captured: list[dict] = []

    async def handle_response(response):
        try:
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type:
                return
            if response.status != 200:
                return
            data = await response.json()
            items = _extract_items_from_response(data)
            if items and _is_property_like(items[0]):
                logger.info(f"  API hit: {len(items)} items from {response.url[:90]}")
                captured.extend(items)
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        # Scroll to trigger infinite-scroll / lazy-load API calls
        for _ in range(4):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
    except Exception as e:
        logger.warning(f"Navigation issue (continuing): {e}")

    return captured


def extract_onmap_listing(item: dict) -> Optional[dict]:
    """Normalize a raw OnMap API item to our listing schema. Returns None if filtered out."""
    try:
        listing_id = str(
            item.get("id") or item.get("propertyId") or item.get("listingId") or ""
        )
        if not listing_id:
            return None

        address = item.get("address") or {}
        neighborhood = (
            item.get("neighborhood")
            or address.get("neighborhood")
            or item.get("quarterName")
            or item.get("neighborhoodName")
            or ""
        )
        city = (
            item.get("city")
            or address.get("city")
            or item.get("cityName")
            or ""
        )
        street = (
            item.get("street")
            or address.get("street")
            or item.get("streetName")
            or ""
        )

        # Filter: must be Rishon Lezion
        if city.strip() not in RISHON_CITY_VARIANTS and city.strip() != "ראשון לציון":
            return None

        # Filter: must be one of the target neighborhoods (skip if neighborhood is unknown)
        if neighborhood and neighborhood not in NEIGHBORHOODS_HE:
            return None

        price = item.get("price") or item.get("askingPrice") or 0
        rooms = item.get("rooms") or item.get("numberOfRooms")
        sqm = item.get("area") or item.get("squareMeter") or item.get("buildingArea")
        floor = item.get("floor") or item.get("floorNumber")

        images = item.get("images") or []
        cover_image = None
        if images and isinstance(images, list):
            first = images[0]
            cover_image = first.get("url") if isinstance(first, dict) else str(first)

        token = f"onmap_{listing_id}"
        listing_url = f"https://www.onmap.co.il/en/properties/{listing_id}"

        return {
            "url": listing_url,
            "price": int(price) if price else 0,
            "rooms": float(rooms) if rooms else None,
            "street": street,
            "neighborhood": neighborhood,
            "city": city,
            "floor": int(floor) if floor else None,
            "sqm": int(sqm) if sqm else 0,
            "phone": None,
            "token": token,
            "is_private": False,
            "cover_image": cover_image,
        }
    except Exception:
        return None


async def run_onmap_scraper():
    from playwright.async_api import async_playwright

    seen_tokens: set[str] = set()
    total_new = 0
    total_updated = 0

    async with async_playwright() as playwright:
        browser, context = await _launch_stealth_browser(playwright)
        page = await context.new_page()

        try:
            logger.info(f"OnMap: loading {ONMAP_URL}")
            raw_items = await _capture_network_listings(page, ONMAP_URL)
        finally:
            await browser.close()

    logger.info(f"OnMap: {len(raw_items)} raw items captured from network")

    if not raw_items:
        logger.warning(
            "OnMap: no API responses captured — site may have changed its internals. "
            "Skipping deactivation to preserve existing data."
        )
        return

    for item in raw_items:
        listing = extract_onmap_listing(item)
        if not listing:
            continue
        token = listing["token"]
        seen_tokens.add(token)
        is_new, price_changed, _ = upsert_listing(token, listing, source="onmap")
        if is_new:
            total_new += 1
        elif price_changed:
            total_updated += 1

    deactivated = deactivate_missing(seen_tokens, source="onmap")
    logger.info(
        f"OnMap scrape complete: {total_new} new, {total_updated} updated, "
        f"{deactivated} deactivated ({len(seen_tokens)} seen this run)"
    )


def main():
    try:
        init_db()
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(run_onmap_scraper())
    except Exception as e:
        logger.error(f"OnMap scraper error: {e}")
        logger.info("OnMap scraper exiting gracefully (non-critical source)")
        sys.exit(0)


if __name__ == "__main__":
    main()
