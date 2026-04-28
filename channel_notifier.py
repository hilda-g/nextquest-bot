"""
NextQuest — Channel Notifier  v1.0
====================================
Runs as a separate FastAPI process alongside bot.py.
Supabase calls this webhook whenever an event row is INSERT-ed or UPDATE-d
with status = 'published'.

Setup:
    pip install fastapi uvicorn python-telegram-bot python-dotenv

Run:
    uvicorn channel_notifier:app --host 0.0.0.0 --port 8000

.env additions needed:
    CHANNEL_ID=-1001234567890   # numeric ID of your Telegram channel
    WEBHOOK_SECRET=changeme     # Supabase will send this in X-Webhook-Secret header
"""

import os
import logging
import hashlib
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import telegram

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
BOT_TOKEN      = os.environ["BOT_TOKEN"]
CHANNEL_ID     = os.environ["CHANNEL_ID"]          # e.g. -1001234567890
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SITE_URL       = os.environ.get("SITE_URL", "https://nextquest.today")
BOT_USERNAME   = os.environ.get("BOT_USERNAME", "NextQuestbot")

CATEGORIES = {
    "boardgames": "🎲 Board Games",
    "rpg":        "🧙 Tabletop RPG",
    "larp":       "⚔️ LARP",
    "festival":   "🎪 Festival",
    "cosplay":    "👽 Cosplay",
    "lectures":   "🔭 Lectures",
    "market":     "🛍️ Market",
    "other":      "🃏 Other",
}

FORMATS = {
    "private":   "🔒 Private",
    "community": "✨ Community",
    "official":  "🎉 Official",
}

def maps_url(city: str, address: str) -> str:
    from urllib.parse import quote
    q = quote(f"{address} {city}".strip())
    return f"https://maps.google.com/?q={q}"

# ── Bot instance ──────────────────────────────────────────────
bot: telegram.Bot | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    bot = telegram.Bot(token=BOT_TOKEN)
    logger.info("Channel notifier started.")
    yield

app = FastAPI(lifespan=lifespan)

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "https://nextquest.today").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── Message builders ──────────────────────────────────────────

def build_google_calendar_url(ev: dict) -> str:
    """Generate a Google Calendar 'Add to Calendar' link from event data."""
    from urllib.parse import quote
    # Format: YYYYMMDDTHHmmss
    start = ev["date_start"].replace("-", "").replace(":", "").replace(" ", "T")[:15] + "00"
    if ev.get("date_end"):
        end = ev["date_end"].replace("-", "").replace(":", "").replace(" ", "T")[:15] + "00"
    else:
        end = start  # same time if no end
    title    = quote(ev.get("title", ""))
    location = quote(f"{ev.get('location_city', '')} {ev.get('location_address', '')}".strip())
    details  = quote(f"{SITE_URL}/events/{ev['id']}")
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={title}&dates={start}/{end}&location={location}&details={details}"
    )

MONTHS_EN  = ["January","February","March","April","May","June",
              "July","August","September","October","November","December"]
WEEKDAYS_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

def format_date_human(iso: str) -> str:
    """Convert ISO datetime to: Wednesday, 21 April · 16:30"""
    from datetime import datetime as dt
    d = dt.fromisoformat(iso[:16])
    weekday = WEEKDAYS_EN[d.weekday()]
    month   = MONTHS_EN[d.month - 1]
    return f"{weekday}, {d.day} {month} · {d.strftime('%H:%M')}"

