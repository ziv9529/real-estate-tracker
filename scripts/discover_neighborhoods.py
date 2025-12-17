"""
Manually defined neighborhoods for Rishon Lezion based on actual Yad2 listings.
These were discovered from the API responses of actual property listings.
"""

import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Neighborhoods for Rishon Lezion (city 8300)
# These are the neighborhoods that appeared in actual Yad2 listings
RISHON_LEZION_NEIGHBORHOODS = {
    "אברמוביץ'": None,  # ID unknown
    "הרקפות": None,
    "השומר": None,
    "כצנלסון": None,
    "מישור הנוף": None,
    "נאות אשלים": None,
    "נווה הדרים": None,
    "נווה חוף": None,
    "נרקיסים": None,
    "קדמת ראשון": 284,
    "קרית גנים": None,
    "קרית ראשון": 295,
    "רביבים, גני ראשון": 324,
    "רמב\"ם": None,
    "רמז, מערב ותיק": None,
    "רמת אליהו": None,
    "מרום ראשון": 470,
}

def main():
    logger.info("="*60)
    logger.info("Rishon Lezion Neighborhoods (16 total)")
    logger.info("="*60)
    
    neighborhoods = {}
    unknown_ids = []
    
    # Known IDs from address-autocomplete
    for name, hood_id in RISHON_LEZION_NEIGHBORHOODS.items():
        if hood_id is not None:
            neighborhoods[hood_id] = name
            logger.info(f"✓ {hood_id:8d} | {name}")
        else:
            unknown_ids.append(name)
    
    logger.info("\n" + "-"*60)
    logger.info(f"Neighborhoods with KNOWN IDs: {len(neighborhoods)}")
    logger.info(f"Neighborhoods with UNKNOWN IDs: {len(unknown_ids)} (need API discovery)")
    logger.info("-"*60)
    
    if unknown_ids:
        logger.info("\nNeighborhoods awaiting ID discovery:")
        for name in unknown_ids:
            logger.info(f"  ⚠ {name}")
    
    # Save what we have
    save_neighborhoods(neighborhoods, unknown_ids)

def save_neighborhoods(neighborhoods, unknown_ids):
    """Save neighborhoods to files"""
    
    sorted_neighborhoods = sorted(neighborhoods.items())
    
    # Save as JSON
    with open("discovered_neighborhoods.json", "w", encoding="utf-8") as f:
        json.dump({
            "city_id": 8300,
            "city_name": "ראשון לציון",
            "total_known": len(neighborhoods),
            "total_unknown": len(unknown_ids),
            "neighborhoods_with_ids": {str(nid): name for nid, name in sorted_neighborhoods},
            "neighborhoods_unknown_ids": unknown_ids
        }, f, indent=2, ensure_ascii=False)
    logger.info("✓ Saved to discovered_neighborhoods.json")
    
    # Save as Python dict
    with open("neighborhoods_dict.py", "w", encoding="utf-8") as f:
        f.write("# Auto-generated neighborhood IDs for Yad2 Scraper\n")
        f.write("# City: ראשון לציון (Rishon Lezion, ID 8300)\n")
        f.write(f"# Total neighborhoods with known IDs: {len(neighborhoods)}\n")
        f.write(f"# Total neighborhoods with unknown IDs: {len(unknown_ids)}\n\n")
        
        f.write("NEIGHBORHOODS = {\n")
        for nid, name in sorted_neighborhoods:
            f.write(f"    {nid}: '{name}',\n")
        f.write("}\n\n")
        
        if unknown_ids:
            f.write("# Neighborhoods without IDs (need discovery):\n")
            for name in unknown_ids:
                f.write(f"#   '{name}'\n")
        
        f.write("\n# For scraper_with_alerts.py, use:\n")
        neighborhood_ids = [nid for nid, _ in sorted_neighborhoods]
        f.write(f"# WANTED_NEIGHBORHOOD_IDS = {neighborhood_ids}\n")
    logger.info("✓ Saved to neighborhoods_dict.py")
    
    # Save as summary text
    with open("neighborhoods_summary.txt", "w", encoding="utf-8") as f:
        f.write("="*70 + "\n")
        f.write("Neighborhood Summary for Rishon Lezion (City ID: 8300)\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"TOTAL NEIGHBORHOODS: {len(neighborhoods) + len(unknown_ids)}\n")
        f.write(f"  - With known IDs: {len(neighborhoods)}\n")
        f.write(f"  - With unknown IDs: {len(unknown_ids)}\n\n")
        
        f.write("="*70 + "\n")
        f.write("NEIGHBORHOODS WITH IDS (Ready for API filtering)\n")
        f.write("="*70 + "\n")
        f.write("ID       | Neighborhood Name\n")
        f.write("-"*70 + "\n")
        for nid, name in sorted_neighborhoods:
            f.write(f"{nid:8d} | {name}\n")
        
        if unknown_ids:
            f.write("\n" + "="*70 + "\n")
            f.write("NEIGHBORHOODS WITHOUT IDS (Cannot be filtered yet)\n")
            f.write("="*70 + "\n")
            for i, name in enumerate(unknown_ids, 1):
                f.write(f"{i:2d}. {name}\n")
        
        f.write("\n" + "="*70 + "\n")
        f.write("USE IN scraper_with_alerts.py:\n")
        f.write("="*70 + "\n")
        neighborhood_ids = [nid for nid, _ in sorted_neighborhoods]
        f.write(f"WANTED_NEIGHBORHOOD_IDS = {neighborhood_ids}\n")
    logger.info("✓ Saved to neighborhoods_summary.txt")
    
    # Show Python format
    neighborhood_ids = [nid for nid, _ in sorted_neighborhoods]
    logger.info("\n" + "="*60)
    logger.info("Copy this to scraper_with_alerts.py:")
    logger.info("="*60)
    logger.info(f"\nWANTED_NEIGHBORHOOD_IDS = {neighborhood_ids}")

if __name__ == "__main__":
    import sys
    if sys.platform.startswith("win"):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    main()
