"""
NextQuest Telegram Bot — v0.4
Соответствует спеке nextquest_spec_v04.docx

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
SITE_URL     = os.environ.get("SITE_URL", "https://nextquest.cy")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = {
    "boardgames": "🎲 Настолки",
    "larp":        "⚔️ LARP",
    "festival":    "🎪 Фестивали",
    "rpg":         "🎭 RPG",
    "cosplay":     "👗 Косплей",
    "other":       "🃏 Другое",
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
    EV_TITLE, EV_DESC, EV_PHOTO,
    EV_URL,
    REJECT_CUSTOM,
) = range(20)


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

def event_card_text(ev: dict) -> str:
    date_str = ev["date_start"][:16].replace("T", " ")
    end_str  = f" → {ev['date_end'][:16].replace('T', ' ')}" if ev.get("date_end") else ""
    limit    = f"{ev['max_participants']} мест" if ev.get("max_participants") else "без лимита"
    url_line = f"\n🔗 {ev['external_url']}" if ev.get("external_url") else ""
    return (
        f"*{ev['title']}*\n"
        f"{CATEGORIES.get(ev['category'], ev['category'])}\n"
        f"🗓 {date_str}{end_str}\n"
        f"📍 {ev['location_city']} · {ev['location_address']}\n"
        f"👥 {limit}{url_line}\n\n"
        f"{ev['description']}"
    )

def event_share_text(ev: dict) -> str:
    """Готовый текст для репоста в Telegram-чат."""
    date_str = ev["date_start"][:16].replace("T", " ")
    return (
        f"📣 *{ev['title']}*\n"
        f"{CATEGORIES.get(ev['category'], ev['category'])} · {ev['location_city']}\n"
        f"🗓 {date_str}\n"
        f"📍 {ev['location_address']}\n\n"
        f"{ev['description'][:300]}{'...' if len(ev['description']) > 300 else ''}\n\n"
        f"🔔 Подписаться на напоминание: t.me/{BOT_USERNAME}?start=event_{ev['id']}\n"
        f"🌐 {SITE_URL}/events/{ev['id']}"
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
    db_user = get_or_create_user(user.id, user.username)

    # Deep-link: /start event_123
    if ctx.args and ctx.args[0].startswith("event_"):
        event_id = ctx.args[0].split("_")[1]
        return await _show_event_deeplink(update, ctx, event_id)

    # Уже выбирал роль раньше — показываем нужное меню
    if db_user.get("onboarded"):
        return await _show_main_menu(update.message, db_user["role"])

    # Первый запуск — спрашиваем кто ты (UC-7.1)
    await update.message.reply_text(
        "👋 Привет! Я *NextQuest* — бот событий гик-сообщества Кипра.\n\nКто ты?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎲 Участник — ищу события",     callback_data="onboard:participant"),
            InlineKeyboardButton("🎪 Организатор — добавляю события", callback_data="onboard:organizer"),
        ]]),
        parse_mode="Markdown"
    )

async def handle_onboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    tg_id  = query.from_user.id

    if choice == "organizer":
        # Организатор — нужна верификация модератором
        supabase.table("users").update({"onboarded": True}).eq("tg_id", tg_id).execute()
        await query.message.reply_text(
            "🎪 Отлично! Чтобы добавлять события, нужна верификация.\n\n"
            "Отправь запрос модератору командой /request\\_organizer",
            parse_mode="Markdown"
        )
        # Показываем меню участника пока не верифицирован
        db_user = get_user(tg_id)
        await _show_main_menu(query.message, db_user["role"])
    else:
        supabase.table("users").update({"onboarded": True}).eq("tg_id", tg_id).execute()
        await _show_main_menu(query.message, "participant")

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
        ctx.user_data["new_event"] = {}
        if not is_organizer(query.from_user.id):
            return await fake.reply_text("⛔ Нужна верификация организатора. Отправь /request_organizer")
        await _ask_category(fake)
        return EV_CATEGORY
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
            [InlineKeyboardButton("📋 Очередь на апрув",  callback_data="admin:pending")],
            [InlineKeyboardButton("📊 Статистика",         callback_data="admin:stats")],
            [InlineKeyboardButton("➕ Добавить организатора", callback_data="admin:add_org_prompt")],
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

async def cmd_new_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    if not is_organizer(user.id):
        return await update.message.reply_text(
            "⛔ Нужна верификация.\nОтправь /request\\_organizer чтобы запросить роль организатора.",
            parse_mode="Markdown"
        )

    # Восстанавливаем черновик если есть
    draft = supabase.table("events").select("*")\
            .eq("organizer_tg_id", user.id).eq("status", "draft").order("created_at", desc=True).limit(1).execute()
    if draft.data:
        ev = draft.data[0]
        await update.message.reply_text(
            f"У тебя есть незавершённый черновик: *{ev.get('title', '(без названия)')}*\nПродолжить или начать заново?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("▶️ Продолжить", callback_data=f"draft_continue:{ev['id']}"),
                InlineKeyboardButton("🗑 Начать заново", callback_data="draft_new"),
            ]]),
            parse_mode="Markdown"
        )
        return EV_CATEGORY

    ctx.user_data["new_event"] = {}
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
    ctx.user_data["new_event"]["category"] = q.data.split(":")[1]
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
        ctx.user_data["new_event"]["cover_image_url"] = update.message.photo[-1].file_id
        ctx.user_data["new_event"]["cover_file_id"]   = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.startswith("http"):
        ctx.user_data["new_event"]["cover_image_url"] = update.message.text.strip()
    else:
        await update.message.reply_text("❌ Нужна картинка или ссылка (https://...)")
        return EV_PHOTO

    await update.message.reply_text("Ссылка на регистрацию (или `-` если нет):")
    return EV_URL

async def ev_get_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        ctx.user_data["new_event"]["external_url"] = txt

    ev = ctx.user_data["new_event"]
    ev["organizer_tg_id"] = update.effective_user.id
    ev["status"]          = "pending"
    await _save_draft(ctx)

    # Шаг 5 — превью
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📤 Отправить на модерацию", callback_data="ev_submit"),
        InlineKeyboardButton("✏️ Изменить",               callback_data="ev_edit"),
        InlineKeyboardButton("🗑 Отмена",                  callback_data="ev_cancel"),
    ]])
    cover = ev.get("cover_file_id") or ev.get("cover_image_url")
    caption = f"Шаг 5/5: *Превью*\n\n{event_card_text(ev)}\n\nВсё верно?"
    try:
        if cover:
            await update.message.reply_photo(cover, caption=caption, reply_markup=keyboard, parse_mode="Markdown")
            return ConversationHandler.END
    except Exception:
        pass
    await update.message.reply_text(caption, reply_markup=keyboard, parse_mode="Markdown")
    return ConversationHandler.END

async def ev_submit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ev_cancel":
        # Удаляем черновик
        if ctx.user_data.get("draft_id"):
            supabase.table("events").delete().eq("id", ctx.user_data["draft_id"]).execute()
        ctx.user_data.pop("new_event", None)
        ctx.user_data.pop("draft_id", None)
        return await query.message.reply_text("❌ Отменено.")

    if query.data == "ev_edit":
        ctx.user_data.pop("new_event", None)
        await query.message.reply_text("Начинаем заново. Используй /new_event")
        return

    ev = ctx.user_data.get("new_event", {})
    if not ev:
        return await query.message.reply_text("❌ Сессия истекла. Попробуй /new_event снова.")

    # Обновляем статус черновика или создаём новую запись
    draft_id = ctx.user_data.pop("draft_id", None)
    if draft_id:
        supabase.table("events").update({**ev, "status": "pending"}).eq("id", draft_id).execute()
        event_id = draft_id
    else:
        res = supabase.table("events").insert({**ev, "status": "pending"}).execute()
        event_id = res.data[0]["id"]

    ctx.user_data.pop("new_event", None)
    await query.message.reply_text(f"✅ Событие отправлено на модерацию!")

    # Модератор получает карточку с кнопками сразу (UC-01, FIX 3)
    ev_with_id = {**ev, "id": event_id}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{event_id}"),
        InlineKeyboardButton("✏️ Правки",       callback_data=f"request_edits:{event_id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:{event_id}"),
    ]])
    cover = ev.get("cover_file_id") or ev.get("cover_image_url")
    text  = f"📬 Новое событие на апруве!\n\n{event_card_text(ev_with_id)}"
    try:
        if cover:
            await ctx.bot.send_photo(MODERATOR_ID, cover, caption=text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await ctx.bot.send_message(MODERATOR_ID, text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Cannot notify moderator: {e}")

async def _save_draft(ctx):
    """Сохраняет или обновляет черновик в БД."""
    ev = ctx.user_data.get("new_event", {})
    if not ev.get("organizer_tg_id"):
        return
    draft_id = ctx.user_data.get("draft_id")
    ev_data  = {**ev, "status": "draft"}
    if draft_id:
        supabase.table("events").update(ev_data).eq("id", draft_id).execute()
    else:
        try:
            res = supabase.table("events").insert(ev_data).execute()
            ctx.user_data["draft_id"] = res.data[0]["id"]
        except Exception:
            pass


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
            CallbackQueryHandler(handle_draft_choice, pattern="^draft_(continue|new)"),
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
            EV_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_title)],
            EV_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_desc)],
            EV_PHOTO:      [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ev_get_photo)],
            EV_URL:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_url)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (
            u.message.reply_text("Отменено. Черновик сохранён — продолжи через /new_event"),
            ConversationHandler.END
        ))],
        allow_reentry=True,
    )

    app.add_handler(wizard)

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
    app.add_handler(CallbackQueryHandler(handle_menu,                       pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(handle_admin_menu,                 pattern="^admin:"))
    app.add_handler(CallbackQueryHandler(handle_moderation_callback,        pattern="^(approve|reject|request_edits):"))
    app.add_handler(CallbackQueryHandler(handle_reject_reason_button,       pattern="^reason:"))
    app.add_handler(CallbackQueryHandler(handle_org_request,                pattern="^(add_org|deny_org):"))
    app.add_handler(CallbackQueryHandler(handle_organizer_event_callback,   pattern="^cancel_ev:"))
    app.add_handler(CallbackQueryHandler(handle_share_callback,             pattern="^share:"))
    app.add_handler(CallbackQueryHandler(handle_feedback_callback,          pattern="^fb:"))
    app.add_handler(CallbackQueryHandler(handle_ev_status_callback,         pattern="^ev_status:"))
    app.add_handler(CallbackQueryHandler(ev_submit_callback,                pattern="^ev_(submit|cancel|edit)$"))
    app.add_handler(CallbackQueryHandler(handle_subev_callback,             pattern="^subev:"))
    app.add_handler(CallbackQueryHandler(handle_unsub_ev_callback,          pattern="^unsub_ev:"))
    app.add_handler(CallbackQueryHandler(handle_subcat_callback,            pattern="^subcat:"))
    app.add_handler(CallbackQueryHandler(handle_cant_come,                  pattern="^cant_come:"))

    # Свободный текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Cron-задачи
    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(job_send_reminders,  interval=3600, first=60)   # каждый час
    job_queue.run_repeating(job_draft_reminders, interval=3600, first=120)  # каждый час

    return app


if __name__ == "__main__":
    application = build_application()
    logger.info("NextQuest bot v0.4 started.")
    application.run_polling()
