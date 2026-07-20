from aiogram import Router, types, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
from datetime import datetime
from config import CHANNEL_ID, FREE_DAILY_LIMIT, VIP_DAILY_LIMIT, VIP_PRICE, CHANNEL_LINK
from database import (
    get_user, create_or_update_user, get_daily_requests, increment_daily_requests,
    is_vip, get_vip_until, get_promo, use_promo, set_vip
)
from payment import create_payment_link
from api_handlers import search_vk_by_name, search_google_dorks, search_leaked_data
import logging

router = Router()

# Состояния для FSM
class PromoState(StatesGroup):
    waiting_for_code = State()

class SearchState(StatesGroup):
    waiting_for_vk_fio = State()
    waiting_for_google_dork = State()
    waiting_for_leak_query = State()
    # waiting_for_leak_type уже не нужна отдельно

# ---- Проверка подписки на канал ----
async def check_subscription(user_id: int, bot: Bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# ---- Проверка доступа (подписка + лимит) ----
async def ensure_access(message: types.Message, bot: Bot) -> bool:
    user_id = message.from_user.id
    # Проверка подписки на канал
    if not await check_subscription(user_id, bot):
        await message.answer(
            f"⚠️ Для использования бота необходимо подписаться на наш канал:\n{CHANNEL_LINK}\n"
            "После подписки нажмите /start заново."
        )
        return False
    # Проверка лимита
    vip = await is_vip(user_id)
    limit = VIP_DAILY_LIMIT if vip else FREE_DAILY_LIMIT
    used, last_date = await get_daily_requests(user_id)
    today = datetime.now().date().isoformat()
    if last_date != today:
        used = 0  # сброс
    if used >= limit:
        if vip:
            await message.answer("❌ Вы исчерпали дневной лимит (15 запросов). Попробуйте завтра.")
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Купить VIP", callback_data="buy_vip")]
            ])
            await message.answer(
                f"❌ У вас закончились бесплатные запросы ({FREE_DAILY_LIMIT} в день).\n"
                "Приобретите VIP-подписку, чтобы получить 15 запросов в день.\n"
                "Нажмите кнопку ниже.",
                reply_markup=keyboard
            )
        return False
    return True

# ---- Команда /start ----
@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    user = message.from_user
    await create_or_update_user(user.id, user.username, user.first_name)
    # Проверяем подписку на канал
    subscribed = await check_subscription(user.id, bot)
    if not subscribed:
        await message.answer(
            f"👋 Привет! Чтобы использовать бота, подпишитесь на канал:\n{CHANNEL_LINK}\n"
            "После подписки нажмите /start снова."
        )
        return
    # Показываем главное меню
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск по ВК (ФИО)", callback_data="search_vk")],
        [InlineKeyboardButton(text="🌐 Google Dorks", callback_data="search_dorks")],
        [InlineKeyboardButton(text="🕵️ Поиск в утечках", callback_data="search_leak")],
        [InlineKeyboardButton(text="💎 VIP статус", callback_data="vip_info")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")]
    ])
    vip_status = "✅ активна" if await is_vip(user.id) else "❌ не активна"
    await message.answer(
        f"Добро пожаловать, {user.first_name}!\n"
        f"Ваш VIP статус: {vip_status}\n"
        f"Доступно запросов сегодня: {FREE_DAILY_LIMIT if not await is_vip(user.id) else VIP_DAILY_LIMIT}",
        reply_markup=keyboard
    )

# ---- Обработчики поиска ----
@router.callback_query(F.data == "search_vk")
async def search_vk_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_access(callback.message, bot):
        await callback.answer()
        return
    await callback.message.answer("Введите имя и фамилию для поиска (через пробел):")
    await state.set_state(SearchState.waiting_for_vk_fio)
    await callback.answer()

@router.message(SearchState.waiting_for_vk_fio)
async def process_vk_search(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(user_id)
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Введите имя и фамилию через пробел.")
        return
    first_name, last_name = parts[0], ' '.join(parts[1:])
    await message.answer("🔎 Ищем...")
    try:
        results = await search_vk_by_name(first_name, last_name)
        if results:
            text = "Результаты поиска ВК:\n"
            for r in results:
                text += f"👤 {r['name']}\nСсылка: {r['profile_url']}\n\n"
            await message.answer(text[:4000])
        else:
            await message.answer("Ничего не найдено.")
    except Exception as e:
        logging.error(e)
        await message.answer("Ошибка при поиске.")

@router.callback_query(F.data == "search_dorks")
async def search_dorks_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_access(callback.message, bot):
        await callback.answer()
        return
    await callback.message.answer("Введите dork-запрос (например, site:example.com filetype:pdf):")
    await state.set_state(SearchState.waiting_for_google_dork)
    await callback.answer()

@router.message(SearchState.waiting_for_google_dork)
async def process_dorks(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(user_id)
    query = message.text
    await message.answer("🔎 Ищем по Google Dorks...")
    results = await search_google_dorks(query)
    if results:
        text = "🌐 Результаты Google Dorks:\n"
        for r in results:
            text += f"📄 {r['title']}\n{r['snippet']}\n{r['link']}\n\n"
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
    await callback.message.answer("Выберите тип данных для поиска в утечках:", reply_markup=keyboard)
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
    user_id = message.from_user.id
    if not await ensure_access(message, bot):
        return
    await increment_daily_requests(user_id)
    data = await state.get_data()
    leak_type = data.get("leak_type", "phone")
    value = message.text.strip()
    await message.answer("🕵️ Ищем в базах утечек...")
    results = await search_leaked_data(leak_type, value)
    if results:
        text = "📂 Результаты:\n"
        for r in results:
            text += f"🔹 {r['source']}: {r['info']}\n"
        await message.answer(text[:4000])
    else:
        await message.answer("Ничего не найдено.")

# ---- VIP информация и покупка ----
@router.callback_query(F.data == "vip_info")
async def vip_info(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    vip = await is_vip(user_id)
    until = await get_vip_until(user_id)
    text = "💎 VIP-подписка:\n"
    if vip:
        date = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        text += f"Активна до {date}\nЛимит: {VIP_DAILY_LIMIT} запросов в день"
        await callback.answer(text, show_alert=True)
    else:
        text += "Не активна.\nКупите за {VIP_PRICE} руб. на {VIP_DURATION_DAYS} дней."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить VIP", callback_data="buy_vip")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    link = await create_payment_link(user_id)
    if link:
        await callback.message.edit_text(
            f"💳 Для оплаты VIP-подписки перейдите по ссылке:\n{link}\n"
            "После оплаты статус обновится автоматически."
        )
    else:
        await callback.answer("Ошибка создания платежа. Попробуйте позже.", show_alert=True)
    await callback.answer()

# ---- Промокоды ----
@router.callback_query(F.data == "activate_promo")
async def activate_promo_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите промокод:")
    await state.set_state(PromoState.waiting_for_code)
    await callback.answer()

@router.message(PromoState.waiting_for_code)
async def process_promo(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    code = message.text.strip()
    promo = await get_promo(code)
    if not promo:
        await message.answer("❌ Неверный промокод.")
        return
    if promo[3] is not None:
        await message.answer("❌ Этот промокод уже был использован.")
        return
    success = await use_promo(code, user_id)
    if success:
        await message.answer("✅ Промокод активирован! VIP-подписка оформлена.")
    else:
        await message.answer("❌ Ошибка активации.")
