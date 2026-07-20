import aiosqlite
import time
from datetime import datetime
from config import DB_NAME

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
