#!/usr/bin/env python3
"""
Generate a CSV file and an HTML table from seen.json for easy viewing and analysis.
This script is automatically run by the GitHub workflow after each scrape.
"""

import json
import csv
import os
from datetime import datetime

SEEN_FILE = "seen.json"
CSV_OUTPUT = "listings.csv"
HTML_OUTPUT = "listings.html"

def generate_csv_from_seen():
    """Convert seen.json to a CSV file with nice formatting"""
    
    if not os.path.exists(SEEN_FILE):
        print(f"Error: {SEEN_FILE} not found")
        return
    
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_data = json.load(f)
        
        if not seen_data:
            print("No listings found in seen.json")
            return
        
        # Prepare data for CSV
        rows = []
        for url, listing in seen_data.items():
            rows.append({
                "URL": url,
                "Price (₪)": listing.get("price", ""),
                "Rooms": listing.get("rooms", ""),
                "Street": listing.get("street", ""),
                "Neighborhood": listing.get("neighborhood", ""),
                "City": listing.get("city", ""),
                "Floor": listing.get("floor", ""),
                "SqM": listing.get("sqm", ""),
                "Phone": listing.get("phone", ""),
                "Type": "Private" if listing.get("is_private") else "Agency",
                "Image URL": listing.get("cover_image", ""),
            })
        
        # Sort by price (descending) for easier browsing
        rows.sort(key=lambda x: x["Price (₪)"], reverse=True)
        
        # Write to CSV
        fieldnames = ["URL", "Price (₪)", "Rooms", "Street", "Neighborhood", "City", "Floor", "SqM", "Phone", "Type", "Image URL"]
        with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        print(f"✅ Generated {CSV_OUTPUT} with {len(rows)} listings")
        
        # Generate HTML table
        generate_html_from_seen(rows)
        
    except Exception as e:
        print(f"Error generating CSV: {e}")

