import os
import asyncio
import logging
import time
import random
import string
from datetime import datetime

# ========== AIOGRAM И ВСПОМОГАТЕЛЬНЫЕ БИБЛИОТЕКИ ==========
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
import aiohttp
from aiohttp import web

# ========== КОНФИГУРАЦИЯ (можно заменить прямо здесь) ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН")  # если не задано в окружении, впишите сюда
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "8457792268").split(',')))  # ваш ID
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1001234567890")  # замените на реальный ID канала
CHANNEL_LINK = "https://t.me/+GgrPnutacI82OTNi"

# Настройки @sendholders (если не используете — оставьте пустыми)
SENDHOLDERS_API_KEY = os.getenv("SENDHOLDERS_API_KEY", "")
SENDHOLDERS_WEBHOOK_URL = os.getenv("SENDHOLDERS_WEBHOOK_URL", "")

FREE_DAILY_LIMIT = 5
VIP_DAILY_LIMIT = 15
VIP_PRICE = 500
VIP_DURATION_DAYS = 30
DB_NAME = "osint_bot.db"

# ========== РАБОТА С БАЗОЙ ДАННЫХ (SQLite) ==========
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                daily_requests INTEGER DEFAULT 0,
                last_request_date TEXT DEFAULT CURRENT_DATE,
                vip_until INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                duration_days INTEGER,
                created_by INTEGER,
                used_by INTEGER DEFAULT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                used_at INTEGER DEFAULT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                payment_id TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        await db.commit()

# ---- Пользователи ----
async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            return await cursor.fetchone()

async def create_or_update_user(user_id, username, first_name):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        ''', (user_id, username, first_name))
        await db.commit()

async def get_daily_requests(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            'SELECT daily_requests, last_request_date FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0, None
            return row[0], row[1]

async def increment_daily_requests(user_id):
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            UPDATE users
            SET daily_requests = CASE
                WHEN last_request_date != ? THEN 1
                ELSE daily_requests + 1
            END,
            last_request_date = ?
            WHERE user_id = ?
        ''', (today, today, user_id))
        await db.commit()

async def set_vip(user_id, duration_days):
    until = int(time.time()) + duration_days * 86400
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET vip_until = ? WHERE user_id = ?', (until, user_id))
        await db.commit()

async def is_vip(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT vip_until FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            return row[0] > int(time.time())

async def get_vip_until(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT vip_until FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

# ---- Промокоды ----
async def create_promo(code, duration_days, created_by):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                'INSERT INTO promocodes (code, duration_days, created_by) VALUES (?, ?, ?)',
                (code, duration_days, created_by)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def get_promo(code):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT * FROM promocodes WHERE code = ?', (code,)) as cursor:
            return await cursor.fetchone()

async def use_promo(code, user_id):
    promo = await get_promo(code)
    if not promo or promo[3] is not None:
        return False
    duration = promo[1]
    await set_vip(user_id, duration)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'UPDATE promocodes SET used_by = ?, used_at = strftime("%s", "now") WHERE code = ?',
            (user_id, code)
        )
        await db.commit()
    return True

async def list_promos():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT code, duration_days, used_by, used_at FROM promocodes ORDER BY created_at DESC') as cursor:
            return await cursor.fetchall()

async def delete_promo(code):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM promocodes WHERE code = ?', (code,))
        await db.commit()

# ---- Платежи ----
async def add_payment(user_id, amount, payment_id, status='pending'):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'INSERT INTO payments (user_id, amount, payment_id, status) VALUES (?, ?, ?, ?)',
            (user_id, amount, payment_id, status)
        )
        await db.commit()

async def update_payment_status(payment_id, status):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE payments SET status = ? WHERE payment_id = ?', (status, payment_id))
        await db.commit()

async def get_payment(payment_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,)) as cursor:
            return await cursor.fetchone()

# ---- Статистика ----
async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        total_users = await db.execute('SELECT COUNT(*) FROM users')
        total_users = (await total_users.fetchone())[0]
        active_vip = await db.execute('SELECT COUNT(*) FROM users WHERE vip_until > strftime("%s", "now")')
        active_vip = (await active_vip.fetchone())[0]
        total_payments = await db.execute('SELECT COUNT(*) FROM payments WHERE status="success"')
        total_payments = (await total_payments.fetchone())[0]
        total_revenue = await db.execute('SELECT SUM(amount) FROM payments WHERE status="success"')
        total_revenue = (await total_revenue.fetchone())[0] or 0
        return {
            'total_users': total_users,
            'active_vip': active_vip,
            'total_payments': total_payments,
            'total_revenue': total_revenue
        }

# ========== API-ФУНКЦИИ ДЛЯ ПОИСКА (заглушки) ==========
async def search_vk_by_name(first_name, last_name, limit=5):
    await asyncio.sleep(1)
    return [
        {"id": 1, "name": f"{first_name} {last_name}", "photo": "url", "profile_url": "https://vk.com/id1"},
        {"id": 2, "name": f"{first_name} {last_name} (двойник)", "photo": "url", "profile_url": "https://vk.com/id2"}
    ]

