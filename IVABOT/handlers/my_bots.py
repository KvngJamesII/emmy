import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import encryption
from config import ADMIN_CONTACT
from otp_engine import send_via_bot_token, stop_session, build_otp_message
from panel_client import PanelSession


# ============================================
# MY BOTS LIST
# ============================================

async def my_bots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's bots list."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    user_id = query.from_user.id
    bots = await db.get_user_bots(user_id)

    if not bots:
        await query.message.edit_text(
            "\U0001f4cb <b>My Bots</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "You don't have any bots yet.\n"
            "Use <b>Add Bot</b> to create one.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f916 Add Bot", callback_data="main:add_bot")],
                [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
            ]),
        )
        return

    keyboard = []
    for bot in bots:
        status = "\U0001f7e2" if bot.get("is_fetching") else "\U0001f534"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {bot['name']}", callback_data=f"mb:view:{bot['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")])

    await query.message.edit_text(
        "\U0001f4cb <b>My Bots</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Select a bot to manage:\n"
        "\U0001f7e2 = Fetching  \U0001f534 = Stopped",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================
# VIEW BOT DETAILS
# ============================================

async def view_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show details for a specific bot."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    bot_data = await db.get_bot(bot_id)

    if not bot_data or bot_data["user_id"] != query.from_user.id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    status = "\U0001f7e2 Fetching" if bot_data.get("is_fetching") else "\U0001f534 Stopped"
    group = bot_data.get("group_id") or "Not set"
    verified = "\u2705 Yes" if bot_data.get("admin_verified") else "\u274c No"

    # Decrypt panel username for display
    panel_display = "None linked"
    if bot_data.get("panel_username"):
        try:
            panel_display = encryption.decrypt(bot_data["panel_username"])
        except Exception:
            panel_display = "Error"

    # Build action buttons
    keyboard = []

    if not bot_data.get("panel_id"):
        keyboard.append([InlineKeyboardButton("\U0001f517 Link Panel", callback_data=f"mb:link:{bot_id}")])
    else:
        keyboard.append([InlineKeyboardButton("\U0001f504 Change Panel", callback_data=f"mb:link:{bot_id}")])

    if bot_data.get("is_fetching"):
        keyboard.append([InlineKeyboardButton("\u23f9 Stop Fetching", callback_data=f"mb:stop:{bot_id}")])
    elif bot_data.get("panel_id") and bot_data.get("admin_verified"):
        keyboard.append([InlineKeyboardButton("\u25b6\ufe0f Start Fetching", callback_data=f"mb:start:{bot_id}")])

    # Test OTP button: show when panel linked and admin verified
    if bot_data.get("panel_id") and bot_data.get("admin_verified"):
        keyboard.append([InlineKeyboardButton("\U0001f9ea Test OTP", callback_data=f"mb:test:{bot_id}")])

    if not bot_data.get("admin_verified"):
        keyboard.append([InlineKeyboardButton("\u2705 Verify Admin", callback_data=f"ab:verify:{bot_id}")])

    keyboard.append([
        InlineKeyboardButton("\U0001f5d1 Delete", callback_data=f"mb:delete:{bot_id}"),
        InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main:my_bots"),
    ])

    await query.message.edit_text(
        f"\U0001f916 <b>{html.escape(bot_data['name'])}</b>\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4cd Group: <code>{html.escape(str(group))}</code>\n"
        f"\u2705 Admin Verified: {verified}\n"
        f"\U0001f4e7 Panel: <code>{html.escape(panel_display)}</code>\n"
        f"\U0001f4e1 Status: {status}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================
# LINK PANEL
# ============================================

async def link_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show panels to link to a bot."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    user_id = query.from_user.id

    panels = await db.get_user_panels(user_id)

    if not panels:
        await query.message.edit_text(
            "\u274c You don't have any panels saved.\nAdd a panel first.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f517 Add Panel", callback_data="main:add_panel")],
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
        return

    keyboard = []
    for panel in panels:
        try:
            panel_name = encryption.decrypt(panel["username"])
        except Exception:
            panel_name = f"Panel #{panel['id']}"
        keyboard.append([
            InlineKeyboardButton(
                f"\U0001f4e7 {panel_name}", callback_data=f"mb:lp:{bot_id}:{panel['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")])

    await query.message.edit_text(
        "\U0001f517 Select a panel to link:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def link_panel_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Link a specific panel to a bot."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    bot_id = int(parts[2])
    panel_id = int(parts[3])

    bot_data = await db.get_bot_by_user_and_id(query.from_user.id, bot_id)
    if not bot_data:
        await query.message.edit_text("\u274c Bot not found.")
        return

    await db.link_bot_panel(bot_id, panel_id)

    panel = await db.get_panel(panel_id)
    try:
        panel_name = encryption.decrypt(panel["username"]) if panel else "Unknown"
    except Exception:
        panel_name = "Panel"

    await query.message.edit_text(
        f"\u2705 Panel <code>{html.escape(panel_name)}</code> linked to "
        f"<b>{html.escape(bot_data['name'])}</b>!\n\n"
        "You can now start fetching OTPs.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u25b6\ufe0f Start Fetching", callback_data=f"mb:start:{bot_id}")],
            [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
        ]),
    )


# ============================================
# START / STOP FETCHING
# ============================================

async def start_fetching_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start OTP fetching for a bot."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    user_id = query.from_user.id

    bot_data = await db.get_bot(bot_id)
    if not bot_data or bot_data["user_id"] != user_id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    if not bot_data.get("panel_id"):
        await query.message.edit_text(
            "\u274c No panel linked. Link a panel first.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f517 Link Panel", callback_data=f"mb:link:{bot_id}")],
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
        return

    if not bot_data.get("admin_verified"):
        await query.message.edit_text(
            "\u274c Bot admin status not verified.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2705 Verify Admin", callback_data=f"ab:verify:{bot_id}")],
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
        return

    # Check subscription
    has_sub = await db.is_subscription_active(user_id)
    if not has_sub:
        await query.message.edit_text(
            "\u274c <b>No Active Subscription</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f194 Your Telegram ID: <code>{user_id}</code>\n\n"
            "You need an active subscription to start fetching.\n\n"
            f"Contact {ADMIN_CONTACT} to subscribe.\n\n"
            "Your bot has been saved in <b>My Bots</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f48e Subscription", callback_data="main:sub")],
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
        return

    # Start fetching
    await db.set_fetching(bot_id, True)

    # ---- Mark existing panel messages as processed so they don't get sent ----
    try:
        panel = await db.get_panel(bot_data["panel_id"])
        if panel:
            panel_user = encryption.decrypt(panel["username"])
            panel_pass = encryption.decrypt(panel["password"])
            session = PanelSession(panel_user, panel_pass)
            logged_in = await session.login()
            if logged_in:
                existing_msgs = await session.fetch_sms()
                if existing_msgs:
                    link = await db.get_active_links()
                    # Find the link_id for this bot
                    link_id = None
                    for lnk in link:
                        if lnk.get("bot_id") == bot_id:
                            link_id = lnk["link_id"]
                            break
                    if link_id:
                        hashes = [m["id"] for m in existing_msgs]
                        await db.bulk_mark_processed(link_id, hashes)
            await session.close()
    except Exception:
        pass

    # Send connection message to the user's group via their bot
    try:
        bot_token = encryption.decrypt(bot_data["token"])
        group_id = bot_data["group_id"]
        await send_via_bot_token(
            bot_token, group_id,
            "\u2b50 <b>OTP FETCHER CONNECTED</b> \u2b50\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\U0001f7e2 Status: <b>Online</b>\n"
            "\U0001f50d Monitoring for new OTPs...\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "<i>IVASMS OTP Sender</i>",
        )
    except Exception:
        pass

    await query.message.edit_text(
        f"\U0001f7e2 <b>Fetching Started!</b>\n\n"
        f"Bot: <b>{html.escape(bot_data['name'])}</b>\n"
        "OTPs will now be polled and sent to your group.\n\n"
        "<i>Use My Bots to stop fetching anytime.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u23f9 Stop", callback_data=f"mb:stop:{bot_id}")],
            [InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots")],
        ]),
    )


