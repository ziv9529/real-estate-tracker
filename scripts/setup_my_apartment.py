"""
setup_my_apartment.py — One-time CLI to configure your apartment in the database.

Run this locally once:
    python scripts/setup_my_apartment.py

You will be prompted for your apartment details. These are used by the daily
report and AI analysis to compare your apartment's value against the market.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import init_db, set_my_apartment, get_my_apartment


def prompt(label: str, default=None, cast=str, required=True):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if not val:
            if default is not None:
                return default
            if not required:
                return None
            print("  (required)")
            continue
        try:
            return cast(val)
        except (ValueError, TypeError):
            print(f"  (invalid value, expected {cast.__name__})")


def main():
    init_db()

    print("\n=== My Apartment Configuration ===")
    print("This data is used to compare your apartment's value against the market.\n")

    existing = get_my_apartment()
    if existing:
        print("Current configuration:")
        for k, v in existing.items():
            if k != "id" and v is not None:
                print(f"  {k}: {v}")
        overwrite = input("\nOverwrite? (y/N): ").strip().lower()
        if overwrite != "y":
            print("Keeping existing configuration.")
            return

    neighborhood = prompt("Neighborhood (Hebrew, e.g. הרקפות)", default=existing.get("neighborhood") if existing else None)
    city = prompt("City (Hebrew, e.g. ראשון לציון)", default=existing.get("city") if existing else "ראשון לציון")
    rooms = prompt("Rooms (e.g. 3 or 3.5)", default=existing.get("rooms") if existing else None, cast=float)
    sqm = prompt("Square meters (optional)", default=existing.get("sqm") if existing else None, cast=int, required=False)
    floor = prompt("Floor (optional)", default=existing.get("floor") if existing else None, cast=int, required=False)
    purchase_price = prompt("Purchase price in ILS (optional, e.g. 2100000)", default=existing.get("purchase_price") if existing else None, cast=int, required=False)
    purchase_date = prompt("Purchase date (YYYY-MM-DD, optional)", default=existing.get("purchase_date") if existing else None, required=False)
    notes = prompt("Notes (optional)", default=existing.get("notes") if existing else None, required=False)

    set_my_apartment(
        neighborhood=neighborhood,
        city=city,
        rooms=rooms,
        sqm=sqm,
        floor=floor,
        purchase_price=purchase_price,
        purchase_date=purchase_date,
        notes=notes,
    )

    print("\n✓ Apartment configuration saved to database.db")
    print(f"  {rooms} rooms | {sqm} sqm | {neighborhood}, {city}")
    if purchase_price:
        print(f"  Purchased: ₪{purchase_price:,}" + (f" on {purchase_date}" if purchase_date else ""))


if __name__ == "__main__":
    main()
