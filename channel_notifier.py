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
BOT_USERNAME   = os.environ.get("BOT_USERNAME", "nextquest_bot")

CATEGORIES = {
    "boardgames": "🎲 Board Games",
    "larp":       "⚔️ LARP",
    "festival":   "🎪 Festival",
    "rpg":        "🎭 RPG",
    "cosplay":    "👗 Cosplay",
    "other":      "🃏 Other",
}

# ── Bot instance ──────────────────────────────────────────────
bot: telegram.Bot | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    bot = telegram.Bot(token=BOT_TOKEN)
    logger.info("Channel notifier started.")
    yield

app = FastAPI(lifespan=lifespan)


# ── Message builders ──────────────────────────────────────────

def build_new_event_message(ev: dict) -> str:
    date_str = ev["date_start"][:16].replace("T", " ")
    end_str  = f" → {ev['date_end'][:16].replace('T', ' ')}" if ev.get("date_end") else ""
    cat      = CATEGORIES.get(ev.get("category", "other"), "🎪 Event")
    url_line = f"\n🔗 {ev['external_url']}" if ev.get("external_url") else ""

    return (
        f"✨ *New event!*\n\n"
        f"*{ev['title']}*\n"
        f"{cat}\n"
        f"🗓 {date_str}{end_str}\n"
        f"📍 {ev.get('location_city', '')} · {ev.get('location_address', '')}{url_line}\n\n"
        f"{ev.get('description', '')[:400]}{'...' if len(ev.get('description', '')) > 400 else ''}\n\n"
        f"🔔 Subscribe for reminders: t.me/{BOT_USERNAME}?start=event_{ev['id']}\n"
        f"🌐 {SITE_URL}/events/{ev['id']}"
    )

def build_updated_event_message(ev: dict) -> str:
    date_str = ev["date_start"][:16].replace("T", " ")
    end_str  = f" → {ev['date_end'][:16].replace('T', ' ')}" if ev.get("date_end") else ""
    cat      = CATEGORIES.get(ev.get("category", "other"), "🎪 Event")

    return (
        f"✏️ *Event updated*\n\n"
        f"*{ev['title']}*\n"
        f"{cat}\n"
        f"🗓 {date_str}{end_str}\n"
        f"📍 {ev.get('location_city', '')} · {ev.get('location_address', '')}\n\n"
        f"🌐 {SITE_URL}/events/{ev['id']}"
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

    is_new_publish = (
        event_type == "INSERT"
        or (event_type == "UPDATE" and old_status != "published")
    )
    is_update = (
        event_type == "UPDATE"
        and old_status == "published"
    )

    try:
        if is_new_publish:
            text = build_new_event_message(record)
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

        elif is_update:
            text = build_updated_event_message(record)
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode="Markdown",
            )
            logger.info(f"Posted update for event {record.get('id')} to channel.")

    except telegram.error.TelegramError as e:
        logger.error(f"Telegram error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
