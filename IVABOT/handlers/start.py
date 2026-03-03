from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database as db


def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f916 Add Bot", callback_data="main:add_bot"),
            InlineKeyboardButton("\U0001f517 Add Panel", callback_data="main:add_panel"),
        ],
        [
            InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots"),
            InlineKeyboardButton("\U0001f48e Subscription", callback_data="main:sub"),
        ],
        [InlineKeyboardButton("\u2753 How To Use", callback_data="main:howto")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.ensure_user(user.id, user.username, user.first_name)
    context.user_data.clear()

    # Handle referral deep link: /start ref_12345
    if context.args and len(context.args) == 1 and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0][4:])
            if referrer_id != user.id:  # Can't refer yourself
                await db.save_referral(user.id, referrer_id)
        except (ValueError, Exception):
            pass

    await update.message.reply_text(
        "\U0001f537 <b>IVASMS OTP SENDER</b> \U0001f537\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Welcome! This bot lets you set up your own\n"
        "OTP fetcher that sends OTPs directly to your group.\n\n"
        "Get started by adding a bot and linking your IVASMS panel.\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    await query.message.edit_text(
        "\U0001f537 <b>IVASMS OTP SENDER</b> \U0001f537\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Welcome! This bot lets you set up your own\n"
        "OTP fetcher that sends OTPs directly to your group.\n\n"
        "Get started by adding a bot and linking your IVASMS panel.\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(),
    )
