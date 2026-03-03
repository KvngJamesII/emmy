import html
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import encryption


async def add_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the Add Bot flow."""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    context.user_data["state"] = "add_bot:name"

    await query.message.edit_text(
        "\U0001f916 <b>Add New Bot</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "<b>Step 1/4:</b> Enter a name for your bot\n\n"
        "<i>This is just a label for you to identify it.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
        ]),
    )


async def handle_add_bot_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input during Add Bot flow."""
    state = context.user_data.get("state", "")

    if state == "add_bot:name":
        name = update.message.text.strip()
        if len(name) > 50:
            await update.message.reply_text("\u274c Name too long. Max 50 characters.")
            return

        context.user_data["bot_name"] = name
        context.user_data["state"] = "add_bot:token"

        await update.message.reply_text(
            f"\u2705 Bot name: <b>{html.escape(name)}</b>\n\n"
            "<b>Step 2/4:</b> Now create a bot on @BotFather:\n\n"
            "1. Open @BotFather on Telegram\n"
            "2. Send /newbot and follow the prompts\n"
            "3. Copy the bot token and send it here\n\n"
            "\U0001f512 <i>The token message will be deleted for security.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
            ]),
        )

    elif state == "add_bot:token":
        token = update.message.text.strip()

        # Delete the token message immediately for security
        try:
            await update.message.delete()
        except Exception:
            pass

        # Validate token format
        if ":" not in token:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "\u274c Invalid token format. It should look like:\n"
                    "<code>123456789:ABCdefGHIjklMNO...</code>\n\n"
                    "Try again:"
                ),
                parse_mode="HTML",
            )
            return

        # Validate token by calling Telegram getMe
        status_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\U0001f504 Validating bot token...",
        )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                data = resp.json()
                if not data.get("ok"):
                    await status_msg.edit_text(
                        "\u274c Invalid bot token. Please check and try again.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
                        ]),
                    )
                    return
                bot_username = data["result"].get("username", "Unknown")
        except Exception:
            await status_msg.edit_text(
                "\u274c Could not validate token. Network error. Try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
                ]),
            )
            return

        # Save token and bot username temporarily
        context.user_data["pending_bot_token"] = token
        context.user_data["pending_bot_username"] = bot_username
        context.user_data["state"] = "add_bot:group"

        await status_msg.edit_text(
            f"\u2705 Bot validated: @{bot_username}\n\n"
            "<b>Step 3/4:</b> Send the group link where you want to receive OTPs.\n\n"
            "Example: <code>https://t.me/mygroup</code>\n\n"
            "<i>You can also send the group ID directly (e.g. -1001234567890).</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")],
            ]),
        )

    elif state == "add_bot:group":
        group_input = update.message.text.strip()
        bot_username = context.user_data.get("pending_bot_username", "your bot")
        token = context.user_data.get("pending_bot_token")

        if not token:
            await update.message.reply_text(
                "\u274c Session expired. Please start over.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f916 Add Bot", callback_data="main:add_bot")]
                ]),
            )
            return

        # Try to resolve group link to a chat ID
        status_msg = await update.message.reply_text("\U0001f504 Checking group...")

        group_id = None
        group_title = None

        # If it looks like a numeric group ID
        if group_input.lstrip("-").isdigit():
            group_id = group_input
            # Try to get the group title via the user's bot
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"https://api.telegram.org/bot{token}/getChat",
                        params={"chat_id": group_id},
                    )
                    data = resp.json()
                    if data.get("ok"):
                        group_title = data["result"].get("title", "Group")
            except Exception:
                pass
        else:
            # Extract username from link like https://t.me/groupname
            import re
            match = re.search(r"(?:t\.me/|@)([a-zA-Z0-9_]+)", group_input)
            if match:
                chat_username = "@" + match.group(1)
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.get(
                            f"https://api.telegram.org/bot{token}/getChat",
                            params={"chat_id": chat_username},
                        )
                        data = resp.json()
                        if data.get("ok"):
                            group_id = str(data["result"]["id"])
                            group_title = data["result"].get("title", "Group")
                except Exception:
                    pass

        if not group_id:
            await status_msg.edit_text(
                "\u274c Could not find that group.\n\n"
                "Make sure:\n"
                f"1. @{bot_username} is already added to the group\n"
                "2. The link or ID is correct\n\n"
                "Try again (send the group link or ID):",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")]
                ]),
            )
            return

        if not group_title:
            group_title = "Group"

        # Save bot to database
        encrypted_token = encryption.encrypt(token)
        bot_name = context.user_data.get("bot_name", "My Bot")
        bot_id = await db.add_bot(update.effective_user.id, bot_name, encrypted_token)

        context.user_data["pending_bot_id"] = bot_id
        context.user_data["pending_group_id"] = group_id
        context.user_data["pending_group_title"] = group_title
        context.user_data["state"] = "add_bot:verify"

        await status_msg.edit_text(
            f"\u2705 Group found: <b>{html.escape(group_title)}</b>\n\n"
            f"<b>Step 4/4:</b> Make @{bot_username} an <b>admin</b> in that group.\n\n"
            "Once done, click <b>Verify Admin</b> below.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2705 Verify Admin", callback_data=f"ab:verify:{bot_id}")],
                [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")],
            ]),
        )