async def search_google_dorks(query):
    await asyncio.sleep(1)
    return [
        {"title": "Страница с данными", "snippet": "Найдены контакты...", "link": "https://example.com/result1"},
        {"title": "Утечка", "snippet": "База данных с email...", "link": "https://example.com/result2"}
    ]

async def search_leaked_data(query_type, value):
    await asyncio.sleep(1)
    if query_type == 'phone':
        return [{"source": "База X", "info": f"Найден номер {value} в утечке 2022"}]
    elif query_type == 'email':
        return [{"source": "База Y", "info": f"Email {value} обнаружен в 3 утечках"}]
    elif query_type == 'telegram':
        return [{"source": "Telegram", "info": f"Юзернейм {value} найден в чатах"}]
    else:
        return [{"source": "Общая база", "info": "Данные не найдены"}]

# ========== ПЛАТЁЖНАЯ ИНТЕГРАЦИЯ (@sendholders) ==========
async def create_payment_link(user_id, amount=VIP_PRICE, description="VIP-подписка на месяц"):
    if not SENDHOLDERS_API_KEY:
        return None
    url = "https://api.sendholders.com/v1/invoice"
    headers = {"Authorization": f"Bearer {SENDHOLDERS_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "amount": amount,
        "currency": "RUB",
        "description": description,
        "webhook_url": SENDHOLDERS_WEBHOOK_URL,
        "metadata": {"user_id": user_id, "type": "vip_subscription"}
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

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class PromoState(StatesGroup):
    waiting_for_code = State()

class SearchState(StatesGroup):
    waiting_for_vk_fio = State()
    waiting_for_google_dork = State()
    waiting_for_leak_query = State()

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
router = Router()

async def check_subscription(user_id: int, bot: Bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

async def ensure_access(message: types.Message, bot: Bot) -> bool:
    user_id = message.from_user.id
    # Проверка подписки (раскомментируйте, когда настроите CHANNEL_ID)
    # if not await check_subscription(user_id, bot):
    #     await message.answer(
    #         f"⚠️ Для использования бота подпишитесь на канал:\n{CHANNEL_LINK}"
    #     )
    #     return False
    vip = await is_vip(user_id)
    limit = VIP_DAILY_LIMIT if vip else FREE_DAILY_LIMIT
    used, last_date = await get_daily_requests(user_id)
    today = datetime.now().date().isoformat()
    if last_date != today:
        used = 0
    if used >= limit:
        if vip:
            await message.answer("❌ Вы исчерпали дневной лимит (15 запросов). Попробуйте завтра.")
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Купить VIP", callback_data="buy_vip")]
            ])
            await message.answer(
                f"❌ Закончились бесплатные запросы ({FREE_DAILY_LIMIT} в день).\nКупите VIP.",
                reply_markup=keyboard
            )
        return False
    return True

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    user = message.from_user
    await create_or_update_user(user.id, user.username, user.first_name)
    # Проверка подписки (раскомментируйте при необходимости)
    # subscribed = await check_subscription(user.id, bot)
    # if not subscribed:
    #     await message.answer(f"Подпишитесь: {CHANNEL_LINK}")
    #     return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск по ВК (ФИО)", callback_data="search_vk")],
        [InlineKeyboardButton(text="🌐 Google Dorks", callback_data="search_dorks")],
        [InlineKeyboardButton(text="🕵️ Поиск в утечках", callback_data="search_leak")],
        [InlineKeyboardButton(text="💎 VIP статус", callback_data="vip_info")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")]
    ])
    vip_status = "✅ активна" if await is_vip(user.id) else "❌ не активна"
    await message.answer(
        f"Добро пожаловать, {user.first_name}!\nVIP: {vip_status}\nЛимит: {FREE_DAILY_LIMIT if not await is_vip(user.id) else VIP_DAILY_LIMIT}",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "search_vk")
async def search_vk_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_access(callback.message, bot):
        await callback.answer()
        return
    await callback.message.answer("Введите имя и фамилию через пробел:")
    await state.set_state(SearchState.waiting_for_vk_fio)
    await callback.answer()

