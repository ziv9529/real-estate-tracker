import requests
import datetime
import time
import json
import os

from dotenv import load_dotenv

load_dotenv()

# === Telegram Credentials ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")

TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# === API URLs ===
API_URL = "https://gw.yad2.co.il/realestate-feed/forsale/feed?city=8300&property=apartment&maxPrice=2200000&minRooms=3&maxRooms=3.5&minSquaremeter=70&minFloor=2&priceOnly=1&sort=1&page=1"
CUSTOMER_URL = "https://gw.yad2.co.il/realestate-item/{}/customer"

# === Seen Ads ===
SEEN_FILE = "seen.json"
seen = {}

def send_telegram(text: str):
    """
    Sends a plain-text message to Telegram via Bot API sendMessage.
    Docs: https://core.telegram.org/bots/api#sendmessage
    """
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        }
        r = requests.post(TELEGRAM_SEND_URL, json=payload, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print("❌ שגיאה בשליחת טלגרם:", e)

# === Load or initialize seen listings with full data ===
def load_or_initialize_seen():
    global seen
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = json.load(f)
        print(f"📂 נטענו {len(seen)} מודעות מ-{SEEN_FILE}")
    else:
        print("🛑 ריצה ראשונה: שומר את כל המודעות הקיימות בלי לשלוח...")
        res = requests.get(API_URL, timeout=20)
        data = res.json()
        listings = data.get("data", {}).get("markers", [])
        for item in listings:
            token = item.get("token")
            if token:
                url = f"https://www.yad2.co.il/item/{token}"
                seen[url] = extract_listing_data(item)
        save_seen()
        print(f"💾 נשמרו {len(seen)} מודעות קיימות.")

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)

def get_contact_phone(token):
    try:
        res = requests.get(CUSTOMER_URL.format(token), timeout=20)
        data = res.json()
        return data.get("data", {}).get("brokerPhone") or data.get("data", {}).get("phone")
    except Exception as e:
        print("⚠️ שגיאה בשליפת טלפון:", e)
        return None

def extract_listing_data(item):
    token = item.get("token")
    return {
        "price": item.get("price", 0),
        "rooms": item.get("additionalDetails", {}).get("roomsCount"),
        "street": item.get("address", {}).get("street", {}).get("text", "לא ידוע"),
        "sqm": item.get("additionalDetails", {}).get("squareMeter", 0),
        "phone": get_contact_phone(token),
    }

def is_possible_duplicate(new_item_data):
    for url, old in seen.items():
        if (
            old.get("street") == new_item_data.get("street")
            and old.get("rooms") == new_item_data.get("rooms")
            and abs(old.get("sqm", 0) - new_item_data.get("sqm", 0)) <= 3
            and old.get("price") != new_item_data.get("price")
            and old.get("phone")
            and new_item_data.get("phone")
            and old.get("phone") == new_item_data.get("phone")
        ):
            return url, old
    return None, None

def check_yad2_json():
    try:
        print(f"[{datetime.datetime.now()}] 📡 בודק מודעות חדשות או שינויי מחיר...")
        res = requests.get(API_URL, timeout=20)
        data = res.json()
        listings = data.get("data", {}).get("markers", [])
        changes = 0

        for item in listings:
            token = item.get("token")
            if not token:
                continue

            url = f"https://www.yad2.co.il/item/{token}"
            new_data = extract_listing_data(item)

            price = new_data["price"]
            rooms = new_data["rooms"]
            street = new_data["street"]
            sqm = new_data["sqm"]
            phone = new_data["phone"]

            if url in seen:
                if seen[url]["price"] != price:
                    old_price = seen[url]["price"]
                    seen[url] = new_data
                    save_seen()

                    message = (
                        f"💸 שינוי במחיר מודעה קיימת:\n"
                        f"רחוב: {street}\nחדרים: {rooms}\n"
                        f"מחיר קודם: {old_price} ₪\n"
                        f"מחיר חדש: {price} ₪\n{url}"
                    )
                    send_telegram(message)
                    changes += 1
            else:
                old_url, old_data = is_possible_duplicate(new_data)
                if old_url:
                    message = (
                        f"🔁 יתכן שזו אותה דירה שפורסמה מחדש ע\"י אותו מפרסם(מניאק):\n"
                        f"רחוב: {street}\nחדרים: {rooms}\nמ\"ר: {sqm}\n"
                        f"מחיר קודם: {old_data['price']} ₪\n"
                        f"מחיר חדש: {price} ₪\n"
                        f"טלפון: {phone}\n"
                        f"קישור חדש: {url}\n"
                        f"קישור קודם: {old_url}"
                    )
                    send_telegram(message)
                else:
                    message = (
                        f"🔔 דירה חדשה ביד2!\nרחוב: {street}\nחדרים: {rooms}\n"
                        f"מחיר: {price} ₪\nטלפון: {phone}\n{url}"
                    )
                    send_telegram(message)

                seen[url] = new_data
                save_seen()
                changes += 1

        print(f"✅ נמצאו {changes} שינויים. סה״כ מודעות שמורות: {len(seen)}")

    except Exception as e:
        print("❌ שגיאה בבדיקה:", e)

# === Main loop ===
load_or_initialize_seen()
while True:
    try:
        check_yad2_json()
    except Exception as e:
        print("🔁 שגיאה כללית בלולאה:", e)
    time.sleep(120)
