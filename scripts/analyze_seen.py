#!/usr/bin/env python3
"""
Analyze seen.json to identify:
1. Missing phone numbers
2. Potential duplicates that weren't caught
3. Data quality issues
4. Patterns and recommendations
"""

import json
import os
from collections import defaultdict
from typing import Dict, List, Tuple

SEEN_FILE = "seen.json"

def load_seen():
    """Load the seen.json file"""
    if not os.path.exists(SEEN_FILE):
        print(f"❌ {SEEN_FILE} not found!")
        return {}
    
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def analyze_missing_phones(seen: Dict):
    """Analyze listings missing phone numbers"""
    print("\n📞 PHONE NUMBER ANALYSIS")
    print("=" * 60)
    
    missing_phone = []
    with_phone = []
    
    for url, data in seen.items():
        if not data.get("phone"):
            missing_phone.append({
                "url": url,
                "token": data.get("token"),
                "city": data.get("city"),
                "street": data.get("street"),
                "price": data.get("price"),
            })
        else:
            with_phone.append(url)
    
    print(f"Total listings: {len(seen)}")
    print(f"With phone: {len(with_phone)} ({len(with_phone)/len(seen)*100:.1f}%)")
    print(f"Missing phone: {len(missing_phone)} ({len(missing_phone)/len(seen)*100:.1f}%)")
    
    if missing_phone:
        print(f"\n⚠️  Listings without phone ({len(missing_phone)}):")
        for item in sorted(missing_phone, key=lambda x: x["price"], reverse=True)[:10]:
            print(f"  • {item['token']}: {item['city']} - {item['street']} | {item['price']:,}₪")
        if len(missing_phone) > 10:
            print(f"  ... and {len(missing_phone) - 10} more")
    
    return missing_phone, with_phone

def find_potential_duplicates(seen: Dict) -> List[List[Dict]]:
    """Find potential duplicates based on location + size"""
    print("\n🔄 POTENTIAL DUPLICATES ANALYSIS")
    print("=" * 60)
    
    # Group by (city, neighborhood, street, floor, rooms, sqm)
    location_groups = defaultdict(list)
    
    for url, data in seen.items():
        key = (
            data.get("city"),
            data.get("neighborhood"),
            data.get("street"),
            data.get("floor"),
            data.get("rooms"),
            data.get("sqm"),
        )
        location_groups[key].append({"url": url, "data": data})
    
    # Find groups with more than 1 entry
    duplicates = [group for group in location_groups.values() if len(group) > 1]
    
    print(f"Total listings: {len(seen)}")
    print(f"Unique locations: {len(location_groups)}")
    print(f"Duplicate groups found: {len(duplicates)}")
    
    if duplicates:
        print(f"\n⚠️  Potential duplicates (same location + size):")
        for i, group in enumerate(sorted(duplicates, key=lambda g: len(g), reverse=True), 1):
            first = group[0]["data"]
            print(f"\n  Group {i}: {len(group)} listings")
            print(f"    Location: {first.get('city')}, {first.get('neighborhood')}, {first.get('street')}")
            print(f"    Floor: {first.get('floor')} | Rooms: {first.get('rooms')} | SQM: {first.get('sqm')}m²")
            print(f"    Prices:")
            for item in sorted(group, key=lambda x: x["data"].get("price", 0)):
                price = item["data"].get("price", "?")
                token = item["data"].get("token")
                phone = item["data"].get("phone", "no phone")
                print(f"      • {token}: {price:,}₪ | Phone: {phone}")
    
    return duplicates

def find_price_anomalies(seen: Dict):
    """Find unusual price patterns"""
    print("\n💰 PRICE ANALYSIS")
    print("=" * 60)
    
    # Group by (rooms, sqm range)
    price_groups = defaultdict(list)
    
    for url, data in seen.items():
        rooms = data.get("rooms")
        sqm = data.get("sqm", 0)
        price = data.get("price", 0)
        
        if rooms and sqm and price:
            sqm_range = f"{sqm - (sqm % 10)}-{sqm - (sqm % 10) + 10}"
            key = (rooms, sqm_range)
            price_groups[key].append(price)
    
    print("Price ranges by room count and sqm:")
    for (rooms, sqm_range), prices in sorted(price_groups.items()):
        if prices:
            avg_price = sum(prices) / len(prices)
            min_price = min(prices)
            max_price = max(prices)
            print(f"  {rooms} rooms, {sqm_range}m²: {min_price:,}₪ - {max_price:,}₪ (avg: {avg_price:,.0f}₪)")

def analyze_by_neighborhood(seen: Dict):
    """Analyze distribution by neighborhood"""
    print("\n🏘️  NEIGHBORHOOD ANALYSIS")
    print("=" * 60)
    
    neighborhoods = defaultdict(int)
    for url, data in seen.items():
        neighborhood = data.get("neighborhood", "Unknown")
        neighborhoods[neighborhood] += 1
    
    print("Listings by neighborhood:")
    for neighborhood, count in sorted(neighborhoods.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {neighborhood}: {count}")

def analyze_listing_types(seen: Dict):
    """Analyze private vs agency listings"""
    print("\n🏷️  LISTING TYPE ANALYSIS")
    print("=" * 60)
    
    private_count = 0
    agency_count = 0
    unknown_count = 0
    
    for url, data in seen.items():
        if data.get("is_private"):
            private_count += 1
        else:
            agency_count += 1
    
    print(f"Private listings (פרטי): {private_count} ({private_count/len(seen)*100:.1f}%)")
    print(f"Agency listings (תיווך): {agency_count} ({agency_count/len(seen)*100:.1f}%)")

def main():
    print("🔍 ANALYZING seen.json")
    print("=" * 60)
    
    seen = load_seen()
    if not seen:
        return
    
    # Run analyses
    missing, with_phone = analyze_missing_phones(seen)
    duplicates = find_potential_duplicates(seen)
    find_price_anomalies(seen)
    analyze_by_neighborhood(seen)
    analyze_listing_types(seen)
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("=" * 60)
    
    if len(missing) / len(seen) > 0.1:
        print("⚠️  More than 10% listings missing phones - verify get_contact_info() is working")
    
    if len(duplicates) > 0:
        print(f"⚠️  {len(duplicates)} duplicate location groups found")
        print("    → Check if is_possible_duplicate() is being called correctly")
        print("    → Verify phone comparison was removed from duplicate logic")
    
    print("\n✅ Analysis complete!")

if __name__ == "__main__":
    main()
