# Yad2 Apartment Monitor - Automated Telegram Alerts 🏠

Monitors Yad2 real estate listings for Rishon Lezion apartments and sends Telegram alerts for new listings and price changes. Runs automatically every 2 minutes via GitHub Actions.

## 🚀 Quick Start

### Option 1: GitHub Actions (Recommended - No Local Setup Needed)

See [GITHUB_ACTIONS_SETUP.md](GITHUB_ACTIONS_SETUP.md) for complete setup guide.

### Option 2: Local Development

```bash
# Clone and setup
git clone <your-repo>
cd alerts
python -m venv .venv
source .venv/Scripts/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Create .env file with credentials
echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env
echo "TELEGRAM_CHAT_ID=your_chat_id_here" >> .env

# Run scraper
python scripts/scraper_with_alerts.py
```

## 📁 Project Structure

```
alerts/
├── scripts/                           # Main application scripts
│   ├── scraper_with_alerts.py        # Main scraper & alerting logic
│   └── discover_neighborhoods.py     # Neighborhood discovery tool
├── utils/                             # Data files and utilities
│   ├── discovered_neighborhoods.json  # Neighborhood mapping
│   ├── neighborhoods_dict.py         # Python-friendly format
│   └── neighborhoods_summary.txt     # Human-readable reference
├── .github/workflows/
│   └── scraper.yml                   # GitHub Actions automation
├── archive/                          # Old/reference files
├── seen.json                         # Tracked listings (persisted in git)
├── .env                              # Credentials (NOT in git)
├── requirements.txt                  # Python dependencies
└── README.md                         # This file
```

## ⚙️ Configuration

Edit `scripts/scraper_with_alerts.py`:

**Search Criteria:**

- **Search 1:** 3-3.5 rooms, 70+ sqm, max ₪2.35M
- **Search 2:** 4-4.5 rooms, 80+ sqm, max ₪2.7M

**Neighborhoods:**

- הרקפות (Harkarot)
- נרקיסים (Narcissim)
- נוריות (Noriyot)
- נחלת יהודה (Nahalat Yehudah)

## 🔔 Alert Types

1. **New Listing** 🔔 - Apartment matches search criteria
2. **Price Change** 💸 - Same apartment's price changed
3. **Possible Repost** 🔁 - Same property reposted by same seller

## 📊 How It Works

1. **Fetches** listings from Yad2 API (every 2 minutes)
2. **Filters** by neighborhood names and search criteria
3. **Compares** against `seen.json` to detect changes
4. **Sends Telegram alerts** for new listings and price changes
5. **Persists state** in `seen.json` (committed to git)

## 🛠️ Utilities

### Discover Neighborhoods

Find all neighborhoods for a specific city:

```bash
python scripts/discover_neighborhoods.py
```

Updates `utils/discovered_neighborhoods.json` with neighborhood IDs.

## 📝 Files Explained

- **seen.json** - Tracks all listings found (URL → details)

  - ✅ Kept in git so GitHub Actions maintains state
  - ❌ Remove from gitignore for multi-machine sync

- **.env** - Telegram credentials

  - ⚠️ Never commit to git
  - Store secrets in GitHub Actions instead

- **scraper_with_alerts.py** - Main application logic
  - Fetches and parses listings
  - Detects price changes
  - Sends Telegram alerts

## 🚀 Deployment

### GitHub Actions (Free, Recommended)

- Runs every 2 minutes automatically
- No local machine needed
- Free tier: 2,000 min/month (well within limit)
- See [GITHUB_ACTIONS_SETUP.md](GITHUB_ACTIONS_SETUP.md)

### Local Machine

- Run continuously or via task scheduler
- Requires machine to stay on

## 📱 Telegram Setup

1. Create bot: Message [@BotFather](https://t.me/botfather)
2. Get token and chat ID
3. Add to `.env` or GitHub Secrets

## 🔐 Security

- `.env` is in `.gitignore` - never committed
- Use GitHub Secrets for deployed version
- Phone numbers are fetched from Yad2 API

## 📈 Performance

- Async requests (25 concurrent max)
- Caches pip dependencies on GitHub
- Typical run: <30 seconds for first page

## 💡 Tips

- Check logs in GitHub Actions → Workflow runs
- Manual trigger: Actions tab → "Run workflow"
- Monitor Telegram for alerts every 2 minutes
- Edit search criteria in `scripts/scraper_with_alerts.py`

---

**Status:** ✅ Production Ready | 🚀 Auto-deployed via GitHub Actions | 📨 Telegram alerts enabled