async def verify_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify the user's bot is an admin in a group by checking getUpdates."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    bot_data = await db.get_bot(bot_id)

    if not bot_data or bot_data["user_id"] != query.from_user.id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    # Get the token (from temp storage or decrypt from DB)
    token = context.user_data.get("pending_bot_token")
    if not token:
        try:
            token = encryption.decrypt(bot_data["token"])
        except Exception:
            await query.message.edit_text("\u274c Could not decrypt bot token.")
            return

    # Get group ID from user_data or from DB
    group_id = context.user_data.get("pending_group_id")
    group_title = context.user_data.get("pending_group_title", "Group")

    if not group_id:
        # Fallback: check if bot already has a group_id saved
        if bot_data.get("group_id"):
            group_id = bot_data["group_id"]
        else:
            await query.message.edit_text(
                "\u274c No group set. Please start over.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f916 Add Bot", callback_data="main:add_bot")],
                    [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
                ]),
            )
            return

    await query.message.edit_text("\U0001f504 Verifying admin status...")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get bot's own ID
            me_resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            me_data = me_resp.json()
            if not me_data.get("ok"):
                await query.message.edit_text(
                    "\u274c Could not reach your bot. Check the token.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001f504 Try Again", callback_data=f"ab:verify:{bot_id}")],
                        [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")],
                    ]),
                )
                return
            bot_tg_id = me_data["result"]["id"]
            bot_username = me_data["result"].get("username", "your bot")

            # Check admin status directly in the provided group
            admin_resp = await client.get(
                f"https://api.telegram.org/bot{token}/getChatMember",
                params={"chat_id": group_id, "user_id": bot_tg_id},
            )
            admin_data = admin_resp.json()
            is_admin_ok = (
                admin_data.get("ok")
                and admin_data.get("result", {}).get("status") in ("administrator", "creator")
            )

            if not is_admin_ok:
                await query.message.edit_text(
                    f"\u274c @{bot_username} is not an admin in <b>{html.escape(group_title)}</b>.\n\n"
                    "Please make it an admin and try again.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001f504 Try Again", callback_data=f"ab:verify:{bot_id}")],
                        [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")],
                    ]),
                )
                return

            # Save group to database
            await db.update_bot_group(bot_id, str(group_id))

            # Clear the bot's pending updates
            try:
                upd_resp = await client.get(f"https://api.telegram.org/bot{token}/getUpdates")
                upd_data = upd_resp.json()
                results = upd_data.get("result", [])
                if results:
                    last_update_id = results[-1]["update_id"]
                    await client.get(
                        f"https://api.telegram.org/bot{token}/getUpdates",
                        params={"offset": last_update_id + 1},
                    )
            except Exception:
                pass

            # Clean up temp data
            context.user_data.pop("pending_bot_token", None)
            context.user_data.pop("pending_bot_id", None)
            context.user_data.pop("pending_bot_username", None)
            context.user_data.pop("pending_group_id", None)
            context.user_data.pop("pending_group_title", None)
            context.user_data["state"] = None

            bot_name = bot_data["name"]
            await query.message.edit_text(
                f"\u2705 <b>{html.escape(bot_name)}</b> added successfully!\n\n"
                f"\U0001f4cd Group: <b>{html.escape(group_title)}</b>\n\n"
                "Now link it to your IVASMS panel to start sending OTPs.\n"
                "Go to <b>My Bots</b> to manage it.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots")],
                    [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
                ]),
            )

    except Exception as e:
        await query.message.edit_text(
            f"\u274c Verification failed: {html.escape(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f504 Try Again", callback_data=f"ab:verify:{bot_id}")],
                [InlineKeyboardButton("\u274c Cancel", callback_data="back:main")],
            ]),
        )


# select_group_callback removed — group is now provided by the user directly
