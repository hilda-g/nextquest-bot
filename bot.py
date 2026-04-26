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
from locales import s, LANG_PICKER_KEYBOARD, cat_label

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, JobQueue
)
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Translation helper ───────────────────────────────────────
import urllib.request
import urllib.parse
import json as _json

def translate_description(text: str) -> dict:
    """
    Translate event description into RU, EL, UK using Google Translate free endpoint.
    Returns dict with keys: description_ru, description_el, description_uk.
    Falls back to original text if a translation fails.
    """
    results = {}
    for lang_code, col in [("ru", "description_ru"), ("el", "description_el"), ("uk", "description_uk")]:
        try:
            url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl=auto&tl={lang_code}&dt=t&q={urllib.parse.quote(text)}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode())
            translated = "".join(chunk[0] for chunk in data[0] if chunk[0])
            results[col] = translated
        except Exception as e:
            logger.warning(f"Translation to {lang_code} failed: {e}")
            results[col] = text   # fallback: keep original
    return results

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
    # Custom limit input
    EV_LIMIT_CUSTOM,
) = range(26)


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

def get_user_lang(tg_id: int) -> str:
    u = get_user(tg_id)
    if u and u.get("language") in ("en", "ru", "el", "uk"):
        return u["language"]
    return "ru"

def set_user_lang(tg_id: int, lang: str):
    supabase.table("users").update({"language": lang}).eq("tg_id", tg_id).execute()


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

def event_card_text(ev: dict, lang: str = "ru") -> str:
    date_str   = format_date_ru(ev["date_start"])
    end_str    = f" – {ev['date_end'][11:16]}" if ev.get("date_end") else ""
    limit      = f"{ev['max_participants']} {s(lang, 'card_spots')}" if ev.get("max_participants") else s(lang, "card_no_limit")
    fmt_label  = FORMATS.get(ev.get("format", "official"), "🎉 Official")
    reg_line   = f"\n{s(lang, 'card_organizer_reg', url=ev['external_url'])}" if ev.get("external_url") else ""
    contact_line = f"\n{s(lang, 'card_organizer_contact', contact=ev['organizer_contacts'])}" if ev.get("organizer_contacts") and not ev.get("external_url") else ""
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
        f"[{s(lang, 'card_subscribe_reminder')}]({remind_url})\n"
        f"[{s(lang, 'card_event_page')}]({event_url})\n"
        f"[{s(lang, 'card_add_to_calendar')}]({gcal_url})\n"
        f"{s(lang, 'card_add_your_event')}"
    )

def event_share_text(ev: dict, lang: str = "ru") -> str:
    date_str   = format_date_ru(ev["date_start"])
    gcal_url   = build_google_calendar_url(ev)
    event_url  = f"{SITE_URL}/events/{ev['id']}"
    remind_url = f"t.me/{BOT_USERNAME}?start=event_{ev['id']}"
    organizer  = f"\n{s(lang, 'card_organizer_reg', url=ev['external_url'])}" if ev.get("external_url") else ""
    contact_line = f"\n{s(lang, 'card_organizer_contact', contact=ev['organizer_contacts'])}" if ev.get("organizer_contacts") and not ev.get("external_url") else ""
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
        f"[{s(lang, 'card_subscribe_reminder')}]({remind_url})\n"
        f"[{s(lang, 'card_event_page')}]({event_url})\n"
        f"[{s(lang, 'card_add_to_calendar')}]({gcal_url})\n"
        f"{s(lang, 'card_add_your_event')}"
    )

def make_year_keyboard(prefix: str) -> InlineKeyboardMarkup:
    now = datetime.now().year
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(str(y), callback_data=f"{prefix}:{y}")
        for y in range(now, now + 3)
    ]])

def make_month_keyboard(prefix: str, lang: str = "ru") -> InlineKeyboardMarkup:
    months_map = {
        "en": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
        "ru": ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"],
        "el": ["Ιαν","Φεβ","Μαρ","Απρ","Μαι","Ιουν","Ιουλ","Αυγ","Σεπ","Οκτ","Νοε","Δεκ"],
        "uk": ["Січ","Лют","Бер","Кві","Тра","Чер","Лип","Сер","Вер","Жов","Лис","Гру"],
    }
    months = months_map.get(lang, months_map["ru"])
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
    text  = event_card_text(ev, get_user_lang(chat_id) if isinstance(chat_id, int) else "ru")
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


# ─── /start — language pick → role pick ─────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    # Deep-link: /start event_123 — skip lang picker, go straight to event
    if ctx.args and ctx.args[0].startswith("event_"):
        event_id = ctx.args[0].split("_")[1]
        return await _show_event_deeplink(update, ctx, event_id)

    # Always show language picker first
    ctx.user_data["lang_picker_from_start"] = True
    await update.message.reply_text(
        "👋 *NextQuest* — geek events in Cyprus / события на Кипре\n\n🌐 Choose your language:",
        reply_markup=LANG_PICKER_KEYBOARD,
        parse_mode="Markdown"
    )

