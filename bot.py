"""
NextQuest Telegram Bot — v0.5
Соответствует nextquest_spec_v04.docx + фиксы:
  - /start всегда показывает приветствие с выбором роли
  - Модератор: удаление и редактирование событий из бота
  - Изменения автоматически отражаются на nextquest.today (через Supabase)

python-telegram-bot==21.5
supabase==2.9.1
python-dotenv==1.0.0
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, JobQueue
)
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
MODERATOR_ID = int(os.environ["MODERATOR_TG_ID"])
BOT_USERNAME = os.environ.get("BOT_USERNAME", "nextquest_bot")
SITE_URL     = os.environ.get("SITE_URL", "https://nextquest.today")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = {
    "boardgames": "🎲 Настолки",
    "larp":        "⚔️ LARP",
    "festival":    "🎪 Фестивали",
    "rpg":         "🎭 RPG",
    "cosplay":     "👗 Косплей",
    "other":       "🃏 Другое",
}

FORMATS = {
    "official": "🎉 Official",
    "private":  "🔒 Private",
}

REJECT_REASONS = [
    "Нет фото обложки",
    "Неполный адрес",
    "Дата в прошлом",
    "Дублирующее событие",
    "Нарушение правил",
    "Недостаточно информации",
    "✏️ Своя причина...",
]

# ─── Wizard states ───────────────────────────────────────────
(
    EV_CATEGORY,
    EV_YEAR, EV_MONTH, EV_DAY, EV_HOUR, EV_MINUTE,
    EV_END_CHOICE, EV_END_YEAR, EV_END_MONTH, EV_END_DAY, EV_END_HOUR, EV_END_MINUTE,
    EV_CITY, EV_ADDRESS, EV_LIMIT,
    EV_FORMAT,
    EV_TITLE, EV_DESC, EV_PHOTO,
    EV_URL,
    REJECT_CUSTOM,
    # Moderator edit wizard states
    MOD_EDIT_FIELD, MOD_EDIT_VALUE,
    # Organizer preview inline-edit states
    EV_EDIT_FIELD, EV_EDIT_VALUE,
) = range(25)


# ─── Helpers ─────────────────────────────────────────────────

def get_or_create_user(tg_id: int, username: str | None, lang: str = "ru"):
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    if res.data:
        return res.data[0]
    new_user = {"tg_id": tg_id, "tg_username": username, "role": "participant", "language": lang}
    supabase.table("users").insert(new_user).execute()
    return new_user

def get_user(tg_id: int):
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    return res.data[0] if res.data else None

def is_moderator(tg_id: int) -> bool:
    u = get_user(tg_id)
    return bool(u and u["role"] == "moderator")

def is_organizer(tg_id: int) -> bool:
    u = get_user(tg_id)
    return bool(u and u["role"] in ("organizer", "moderator"))

def build_google_calendar_url(ev: dict) -> str:
    """Generate a Google Calendar 'Add to Calendar' link from event data."""
    from urllib.parse import quote
    start = ev["date_start"].replace("-", "").replace(":", "").replace(" ", "T")[:15] + "00"
    if ev.get("date_end"):
        end = ev["date_end"].replace("-", "").replace(":", "").replace(" ", "T")[:15] + "00"
    else:
        end = start
    title    = quote(ev.get("title", ""))
    location = quote(f"{ev.get('location_city', '')} {ev.get('location_address', '')}".strip())
    details  = quote(f"{SITE_URL}/events/{ev.get('id', '')}")
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={title}&dates={start}/{end}&location={location}&details={details}"
    )


MONTHS_RU = ["января","февраля","марта","апреля","мая","июня",
             "июля","августа","сентября","октября","ноября","декабря"]
WEEKDAYS_RU = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

def format_date_ru(iso: str) -> str:
    """Convert ISO datetime to human-readable Russian format: Суббота, 10 мая · 22:30"""
    from datetime import datetime as dt
    d = dt.fromisoformat(iso[:16])
    weekday = WEEKDAYS_RU[d.weekday()]
    month   = MONTHS_RU[d.month - 1]
    return f"{weekday}, {d.day} {month} · {d.strftime('%H:%M')}"

def maps_url(city: str, address: str) -> str:
    from urllib.parse import quote
    q = quote(f"{address} {city}".strip())
    return f"https://maps.google.com/?q={q}"

def event_card_text(ev: dict) -> str:
    date_str   = format_date_ru(ev["date_start"])
    end_str    = f" – {ev['date_end'][11:16]}" if ev.get("date_end") else ""
    limit      = f"{ev['max_participants']} мест" if ev.get("max_participants") else "без лимита"
    fmt_label  = FORMATS.get(ev.get("format", "official"), "🎉 Official")
    reg_line   = f"\n⭐ Организатор: [Регистрация]({ev['external_url']})" if ev.get("external_url") else ""
    contact_line = f"\n📋 Контакт организатора: {ev['organizer_contacts']}" if ev.get("organizer_contacts") and not ev.get("external_url") else ""
    gcal_url   = build_google_calendar_url(ev)
    event_url  = f"{SITE_URL}/events/{ev.get('id', '')}"
    remind_url = f"t.me/{BOT_USERNAME}?start=event_{ev.get('id', '')}"
    location_link = f"[📍 {ev['location_city']} · {ev['location_address']}]({maps_url(ev['location_city'], ev['location_address'])})"
    return (
        f"*{ev['title'].upper()}*\n"
        f"{CATEGORIES.get(ev['category'], ev['category'])} · {fmt_label}\n"
        f"📅 {date_str}{end_str}\n"
        f"{location_link}\n"
        f"👥 {limit}"
        f"{contact_line}"
        f"{reg_line}\n\n"
        f"{ev['description']}\n\n"
        f"——————————————————\n\n"
        f"[🔔 Подписаться на напоминание]({remind_url})\n"
        f"[🌐 Страница события]({event_url})\n"
        f"[📅 Добавить в Google Календарь]({gcal_url})\n"
        f"⭐ Хочешь добавить своё событие? Напиши боту!"
    )

def event_share_text(ev: dict) -> str:
    """Готовый текст для репоста в Telegram-чат."""
    date_str   = format_date_ru(ev["date_start"])
    gcal_url   = build_google_calendar_url(ev)
    event_url  = f"{SITE_URL}/events/{ev['id']}"
    remind_url = f"t.me/{BOT_USERNAME}?start=event_{ev['id']}"
    organizer  = f"\n⭐ Организатор: [Регистрация]({ev['external_url']})" if ev.get("external_url") else ""
    contact_line = f"\n📋 Контакт организатора: {ev['organizer_contacts']}" if ev.get("organizer_contacts") and not ev.get("external_url") else ""
    description = ev['description'][:300] + ('...' if len(ev['description']) > 300 else '')
    location_link = f"[📍 {ev['location_city']} · {ev['location_address']}]({maps_url(ev['location_city'], ev['location_address'])})"
    return (
        f"*{ev['title'].upper()}*\n"
        f"{CATEGORIES.get(ev['category'], ev['category'])} · {ev['location_city']}\n"
        f"📅 {date_str}\n"
        f"{location_link}"
        f"{contact_line}"
        f"{organizer}\n\n"
        f"{description}\n\n"
        f"——————————————————\n\n"
        f"[🔔 Подписаться на напоминание]({remind_url})\n"
        f"[🌐 Страница события]({event_url})\n"
        f"[📅 Добавить в Google Календарь]({gcal_url})\n"
        f"⭐ Хочешь добавить своё событие? Напиши боту!"
    )

def make_year_keyboard(prefix: str) -> InlineKeyboardMarkup:
    now = datetime.now().year
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(str(y), callback_data=f"{prefix}:{y}")
        for y in range(now, now + 3)
    ]])

def make_month_keyboard(prefix: str) -> InlineKeyboardMarkup:
    months = ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(months[i+j], callback_data=f"{prefix}:{i+j+1}") for j in range(3)]
        for i in range(0, 12, 3)
    ])

def make_day_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for d in range(1, 32):
        row.append(InlineKeyboardButton(str(d), callback_data=f"{prefix}:{d}"))
        if len(row) == 7:
            rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def make_hour_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(0, 24):
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"{prefix}:{h}"))
        if len(row) == 6:
            rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def make_minute_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("00", callback_data=f"{prefix}:0"),
        InlineKeyboardButton("15", callback_data=f"{prefix}:15"),
        InlineKeyboardButton("30", callback_data=f"{prefix}:30"),
        InlineKeyboardButton("45", callback_data=f"{prefix}:45"),
    ]])

async def send_event_card(bot_or_message, chat_id, ev: dict, keyboard=None, is_reply=False):
    """Отправляет карточку события с фото если есть."""
    text  = event_card_text(ev)
    cover = ev.get("cover_image_url") or ev.get("cover_file_id")
    try:
        if cover:
            if is_reply:
                await bot_or_message.reply_photo(cover, caption=text, reply_markup=keyboard, parse_mode="Markdown")
            else:
                await bot_or_message.send_photo(chat_id, cover, caption=text, reply_markup=keyboard, parse_mode="Markdown")
            return
    except Exception:
        pass
    if is_reply:
        await bot_or_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await bot_or_message.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")


# ─── /start — онбординг с выбором роли (UC-09 + UC-04) ──────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    # Deep-link: /start event_123
    if ctx.args and ctx.args[0].startswith("event_"):
        event_id = ctx.args[0].split("_")[1]
        return await _show_event_deeplink(update, ctx, event_id)

    # Всегда показываем приветствие с выбором роли
    await update.message.reply_text(
        "👋 Привет! Я *NextQuest* — бот событий гик-сообщества Кипра.\n\nКто ты?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎲 Участник — ищу события",        callback_data="onboard:participant"),
            InlineKeyboardButton("🎪 Организатор — добавляю события", callback_data="onboard:organizer"),
        ]]),
        parse_mode="Markdown"
    )

async def handle_onboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    tg_id  = query.from_user.id

    if choice == "participant":
        # Participant button → always show participant menu, regardless of DB role
        await _show_main_menu(query.message, "participant")
    else:
        # Organizer button → check actual DB role
        db_user = get_user(tg_id)
        actual_role = db_user["role"] if db_user else "participant"
        if actual_role not in ("organizer", "moderator"):
            await query.message.reply_text(
                "🎪 Чтобы добавлять события, нужна верификация модератором.\n\n"
                "Отправь запрос командой /request\\_organizer",
                parse_mode="Markdown"
            )
            await _show_main_menu(query.message, "participant")
        else:
            await _show_main_menu(query.message, actual_role)

async def _show_main_menu(message, role: str):
    if role in ("organizer", "moderator"):
        await message.reply_text(
            "Меню организатора:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Добавить событие",   callback_data="menu:new_event")],
                [InlineKeyboardButton("📋 Мои события",        callback_data="menu:my_events")],
                [InlineKeyboardButton("📬 Обратная связь",     callback_data="menu:feedback")],
                [InlineKeyboardButton("🔔 Мои подписки",       callback_data="menu:my")],
            ])
        )
    else:
        await message.reply_text(
            "Меню:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗓 Ближайшие события",  callback_data="menu:events")],
                [InlineKeyboardButton("🔔 Мои подписки",       callback_data="menu:my")],
                [InlineKeyboardButton("📌 Подписаться на тему", callback_data="menu:subscribe")],
            ])
        )

async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    fake = query.message

    if action == "new_event":
        # Guard check — wizard entry point will do the real work.
        # This handler just blocks unverified users early.
        if not is_organizer(query.from_user.id):
            return await fake.reply_text("⛔ Нужна верификация организатора. Отправь /request_organizer")
        # Falls through to the ConversationHandler entry point below (menu:new_event)
        # Nothing to return here — the wizard entry point picks it up
    elif action == "my_events":
        await _show_my_events(fake, query.from_user.id, ctx)
    elif action == "feedback":
        await _show_feedback(fake, query.from_user.id)
    elif action == "events":
        await _cmd_events_inner(fake)
    elif action == "my":
        await _cmd_my_inner(fake, query.from_user.id)
    elif action == "subscribe":
        await _cmd_subscribe_inner(fake, query.from_user.id)


# ─── Deep-link для участника (UC-10) ────────────────────────

async def _show_event_deeplink(update: Update, ctx: ContextTypes.DEFAULT_TYPE, event_id: str):
    res = supabase.table("events").select("*").eq("id", event_id).execute()
    if not res.data:
        return await update.message.reply_text("❌ Событие не найдено.")
    ev = res.data[0]
    tg_id = update.effective_user.id

    # Проверяем уже подписан?
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отписаться", callback_data=f"unsub_ev:{existing.data[0]['id']}"),
        ]])
        return await send_event_card(update.message, None, ev, keyboard, is_reply=True)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔔 Подписаться на напоминание", callback_data=f"subev:{event_id}"),
    ]])
    await send_event_card(update.message, None, ev, keyboard, is_reply=True)


# ─── /request_organizer (UC-00) ─────────────────────────────

async def cmd_request_organizer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    if is_organizer(user.id):
        return await update.message.reply_text("✅ Ты уже организатор!")

    await update.message.reply_text("📬 Запрос отправлен модератору. Ожидай подтверждения.")
    await ctx.bot.send_message(
        MODERATOR_ID,
        f"📬 Запрос на роль организатора\n\n"
        f"👤 @{user.username or '—'} (ID: {user.id})\n"
        f"Имя: {user.full_name}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Добавить организатором", callback_data=f"add_org:{user.id}"),
            InlineKeyboardButton("❌ Отказать",               callback_data=f"deny_org:{user.id}"),
        ]])
    )

async def handle_org_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    action, tg_id = query.data.split(":")
    tg_id = int(tg_id)

    if action == "add_org":
        supabase.table("users").update({"role": "organizer"}).eq("tg_id", tg_id).execute()
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("✅ Пользователь добавлен как организатор.")
        try:
            await ctx.bot.send_message(
                tg_id,
                "🎉 Твой запрос одобрен! Теперь ты организатор NextQuest.\n\nИспользуй /new_event чтобы добавить событие."
            )
        except Exception:
            pass
    elif action == "deny_org":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("❌ Запрос отклонён.")
        try:
            await ctx.bot.send_message(tg_id, "❌ Твой запрос на роль организатора отклонён. Напиши модератору если есть вопросы.")
        except Exception:
            pass


# ─── /admin — скрытое меню модератора (UC раздел 3) ─────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return  # Не отвечаем — команда скрыта

    await update.message.reply_text(
        "👑 Панель модератора",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Очередь на апрув",      callback_data="admin:pending")],
            [InlineKeyboardButton("🗂 Управление событиями",   callback_data="admin:manage_events")],
            [InlineKeyboardButton("📊 Статистика",             callback_data="admin:stats")],
            [InlineKeyboardButton("➕ Добавить организатора",   callback_data="admin:add_org_prompt")],
        ])
    )

async def handle_admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    action = query.data.split(":")[1]
    if action == "pending":
        await _show_pending(query.message)
    elif action == "stats":
        await _show_stats(query.message)
    elif action == "add_org_prompt":
        await query.message.reply_text("Отправь: /add_organizer @username")
    elif action == "manage_events":
        await _show_mod_events(query.message)


async def _show_stats(message):
    published = supabase.table("events").select("id", count="exact").eq("status", "published").execute()
    pending   = supabase.table("events").select("id", count="exact").eq("status", "pending").execute()
    subs      = supabase.table("subscriptions").select("id", count="exact").execute()
    users_cnt = supabase.table("users").select("tg_id", count="exact").execute()
    orgs      = supabase.table("users").select("tg_id", count="exact").eq("role", "organizer").execute()

    # Статистика по категориям
    cat_lines = []
    for cat_id, label in CATEGORIES.items():
        cnt = supabase.table("events").select("id", count="exact").eq("category", cat_id).eq("status", "published").execute()
        if cnt.count:
            cat_lines.append(f"  {label}: {cnt.count}")

    await message.reply_text(
        f"📊 *NextQuest stats*\n\n"
        f"✅ Опубликовано: {published.count}\n"
        f"⏳ На апруве: {pending.count}\n"
        f"👥 Пользователей: {users_cnt.count}\n"
        f"🎪 Организаторов: {orgs.count}\n"
        f"🔔 Подписок: {subs.count}\n\n"
        f"По категориям:\n" + ("\n".join(cat_lines) or "  —"),
        parse_mode="Markdown"
    )

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return
    await _show_stats(update.message)


# ─── Управление событиями модератором ────────────────────────

async def _show_mod_events(message, offset: int = 0):
    """Показывает список всех published/pending событий с кнопками Edit и Delete."""
    res = supabase.table("events").select("*")\
          .in_("status", ["published", "pending", "cancelled"])\
          .order("date_start", desc=True)\
          .range(offset, offset + 4).execute()

    if not res.data:
        return await message.reply_text("Событий не найдено.")

    for ev in res.data:
        icon = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
        date = ev["date_start"][:10]
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Изменить", callback_data=f"mod_edit:{ev['id']}"),
            InlineKeyboardButton("🗑 Удалить",   callback_data=f"mod_delete:{ev['id']}"),
        ]])
        await message.reply_text(
            f"{icon} *{ev['title']}*\n"
            f"{CATEGORIES.get(ev['category'], ev['category'])} · {ev['location_city']} · {date}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    # Пагинация
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"mod_page:{offset - 5}"))
    if len(res.data) == 5:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"mod_page:{offset + 5}"))
    if nav_buttons:
        await message.reply_text("Навигация:", reply_markup=InlineKeyboardMarkup([nav_buttons]))


async def handle_mod_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    offset = int(query.data.split(":")[1])
    await _show_mod_events(query.message, offset)


# ─── Удаление события модератором ────────────────────────────

async def handle_mod_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Запрашивает подтверждение удаления события."""
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("id, title, status, organizer_tg_id").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text("❌ Событие не найдено.")

    await query.message.reply_text(
        f"⚠️ Удалить событие *{ev['title']}* (#{ev['id']}) из базы данных?\n\n"
        f"Это действие нельзя отменить. Событие исчезнет с сайта немедленно.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Да, удалить",  callback_data=f"mod_delete_confirm:{event_id}"),
            InlineKeyboardButton("❌ Отмена",        callback_data="mod_delete_cancel"),
        ]]),
        parse_mode="Markdown"
    )


