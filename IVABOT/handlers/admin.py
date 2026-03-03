import html
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, DURATION_MAP, ADMIN_CONTACT
import database as db
from otp_engine import get_engine_stats


def is_admin(user_id):
    return user_id == ADMIN_ID


# ============================================
# /admin - Dashboard
# ============================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stats = await db.get_stats()
    engine = get_engine_stats()
    uptime = engine["uptime"]
    hours, rem = divmod(uptime, 3600)
    minutes, seconds = divmod(rem, 60)

    await update.message.reply_text(
        "\U0001f451 <b>Admin Dashboard</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f465 Total Users: <b>{stats['total_users']}</b>\n"
        f"\U0001f916 Total Bots: <b>{stats['total_bots']}</b>\n"
        f"\U0001f517 Total Panels: <b>{stats['total_panels']}</b>\n"
        f"\U0001f48e Active Subs: <b>{stats['active_subs']}</b>\n"
        f"\U0001f7e2 Fetching Now: <b>{stats['active_fetching']}</b>\n"
        f"\U0001f4e8 OTPs Sent: <b>{engine['otps_sent']}</b>\n"
        f"\U0001f504 Polls: <b>{engine['poll_count']}</b>\n"
        f"\u23f1 Uptime: {hours}h {minutes}m {seconds}s\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "<b>Commands:</b>\n"
        "/subscribe <code>&lt;user_id&gt; &lt;duration&gt;</code>\n"
        "/revoke <code>&lt;user_id&gt;</code>\n"
        "/users \u2014 List all users\n"
        "/broadcast <code>&lt;message&gt;</code>",
        parse_mode="HTML",
    )


# ============================================
# /subscribe <user_id> <duration>
# ============================================

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: /subscribe <code>&lt;user_id&gt; &lt;duration&gt;</code>\n\n"
            f"Durations: {', '.join(DURATION_MAP.keys())}",
            parse_mode="HTML",
        )
        return

    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("\u274c Invalid user ID. Must be a number.")
        return

    duration_key = args[1].lower()
    if duration_key not in DURATION_MAP:
        await update.message.reply_text(
            f"\u274c Invalid duration.\nValid: {', '.join(DURATION_MAP.keys())}"
        )
        return

    duration = DURATION_MAP[duration_key]
    now = datetime.now(timezone.utc)
    end_date = now + timedelta(**duration)

    plan_labels = {
        "1min": "1 Minute", "1h": "1 Hour", "1d": "1 Day",
        "1w": "1 Week", "1m": "1 Month", "2m": "2 Months",
        "3m": "3 Months", "6m": "6 Months", "1y": "1 Year",
    }
    plan_label = plan_labels.get(duration_key, duration_key)

    await db.add_subscription(user_id, plan_label, end_date.isoformat())

    await update.message.reply_text(
        "\u2705 Subscription granted!\n\n"
        f"\U0001f464 User: <code>{user_id}</code>\n"
        f"\U0001f4cb Plan: <b>{plan_label}</b>\n"
        f"\U0001f4c5 Expires: <b>{end_date.strftime('%B %d, %Y %H:%M UTC')}</b>",
        parse_mode="HTML",
    )

    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "\U0001f389 <b>Subscription Activated!</b>\n"
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                f"\U0001f4cb Plan: <b>{plan_label}</b>\n"
                f"\U0001f4c5 Expires: <b>{end_date.strftime('%B %d, %Y %H:%M UTC')}</b>\n\n"
                "You can now start fetching OTPs!\n"
                "Go to <b>My Bots</b> \u2192 Select bot \u2192 <b>Start Fetching</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        await update.message.reply_text(
            "\u26a0\ufe0f Could not notify user (they may need to /start the bot first)."
        )

    # ---- Referral reward: gift referrer 1 free week for 1M+ plans ----
    qualified_plans = {"1m", "2m", "3m", "6m", "1y"}
    if duration_key in qualified_plans:
        try:
            ref_info = await db.get_referrer(user_id)
            if ref_info and not ref_info["rewarded"]:
                referrer_id = ref_info["referred_by"]
                # Give referrer 1 week free
                ref_now = datetime.now(timezone.utc)
                # Extend existing sub or create new
                ref_sub = await db.get_subscription(referrer_id)
                ref_active = await db.is_subscription_active(referrer_id)
                if ref_sub and ref_active:
                    try:
                        ref_end = datetime.fromisoformat(ref_sub["end_date"])
                        if ref_end.tzinfo is None:
                            ref_end = ref_end.replace(tzinfo=timezone.utc)
                        ref_new_end = ref_end + timedelta(weeks=1)
                    except Exception:
                        ref_new_end = ref_now + timedelta(weeks=1)
                else:
                    ref_new_end = ref_now + timedelta(weeks=1)

                await db.add_subscription(referrer_id, "Referral Bonus (1 Week)", ref_new_end.isoformat())
                await db.mark_referral_rewarded(user_id)

                # Notify referrer
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            "\U0001f381 <b>Referral Reward!</b>\n"
                            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                            "Someone you referred just subscribed!\n"
                            "You've been gifted <b>1 free week</b> of subscription.\n\n"
                            f"\U0001f4c5 New expiry: <b>{ref_new_end.strftime('%B %d, %Y %H:%M UTC')}</b>\n\n"
                            "Keep sharing your referral link for more rewards!"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

                await update.message.reply_text(
                    f"\U0001f381 Referrer <code>{referrer_id}</code> was gifted 1 week (referral reward).",
                    parse_mode="HTML",
                )
        except Exception:
            pass


# ============================================
# /revoke <user_id>
# ============================================

async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /revoke <code>&lt;user_id&gt;</code>", parse_mode="HTML"
        )
        return

    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("\u274c Invalid user ID.")
        return

    await db.revoke_subscription(user_id)
    await db.stop_all_user_fetching(user_id)

    await update.message.reply_text(
        f"\u2705 Subscription revoked for user <code>{user_id}</code>.\n"
        "All fetching stopped.",
        parse_mode="HTML",
    )

    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "\u26a0\ufe0f <b>Subscription Revoked</b>\n"
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                "Your subscription has been revoked.\n"
                "All OTP fetching has been stopped.\n\n"
                f"Contact {ADMIN_CONTACT} for support."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ============================================
# /users - List all users
# ============================================

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    users = await db.get_all_users()
    if not users:
        await update.message.reply_text("No users yet.")
        return

    lines = ["\U0001f465 <b>All Users</b>\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"]
    for u in users[:50]:
        sub_icon = "\U0001f48e" if u.get("has_sub") else "\u2b1c"
        name = u.get("first_name") or u.get("username") or "Unknown"
        lines.append(
            f"{sub_icon} <code>{u['telegram_id']}</code> \u2014 "
            f"{html.escape(str(name))} ({u.get('bot_count', 0)} bots)"
        )

    if len(users) > 50:
        lines.append(f"\n... and {len(users) - 50} more")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ============================================
# /broadcast <message>
# ============================================

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <code>&lt;message&gt;</code>", parse_mode="HTML"
        )
        return

    message = update.message.text.split(" ", 1)[1]
    users = await db.get_all_users()

    status_msg = await update.message.reply_text(
        f"\U0001f4e2 Broadcasting to {len(users)} users..."
    )

    sent = 0
    failed = 0
    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u["telegram_id"],
                text=(
                    "\U0001f4e2 <b>Announcement</b>\n"
                    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"{message}"
                ),
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Rate limiting

    await status_msg.edit_text(
        f"\U0001f4e2 Broadcast complete: {sent} sent, {failed} failed."
    )
