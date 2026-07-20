from aiogram import Router, types, F
from aiogram.filters import Command
from config import ADMIN_IDS
from database import create_promo, list_promos, delete_promo, get_stats
import random
import string

router = Router()

@router.message(Command("create_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_create_promo(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /create_promo <количество_дней>")
        return
    try:
        days = int(args[1])
    except ValueError:
        await message.answer("Дни должны быть числом.")
        return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    success = await create_promo(code, days, message.from_user.id)
    if success:
        await message.answer(f"✅ Промокод создан:\n`{code}`\nДействует {days} дней.", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка создания (возможно код уже существует).")

@router.message(Command("list_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_list_promo(message: types.Message):
    promos = await list_promos()
    if not promos:
        await message.answer("Промокодов пока нет.")
        return
    text = "📋 Список промокодов:\n"
    for code, days, used_by, used_at in promos:
        status = "использован" if used_by else "активен"
        text += f"`{code}` – {days} дней, {status}\n"
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("delete_promo"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_delete_promo(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delete_promo <код>")
        return
    code = args[1]
    await delete_promo(code)
    await message.answer(f"Промокод `{code}` удалён.", parse_mode="Markdown")

@router.message(Command("stats"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stats(message: types.Message):
    stats = await get_stats()
    text = (
        f"📊 Статистика:\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"💎 Активных VIP: {stats['active_vip']}\n"
        f"💰 Оплат: {stats['total_payments']}\n"
        f"💵 Выручка: {stats['total_revenue']} руб."
    )
    await message.answer(text)