async def handle_mod_delete_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Выполняет удаление события из Supabase — сайт обновится автоматически."""
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return

    if query.data == "mod_delete_cancel":
        return await query.message.reply_text("Отменено.")

    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text("❌ Событие не найдено.")

    title = ev["title"]

    # Уведомляем подписчиков об отмене перед удалением
    subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
    for s in subs.data:
        try:
            await ctx.bot.send_message(
                s["tg_id"],
                f"❌ Событие *{title}* было удалено модератором.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # Уведомляем организатора
    try:
        await ctx.bot.send_message(
            ev["organizer_tg_id"],
            f"❌ Твоё событие *{title}* было удалено модератором.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Удаляем подписки, логи и само событие из Supabase
    # (сайт на nextquest.today читает данные из Supabase — обновится автоматически)
    supabase.table("subscriptions").delete().eq("event_id", event_id).execute()
    supabase.table("notification_log").delete().eq("event_id", event_id).execute()
    supabase.table("events").delete().eq("id", event_id).execute()

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        f"✅ Событие *{title}* удалено.\n"
        f"Сайт nextquest.today обновлён автоматически.",
        parse_mode="Markdown"
    )
    logger.info(f"Moderator {query.from_user.id} deleted event {event_id} ({title})")


# ─── Редактирование события модератором ──────────────────────

async def handle_mod_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора поля для редактирования."""
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text("❌ Событие не найдено.")

    ctx.user_data["mod_editing_event_id"] = event_id

    await query.message.reply_text(
        f"✏️ Редактируем: *{ev['title']}*\n\nЧто изменить?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Название",     callback_data="mef:title"),
             InlineKeyboardButton("📄 Описание",     callback_data="mef:description")],
            [InlineKeyboardButton("📍 Город",        callback_data="mef:location_city"),
             InlineKeyboardButton("🏠 Адрес",        callback_data="mef:location_address")],
            [InlineKeyboardButton("🗓 Дата начала",  callback_data="mef:date_start"),
             InlineKeyboardButton("🗓 Дата конца",   callback_data="mef:date_end")],
            [InlineKeyboardButton("🎲 Категория",    callback_data="mef:category"),
             InlineKeyboardButton("👥 Лимит",        callback_data="mef:max_participants")],
            [InlineKeyboardButton("🔗 Ссылка рег.",  callback_data="mef:external_url"),
             InlineKeyboardButton("🖼 Обложка",      callback_data="mef:cover_image_url")],
            [InlineKeyboardButton("🎉 Формат",       callback_data="mef:format"),
             InlineKeyboardButton("❌ Отмена",        callback_data="mef:cancel")],
        ]),
        parse_mode="Markdown"
    )
    return MOD_EDIT_FIELD


