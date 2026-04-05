"""
generate_dashboard.py — Builds listings.html from SQLite database.

Produces a self-contained HTML file with:
  1. My Apartment panel — purchase price vs current market comparables
  2. Price trend charts (Chart.js CDN) — 30-day median for 3-3.5 and 4-4.5 rooms
  3. Latest AI report — rendered Markdown from the ai_reports table
  4. All active listings — existing card grid with filters (preserved from generate_csv.py)

Called by morning_report.yml (daily) and weekly_analysis.yml (after AI report).
"""

import os
import sys
import json
import csv
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.db_utils import init_db, get_dashboard_data, get_comparable_stats

HTML_OUTPUT = "listings.html"
CSV_OUTPUT = "listings.csv"
CITY = "ראשון לציון"


def fmt(price) -> str:
    try:
        return f"₪{int(price):,}"
    except Exception:
        return str(price)


def escape_js(s: str) -> str:
    """Escape a string for safe embedding in JavaScript template literals."""
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def markdown_to_html(md: str) -> str:
    """Very minimal Markdown → HTML converter (no external deps)."""
    if not md:
        return ""
    lines = md.splitlines()
    html_lines = []
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("## "):
            html_lines.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("### "):
            html_lines.append(f"<h4>{line[4:]}</h4>")
        elif line.startswith("- ") or line.startswith("• "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.startswith("_") and line.endswith("_"):
            html_lines.append(f"<em>{line[1:-1]}</em>")
        elif line.strip() == "" or line.strip() == "---":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")
    return "\n".join(html_lines)


def generate_dashboard():
    init_db()
    data = get_dashboard_data()

    listings = data["listings"]
    trend_3 = data["trend_3"]
    trend_4 = data["trend_4"]
    ai_report = data.get("ai_report")
    my_apt = data.get("my_apartment")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── CSV export ────────────────────────────────────────────────────────────
    _generate_csv(listings)

    # ── Stats ─────────────────────────────────────────────────────────────────
    rooms_3 = [l for l in listings if l.get("rooms") and 3 <= float(l["rooms"]) <= 3.5]
    rooms_4 = [l for l in listings if l.get("rooms") and 4 <= float(l["rooms"]) <= 4.5]
    avg_3 = int(sum(l["price"] for l in rooms_3 if l.get("price")) / len(rooms_3)) if rooms_3 else 0
    avg_4 = int(sum(l["price"] for l in rooms_4 if l.get("price")) / len(rooms_4)) if rooms_4 else 0

    # ── My apartment comparison ───────────────────────────────────────────────
    my_apt_html = ""
    if my_apt:
        comp = get_comparable_stats(my_apt["rooms"], CITY, my_apt["neighborhood"])
        purchase = my_apt.get("purchase_price")
        if comp:
            diff = comp["avg"] - purchase if purchase else None
            diff_str = ""
            if diff is not None:
                sign = "▲" if diff >= 0 else "▼"
                diff_str = f'<span style="color:{"#27ae60" if diff >= 0 else "#e74c3c"}">{sign} {fmt(abs(diff))}</span>'
            my_apt_html = f"""
        <div class="my-apt-panel">
            <div class="my-apt-title">🏠 הנכס שלך — {my_apt['rooms']} חדרים, {my_apt['neighborhood']}</div>
            <div class="my-apt-grid">
                <div class="my-apt-stat">
                    <div class="my-apt-val">{comp.get('count', '—')}</div>
                    <div class="my-apt-label">נכסים דומים בשוק</div>
                </div>
                <div class="my-apt-stat">
                    <div class="my-apt-val">{fmt(comp['avg']) if comp else '—'}</div>
                    <div class="my-apt-label">מחיר ממוצע דומות</div>
                </div>
                <div class="my-apt-stat">
                    <div class="my-apt-val">{fmt(purchase) if purchase else '—'}</div>
                    <div class="my-apt-label">מחיר קנייה שלך</div>
                </div>
                <div class="my-apt-stat">
                    <div class="my-apt-val">{diff_str if diff_str else '—'}</div>
                    <div class="my-apt-label">הפרש מהשוק</div>
                </div>
            </div>
        </div>"""
    else:
        my_apt_html = """
        <div class="my-apt-panel">
            <div class="my-apt-title">🏠 הנכס שלך</div>
            <p style="color:rgba(255,255,255,0.7);margin:0">
                הגדר את הנכס שלך באמצעות: <code>python scripts/setup_my_apartment.py</code>
            </p>
        </div>"""

    # ── Chart data ────────────────────────────────────────────────────────────
    chart_labels_3 = [r["snapshot_date"] for r in reversed(trend_3)]
    chart_data_3 = [r.get("median_price") or r.get("avg_price") for r in reversed(trend_3)]
    chart_labels_4 = [r["snapshot_date"] for r in reversed(trend_4)]
    chart_data_4 = [r.get("median_price") or r.get("avg_price") for r in reversed(trend_4)]

    has_charts = bool(chart_data_3 or chart_data_4)

    # ── AI report ─────────────────────────────────────────────────────────────
    ai_report_html = ""
    if ai_report:
        report_body = markdown_to_html(ai_report.get("report_md", ""))
        ai_report_html = f"""
        <div class="ai-report-panel">
            <div class="ai-report-title">🤖 ניתוח שוק שבועי — {ai_report.get('report_date', '')}</div>
            <div class="ai-report-body">{report_body}</div>
        </div>"""

    # ── Listings JSON for JS ──────────────────────────────────────────────────
    js_listings = []
    for l in listings:
        js_listings.append({
            "URL": l.get("url", ""),
            "Price": l.get("price", 0),
            "Rooms": l.get("rooms", ""),
            "Street": l.get("street", ""),
            "Neighborhood": l.get("neighborhood", ""),
            "City": l.get("city", ""),
            "Floor": l.get("floor", ""),
            "SqM": l.get("sqm", ""),
            "Phone": l.get("phone", ""),
            "Type": "Private" if l.get("is_private") else "Agency",
            "Image": l.get("cover_image", ""),
            "Source": l.get("source", "yad2"),
            "FirstSeen": l.get("first_seen_at", "")[:10] if l.get("first_seen_at") else "",
        })

    # ── Filter options ────────────────────────────────────────────────────────
    rooms_vals = sorted(set(str(l.get("rooms")) for l in listings if l.get("rooms")))
    neighborhoods_vals = sorted(set(l.get("neighborhood", "") for l in listings if l.get("neighborhood") and l.get("neighborhood") != "לא ידוע"))
    cities_vals = sorted(set(l.get("city", "") for l in listings if l.get("city")))

    def make_checkboxes(vals, css_class, prefix):
        return "\n".join(
            f'<div class="filter-option"><input type="checkbox" id="{prefix}_{i}" value="{v}" class="{css_class}"><label for="{prefix}_{i}">{v}</label></div>'
            for i, v in enumerate(vals)
        )

    rooms_checkboxes = make_checkboxes(rooms_vals, "rooms-cb", "r")
    neigh_checkboxes = make_checkboxes(neighborhoods_vals, "neigh-cb", "n")
    city_checkboxes = make_checkboxes(cities_vals, "city-cb", "c")

    # ── HTML ─────────────────────────────────────────────────────────────────
    charts_section = ""
    if has_charts:
        charts_section = f"""
        <div class="charts-row">
            <div class="chart-box">
                <div class="chart-title">📈 מגמת מחיר — 3-3.5 חדרים (חציון)</div>
                <canvas id="chart3"></canvas>
            </div>
            <div class="chart-box">
                <div class="chart-title">📈 מגמת מחיר — 4-4.5 חדרים (חציון)</div>
                <canvas id="chart4"></canvas>
            </div>
        </div>"""

    chart_js = ""
    if has_charts:
        chart_js = f"""
        const ctx3 = document.getElementById('chart3');
        const ctx4 = document.getElementById('chart4');
        const chartDefaults = {{
            type: 'line',
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    y: {{
                        ticks: {{
                            callback: v => '₪' + Number(v).toLocaleString()
                        }}
                    }}
                }}
            }}
        }};
        if (ctx3) {{
            new Chart(ctx3, {{
                ...chartDefaults,
                data: {{
                    labels: {json.dumps(chart_labels_3)},
                    datasets: [{{ label: 'חציון', data: {json.dumps(chart_data_3)},
                        borderColor: '#667eea', backgroundColor: 'rgba(102,126,234,0.1)',
                        tension: 0.3, fill: true }}]
                }}
            }});
        }}
        if (ctx4) {{
            new Chart(ctx4, {{
                ...chartDefaults,
                data: {{
                    labels: {json.dumps(chart_labels_4)},
                    datasets: [{{ label: 'חציון', data: {json.dumps(chart_data_4)},
                        borderColor: '#764ba2', backgroundColor: 'rgba(118,75,162,0.1)',
                        tension: 0.3, fill: true }}]
                }}
            }});
        }}"""

    source_labels = {"yad2": "יד2", "madlan": "מדלן", "onmap": "OnMap"}

    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ניטור שוק נדל"ן — ראשון לציון</title>
    {"<script src='https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js'></script>" if has_charts else ""}
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: white; text-align: center; margin-bottom: 10px; font-size: 2.5em; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }}
        .info {{ color: rgba(255,255,255,0.9); text-align: center; margin-bottom: 20px; font-size: 1.1em; }}

        /* My apartment panel */
        .my-apt-panel {{
            background: rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.3);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            color: white;
        }}
        .my-apt-title {{ font-size: 1.2em; font-weight: 700; margin-bottom: 14px; }}
        .my-apt-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
        .my-apt-stat {{ background: rgba(255,255,255,0.1); border-radius: 8px; padding: 12px; text-align: center; }}
        .my-apt-val {{ font-size: 1.4em; font-weight: 700; }}
        .my-apt-label {{ font-size: 0.85em; opacity: 0.8; margin-top: 4px; }}

        /* Charts */
        .charts-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .chart-box {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }}
        .chart-title {{ font-size: 1em; font-weight: 600; color: #333; margin-bottom: 12px; }}

        /* AI report */
        .ai-report-panel {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }}
        .ai-report-title {{ font-size: 1.2em; font-weight: 700; color: #333; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #667eea; }}
        .ai-report-body {{ color: #444; line-height: 1.7; font-size: 0.95em; }}
        .ai-report-body h2, .ai-report-body h3 {{ color: #333; margin: 14px 0 6px; }}
        .ai-report-body p {{ margin-bottom: 8px; }}
        .ai-report-body li {{ margin-right: 20px; margin-bottom: 4px; }}
        .ai-report-body em {{ color: #888; font-size: 0.9em; }}

        /* Stats bar */
        .stats {{ background: rgba(255,255,255,0.1); color: white; padding: 15px 20px; border-radius: 10px; margin-bottom: 20px; display: flex; justify-content: center; gap: 30px; flex-wrap: wrap; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 1.8em; font-weight: bold; }}
        .stat-label {{ font-size: 0.9em; opacity: 0.9; }}
        .stat-sublabel {{ font-size: 0.8em; opacity: 0.7; margin-top: 4px; }}

        /* Filters */
        .filters-section {{ background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 8px 16px rgba(0,0,0,0.1); }}
        .filters-title {{ font-size: 1.2em; font-weight: 600; color: #333; margin-bottom: 15px; }}
        .filters-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        .filter-group {{ display: flex; flex-direction: column; }}
        .filter-label {{ font-size: 0.9em; font-weight: 600; color: #555; margin-bottom: 6px; }}
        .filter-options {{ display: flex; flex-direction: column; gap: 8px; max-height: 150px; overflow-y: auto; padding: 8px; border: 1px solid #ddd; border-radius: 6px; background: #fafafa; }}
        .filter-option {{ display: flex; align-items: center; gap: 8px; }}
        .filter-option input[type="checkbox"] {{ width: 18px; height: 18px; cursor: pointer; accent-color: #667eea; }}
        .filter-option label {{ cursor: pointer; font-size: 0.95em; color: #333; flex: 1; }}
        .filter-select {{ padding: 10px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 0.95em; }}
        .filter-buttons {{ display: flex; gap: 10px; margin-top: 10px; grid-column: 1 / -1; }}
        .btn-filter {{ flex: 1; padding: 10px 15px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.95em; }}
        .btn-apply {{ background-color: #2ecc71; color: white; }}
        .btn-apply:hover {{ background-color: #27ae60; }}
        .btn-clear {{ background-color: #e74c3c; color: white; }}
        .btn-clear:hover {{ background-color: #c0392b; }}

        .results-info {{ color: white; text-align: center; margin-bottom: 15px; font-size: 1.05em; }}

        /* Listing cards */
        .listings-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; }}
        .listing-card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 16px rgba(0,0,0,0.1); transition: transform 0.3s ease, box-shadow 0.3s ease; display: flex; flex-direction: column; }}
        .listing-card:hover {{ transform: translateY(-5px); box-shadow: 0 12px 24px rgba(0,0,0,0.15); }}
        .image-container {{ position: relative; width: 100%; height: 240px; background: #f0f0f0; overflow: hidden; }}
        .listing-image {{ width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s ease; }}
        .listing-card:hover .listing-image {{ transform: scale(1.05); }}
        .no-image {{ display: flex; align-items: center; justify-content: center; height: 100%; color: #999; font-size: 0.9em; }}
        .listing-content {{ padding: 16px; flex: 1; display: flex; flex-direction: column; }}
        .price {{ font-size: 1.6em; font-weight: bold; color: #2ecc71; margin-bottom: 10px; }}
        .details {{ font-size: 0.95em; color: #333; margin-bottom: 12px; line-height: 1.6; }}
        .detail-row {{ display: flex; justify-content: space-between; margin-bottom: 6px; }}
        .detail-label {{ font-weight: 600; color: #555; }}
        .detail-value {{ color: #777; text-align: right; }}
        .footer {{ display: flex; gap: 8px; margin-top: auto; padding-top: 12px; border-top: 1px solid #eee; }}
        .btn {{ flex: 1; padding: 10px; text-align: center; text-decoration: none; border-radius: 6px; font-size: 0.9em; font-weight: 600; transition: background-color 0.2s ease; display: inline-block; }}
        .btn-link {{ background-color: #3498db; color: white; }}
        .btn-link:hover {{ background-color: #2980b9; }}
        .btn-phone {{ background-color: #e74c3c; color: white; }}
        .btn-phone:hover {{ background-color: #c0392b; }}
        .type-badge {{ display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 0.85em; font-weight: 600; margin-top: 8px; margin-bottom: 8px; }}
        .source-badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600; background: #ecf0f1; color: #7f8c8d; margin-right: 6px; }}
        .type-private {{ background-color: #f39c12; color: white; }}
        .type-agency {{ background-color: #9b59b6; color: white; }}
        .no-results {{ background: white; padding: 40px; border-radius: 12px; text-align: center; color: #666; font-size: 1.1em; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 ניטור שוק נדל"ן</h1>
        <div class="info">עדכון אחרון: {now_str} | ראשון לציון</div>

        {my_apt_html}

        {charts_section}

        {ai_report_html}

        <div class="stats">
            <div class="stat">
                <div class="stat-value">{len(listings)}</div>
                <div class="stat-label">סה"כ מודעות פעילות</div>
            </div>
            <div class="stat">
                <div class="stat-value">{fmt(avg_3)}</div>
                <div class="stat-label">ממוצע 3-3.5 חדרים</div>
                <div class="stat-sublabel">({len(rooms_3)} מודעות)</div>
            </div>
            <div class="stat">
                <div class="stat-value">{fmt(avg_4)}</div>
                <div class="stat-label">ממוצע 4-4.5 חדרים</div>
                <div class="stat-sublabel">({len(rooms_4)} מודעות)</div>
            </div>
        </div>

        <div class="filters-section">
            <div class="filters-title">🔍 סינונים ומיון</div>
            <div class="filters-grid">
                <div class="filter-group">
                    <label class="filter-label">מספר חדרים</label>
                    <div class="filter-options">{rooms_checkboxes}</div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">שכונה</label>
                    <div class="filter-options">{neigh_checkboxes}</div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">עיר</label>
                    <div class="filter-options">{city_checkboxes}</div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">סוג</label>
                    <div class="filter-options">
                        <div class="filter-option"><input type="checkbox" id="type_0" value="Private" class="type-cb"><label for="type_0">פרטי</label></div>
                        <div class="filter-option"><input type="checkbox" id="type_1" value="Agency" class="type-cb"><label for="type_1">תיווך</label></div>
                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">מקור</label>
                    <div class="filter-options">
                        <div class="filter-option"><input type="checkbox" id="src_0" value="yad2" class="src-cb"><label for="src_0">יד2</label></div>
                        <div class="filter-option"><input type="checkbox" id="src_1" value="madlan" class="src-cb"><label for="src_1">מדלן</label></div>
                        <div class="filter-option"><input type="checkbox" id="src_2" value="onmap" class="src-cb"><label for="src_2">OnMap</label></div>
                    </div>
                </div>
                <div class="filter-group">
                    <label class="filter-label">מיון לפי מחיר</label>
                    <select class="filter-select" id="priceSort">
                        <option value="">ללא מיון</option>
                        <option value="asc" selected>זול ביותר</option>
                        <option value="desc">יקר ביותר</option>
                    </select>
                </div>
                <div class="filter-buttons">
                    <button class="btn-filter btn-apply" onclick="applyFilters()">החל סינונים</button>
                    <button class="btn-filter btn-clear" onclick="clearFilters()">נקה הכל</button>
                </div>
            </div>
        </div>

        <div class="results-info" id="resultsInfo"></div>
        <div class="listings-grid" id="listingsGrid"></div>
    </div>

    <script>
        const sourceLabels = {json.dumps(source_labels, ensure_ascii=False)};
        const allListings = {json.dumps(js_listings, ensure_ascii=False)};

        function getChecked(cls) {{
            return Array.from(document.querySelectorAll('.' + cls + ':checked')).map(cb => cb.value);
        }}

        function getFilteredListings() {{
            const rooms = getChecked('rooms-cb').map(parseFloat);
            const neighs = getChecked('neigh-cb');
            const cities = getChecked('city-cb');
            const types = getChecked('type-cb');
            const srcs = getChecked('src-cb');
            const sort = document.getElementById('priceSort').value;

            let filtered = allListings.filter(l => {{
                if (rooms.length && !rooms.includes(parseFloat(l.Rooms))) return false;
                if (neighs.length && !neighs.includes(l.Neighborhood)) return false;
                if (cities.length && !cities.includes(l.City)) return false;
                if (types.length && !types.includes(l.Type)) return false;
                if (srcs.length && !srcs.includes(l.Source)) return false;
                return true;
            }});

            if (sort === 'asc') filtered.sort((a,b) => a.Price - b.Price);
            else if (sort === 'desc') filtered.sort((a,b) => b.Price - a.Price);
            return filtered;
        }}

        function renderListings(listings) {{
            const grid = document.getElementById('listingsGrid');
            const info = document.getElementById('resultsInfo');
            if (!listings.length) {{
                grid.innerHTML = '<div class="no-results" style="grid-column:1/-1">אין נכסים התואמים את הסינונים שלך</div>';
                info.textContent = 'מוצגים 0 נכסים';
                return;
            }}
            info.textContent = `מוצגים ${{listings.length}} מתוך ${{allListings.length}} נכסים`;
            grid.innerHTML = listings.map(l => {{
                const price = Number(l.Price).toLocaleString();
                const imgHtml = l.Image
                    ? `<img src="${{l.Image}}" alt="" class="listing-image" loading="lazy">`
                    : '<div class="no-image">אין תמונה</div>';
                const typeClass = l.Type === 'Private' ? 'type-private' : 'type-agency';
                const typeText = l.Type === 'Private' ? 'פרטי' : 'תיווך';
                const srcLabel = sourceLabels[l.Source] || l.Source;
                const phone = l.Phone || '';
                const phoneBtn = phone
                    ? `<a href="tel:${{phone}}" class="btn btn-phone">📞 ${{phone}}</a>`
                    : `<span class="btn btn-phone" style="opacity:0.5">אין טלפון</span>`;
                return `
                    <div class="listing-card">
                        <div class="image-container">${{imgHtml}}</div>
                        <div class="listing-content">
                            <div class="price">₪ ${{price}}</div>
                            <div class="details">
                                <div class="detail-row"><span class="detail-label">חדרים:</span><span class="detail-value">${{l.Rooms}}</span></div>
                                <div class="detail-row"><span class="detail-label">מ"ר:</span><span class="detail-value">${{l.SqM}}</span></div>
                                <div class="detail-row"><span class="detail-label">קומה:</span><span class="detail-value">${{l.Floor}}</span></div>
                                <div class="detail-row"><span class="detail-label">רחוב:</span><span class="detail-value">${{l.Street}}</span></div>
                                <div class="detail-row"><span class="detail-label">שכונה:</span><span class="detail-value">${{l.Neighborhood}}</span></div>
                            </div>
                            <div>
                                <span class="source-badge">${{srcLabel}}</span>
                                <span class="type-badge ${{typeClass}}">${{typeText}}</span>
                            </div>
                            <div class="footer">
                                <a href="${{l.URL}}" target="_blank" class="btn btn-link">צפה</a>
                                ${{phoneBtn}}
                            </div>
                        </div>
                    </div>`;
            }}).join('');
        }}

        function applyFilters() {{ renderListings(getFilteredListings()); }}
        function clearFilters() {{
            document.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
            document.getElementById('priceSort').value = 'asc';
            applyFilters();
        }}

        {chart_js}

        // Initial render
        applyFilters();
    </script>
</body>
</html>"""

    with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {HTML_OUTPUT} with {len(listings)} listings")


def _generate_csv(listings: list):
    """Export active listings to listings.csv."""
    rows = []
    for l in listings:
        rows.append({
            "URL": l.get("url", ""),
            "Price (₪)": l.get("price", ""),
            "Rooms": l.get("rooms", ""),
            "Street": l.get("street", ""),
            "Neighborhood": l.get("neighborhood", ""),
            "City": l.get("city", ""),
            "Floor": l.get("floor", ""),
            "SqM": l.get("sqm", ""),
            "Phone": l.get("phone", ""),
            "Type": "Private" if l.get("is_private") else "Agency",
            "Source": l.get("source", ""),
            "Image URL": l.get("cover_image", ""),
        })
    rows.sort(key=lambda x: x.get("Price (₪)") or 0, reverse=True)

    fieldnames = ["URL", "Price (₪)", "Rooms", "Street", "Neighborhood", "City", "Floor", "SqM", "Phone", "Type", "Source", "Image URL"]
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {CSV_OUTPUT} with {len(rows)} rows")


if __name__ == "__main__":
    generate_dashboard()