async def handle_setlang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User picked a language — save it.
    If coming from /start (ctx.user_data has 'from_start'), show role picker.
    If coming from /settings, just confirm the change.
    """
    query = update.callback_query
    await query.answer()
    lang  = query.data.split(":")[1]
    tg_id = query.from_user.id
    set_user_lang(tg_id, lang)

    # Decide context: from_start flag set by cmd_start, absent when from /settings
    from_start = ctx.user_data.pop("lang_picker_from_start", False)
    if from_start:
        await query.message.reply_text(
            s(lang, "welcome"),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(s(lang, "btn_participant"), callback_data="onboard:participant"),
                InlineKeyboardButton(s(lang, "btn_organizer"),  callback_data="onboard:organizer"),
            ]]),
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text(s(lang, "lang_changed"))

async def handle_onboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    tg_id  = query.from_user.id
    lang   = get_user_lang(tg_id)

    if choice == "participant":
        await _show_main_menu(query.message, "participant", lang)
    else:
        db_user     = get_user(tg_id)
        actual_role = db_user["role"] if db_user else "participant"
        if actual_role not in ("organizer", "moderator"):
            await query.message.reply_text(
                s(lang, "no_org_role"),
                parse_mode="Markdown"
            )
            await _show_main_menu(query.message, "participant", lang)
        else:
            await _show_main_menu(query.message, actual_role, lang)

async def _show_main_menu(message, role: str, lang: str = "ru"):
    if role in ("organizer", "moderator"):
        await message.reply_text(
            s(lang, "menu_organizer"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(s(lang, "btn_new_event"),  callback_data="menu:new_event")],
                [InlineKeyboardButton(s(lang, "btn_my_events"),  callback_data="menu:my_events")],
                [InlineKeyboardButton(s(lang, "btn_feedback"),   callback_data="menu:feedback")],
            ])
        )
    else:
        await message.reply_text(
            s(lang, "menu_participant"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(s(lang, "btn_upcoming"),  callback_data="menu:events")],
                [InlineKeyboardButton(s(lang, "btn_my_subs"),   callback_data="menu:my")],
                [InlineKeyboardButton(s(lang, "btn_subscribe"), callback_data="menu:subscribe")],
            ])
        )

async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    fake = query.message

    if action == "new_event":
        # Guard check — wizard entry point will do the real work.
        # This handler just blocks unverified users early.
        if not is_organizer(query.from_user.id):
            return await fake.reply_text(s(lang, "need_verification"))
        # Falls through to the ConversationHandler entry point below (menu:new_event)
        # Nothing to return here — the wizard entry point picks it up
    elif action == "my_events":
        await _show_my_events(fake, query.from_user.id, ctx)
    elif action == "feedback":
        await _show_feedback(fake, query.from_user.id)
    elif action == "events":
        await _cmd_events_inner(fake, get_user_lang(query.from_user.id))
    elif action == "my":
        await _cmd_my_inner(fake, query.from_user.id)
    elif action == "subscribe":
        await _cmd_subscribe_inner(fake, query.from_user.id)


# ─── Deep-link для участника (UC-10) ────────────────────────

async def _show_event_deeplink(update: Update, ctx: ContextTypes.DEFAULT_TYPE, event_id: str):
    lang = get_user_lang(update.effective_user.id)
    res = supabase.table("events").select("*").eq("id", event_id).execute()
    if not res.data:
        return await update.message.reply_text(s(lang, "event_not_found"))
    ev = res.data[0]
    tg_id = update.effective_user.id

    # Проверяем уже подписан?
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_unsubscribe"), callback_data=f"unsub_ev:{existing.data[0]['id']}"),
        ]])
        return await send_event_card(update.message, None, ev, keyboard, is_reply=True)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(s(lang, "card_subscribe_reminder"), callback_data=f"subev:{event_id}"),
    ]])
    await send_event_card(update.message, None, ev, keyboard, is_reply=True)


# ─── /settings ───────────────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    lang  = get_user_lang(tg_id)
    await update.message.reply_text(
        s(lang, "settings_title"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "settings_lang"), callback_data="settings:lang"),
        ]])
    )

async def handle_settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    if action == "lang":
        await query.message.reply_text(
            "🌐 Choose your language:",
            reply_markup=LANG_PICKER_KEYBOARD
        )


# ─── /request_organizer (UC-00) ─────────────────────────────

async def cmd_request_organizer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    if is_organizer(user.id):
        return await update.message.reply_text(s(lang, "already_organizer"))

    await update.message.reply_text(s(lang, "org_request_sent"))
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
                s(get_user_lang(tg_id), "org_request_approved")
            )
        except Exception:
            pass
    elif action == "deny_org":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("❌ Запрос отклонён.")
        try:
            await ctx.bot.send_message(tg_id, s(get_user_lang(tg_id), "org_request_denied"))
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
        await query.message.reply_text("Usage: /add_organizer @username")
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
        return await message.reply_text("No events found.")

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
        await message.reply_text("Navigation:", reply_markup=InlineKeyboardMarkup([nav_buttons]))


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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("id, title, status, organizer_tg_id").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text(s(lang, "event_not_found"))

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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return

    if query.data == "mod_delete_cancel":
        return await query.message.reply_text(s(lang, "cancelled"))

    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text(s(lang, "event_not_found"))

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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    if not is_moderator(query.from_user.id):
        return
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if not ev:
        return await query.message.reply_text(s(lang, "event_not_found"))

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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]

    if field == "cancel":
        ctx.user_data.pop("mod_editing_event_id", None)
        ctx.user_data.pop("mod_editing_field", None)
        return await query.message.reply_text(s(lang, "cancelled"))

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
    lang = get_user_lang(update.effective_user.id)
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
        await update.message.reply_text(s(lang, "expect_text_or_photo"))
        return MOD_EDIT_VALUE

    # Нормализация значений
    if raw == "-":
        new_value = None
    elif field in ("date_start", "date_end"):
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            new_value = dt.isoformat()
        except ValueError:
            await update.message.reply_text(s(lang, "invalid_date_format"))
            return MOD_EDIT_VALUE
    elif field == "max_participants":
        try:
            new_value = int(raw)
        except ValueError:
            await update.message.reply_text(s(lang, "invalid_number"))
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
    # If description was edited, regenerate all translations
    if field == "description" and new_value:
        update_data.update(translate_description(new_value))
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
        return await message.reply_text("✅ Queue is empty.")

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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    parts    = query.data.split(":")
    action   = parts[0]
    event_id = parts[1]

    if action == "approve":
        # Fetch event first to get description for translation
        ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
        # Translate description and save together with status change
        translations = translate_description(ev.get("description", ""))
        supabase.table("events").update({"status": "published", **translations}).eq("id", event_id).execute()
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
                        InlineKeyboardButton(s(lang, "card_subscribe_reminder"), callback_data=f"subev:{event_id}"),
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
        await query.message.reply_text("Write your reason:")
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
        return await update.message.reply_text("Usage: /add_organizer @username")
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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    if not is_organizer(query.from_user.id):
        await query.message.reply_text(s(lang, "need_verification"))
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
            s(lang, "draft_found", title=ev.get('title', '(untitled)')),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(s(lang, "btn_continue_draft"), callback_data=f"draft_continue:{ev['id']}"),
                InlineKeyboardButton(s(lang, "btn_new_draft"),      callback_data="draft_new"),
            ]]),
            parse_mode="Markdown"
        )
        return EV_CATEGORY

    return await _ask_category(query.message, lang)

async def cmd_new_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
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
            s(lang, "draft_found", title=ev.get('title', '(untitled)')),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(s(lang, "btn_continue_draft"), callback_data=f"draft_continue:{ev['id']}"),
                InlineKeyboardButton(s(lang, "btn_new_draft"),      callback_data="draft_new"),
            ]]),
            parse_mode="Markdown"
        )
        return EV_CATEGORY

    return await _ask_category(update.message, lang)

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

async def _ask_category(message, lang: str = "ru") -> int:
    buttons = [[InlineKeyboardButton(cat_label(lang, cat_id), callback_data=f"cat:{cat_id}")]
               for cat_id in CATEGORIES]
    await message.reply_text(
        s(lang, "step_category"),
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
    ctx.user_data["new_event"]["organizer_username"] = q.from_user.username or str(q.from_user.id)
    await _save_draft(ctx)
    lang = get_user_lang(q.from_user.id)
    await q.message.reply_text(
        s(lang, "step_date_start"),
        reply_markup=make_year_keyboard("sy"),
        parse_mode="Markdown"
    )
    return EV_YEAR

# Шаг 2 — дата (кнопки)
async def ev_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_sy"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_month"), reply_markup=make_month_keyboard("sm", lang))
    return EV_MONTH

async def ev_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_sm"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_day"), reply_markup=make_day_keyboard("sd"))
    return EV_DAY

async def ev_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_sd"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_hour_start"), reply_markup=make_hour_keyboard("sh"))
    return EV_HOUR

async def ev_hour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_sh"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_minute"), reply_markup=make_minute_keyboard("smin"))
    return EV_MINUTE

async def ev_minute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = get_user_lang(q.from_user.id)
    m  = int(q.data.split(":")[1])
    d  = ctx.user_data
    dt = datetime(d["_sy"], d["_sm"], d["_sd"], d["_sh"], m)
    ctx.user_data["new_event"]["date_start"] = dt.isoformat()
    await _save_draft(ctx)
    lang = get_user_lang(q.from_user.id)
    await q.message.reply_text(
        s(lang, "start_confirmed", dt=dt.strftime('%d %b %Y %H:%M')),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_yes"), callback_data="end:yes"),
            InlineKeyboardButton(s(lang, "btn_no"),  callback_data="end:no"),
        ]]),
        parse_mode="Markdown"
    )
    return EV_END_CHOICE

async def ev_end_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    if q.data == "end:no":
        return await _ask_city(q.message, ctx, lang)
    await q.message.reply_text(s(lang, "ask_end_year"), reply_markup=make_year_keyboard("ey"))
    return EV_END_YEAR

async def ev_end_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_ey"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_end_month"), reply_markup=make_month_keyboard("em", lang))
    return EV_END_MONTH

async def ev_end_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_em"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_end_day"), reply_markup=make_day_keyboard("ed"))
    return EV_END_DAY

async def ev_end_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_ed"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_end_hour"), reply_markup=make_hour_keyboard("eh"))
    return EV_END_HOUR

async def ev_end_hour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["_eh"] = int(q.data.split(":")[1])
    await q.message.reply_text(s(lang, "ask_end_minute"), reply_markup=make_minute_keyboard("emin"))
    return EV_END_MINUTE

async def ev_end_minute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    m  = int(q.data.split(":")[1])
    d  = ctx.user_data
    dt = datetime(d["_ey"], d["_em"], d["_ed"], d["_eh"], m)
    ctx.user_data["new_event"]["date_end"] = dt.isoformat()
    return await _ask_city(q.message, ctx, lang)

# Шаг 3 — детали (город, адрес, лимит)
async def _ask_city(message, ctx, lang: str = "ru"):
    buttons = [[InlineKeyboardButton(c, callback_data=f"city:{c}")]
               for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
    await message.reply_text(
        s(lang, "step_city"),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CITY

async def ev_get_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["new_event"]["location_city"] = q.data.split(":")[1]
    await q.message.reply_text(s(lang, "ask_address"), parse_mode="Markdown")
    return EV_ADDRESS

async def ev_get_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    ctx.user_data["new_event"]["location_address"] = update.message.text
    await update.message.reply_text(
        s(lang, "ask_limit"),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("10",                        callback_data="limit:10"),
                InlineKeyboardButton("20",                        callback_data="limit:20"),
                InlineKeyboardButton("50",                        callback_data="limit:50"),
                InlineKeyboardButton(s(lang, "btn_no_limit"),     callback_data="limit:0"),
            ],
            [InlineKeyboardButton(s(lang, "btn_custom_limit"),    callback_data="limit:custom")],
        ])
    )
    return EV_LIMIT

async def ev_get_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    val_str = q.data.split(":")[1]
    if val_str == "custom":
        await q.message.reply_text(s(lang, "ask_custom_limit"))
        return EV_LIMIT_CUSTOM
    val = int(val_str)
    if val > 0:
        ctx.user_data["new_event"]["max_participants"] = val
    await _save_draft(ctx)
    await q.message.reply_text(
        s(lang, "ask_format"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_format_official"), callback_data="fmt:official"),
            InlineKeyboardButton(s(lang, "btn_format_private"),  callback_data="fmt:private"),
        ]])
    )
    return EV_FORMAT

async def ev_get_limit_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle free-text custom participant limit input."""
    lang = get_user_lang(update.effective_user.id)
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text(s(lang, "invalid_number"))
        return EV_LIMIT_CUSTOM
    ctx.user_data["new_event"]["max_participants"] = int(text)
    await _save_draft(ctx)
    await update.message.reply_text(
        s(lang, "ask_format"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_format_official"), callback_data="fmt:official"),
            InlineKeyboardButton(s(lang, "btn_format_private"),  callback_data="fmt:private"),
        ]])
    )
    return EV_FORMAT