@router.message(SearchState.waiting_for_vk_fio)
async def process_vk_search(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Введите имя и фамилию через пробел.")
        return
    first_name, last_name = parts[0], ' '.join(parts[1:])
    await message.answer("🔎 Ищем...")
    results = await search_vk_by_name(first_name, last_name)
    if results:
        text = "Результаты ВК:\n" + "\n".join(f"👤 {r['name']}\nСсылка: {r['profile_url']}" for r in results)
        await message.answer(text[:4000])
    else:
        await message.answer("Ничего не найдено.")

@router.callback_query(F.data == "search_dorks")
async def search_dorks_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_access(callback.message, bot):
        await callback.answer()
        return
    await callback.message.answer("Введите dork-запрос:")
    await state.set_state(SearchState.waiting_for_google_dork)
    await callback.answer()

@router.message(SearchState.waiting_for_google_dork)
async def process_dorks(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(message.from_user.id)
    query = message.text
    await message.answer("🔎 Ищем по Dorks...")
    results = await search_google_dorks(query)
    if results:
        text = "Результаты Dorks:\n" + "\n".join(f"📄 {r['title']}\n{r['snippet']}\n{r['link']}" for r in results)
        await message.answer(text[:4000])
    else:
        await message.answer("Ничего не найдено.")

@router.callback_query(F.data == "search_leak")
async def search_leak_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_access(callback.message, bot):
        await callback.answer()
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 По номеру телефона", callback_data="leak_phone")],
        [InlineKeyboardButton(text="📧 По email", callback_data="leak_email")],
        [InlineKeyboardButton(text="💬 По Telegram username", callback_data="leak_telegram")]
    ])
    await callback.message.answer("Выберите тип:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("leak_"))
async def leak_type_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    leak_type = callback.data.split("_")[1]
    await state.update_data(leak_type=leak_type)
    type_names = {"phone": "номер телефона", "email": "email", "telegram": "Telegram username"}
    await callback.message.answer(f"Введите {type_names.get(leak_type, 'данные')}:")
    await state.set_state(SearchState.waiting_for_leak_query)
    await callback.answer()

@router.message(SearchState.waiting_for_leak_query)
async def process_leak(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(message.from_user.id)
    data = await state.get_data()
    leak_type = data.get("leak_type", "phone")
    value = message.text.strip()
    await message.answer("🕵️ Ищем в утечках...")
    results = await search_leaked_data(leak_type, value)
    if results:
        text = "📂 Результаты:\n" + "\n".join(f"🔹 {r['source']}: {r['info']}" for r in results)
        await message.answer(text[:4000])
    else:
        await message.answer("Ничего не найдено.")

@router.callback_query(F.data == "vip_info")
async def vip_info(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    vip = await is_vip(user_id)
    until = await get_vip_until(user_id)
    if vip:
        date = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        await callback.answer(f"VIP активна до {date}\nЛимит: {VIP_DAILY_LIMIT}", show_alert=True)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить VIP", callback_data="buy_vip")]
        ])
        await callback.message.edit_text(
            "VIP не активна. Купите за {VIP_PRICE} руб. на {VIP_DURATION_DAYS} дней.",
            reply_markup=keyboard
        )
        await callback.answer()

@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    link = await create_payment_link(user_id)
    if link:
        await callback.message.edit_text(f"Оплатите по ссылке:\n{link}\nПосле оплаты статус обновится.")
    else:
        await callback.answer("Оплата временно недоступна.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "activate_promo")
async def activate_promo_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите промокод:")
    await state.set_state(PromoState.waiting_for_code)
    await callback.answer()

@router.message(PromoState.waiting_for_code)
async def process_promo(message: types.Message, state: FSMContext):
    await state.clear()
    code = message.text.strip()
    promo = await get_promo(code)
    if not promo:
        await message.answer("❌ Неверный промокод.")
        return
    if promo[3] is not None:
        await message.answer("❌ Промокод уже использован.")
        return
    success = await use_promo(code, message.from_user.id)
    if success:
        await message.answer("✅ Промокод активирован! VIP оформлена.")
    else:
        await message.answer("❌ Ошибка активации.")

# ========== АДМИН-КОМАНДЫ ==========
admin_router = Router()

@admin_router.message(Command("create_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_create_promo(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /create_promo <дни>")
        return
    try:
        days = int(args[1])
    except ValueError:
        await message.answer("Дни должны быть числом.")
        return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    success = await create_promo(code, days, message.from_user.id)
    if success:
        await message.answer(f"✅ Промокод: `{code}`\nДействует {days} дней.", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка создания.")

@admin_router.message(Command("list_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_list_promo(message: types.Message):
    promos = await list_promos()
    if not promos:
        await message.answer("Промокодов нет.")
        return
    text = "📋 Список:\n" + "\n".join(f"`{code}` – {days} дней, {'использован' if used_by else 'активен'}" for code, days, used_by, used_at in promos)
    await message.answer(text, parse_mode="Markdown")

@admin_router.message(Command("delete_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_delete_promo(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delete_promo <код>")
        return
    code = args[1]
    await delete_promo(code)
    await message.answer(f"Промокод `{code}` удалён.", parse_mode="Markdown")

@admin_router.message(Command("stats"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stats(message: types.Message):
    stats = await get_stats()
    await message.answer(
        f"📊 Статистика:\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"💎 VIP: {stats['active_vip']}\n"
        f"💰 Оплат: {stats['total_payments']}\n"
        f"💵 Выручка: {stats['total_revenue']} руб."
    )

# ========== ГЛАВНЫЙ ФАЙЛ (ЗАПУСК) ==========
async def on_startup(bot: Bot):
    await init_db()
    logging.info("База данных инициализирована")

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
    dp.include_router(router)
    dp.include_router(admin_router)

    # Запуск вебхук-сервера (для @sendholders)
    web_app = start_webhook_server()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logging.info("Вебхук-сервер запущен на порту 8080")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, on_startup=on_startup)

if __name__ == "__main__":
    asyncio.run(main())