def build_new_event_message(ev: dict) -> str:
    date_str  = format_date_human(ev["date_start"])
    end_str   = f" → {format_date_human(ev['date_end'])}" if ev.get("date_end") else ""
    cat       = CATEGORIES.get(ev.get("category", "other"), "🎪 Event")
    fmt       = FORMATS.get(ev.get("format", "official"), "🎉 Official")
    limit     = f"{ev['max_participants']} spots" if ev.get("max_participants") else "no limit"
    location  = f"{ev.get('location_city', '')} · {ev.get('location_address', '')}"
    maps_link = f"[📍 {location}]({maps_url(ev.get('location_city', ''), ev.get('location_address', ''))})"

    organizer_name = ev.get("organizer_username") or ""
    org_link = ev.get("organizer_link") or ""

    if organizer_name and org_link:
        organizer_line = f"\n🎪 Organizer: [{organizer_name}]({org_link})"
    elif organizer_name:
        organizer_line = f"\n🎪 Organizer: {organizer_name}"
    else:
        organizer_line = ""

    if ev.get("external_url"):
        contact_line = f"\n📋 Contact: [Register]({ev['external_url']})"
    elif ev.get("organizer_contacts"):
        contact_line = f"\n📋 Contact: {ev['organizer_contacts']}"
    else:
        contact_line = ""

    description  = ev.get("description", "")[:400] + ("..." if len(ev.get("description", "")) > 400 else "")
    gcal_url     = build_google_calendar_url(ev)
    event_url    = f"{SITE_URL}/events/{ev['id']}"
    remind_url   = f"t.me/{BOT_USERNAME}?start=event_{ev['id']}"
    bot_start_url = f"https://t.me/{BOT_USERNAME}?start=start"

    return (
        f"*{ev['title'].upper()}*\n"
        f"{cat} · {fmt}\n"
        f"📅 {date_str}{end_str}\n"
        f"{maps_link}\n"
        f"👥 {limit}"
        f"{organizer_line}"
        f"{contact_line}\n\n"
        f"{description}\n\n"
        f"——————————————————\n\n"
        f"[🔔 Подписаться на напоминание]({remind_url})\n"
        f"[🌐 Страница события]({event_url})\n"
        f"[📅 Добавить в Google Календарь]({gcal_url})\n"
        f"⭐ Хочешь добавить своё событие? [Напиши боту!]({bot_start_url})"
    )



# ── Webhook endpoint ──────────────────────────────────────────

@app.post("/webhook/event")
async def handle_event_webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
):
    # 1. Verify secret (optional but recommended)
    if WEBHOOK_SECRET:
        if x_webhook_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret")

    payload = await request.json()

    # Supabase sends { type: "INSERT"|"UPDATE", record: {...}, old_record: {...} }
    event_type = payload.get("type")          # "INSERT" or "UPDATE"
    record     = payload.get("record", {})
    old_record = payload.get("old_record", {})

    if not record:
        return {"ok": True, "skipped": "no record"}

    status     = record.get("status")
    old_status = old_record.get("status") if old_record else None

    # Only act when status is published
    if status != "published":
        return {"ok": True, "skipped": f"status={status}"}

    # Only post on first approval. Edits/cancellations do NOT auto-post.
    is_new_publish = (
        event_type == "INSERT"
        or (event_type == "UPDATE" and old_status != "published")
    )

    if not is_new_publish:
        return {"ok": True, "skipped": "not a new publish"}

    try:
        text  = build_new_event_message(record)
        cover = record.get("cover_image_url")

        if cover:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=cover,
                caption=text,
                parse_mode="Markdown",
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        logger.info(f"Posted new event {record.get('id')} to channel.")

    except telegram.error.TelegramError as e:
        logger.error(f"Telegram error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


# ── Manual post endpoint (called by website admin panel) ──────────────

@app.post("/post/manual")
async def post_manual(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
):
    """Called by the website admin panel to manually post an event to the channel."""
    if WEBHOOK_SECRET:
        if x_webhook_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret")

    payload = await request.json()
    ev = payload.get("record") or payload

    if not ev:
        raise HTTPException(status_code=400, detail="No event data")

    text  = build_new_event_message(ev)
    cover = ev.get("cover_image_url")

    try:
        if cover:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=cover,
                caption=text,
                parse_mode="Markdown",
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        logger.info(f"Manual post sent for event {ev.get('id')}")
    except telegram.error.TelegramError as e:
        logger.error(f"Telegram error on manual post: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