FIELD_LABELS = {
    "title":            "Новое название:",
    "description":      "Новое описание:",
    "location_city":    "Новый город:",
    "location_address": "Новый адрес:",
    "date_start":       "Новая дата начала (YYYY-MM-DD HH:MM):",
    "date_end":         "Новая дата окончания (YYYY-MM-DD HH:MM) или `-` чтобы убрать:",
    "max_participants": "Новый лимит участников (число или `-` без лимита):",
    "external_url":     "Новая ссылка на регистрацию (или `-` чтобы убрать):",
    "cover_image_url":  "Новая ссылка на обложку (https://...) или отправь фото:",
    "category":         "Выбери категорию:",
    "format":           "Выбери формат:",
}


async def handle_mod_edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор поля и запрашивает новое значение."""
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]

    if field == "cancel":
        ctx.user_data.pop("mod_editing_event_id", None)
        ctx.user_data.pop("mod_editing_field", None)
        return await query.message.reply_text("Отменено.")

    ctx.user_data["mod_editing_field"] = field
    label = FIELD_LABELS.get(field, f"Новое значение для {field}:")

    if field == "category":
        buttons = [[InlineKeyboardButton(lbl, callback_data=f"mev:{cat_id}")]
                   for cat_id, lbl in CATEGORIES.items()]
        await query.message.reply_text(label, reply_markup=InlineKeyboardMarkup(buttons))
        return MOD_EDIT_VALUE

    if field == "format":
        buttons = [[
            InlineKeyboardButton("🎉 Official", callback_data="mev:official"),
            InlineKeyboardButton("🔒 Private",  callback_data="mev:private"),
        ]]
        await query.message.reply_text(label, reply_markup=InlineKeyboardMarkup(buttons))
        return MOD_EDIT_VALUE

    await query.message.reply_text(label, parse_mode="Markdown")
    return MOD_EDIT_VALUE


async def handle_mod_edit_value_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор категории или формата через кнопку."""
    query = update.callback_query
    await query.answer()
    new_value = query.data.split(":")[1]
    field = ctx.user_data.get("mod_editing_field", "category")
    await _apply_mod_edit(ctx, field, new_value, query.message)
    return ConversationHandler.END