async def ev_get_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    q = update.callback_query; await q.answer()
    ctx.user_data["new_event"]["format"] = q.data.split(":")[1]
    await _save_draft(ctx)
    await q.message.reply_text(s(lang, "step_title"), parse_mode="Markdown")
    return EV_TITLE

# Шаг 4 — название, описание, фото
async def ev_get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    ctx.user_data["new_event"]["title"] = update.message.text
    await update.message.reply_text(s(lang, "ask_description"))
    return EV_DESC

async def ev_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    ctx.user_data["new_event"]["description"] = update.message.text
    await update.message.reply_text(s(lang, "ask_photo"))
    return EV_PHOTO

async def ev_get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
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
        await update.message.reply_text(s(lang, "need_image_or_url"))
        return EV_PHOTO

    await update.message.reply_text(
        s(lang, "ask_has_reg_url"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_yes"), callback_data="reg:yes"),
            InlineKeyboardButton(s(lang, "btn_no"),  callback_data="reg:no"),
        ]])
    )
    return EV_URL

async def ev_reg_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle Yes/No registration choice."""
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    if choice == "yes":
        ctx.user_data["_reg_mode"] = "url"
        await query.message.reply_text(s(lang, "ask_reg_url"))
    else:
        ctx.user_data["_reg_mode"] = "contacts"
        await query.message.reply_text(s(lang, "ask_organizer_contacts"))
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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()

    if query.data == "ev_cancel":
        if ctx.user_data.get("draft_id"):
            supabase.table("events").delete().eq("id", ctx.user_data["draft_id"]).execute()
        ctx.user_data.pop("new_event", None)
        ctx.user_data.pop("draft_id", None)
        await query.message.reply_text(s(lang, "event_cancelled_creation"))
        return ConversationHandler.END

    if query.data == "ev_edit":
        # Show field picker — don't restart from scratch
        ev = ctx.user_data.get("new_event", {})
        if not ev:
            await query.message.reply_text(s(lang, "session_expired"))
            return ConversationHandler.END
        await query.message.reply_text(
            s(lang, "edit_what"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(s(lang, "ef_title"),        callback_data="evf:title"),
                 InlineKeyboardButton(s(lang, "ef_description"),  callback_data="evf:description")],
                [InlineKeyboardButton(s(lang, "ef_category"),     callback_data="evf:category"),
                 InlineKeyboardButton(s(lang, "ef_city"),         callback_data="evf:location_city")],
                [InlineKeyboardButton(s(lang, "ef_address"),      callback_data="evf:location_address"),
                 InlineKeyboardButton(s(lang, "ef_limit"),        callback_data="evf:max_participants")],
                [InlineKeyboardButton(s(lang, "ef_date_start"),   callback_data="evf:date_start"),
                 InlineKeyboardButton(s(lang, "ef_date_end"),     callback_data="evf:date_end")],
                [InlineKeyboardButton(s(lang, "ef_reg_url"),      callback_data="evf:external_url"),
                 InlineKeyboardButton(s(lang, "ef_contact"),      callback_data="evf:organizer_contacts")],
                [InlineKeyboardButton(s(lang, "ef_cover"),        callback_data="evf:cover_image_url")],
                [InlineKeyboardButton(s(lang, "ef_format"),       callback_data="evf:format"),
                 InlineKeyboardButton(s(lang, "edit_back_to_preview"), callback_data="evf:done")],
            ])
        )
        return EV_EDIT_FIELD

    # ev_submit — save and notify moderator
    ev = ctx.user_data.get("new_event", {})
    if not ev:
        await query.message.reply_text(s(lang, "session_expired"))
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
        await query.message.reply_text(s(lang, "save_error"))
        return ConversationHandler.END

    ctx.user_data.pop("new_event", None)
    await query.message.reply_text(s(lang, "event_submitted"))

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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]

    if field == "done":
        # Return to preview
        ev = ctx.user_data.get("new_event", {})
        if not ev:
            await query.message.reply_text(s(lang, "session_expired_restart"))
            return ConversationHandler.END
        return await _show_preview(query.message, ev)

    ctx.user_data["ev_editing_field"] = field

    if field == "category":
        buttons = [[InlineKeyboardButton(cat_label(lang, cat_id), callback_data=f"evv:{cat_id}")]
                   for cat_id in CATEGORIES]
        await query.message.reply_text(s(lang, "ask_select_category"), reply_markup=InlineKeyboardMarkup(buttons))
        return EV_EDIT_VALUE

    if field == "max_participants":
        await query.message.reply_text(
            s(lang, "ask_new_limit"),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("10",         callback_data="evv:10"),
                InlineKeyboardButton("20",         callback_data="evv:20"),
                InlineKeyboardButton("50",         callback_data="evv:50"),
                InlineKeyboardButton(s(lang, "btn_no_limit"), callback_data="evv:0"),
            ]])
        )
        return EV_EDIT_VALUE

    if field == "location_city":
        buttons = [[InlineKeyboardButton(c, callback_data=f"evv:{c}")]
                   for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
        await query.message.reply_text(s(lang, "ask_select_city"), reply_markup=InlineKeyboardMarkup(buttons))
        return EV_EDIT_VALUE

    if field == "format":
        await query.message.reply_text(
            s(lang, "ask_format"),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(s(lang, "btn_format_official"), callback_data="evv:official"),
                InlineKeyboardButton(s(lang, "btn_format_private"),  callback_data="evv:private"),
            ]])
        )
        return EV_EDIT_VALUE

    prompts = {
        "title":                s(lang, "prompts_title"),
        "description":          s(lang, "prompts_description"),
        "location_address":     s(lang, "prompts_location_address"),
        "date_start":           s(lang, "prompts_date_start"),
        "date_end":             s(lang, "prompts_date_end"),
        "external_url":         s(lang, "prompts_external_url"),
        "organizer_contacts":   s(lang, "prompts_organizer_contacts"),
        "cover_image_url":      s(lang, "prompts_cover_image_url"),
    }
    await query.message.reply_text(prompts.get(field, f"New value for {field}:"))
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
    lang = get_user_lang(message.chat.id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(s(lang, "btn_submit"),     callback_data="ev_submit"),
        InlineKeyboardButton(s(lang, "btn_edit_more"),  callback_data="ev_edit"),
        InlineKeyboardButton(s(lang, "btn_cancel_str"), callback_data="ev_cancel"),
    ]])
    caption = f"{s(lang, 'step_preview')}\n\n{event_card_text(ev, lang)}\n\n{s(lang, 'preview_ok')}"
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
    "organizer_tg_id", "organizer_username", "status",
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
    lang = get_user_lang(tg_id)
    res = supabase.table("events").select("*")\
          .eq("organizer_tg_id", tg_id)\
          .neq("status", "draft")\
          .order("date_start", desc=True).limit(5).execute()
    if not res.data:
        return await message.reply_text(s(lang, "no_events_yet"))
    for ev in res.data:
        icon    = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
        reject  = f"\n⚠️ {ev['reject_reason']}" if ev.get("reject_reason") else ""
        subs_cnt = supabase.table("subscriptions").select("id", count="exact").eq("event_id", ev["id"]).execute()
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_cancel_event"), callback_data=f"cancel_ev:{ev['id']}"),
            InlineKeyboardButton(s(lang, "btn_share"), callback_data=f"share:{ev['id']}"),
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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    action, event_id = query.data.split(":")
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if ev["organizer_tg_id"] != query.from_user.id and not is_moderator(query.from_user.id):
        return await query.message.reply_text(s(lang, "not_your_event"))

    if action == "cancel_ev":
        ctx.user_data["cancel_event_id"] = event_id
        await query.message.reply_text(
            s(lang, "ask_cancel_reason", title=ev['title']),
            parse_mode="Markdown"
        )
        ctx.user_data["awaiting_cancel_reason"] = True

async def handle_cancel_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    if not ctx.user_data.get("awaiting_cancel_reason"):
        return
    ctx.user_data.pop("awaiting_cancel_reason")
    reason   = update.message.text.strip()
    event_id = ctx.user_data.pop("cancel_event_id")

    supabase.table("events").update({"status": "cancelled"}).eq("id", event_id).execute()
    await update.message.reply_text(s(lang, "event_cancelled"))

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

    # Clean up event subscriptions immediately after notifying
    supabase.table("subscriptions").delete().eq("event_id", event_id).execute()


# ─── Поделиться (UC-08) ──────────────────────────────────────

async def handle_share_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    share_text = event_share_text(ev, lang)
    await query.message.reply_text(
        s(lang, "share_announce", text=share_text),
        parse_mode="Markdown"
    )


# ─── Обратная связь (UC-07) ──────────────────────────────────

async def _show_feedback(message, tg_id: int):
    lang = get_user_lang(tg_id)
    await message.reply_text(
        s(lang, "feedback_title"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_event_status"),  callback_data="fb:status"),
            InlineKeyboardButton(s(lang, "btn_contact_mod"),   callback_data="fb:contact"),
        ]])
    )

async def handle_feedback_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "status":
        res = supabase.table("events").select("id, title, status")\
              .eq("organizer_tg_id", query.from_user.id)\
              .neq("status", "draft")\
              .order("created_at", desc=True).limit(5).execute()
        if not res.data:
            return await query.message.reply_text(s(lang, "no_events_for_status"))
        buttons = [[InlineKeyboardButton(f"{ev['title'][:30]}", callback_data=f"ev_status:{ev['id']}")]
                   for ev in res.data]
        await query.message.reply_text(s(lang, "select_event"), reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "contact":
        ctx.user_data["awaiting_mod_message"] = True
        await query.message.reply_text(s(lang, "ask_mod_message"))

async def handle_ev_status_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    subs = supabase.table("subscriptions").select("id", count="exact").eq("event_id", event_id).execute()
    icon = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
    lang = get_user_lang(query.from_user.id)
    await query.message.reply_text(
        s(lang, "event_status_info",
          icon=icon, title=ev['title'], status=ev['status'],
          count=subs.count,
          reject=('⚠️ ' + ev['reject_reason'] if ev.get('reject_reason') else '')),
        parse_mode="Markdown"
    )

async def handle_mod_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    if not ctx.user_data.get("awaiting_mod_message"):
        return False
    ctx.user_data.pop("awaiting_mod_message")
    user = update.effective_user
    await ctx.bot.send_message(
        MODERATOR_ID,
        f"✉️ Сообщение от @{user.username or '—'} (ID: {user.id}):\n\n{update.message.text}"
    )
    await update.message.reply_text(s(lang, "mod_message_sent"))
    return True


# ─── Просмотр событий (UC-09) ────────────────────────────────

async def _cmd_events_inner(message, lang: str = "ru"):
    now = datetime.now(timezone.utc)
    # Start = right now, end = last moment of current month
    month_end = datetime(now.year, now.month, 1, tzinfo=timezone.utc).replace(
        month=now.month % 12 + 1, day=1
    ) if now.month < 12 else datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    res = supabase.table("events").select("*")\
          .eq("status", "published")\
          .gte("date_start", now.isoformat())\
          .lt("date_start", month_end.isoformat())\
          .order("date_start").execute()
    if not res.data:
        return await message.reply_text(s(lang, "no_upcoming"))
    for ev in res.data:
        date = ev["date_start"][:10]
        cat  = CATEGORIES.get(ev["category"], ev["category"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(s(lang, "btn_notify_me"), callback_data=f"subev:{ev['id']}"),
            InlineKeyboardButton(s(lang, "btn_register"), url=ev.get("external_url") or f"{SITE_URL}/events/{ev['id']}"),
        ]])
        await message.reply_text(
            f"{cat} *{ev['title']}*\n📍 {ev['location_city']} · 🗓 {date}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def cmd_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    await _cmd_events_inner(update.message, lang)


# ─── Подписки (UC-10, UC-11, UC-12) ─────────────────────────

async def handle_subev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query    = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]
    tg_id    = query.from_user.id
    get_or_create_user(tg_id, query.from_user.username)

    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        return await query.answer(s(lang, "already_subscribed"), show_alert=True)

    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    await query.answer(s(lang, "reminder_set"), show_alert=True)

    # Upsell на категорию (UC-10)
    ev = supabase.table("events").select("category").eq("id", event_id).single().execute().data
    cat_label = CATEGORIES.get(ev["category"], "")
    cat_sub   = supabase.table("subscriptions").select("id")\
                .eq("tg_id", tg_id).eq("category", ev["category"]).execute()
    if not cat_sub.data:
        await ctx.bot.send_message(
            tg_id,
            s(lang, "upsell_cat", cat=cat_label),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(s(lang, "btn_sub_cat", cat=cat_label), callback_data=f"subcat:{ev['category']}"),
                InlineKeyboardButton(s(lang, "btn_no_thanks"), callback_data="subcat:skip"),
            ]])
        )

async def handle_unsub_ev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":")[1]
    supabase.table("subscriptions").delete().eq("id", sub_id).eq("tg_id", query.from_user.id).execute()
    await query.message.reply_text(s(lang, "unsubscribed"))

async def _cmd_my_inner(message, tg_id: int):
    lang = get_user_lang(tg_id)
    subs = supabase.table("subscriptions").select("*").eq("tg_id", tg_id).execute()
    if not subs.data:
        return await message.reply_text(
            s(lang, "no_subscriptions")
        )
    # Разделяем на события и категории
    event_subs = [sub for sub in subs.data if sub.get("event_id")]
    cat_subs   = [sub for sub in subs.data if sub.get("category")]
    lines, buttons = [], []

    if event_subs:
        lines.append(s(lang, "subs_on_events"))
        for sub in event_subs:
            ev = supabase.table("events").select("title").eq("id", sub["event_id"]).execute()
            name = ev.data[0]["title"] if ev.data else f"Event #{sub['event_id']}"
            lines.append(f"  🗓 {name}")
            buttons.append([InlineKeyboardButton(s(lang, "btn_unsub_prefix") + name[:28], callback_data=f"unsub_ev:{sub['id']}")])

    if cat_subs:
        lines.append(s(lang, "subs_on_cats"))
        for sub in cat_subs:
            label = CATEGORIES.get(sub["category"], sub["category"])
            lines.append(f"  📌 {label}")
            buttons.append([InlineKeyboardButton(s(lang, "btn_unsub_prefix") + label, callback_data=f"unsub_ev:{sub['id']}")])

    buttons.append([InlineKeyboardButton(s(lang, "btn_add_cat"), callback_data="menu:subscribe")])
    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def cmd_my_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_my_inner(update.message, update.effective_user.id)

async def _cmd_subscribe_inner(message, tg_id: int):
    lang = get_user_lang(tg_id)
    existing = supabase.table("subscriptions").select("category")\
               .eq("tg_id", tg_id).not_.is_("category", "null").execute()
    existing_cats = {sub["category"] for sub in existing.data}
    buttons = []
    for cat_id in CATEGORIES:
        check = "✅ " if cat_id in existing_cats else ""
        buttons.append([InlineKeyboardButton(f"{check}{cat_label(lang, cat_id)}", callback_data=f"subcat:{cat_id}")])
    await message.reply_text(s(lang, "select_categories"), reply_markup=InlineKeyboardMarkup(buttons))

async def cmd_subscribe_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_subscribe_inner(update.message, update.effective_user.id)

async def handle_subcat_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    tg_id  = query.from_user.id
    action = query.data.split(":")[1]

    if action in ("done", "skip"):
        return await query.message.reply_text(s(lang, "settings_saved"))

    cat      = action
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("category", cat).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
        await query.answer(s(lang, "subcat_unsub", cat=cat_label(lang, cat)), show_alert=False)
    else:
        get_or_create_user(tg_id, query.from_user.username)
        supabase.table("subscriptions").insert({"tg_id": tg_id, "category": cat}).execute()
        await query.answer(s(lang, "subcat_sub", cat=cat_label(lang, cat)), show_alert=False)
        await query.message.reply_text(
            s(lang, "subcat_sub_confirm", cat=cat_label(lang, cat)),
            parse_mode="Markdown"
        )


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
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    parts    = query.data.split(":")
    event_id = parts[1]
    tg_id    = query.from_user.id
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
    await query.message.reply_text(s(lang, "cant_come"))


# ─── Черновик: напоминание через 24ч ─────────────────────────

async def job_draft_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    """Напоминает организаторам о незавершённых черновиках."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    drafts = supabase.table("events").select("*")\
             .eq("status", "draft")\
             .lte("created_at", cutoff).execute()
    for ev in drafts.data:
        try:
            ev_lang = get_user_lang(ev["organizer_tg_id"])
            await ctx.bot.send_message(
                ev["organizer_tg_id"],
                s(ev_lang, "draft_reminder",
                  cat=CATEGORIES.get(ev.get('category', ''), '—'),
                  title=ev.get('title', '(untitled)')),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(s(ev_lang, "btn_continue_draft"), callback_data=f"draft_continue:{ev['id']}"),
                ]])
            )
        except Exception:
            pass



