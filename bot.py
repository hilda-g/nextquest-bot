"""
NextQuest Telegram Bot
Fixes:
  1. Preview показывает загруженное фото (file_id), не URL
  2. Дата выбирается кнопками (год/месяц/день/час/минута)
  3. После сабмита модератору сразу летит сообщение с кнопками Approve/Reject
  4. Любой может отправить ивент — проверка на organizer убрана
  5. Организатор получает уведомление об апруве/реджекте
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
MODERATOR_ID = int(os.environ["MODERATOR_TG_ID"])

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = {
    "boardgames": "🎲 Board Games",
    "larp":        "⚔️ LARP",
    "festival":    "🎪 Festival",
    "rpg":         "🎭 RPG",
    "cosplay":     "👗 Cosplay",
    "other":       "🃏 Other",
}

# ─── Wizard states ───────────────────────────────────────────
(
    EV_TITLE, EV_CATEGORY,
    EV_YEAR, EV_MONTH, EV_DAY, EV_HOUR, EV_MINUTE,
    EV_END_CHOICE, EV_END_YEAR, EV_END_MONTH, EV_END_DAY, EV_END_HOUR, EV_END_MINUTE,
    EV_CITY, EV_ADDRESS, EV_DESC, EV_PHOTO, EV_LIMIT, EV_URL
) = range(19)


# ─── Helpers ─────────────────────────────────────────────────

def get_or_create_user(tg_id: int, username: str | None, lang: str = "ru"):
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    if res.data:
        return res.data[0]
    new_user = {"tg_id": tg_id, "tg_username": username, "role": "participant", "language": lang}
    supabase.table("users").insert(new_user).execute()
    return new_user

def is_moderator(tg_id: int) -> bool:
    res = supabase.table("users").select("role").eq("tg_id", tg_id).execute()
    return bool(res.data and res.data[0]["role"] == "moderator")

def event_preview_text(ev: dict) -> str:
    date_str = ev["date_start"][:16].replace("T", " ")
    end_str  = f" → {ev['date_end'][:16].replace('T',' ')}" if ev.get("date_end") else ""
    limit    = f"{ev['max_participants']} max" if ev.get("max_participants") else "no limit"
    return (
        f"📡 *{ev['title']}*\n"
        f"Category: {CATEGORIES.get(ev['category'], ev['category'])}\n"
        f"🗓 {date_str}{end_str}\n"
        f"📍 {ev['location_city']} · {ev['location_address']}\n"
        f"👥 {limit}\n"
        f"🔗 {ev.get('external_url','—')}\n\n"
        f"{ev['description']}"
    )

def make_year_keyboard(prefix: str) -> InlineKeyboardMarkup:
    now = datetime.now().year
    buttons = [[InlineKeyboardButton(str(y), callback_data=f"{prefix}:{y}")]
               for y in range(now, now + 3)]
    return InlineKeyboardMarkup(buttons)

def make_month_keyboard(prefix: str) -> InlineKeyboardMarkup:
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    buttons = [
        [InlineKeyboardButton(months[i], callback_data=f"{prefix}:{i+1}"),
         InlineKeyboardButton(months[i+1], callback_data=f"{prefix}:{i+2}"),
         InlineKeyboardButton(months[i+2], callback_data=f"{prefix}:{i+3}")]
        for i in range(0, 12, 3)
    ]
    return InlineKeyboardMarkup(buttons)

def make_day_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for d in range(1, 32):
        row.append(InlineKeyboardButton(str(d), callback_data=f"{prefix}:{d}"))
        if len(row) == 7:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def make_hour_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for h in range(0, 24):
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"{prefix}:{h}"))
        if len(row) == 6:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def make_minute_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = [[
        InlineKeyboardButton("00", callback_data=f"{prefix}:0"),
        InlineKeyboardButton("15", callback_data=f"{prefix}:15"),
        InlineKeyboardButton("30", callback_data=f"{prefix}:30"),
        InlineKeyboardButton("45", callback_data=f"{prefix}:45"),
    ]]
    return InlineKeyboardMarkup(buttons)


# ─── /start ──────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    if ctx.args and ctx.args[0].startswith("event_"):
        event_id = int(ctx.args[0].split("_")[1])
        await _subscribe_to_event(update, ctx, event_id)
        return

    await update.message.reply_text(
        "👋 Welcome to *NextQuest*!\n\n"
        "Available commands:\n"
        "/events — browse upcoming events\n"
        "/new\\_event — submit a new event\n"
        "/my\\_events — manage my events\n"
        "/my — my subscriptions\n"
        "/subscribe — subscribe to categories\n\n"
        "_Moderators:_ /pending · /stats",
        parse_mode="Markdown"
    )


# ─── Moderator: stats ────────────────────────────────────────

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorised.")
    published = supabase.table("events").select("id", count="exact").eq("status", "published").execute()
    pending   = supabase.table("events").select("id", count="exact").eq("status", "pending").execute()
    subs      = supabase.table("subscriptions").select("id", count="exact").execute()
    users_cnt = supabase.table("users").select("tg_id", count="exact").execute()
    await update.message.reply_text(
        f"📊 *NextQuest stats*\n\n"
        f"✅ Published: {published.count}\n"
        f"⏳ Pending: {pending.count}\n"
        f"👥 Users: {users_cnt.count}\n"
        f"🔔 Subscriptions: {subs.count}",
        parse_mode="Markdown"
    )


# ─── Moderator: pending queue ────────────────────────────────

async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorised.")
    res = supabase.table("events").select("*").eq("status", "pending").order("created_at").execute()
    if not res.data:
        return await update.message.reply_text("✅ No events pending approval.")
    for ev in res.data:
        await _send_moderation_card(update.message, ctx, ev)


async def _send_moderation_card(message, ctx, ev: dict):
    """Send event card with Approve/Reject buttons to moderator."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{ev['id']}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{ev['id']}"),
    ]])
    text = f"[#{ev['id']}] {event_preview_text(ev)}"
    cover = ev.get("cover_image_url") or ev.get("cover_file_id")
    if cover:
        try:
            await message.reply_photo(cover, caption=text, reply_markup=keyboard, parse_mode="Markdown")
            return
        except Exception:
            pass
    await message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_moderation_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, event_id = query.data.split(":")
    event_id = int(event_id)

    if action == "approve":
        supabase.table("events").update({"status": "published"}).eq("id", event_id).execute()
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"✅ Event #{event_id} published!")

        ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

        # FIX 5: notify organizer
        try:
            await ctx.bot.send_message(
                ev["organizer_tg_id"],
                f"🎉 Твой ивент *{ev['title']}* одобрен и опубликован!",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not notify organizer: {e}")

        # Notify category subscribers
        subs = supabase.table("subscriptions").select("tg_id").eq("category", ev["category"]).execute()
        for s in subs.data:
            try:
                await ctx.bot.send_message(
                    s["tg_id"],
                    f"🔔 New event in {CATEGORIES[ev['category']]}!\n\n{event_preview_text(ev)}",
                    parse_mode="Markdown"
                )
                supabase.table("notification_log").insert({
                    "tg_id": s["tg_id"], "event_id": event_id, "type": "new_event"
                }).execute()
            except Exception as e:
                logger.warning(f"Failed to notify {s['tg_id']}: {e}")

    elif action == "reject":
        ctx.user_data["reject_event_id"] = event_id
        ctx.user_data["awaiting_reject_reason"] = True
        await query.message.reply_text(f"Rejecting event #{event_id}.\nSend the reason:")


async def handle_reject_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_reject_reason"):
        return
    reason   = update.message.text
    event_id = ctx.user_data.pop("reject_event_id")
    ctx.user_data.pop("awaiting_reject_reason")

    supabase.table("events").update({"reject_reason": reason}).eq("id", event_id).execute()
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data

    # FIX 5: notify organizer with reason
    try:
        await ctx.bot.send_message(
            ev["organizer_tg_id"],
            f"❌ Твой ивент *{ev['title']}* отклонён.\n\nПричина: {reason}\n\n"
            "Отредактируй и отправь снова через /new\\_event",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Could not notify organizer: {e}")

    await update.message.reply_text("Done. Organizer notified.")


# ─── New event wizard ─────────────────────────────────────────
# FIX 4: removed organizer check — anyone can submit

async def cmd_new_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_or_create_user(update.effective_user.id, update.effective_user.username)
    ctx.user_data["new_event"] = {}
    await update.message.reply_text(
        "📝 Создаём ивент!\n\nШаг 1/9: *Название ивента*",
        parse_mode="Markdown"
    )
    return EV_TITLE

async def ev_get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["title"] = update.message.text
    buttons = [[InlineKeyboardButton(label, callback_data=f"cat:{cat_id}")]
               for cat_id, label in CATEGORIES.items()]
    await update.message.reply_text(
        "Шаг 2/9: *Категория?*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CATEGORY

async def ev_get_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["new_event"]["category"] = query.data.split(":")[1]
    await query.message.reply_text(
        "Шаг 3/9: *Год начала?*",
        reply_markup=make_year_keyboard("sy"),
        parse_mode="Markdown"
    )
    return EV_YEAR

# FIX 2: date picker via buttons
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
    m = int(q.data.split(":")[1])
    d = ctx.user_data
    dt = datetime(d["_sy"], d["_sm"], d["_sd"], d["_sh"], m)
    ctx.user_data["new_event"]["date_start"] = dt.isoformat()
    await q.message.reply_text(
        f"Начало: *{dt.strftime('%d %b %Y %H:%M')}* ✓\n\nИвент многодневный?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, добавить дату окончания", callback_data="end:yes"),
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
    m = int(q.data.split(":")[1])
    d = ctx.user_data
    dt = datetime(d["_ey"], d["_em"], d["_ed"], d["_eh"], m)
    ctx.user_data["new_event"]["date_end"] = dt.isoformat()
    return await _ask_city(q.message, ctx)

async def _ask_city(message, ctx):
    buttons = [[InlineKeyboardButton(c, callback_data=f"city:{c}")]
               for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
    await message.reply_text(
        "Шаг 4/9: *Город?*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CITY

async def ev_get_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["new_event"]["location_city"] = q.data.split(":")[1]
    await q.message.reply_text("Шаг 5/9: *Адрес?*\nПример: `The Brew, Stasinos Ave 10`", parse_mode="Markdown")
    return EV_ADDRESS

async def ev_get_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["location_address"] = update.message.text
    await update.message.reply_text("Шаг 6/9: *Описание ивента:*", parse_mode="Markdown")
    return EV_DESC

async def ev_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["description"] = update.message.text
    await update.message.reply_text("Шаг 7/9: *Обложка* — отправь фото или URL:", parse_mode="Markdown")
    return EV_PHOTO

async def ev_get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # FIX 1: store file_id for uploaded photos, URL for links
    if update.message.photo:
        photo = update.message.photo[-1]
        # Store file_id directly — works in both preview and moderation card
        ctx.user_data["new_event"]["cover_file_id"] = photo.file_id
        ctx.user_data["new_event"]["cover_image_url"] = photo.file_id  # for DB compatibility
    elif update.message.text and update.message.text.startswith("http"):
        ctx.user_data["new_event"]["cover_image_url"] = update.message.text.strip()
    else:
        await update.message.reply_text("❌ Отправь фото или ссылку (https://...)")
        return EV_PHOTO

    await update.message.reply_text(
        "Шаг 8/9: *Лимит участников?*\nОтправь число или `-` без лимита:",
        parse_mode="Markdown"
    )
    return EV_LIMIT

async def ev_get_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        if not txt.isdigit():
            await update.message.reply_text("❌ Число или `-`")
            return EV_LIMIT
        ctx.user_data["new_event"]["max_participants"] = int(txt)
    await update.message.reply_text("Шаг 9/9: *Ссылка для регистрации* (или `-`):", parse_mode="Markdown")
    return EV_URL

async def ev_get_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        ctx.user_data["new_event"]["external_url"] = txt

    ev = ctx.user_data["new_event"]
    ev["organizer_tg_id"] = update.effective_user.id
    ev["status"] = "pending"

    preview_text = event_preview_text(ev)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📤 Отправить на модерацию", callback_data="ev_submit"),
        InlineKeyboardButton("🗑 Отмена", callback_data="ev_cancel"),
    ]])

    # FIX 1: preview with actual uploaded photo
    cover = ev.get("cover_file_id") or ev.get("cover_image_url")
    if cover:
        try:
            await update.message.reply_photo(
                cover,
                caption=f"Превью:\n\n{preview_text}\n\nВсё верно?",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return ConversationHandler.END
        except Exception:
            pass
    await update.message.reply_text(
        f"Превью:\n\n{preview_text}\n\nВсё верно?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def ev_submit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ev_cancel":
        ctx.user_data.pop("new_event", None)
        return await query.message.reply_text("❌ Отменено.")

    ev = ctx.user_data.pop("new_event", {})
    if not ev:
        return await query.message.reply_text("❌ Сессия истекла. Попробуй /new_event снова.")

    res = supabase.table("events").insert(ev).execute()
    event_id = res.data[0]["id"]
    await query.message.reply_text(f"✅ Ивент #{event_id} отправлен на модерацию!")

    # FIX 3: moderator gets card with Approve/Reject immediately
    mod_chat = await ctx.bot.get_chat(MODERATOR_ID)
    class FakeMessage:
        async def reply_photo(self, *a, **kw): return await ctx.bot.send_photo(MODERATOR_ID, *a, **kw)
        async def reply_text(self, *a, **kw):  return await ctx.bot.send_message(MODERATOR_ID, *a, **kw)
    await _send_moderation_card(FakeMessage(), ctx, {**ev, "id": event_id})


# ─── Organizer: my events ────────────────────────────────────

async def cmd_my_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("events").select("*")\
          .eq("organizer_tg_id", update.effective_user.id)\
          .order("date_start", desc=True).execute()
    if not res.data:
        return await update.message.reply_text("У тебя пока нет ивентов.")
    for ev in res.data[:5]:
        icon = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
        reject_note = f"\n⚠️ Причина отклонения: {ev['reject_reason']}" if ev.get("reject_reason") else ""
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚫 Отменить", callback_data=f"cancel_ev:{ev['id']}"),
        ]])
        await update.message.reply_text(
            f"{icon} *{ev['title']}* (#{ev['id']})\n"
            f"{ev['date_start'][:10]} · {ev['location_city']}{reject_note}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def handle_organizer_event_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, event_id = query.data.split(":")
    event_id = int(event_id)
    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    if ev["organizer_tg_id"] != query.from_user.id and not is_moderator(query.from_user.id):
        return await query.message.reply_text("⛔ Это не твой ивент.")
    if action == "cancel_ev":
        supabase.table("events").update({"status": "cancelled"}).eq("id", event_id).execute()
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"🚫 Ивент *{ev['title']}* отменён.", parse_mode="Markdown")
        subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
        for s in subs.data:
            try:
                await ctx.bot.send_message(s["tg_id"], f"❌ *{ev['title']}* отменён.", parse_mode="Markdown")
            except Exception:
                pass


# ─── Subscribe to event ──────────────────────────────────────

async def _subscribe_to_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE, event_id: int):
    ev = supabase.table("events").select("*").eq("id", event_id).execute()
    if not ev.data:
        return await update.message.reply_text("❌ Ивент не найден.")
    ev = ev.data[0]
    tg_id = update.effective_user.id
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        return await update.message.reply_text("✅ Ты уже подписан на этот ивент!")
    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    await update.message.reply_text(
        f"🔔 Подписка оформлена на *{ev['title']}*!\nНапомним за 7 дней до ивента.",
        parse_mode="Markdown"
    )


