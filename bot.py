"""
QuestRadar Telegram Bot
python-telegram-bot v20+ (async)

Covers:
  UC-00  Add organizer (whitelist)
  UC-01  Moderator approve/reject event
  UC-02  Moderator edit/cancel event
  UC-03  Moderator stats
  UC-04  Organizer submit new event (step-by-step wizard)
  UC-05  Organizer edit own event
  UC-06  Organizer cancel own event
  UC-07  /start deep-link (from website notify button)
  UC-08  Participant subscribe to event
  UC-09  Participant unsubscribe
  UC-10  Category subscription

Install:
  pip install python-telegram-bot==20.* supabase python-dotenv

.env:
  BOT_TOKEN=...
  SUPABASE_URL=https://xxx.supabase.co
  SUPABASE_SERVICE_KEY=...      # service_role key (bypasses RLS)
  MODERATOR_TG_ID=123456789
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN       = os.environ["BOT_TOKEN"]
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_SERVICE_KEY"]
MODERATOR_ID    = int(os.environ["MODERATOR_TG_ID"])

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = {
    "boardgames": "🎲 Board Games",
    "larp":        "⚔️ LARP",
    "festival":    "🎪 Festival",
    "rpg":         "🎭 RPG",
    "cosplay":     "👗 Cosplay",
    "other":       "🃏 Other",
}

# ─── ConversationHandler states ──────────────────────────────
(
    EV_TITLE, EV_CATEGORY, EV_DATE_START, EV_DATE_END,
    EV_CITY, EV_ADDRESS, EV_DESC, EV_PHOTO, EV_LIMIT, EV_URL
) = range(10)


# ─── Helpers ─────────────────────────────────────────────────

def get_or_create_user(tg_id: int, username: str | None, lang: str = "ru"):
    """Ensure user row exists in DB."""
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    if res.data:
        return res.data[0]
    new_user = {"tg_id": tg_id, "tg_username": username, "role": "participant", "language": lang}
    supabase.table("users").insert(new_user).execute()
    return new_user

def is_moderator(tg_id: int) -> bool:
    res = supabase.table("users").select("role").eq("tg_id", tg_id).execute()
    return bool(res.data and res.data[0]["role"] == "moderator")

def is_organizer(tg_id: int) -> bool:
    res = supabase.table("users").select("role").eq("tg_id", tg_id).execute()
    return bool(res.data and res.data[0]["role"] in ("organizer", "moderator"))

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


# ─── /start ──────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username)

    # Deep-link: /start event_123  →  subscribe to event
    if ctx.args and ctx.args[0].startswith("event_"):
        event_id = int(ctx.args[0].split("_")[1])
        await _subscribe_to_event(update, ctx, event_id)
        return

    await update.message.reply_text(
        "👋 Welcome to *QuestRadar*!\n\n"
        "Available commands:\n"
        "/events — browse upcoming events\n"
        "/my — my subscriptions\n"
        "/subscribe — subscribe to categories\n\n"
        "_Organizers:_ /new\\_event · /my\\_events\n"
        "_Moderators:_ /pending · /stats · /add\\_organizer",
        parse_mode="Markdown"
    )


# ─── Moderator: add organizer  (UC-00) ───────────────────────

async def cmd_add_organizer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorised.")
    if not ctx.args:
        return await update.message.reply_text("Usage: /add_organizer @username")
    
    username = ctx.args[0].lstrip("@")
    # Try to find user by username
    res = supabase.table("users").select("*").eq("tg_username", username).execute()
    if not res.data:
        return await update.message.reply_text(
            f"❌ User @{username} not found. They must /start the bot first."
        )
    supabase.table("users").update({"role": "organizer"}).eq("tg_username", username).execute()
    await update.message.reply_text(f"✅ @{username} is now an organizer!")


# ─── Moderator: stats  (UC-03) ───────────────────────────────

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorised.")
    
    published = supabase.table("events").select("id", count="exact").eq("status", "published").execute()
    pending   = supabase.table("events").select("id", count="exact").eq("status", "pending").execute()
    subs      = supabase.table("subscriptions").select("id", count="exact").execute()
    users_cnt = supabase.table("users").select("id", count="exact").execute()
    
    await update.message.reply_text(
        f"📊 *QuestRadar stats*\n\n"
        f"✅ Published events: {published.count}\n"
        f"⏳ Pending approval: {pending.count}\n"
        f"👥 Total users: {users_cnt.count}\n"
        f"🔔 Total subscriptions: {subs.count}",
        parse_mode="Markdown"
    )


# ─── Moderator: pending queue  (UC-01) ───────────────────────

async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_moderator(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorised.")
    
    res = supabase.table("events").select("*").eq("status", "pending").order("created_at").execute()
    if not res.data:
        return await update.message.reply_text("✅ No events pending approval.")
    
    for ev in res.data:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{ev['id']}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{ev['id']}"),
        ]])
        text = f"[#{ev['id']}] {event_preview_text(ev)}"
        if ev.get("cover_image_url"):
            await update.message.reply_photo(ev["cover_image_url"], caption=text,
                                              reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_moderation_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, event_id = query.data.split(":")
    event_id = int(event_id)

    if action == "approve":
        supabase.table("events").update({"status": "published"}).eq("id", event_id).execute()
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"✅ Event #{event_id} published!")
        
        # Notify organizer
        ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
        await ctx.bot.send_message(
            ev["organizer_tg_id"],
            f"🎉 Your event *{ev['title']}* has been *approved* and is now live!",
            parse_mode="Markdown"
        )
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
        # Store context for reject reason
        ctx.user_data["reject_event_id"] = event_id
        await query.message.reply_text(
            f"❌ Rejecting event #{event_id}.\nPlease send the reason:"
        )
        ctx.user_data["awaiting_reject_reason"] = True


async def handle_reject_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_reject_reason"):
        return
    
    reason   = update.message.text
    event_id = ctx.user_data.pop("reject_event_id")
    ctx.user_data.pop("awaiting_reject_reason")
    
    supabase.table("events").update({
        "status": "pending",   # keep as pending so organizer can re-edit
        "reject_reason": reason
    }).eq("id", event_id).execute()

    ev = supabase.table("events").select("*").eq("id", event_id).single().execute().data
    await ctx.bot.send_message(
        ev["organizer_tg_id"],
        f"❌ Your event *{ev['title']}* was rejected.\n\nReason: {reason}\n\n"
        "You can edit it with /my_events and resubmit.",
        parse_mode="Markdown"
    )
    await update.message.reply_text("Done. Organizer notified.")


# ─── Organizer: new event wizard  (UC-04) ────────────────────

async def cmd_new_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_organizer(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not an organizer. Contact the moderator.")
    
    ctx.user_data["new_event"] = {}
    await update.message.reply_text("📝 Let's create a new event!\n\nStep 1/10: *Event title* (in English)?", parse_mode="Markdown")
    return EV_TITLE

async def ev_get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["title"] = update.message.text
    
    buttons = [[InlineKeyboardButton(label, callback_data=f"cat:{cat_id}")]
               for cat_id, label in CATEGORIES.items()]
    await update.message.reply_text(
        "Step 2/10: *Category?*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return EV_CATEGORY

async def ev_get_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.split(":")[1]
    ctx.user_data["new_event"]["category"] = cat
    await query.message.reply_text(
        "Step 3/10: *Start date and time*\nFormat: `2026-05-10 18:00`",
        parse_mode="Markdown"
    )
    return EV_DATE_START

async def ev_get_date_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        dt = datetime.strptime(update.message.text.strip(), "%Y-%m-%d %H:%M")
        ctx.user_data["new_event"]["date_start"] = dt.isoformat()
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Try: `2026-05-10 18:00`", parse_mode="Markdown")
        return EV_DATE_START
    
    await update.message.reply_text(
        "Step 4/10: *End date* (optional, for multi-day)\n"
        "Format: `2026-05-12 20:00` or send `-` to skip",
        parse_mode="Markdown"
    )
    return EV_DATE_END

async def ev_get_date_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        try:
            dt = datetime.strptime(txt, "%Y-%m-%d %H:%M")
            ctx.user_data["new_event"]["date_end"] = dt.isoformat()
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Try `2026-05-12 20:00` or `-`", parse_mode="Markdown")
            return EV_DATE_END
    
    buttons = [[InlineKeyboardButton(c, callback_data=f"city:{c}")]
               for c in ["Nicosia", "Limassol", "Larnaca", "Paphos", "Other"]]
    await update.message.reply_text("Step 5/10: *City?*", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    return EV_CITY

async def ev_get_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["new_event"]["location_city"] = query.data.split(":")[1]
    await query.message.reply_text("Step 6/10: *Full address?*\nExample: `The Brew, Stasinos Ave 10`", parse_mode="Markdown")
    return EV_ADDRESS

async def ev_get_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["location_address"] = update.message.text
    await update.message.reply_text("Step 7/10: *Description* (a few sentences about the event):", parse_mode="Markdown")
    return EV_DESC

async def ev_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_event"]["description"] = update.message.text
    await update.message.reply_text("Step 8/10: *Cover photo* — send an image or URL:", parse_mode="Markdown")
    return EV_PHOTO

async def ev_get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        # Download and upload to Supabase Storage
        photo  = update.message.photo[-1]
        file   = await photo.get_file()
        path   = f"events/{update.effective_user.id}_{photo.file_id}.jpg"
        data   = await file.download_as_bytearray()
        supabase.storage.from_("event-covers").upload(path, bytes(data), {"content-type": "image/jpeg"})
        url = supabase.storage.from_("event-covers").get_public_url(path)
        ctx.user_data["new_event"]["cover_image_url"] = url
    elif update.message.text and update.message.text.startswith("http"):
        ctx.user_data["new_event"]["cover_image_url"] = update.message.text.strip()
    else:
        await update.message.reply_text("❌ Please send a photo or a valid URL.")
        return EV_PHOTO
    
    await update.message.reply_text("Step 9/10: *Participant limit?*\nSend a number or `-` for no limit:", parse_mode="Markdown")
    return EV_LIMIT

async def ev_get_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        if not txt.isdigit():
            await update.message.reply_text("❌ Send a number or `-`.")
            return EV_LIMIT
        ctx.user_data["new_event"]["max_participants"] = int(txt)
    
    await update.message.reply_text("Step 10/10: *Registration URL* (Telegram, Eventbrite, etc.) or `-`:", parse_mode="Markdown")
    return EV_URL

async def ev_get_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != "-":
        ctx.user_data["new_event"]["external_url"] = txt
    
    ev = ctx.user_data["new_event"]
    ev["organizer_tg_id"] = update.effective_user.id
    ev["status"] = "pending"
    
    preview = event_preview_text(ev)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📤 Submit for moderation", callback_data="ev_submit"),
        InlineKeyboardButton("🗑 Cancel",                callback_data="ev_cancel"),
    ]])
    await update.message.reply_text(
        f"Preview:\n\n{preview}\n\nLooks good?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def ev_submit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "ev_cancel":
        ctx.user_data.pop("new_event", None)
        return await query.message.reply_text("❌ Cancelled.")
    
    ev = ctx.user_data.pop("new_event", {})
    if not ev:
        return await query.message.reply_text("❌ Session expired. Please /new_event again.")
    
    res = supabase.table("events").insert(ev).execute()
    event_id = res.data[0]["id"]
    
    await query.message.reply_text(f"✅ Event #{event_id} submitted for moderation!")
    
    # Notify moderator
    await ctx.bot.send_message(
        MODERATOR_ID,
        f"📬 New event pending approval!\n\n{event_preview_text(ev)}\n\n"
        f"Use /pending to review.",
        parse_mode="Markdown"
    )


# ─── Organizer: my events  (UC-05, UC-06) ────────────────────

async def cmd_my_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_organizer(update.effective_user.id):
        return await update.message.reply_text("⛔ Not an organizer.")
    
    res = supabase.table("events").select("*")\
          .eq("organizer_tg_id", update.effective_user.id)\
          .order("date_start", desc=True).execute()
    
    if not res.data:
        return await update.message.reply_text("You have no events.")
    
    for ev in res.data[:5]:
        status_icon = {"published": "✅", "pending": "⏳", "cancelled": "❌"}.get(ev["status"], "?")
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Edit",   callback_data=f"edit:{ev['id']}"),
            InlineKeyboardButton("🚫 Cancel", callback_data=f"cancel_ev:{ev['id']}"),
        ]])
        await update.message.reply_text(
            f"{status_icon} *{ev['title']}* (#{ev['id']})\n"
            f"{ev['date_start'][:10]} · {ev['location_city']}",
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
        return await query.message.reply_text("⛔ Not your event.")
    
    if action == "cancel_ev":
        supabase.table("events").update({"status": "cancelled"}).eq("id", event_id).execute()
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"🚫 Event *{ev['title']}* cancelled.", parse_mode="Markdown")
        
        # Notify subscribers
        subs = supabase.table("subscriptions").select("tg_id").eq("event_id", event_id).execute()
        for s in subs.data:
            try:
                await ctx.bot.send_message(
                    s["tg_id"],
                    f"❌ *{ev['title']}* has been cancelled.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    
    elif action == "edit":
        await query.message.reply_text(
            f"Editing event #{event_id}.\n\n"
            "Note: changes to date/location require re-approval.\n\n"
            "What would you like to change? (send updated description, or use /new_event to recreate)"
        )


# ─── Participant: subscribe to event  (UC-08) ────────────────

async def _subscribe_to_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE, event_id: int):
    ev = supabase.table("events").select("*").eq("id", event_id).execute()
    if not ev.data:
        return await update.message.reply_text("❌ Event not found.")
    ev = ev.data[0]
    
    tg_id = update.effective_user.id
    existing = supabase.table("subscriptions").select("id")\
               .eq("tg_id", tg_id).eq("event_id", event_id).execute()
    
    if existing.data:
        return await update.message.reply_text("✅ You are already subscribed to this event!")
    
    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    await update.message.reply_text(
        f"🔔 Subscribed to *{ev['title']}*!\n"
        f"You'll get a reminder 7 days before the event.",
        parse_mode="Markdown"
    )


# ─── Participant: manage subscriptions  (UC-09, UC-10) ───────

async def cmd_my_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    subs  = supabase.table("subscriptions").select("*").eq("tg_id", tg_id).execute()
    
    if not subs.data:
        return await update.message.reply_text(
            "You have no subscriptions yet.\n"
            "Visit the website and click 🔔 on any event, or use /subscribe for categories."
        )
    
    lines = []
    buttons = []
    for s in subs.data:
        if s["event_id"]:
            ev = supabase.table("events").select("title").eq("id", s["event_id"]).execute()
            name = ev.data[0]["title"] if ev.data else f"Event #{s['event_id']}"
            lines.append(f"🗓 {name}")
            buttons.append([InlineKeyboardButton(f"Unsub: {name[:30]}", callback_data=f"unsub:{s['id']}")])
        elif s["category"]:
            lines.append(f"📌 Category: {CATEGORIES.get(s['category'], s['category'])}")
            buttons.append([InlineKeyboardButton(f"Unsub: {s['category']}", callback_data=f"unsub:{s['id']}")])
    
    await update.message.reply_text(
        "Your subscriptions:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def handle_unsub_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = int(query.data.split(":")[1])
    supabase.table("subscriptions").delete().eq("id", sub_id).eq("tg_id", query.from_user.id).execute()
    await query.message.reply_text("✅ Unsubscribed.")

async def cmd_subscribe_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    existing = supabase.table("subscriptions").select("category")\
               .eq("tg_id", tg_id).not_.is_("category", "null").execute()
    existing_cats = {s["category"] for s in existing.data}
    
    buttons = []
    for cat_id, label in CATEGORIES.items():
        check = "✅ " if cat_id in existing_cats else ""
        buttons.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"subcat:{cat_id}")])
    buttons.append([InlineKeyboardButton("Done ✔", callback_data="subcat:done")])
    
    await update.message.reply_text(
        "Select categories to subscribe to\n(tap to toggle):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_subcat_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id  = query.from_user.id
    action = query.data.split(":")[1]
    
    if action == "done":
        return await query.message.reply_text("✅ Preferences saved!")
    
    cat = action
    existing = supabase.table("subscriptions").select("id")\
               .eq("tg_id", tg_id).eq("category", cat).execute()
    if existing.data:
        supabase.table("subscriptions").delete().eq("id", existing.data[0]["id"]).execute()
        await query.answer(f"Unsubscribed from {CATEGORIES[cat]}", show_alert=False)
    else:
        supabase.table("subscriptions").insert({"tg_id": tg_id, "category": cat}).execute()
        await query.answer(f"Subscribed to {CATEGORIES[cat]}", show_alert=False)


# ─── Browse events  (UC-07) ──────────────────────────────────

async def cmd_events(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("events").select("*")\
          .eq("status", "published")\
          .gte("date_start", now)\
          .order("date_start").limit(5).execute()
    
    if not res.data:
        return await update.message.reply_text("No upcoming events.")
    
    for ev in res.data:
        date = ev["date_start"][:10]
        city = ev["location_city"]
        cat  = CATEGORIES.get(ev["category"], ev["category"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 Remind me", callback_data=f"subev:{ev['id']}"),
            InlineKeyboardButton("🔗 Register",  url=ev.get("external_url", "https://t.me/questradar")),
        ]])
        await update.message.reply_text(
            f"{cat} *{ev['title']}*\n📍 {city} · 🗓 {date}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def handle_subev_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split(":")[1])
    tg_id = query.from_user.id
    
    existing = supabase.table("subscriptions").select("id")\
               .eq("tg_id", tg_id).eq("event_id", event_id).execute()
    if existing.data:
        return await query.answer("Already subscribed!", show_alert=True)
    
    supabase.table("subscriptions").insert({"tg_id": tg_id, "event_id": event_id}).execute()
    get_or_create_user(tg_id, query.from_user.username)
    await query.answer("🔔 Reminder set!", show_alert=True)


# ─── Reminder sender (called by cron or manually) ────────────

async def send_pending_reminders(application):
    """
    Poll notification_log for tg_ids that need a 7-day reminder.
    Run this from a cron job or call manually for testing.
    
    In production, pg_cron inserts rows into notification_log,
    and this function reads + sends them.
    """
    # Find unsent reminders
    pending = supabase.table("notification_log").select("*, events(*)")\
              .eq("type", "reminder_7d").is_("sent_at", "null").execute()
    
    for row in pending.data:
        ev = row.get("events", {})
        try:
            await application.bot.send_message(
                row["tg_id"],
                f"🔔 Reminder: *{ev.get('title','Event')}* is in 7 days!\n"
                f"📍 {ev.get('location_city')} · {ev.get('location_address')}\n"
                f"🔗 {ev.get('external_url','')}",
                parse_mode="Markdown"
            )
            supabase.table("notification_log").update({"sent_at": datetime.utcnow().isoformat()})\
                    .eq("id", row["id"]).execute()
        except Exception as e:
            logger.warning(f"Reminder failed for {row['tg_id']}: {e}")


# ─── App setup ───────────────────────────────────────────────

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # New event wizard
    wizard = ConversationHandler(
        entry_points=[CommandHandler("new_event", cmd_new_event)],
        states={
            EV_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_title)],
            EV_CATEGORY:   [CallbackQueryHandler(ev_get_category, pattern="^cat:")],
            EV_DATE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_date_start)],
            EV_DATE_END:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_date_end)],
            EV_CITY:       [CallbackQueryHandler(ev_get_city, pattern="^city:")],
            EV_ADDRESS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_address)],
            EV_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_desc)],
            EV_PHOTO:      [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ev_get_photo)],
            EV_LIMIT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_limit)],
            EV_URL:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ev_get_url)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: (u.message.reply_text("Cancelled."), ConversationHandler.END))],
    )

    app.add_handler(wizard)
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("add_organizer",  cmd_add_organizer))
    app.add_handler(CommandHandler("stats",          cmd_stats))
    app.add_handler(CommandHandler("pending",        cmd_pending))
    app.add_handler(CommandHandler("my_events",      cmd_my_events))
    app.add_handler(CommandHandler("events",         cmd_events))
    app.add_handler(CommandHandler("my",             cmd_my_subscriptions))
    app.add_handler(CommandHandler("subscribe",      cmd_subscribe_categories))

    app.add_handler(CallbackQueryHandler(handle_moderation_callback,     pattern="^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(handle_organizer_event_callback, pattern="^(edit|cancel_ev):"))
    app.add_handler(CallbackQueryHandler(ev_submit_callback,              pattern="^ev_(submit|cancel)$"))
    app.add_handler(CallbackQueryHandler(handle_unsub_callback,           pattern="^unsub:"))
    app.add_handler(CallbackQueryHandler(handle_subcat_callback,          pattern="^subcat:"))
    app.add_handler(CallbackQueryHandler(handle_subev_callback,           pattern="^subev:"))

    # Catch reject reason text from moderator
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_reason))

    return app


if __name__ == "__main__":
    application = build_application()
    logger.info("QuestRadar bot started.")
    application.run_polling()
