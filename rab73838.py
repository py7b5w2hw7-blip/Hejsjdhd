import asyncio
import sqlite3
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, CallbackQuery, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN       = os.getenv("BOT_TOKEN")
BOT_USERNAME    = os.getenv("BOT_USERNAME", "berrynano6bot")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "7950533047"))
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "feji73")
CHANNEL_LINK    = os.getenv("CHANNEL_LINK", "https://t.me/+otgte7DKQF40YmMy")
STARS_BUY       = os.getenv("STARS_BUY", "https://split.tg/?ref=UQD06L7Gv3pWk1J8DJ1wUeNsflj30ZmUyuZnb3zknSmVy5J-")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан! Создай файл .env")

PLANS = {
    "tb1":    {"label": "1 ТБ", "stars": 950, "crypto": None},
    "full":   {"label": "50 ГБ", "stars": 600, "crypto": "https://t.me/send?start=IVfBnFlf6v5b"},
    "medium": {"label": "15 ГБ", "stars": 400, "crypto": "https://t.me/send?start=IVCR8jU3BohU"},
    "small":  {"label": "5 ГБ",  "stars": 350, "crypto": None},
}
PLAN_NAMES = {"tb1": "1 ТБ", "full": "50 ГБ", "medium": "15 ГБ", "small": "5 ГБ"}

LEVELS = [
    (0,    "🥉 Новичок",     15, 0),
    (5,    "🥈 Продвинутый", 20, 10),
    (15,   "🥇 Опытный",     25, 25),
    (30,   "💎 Эксперт",     35, 40),
    (50,   "🔥 Топ",         50, 50),
]

def get_level(invited_count: int):
    current = LEVELS[0]
    for threshold, name, percent, reward in LEVELS:
        if invited_count >= threshold:
            current = (threshold, name, percent, reward)
    next_threshold = None
    for threshold, name, percent, reward in LEVELS:
        if threshold > invited_count:
            next_threshold = threshold
            break
    return current[1], current[2], next_threshold, current[3]

BUYER_LEVELS = [
    (0,     "🥉 Бронза"),
    (500,   "🥈 Серебро"),
    (2000,  "🥇 Золото"),
    (5000,  "💎 Платина"),
]

def get_buyer_level(total_spent: int):
    level = BUYER_LEVELS[0][1]
    for threshold, name in BUYER_LEVELS:
        if total_spent >= threshold:
            level = name
    return level

DB = "tendo.db"

# ═══════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ═══════════════════════════════════════════════════════

def db_init():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT,
            ref_by      INTEGER DEFAULT NULL,
            banned      INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            last_daily  TEXT DEFAULT NULL,
            level_rewards TEXT DEFAULT '[]',
            balance     INTEGER DEFAULT 0
        )
    """)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            plan        TEXT,
            stars       INTEGER,
            paid_at     TEXT,
            ref_owner   INTEGER DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ref_earnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id    INTEGER,
            from_user   INTEGER,
            stars       INTEGER,
            earned      INTEGER,
            paid_at     TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            amount      INTEGER,
            status      TEXT DEFAULT 'pending',
            requested_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ref_notify_sent (
            owner_id    INTEGER,
            from_user   INTEGER,
            PRIMARY KEY (owner_id, from_user)
        )
    """)
    con.commit()
    con.close()

def db_add_user(user: types.User, ref_by: int = None):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, ref_by, banned, total_spent, last_daily, level_rewards, balance)
        VALUES (?, ?, ?, ?, ?, 0, 0, NULL, '[]', 0)
    """, (user.id, user.username, user.first_name,
          datetime.now().strftime("%Y-%m-%d %H:%M"), ref_by))
    con.commit()
    con.close()

def db_get_balance(user_id: int) -> int:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row[0] if row else 0

def db_update_balance(user_id: int, amount: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    con.commit()
    con.close()

def db_get_total_spent(user_id: int) -> int:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT total_spent FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row[0] if row else 0

def db_update_total_spent(user_id: int, stars: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("UPDATE users SET total_spent = total_spent + ? WHERE user_id=?", (stars, user_id))
    con.commit()
    con.close()

def db_can_claim_daily(user_id: int) -> bool:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT last_daily FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    if not row or not row[0]:
        return True
    last = datetime.strptime(row[0], "%Y-%m-%d")
    return datetime.now().date() > last.date()

def db_claim_daily(user_id: int) -> int:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("UPDATE users SET last_daily = ? WHERE user_id=?", (datetime.now().strftime("%Y-%m-%d"), user_id))
    cur.execute("UPDATE users SET balance = balance + 5 WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
    return 5

def db_get_ref_by(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT ref_by FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row[0] if row else None

def db_get_invited_count(owner_id: int) -> int:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    count = cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (owner_id,)).fetchone()[0]
    con.close()
    return count

def db_has_ref_notify_sent(owner_id: int, from_user: int) -> bool:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT 1 FROM ref_notify_sent WHERE owner_id=? AND from_user=?", (owner_id, from_user)).fetchone()
    con.close()
    return row is not None

def db_mark_ref_notify_sent(owner_id: int, from_user: int):
    con = sqlite3.connect(DB)
    con.execute("INSERT OR IGNORE INTO ref_notify_sent (owner_id, from_user) VALUES (?, ?)", (owner_id, from_user))
    con.commit()
    con.close()

def db_is_banned(user_id: int) -> bool:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT banned FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row[0] == 1 if row else False

def db_ban_user(user_id: int, ban: bool = True):
    con = sqlite3.connect(DB)
    con.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if ban else 0, user_id))
    con.commit()
    con.close()

def db_has_level_reward(user_id: int, level_name: str) -> bool:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT level_rewards FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    if not row:
        return False
    rewards = json.loads(row[0])
    return level_name in rewards

def db_add_level_reward(user_id: int, level_name: str):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT level_rewards FROM users WHERE user_id=?", (user_id,)).fetchone()
    rewards = json.loads(row[0]) if row else []
    rewards.append(level_name)
    cur.execute("UPDATE users SET level_rewards = ? WHERE user_id=?", (json.dumps(rewards), user_id))
    con.commit()
    con.close()

def db_check_and_give_level_reward(user_id: int, invited_count: int):
    level_name, _, _, reward = get_level(invited_count)
    if reward > 0 and not db_has_level_reward(user_id, level_name):
        db_add_level_reward(user_id, level_name)
        db_update_balance(user_id, reward)
        return reward
    return 0

def db_add_purchase(user_id: int, plan: str, stars: int) -> tuple:
    db_update_total_spent(user_id, stars)

    ref_by = db_get_ref_by(user_id)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO purchases (user_id, plan, stars, paid_at, ref_owner)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, plan, stars, datetime.now().strftime("%Y-%m-%d %H:%M"), ref_by))
    con.commit()
    con.close()

    if ref_by and ref_by != user_id:
        invited_count = db_get_invited_count(ref_by)
        _, pct, _, _ = get_level(invited_count)
        earned = int(stars * pct / 100)
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO ref_earnings (owner_id, from_user, stars, earned, paid_at)
            VALUES (?, ?, ?, ?, ?)
        """, (ref_by, user_id, stars, earned, datetime.now().strftime("%Y-%m-%d %H:%M")))
        con.commit()
        con.close()
        db_update_balance(ref_by, earned)
        return ref_by, earned
    return 0, 0