async def stop_fetching_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop OTP fetching for a bot."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    bot_data = await db.get_bot(bot_id)

    if not bot_data or bot_data["user_id"] != query.from_user.id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    await db.set_fetching(bot_id, False)

    # Stop the engine session
    if bot_data.get("link_id"):
        await stop_session(bot_data["link_id"])

    await query.message.edit_text(
        f"\U0001f534 <b>Fetching Stopped</b>\n\n"
        f"Bot: <b>{html.escape(bot_data['name'])}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u25b6\ufe0f Start Again", callback_data=f"mb:start:{bot_id}")],
            [InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots")],
        ]),
    )


# ============================================
# DELETE BOT
# ============================================

async def delete_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for delete confirmation."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    bot_data = await db.get_bot(bot_id)

    if not bot_data or bot_data["user_id"] != query.from_user.id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    await query.message.edit_text(
        f"\u26a0\ufe0f Are you sure you want to delete <b>{html.escape(bot_data['name'])}</b>?\n\n"
        "This will stop fetching and remove all data for this bot.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f5d1 Yes, Delete", callback_data=f"mb:cdel:{bot_id}")],
            [InlineKeyboardButton("\u2b05\ufe0f Cancel", callback_data=f"mb:view:{bot_id}")],
        ]),
    )


