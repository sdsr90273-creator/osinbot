import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db
from handlers import router as main_router
from admin_handlers import router as admin_router
from aiohttp import web
from payment import handle_webhook

# Инициализация БД при запуске
async def on_startup(bot: Bot):
    await init_db()
    logging.info("База данных инициализирована")

# Обработчик вебхука от @sendholders
async def webhook_handler(request):
    try:
        data = await request.json()
        await handle_webhook(data)
        return web.Response(text="OK")
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return web.Response(text="ERROR", status=500)

def start_webhook_server():
    app = web.Application()
    app.router.add_post('/webhook', webhook_handler)
    return app

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(main_router)
    dp.include_router(admin_router)

    # Запускаем веб-сервер для вебхуков на порту 8080
    web_app = start_webhook_server()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logging.info("Вебхук-сервер запущен на порту 8080")

    # Запускаем бота в режиме long polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, on_startup=on_startup)

if __name__ == "__main__":
    asyncio.run(main())
