"""
madlan_scraper.py — Madlan.co.il listing scraper using Playwright browser automation.

Loads the Rishon Lezion for-sale page in a real stealth browser, then intercepts
network API/GraphQL responses to capture clean JSON property data.

Tries two URL slugs for Rishon Lezion since the transliteration is ambiguous.
If no API responses yield property data, logs clearly and exits without deactivating
existing listings (safe degradation).

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

# Rishon Lezion for-sale pages — try both slug variants
MADLAN_URLS = [
    "https://www.madlan.co.il/for-sale/%D7%A8%D7%90%D7%A9%D7%95%D7%9F-%D7%9C%D7%A6%D7%99%D7%95%D7%9F-%D7%99%D7%A9%D7%A8%D7%90%D7%9C",
]

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
    for key in ("listings", "properties", "results", "items", "feed", "data", "searchResults"):
        val = data.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
        if isinstance(val, dict):
            for subkey in ("listings", "properties", "results", "items", "searchResults"):
                subval = val.get(subkey)
                if isinstance(subval, list) and subval and isinstance(subval[0], dict):
                    return subval
    return []


async def _launch_stealth_browser(playwright):
    """Launch Chromium with stealth patches to bypass bot detection."""
    from playwright_stealth import Stealth

    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--window-size=1920,1080",
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
    page = await context.new_page()
    await Stealth().apply_stealth_async(page)
    return browser, context, page


async def _capture_network_listings(page, url: str) -> list[dict]:
    """
    Navigate to url, intercept all JSON responses, and return any items
    that look like property listings.
    """
    import json as _json

    captured: list[dict] = []
    all_responses: list[tuple] = []  # (status, content_type, url)

    async def handle_response(response):
        try:
            ct = response.headers.get("content-type", "")
            all_responses.append((response.status, ct, response.url))

            if response.status != 200:
                return
            if "json" not in ct:
                return

            raw_text = await response.text()
            if not raw_text.strip().startswith(("{", "[")):
                return

            try:
                data = _json.loads(raw_text)
            except Exception:
                return

            top_keys = list(data.keys())[:8] if isinstance(data, dict) else f"list[{len(data)}]"
            logger.info(f"  [json] {response.url[:90]}")
            logger.info(f"         keys: {top_keys}")

            items = _extract_items_from_response(data)
            if items:
                if _is_property_like(items[0]):
                    logger.info(f"         → MATCH {len(items)} items, sample: {list(items[0].keys())[:10]}")
                    captured.extend(items)
                else:
                    logger.info(f"         → list[{len(items)}] but not property-like: {list(items[0].keys())[:8]}")
            else:
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            logger.info(f"         [{k}]→dict keys: {list(v.keys())[:8]}")
                        elif isinstance(v, list) and v:
                            fk = list(v[0].keys())[:8] if isinstance(v[0], dict) else type(v[0]).__name__
                            logger.info(f"         [{k}]→list[{len(v)}] first-keys: {fk}")

        except Exception as exc:
            logger.debug(f"  [net] handler error: {exc}")

    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)  # let initial JS settle
        for _ in range(6):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
    except Exception as e:
        logger.warning(f"Navigation issue (continuing): {e}")

    # --- Screenshot so we can see what the page actually shows ---
    screenshot_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "madlan_debug.png")
    try:
        await page.screenshot(path=screenshot_path, full_page=False)
        logger.info(f"  [debug] Screenshot saved: {screenshot_path}")
    except Exception as exc:
        logger.warning(f"  [debug] Screenshot failed: {exc}")

    # --- Summary of all network traffic ---
    logger.info(f"  [net] Total responses: {len(all_responses)}")
    non_json = [(s, ct, u) for s, ct, u in all_responses if "json" not in ct]
    json_hits = [(s, ct, u) for s, ct, u in all_responses if "json" in ct]
    logger.info(f"  [net] JSON responses: {len(json_hits)}, non-JSON: {len(non_json)}")
    logger.info("  [net] All response URLs:")
    for s, ct, u in all_responses:
        logger.info(f"         {s} [{ct.split(';')[0].strip()}] {u[:100]}")

    # --- Fallback: __NEXT_DATA__ ---
    if not captured:
        logger.info("  [next] Trying __NEXT_DATA__ extraction")
        try:
            next_data = await page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent : null; }"
            )
            if next_data:
                nd = _json.loads(next_data)
                logger.info(f"  [next] found, top keys: {list(nd.keys())[:8]}")
                props = nd.get("props", {}).get("pageProps", {})
                logger.info(f"  [next] pageProps keys: {list(props.keys())[:12]}")
                _walk_and_collect(props, captured, prefix="pageProps")
            else:
                logger.info("  [next] No __NEXT_DATA__ on page")
                # Log page title and first 500 chars of body text so we can see if it's a CAPTCHA/block
                title = await page.title()
                body_text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 500) : ''")
                logger.info(f"  [page] title: {title!r}")
                logger.info(f"  [page] body snippet: {body_text[:300]!r}")
        except Exception as exc:
            logger.warning(f"  [next] failed: {exc}")

    logger.info(f"  [net] captured items total: {len(captured)}")
    return captured


def _walk_and_collect(obj, captured: list, prefix: str = "", depth: int = 0):
    """Recursively walk a dict/list to find property-like arrays."""
    import json as _json
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}"
            if isinstance(v, list) and v and isinstance(v[0], dict):
                logger.info(f"  [next] {path} list[{len(v)}] keys: {list(v[0].keys())[:10]}")
                if _is_property_like(v[0]):
                    logger.info(f"  [next] → MATCH at {path}")
                    captured.extend(v)
                else:
                    _walk_and_collect(v[0], captured, path + "[0]", depth + 1)
            elif isinstance(v, dict):
                _walk_and_collect(v, captured, path, depth + 1)


def extract_madlan_listing(item: dict) -> Optional[dict]:
    """Normalize a raw Madlan API item to our listing schema. Returns None if filtered out."""
    try:
        listing_id = str(
            item.get("id") or item.get("listingId") or item.get("propertyId") or ""
        )
        if not listing_id:
            return None

        address = item.get("address") or {}
        neighborhood = (
            item.get("neighborhood")
            or address.get("neighborhood")
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

        # Filter: must be one of the target neighborhoods (skip if neighborhood unknown)
        if neighborhood and neighborhood not in NEIGHBORHOODS_HE:
            return None

        price = item.get("price") or item.get("askingPrice") or 0
        rooms = item.get("rooms") or item.get("numberOfRooms")
        sqm = item.get("area") or item.get("squareMeter") or item.get("buildingArea")
        floor = item.get("floor") or item.get("floorNumber")

        images = item.get("images") or item.get("photos") or []
        cover_image = None
        if images and isinstance(images, list):
            first = images[0]
            cover_image = first.get("url") if isinstance(first, dict) else str(first)

        token = f"madlan_{listing_id}"
        listing_url = f"https://www.madlan.co.il/listings/{listing_id}"

        return {
            "url": listing_url,
            "price": int(price) if price else 0,
            "rooms": float(rooms) if rooms else None,
            "street": street,
            "neighborhood": neighborhood,
            "city": city or "ראשון לציון",
            "floor": int(floor) if floor else None,
            "sqm": int(sqm) if sqm else 0,
            "phone": None,
            "token": token,
            "is_private": False,
            "cover_image": cover_image,
        }
    except Exception:
        return None


async def run_madlan_scraper():
    from playwright.async_api import async_playwright

    seen_tokens: set[str] = set()
    total_new = 0
    total_updated = 0
    all_raw_items: list[dict] = []

    async with async_playwright() as playwright:
        browser, context, page = await _launch_stealth_browser(playwright)

        try:
            for url in MADLAN_URLS:
                logger.info(f"Madlan: trying {url}")
                raw_items = await _capture_network_listings(page, url)
                logger.info(f"  → {len(raw_items)} raw items captured")
                all_raw_items.extend(raw_items)
                if raw_items:
                    # Found results on this URL slug — no need to try the next
                    break
                await asyncio.sleep(2)
        finally:
            await browser.close()

    logger.info(f"Madlan: {len(all_raw_items)} total raw items from network")

    if not all_raw_items:
        logger.warning(
            "Madlan: no API responses captured — site may have changed its internals "
            "or the city slug is wrong. Skipping deactivation to preserve existing data."
        )
        return

    for item in all_raw_items:
        listing = extract_madlan_listing(item)
        if not listing:
            continue
        token = listing["token"]
        seen_tokens.add(token)
        is_new, price_changed, _ = upsert_listing(token, listing, source="madlan")
        if is_new:
            total_new += 1
        elif price_changed:
            total_updated += 1

    deactivated = deactivate_missing(seen_tokens, source="madlan")
    logger.info(
        f"Madlan scrape complete: {total_new} new, {total_updated} updated, "
        f"{deactivated} deactivated ({len(seen_tokens)} seen this run)"
    )


def main():
    try:
        init_db()
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(run_madlan_scraper())
    except Exception as e:
        logger.error(f"Madlan scraper error: {e}")
        logger.info("Madlan scraper exiting gracefully (non-critical source)")
        sys.exit(0)


if __name__ == "__main__":
    main()