async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually delete the bot."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    bot_data = await db.get_bot(bot_id)

    if not bot_data or bot_data["user_id"] != query.from_user.id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    # Stop engine session if running
    if bot_data.get("link_id"):
        await stop_session(bot_data["link_id"])

    name = bot_data["name"]
    await db.delete_bot(bot_id)

    await query.message.edit_text(
        f"\U0001f5d1 <b>{html.escape(name)}</b> has been deleted.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4cb My Bots", callback_data="main:my_bots")],
            [InlineKeyboardButton("\U0001f3e0 Main Menu", callback_data="back:main")],
        ]),
    )


# ============================================
# TEST OTP
# ============================================

async def test_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a sample OTP message from the panel to the group."""
    query = update.callback_query
    await query.answer()

    bot_id = int(query.data.split(":")[-1])
    user_id = query.from_user.id

    bot_data = await db.get_bot(bot_id)
    if not bot_data or bot_data["user_id"] != user_id:
        await query.message.edit_text("\u274c Bot not found.")
        return

    if not bot_data.get("panel_id") or not bot_data.get("admin_verified"):
        await query.message.edit_text(
            "\u274c Bot must have a linked panel and verified admin status to test.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
        return

    await query.message.edit_text(
        "\U0001f50d <b>Testing OTP...</b>\n\nFetching messages from panel...",
        parse_mode="HTML",
    )

    try:
        panel = await db.get_panel(bot_data["panel_id"])
        if not panel:
            await query.message.edit_text(
                "\u274c Panel not found.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
                ]),
            )
            return

        panel_user = encryption.decrypt(panel["username"])
        panel_pass = encryption.decrypt(panel["password"])
        bot_token = encryption.decrypt(bot_data["token"])
        group_id = bot_data["group_id"]

        session = PanelSession(panel_user, panel_pass)
        logged_in = await session.login()

        if not logged_in:
            await session.close()
            await query.message.edit_text(
                "\u274c Failed to login to panel. Check your credentials.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
                ]),
            )
            return

        messages = await session.fetch_sms()
        await session.close()

        if not messages:
            await query.message.edit_text(
                "\u274c No messages found on the panel right now.\n\n"
                "Make sure your IVASMS panel has active numbers with incoming SMS.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
                ]),
            )
            return

        # Send the first message as a test
        test_msg = messages[0]
        text = build_otp_message(test_msg)
        test_text = (
            "\U0001f9ea <b>TEST OTP</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            + text
        )

        sent = await send_via_bot_token(bot_token, group_id, test_text)

        if sent:
            await query.message.edit_text(
                "\u2705 <b>Test OTP sent successfully!</b>\n\n"
                "Check your group for the test message.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
                ]),
            )
        else:
            await query.message.edit_text(
                "\u274c Failed to send test OTP to group.\n"
                "Make sure the bot is admin in the group.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
                ]),
            )

    except Exception as e:
        await query.message.edit_text(
            f"\u274c Error during test: {html.escape(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=f"mb:view:{bot_id}")],
            ]),
        )
