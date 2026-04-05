---
name: Project Transformation — Apartment Finder → Market Monitor
description: Major architectural overhaul completed; system now monitors real estate market for apartment owner rather than searching for apartments
type: project
---

The repo was transformed from a real-time apartment-finder (every 20 min scraper → Telegram alerts) into a comprehensive market monitoring platform.

**Why:** User purchased a 3-room apartment in Rishon Lezion and now monitors market value of their current apartment + tracks 4-4.5 room upgrade targets.

**New architecture:**
- `database.db` (SQLite, committed to git) replaced `seen.json` + `phone_cache.json`
- 4 GitHub Actions workflows replace the single every-20-min workflow:
  - `nightly_scraper.yml` — 23:00 IL, scrapes Yad2 + Madlan + OnMap
  - `morning_report.yml` — 07:30 IL daily, sends structured Telegram brief
  - `weekly_analysis.yml` — Sunday 07:00 IL, Claude AI market analysis
  - `monthly_govdata.yml` — 1st of month, nadlan.gov.il transaction data
- `scraper.yml` (old) — disabled (no schedule triggers), kept for reference

**Key new scripts in `scripts/`:**
- `db_utils.py` — all SQLite operations
- `daily_report.py` — morning Telegram brief
- `ai_analysis.py` — Claude API weekly analysis (uses `claude-haiku-4-5-20251001`)
- `generate_dashboard.py` — enhanced HTML with Chart.js price trends + AI report panel
- `madlan_scraper.py` — Madlan.co.il scraper (graceful fail)
- `onmap_scraper.py` — OnMap.co.il scraper (graceful fail)
- `govdata_fetcher.py` — nadlan.gov.il actual sold prices (monthly)
- `setup_my_apartment.py` — one-time CLI to configure user's apartment
- `migrate_history.py` — one-time migration of git history → price_history table

**One-time setup steps still needed:**
1. Run `python scripts/migrate_history.py` locally to populate price history from git commits
2. Run `python scripts/setup_my_apartment.py` to configure the my_apartment table
3. Add `ANTHROPIC_API_KEY` to GitHub Secrets
4. Commit the initial `database.db` to git

**How to apply:** When working on this repo, assume SQLite (`database.db`) is the source of truth, not `seen.json`. The `seen.json` file is legacy and no longer written to by any script.