async def handle_mod_edit_value_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод нового значения поля."""
    field = ctx.user_data.get("mod_editing_field")
    event_id = ctx.user_data.get("mod_editing_event_id")
    if not field or not event_id:
        return ConversationHandler.END

    raw = update.message.text.strip() if update.message.text else None

    # Фото для обложки
    if field == "cover_image_url" and update.message.photo:
        file = await update.message.photo[-1].get_file()
        file_bytes = await file.download_as_bytearray()
        filename = f"covers/{update.effective_user.id}_{int(datetime.now().timestamp())}.jpg"
        supabase.storage.from_("event-covers").upload(
            filename, bytes(file_bytes), {"content-type": "image/jpeg"}
        )
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/event-covers/{filename}"
        ctx.user_data["new_event"]["cover_image_url"] = public_url

    if raw is None:
        await update.message.reply_text("❌ Ожидается текст или фото.")
        return MOD_EDIT_VALUE

    # Нормализация значений
    if raw == "-":
        new_value = None
    elif field in ("date_start", "date_end"):
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            new_value = dt.isoformat()
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Используй: YYYY-MM-DD HH:MM")
            return MOD_EDIT_VALUE
    elif field == "max_participants":
        try:
            new_value = int(raw)
        except ValueError:
            await update.message.reply_text("❌ Введи число или `-`.")
            return MOD_EDIT_VALUE
    else:
        new_value = raw

    await _apply_mod_edit(ctx, field, new_value, update.message)
    return ConversationHandler.END


async def _apply_mod_edit(ctx, field: str, new_value, message):
    """Записывает изменение в Supabase и уведомляет подписчиков."""
    event_id = ctx.user_data.pop("mod_editing_event_id", None)
    ctx.user_data.pop("mod_editing_field", None)
    if not event_id:
        return await message.reply_text("❌ Сессия истекла.")

    update_data = {field: new_value}
    supabase.table("events").update(update_data).eq("id", event_id).execute()
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    display = new_value if new_value is not None else "убрано"
    await message.reply_text(
        f"✅ Поле *{field}* обновлено → `{display}`\n\n"
        f"Сайт nextquest.today обновлён автоматически.",
        parse_mode="Markdown"
    )

    # Уведомляем подписчиков об изменении
    subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
    for s in subs.data:
        try:
            await ctx.bot.send_message(
                s["tg_id"],
                f"📝 Детали события *{ev['title']}* изменились!\n\n{event_card_text(ev)}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # Уведомляем организатора
    try:
        await ctx.bot.send_message(
            ev["organizer_tg_id"],
            f"📝 Модератор изменил событие *{ev['title']}*.\n\nПоле: {field}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    logger.info(f"Moderator edited event {event_id}: {field} = {new_value}")


# ─── Модерация (UC-01) ───────────────────────────────────────

async def _show_pending(message):
    res = supabase.table("events").select("*").eq("status", "pending").order("created_at").execute()
    if not res.data:
        return await message.reply_text("✅ Очередь пуста.")

    for ev in res.data:
        # Таймер до автоапрува
        created = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
        auto_at = created + timedelta(hours=48)
        hours_left = max(0, int((auto_at - datetime.now(timezone.utc)).total_seconds() / 3600))

        # Бейдж нового организатора
        org_events = supabase.table("events").select("id", count="exact").eq("organizer_tg_id", ev["organizer_tg_id"]).execute()
        new_badge = " 🆕 новый организатор" if org_events.count == 1 else ""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{ev['id']}"),
            InlineKeyboardButton("✏️ Правки",       callback_data=f"request_edits:{ev['id']}"),
            InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:{ev['id']}"),
        ]])
        header = f"[#{ev['id']}]{new_badge} ⏱ {hours_left}ч до автоапрува\n\n"
        cover = ev.get("cover_image_url") or ev.get("cover_file_id")
        try:
            if cover:
                await message.reply_photo(cover, caption=header + event_card_text(ev),
                                          reply_markup=keyboard, parse_mode="Markdown")
                continue
        except Exception:
            pass
        await message.reply_text(header + event_card_text(ev), reply_markup=keyboard, parse_mode="Markdown")

async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return
    await _show_pending(update.message)

async def handle_moderation_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts    = query.data.split(":")
    action   = parts[0]
    event_id = parts[1]

    if action == "approve":
        supabase.table("events").update({"status": "published"}).eq("id", event_id).execute()
        ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"✅ Событие #{event_id} опубликовано!")

        # Уведомление организатору (UC-09 уведомления)
        try:
            await ctx.bot.send_message(
                ev["organizer_tg_id"],
                f"🎉 Твоё событие *{ev['title']}* опубликовано!\n\n"
                f"🔗 {SITE_URL}/events/{event_id}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 Поделиться", callback_data=f"share:{event_id}"),
                ]]),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Cannot notify organizer: {e}")

        # Уведомление подписчикам категории
        subs = supabase.table("subscriptions").select("tg_id").eq("category", ev["category"]).execute()
        for s in subs.data:
            try:
                await ctx.bot.send_message(
                    s["tg_id"],
                    f"🔔 Новое событие в {CATEGORIES[ev['category']]}!\n\n{event_card_text(ev)}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔔 Подписаться на напоминание", callback_data=f"subev:{event_id}"),
                    ]]),
                    parse_mode="Markdown"
                )
                supabase.table("notification_log").insert({
                    "tg_id": s["tg_id"], "event_id": event_id, "type": "new_event"
                }).execute()
            except Exception:
                pass

    elif action in ("reject", "request_edits"):
        ctx.user_data["mod_action"]   = action
        ctx.user_data["mod_event_id"] = event_id
        # Показываем список готовых причин
        buttons = [[InlineKeyboardButton(r, callback_data=f"reason:{i}")]
                   for i, r in enumerate(REJECT_REASONS)]
        await query.message.reply_text(
            "Выбери причину:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

async def handle_reject_reason_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx    = int(query.data.split(":")[1])
    reason = REJECT_REASONS[idx]

    if reason.startswith("✏️"):
        ctx.user_data["awaiting_custom_reason"] = True
        await query.message.reply_text("Напиши свою причину:")
        return REJECT_CUSTOM

    await _apply_moderation_decision(ctx, reason, query.message, query.from_user.id)

async def handle_custom_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_custom_reason"):
        return
    ctx.user_data.pop("awaiting_custom_reason")
    await _apply_moderation_decision(ctx, update.message.text, update.message, update.effective_user.id)
    return ConversationHandler.END

async def _apply_moderation_decision(ctx, reason: str, message, mod_id: int):
    action   = ctx.user_data.pop("mod_action", "reject")
    event_id = ctx.user_data.pop("mod_event_id", None)
    if not event_id:
        return

    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    if action == "reject":
        supabase.table("events").update({"reject_reason": reason}).eq("id", event_id).execute()
        await message.reply_text(f"❌ Событие #{event_id} отклонено.")
        notify_text = (
            f"❌ Твоё событие *{ev['title']}* отклонено.\n\n"
            f"Причина: {reason}"
        )
        button_text = "✏️ Создать заново"
    else:  # request_edits
        supabase.table("events").update({"reject_reason": f"[Правки] {reason}"}).eq("id", event_id).execute()
        await message.reply_text(f"✏️ Запрошены правки для #{event_id}.")
        notify_text = (
            f"✏️ По событию *{ev['title']}* запрошены правки.\n\n"
            f"Комментарий: {reason}"
        )
        button_text = "✏️ Исправить"

    try:
        await ctx.bot.send_message(
            ev["organizer_tg_id"],
            notify_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(button_text, callback_data="menu:new_event"),
            ]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Cannot notify organizer: {e}")


# ─── /add_organizer (UC-00, модератор) ──────────────────────

async def cmd_add_organizer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("Использование: /add_organizer @username")
    username = ctx.args[0].lstrip("@")
    res = supabase.table("users").select("*").eq("tg_username", username).execute()
    if not res.data:
        return await update.message.reply_text(f"❌ @{username} не найден. Пользователь должен написать /start сначала.")
    supabase.table("users").update({"role": "organizer"}).eq("tg_username", username).execute()
    await update.message.reply_text(f"✅ @{username} теперь организатор!")
    try:
        await ctx.bot.send_message(res.data[0]["tg_id"],
            "🎉 Тебе выдана роль организатора NextQuest!\n\nИспользуй /new_event чтобы добавить событие.")
    except Exception:
        pass


# ─── Wizard: новое событие (UC-04, 5 шагов) ─────────────────

async def wizard_start_from_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point for the new-event wizard triggered via the menu button."""
    query = update.callback_query
    await query.answer()
    if not is_organizer(query.from_user.id):
        await query.message.reply_text("⛔ Нужна верификация организатора. Отправь /request_organizer")
        return ConversationHandler.END

    ctx.user_data["new_event"] = {}
    ctx.user_data.pop("draft_id", None)

    # Check for existing draft
    user_id = query.from_user.id
    draft = supabase.table("events").select("*")\
            .eq("organizer_tg_id", user_id).eq("status", "draft")\
            .order("created_at", desc=True).limit(1).execute()
    if draft.data:
        ev = draft.data[0]
        await query.message.reply_text(
            f"У тебя есть незавершённый черновик: *{ev.get('title', '(без названия)')}*\n"
            f"Продолжить или начать заново?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("▶️ Продолжить",   callback_data=f"draft_continue:{ev['id']}"),
                InlineKeyboardButton("🗑 Начать заново", callback_data="draft_new"),
            ]]),
            parse_mode="Markdown"
        )
        return EV_CATEGORY

    return await _ask_category(query.message)

async def cmd_new_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    if not is_organizer(user.id):
        await update.message.reply_text(
            "⛔ Нужна верификация.\nОтправь /request\\_organizer чтобы запросить роль организатора.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    ctx.user_data["new_event"] = {}
    ctx.user_data.pop("draft_id", None)

    # Restore draft if exists
    draft = supabase.table("events").select("*")\
            .eq("organizer_tg_id", user.id).eq("status", "draft")\
            .order("created_at", desc=True).limit(1).execute()
    if draft.data:
        ev = draft.data[0]
        await update.message.reply_text(
            f"У тебя есть незавершённый черновик: *{ev.get('title', '(без названия)')}*\n"
            f"Продолжить или начать заново?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("▶️ Продолжить",   callback_data=f"draft_continue:{ev['id']}"),
                InlineKeyboardButton("🗑 Начать заново", callback_data="draft_new"),
            ]]),
            parse_mode="Markdown"
        )
        return EV_CATEGORY

    return await _ask_category(update.message)

async def handle_draft_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "draft_new":
        ctx.user_data["new_event"] = {}
        return await _ask_category(query.message)
    draft_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", draft_id).single().execute().data
    ctx.user_data["new_event"] = ev
    ctx.user_data["draft_id"]  = draft_id
    return await _ask_category(query.message)

async def _ask_category(message) -> int:
    buttons = [[InlineKeyboardButton(label, callback_data=f"cat:{cat_id}")]
               for cat_id, label in CATEGORIES.items()]
    await message.reply_text(
        "Шаг 1/5: *Категория события?*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CATEGORY

# Шаг 1 — категория
async def ev_get_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if "new_event" not in ctx.user_data:
        ctx.user_data["new_event"] = {}
    ctx.user_data["new_event"]["category"] = q.data.split(":")[1]
    ctx.user_data["new_event"]["organizer_tg_id"] = q.from_user.id
    await _save_draft(ctx)
    await q.message.reply_text(
        "Шаг 2/5: *Дата и время начала*\n\nВыбери год:",
        reply_markup=make_year_keyboard("sy"),
        parse_mode="Markdown"
    )
    return EV_YEAR

# Шаг 2 — дата (кнопки)
async def ev_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_sy"] = int(q.data.split(":")[1])
    await q.message.reply_text("Месяц?", reply_markup=make_month_keyboard("sm"))
    return EV_MONTH

async def ev_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_sm"] = int(q.data.split(":")[1])
    await q.message.reply_text("День?", reply_markup=make_day_keyboard("sd"))
    return EV_DAY

async def ev_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_sd"] = int(q.data.split(":")[1])
    await q.message.reply_text("Час начала?", reply_markup=make_hour_keyboard("sh"))
    return EV_HOUR

async def ev_hour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_sh"] = int(q.data.split(":")[1])
    await q.message.reply_text("Минуты?", reply_markup=make_minute_keyboard("smin"))
    return EV_MINUTE

async def ev_minute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    m  = int(q.data.split(":")[1])
    d  = ctx.user_data
    dt = datetime(d["_sy"], d["_sm"], d["_sd"], d["_sh"], m)
    ctx.user_data["new_event"]["date_start"] = dt.isoformat()
    await _save_draft(ctx)
    await q.message.reply_text(
        f"Начало: *{dt.strftime('%d %b %Y %H:%M')}* ✓\n\nМногодневное событие?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да", callback_data="end:yes"),
            InlineKeyboardButton("Нет", callback_data="end:no"),
        ]]),
        parse_mode="Markdown"
    )
    return EV_END_CHOICE

