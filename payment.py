import aiohttp
import logging
from config import SENDHOLDERS_API_KEY, SENDHOLDERS_WEBHOOK_URL, VIP_PRICE, VIP_DURATION_DAYS
from database import add_payment, update_payment_status, set_vip

async def create_payment_link(user_id, amount=VIP_PRICE, description="VIP-подписка на месяц"):
    """Создает ссылку для оплаты через @sendholders"""
    # Это гипотетический эндпоинт — замените на реальный URL от @sendholders
    url = "https://api.sendholders.com/v1/invoice"
    headers = {
        "Authorization": f"Bearer {SENDHOLDERS_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "amount": amount,
        "currency": "RUB",
        "description": description,
        "webhook_url": SENDHOLDERS_WEBHOOK_URL,
        "metadata": {
            "user_id": user_id,
            "type": "vip_subscription"
        }
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    payment_id = data.get("payment_id")
                    payment_link = data.get("payment_link")
                    await add_payment(user_id, amount, payment_id, "pending")
                    return payment_link
                else:
                    logging.error(f"Ошибка @sendholders: {resp.status} {await resp.text()}")
                    return None
        except Exception as e:
            logging.error(f"Исключение при создании платежа: {e}")
            return None

async def handle_webhook(request_data):
    """Обработка вебхука от @sendholders (вызывается из веб-сервера)"""
    payment_id = request_data.get("payment_id")
    status = request_data.get("status")
    metadata = request_data.get("metadata", {})
    user_id = metadata.get("user_id")
    if not payment_id or not status:
        return False
    if status == "success":
        await update_payment_status(payment_id, "success")
        if user_id:
            await set_vip(int(user_id), VIP_DURATION_DAYS)
            logging.info(f"VIP активирован для {user_id} через оплату")
        return True
    else:
        await update_payment_status(payment_id, status)
        return True