def db_get_ref_stats(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    invited = cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)).fetchone()[0]
    buyers = cur.execute("SELECT COUNT(DISTINCT from_user) FROM ref_earnings WHERE owner_id=?", (user_id,)).fetchone()[0]
    total_earned = cur.execute("SELECT COALESCE(SUM(earned),0) FROM ref_earnings WHERE owner_id=?", (user_id,)).fetchone()[0]
    paid_out = cur.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='done'", (user_id,)).fetchone()[0]
    pending_req = cur.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='pending'", (user_id,)).fetchone()[0]
    balance = total_earned - paid_out - pending_req
    recent = cur.execute("""
        SELECT u.first_name, u.username, re.stars, re.earned, re.paid_at
        FROM ref_earnings re LEFT JOIN users u ON re.from_user = u.user_id
        WHERE re.owner_id=? ORDER BY re.id DESC LIMIT 5
    """, (user_id,)).fetchall()
    con.close()
    return {
        "invited": invited, "buyers": buyers,
        "total_earned": total_earned, "paid_out": paid_out,
        "pending": pending_req, "balance": balance, "recent": recent
    }

def db_get_stats():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    s = {
        "total_users":      cur.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "today_users":      cur.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)).fetchone()[0],
        "total_purchases":  cur.execute("SELECT COUNT(*) FROM purchases").fetchone()[0],
        "today_purchases":  cur.execute("SELECT COUNT(*) FROM purchases WHERE paid_at LIKE ?", (f"{today}%",)).fetchone()[0],
        "total_stars":      cur.execute("SELECT COALESCE(SUM(stars),0) FROM purchases").fetchone()[0],
        "total_earned":     cur.execute("SELECT COALESCE(SUM(earned),0) FROM ref_earnings").fetchone()[0],
        "pending_withdrawals": cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
        "recent":           cur.execute("""
            SELECT u.first_name, u.username, p.plan, p.stars, p.paid_at
            FROM purchases p LEFT JOIN users u ON p.user_id=u.user_id
            ORDER BY p.id DESC LIMIT 5
        """).fetchall(),
    }
    con.close()
    return s

def db_get_all_users():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT user_id FROM users").fetchall()
    con.close()
    return [r[0] for r in rows]

def db_get_top_refs():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT u.user_id, u.first_name, u.username,
               (SELECT COUNT(*) FROM users u2 WHERE u2.ref_by = u.user_id) as invited,
               (SELECT COALESCE(SUM(earned),0) FROM ref_earnings re WHERE re.owner_id = u.user_id) as earned
        FROM users u
        WHERE (SELECT COUNT(*) FROM users u2 WHERE u2.ref_by = u.user_id) > 0
        ORDER BY invited DESC
        LIMIT 10
    """).fetchall()
    con.close()
    return rows

def db_get_workers():
    """Все пользователи, у которых есть хотя бы 1 приглашённый"""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT u.user_id, u.first_name, u.username,
               (SELECT COUNT(*) FROM users u2 WHERE u2.ref_by = u.user_id) as invited,
               (SELECT COUNT(DISTINCT from_user) FROM ref_earnings re WHERE re.owner_id = u.user_id) as buyers,
               (SELECT COALESCE(SUM(earned),0) FROM ref_earnings re WHERE re.owner_id = u.user_id) as earned
        FROM users u
        WHERE (SELECT COUNT(*) FROM users u2 WHERE u2.ref_by = u.user_id) > 0
        ORDER BY invited DESC
    """).fetchall()
    con.close()
    return rows