# ─── Cleanup: remove past event subscriptions ────────────────

async def job_cleanup_past_event_subscriptions(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Runs every hour. Deletes per-event subscriptions for events
    whose date_start is in the past. Category subscriptions are never touched.
    """
    now = datetime.now(timezone.utc).isoformat()
    # Find all past published events
    past_events = supabase.table("events").select("id")\
                  .eq("status", "published")\
                  .lt("date_start", now).execute()
    if not past_events.data:
        return
    past_ids = [ev["id"] for ev in past_events.data]
    deleted = 0
    for event_id in past_ids:
        res = supabase.table("subscriptions")\
              .delete()\
              .eq("event_id", event_id)\
              .not_.is_("event_id", "null")\
              .execute()
        if res.data:
            deleted += len(res.data)
    if deleted:
        logger.info(f"Cleaned up {deleted} past event subscription(s)")


# ─── Напоминание организатору: завершить регистрацию (7 дней) ─

async def job_organizer_reg_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Runs every hour. 7 days before the event start, sends the organizer
    a reminder to press 'End Registration' if all spots are filled.
    Only fires for published events with max_participants set and
    registration_closed = false. Logged to notification_log (type = reg_reminder_7d).
    """
    now          = datetime.now(timezone.utc)
    window_start = now + timedelta(days=7) - timedelta(hours=1)
    window_end   = now + timedelta(days=7) + timedelta(hours=1)

    events = supabase.table("events").select("*")             .eq("status", "published")             .eq("registration_closed", False)             .not_.is_("max_participants", "null")             .gte("date_start", window_start.isoformat())             .lte("date_start", window_end.isoformat()).execute()

    for ev in events.data:
        organizer_id = ev.get("organizer_tg_id")
        if not organizer_id:
            continue

        # Skip if already sent this reminder for this event
        already = supabase.table("notification_log").select("id")                  .eq("tg_id", organizer_id)                  .eq("event_id", ev["id"])                  .eq("type", "reg_reminder_7d").execute()
        if already.data:
            continue

        date_str = ev["date_start"][:16].replace("T", " ")
        limit    = ev["max_participants"]

        try:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔒 End Registration", callback_data=f"end_reg:{ev['id']}"),
                InlineKeyboardButton("✅ Still Open",       callback_data=f"end_reg_skip:{ev['id']}"),
            ]])
            text = (
                "⏰ *Событие через 7 дней!*\n\n"
                f"📌 *{ev['title']}*\n"
                f"📅 {date_str}\n"
                f"👥 Лимит: {limit} мест\n\n"
                "Если все места уже заняты — нажми *End Registration*, "
                "чтобы обновить статус до *Full* на сайте."
            )
            await ctx.bot.send_message(
                organizer_id,
                text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            supabase.table("notification_log").insert({
                "tg_id": organizer_id,
                "event_id": ev["id"],
                "type": "reg_reminder_7d"
            }).execute()
            logger.info(f"Sent reg_reminder_7d to organizer {organizer_id} for event {ev['id']}")
        except Exception as e:
            logger.warning(f"reg_reminder_7d failed for {organizer_id}: {e}")


async def handle_end_registration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Step 1: Organizer taps 'End Registration' inline button.
    Stores event_id and asks for confirmation.
    """
    lang = get_user_lang(update.effective_user.id)
    query    = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]

    ev = supabase.table("events").select("id, title, max_participants")         .eq("id", event_id).single().execute().data
    if not ev:
        await query.message.reply_text(s(lang, "event_not_found"))
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да, закрыть регистрацию", callback_data=f"end_reg_confirm:{event_id}"),
        InlineKeyboardButton("❌ Отмена",                  callback_data=f"end_reg_cancel:{event_id}"),
    ]])
    await query.message.reply_text(
        s(lang, "close_reg_confirm", title=ev["title"], limit=ev["max_participants"]),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def handle_end_registration_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Step 2: Organizer confirms. Writes registration_closed=true and notifies subscribers.
    """
    query    = update.callback_query
    await query.answer()
    event_id = query.data.split(":")[1]

    # Write to DB
    supabase.table("events").update({"registration_closed": True}).eq("id", event_id).execute()
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    await query.message.reply_text(
        s(lang, "reg_closed_done", title=ev["title"]),
        parse_mode="Markdown"
    )
    logger.info(f"registration_closed=true set for event {event_id}")

    # Notify all subscribers
    subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
    date_str = ev["date_start"][:16].replace("T", " ")
    for s in subs.data:
        try:
            sub_lang = get_user_lang(s["tg_id"])
            await ctx.bot.send_message(
                s["tg_id"],
                s(sub_lang, "reg_closed_notify", title=ev["title"], date=date_str),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Subscriber notify failed for {s['tg_id']}: {e}")


async def handle_end_registration_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Organizer taps 'Still Open' — dismiss reminder silently."""
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer(s(lang, "reg_still_open"), show_alert=False)


async def handle_end_registration_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Organizer cancels the confirmation step."""
    lang = get_user_lang(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(s(lang, "reg_cancel"))


# ─── Общий обработчик текста ─────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Перехватывает свободный текст для разных состояний."""
    lang = get_user_lang(update.effective_user.id)
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
            EV_LIMIT:        [CallbackQueryHandler(ev_get_limit,        pattern="^limit:")],
            EV_LIMIT_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_limit_custom)],
            EV_FORMAT:       [CallbackQueryHandler(ev_get_format,    pattern="^fmt:")],
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
            u.message.reply_text(s(lang, "wizard_cancelled")),
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
            u.message.reply_text(s(lang, "edit_cancelled")),
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
    app.add_handler(CommandHandler("settings",           cmd_settings))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_setlang,                    pattern="^setlang:"))
    app.add_handler(CallbackQueryHandler(handle_settings_callback,          pattern="^settings:"))
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
    app.add_handler(CallbackQueryHandler(handle_end_registration,            pattern="^end_reg:[^_]"))
    app.add_handler(CallbackQueryHandler(handle_end_registration_confirm,    pattern="^end_reg_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_end_registration_cancel,     pattern="^end_reg_cancel:"))
    app.add_handler(CallbackQueryHandler(handle_end_registration_skip,       pattern="^end_reg_skip:"))
    # Moderator manage-events callbacks
    app.add_handler(CallbackQueryHandler(handle_mod_page,                   pattern="^mod_page:"))
    app.add_handler(CallbackQueryHandler(handle_mod_delete,                 pattern="^mod_delete:"))
    app.add_handler(CallbackQueryHandler(handle_mod_delete_confirm,         pattern="^mod_delete_(confirm|cancel)"))

    # Свободный текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Cron-задачи
    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(job_send_reminders,                    interval=3600, first=60)
    job_queue.run_repeating(job_organizer_reg_reminder,            interval=3600, first=90)
    job_queue.run_repeating(job_draft_reminders,                   interval=3600, first=120)
    job_queue.run_repeating(job_cleanup_past_event_subscriptions,  interval=86400, first=150)

    # ── Bot menu commands (shown in Telegram's "/" menu) ──────
    async def post_init(application: Application) -> None:
        from telegram import BotCommandScopeAllPrivateChats
        commands = {
            "en": [
                BotCommand("start",     "👋 Start"),
                BotCommand("events",    "📅 Events this month"),
                BotCommand("my",        "🔔 My subscriptions"),
                BotCommand("subscribe", "📌 Subscribe to category"),
                BotCommand("settings",  "⚙️ Settings"),
            ],
            "ru": [
                BotCommand("start",     "👋 Старт"),
                BotCommand("events",    "📅 События этого месяца"),
                BotCommand("my",        "🔔 Мои подписки"),
                BotCommand("subscribe", "📌 Подписаться на категорию"),
                BotCommand("settings",  "⚙️ Настройки"),
            ],
            "el": [
                BotCommand("start",     "👋 Έναρξη"),
                BotCommand("events",    "📅 Εκδηλώσεις αυτόν τον μήνα"),
                BotCommand("my",        "🔔 Οι συνδρομές μου"),
                BotCommand("subscribe", "📌 Εγγραφή σε κατηγορία"),
                BotCommand("settings",  "⚙️ Ρυθμίσεις"),
            ],
            "uk": [
                BotCommand("start",     "👋 Початок"),
                BotCommand("events",    "📅 Події цього місяця"),
                BotCommand("my",        "🔔 Мої підписки"),
                BotCommand("subscribe", "📌 Підписатись на категорію"),
                BotCommand("settings",  "⚙️ Налаштування"),
            ],
        }
        # Default menu for users with no matched language
        await application.bot.set_my_commands(commands["en"])
        # Language-specific menus
        for lang_code, cmds in commands.items():
            try:
                await application.bot.set_my_commands(
                    cmds,
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=lang_code,
                )
            except Exception as e:
                logger.warning(f"Could not set commands for {lang_code}: {e}")

    app.post_init = post_init

    return app


if __name__ == "__main__":
    application = build_application()
    logger.info("NextQuest bot v0.5 started.")
    application.run_polling()