def generate_html_from_seen(rows):
    """Generate an HTML table with images, filters, and sorting"""
    
    try:
        # Calculate statistics by room range
        rooms_3_35 = [r for r in rows if 3 <= float(r["Rooms"]) <= 3.5]
        rooms_4_45 = [r for r in rows if 4 <= float(r["Rooms"]) <= 4.5]
        
        avg_price_3_35 = int(sum(r["Price (₪)"] for r in rooms_3_35) / len(rooms_3_35)) if rooms_3_35 else 0
        avg_price_4_45 = int(sum(r["Price (₪)"] for r in rooms_4_45) / len(rooms_4_45)) if rooms_4_45 else 0
        
        # Search criteria
        search_1_info = "3-3.5 rooms | 70+ sqm | Max ₪2,350,000"
        search_2_info = "4-4.5 rooms | 85+ sqm | Max ₪2,700,000"
        
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Yad2 Listings - Live View</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: white;
            text-align: center;
            margin-bottom: 10px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .info {
            color: rgba(255,255,255,0.9);
            text-align: center;
            margin-bottom: 20px;
            font-size: 1.1em;
        }
        .search-info {
            background: rgba(255,255,255,0.1);
            border-left: 4px solid #3498db;
            color: white;
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-size: 0.95em;
            line-height: 1.6;
        }
        .search-info-title {
            font-weight: 600;
            margin-bottom: 8px;
            color: #fff;
        }
        .search-info-item {
            margin-bottom: 6px;
            padding-left: 20px;
            position: relative;
        }
        .search-info-item:before {
            content: "▶";
            position: absolute;
            left: 0;
            color: #3498db;
        }
        .stats {
            background: rgba(255,255,255,0.1);
            color: white;
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            display: flex;
            justify-content: center;
            gap: 30px;
            flex-wrap: wrap;
        }
        .stat {
            text-align: center;
        }
        .stat-value {
            font-size: 1.8em;
            font-weight: bold;
        }
        .stat-label {
            font-size: 0.9em;
            opacity: 0.9;
        }
        .stat-sublabel {
            font-size: 0.8em;
            opacity: 0.7;
            margin-top: 4px;
        }
        .filters-section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }
        .filters-title {
            font-size: 1.2em;
            font-weight: 600;
            color: #333;
            margin-bottom: 15px;
        }
        .filters-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .filter-group {
            display: flex;
            flex-direction: column;
        }
        .filter-label {
            font-size: 0.9em;
            font-weight: 600;
            color: #555;
            margin-bottom: 6px;
        }
        .filter-input, .filter-select {
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 0.95em;
            transition: border-color 0.2s ease;
        }
        .filter-input:focus, .filter-select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .filter-options {
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-height: 150px;
            overflow-y: auto;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 6px;
            background: #fafafa;
        }
        .filter-option {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .filter-option input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: #667eea;
        }
        .filter-option label {
            cursor: pointer;
            font-size: 0.95em;
            color: #333;
            flex: 1;
        }
        .filter-buttons {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            grid-column: 1 / -1;
        }
        .btn-filter {
            flex: 1;
            padding: 10px 15px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s ease;
            font-size: 0.95em;
        }
        .btn-apply {
            background-color: #2ecc71;
            color: white;
        }
        .btn-apply:hover {
            background-color: #27ae60;
        }
        .btn-clear {
            background-color: #e74c3c;
            color: white;
        }
        .btn-clear:hover {
            background-color: #c0392b;
        }
        .results-info {
            color: white;
            text-align: center;
            margin-bottom: 15px;
            font-size: 1.05em;
        }
        .listings-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }
        .listing-card {
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
            display: flex;
            flex-direction: column;
            height: 100%;
        }
        .listing-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 24px rgba(0,0,0,0.15);
        }
        .image-container {
            position: relative;
            width: 100%;
            height: 240px;
            background: #f0f0f0;
            overflow: hidden;
        }
        .listing-image {
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: transform 0.3s ease;
        }
        .listing-card:hover .listing-image {
            transform: scale(1.05);
        }
        .no-image {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #999;
            font-size: 0.9em;
        }
        .listing-content {
            padding: 16px;
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .price {
            font-size: 1.6em;
            font-weight: bold;
            color: #2ecc71;
            margin-bottom: 10px;
        }
        .details {
            font-size: 0.95em;
            color: #333;
            margin-bottom: 12px;
            line-height: 1.6;
        }
        .detail-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
        }
        .detail-label {
            font-weight: 600;
            color: #555;
        }
        .detail-value {
            color: #777;
            text-align: right;
        }
        .footer {
            display: flex;
            gap: 8px;
            margin-top: auto;
            padding-top: 12px;
            border-top: 1px solid #eee;
        }
        .btn {
            flex: 1;
            padding: 10px;
            text-align: center;
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.9em;
            font-weight: 600;
            transition: background-color 0.2s ease;
            display: inline-block;
        }
        .btn-link {
            background-color: #3498db;
            color: white;
        }
        .btn-link:hover {
            background-color: #2980b9;
        }
        .btn-phone {
            background-color: #e74c3c;
            color: white;
        }
        .btn-phone:hover {
            background-color: #c0392b;
        }
        .type-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            margin-top: 8px;
            margin-bottom: 8px;
        }
        .type-private {
            background-color: #f39c12;
            color: white;
        }
        .type-agency {
            background-color: #9b59b6;
            color: white;
        }
        .no-results {
            background: white;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            color: #666;
            font-size: 1.1em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 Yad2 Listings</h1>
        <div class="info">Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</div>
        
        <div class="search-info">
            <div class="search-info-title">📋 Active Searches</div>
            <div class="search-info-item"><strong>Search 1:</strong> """ + search_1_info + """</div>
            <div class="search-info-item"><strong>Search 2:</strong> """ + search_2_info + """</div>
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value">""" + str(len(rows)) + """</div>
                <div class="stat-label">Total Listings</div>
            </div>
            <div class="stat">
                <div class="stat-value">₪ """ + format(avg_price_3_35, ',') + """</div>
                <div class="stat-label">Average Price</div>
                <div class="stat-sublabel">3-3.5 Rooms (""" + str(len(rooms_3_35)) + """)</div>
            </div>
            <div class="stat">
                <div class="stat-value">₪ """ + format(avg_price_4_45, ',') + """</div>
                <div class="stat-label">Average Price</div>
                <div class="stat-sublabel">4-4.5 Rooms (""" + str(len(rooms_4_45)) + """)</div>
            </div>
        </div>

        <div class="filters-section">
            <div class="filters-title">🔍 Filters & Sort</div>
            <div class="filters-grid">
                <div class="filter-group">
                    <label class="filter-label">Rooms</label>
                    <div class="filter-options" id="roomsFilterContainer">
"""
        
        # Extract unique rooms, sorted
        rooms = sorted(set(r["Rooms"] for r in rows if r["Rooms"]))
        for i, room in enumerate(rooms):
            html_content += f'                        <div class="filter-option"><input type="checkbox" id="rooms_{i}" value="{room}" class="rooms-checkbox"><label for="rooms_{i}">{room} rooms</label></div>\n'
        
        html_content += """                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">Neighborhood</label>
                    <div class="filter-options" id="neighborhoodFilterContainer">
"""
        
        # Extract unique neighborhoods, sorted
        neighborhoods = sorted(set(r["Neighborhood"] for r in rows if r["Neighborhood"] != "לא ידוע"))
        for i, neighborhood in enumerate(neighborhoods):
            html_content += f'                        <div class="filter-option"><input type="checkbox" id="neighborhood_{i}" value="{neighborhood}" class="neighborhood-checkbox"><label for="neighborhood_{i}">{neighborhood}</label></div>\n'
        
        html_content += """                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">City</label>
                    <div class="filter-options" id="cityFilterContainer">
"""
        
        # Extract unique cities, sorted
        cities = sorted(set(r["City"] for r in rows if r["City"]))
        for i, city in enumerate(cities):
            html_content += f'                        <div class="filter-option"><input type="checkbox" id="city_{i}" value="{city}" class="city-checkbox"><label for="city_{i}">{city}</label></div>\n'
        
        html_content += """                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">Type</label>
                    <div class="filter-options">
                        <div class="filter-option"><input type="checkbox" id="type_0" value="Private" class="type-checkbox"><label for="type_0">Private</label></div>
                        <div class="filter-option"><input type="checkbox" id="type_1" value="Agency" class="type-checkbox"><label for="type_1">Agency</label></div>
                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">Sort by Price</label>
                    <select class="filter-select" id="priceSort">
                        <option value="">None</option>
                        <option value="desc">Highest First</option>
                        <option value="asc" selected>Lowest First</option>
                    </select>
                </div>
                <div class="filter-buttons">
                    <button class="btn-filter btn-apply" onclick="applyFilters()">Apply Filters</button>
                    <button class="btn-filter btn-clear" onclick="clearFilters()">Clear All</button>
                </div>
            </div>
        </div>

        <div class="results-info" id="resultsInfo"></div>
        <div class="listings-grid" id="listingsGrid">
"""
        
        # Add all listings data as hidden JSON
        html_content += '        </div>\n'
        html_content += '    </div>\n\n'
        html_content += '    <script>\n'
        html_content += '        const allListings = ' + json.dumps(rows) + ';\n'
        html_content += """
        function getFilteredListings() {
            // Get selected values from checkboxes (multiple select)
            const selectedRooms = Array.from(document.querySelectorAll('.rooms-checkbox:checked')).map(cb => parseFloat(cb.value));
            const selectedNeighborhoods = Array.from(document.querySelectorAll('.neighborhood-checkbox:checked')).map(cb => cb.value);
            const selectedCities = Array.from(document.querySelectorAll('.city-checkbox:checked')).map(cb => cb.value);
            const selectedTypes = Array.from(document.querySelectorAll('.type-checkbox:checked')).map(cb => cb.value);
            const priceSort = document.getElementById('priceSort').value;

            let filtered = allListings.filter(listing => {
                let match = true;
                
                // If rooms filters are selected, listing must match at least one
                if (selectedRooms.length > 0) {
                    match = match && selectedRooms.includes(parseFloat(listing['Rooms']));
                }
                
                // If neighborhood filters are selected, listing must match at least one
                if (selectedNeighborhoods.length > 0) {
                    match = match && selectedNeighborhoods.includes(listing['Neighborhood']);
                }
                
                // If city filters are selected, listing must match at least one
                if (selectedCities.length > 0) {
                    match = match && selectedCities.includes(listing['City']);
                }
                
                // If type filters are selected, listing must match at least one
                if (selectedTypes.length > 0) {
                    match = match && selectedTypes.includes(listing['Type']);
                }
                
                return match;
            });

            // Apply sorting
            if (priceSort === 'asc') {
                filtered.sort((a, b) => a['Price (₪)'] - b['Price (₪)']);
            } else if (priceSort === 'desc') {
                filtered.sort((a, b) => b['Price (₪)'] - a['Price (₪)']);
            }

            return filtered;
        }

        function renderListings(listings) {
            const grid = document.getElementById('listingsGrid');
            const info = document.getElementById('resultsInfo');
            
            if (listings.length === 0) {
                grid.innerHTML = '<div class="no-results" style="grid-column: 1/-1;">No listings match your filters</div>';
                info.textContent = 'Showing 0 listings';
                return;
            }

            info.textContent = `Showing ${listings.length} of ${allListings.length} listings`;
            
            grid.innerHTML = listings.map(row => {
                const price = `${parseInt(row['Price (₪)']).toLocaleString()}`;
                const imageUrl = row['Image URL'];
                const imageHtml = imageUrl ? 
                    `<img src="${imageUrl}" alt="Listing image" class="listing-image">` : 
                    '<div class="no-image">No image available</div>';
                const typeClass = row['Type'] === 'Private' ? 'type-private' : 'type-agency';
                const phone = row['Phone'] || 'N/A';
                
                return `
                    <div class="listing-card">
                        <div class="image-container">
                            ${imageHtml}
                        </div>
                        <div class="listing-content">
                            <div class="price">₪ ${price}</div>
                            <div class="details">
                                <div class="detail-row">
                                    <span class="detail-label">Rooms:</span>
                                    <span class="detail-value">${row['Rooms']}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">SqM:</span>
                                    <span class="detail-value">${row['SqM']}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Floor:</span>
                                    <span class="detail-value">${row['Floor']}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Street:</span>
                                    <span class="detail-value">${row['Street']}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Neighborhood:</span>
                                    <span class="detail-value">${row['Neighborhood']}</span>
                                </div>
                            </div>
                            <span class="type-badge ${typeClass}">${row['Type']}</span>
                            <div class="footer">
                                <a href="${row['URL']}" target="_blank" class="btn btn-link">View</a>
                                <a href="tel:${phone}" class="btn btn-phone">📞 Call</a>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function applyFilters() {
            const filtered = getFilteredListings();
            renderListings(filtered);
        }

        function clearFilters() {
            document.getElementById('roomsFilter').value = '';
            document.getElementById('neighborhoodFilter').value = '';
            document.getElementById('cityFilter').value = '';
            document.getElementById('typeFilter').value = '';
            document.getElementById('priceSort').value = '';
            renderListings(allListings);
        }

        // Initial render with default sort (lowest first)
        applyFilters();
    </script>
</body>
</html>
"""
        
        with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print(f"✅ Generated {HTML_OUTPUT} with {len(rows)} listings (with filters and sorting!)")
        
    except Exception as e:
        print(f"Error generating HTML: {e}")

if __name__ == "__main__":
    generate_csv_from_seen()