# ─── My subscriptions ────────────────────────────────────────

async def cmd_my_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    subs  = supabase.table("subscriptions").select("*").eq("tg_id", tg_id).execute()
    if not subs.data:
        return await update.message.reply_text(
            "Подписок пока нет.\n/subscribe — подписаться на категории\n/events — смотреть ивенты"
        )
    lines, buttons = [], []
    for s in subs.data:
        if s["event_id"]:
            ev = supabase.table("events").select("title").eq("id", s["event_id"]).execute()
            name = ev.data[0]["title"] if ev.data else f"Event #{s['event_id']}"
            lines.append(f"🗓 {name}")
            buttons.append([InlineKeyboardButton(f"Отписаться: {name[:28]}", callback_data=f"unsub:{s['id']}")])
        elif s["category"]:
            lines.append(f"📌 {CATEGORIES.get(s['category'], s['category'])}")
            buttons.append([InlineKeyboardButton(f"Отписаться: {s['category']}", callback_data=f"unsub:{s['id']}")])
    await update.message.reply_text(
        "Твои подписки:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_unsub_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = int(query.data.split(":")[1])
    supabase.table("subscriptions").delete().eq("id", sub_id).eq("tg_id", query.from_user.id).execute()
    await query.message.reply_text("✅ Отписка оформлена.")


# ─── Category subscriptions ──────────────────────────────────

async def cmd_subscribe_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    existing = supabase.table("subscriptions").select("category")\
               .eq("tg_id", tg_id).not_.is_("category", "null").execute()
    existing_cats = {s["category"] for s in existing.data}
    buttons = []
    for cat_id, label in CATEGORIES.items():
        check = "✅ " if cat_id in existing_cats else ""
        buttons.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"subcat:{cat_id}")])
    buttons.append([InlineKeyboardButton("Готово ✔", callback_data="subcat:done")])
    await update.message.reply_text(
        "Выбери категории (нажми чтобы переключить):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_subcat_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id  = query.from_user.id
    action = query.data.split(":")[1]
    if action == "done":
        return await query.message.reply_text("✅ Настройки сохранены!")
    cat = action
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("category", cat).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
        await query.answer(f"Отписка от {CATEGORIES[cat]}", show_alert=False)
    else:
        supabase.table("subscriptions").insert({"tg_id": tg_id, "category": cat}).execute()
        await query.answer(f"Подписка на {CATEGORIES[cat]}", show_alert=False)


# ─── Browse events ───────────────────────────────────────────

async def cmd_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("events").select("*")\
          .eq("status", "published").gte("date_start", now)\
          .order("date_start").limit(5).execute()
    if not res.data:
        return await update.message.reply_text("Ближайших ивентов пока нет.")
    for ev in res.data:
        date = ev["date_start"][:10]
        cat  = CATEGORIES.get(ev["category"], ev["category"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 Напомни мне", callback_data=f"subev:{ev['id']}"),
            InlineKeyboardButton("🔗 Регистрация", url=ev.get("external_url") or "https://t.me/nextquest_bot"),
        ]])
        await update.message.reply_text(
            f"{cat} *{ev['title']}*\n📍 {ev['location_city']} · 🗓 {date}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def handle_subev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split(":")[1])
    tg_id = query.from_user.id
    existing = supabase.table("subscriptions").select("id").eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        return await query.answer("Уже подписан!", show_alert=True)
    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    get_or_create_user(tg_id, query.from_user.username)
    await query.answer("🔔 Напоминание установлено!", show_alert=True)


# ─── App setup ───────────────────────────────────────────────

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    wizard = ConversationHandler(
        entry_points=[CommandHandler("new_event", cmd_new_event)],
        states={
            EV_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_title)],
            EV_CATEGORY:   [CallbackQueryHandler(ev_get_category,  pattern="^cat:")],
            EV_YEAR:       [CallbackQueryHandler(ev_year,           pattern="^sy:")],
            EV_MONTH:      [CallbackQueryHandler(ev_month,          pattern="^sm:")],
            EV_DAY:        [CallbackQueryHandler(ev_day,            pattern="^sd:")],
            EV_HOUR:       [CallbackQueryHandler(ev_hour,           pattern="^sh:")],
            EV_MINUTE:     [CallbackQueryHandler(ev_minute,         pattern="^smin:")],
            EV_END_CHOICE: [CallbackQueryHandler(ev_end_choice,     pattern="^end:")],
            EV_END_YEAR:   [CallbackQueryHandler(ev_end_year,       pattern="^ey:")],
            EV_END_MONTH:  [CallbackQueryHandler(ev_end_month,      pattern="^em:")],
            EV_END_DAY:    [CallbackQueryHandler(ev_end_day,        pattern="^ed:")],
            EV_END_HOUR:   [CallbackQueryHandler(ev_end_hour,       pattern="^eh:")],
            EV_END_MINUTE: [CallbackQueryHandler(ev_end_minute,     pattern="^emin:")],
            EV_CITY:       [CallbackQueryHandler(ev_get_city,       pattern="^city:")],
            EV_ADDRESS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_address)],
            EV_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_desc)],
            EV_PHOTO:      [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ev_get_photo)],
            EV_LIMIT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_limit)],
            EV_URL:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_url)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (u.message.reply_text("Отменено."), ConversationHandler.END))],
        allow_reentry=True,
    )

    app.add_handler(wizard)
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("pending",  cmd_pending))
    app.add_handler(CommandHandler("my_events", cmd_my_events))
    app.add_handler(CommandHandler("events",   cmd_events))
    app.add_handler(CommandHandler("my",       cmd_my_subscriptions))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe_categories))

    app.add_handler(CallbackQueryHandler(handle_moderation_callback,      pattern="^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(handle_organizer_event_callback,  pattern="^cancel_ev:"))
    app.add_handler(CallbackQueryHandler(ev_submit_callback,               pattern="^ev_(submit|cancel)$"))
    app.add_handler(CallbackQueryHandler(handle_unsub_callback,            pattern="^unsub:"))
    app.add_handler(CallbackQueryHandler(handle_subcat_callback,           pattern="^subcat:"))
    app.add_handler(CallbackQueryHandler(handle_subev_callback,            pattern="^subev:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_reason))

    return app


if __name__ == "__main__":
    application = build_application()
    logger.info("NextQuest bot started.")
    application.run_polling()
