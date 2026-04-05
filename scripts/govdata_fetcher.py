"""
govdata_fetcher.py — Fetches actual real estate transaction data from nadlan.gov.il
(Israeli government property transaction records).

Runs once per month (monthly_govdata.yml workflow).
Data is updated monthly by the Israel Tax Authority.

This provides ACTUAL SOLD PRICES (not asking prices) — the most reliable
data for valuing your apartment and understanding market reality.

API: nadlan.gov.il uses a public REST API to expose transaction records.
"""

import os
import sys
import json
import logging
import datetime
import requests
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import init_db, upsert_gov_transaction

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# nadlan.gov.il API endpoint for transaction data
# The API is documented at https://www.nadlan.gov.il/
NADLAN_API_BASE = "https://www.nadlan.gov.il/Nadlan.REST/Homepage/GetAssestsByFilter"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9",
    "Referer": "https://www.nadlan.gov.il/",
    "Content-Type": "application/json",
}

# Rishon Lezion city code for nadlan.gov.il
RISHON_LEZION_CITY_CODE = "6900"

TARGET_NEIGHBORHOODS = [
    "הרקפות",
    "נרקיסים",
    "נוריות",
    "נחלת יהודה",
]


def build_request_payload(neighborhood: str, rooms_min: int, rooms_max: int,
                           months_back: int = 12) -> dict:
    """Build the POST payload for the nadlan API."""
    date_from = (datetime.date.today() - datetime.timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
    return {
        "CityCode": RISHON_LEZION_CITY_CODE,
        "Neighborhood": neighborhood,
        "MinRooms": rooms_min,
        "MaxRooms": rooms_max,
        "PropertyType": "1",  # Apartment
        "DateFrom": date_from,
        "PageNumber": 1,
        "PageSize": 100,
    }


def parse_transaction(item: dict) -> dict | None:
    """Extract normalized transaction data from a nadlan.gov.il API response item."""
    try:
        price = item.get("DEALAMOUNT") or item.get("DealAmount")
        if not price or int(price) < 100000:
            return None

        deal_date = item.get("DEALDATETIME") or item.get("DealDate") or ""
        if deal_date:
            # Normalize to YYYY-MM-DD
            deal_date = str(deal_date)[:10]

        street = item.get("STREET") or item.get("Street") or ""
        neighborhood = item.get("NEIGHBORHOOD") or item.get("Neighborhood") or ""
        rooms_raw = item.get("ROOMS") or item.get("Rooms")
        sqm_raw = item.get("BUILDINGAREA") or item.get("BuildingArea") or item.get("Area")
        floor_raw = item.get("FLOORNUMBER") or item.get("FloorNumber")

        rooms = float(rooms_raw) if rooms_raw else None
        sqm = int(float(sqm_raw)) if sqm_raw else None
        floor = int(floor_raw) if floor_raw else None
        price_int = int(price)

        return {
            "deal_date": deal_date,
            "city": "ראשון לציון",
            "neighborhood": neighborhood,
            "street": street,
            "rooms": rooms,
            "sqm": sqm,
            "floor": floor,
            "price": price_int,
            "source_url": "https://www.nadlan.gov.il/",
        }
    except Exception:
        return None


def fetch_transactions(neighborhood: str, rooms_min: int, rooms_max: int) -> list[dict]:
    """Fetch transaction records from nadlan.gov.il for a given segment."""
    try:
        payload = build_request_payload(neighborhood, rooms_min, rooms_max)
        response = requests.post(NADLAN_API_BASE, json=payload, headers=HEADERS, timeout=30)

        if response.status_code != 200:
            logger.warning(f"nadlan API returned {response.status_code} for {neighborhood}")
            return []

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type and "text/json" not in content_type:
            # Try parsing anyway
            try:
                data = response.json()
            except Exception:
                logger.warning(f"nadlan returned non-JSON for {neighborhood}: {content_type}")
                return []
        else:
            data = response.json()

        # Handle different response structures
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("Data")
                or data.get("data")
                or data.get("Results")
                or data.get("results")
                or []
            )
        else:
            return []

        return items

    except Exception as e:
        logger.warning(f"Failed to fetch nadlan data for {neighborhood}: {e}")
        return []


def main():
    try:
        init_db()

        total_inserted = 0
        today = datetime.date.today().isoformat()
        logger.info(f"Starting government transaction data fetch — {today}")

        for neighborhood in TARGET_NEIGHBORHOODS:
            for rooms_min, rooms_max in [(3, 4), (4, 5)]:
                logger.info(f"  Fetching: {neighborhood}, {rooms_min}-{rooms_max} rooms")
                items = fetch_transactions(neighborhood, rooms_min, rooms_max)
                logger.info(f"  Got {len(items)} raw transactions")

                for item in items:
                    tx = parse_transaction(item)
                    if not tx:
                        continue

                    upsert_gov_transaction(
                        deal_date=tx["deal_date"],
                        city=tx["city"],
                        neighborhood=tx.get("neighborhood") or neighborhood,
                        street=tx["street"],
                        rooms=tx["rooms"],
                        sqm=tx["sqm"],
                        floor=tx["floor"],
                        price=tx["price"],
                        source_url=tx["source_url"],
                    )
                    total_inserted += 1

                import time
                time.sleep(1)  # Polite delay between API calls

        logger.info(f"Government data fetch complete: {total_inserted} transactions processed")

    except Exception as e:
        logger.error(f"govdata_fetcher error: {e}")
        logger.info("Exiting gracefully (non-critical source)")
        sys.exit(0)


if __name__ == "__main__":
    main()
