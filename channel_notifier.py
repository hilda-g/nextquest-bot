"""
NextQuest — Channel Notifier  v2.0
====================================
Runs as a separate FastAPI process alongside bot.py.
Supabase calls this webhook whenever an event row is INSERT-ed or UPDATE-d.

Changes from v1.0:
  - Auto-post on edit (published → published) has been REMOVED.
    Only first-publish triggers an automatic channel post.
  - New endpoint POST /post/manual  — called by the web admin panel
    when the admin explicitly chooses to post an event to the channel.
  - Shared helper build_channel_post_text() used by both code paths.
  - Supabase client added (needed for /post/manual to fetch event by ID).

Setup:
    pip install fastapi uvicorn python-telegram-bot python-dotenv supabase

Run:
    uvicorn channel_notifier:app --host 0.0.0.0 --port 8000

.env:
    BOT_TOKEN=...
    CHANNEL_ID=-1001234567890
    WEBHOOK_SECRET=changeme
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY=eyJ...
    SITE_URL=https://nextquest.today        # optional
    BOT_USERNAME=nextquest_bot              # optional
"""

import os
import logging
from contextlib import asynccontextmanager
from pydantic import BaseModel

from fastapi import FastAPI, Request, HTTPException, Header
from dotenv import load_dotenv
from supabase import create_client, Client
import telegram

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
BOT_TOKEN      = os.environ["BOT_TOKEN"]
CHANNEL_ID     = os.environ["CHANNEL_ID"]          # e.g. -1001234567890
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_SERVICE_KEY"]
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

# ── Clients ───────────────────────────────────────────────────
bot: telegram.Bot | None = None
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    bot = telegram.Bot(token=BOT_TOKEN)
    logger.info("Channel notifier started.")
    yield


app = FastAPI(lifespan=lifespan)


# ── Message builder (single source of truth) ─────────────────

def build_channel_post_text(ev: dict) -> str:
    """
    Builds the standard channel post text for any event.
    Used by both the auto-post-on-publish path and the manual /post/manual path.
    """
    date_str = ev["date_start"][:16].replace("T", " ")
    end_str  = f" → {ev['date_end'][:16].replace('T', ' ')}" if ev.get("date_end") else ""
    cat      = CATEGORIES.get(ev.get("category", "other"), "🎪 Event")
    url_line = f"\n🔗 {ev['external_url']}" if ev.get("external_url") else ""
    desc     = ev.get("description", "")
    desc_str = desc[:400] + ("..." if len(desc) > 400 else "")

    return (
        f"✨ *Событие в календаре*\n\n"
        f"*{ev['title']}*\n"
        f"{cat}\n"
        f"🗓 {date_str}{end_str}\n"
        f"📍 {ev.get('location_city', '')} · {ev.get('location_address', '')}{url_line}\n\n"
        f"{desc_str}\n\n"
        f"🔔 Подписаться на напоминание: t.me/{BOT_USERNAME}?start=event_{ev['id']}\n"
        f"🌐 {SITE_URL}/events/{ev['id']}"
    )


# ── Shared send helper ────────────────────────────────────────

async def _send_to_channel(ev: dict) -> int:
    """
    Posts ev to CHANNEL_ID. Returns the Telegram message_id.
    Raises telegram.error.TelegramError on failure.
    """
    text  = build_channel_post_text(ev)
    cover = ev.get("cover_image_url")

    if cover:
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=cover,
            caption=text,
            parse_mode="Markdown",
        )
    else:
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )
    return msg.message_id


# ── Auth helper ───────────────────────────────────────────────

def _verify_secret(x_webhook_secret: str | None):
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")


# ── Supabase webhook endpoint ─────────────────────────────────

@app.post("/webhook/event")
async def handle_event_webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
):
    _verify_secret(x_webhook_secret)

    payload    = await request.json()
    event_type = payload.get("type")           # "INSERT" or "UPDATE"
    record     = payload.get("record", {})
    old_record = payload.get("old_record", {})

    if not record:
        return {"ok": True, "skipped": "no record"}

    status     = record.get("status")
    old_status = old_record.get("status") if old_record else None

    if status != "published":
        return {"ok": True, "skipped": f"status={status}"}

    # Only post automatically on first publish.
    # Edits to an already-published event no longer trigger a channel post —
    # the admin must use the "Create Post" button in the web admin panel instead.
    is_new_publish = (
        event_type == "INSERT"
        or (event_type == "UPDATE" and old_status != "published")
    )

    if not is_new_publish:
        return {"ok": True, "skipped": "edit to published event — no auto-post"}

    try:
        message_id = await _send_to_channel(record)
        logger.info(f"Auto-posted new event {record.get('id')} to channel (msg {message_id}).")
    except telegram.error.TelegramError as e:
        logger.error(f"Telegram error on auto-post: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "message_id": message_id}


# ── Manual post endpoint (called by web admin panel) ──────────

class ManualPostRequest(BaseModel):
    event_id: str


@app.post("/post/manual")
async def handle_manual_post(
    body: ManualPostRequest,
    x_webhook_secret: str | None = Header(default=None),
):
    """
    Called by the website backend when an admin clicks "Create Post".
    Fetches the event from Supabase, builds the post, and sends it to the channel.
    No de-duplication — if called twice, two posts appear (by design).
    """
    _verify_secret(x_webhook_secret)

    # Fetch event from Supabase
    res = supabase.table("events").select("*").eq("id", body.event_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Event not found")

    ev = res.data[0]

    try:
        message_id = await _send_to_channel(ev)
        logger.info(f"Manual post: event {ev['id']} → channel (msg {message_id}).")
    except telegram.error.TelegramError as e:
        logger.error(f"Telegram error on manual post: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "message_id": message_id}


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
