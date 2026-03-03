import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import encryption
from panel_client import PanelSession


async def add_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the Add Panel flow."""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    context.user_data["state"] = "add_panel:username"

    await query.message.edit_text(
        "\U0001f517 <b>Add IVASMS Panel</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "<b>Step 1/2:</b> Enter your IVASMS panel email/username:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
        ]),
    )


async def handle_add_panel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input during Add Panel flow."""
    state = context.user_data.get("state", "")

    if state == "add_panel:username":
        username = update.message.text.strip()
        if len(username) > 100:
            await update.message.reply_text("\u274c Username too long.")
            return

        context.user_data["panel_username"] = username
        context.user_data["state"] = "add_panel:password"

        await update.message.reply_text(
            f"\u2705 Username: <code>{html.escape(username)}</code>\n\n"
            "<b>Step 2/2:</b> Enter your IVASMS panel password:\n\n"
            "\U0001f512 <i>The password message will be deleted for security.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
            ]),
        )

    elif state == "add_panel:password":
        password = update.message.text.strip()

        # Delete password message immediately
        try:
            await update.message.delete()
        except Exception:
            pass

        username = context.user_data.get("panel_username", "")

        status_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\U0001f504 Logging into IVASMS panel...",
        )

        # Try logging in
        session = PanelSession(username, password)
        try:
            success = await session.login()
        except Exception:
            success = False
        finally:
            await session.close()

        if success:
            enc_username = encryption.encrypt(username)
            enc_password = encryption.encrypt(password)
            await db.add_panel(update.effective_user.id, enc_username, enc_password)

            context.user_data.clear()

            await status_msg.edit_text(
                "\u2705 <b>Panel added successfully!</b>\n\n"
                f"\U0001f4e7 Username: <code>{html.escape(username)}</code>\n\n"
                "Go to <b>My Bots</b> to link this panel to a bot.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots")],
                    [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
                ]),
            )
        else:
            context.user_data["state"] = "add_panel:password"

            await status_msg.edit_text(
                "\u274c <b>Login failed!</b>\n\n"
                "Please check your credentials and try again.\n"
                "Send your password again:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
                ]),
            )
