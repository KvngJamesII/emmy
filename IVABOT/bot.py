"""
IVASMS OTP Sender - Main Bot Entry Point

A Telegram SaaS bot that lets users create their own OTP fetcher bots.
Users add their bot tokens, groups, and IVASMS panel credentials.
The system polls panels and sends OTPs to groups via user bot tokens.
"""

import config
import database as db
import encryption
from otp_engine import poll_job

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from handlers.start import start_command, main_menu_callback
from handlers.add_bot import (
    add_bot_callback,
    handle_add_bot_text,
    verify_admin_callback,
)
from handlers.add_panel import add_panel_callback, handle_add_panel_text
from handlers.my_bots import (
    my_bots_callback,
    view_bot_callback,
    link_panel_callback,
    link_panel_select_callback,
    start_fetching_callback,
    stop_fetching_callback,
    delete_bot_callback,
    confirm_delete_callback,
    test_otp_callback,
)
from handlers.subscription import subscription_callback
from handlers.howto import howto_callback
from handlers.admin import (
    admin_command,
    subscribe_command,
    revoke_command,
    users_command,
    broadcast_command,
)


# ============================================
# TEXT MESSAGE ROUTER
# ============================================

async def text_handler(update, context):
    """Route text messages to the correct handler based on user_data state."""
    if not update.message or not update.message.text:
        return

    state = context.user_data.get("state", "")

    if state.startswith("add_bot:"):
        await handle_add_bot_text(update, context)
    elif state.startswith("add_panel:"):
        await handle_add_panel_text(update, context)


# ============================================
# POST-INIT (DB setup)
# ============================================

async def post_init(app):
    await db.init_db()
    print("\u2705 Database initialized")


# ============================================
# MAIN
# ============================================

def main():
    print("\U0001f680 IVASMS OTP Sender starting...")

    # Initialize encryption
    encryption.setup(config.KEY_FILE)
    print("\U0001f510 Encryption initialized")

    # Initialize database path
    db.setup(config.DB_PATH)

    # Build application
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # ---- Commands ----
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("revoke", revoke_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # ---- Callbacks: Main Menu ----
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern=r"^back:main$"))
    app.add_handler(CallbackQueryHandler(add_bot_callback, pattern=r"^main:add_bot$"))
    app.add_handler(CallbackQueryHandler(add_panel_callback, pattern=r"^main:add_panel$"))
    app.add_handler(CallbackQueryHandler(my_bots_callback, pattern=r"^main:my_bots$"))
    app.add_handler(CallbackQueryHandler(subscription_callback, pattern=r"^main:sub$"))
    app.add_handler(CallbackQueryHandler(howto_callback, pattern=r"^main:howto$"))

    # ---- Callbacks: Add Bot ----
    app.add_handler(CallbackQueryHandler(verify_admin_callback, pattern=r"^ab:verify:\d+$"))

    # ---- Callbacks: My Bots ----
    app.add_handler(CallbackQueryHandler(view_bot_callback, pattern=r"^mb:view:\d+$"))
    app.add_handler(CallbackQueryHandler(link_panel_callback, pattern=r"^mb:link:\d+$"))
    app.add_handler(CallbackQueryHandler(link_panel_select_callback, pattern=r"^mb:lp:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(start_fetching_callback, pattern=r"^mb:start:\d+$"))
    app.add_handler(CallbackQueryHandler(stop_fetching_callback, pattern=r"^mb:stop:\d+$"))
    app.add_handler(CallbackQueryHandler(delete_bot_callback, pattern=r"^mb:delete:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern=r"^mb:cdel:\d+$"))
    app.add_handler(CallbackQueryHandler(test_otp_callback, pattern=r"^mb:test:\d+$"))

    # ---- Text Messages ----
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # ---- Background Polling Job ----
    app.job_queue.run_repeating(poll_job, interval=config.POLL_INTERVAL, first=10)

    print(f"\U0001f537 IVASMS OTP Sender online! Polling every {config.POLL_INTERVAL}s")
    app.run_polling()


if __name__ == "__main__":
    main()
