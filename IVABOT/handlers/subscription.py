from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from config import ADMIN_CONTACT, PLANS_DISPLAY


async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user's subscription status."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    sub = await db.get_subscription(user_id)
    is_active = await db.is_subscription_active(user_id)

    # Referral info
    referral_count = await db.get_referral_count(user_id)
    bot_me = await context.bot.get_me()
    bot_username = bot_me.username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    referral_text = (
        "\n\U0001f91d <b>Referral Program</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f517 Your link:\n<code>{referral_link}</code>\n\n"
        f"\U0001f465 Referrals: <b>{referral_count}</b>\n"
        "\U0001f381 Get <b>1 free week</b> when your referral subscribes (1M+)!\n"
    )

    if sub and is_active:
        from datetime import datetime, timezone
        try:
            end_dt = datetime.fromisoformat(sub["end_date"])
            end_str = end_dt.strftime("%B %d, %Y %H:%M UTC")
        except Exception:
            end_str = sub["end_date"]

        plan = sub.get("plan", "Unknown")

        await query.message.edit_text(
            "\U0001f48e <b>Subscription Status</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\u2705 <b>Active Subscription</b>\n\n"
            f"\U0001f4cb Plan: <b>{plan}</b>\n"
            f"\U0001f4c5 Expires: <b>{end_str}</b>\n"
            f"\U0001f194 Telegram ID: <code>{user_id}</code>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"{referral_text}"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
            ]),
        )
    else:
        plans_text = "\n".join(
            f"\U0001f48e <b>{p['price']}</b> / {p['label']}" for p in PLANS_DISPLAY
        )

        await query.message.edit_text(
            "\U0001f48e <b>Subscription Status</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\u274c <b>No Active Subscription</b>\n\n"
            f"\U0001f194 Your Telegram ID: <code>{user_id}</code>\n\n"
            "<b>Plans:</b>\n"
            f"{plans_text}\n\n"
            f"Contact {ADMIN_CONTACT} to subscribe.\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"{referral_text}"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
            ]),
        )