def db_get_user_detail(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    user = cur.execute("SELECT first_name, username, banned, total_spent, joined_at FROM users WHERE user_id=?", (user_id,)).fetchone()
    invited = cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)).fetchone()[0]
    earnings = cur.execute("""
        SELECT u.first_name, u.username, re.stars, re.earned, re.paid_at
        FROM ref_earnings re LEFT JOIN users u ON re.from_user=u.user_id
        WHERE re.owner_id=? ORDER BY re.id DESC LIMIT 10
    """, (user_id,)).fetchall()
    total = cur.execute("SELECT COALESCE(SUM(earned),0) FROM ref_earnings WHERE owner_id=?", (user_id,)).fetchone()[0]
    paid = cur.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='done'", (user_id,)).fetchone()[0]
    pending = cur.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='pending'", (user_id,)).fetchone()[0]
    buyers = cur.execute("SELECT COUNT(DISTINCT from_user) FROM ref_earnings WHERE owner_id=?", (user_id,)).fetchone()[0]
    con.close()
    return {
        "user": user, "invited": invited, "earnings": earnings,
        "total": total, "paid": paid, "pending": pending,
        "balance": total - paid - pending, "buyers": buyers
    }

def db_get_pending_withdrawals():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT w.id, w.user_id, u.first_name, u.username, w.amount, w.requested_at
        FROM withdrawals w LEFT JOIN users u ON w.user_id=u.user_id
        WHERE w.status='pending' ORDER BY w.id
    """).fetchall()
    con.close()
    return rows

def db_set_withdrawal_status(wid: int, status: str):
    con = sqlite3.connect(DB)
    con.execute("UPDATE withdrawals SET status=? WHERE id=?", (status, wid))
    con.commit()
    con.close()

def db_request_withdrawal(user_id: int, amount: int):
    con = sqlite3.connect(DB)
    con.execute("""
        INSERT INTO withdrawals (user_id, amount, status, requested_at)
        VALUES (?, ?, 'pending', ?)
    """, (user_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
    con.commit()
    con.close()

def db_get_recent_users(limit=20):
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT user_id, first_name, username, joined_at FROM users ORDER BY rowid DESC LIMIT ?",
        (limit,)
    ).fetchall()
    con.close()
    return rows

# ═══════════════════════════════════════════════════════
# FSM
# ═══════════════════════════════════════════════════════

class BroadcastState(StatesGroup):
    waiting_text = State()

class AdminState(StatesGroup):
    user_lookup = State()

# ═══════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════

db_init()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ═══════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════

def kb_main():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Оплатить звёздами", callback_data="menu_stars"))
    kb.row(InlineKeyboardButton(text="🌐 Оплатить криптой",  callback_data="menu_crypto"))
    kb.row(InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="ref_menu"))
    kb.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    kb.row(InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily"))
    kb.row(InlineKeyboardButton(text="💫 Где купить звёзды?", url=STARS_BUY))
    return kb.as_markup()

def kb_admin():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Статистика",        callback_data="adm_stats"))
    kb.row(InlineKeyboardButton(text="👥 Все пользователи",  callback_data="adm_users"))
    kb.row(InlineKeyboardButton(text="📋 Последние покупки", callback_data="adm_recent"))
    kb.row(InlineKeyboardButton(text="🏆 Топ рефереров",     callback_data="adm_refs"))
    kb.row(InlineKeyboardButton(text="👷 Рабочие",           callback_data="adm_workers"))
    kb.row(InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="adm_user_lookup"))
    kb.row(InlineKeyboardButton(text="💸 Заявки на выплату", callback_data="adm_withdrawals"))
    kb.row(InlineKeyboardButton(text="📢 Рассылка",          callback_data="adm_broadcast"))
    kb.row(InlineKeyboardButton(text="❌ Закрыть",           callback_data="adm_close"))
    return kb.as_markup()

def kb_back_admin():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад в админ", callback_data="adm_back")
    ]])

# ═══════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if db_is_banned(message.from_user.id):
        return

    args = message.text.split()
    ref_by = None
    new_user = False

    con = sqlite3.connect(DB)
    cur = con.cursor()
    existing = cur.execute("SELECT 1 FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    con.close()

    if not existing:
        new_user = True
        if len(args) > 1 and args[1].startswith("ref"):
            try:
                ref_id = int(args[1][3:])
                if ref_id != message.from_user.id:
                    existing_ref = db_get_ref_by(message.from_user.id)
                    if existing_ref is None:
                        ref_by = ref_id
            except ValueError:
                pass

    db_add_user(message.from_user, ref_by)

    if ref_by and new_user:
        if not db_has_ref_notify_sent(ref_by, message.from_user.id):
            db_mark_ref_notify_sent(ref_by, message.from_user.id)
            try:
                invited_count = db_get_invited_count(ref_by)
                level_name, pct, _, _ = get_level(invited_count)
                await bot.send_message(
                    ref_by,
                    f"👤 <b>Новый реферал!</b>\n\n"
                    f"По вашей ссылке перешёл: {message.from_user.first_name}\n"
                    f"📊 Текущий уровень: {level_name} ({pct}%)\n"
                    f"👥 Приглашено: {invited_count + 1} чел.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await message.answer(
        "🌿 <b>TENDO</b>\n\n"
        "✅ Автовыдача сразу после оплаты\n"
        "🔒 Безопасная оплата через Telegram Stars\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=kb_main()
    )

# ═══════════════════════════════════════════════════════
# /profile
# ═══════════════════════════════════════════════════════

@dp.message(Command("profile"))
@dp.callback_query(F.data == "profile")
async def show_profile(event):
    is_callback = isinstance(event, CallbackQuery)
    user_id = event.from_user.id
    msg = event.message if is_callback else event

    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT balance, total_spent, joined_at, first_name, username FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()

    if not row:
        if is_callback:
            await event.answer("Ошибка", show_alert=True)
        else:
            await event.answer("Ошибка")
        return

    balance, total_spent, joined_at, first_name, username = row
    level = get_buyer_level(total_spent)
    username_str = f"@{username}" if username else "—"

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Имя: {first_name}\n"
        f"Username: {username_str}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📅 Регистрация: {joined_at[:10]}\n\n"
        f"💰 Реф. баланс: <b>{balance}⭐</b>\n"
        f"💸 Всего потрачено: <b>{total_spent}⭐</b>\n"
        f"🏆 Уровень покупателя: {level}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_start")
    ]])

    if is_callback:
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)

# ═══════════════════════════════════════════════════════
# /daily
# ═══════════════════════════════════════════════════════

@dp.message(Command("daily"))
@dp.callback_query(F.data == "daily")
async def daily_bonus(event):
    is_callback = isinstance(event, CallbackQuery)
    user_id = event.from_user.id

    if db_is_banned(user_id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_start")
    ]])

    if db_can_claim_daily(user_id):
        amount = db_claim_daily(user_id)
        new_balance = db_get_balance(user_id)
        text = f"✅ <b>Ежедневный бонус получен!</b>\n\n🎁 +{amount}⭐ к реф. балансу\n💰 Реф. баланс: {new_balance}⭐"
        if is_callback:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            await event.answer()
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        text = "❌ <b>Вы уже забирали бонус сегодня!</b>\n\nПриходите завтра."
        if is_callback:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            await event.answer()
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=kb)

# ═══════════════════════════════════════════════════════
# /admin
# ═══════════════════════════════════════════════════════

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    s = db_get_stats()
    await message.answer(
        f"🛡 <b>Админ-панель TENDO</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
        f"🆕 Новых сегодня: <b>{s['today_users']}</b>\n"
        f"💳 Покупок сегодня: <b>{s['today_purchases']}</b>\n"
        f"⭐ Всего звёзд: <b>{s['total_stars']}</b>",
        parse_mode="HTML",
        reply_markup=kb_admin()
    )

# ═══════════════════════════════════════════════════════
# РЕФЕРАЛЬНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "ref_menu")
async def ref_menu(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    uid = call.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    s = db_get_ref_stats(uid)

    invited_count = s["invited"]
    level_name, pct, next_thresh, _ = get_level(invited_count)

    levels_text = (
        "📊 <b>Уровни (по приглашённым):</b>\n"
        "🥉 Новичок — 0 пригл. → <b>15%</b>\n"
        "🥈 Продвинутый — 5+ пригл. → <b>20%</b> +10⭐\n"
        "🥇 Опытный — 15+ пригл. → <b>25%</b> +25⭐\n"
        "💎 Эксперт — 30+ пригл. → <b>35%</b> +40⭐\n"
        "🔥 Топ — 50+ пригл. → <b>50%</b> +50⭐"
    )

    next_line = f"⬆️ До следующего уровня: ещё <b>{next_thresh - invited_count}</b> приглашений" if next_thresh else "🏆 Максимальный уровень!"

    recent_lines = ""
    if s["recent"]:
        lines = []
        for name, uname, stars, earned, at in s["recent"]:
            lines.append(f"  • {name or '?'} — {stars}⭐ покупка, тебе +{earned}⭐ ({at[:10]})")
        recent_lines = "\n\n📜 <b>Последние начисления:</b>\n" + "\n".join(lines)

    text = (
        f"⭐ <b>Реферальная программа</b>\n\n"
        f"{levels_text}\n\n"
        f"🎯 Твой уровень: {level_name} — <b>{pct}%</b>\n"
        f"{next_line}\n\n"
        f"🔗 <b>Твоя реферальная ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📈 <b>Твоя статистика:</b>\n"
        f"👥 Приглашено: <b>{s['invited']}</b> чел.\n"
        f"✅ Рефералов с покупкой: <b>{s['buyers']}</b> чел.\n"
        f"⭐ Всего заработано: <b>{s['total_earned']}</b> звёзд\n"
        f"💸 Выплачено: <b>{s['paid_out']}</b> звёзд\n"
        f"⏳ На рассмотрении: <b>{s['pending']}</b> звёзд\n"
        f"💰 Баланс: <b>{s['balance']}</b> звёзд"
        f"{recent_lines}\n\n"
        f"✨ <b>Не забывай:</b>\n"
        f"• За достижение уровней даются бонусы!\n"
        f"• По вопросам выплат: @{ADMIN_USERNAME}"
    )

    kb = InlineKeyboardBuilder()
    if s["balance"] > 0:
        kb.row(InlineKeyboardButton(
            text=f"💸 Вывести {s['balance']}⭐", callback_data="ref_withdraw"
        ))
    kb.row(InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="ref_howto"))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "ref_howto")
async def ref_howto(call: CallbackQuery):
    text = (
        "⭐ <b>Как работает реферальная система</b>\n\n"
        "Ты приглашаешь людей по своей ссылке → получаешь процент с их покупок.\n\n"
        "<b>Уровни (чем больше пригласил, тем выше процент и бонусы):</b>\n"
        "• 0 приглашённых → 15%\n"
        "• 5+ приглашённых → 20% + 10⭐\n"
        "• 15+ приглашённых → 25% + 25⭐\n"
        "• 30+ приглашённых → 35% + 40⭐\n"
        "• 50+ приглашённых → 50% + 50⭐\n\n"
        "💰 <b>Пример:</b>\n"
        "Твой реферал купил пакет за 600⭐.\n"
        "Если ты пригласил 0 человек → получишь 90⭐\n"
        "Если пригласил 50+ человек → получишь 300⭐!\n\n"
        "🎁 <b>Бонусы за уровни:</b>\n"
        "При достижении каждого нового уровня ты получаешь разовую награду!\n\n"
        "📢 При переходе по твоей ссылке ты получишь уведомление."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="ref_menu")
    ]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "ref_withdraw")
async def ref_withdraw(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    uid = call.from_user.id
    s = db_get_ref_stats(uid)
    if s["balance"] <= 0:
        await call.answer("У вас нет доступного баланса", show_alert=True)
        return

    db_request_withdrawal(uid, s["balance"])

    uname = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💸 <b>Заявка на вывод!</b>\n\n"
            f"👤 {uname} (ID: <code>{uid}</code>)\n"
            f"⭐ Сумма: <b>{s['balance']}</b> звёзд\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("✅ Заявка отправлена! Ожидайте выплату.", show_alert=True)
    await ref_menu(call)

# ═══════════════════════════════════════════════════════
# ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and c.data.startswith("adm_"))
async def admin_handler(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    action = call.data

    if action == "adm_stats":
        s = db_get_stats()
        text = (
            "📊 <b>Статистика TENDO</b>\n\n"
            f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
            f"🆕 Новых сегодня: <b>{s['today_users']}</b>\n\n"
            f"💳 Всего покупок: <b>{s['total_purchases']}</b>\n"
            f"📅 Покупок сегодня: <b>{s['today_purchases']}</b>\n"
            f"⭐ Всего звёзд получено: <b>{s['total_stars']}</b>\n\n"
            f"🤝 Реф. выплаты начислено: <b>{s['total_earned']}</b>⭐\n"
            f"💸 Заявок на вывод: <b>{s['pending_withdrawals']}</b>"
        )
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_recent":
        s = db_get_stats()
        if not s["recent"]:
            text = "📋 Покупок ещё нет."
        else:
            lines = ["📋 <b>Последние 5 покупок:</b>\n"]
            for name, uname, plan, stars, at in s["recent"]:
                ustr = f"@{uname}" if uname else "—"
                lines.append(f"• {name or '?'} ({ustr})\n  📦 {PLAN_NAMES.get(plan, plan)} — {stars}⭐ — {at}")
            text = "\n\n".join(lines)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_refs":
        rows = db_get_top_refs()
        if not rows:
            text = "🤝 Реферальных продаж ещё нет."
        else:
            lines = ["🏆 <b>Топ рефереров:</b>\n"]
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            for i, (uid, name, uname, invited, earned) in enumerate(rows):
                lvl_name, pct, _, _ = get_level(invited)
                ustr = f"@{uname}" if uname else f"ID:{uid}"
                medal = medals[i] if i < len(medals) else f"{i+1}."
                lines.append(
                    f"{medal} {name or '?'} ({ustr})\n"
                    f"   {lvl_name} ({pct}%) | 👥 {invited} пригл. | ⭐ {earned} заработано"
                )
            text = "\n\n".join(lines)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_workers":
        rows = db_get_workers()
        if not rows:
            await call.message.edit_text(
                "👷 <b>Рабочие</b>\n\nНет пользователей с рефералами.",
                parse_mode="HTML",
                reply_markup=kb_back_admin()
            )
        else:
            kb = InlineKeyboardBuilder()
            lines = [f"👷 <b>Рабочие — {len(rows)} чел.</b>\n(приглашали хотя бы 1 человека)\n\n"]
            for uid, name, uname, invited, buyers, earned in rows:
                ustr = f"@{uname}" if uname else f"ID:{uid}"
                lvl_name, pct, _, _ = get_level(invited)
                lines.append(
                    f"• {name or '?'} ({ustr})\n"
                    f"  👥 Приглашено: {invited} | ✅ Купили: {buyers} | ⭐ Заработано: {earned} | {lvl_name}\n"
                )
                kb.row(InlineKeyboardButton(
                    text=f"🔍 {name or ustr}",
                    callback_data=f"worker_{uid}"
                ))
            kb.row(InlineKeyboardButton(text="◀️ Назад в админ", callback_data="adm_back"))
            await call.message.edit_text(
                "\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup()
            )

    elif action == "adm_user_lookup":
        await state.set_state(AdminState.user_lookup)
        await call.message.edit_text(
            "🔍 Введите Telegram ID пользователя для просмотра статистики и управления:\n\nДля отмены /cancel",
            parse_mode="HTML"
        )

    elif action == "adm_withdrawals":
        rows = db_get_pending_withdrawals()
        if not rows:
            await call.message.edit_text("💸 Заявок на вывод нет.", reply_markup=kb_back_admin())
        else:
            for wid, uid, name, uname, amount, req_at in rows:
                ustr = f"@{uname}" if uname else "—"
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Оплачено", callback_data=f"wdone_{wid}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wdecline_{wid}"),
                ]])
                await bot.send_message(
                    ADMIN_ID,
                    f"💸 <b>Заявка #{wid}</b>\n"
                    f"👤 {name or '?'} ({ustr}) — ID <code>{uid}</code>\n"
                    f"⭐ Сумма: <b>{amount}</b> звёзд\n"
                    f"📅 {req_at}",
                    parse_mode="HTML",
                    reply_markup=kb
                )
            await call.message.edit_text(
                f"📋 Отправлено <b>{len(rows)}</b> заявок выше ↑",
                parse_mode="HTML",
                reply_markup=kb_back_admin()
            )

    elif action == "adm_users":
        s = db_get_stats()
        rows = db_get_recent_users(20)
        lines = [
            f"👥 <b>Пользователи</b>\n"
            f"Всего: <b>{s['total_users']}</b> | Сегодня: <b>{s['today_users']}</b>\n\n"
            f"<b>Последние 20:</b>"
        ]
        for uid, name, uname, joined in rows:
            ustr = f"@{uname}" if uname else "—"
            lines.append(f"• {name or '?'} ({ustr}) — {joined[:10]}")
        await call.message.edit_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=kb_back_admin()
        )

    elif action == "adm_broadcast":
        s = db_get_stats()
        await state.set_state(BroadcastState.waiting_text)
        await call.message.edit_text(
            f"📢 <b>Рассылка</b>\n\n"
            f"Будет отправлено: <b>{s['total_users']}</b> пользователям\n\n"
            f"Отправь текст (поддерживается HTML: <b>жирный</b>, <i>курсив</i>).\n"
            f"Для отмены — /cancel",
            parse_mode="HTML"
        )

    elif action == "adm_back":
        await state.clear()
        s = db_get_stats()
        await call.message.edit_text(
            f"🛡 <b>Админ-панель TENDO</b>\n\n"
            f"👥 Всего: <b>{s['total_users']}</b> | Сегодня: <b>{s['today_users']}</b>\n"
            f"💳 Покупок сегодня: <b>{s['today_purchases']}</b>",
            parse_mode="HTML",
            reply_markup=kb_admin()
        )

    elif action == "adm_close":
        await call.message.delete()

    await call.answer()

# ═══════════════════════════════════════════════════════
# ПРОСМОТР РАБОЧЕГО (подробная статистика)
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and c.data.startswith("worker_"))
async def worker_detail(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        uid = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        await call.answer("Ошибка ID")
        return

    d = db_get_user_detail(uid)
    if not d["user"]:
        await call.answer("Пользователь не найден", show_alert=True)
        return

    name, uname, banned, total_spent, joined_at = d["user"]
    invited_count = d["invited"]
    lvl_name, pct, _, _ = get_level(invited_count)
    ustr = f"@{uname}" if uname else "—"
    buyer_level = get_buyer_level(total_spent)

    lines = [
        f"🔍 <b>{name or '?'} ({ustr})</b>\n"
        f"ID: <code>{uid}</code>\n\n"
        f"🎯 Реф. уровень: {lvl_name} ({pct}%)\n"
        f"🏆 Уровень покупателя: {buyer_level}\n"
        f"💰 Всего потрачено: <b>{total_spent}</b>⭐\n"
        f"👥 Приглашено: <b>{invited_count}</b>\n"
        f"✅ Рефералов с покупкой: <b>{d['buyers']}</b>\n"
        f"⭐ Заработано на реф.: <b>{d['total']}</b>⭐\n"
        f"💸 Выплачено: <b>{d['paid']}</b>⭐\n"
        f"⏳ На рассмотрении: <b>{d['pending']}</b>⭐\n"
        f"💰 Остаток: <b>{d['balance']}</b>⭐"
    ]

    if d["earnings"]:
        lines.append("\n📜 <b>Последние покупки рефералов:</b>")
        for rname, runame, stars, earned, at in d["earnings"]:
            lines.append(f"  • {rname or '?'} — {stars}⭐ → +{earned}⭐ ({at[:10]})")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад к рабочим", callback_data="adm_workers")
    ]])

    await call.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await call.answer()

# ═══════════════════════════════════════════════════════
# ПОИСК ПОЛЬЗОВАТЕЛЯ ПО ID
# ═══════════════════════════════════════════════════════

@dp.message(AdminState.user_lookup)
async def user_lookup_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_admin())
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Введите числовой ID")
        return

    await state.clear()
    d = db_get_user_detail(uid)
    if not d["user"]:
        await message.answer("❌ Пользователь не найден в БД.", reply_markup=kb_admin())
        return

    name, uname, banned, total_spent, joined_at = d["user"]
    invited_count = d["invited"]
    lvl_name, pct, _, _ = get_level(invited_count)
    ustr = f"@{uname}" if uname else "—"
    buyer_level = get_buyer_level(total_spent)

    ban_status = "🔴 ЗАБЛОКИРОВАН" if banned else "🟢 АКТИВЕН"

    lines = [
        f"🔍 <b>Пользователь: {name or '?'} ({ustr})</b>\n"
        f"ID: <code>{uid}</code>\n\n"
        f"Статус: {ban_status}\n"
        f"🎯 Реф. уровень: {lvl_name} ({pct}%)\n"
        f"🏆 Уровень покупателя: {buyer_level}\n"
        f"💰 Всего потрачено: <b>{total_spent}</b>⭐\n"
        f"👥 Приглашено: <b>{d['invited']}</b>\n"
        f"✅ Рефералов с покупкой: <b>{d['buyers']}</b>\n"
        f"⭐ Заработано на реф.: <b>{d['total']}</b>⭐\n"
        f"💸 Выплачено: <b>{d['paid']}</b>⭐\n"
        f"⏳ На рассмотрении: <b>{d['pending']}</b>⭐\n"
        f"💰 Остаток: <b>{d['balance']}</b>⭐"
    ]

    kb = InlineKeyboardBuilder()
    if banned:
        kb.row(InlineKeyboardButton(text="🔓 Разбанить пользователя", callback_data=f"unban_{uid}"))
    else:
        kb.row(InlineKeyboardButton(text="🔒 Забанить пользователя", callback_data=f"ban_{uid}"))
    kb.row(InlineKeyboardButton(text="◀️ Назад в админ", callback_data="adm_back"))

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup())

# ═══════════════════════════════════════════════════════
# ОБРАБОТКА БАНА/РАЗБАНА
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and (c.data.startswith("ban_") or c.data.startswith("unban_")))
async def handle_ban(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    parts = call.data.split("_")
    action = parts[0]
    uid = int(parts[1])

    if action == "ban":
        db_ban_user(uid, True)
        await call.answer(f"✅ Пользователь {uid} заблокирован", show_alert=True)
    else:
        db_ban_user(uid, False)
        await call.answer(f"✅ Пользователь {uid} разблокирован", show_alert=True)

    d = db_get_user_detail(uid)
    if d["user"]:
        name, uname, banned, total_spent, joined_at = d["user"]
        invited_count = d["invited"]
        lvl_name, pct, _, _ = get_level(invited_count)
        ustr = f"@{uname}" if uname else "—"
        buyer_level = get_buyer_level(total_spent)
        ban_status = "🔴 ЗАБЛОКИРОВАН" if banned else "🟢 АКТИВЕН"

        lines = [
            f"🔍 <b>Пользователь: {name or '?'} ({ustr})</b>\n"
            f"ID: <code>{uid}</code>\n\n"
            f"Статус: {ban_status}\n"
            f"🎯 Реф. уровень: {lvl_name} ({pct}%)\n"
            f"🏆 Уровень покупателя: {buyer_level}\n"
            f"💰 Всего потрачено: <b>{total_spent}</b>⭐\n"
            f"👥 Приглашено: <b>{d['invited']}</b>\n"
            f"✅ Рефералов с покупкой: <b>{d['buyers']}</b>\n"
            f"⭐ Заработано на реф.: <b>{d['total']}</b>⭐\n"
            f"💸 Выплачено: <b>{d['paid']}</b>⭐\n"
            f"⏳ На рассмотрении: <b>{d['pending']}</b>⭐\n"
            f"💰 Остаток: <b>{d['balance']}</b>⭐"
        ]

        kb = InlineKeyboardBuilder()
        if banned:
            kb.row(InlineKeyboardButton(text="🔓 Разбанить пользователя", callback_data=f"unban_{uid}"))
        else:
            kb.row(InlineKeyboardButton(text="🔒 Забанить пользователя", callback_data=f"ban_{uid}"))
        kb.row(InlineKeyboardButton(text="◀️ Назад в админ", callback_data="adm_back"))

        await call.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup())

# ═══════════════════════════════════════════════════════
# ВЫПЛАТЫ
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and (c.data.startswith("wdone_") or c.data.startswith("wdecline_")))
async def handle_withdrawal(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    action = parts[0]
    wid = int(parts[1])

    con = sqlite3.connect(DB)
    row = con.execute("SELECT user_id, amount FROM withdrawals WHERE id=?", (wid,)).fetchone()
    con.close()

    if not row:
        await call.answer("Заявка не найдена")
        return

    uid, amount = row

    if action == "wdone":
        db_set_withdrawal_status(wid, "done")
        await bot.send_message(
            uid,
            f"✅ <b>Выплата {amount}⭐ одобрена!</b>\n\n"
            f"Средства будут переведены в ближайшее время.",
            parse_mode="HTML"
        )
        await call.message.edit_text(f"✅ Заявка #{wid} — оплачено ({amount}⭐)")
    else:
        db_set_withdrawal_status(wid, "declined")
        await bot.send_message(
            uid,
            f"❌ <b>Заявка на вывод {amount}⭐ отклонена.</b>\n\n"
            f"Свяжитесь с администратором: @{ADMIN_USERNAME}",
            parse_mode="HTML"
        )
        await call.message.edit_text(f"❌ Заявка #{wid} — отклонена")
    await call.answer()

# ═══════════════════════════════════════════════════════
# РАССЫЛКА
# ═══════════════════════════════════════════════════════

@dp.message(BroadcastState.waiting_text)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=kb_admin())
        return

    await state.clear()
    users = db_get_all_users()
    total = len(users)
    ok, fail = 0, 0

    status_msg = await message.answer(f"⏳ Начинаю рассылку...\n0 / {total}")

    for i, uid in enumerate(users, 1):
        try:
            await bot.send_message(uid, message.html_text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1

        if i % 20 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"⏳ Рассылка...\n"
                    f"✅ Отправлено: {ok} / {total}\n"
                    f"❌ Ошибок: {fail}"
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📨 Отправлено: <b>{ok}</b>\n"
            f"❌ Не доставлено: <b>{fail}</b>\n"
            f"📊 Всего: <b>{total}</b>",
            parse_mode="HTML",
            reply_markup=kb_back_admin()
        )
    except Exception:
        await message.answer(
            f"✅ <b>Рассылка завершена!</b>\n📨 {ok}/{total} доставлено",
            parse_mode="HTML",
            reply_markup=kb_back_admin()
        )

# ═══════════════════════════════════════════════════════
# ОПЛАТА ЗВЁЗДАМИ
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "menu_stars")
async def menu_stars(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="1 ТБ — 950 ⭐", callback_data="stars_tb1"))
    kb.row(InlineKeyboardButton(text="50 ГБ — 600 ⭐", callback_data="stars_full"))
    kb.row(InlineKeyboardButton(text="15 ГБ — 400 ⭐", callback_data="stars_medium"))
    kb.row(InlineKeyboardButton(text="5 ГБ  — 350 ⭐", callback_data="stars_small"))
    kb.row(InlineKeyboardButton(text="💫 Где купить звёзды?", url=STARS_BUY))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))
    await call.message.edit_text(
        "⭐ <b>Оплата звёздами</b>\n\n"
        "✅ После оплаты вы автоматически получите доступ.\n"
        "Выберите объём:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await call.answer()

@dp.callback_query(F.data == "menu_crypto")
async def menu_crypto(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    kb = InlineKeyboardBuilder()
    if PLANS["full"]["crypto"]:
        kb.row(InlineKeyboardButton(text="50 ГБ — Оплатить", url=PLANS["full"]["crypto"]))
    if PLANS["medium"]["crypto"]:
        kb.row(InlineKeyboardButton(text="15 ГБ — Оплатить", url=PLANS["medium"]["crypto"]))
    if PLANS["small"]["crypto"]:
        kb.row(InlineKeyboardButton(text="5 ГБ — Оплатить", url=PLANS["small"]["crypto"]))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))
    await call.message.edit_text(
        "🌐 <b>Оплата криптой</b>\n\n"
        "✅ После оплаты вы автоматически получите доступ.\n"
        "Выберите объём:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await call.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("stars_"))
async def send_invoice(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    key = call.data.replace("stars_", "")
    plan = PLANS.get(key)
    if not plan:
        await call.answer("❌ Тариф не найден", show_alert=True)
        return

    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"TENDO — {plan['label']}",
        description=f"Доступ к контенту {plan['label']}. Автовыдача сразу после оплаты ✅",
        payload=f"tendo_{key}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="XTR", amount=plan["stars"])],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐ Заплатить {plan['stars']} звёзд", pay=True)
        ]])
    )
    await call.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(lambda m: m.successful_payment is not None)
async def successful_payment(message: Message):
    key = message.successful_payment.invoice_payload.replace("tendo_", "")
    stars = message.successful_payment.total_amount
    ref_id, earned = db_add_purchase(message.from_user.id, key, stars)

    if ref_id:
        invited_count = db_get_invited_count(ref_id)
        reward = db_check_and_give_level_reward(ref_id, invited_count)
        if reward:
            try:
                await bot.send_message(
                    ref_id,
                    f"🎁 <b>Поздравляем! Вы достигли нового уровня!</b>\n\n"
                    f"💰 Награда: <b>+{reward}⭐</b> на реф. баланс.\n"
                    f"Продолжайте приглашать друзей!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    if ref_id and earned:
        buyer_name = message.from_user.first_name
        invited_count = db_get_invited_count(ref_id)
        lvl_name, pct, _, _ = get_level(invited_count)
        try:
            await bot.send_message(
                ref_id,
                f"🎉 <b>Твой реферал совершил покупку!</b>\n\n"
                f"👤 {buyer_name}\n"
                f"📦 {PLAN_NAMES.get(key, key)} — {stars}⭐\n"
                f"💰 Тебе начислено: <b>+{earned}⭐</b>\n\n"
                f"🎯 Твой уровень: {lvl_name} ({pct}%)\n"
                f"👥 Приглашено: {invited_count} чел.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    uname = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Новая покупка!</b>\n\n"
            f"👤 {uname} (ID: <code>{message.from_user.id}</code>)\n"
            f"📦 {PLAN_NAMES.get(key, key)} — {stars}⭐\n"
            f"{'🤝 Реферал от ID: ' + str(ref_id) + f' (+{earned}⭐)' if ref_id else '🔗 Без реферала'}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.answer(
        "✅ <b>Оплата прошла успешно!</b>\n\nНажми кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📁 Получить контент", url=CHANNEL_LINK)
        ]])
    )

# ═══════════════════════════════════════════════════════
# НАЗАД В ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "back_start")
async def back_start(call: CallbackQuery):
    if db_is_banned(call.from_user.id):
        return

    await call.message.edit_text(
        "🌿 <b>TENDO</b>\n\n"
        "✅ Автовыдача сразу после оплаты\n"
        "🔒 Безопасная оплата через Telegram Stars\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=kb_main()
    )
    await call.answer()

# ═══════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════

async def main():
    print("✅ Бот TENDO запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())