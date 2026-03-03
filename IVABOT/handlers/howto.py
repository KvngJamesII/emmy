from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


async def howto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the How To guide."""
    query = update.callback_query
    await query.answer()

    await query.message.edit_text(
        "\u2753 <b>How To Use IVASMS OTP Sender</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "<b>Step 1: Create a Telegram Bot</b>\n"
        "\u2022 Open @BotFather on Telegram\n"
        "\u2022 Send /newbot and follow the prompts\n"
        "\u2022 Copy the bot token\n\n"
        "<b>Step 2: Add Your Bot Here</b>\n"
        "\u2022 Click <b>Add Bot</b> in the main menu\n"
        "\u2022 Enter a name and paste your bot token\n"
        "\u2022 Add the bot to your group as an admin\n"
        "\u2022 Click Verify to confirm admin status\n\n"
        "<b>Step 3: Add Your IVASMS Panel</b>\n"
        "\u2022 Click <b>Add Panel</b> in the main menu\n"
        "\u2022 Enter your IVASMS email and password\n"
        "\u2022 The bot will verify your login credentials\n\n"
        "<b>Step 4: Link Panel to Bot</b>\n"
        "\u2022 Go to <b>My Bots</b> \u2192 Select your bot\n"
        "\u2022 Click <b>Link Panel</b>\n"
        "\u2022 Choose the panel to connect\n\n"
        "<b>Step 5: Subscribe & Start Fetching</b>\n"
        "\u2022 Contact @theidledeveloper to get a subscription\n"
        "\u2022 Go to <b>My Bots</b> \u2192 Select bot \u2192 <b>Start Fetching</b>\n"
        "\u2022 OTPs will be automatically sent to your group!\n\n"
        "\U0001f512 <b>Security:</b> Bot tokens and passwords are\n"
        "encrypted and messages are deleted immediately.\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
        ]),
    )