async def ev_end_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "end:no":
        return await _ask_city(q.message, ctx)
    await q.message.reply_text("Год окончания?", reply_markup=make_year_keyboard("ey"))
    return EV_END_YEAR

async def ev_end_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_ey"] = int(q.data.split(":")[1])
    await q.message.reply_text("Месяц окончания?", reply_markup=make_month_keyboard("em"))
    return EV_END_MONTH

async def ev_end_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_em"] = int(q.data.split(":")[1])
    await q.message.reply_text("День окончания?", reply_markup=make_day_keyboard("ed"))
    return EV_END_DAY

async def ev_end_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_ed"] = int(q.data.split(":")[1])
    await q.message.reply_text("Час окончания?", reply_markup=make_hour_keyboard("eh"))
    return EV_END_HOUR

async def ev_end_hour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["_eh"] = int(q.data.split(":")[1])
    await q.message.reply_text("Минуты окончания?", reply_markup=make_minute_keyboard("emin"))
    return EV_END_MINUTE

async def ev_end_minute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    m  = int(q.data.split(":")[1])
    d  = ctx.user_data
    dt = datetime(d["_ey"], d["_em"], d["_ed"], d["_eh"], m)
    ctx.user_data["new_event"]["date_end"] = dt.isoformat()
    return await _ask_city(q.message, ctx)

# Шаг 3 — детали (город, адрес, лимит)
async def _ask_city(message, ctx):
    buttons = [[InlineKeyboardButton(c, callback_data=f"city:{c}")]
               for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
    await message.reply_text(
        "Шаг 3/5: *Город?*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CITY

async def ev_get_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["new_event"]["location_city"] = q.data.split(":")[1]
    await q.message.reply_text("Адрес? (улица, заведение)", parse_mode="Markdown")
    return EV_ADDRESS

async def ev_get_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["location_address"] = update.message.text
    await update.message.reply_text(
        "Лимит участников?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("10",          callback_data="limit:10"),
            InlineKeyboardButton("20",          callback_data="limit:20"),
            InlineKeyboardButton("50",          callback_data="limit:50"),
            InlineKeyboardButton("Без лимита",  callback_data="limit:0"),
        ]])
    )
    return EV_LIMIT

async def ev_get_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    val = int(q.data.split(":")[1])
    if val > 0:
        ctx.user_data["new_event"]["max_participants"] = val
    await _save_draft(ctx)
    await q.message.reply_text(
        "Формат события?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎉 Official — публичное мероприятие", callback_data="fmt:official"),
            InlineKeyboardButton("🔒 Private — закрытая вечеринка",     callback_data="fmt:private"),
        ]])
    )
    return EV_FORMAT

async def ev_get_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["new_event"]["format"] = q.data.split(":")[1]
    await _save_draft(ctx)
    await q.message.reply_text("Шаг 4/5: *Название события?*", parse_mode="Markdown")
    return EV_TITLE

# Шаг 4 — название, описание, фото
async def ev_get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["title"] = update.message.text
    await update.message.reply_text("Описание события:")
    return EV_DESC

async def ev_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["description"] = update.message.text
    await update.message.reply_text("Фото обложки — отправь картинку или ссылку (https://...):")
    return EV_PHOTO

async def ev_get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        file_bytes = await file.download_as_bytearray()
        filename = f"covers/{update.effective_user.id}_{int(datetime.now().timestamp())}.jpg"
        supabase.storage.from_("event-covers").upload(
            filename,
            bytes(file_bytes),
            {"content-type": "image/jpeg"}
        )
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/event-covers/{filename}"
        ctx.user_data["new_event"]["cover_image_url"] = public_url
    elif update.message.text and update.message.text.startswith("http"):
        ctx.user_data["new_event"]["cover_image_url"] = update.message.text.strip()
    else:
        await update.message.reply_text("❌ Нужна картинка или ссылка (https://...)")
        return EV_PHOTO

    await update.message.reply_text(
        "Есть ссылка на регистрацию?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да", callback_data="reg:yes"),
            InlineKeyboardButton("❌ Нет", callback_data="reg:no"),
        ]])
    )
    return EV_URL

async def ev_reg_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle Yes/No registration choice."""
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    if choice == "yes":
        ctx.user_data["_reg_mode"] = "url"
        await query.message.reply_text("Отправь ссылку на регистрацию:")
    else:
        ctx.user_data["_reg_mode"] = "contacts"
        await query.message.reply_text(
            "Как с тобой связаться для регистрации?\n"
            "Напиши @username, ссылку, телефон или любой текст:"
        )
    return EV_URL

async def ev_get_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle registration link or organizer contacts free-text input."""
    txt = update.message.text.strip()
    mode = ctx.user_data.pop("_reg_mode", "url")
    if mode == "url":
        ctx.user_data["new_event"]["external_url"] = txt
        ctx.user_data["new_event"].pop("organizer_contacts", None)
    else:
        ctx.user_data["new_event"]["organizer_contacts"] = txt
        ctx.user_data["new_event"].pop("external_url", None)

    ev = ctx.user_data["new_event"]
    ev["organizer_tg_id"] = update.effective_user.id
    await _save_draft(ctx)
    return await _show_preview(update.message, ev)

async def ev_submit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ev_cancel":
        if ctx.user_data.get("draft_id"):
            supabase.table("events").delete().eq("id", ctx.user_data["draft_id"]).execute()
        ctx.user_data.pop("new_event", None)
        ctx.user_data.pop("draft_id", None)
        await query.message.reply_text("❌ Создание события отменено.")
        return ConversationHandler.END

    if query.data == "ev_edit":
        # Show field picker — don't restart from scratch
        ev = ctx.user_data.get("new_event", {})
        if not ev:
            await query.message.reply_text("❌ Сессия истекла. Попробуй /new_event снова.")
            return ConversationHandler.END
        await query.message.reply_text(
            "✏️ Что хочешь исправить?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Название",    callback_data="evf:title"),
                 InlineKeyboardButton("📄 Описание",    callback_data="evf:description")],
                [InlineKeyboardButton("🎲 Категория",   callback_data="evf:category"),
                 InlineKeyboardButton("📍 Город",       callback_data="evf:location_city")],
                [InlineKeyboardButton("🏠 Адрес",       callback_data="evf:location_address"),
                 InlineKeyboardButton("👥 Лимит",       callback_data="evf:max_participants")],
                [InlineKeyboardButton("🗓 Дата начала", callback_data="evf:date_start"),
                 InlineKeyboardButton("🗓 Дата конца",  callback_data="evf:date_end")],
                [InlineKeyboardButton("🔗 Ссылка рег.", callback_data="evf:external_url"),
                 InlineKeyboardButton("📋 Контакт орг.", callback_data="evf:organizer_contacts")],
                [InlineKeyboardButton("🖼 Обложка",     callback_data="evf:cover_image_url")],
                [InlineKeyboardButton("🎉 Формат",      callback_data="evf:format"),
                 InlineKeyboardButton("✅ Всё верно — вернуться к превью", callback_data="evf:done")],
            ])
        )
        return EV_EDIT_FIELD

    # ev_submit — save and notify moderator
    ev = ctx.user_data.get("new_event", {})
    if not ev:
        await query.message.reply_text("❌ Сессия истекла. Попробуй /new_event снова.")
        return ConversationHandler.END

    draft_id = ctx.user_data.pop("draft_id", None)
    db_ev = {**_db_fields(ev), "status": "pending"}
    try:
        if draft_id:
            supabase.table("events").update(db_ev).eq("id", draft_id).execute()
            event_id = draft_id
        else:
            res = supabase.table("events").insert(db_ev).execute()
            event_id = res.data[0]["id"]
    except Exception as e:
        logger.error(f"Failed to save event to Supabase: {e}")
        await query.message.reply_text("❌ Ошибка сохранения. Попробуй ещё раз.")
        return ConversationHandler.END

    ctx.user_data.pop("new_event", None)
    await query.message.reply_text("✅ Событие отправлено на модерацию!")

    # Notify moderator
    ev_with_id = {**ev, "id": event_id}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{event_id}"),
        InlineKeyboardButton("✏️ Правки",       callback_data=f"request_edits:{event_id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:{event_id}"),
    ]])
    cover = ev.get("cover_file_id") or ev.get("cover_image_url")
    organizer = query.from_user
    org_name = f"@{organizer.username}" if organizer.username else organizer.full_name
    text = (
        f"📬 *Новое событие на апруве!*\n"
        f"От: {org_name} (ID: {organizer.id})\n\n"
        f"{event_card_text(ev_with_id)}"
    )
    try:
        if cover:
            await ctx.bot.send_photo(
                MODERATOR_ID, cover,
                caption=text, reply_markup=keyboard, parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                MODERATOR_ID, text,
                reply_markup=keyboard, parse_mode="Markdown"
            )
        logger.info(f"Moderator notification sent for event {event_id} to {MODERATOR_ID}")
    except Exception as e:
        logger.error(f"FAILED to notify moderator {MODERATOR_ID} for event {event_id}: {e}")

    return ConversationHandler.END


