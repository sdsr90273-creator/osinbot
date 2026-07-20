import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(','))) if os.getenv("ADMIN_IDS") else []
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = "https://t.me/+GgrPnutacI82OTNi"

SENDHOLDERS_API_KEY = os.getenv("SENDHOLDERS_API_KEY")
SENDHOLDERS_WEBHOOK_URL = os.getenv("SENDHOLDERS_WEBHOOK_URL")

FREE_DAILY_LIMIT = 5
VIP_DAILY_LIMIT = 15
VIP_PRICE = 500
VIP_DURATION_DAYS = 30

DB_NAME = "osint_bot.db"
