Python 3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)] on win32
Enter "help" below or click "Help" above for more information.
>>> import os
... from dotenv import load_dotenv
... 
... load_dotenv()
... 
... BOT_TOKEN = os.getenv("BOT_TOKEN")
... ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(',')))  # например 123456,789012
... CHANNEL_ID = os.getenv("CHANNEL_ID")  # например -1001234567890 (ID канала)
... CHANNEL_LINK = "https://t.me/+GgrPnutacI82OTNi"  # для отображения
... 
... # Настройки @sendholders (получите у бота @sendholders)
... SENDHOLDERS_API_KEY = os.getenv("SENDHOLDERS_API_KEY")
... SENDHOLDERS_WEBHOOK_URL = os.getenv("SENDHOLDERS_WEBHOOK_URL")  # https://ваш-сервер/webhook
... 
... # Параметры подписки
... FREE_DAILY_LIMIT = 5
... VIP_DAILY_LIMIT = 15
... VIP_PRICE = 500  # цена в рублях
... VIP_DURATION_DAYS = 30  # на месяц
... 