# ─── Inline preview edit (organizer corrects before submitting) ──

async def ev_edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle field selection in the preview edit picker."""
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]

    if field == "done":
        # Return to preview
        ev = ctx.user_data.get("new_event", {})
        if not ev:
            await query.message.reply_text("❌ Сессия истекла. Начни заново: /new_event")
            return ConversationHandler.END
        return await _show_preview(query.message, ev)

    ctx.user_data["ev_editing_field"] = field

    if field == "category":
        buttons = [[InlineKeyboardButton(lbl, callback_data=f"evv:{cat_id}")]
                   for cat_id, lbl in CATEGORIES.items()]
        await query.message.reply_text("Выбери категорию:", reply_markup=InlineKeyboardMarkup(buttons))
        return EV_EDIT_VALUE

    if field == "max_participants":
        await query.message.reply_text(
            "Новый лимит участников:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("10",         callback_data="evv:10"),
                InlineKeyboardButton("20",         callback_data="evv:20"),
                InlineKeyboardButton("50",         callback_data="evv:50"),
                InlineKeyboardButton("Без лимита", callback_data="evv:0"),
            ]])
        )
        return EV_EDIT_VALUE

    if field == "location_city":
        buttons = [[InlineKeyboardButton(c, callback_data=f"evv:{c}")]
                   for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
        await query.message.reply_text("Выбери город:", reply_markup=InlineKeyboardMarkup(buttons))
        return EV_EDIT_VALUE

    if field == "format":
        await query.message.reply_text(
            "Формат события?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎉 Official — публичное мероприятие", callback_data="evv:official"),
                InlineKeyboardButton("🔒 Private — закрытая вечеринка",     callback_data="evv:private"),
            ]])
        )
        return EV_EDIT_VALUE

    prompts = {
        "title":                "Новое название:",
        "description":          "Новое описание:",
        "location_address":     "Новый адрес:",
        "date_start":           "Новая дата начала (YYYY-MM-DD HH:MM):",
        "date_end":             "Новая дата конца (YYYY-MM-DD HH:MM) или `-` чтобы убрать:",
        "external_url":         "Новая ссылка на регистрацию (или `-` чтобы убрать):",
        "organizer_contacts":   "Контакт организатора (@username, ссылка, телефон) или `-` чтобы убрать:",
        "cover_image_url":      "Новая обложка — ссылка (https://...) или отправь фото:",
    }
    await query.message.reply_text(prompts.get(field, f"Новое значение для {field}:"))
    return EV_EDIT_VALUE


async def ev_edit_value_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle button-based field values (category, city, limit)."""
    query = update.callback_query
    await query.answer()
    field = ctx.user_data.get("ev_editing_field")
    raw   = query.data.split(":")[1]

    if field == "max_participants":
        val = int(raw)
        ctx.user_data["new_event"][field] = val if val > 0 else None
    elif field == "category":
        ctx.user_data["new_event"][field] = raw
    else:
        ctx.user_data["new_event"][field] = raw

    ctx.user_data.pop("ev_editing_field", None)
    ev = ctx.user_data["new_event"]
    await _save_draft(ctx)
    return await _show_preview(query.message, ev)


async def ev_edit_value_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text/photo field values."""
    field = ctx.user_data.get("ev_editing_field")
    if not field:
        return EV_EDIT_VALUE

    # Photo upload for cover
    if field == "cover_image_url" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        ctx.user_data["new_event"]["cover_image_url"] = file_id
        ctx.user_data["new_event"]["cover_file_id"]   = file_id
        ctx.user_data.pop("ev_editing_field", None)
        await _save_draft(ctx)
        return await _show_preview(update.message, ctx.user_data["new_event"])

    raw = update.message.text.strip() if update.message.text else None
    if raw is None:
        await update.message.reply_text("❌ Отправь текст или фото.")
        return EV_EDIT_VALUE

    if field in ("date_start", "date_end"):
        if raw == "-":
            ctx.user_data["new_event"][field] = None
        else:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
                ctx.user_data["new_event"][field] = dt.isoformat()
            except ValueError:
                await update.message.reply_text("❌ Формат: YYYY-MM-DD HH:MM (например 2026-06-15 18:00)")
                return EV_EDIT_VALUE
    elif raw == "-":
        ctx.user_data["new_event"][field] = None
    else:
        ctx.user_data["new_event"][field] = raw

    ctx.user_data.pop("ev_editing_field", None)
    await _save_draft(ctx)
    return await _show_preview(update.message, ctx.user_data["new_event"])


async def _show_preview(message, ev: dict):
    """Re-render the step-5 preview card with fresh data."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📤 Отправить на модерацию", callback_data="ev_submit"),
        InlineKeyboardButton("✏️ Исправить ещё",          callback_data="ev_edit"),
        InlineKeyboardButton("🗑 Отмена",                  callback_data="ev_cancel"),
    ]])
    caption = f"Шаг 5/5: *Превью* (обновлено)\n\n{event_card_text(ev)}\n\nВсё верно?"
    cover = ev.get("cover_file_id") or ev.get("cover_image_url")
    try:
        if cover:
            await message.reply_photo(cover, caption=caption, reply_markup=keyboard, parse_mode="Markdown")
            return EV_EDIT_FIELD
    except Exception:
        pass
    await message.reply_text(caption, reply_markup=keyboard, parse_mode="Markdown")
    return EV_EDIT_FIELD

# Known columns in the Supabase `events` table.
# Keys NOT in this set are internal bot state and must never be sent to the DB.
_EVENT_DB_COLUMNS = {
    "title", "description", "category",
    "date_start", "date_end", "timezone",
    "cover_image_url",
    "location_city", "location_address", "location_lat", "location_lng",
    "organizer_tg_id", "status",
    "max_participants", "external_url", "organizer_contacts",
    "reject_reason", "format",
}

def _db_fields(ev: dict) -> dict:
    """Return only the keys that belong to the Supabase events table."""
    return {k: v for k, v in ev.items() if k in _EVENT_DB_COLUMNS}


async def _save_draft(ctx):
    """Сохраняет или обновляет черновик в БД."""
    ev = ctx.user_data.get("new_event", {})
    if not ev.get("organizer_tg_id"):
        return
    draft_id = ctx.user_data.get("draft_id")
    ev_data  = {**_db_fields(ev), "status": "draft"}
    if draft_id:
        supabase.table("events").update(ev_data).eq("id", draft_id).execute()
    else:
        try:
            res = supabase.table("events").insert(ev_data).execute()
            ctx.user_data["draft_id"] = res.data[0]["id"]
        except Exception as e:
            logger.warning(f"_save_draft insert failed: {e}")


# ─── Мои события (UC-05, UC-06) ─────────────────────────────

