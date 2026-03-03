"""
OTP Polling Engine.
Runs as a background job, polling all active user links and sending OTPs
to their groups via their bot tokens.
"""

import time
import html as html_lib
import httpx
from datetime import datetime, timezone
from telegram.ext import ContextTypes

import database as db
import encryption
from panel_client import PanelSession, SERVICE_EMOJIS
from config import LOGIN_REFRESH, ADMIN_CONTACT

# ============================================
# STATE
# ============================================

# Active sessions: link_id -> PanelSession
_sessions = {}
_otps_sent = 0
_poll_count = 0
_start_time = time.time()

# ============================================
# OTP MESSAGE TEMPLATE
# ============================================

OTP_TEMPLATE = (
    "\U0001f4e8 <b>New OTP Received</b> {flag}\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "\U0001f4cc <b>Service:</b> {service_emoji} {service}\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "\U0001f4de <b>Number:</b> <code>{number}</code>\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "\U0001f513 <b>OTP:</b> <code>{otp}</code>\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "\U0001f4ac <b>Message:</b>\n"
    "<blockquote>{message}</blockquote>\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "<i>IVASMS OTP Sender</i>"
)


def build_otp_message(msg_data):
    """Format an OTP message from SMS data."""
    number = msg_data["number"]
    masked = f"+{number[:2]}***{number[-4:]}" if len(number) > 5 else number
    service = msg_data["service"]
    service_emoji = SERVICE_EMOJIS.get(service, "\u2753")

    text = OTP_TEMPLATE
    text = text.replace("{flag}", msg_data["flag"])
    text = text.replace("{service_emoji}", service_emoji)
    text = text.replace("{service}", html_lib.escape(service))
    text = text.replace("{number}", html_lib.escape(masked))
    text = text.replace("{otp}", html_lib.escape(msg_data["otp"]))
    text = text.replace("{message}", html_lib.escape(msg_data["sms"]))
    return text


async def send_via_bot_token(bot_token, chat_id, text, parse_mode="HTML"):
    """Send a Telegram message using a specific bot token (via HTTP API)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        return data.get("ok", False)


# ============================================
# MAIN POLL JOB
# ============================================

async def poll_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job: poll all active links for new OTPs."""
    global _poll_count, _otps_sent

    try:
        active_links = await db.get_active_links()

        for link in active_links:
            link_id = link["link_id"]
            bot_token_enc = link["bot_token"]
            group_id = link["group_id"]
            panel_username_enc = link["panel_username"]
            panel_password_enc = link["panel_password"]
            user_id = link["user_id"]
            end_date_str = link.get("end_date")
            sub_active = link.get("sub_active")

            # ---- Check subscription validity ----
            if not sub_active or not end_date_str:
                await _handle_expired(link, user_id, context)
                continue

            try:
                end_dt = datetime.fromisoformat(end_date_str)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if end_dt < datetime.now(timezone.utc):
                    await db.revoke_subscription(user_id)
                    await _handle_expired(link, user_id, context)
                    continue
            except Exception:
                pass

            # ---- Decrypt credentials ----
            try:
                bot_token = encryption.decrypt(bot_token_enc)
                panel_user = encryption.decrypt(panel_username_enc)
                panel_pass = encryption.decrypt(panel_password_enc)
            except Exception:
                continue

            # ---- Get or create session ----
            if link_id not in _sessions:
                _sessions[link_id] = PanelSession(panel_user, panel_pass)

            session = _sessions[link_id]
            now = time.time()

            # ---- Login or refresh ----
            if session.csrf is None or (now - session.last_login) >= LOGIN_REFRESH:
                success = await session.login()
                if not success:
                    continue

            # ---- Fetch SMS ----
            try:
                messages = await session.fetch_sms()
            except Exception:
                session.csrf = None  # Force re-login next cycle
                continue

            # ---- Process new messages ----
            for msg in messages:
                msg_hash = msg["id"]
                is_processed = await db.is_message_processed(link_id, msg_hash)
                if not is_processed:
                    await db.mark_message_processed(link_id, msg_hash)
                    text = build_otp_message(msg)
                    try:
                        await send_via_bot_token(bot_token, group_id, text)
                        _otps_sent += 1
                    except Exception:
                        pass

        _poll_count += 1

        # Periodic cleanup (every ~1 hour at 5s interval = 720 polls)
        if _poll_count % 720 == 0:
            await db.cleanup_old_processed(days=7)

    except Exception as e:
        print(f"\u274c Poll engine error: {e}")
        import traceback
        traceback.print_exc()


async def _handle_expired(link, user_id, context):
    """Handle an expired subscription: stop fetching and notify user."""
    link_id = link["link_id"]
    await db.set_fetching(link["bot_id"], False)
    if link_id in _sessions:
        await _sessions[link_id].close()
        del _sessions[link_id]
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "\u26a0\ufe0f <b>Subscription Expired</b>\n"
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                "Your subscription has expired and OTP fetching has been stopped.\n\n"
                f"Contact {ADMIN_CONTACT} to renew."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ============================================
# ENGINE UTILITIES
# ============================================

def get_engine_stats():
    """Return current engine statistics."""
    return {
        "otps_sent": _otps_sent,
        "poll_count": _poll_count,
        "active_sessions": len(_sessions),
        "uptime": int(time.time() - _start_time),
    }


async def stop_session(link_id):
    """Stop and remove a specific session."""
    if link_id in _sessions:
        await _sessions[link_id].close()
        del _sessions[link_id]