async def _show_my_events(message, tg_id: int, ctx):
    res = supabase.table("events").select("*")\
          .eq("organizer_tg_id", tg_id)\
          .neq("status", "draft")\
          .order("date_start", desc=True).limit(5).execute()
    if not res.data:
        return await message.reply_text("У тебя пока нет событий. /new_event чтобы добавить!")
    for ev in res.data:
        icon    = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
        reject  = f"\n⚠️ {ev['reject_reason']}" if ev.get("reject_reason") else ""
        subs_cnt = supabase.table("subscriptions").select("id", count="exact").eq("event_id", ev["id"]).execute()
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚫 Отменить", callback_data=f"cancel_ev:{ev['id']}"),
            InlineKeyboardButton("🔗 Поделиться", callback_data=f"share:{ev['id']}"),
        ]])
        await message.reply_text(
            f"{icon} *{ev['title']}* (#{ev['id']})\n"
            f"{ev['date_start'][:10]} · {ev['location_city']}\n"
            f"👥 {subs_cnt.count} подписчиков{reject}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def cmd_my_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_my_events(update.message, update.effective_user.id, ctx)

async def handle_organizer_event_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, event_id = query.data.split(":")
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if ev["organizer_tg_id"] != query.from_user.id and not is_moderator(query.from_user.id):
        return await query.message.reply_text("⛔ Это не твоё событие.")

    if action == "cancel_ev":
        ctx.user_data["cancel_event_id"] = event_id
        await query.message.reply_text(
            f"Отменяем *{ev['title']}*.\nУказать причину? (или отправь `-`)",
            parse_mode="Markdown"
        )
        ctx.user_data["awaiting_cancel_reason"] = True

async def handle_cancel_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_cancel_reason"):
        return
    ctx.user_data.pop("awaiting_cancel_reason")
    reason   = update.message.text.strip()
    event_id = ctx.user_data.pop("cancel_event_id")

    supabase.table("events").update({"status": "cancelled"}).eq("id", event_id).execute()
    await update.message.reply_text("🚫 Событие отменено.")

    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    reason_text = f"\n\nПричина: {reason}" if reason != "-" else ""
    subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
    for s in subs.data:
        try:
            await ctx.bot.send_message(
                s["tg_id"],
                f"❌ Событие *{ev['title']}* отменено.{reason_text}",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ─── Поделиться (UC-08) ──────────────────────────────────────

async def handle_share_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    share_text = event_share_text(ev)
    await query.message.reply_text(
        f"Готовый анонс для репоста:\n\n{share_text}\n\n"
        f"_Скопируй и отправь в свой Telegram-чат_",
        parse_mode="Markdown"
    )


# ─── Обратная связь (UC-07) ──────────────────────────────────

async def _show_feedback(message, tg_id: int):
    await message.reply_text(
        "📬 Обратная связь",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Статус события",       callback_data="fb:status"),
            InlineKeyboardButton("✉️ Написать модератору",   callback_data="fb:contact"),
        ]])
    )

async def handle_feedback_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "status":
        res = supabase.table("events").select("id, title, status")\
              .eq("organizer_tg_id", query.from_user.id)\
              .neq("status", "draft")\
              .order("created_at", desc=True).limit(5).execute()
        if not res.data:
            return await query.message.reply_text("У тебя нет событий.")
        buttons = [[InlineKeyboardButton(f"{ev['title'][:30]}", callback_data=f"ev_status:{ev['id']}")]
                   for ev in res.data]
        await query.message.reply_text("Выбери событие:", reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "contact":
        ctx.user_data["awaiting_mod_message"] = True
        await query.message.reply_text("Напиши сообщение модератору:")

async def handle_ev_status_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    subs = supabase.table("subscriptions").select("id", count="exact").eq("event_id", event_id).execute()
    icon = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
    await query.message.reply_text(
        f"{icon} *{ev['title']}*\n"
        f"Статус: {ev['status']}\n"
        f"👥 Подписчиков: {subs.count}\n"
        f"{'⚠️ ' + ev['reject_reason'] if ev.get('reject_reason') else ''}",
        parse_mode="Markdown"
    )

async def handle_mod_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_mod_message"):
        return False
    ctx.user_data.pop("awaiting_mod_message")
    user = update.effective_user
    await ctx.bot.send_message(
        MODERATOR_ID,
        f"✉️ Сообщение от @{user.username or '—'} (ID: {user.id}):\n\n{update.message.text}"
    )
    await update.message.reply_text("✅ Сообщение отправлено модератору.")
    return True


# ─── Просмотр событий (UC-09) ────────────────────────────────

async def _cmd_events_inner(message):
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("events").select("*")\
          .eq("status", "published").gte("date_start", now)\
          .order("date_start").limit(5).execute()
    if not res.data:
        return await message.reply_text("Ближайших событий пока нет.")
    for ev in res.data:
        date = ev["date_start"][:10]
        cat  = CATEGORIES.get(ev["category"], ev["category"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 Напомни мне",  callback_data=f"subev:{ev['id']}"),
            InlineKeyboardButton("🔗 Регистрация",  url=ev.get("external_url") or f"{SITE_URL}/events/{ev['id']}"),
        ]])
        await message.reply_text(
            f"{cat} *{ev['title']}*\n📍 {ev['location_city']} · 🗓 {date}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def cmd_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_events_inner(update.message)


# ─── Подписки (UC-10, UC-11, UC-12) ─────────────────────────

async def handle_subev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    tg_id    = query.from_user.id
    get_or_create_user(tg_id, query.from_user.username)

    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        return await query.answer("Уже подписан!", show_alert=True)

    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    await query.answer("🔔 Напоминание установлено!", show_alert=True)

    # Upsell на категорию (UC-10)
    ev = supabase.table("events").select("category").eq("id", event_id).single().execute().data
    cat_label = CATEGORIES.get(ev["category"], "")
    cat_sub   = supabase.table("subscriptions").select("id")\
                .eq("tg_id", tg_id).eq("category", ev["category"]).execute()
    if not cat_sub.data:
        await ctx.bot.send_message(
            tg_id,
            f"Хочешь получать все новые события {cat_label}?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Подписаться на {cat_label}", callback_data=f"subcat:{ev['category']}"),
                InlineKeyboardButton("Нет, спасибо", callback_data="subcat:skip"),
            ]])
        )

async def handle_unsub_ev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":")[1]
    supabase.table("subscriptions").delete().eq("id", sub_id).eq("tg_id", query.from_user.id).execute()
    await query.message.reply_text("✅ Отписка оформлена.")

async def _cmd_my_inner(message, tg_id: int):
    subs = supabase.table("subscriptions").select("*").eq("tg_id", tg_id).execute()
    if not subs.data:
        return await message.reply_text(
            "Подписок нет.\n/events — события\n/subscribe — подписаться на категории"
        )
    # Разделяем на события и категории
    event_subs = [s for s in subs.data if s.get("event_id")]
    cat_subs   = [s for s in subs.data if s.get("category")]
    lines, buttons = [], []

    if event_subs:
        lines.append("*На события:*")
        for s in event_subs:
            ev = supabase.table("events").select("title").eq("id", s["event_id"]).execute()
            name = ev.data[0]["title"] if ev.data else f"Событие #{s['event_id']}"
            lines.append(f"  🗓 {name}")
            buttons.append([InlineKeyboardButton(f"Отписаться: {name[:28]}", callback_data=f"unsub_ev:{s['id']}")])

    if cat_subs:
        lines.append("\n*На категории:*")
        for s in cat_subs:
            label = CATEGORIES.get(s["category"], s["category"])
            lines.append(f"  📌 {label}")
            buttons.append([InlineKeyboardButton(f"Отписаться: {label}", callback_data=f"unsub_ev:{s['id']}")])

    buttons.append([InlineKeyboardButton("+ Добавить категорию", callback_data="menu:subscribe")])
    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def cmd_my_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_my_inner(update.message, update.effective_user.id)

async def _cmd_subscribe_inner(message, tg_id: int):
    existing = supabase.table("subscriptions").select("category")\
               .eq("tg_id", tg_id).not_.is_("category", "null").execute()
    existing_cats = {s["category"] for s in existing.data}
    buttons = []
    for cat_id, label in CATEGORIES.items():
        check = "✅ " if cat_id in existing_cats else ""
        buttons.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"subcat:{cat_id}")])
    buttons.append([InlineKeyboardButton("Готово ✔", callback_data="subcat:done")])
    await message.reply_text("Выбери категории (нажми чтобы переключить):", reply_markup=InlineKeyboardMarkup(buttons))

async def cmd_subscribe_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_subscribe_inner(update.message, update.effective_user.id)

async def handle_subcat_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id  = query.from_user.id
    action = query.data.split(":")[1]

    if action in ("done", "skip"):
        return await query.message.reply_text("✅ Настройки сохранены!")

    cat      = action
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("category", cat).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
        await query.answer(f"Отписка от {CATEGORIES[cat]}", show_alert=False)
    else:
        get_or_create_user(tg_id, query.from_user.username)
        supabase.table("subscriptions").insert({"tg_id": tg_id, "category": cat}).execute()
        await query.answer(f"Подписка на {CATEGORIES[cat]}", show_alert=False)


# ─── Напоминания (UC-10: 7д и 1д) ───────────────────────────

async def job_send_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    """Запускается раз в час. Отправляет напоминания за 7 и 1 день."""
    now = datetime.now(timezone.utc)

    for days, notif_type, label in [
        (7, "reminder_7d", "за 7 дней"),
        (1, "reminder_1d", "завтра"),
    ]:
        window_start = now + timedelta(days=days) - timedelta(hours=1)
        window_end   = now + timedelta(days=days) + timedelta(hours=1)

        events = supabase.table("events").select("*")\
                 .eq("status", "published")\
                 .gte("date_start", window_start.isoformat())\
                 .lte("date_start", window_end.isoformat()).execute()

        for ev in events.data:
            subs = supabase.table("subscriptions").select("tg_id").eq("event_id", ev["id"]).execute()
            for s in subs.data:
                already = supabase.table("notification_log").select("id")\
                          .eq("tg_id", s["tg_id"]).eq("event_id", ev["id"]).eq("type", notif_type).execute()
                if already.data:
                    continue
                try:
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Не смогу прийти", callback_data=f"cant_come:{ev['id']}:{s['tg_id']}"),
                    ]])
                    await ctx.bot.send_message(
                        s["tg_id"],
                        f"🔔 Напоминание {label}!\n\n{event_card_text(ev)}\n\n📍 {ev['location_address']}",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                    supabase.table("notification_log").insert({
                        "tg_id": s["tg_id"], "event_id": ev["id"], "type": notif_type
                    }).execute()
                except Exception as e:
                    logger.warning(f"Reminder failed for {s['tg_id']}: {e}")

async def handle_cant_come(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts    = query.data.split(":")
    event_id = parts[1]
    tg_id    = query.from_user.id
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
    await query.message.reply_text("Понял, отписал тебя. Увидимся на другом событии! 👋")


# ─── Черновик: напоминание через 24ч ─────────────────────────

async def job_draft_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    """Напоминает организаторам о незавершённых черновиках."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    drafts = supabase.table("events").select("*")\
             .eq("status", "draft")\
             .lte("created_at", cutoff).execute()
    for ev in drafts.data:
        try:
            await ctx.bot.send_message(
                ev["organizer_tg_id"],
                f"📝 У тебя есть незавершённый черновик события!\n\n"
                f"Категория: {CATEGORIES.get(ev.get('category', ''), '—')}\n"
                f"Название: {ev.get('title', '(не указано)')}\n\n"
                "Продолжи или удали его через /new_event",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Продолжить", callback_data=f"draft_continue:{ev['id']}"),
                ]])
            )
        except Exception:
            pass


# ─── Общий обработчик текста ─────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Перехватывает свободный текст для разных состояний."""
    # Причина реджекта
    if ctx.user_data.get("awaiting_custom_reason"):
        ctx.user_data.pop("awaiting_custom_reason")
        await _apply_moderation_decision(ctx, update.message.text, update.message, update.effective_user.id)
        return
    # Сообщение модератору
    if await handle_mod_message(update, ctx):
        return
    # Причина отмены события
    if ctx.user_data.get("awaiting_cancel_reason"):
        await handle_cancel_reason(update, ctx)


# ─── App setup ───────────────────────────────────────────────

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    wizard = ConversationHandler(
        entry_points=[
            CommandHandler("new_event", cmd_new_event),
            CallbackQueryHandler(wizard_start_from_menu, pattern="^menu:new_event$"),
            CallbackQueryHandler(handle_draft_choice,    pattern="^draft_(continue|new)"),
        ],
        states={
            EV_CATEGORY:   [CallbackQueryHandler(ev_get_category, pattern="^cat:")],
            EV_YEAR:       [CallbackQueryHandler(ev_year,          pattern="^sy:")],
            EV_MONTH:      [CallbackQueryHandler(ev_month,         pattern="^sm:")],
            EV_DAY:        [CallbackQueryHandler(ev_day,           pattern="^sd:")],
            EV_HOUR:       [CallbackQueryHandler(ev_hour,          pattern="^sh:")],
            EV_MINUTE:     [CallbackQueryHandler(ev_minute,        pattern="^smin:")],
            EV_END_CHOICE: [CallbackQueryHandler(ev_end_choice,    pattern="^end:")],
            EV_END_YEAR:   [CallbackQueryHandler(ev_end_year,      pattern="^ey:")],
            EV_END_MONTH:  [CallbackQueryHandler(ev_end_month,     pattern="^em:")],
            EV_END_DAY:    [CallbackQueryHandler(ev_end_day,       pattern="^ed:")],
            EV_END_HOUR:   [CallbackQueryHandler(ev_end_hour,      pattern="^eh:")],
            EV_END_MINUTE: [CallbackQueryHandler(ev_end_minute,    pattern="^emin:")],
            EV_CITY:       [CallbackQueryHandler(ev_get_city,      pattern="^city:")],
            EV_ADDRESS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_address)],
            EV_LIMIT:      [CallbackQueryHandler(ev_get_limit,     pattern="^limit:")],
            EV_FORMAT:     [CallbackQueryHandler(ev_get_format,    pattern="^fmt:")],
            EV_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_title)],
            EV_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_desc)],
            EV_PHOTO:      [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ev_get_photo)],
            EV_URL:        [CallbackQueryHandler(ev_reg_choice, pattern="^reg:"),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_url)],
            # Preview stage — submit / edit / cancel
            ConversationHandler.END: [
                CallbackQueryHandler(ev_submit_callback, pattern="^ev_(submit|cancel|edit)$"),
            ],
            # Inline field picker
            EV_EDIT_FIELD: [
                CallbackQueryHandler(ev_submit_callback,    pattern="^ev_(submit|cancel|edit)$"),
                CallbackQueryHandler(ev_edit_field,         pattern="^evf:"),
            ],
            EV_EDIT_VALUE: [
                CallbackQueryHandler(ev_edit_value_callback, pattern="^evv:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ev_edit_value_text),
                MessageHandler(filters.PHOTO,                   ev_edit_value_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (
            u.message.reply_text("Отменено. Черновик сохранён — продолжи через /new_event"),
            ConversationHandler.END
        ))],
        allow_reentry=True,
    )

    # Moderator edit wizard
    mod_edit_wizard = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_mod_edit, pattern="^mod_edit:"),
        ],
        states={
            MOD_EDIT_FIELD: [
                CallbackQueryHandler(handle_mod_edit_field, pattern="^mef:"),
            ],
            MOD_EDIT_VALUE: [
                CallbackQueryHandler(handle_mod_edit_value_callback, pattern="^mev:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mod_edit_value_text),
                MessageHandler(filters.PHOTO, handle_mod_edit_value_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (
            u.message.reply_text("Редактирование отменено."),
            ConversationHandler.END
        ))],
        allow_reentry=True,
    )

    app.add_handler(wizard)
    app.add_handler(mod_edit_wizard)

    # Команды
    app.add_handler(CommandHandler("start",              cmd_start))
    app.add_handler(CommandHandler("admin",              cmd_admin))
    app.add_handler(CommandHandler("stats",              cmd_stats))
    app.add_handler(CommandHandler("pending",            cmd_pending))
    app.add_handler(CommandHandler("add_organizer",      cmd_add_organizer))
    app.add_handler(CommandHandler("request_organizer",  cmd_request_organizer))
    app.add_handler(CommandHandler("my_events",          cmd_my_events))
    app.add_handler(CommandHandler("events",             cmd_events))
    app.add_handler(CommandHandler("my",                 cmd_my_subscriptions))
    app.add_handler(CommandHandler("subscribe",          cmd_subscribe_categories))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_onboard,                    pattern="^onboard:"))
    app.add_handler(CallbackQueryHandler(handle_menu, pattern="^menu:(?!new_event)"))
    app.add_handler(CallbackQueryHandler(handle_admin_menu,                 pattern="^admin:"))
    app.add_handler(CallbackQueryHandler(handle_moderation_callback,        pattern="^(approve|reject|request_edits):"))
    app.add_handler(CallbackQueryHandler(handle_reject_reason_button,       pattern="^reason:"))
    app.add_handler(CallbackQueryHandler(handle_org_request,                pattern="^(add_org|deny_org):"))
    app.add_handler(CallbackQueryHandler(handle_organizer_event_callback,   pattern="^cancel_ev:"))
    app.add_handler(CallbackQueryHandler(handle_share_callback,             pattern="^share:"))
    app.add_handler(CallbackQueryHandler(handle_feedback_callback,          pattern="^fb:"))
    app.add_handler(CallbackQueryHandler(handle_ev_status_callback,         pattern="^ev_status:"))
    app.add_handler(CallbackQueryHandler(handle_subev_callback,             pattern="^subev:"))
    app.add_handler(CallbackQueryHandler(handle_unsub_ev_callback,          pattern="^unsub_ev:"))
    app.add_handler(CallbackQueryHandler(handle_subcat_callback,            pattern="^subcat:"))
    app.add_handler(CallbackQueryHandler(handle_cant_come,                  pattern="^cant_come:"))
    # Moderator manage-events callbacks
    app.add_handler(CallbackQueryHandler(handle_mod_page,                   pattern="^mod_page:"))
    app.add_handler(CallbackQueryHandler(handle_mod_delete,                 pattern="^mod_delete:"))
    app.add_handler(CallbackQueryHandler(handle_mod_delete_confirm,         pattern="^mod_delete_(confirm|cancel)"))

    # Свободный текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Cron-задачи
    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(job_send_reminders,  interval=3600, first=60)   # каждый час
    job_queue.run_repeating(job_draft_reminders, interval=3600, first=120)  # каждый час

    return app


if __name__ == "__main__":
    application = build_application()
    logger.info("NextQuest bot v0.5 started.")
    application.run_polling()
