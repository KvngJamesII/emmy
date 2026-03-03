"""
Eden OTP Bot — Fully automated Telegram bot for OTP processing.

Features:
  🔐 Account login/logout via Telegram user session
  📋 OTP group management (private/public, topics)
  📁 Number management (file upload or paste)
  🚀 Auto OTP task engine (batch send → monitor → reply)
  👁 Live OTP group monitor
  📊 Real-time statistics & history
  ⚙️ Configurable settings (batch size, timeout, target bot, match digits)
  ⏸ Pause / Resume / Stop controls mid-task
  📤 Export results as .txt file

Usage:
  1. Create a bot via @BotFather, get the token
  2. Set BOT_TOKEN below (or env var EDEN_BOT_TOKEN)
  3. Run: python eden.py
  4. Open your bot in Telegram and type /start
"""

import asyncio
import time
import re
import os
import json
import random
import logging
from datetime import datetime
from io import BytesIO

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    FloodWaitError, PhoneNumberInvalidError
)
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import PeerChannel

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOT_TOKEN = os.environ.get('EDEN_BOT_TOKEN', '8409880931:AAGTJZQcys7Iqi2IFVNA3AbHjXqz-IV6HhI')
API_ID = int(os.environ.get('EDEN_API_ID', '24268062'))
API_HASH = os.environ.get('EDEN_API_HASH', 'aaab3d4a5ab8f7b3024a3edbd88cabf7')

# Restrict who can use the bot. Empty list = anyone can use it.
# Add Telegram user IDs (integers) to lock it down.
AUTHORIZED_USERS = []  # e.g. [123456789, 987654321]

DATA_FILE = 'eden_data.json'

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LOGGING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('Eden')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  USER STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class UserState:
    """Holds all per-user data and runtime state."""

    def __init__(self):
        # Auth
        self.client = None
        self.session_string = None
        self.phone = None
        self.phone_code_hash = None
        self.is_authenticated = False
        self.temp_client = None

        # OTP group
        self.otp_group_link = None
        self.otp_group_entity = None
        self.otp_topic_id = None

        # Numbers
        self.numbers = []

        # Settings
        self.target_bot = 'wsotp200bot'
        self.batch_size = 4
        self.timeout = 240       # seconds per batch
        self.match_digits = 3    # last N digits for OTP matching
        self.delay_min = 1.0     # min delay between sends (seconds)
        self.delay_max = 3.0     # max delay between sends (seconds)

        # Task control
        self.task_running = False
        self.task_paused = False
        self.task_stop = False
        self.task_handle = None

        # Statistics
        self.stats = {'success': 0, 'failed': 0, 'timeout': 0, 'total': 0}
        self.session_results = {}   # number -> result string
        self.activity_log = []

        # Conversation state
        self.awaiting = None  # what input we expect next


users = {}  # chat_id -> UserState


def get_user(chat_id):
    if chat_id not in users:
        users[chat_id] = UserState()
        _load_user(chat_id)
    return users[chat_id]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PERSISTENCE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _all_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}


def _save_all(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def _load_user(chat_id):
    data = _all_data()
    key = str(chat_id)
    if key in data:
        u = users[chat_id]
        d = data[key]
        u.session_string = d.get('session_string')
        u.otp_group_link = d.get('otp_group_link')
        u.target_bot = d.get('target_bot', 'wsotp200bot')
        u.batch_size = d.get('batch_size', 4)
        u.timeout = d.get('timeout', 240)
        u.match_digits = d.get('match_digits', 3)
        u.delay_min = d.get('delay_min', 1.0)
        u.delay_max = d.get('delay_max', 3.0)
        u.stats = d.get('stats', u.stats)
        u.is_authenticated = bool(u.session_string)


def save_user(chat_id):
    data = _all_data()
    u = users[chat_id]
    data[str(chat_id)] = {
        'session_string': u.session_string,
        'otp_group_link': u.otp_group_link,
        'target_bot': u.target_bot,
        'batch_size': u.batch_size,
        'timeout': u.timeout,
        'match_digits': u.match_digits,
        'delay_min': u.delay_min,
        'delay_max': u.delay_max,
        'stats': u.stats,
    }
    _save_all(data)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_telegram_link(link):
    """Return (chat_id, topic_id) from a Telegram link."""
    # Private: https://t.me/c/123456789/topic_id
    m = re.search(r't\.me/c/(\d+)(?:/(\d+))?', link)
    if m:
        cid = int('-100' + m.group(1))
        tid = int(m.group(2)) if m.group(2) else None
        return cid, tid
    # Invite: https://t.me/+ABC or https://t.me/joinchat/ABC
    m = re.search(r't\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', link)
    if m:
        return m.group(1), None
    # Public: https://t.me/username/topic_id
    m = re.search(r't\.me/([a-zA-Z0-9_]+)(?:/(\d+))?', link)
    if m:
        cid = m.group(1)
        tid = int(m.group(2)) if m.group(2) else None
        return cid, tid
    return link, None


async def resolve_entity(client, chat_id):
    """Resolve a chat entity, handling numeric IDs for private channels/groups."""
    if isinstance(chat_id, int) and str(chat_id).startswith('-100'):
        # Private channel/supergroup — use PeerChannel
        channel_id = int(str(chat_id)[4:])  # strip -100 prefix
        try:
            entity = await client.get_entity(PeerChannel(channel_id))
            return entity
        except Exception:
            # Fallback: try get_entity with full ID
            return await client.get_entity(chat_id)
    else:
        return await client.get_entity(chat_id)


def extract_otp(text):
    """Extract a 4–8 digit OTP from text."""
    if not text:
        return None
    # 6 digits with optional separator (123-456, 123 456)
    m = re.search(r'(\d{3})[\s\-.]?(\d{3})', text)
    if m:
        return m.group(1) + m.group(2)
    # 4–8 consecutive digits as standalone token
    m = re.search(r'\b(\d{4,8})\b', text)
    if m:
        return m.group(1)
    return None


def extract_all_otps(message):
    """Extract OTPs from message text AND inline buttons."""
    found = []
    otp = extract_otp(message.raw_text)
    if otp:
        found.append(otp)
    if message.reply_markup:
        try:
            for row in message.reply_markup.rows:
                for btn in row.buttons:
                    otp = extract_otp(getattr(btn, 'text', ''))
                    if otp and otp not in found:
                        found.append(otp)
        except Exception:
            pass
    return found


def progress_bar(current, total, length=15):
    if total == 0:
        return '░' * length
    filled = int(length * current / total)
    return '█' * filled + '░' * (length - filled)


def ts():
    return datetime.now().strftime('%H:%M:%S')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ACCESS CONTROL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_authorized(user_id):
    if not AUTHORIZED_USERS:
        return True
    return user_id in AUTHORIZED_USERS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  KEYBOARD LAYOUTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main_menu_buttons(u):
    auth_icon = '✅' if u.is_authenticated else '❌'
    group_icon = '✅' if u.otp_group_link else '❌'
    num_count = len(u.numbers)
    return [
        [Button.inline(f'🔐 Account {auth_icon}', b'menu_account'),
         Button.inline(f'📋 OTP Group {group_icon}', b'menu_group')],
        [Button.inline(f'📁 Numbers ({num_count})', b'menu_numbers'),
         Button.inline('🚀 Start Task', b'task_start')],
        [Button.inline('👁 Live Monitor', b'monitor_start'),
         Button.inline('📊 Statistics', b'menu_stats')],
        [Button.inline('⚙️ Settings', b'menu_settings'),
         Button.inline('❓ Help', b'help')],
    ]


def main_menu_text(u):
    auth = '✅ Connected' if u.is_authenticated else '❌ Not connected'
    group = '✅ Set' if u.otp_group_link else '❌ Not set'
    nums = f'{len(u.numbers)} loaded' if u.numbers else 'None'
    bot_name = f'@{u.target_bot}'
    return (
        '╔══════════════════════════════╗\n'
        '║    🌿 **Eden OTP Bot** 🌿     ║\n'
        '╚══════════════════════════════╝\n\n'
        f'🔐 Account: {auth}\n'
        f'📋 OTP Group: {group}\n'
        f'📁 Numbers: {nums}\n'
        f'🤖 Target: {bot_name}\n\n'
        'Select an option below 👇'
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOT CLIENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bot = TelegramClient('eden_bot', API_ID, API_HASH)

# ─── /start ──────────────────────────────────────────────────

@bot.on(events.NewMessage(pattern=r'/start'))
async def cmd_start(event):
    if not is_authorized(event.sender_id):
        await event.respond('⛔ You are not authorized to use this bot.')
        return
    u = get_user(event.chat_id)
    u.awaiting = None
    # Try to restore saved session
    if u.session_string and not u.client:
        try:
            u.client = TelegramClient(StringSession(u.session_string), API_ID, API_HASH)
            await u.client.connect()
            if await u.client.is_user_authorized():
                u.is_authenticated = True
            else:
                u.is_authenticated = False
                u.session_string = None
                save_user(event.chat_id)
        except Exception:
            u.is_authenticated = False
    await event.respond(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')


@bot.on(events.NewMessage(pattern=r'/menu'))
async def cmd_menu(event):
    if not is_authorized(event.sender_id):
        return
    u = get_user(event.chat_id)
    u.awaiting = None
    await event.respond(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')

# ─── CALLBACK QUERY ROUTER ──────────────────────────────────

@bot.on(events.CallbackQuery)
async def callback_router(event):
    if not is_authorized(event.sender_id):
        await event.answer('⛔ Not authorized', alert=True)
        return

    uid = event.chat_id
    u = get_user(uid)
    data = event.data.decode()

    try:
        # ── Main Menu ──
        if data == 'main_menu':
            u.awaiting = None
            await event.edit(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')

        # ── Account ──
        elif data == 'menu_account':
            await show_account_menu(event, u)
        elif data == 'account_login':
            await start_login(event, u)
        elif data == 'account_logout':
            await do_logout(event, u, uid)

        # ── OTP Group ──
        elif data == 'menu_group':
            await show_group_menu(event, u)
        elif data == 'group_set':
            u.awaiting = 'otp_group_link'
            await event.edit(
                '📋 **Set OTP Group**\n\n'
                'Send me the Telegram group link.\n'
                'Supported formats:\n'
                '• `https://t.me/c/123456/2` (private + topic)\n'
                '• `https://t.me/groupname`\n'
                '• `https://t.me/+invite_hash`\n\n'
                'Send /cancel to go back.',
                buttons=[[Button.inline('🔙 Back', b'menu_group')]],
                parse_mode='md'
            )
        elif data == 'group_clear':
            u.otp_group_link = None
            u.otp_group_entity = None
            u.otp_topic_id = None
            save_user(uid)
            await event.answer('🗑 OTP group cleared')
            await show_group_menu(event, u)
        elif data == 'group_verify':
            await verify_group(event, u)

        # ── Numbers ──
        elif data == 'menu_numbers':
            await show_numbers_menu(event, u)
        elif data == 'numbers_upload':
            u.awaiting = 'numbers_input'
            await event.edit(
                '📁 **Add Numbers**\n\n'
                'You can:\n'
                '• Send a `.txt` file (one number per line)\n'
                '• Paste numbers directly (one per line)\n\n'
                'Numbers will be **added** to existing list.\n'
                'Send /cancel to go back.',
                buttons=[[Button.inline('🔙 Back', b'menu_numbers')]],
                parse_mode='md'
            )
        elif data == 'numbers_clear':
            u.numbers.clear()
            await event.answer('🗑 Numbers cleared')
            await show_numbers_menu(event, u)
        elif data == 'numbers_preview':
            preview = u.numbers[:20]
            text = '\n'.join(preview)
            if len(u.numbers) > 20:
                text += f'\n... and {len(u.numbers) - 20} more'
            await event.answer()
            await event.respond(
                f'📋 **Numbers Preview** ({len(u.numbers)} total):\n\n`{text}`',
                parse_mode='md'
            )
        elif data == 'numbers_shuffle':
            random.shuffle(u.numbers)
            await event.answer('🔀 Numbers shuffled!')

        # ── Task ──
        elif data == 'task_start':
            await task_start_handler(event, u, uid)
        elif data == 'task_pause':
            u.task_paused = True
            await event.answer('⏸ Pausing after current operation...')
        elif data == 'task_resume':
            u.task_paused = False
            await event.answer('▶️ Resumed!')
        elif data == 'task_stop':
            u.task_stop = True
            u.task_paused = False
            await event.answer('🛑 Stopping after current batch...')

        # ── Monitor ──
        elif data == 'monitor_start':
            await monitor_start_handler(event, u, uid)
        elif data == 'monitor_stop':
            u.task_stop = True
            await event.answer('👁 Stopping monitor...')

        # ── Statistics ──
        elif data == 'menu_stats':
            await show_stats(event, u)
        elif data == 'stats_reset':
            u.stats = {'success': 0, 'failed': 0, 'timeout': 0, 'total': 0}
            u.session_results.clear()
            u.activity_log.clear()
            save_user(uid)
            await event.answer('📊 Stats reset!')
            await show_stats(event, u)
        elif data == 'stats_export':
            await export_results(event, u)

        # ── Settings ──
        elif data == 'menu_settings':
            await show_settings(event, u)
        elif data == 'set_target_bot':
            u.awaiting = 'target_bot'
            await event.edit(
                '🤖 **Set Target Bot**\n\nSend the bot username (without @):',
                buttons=[[Button.inline('🔙 Back', b'menu_settings')]],
                parse_mode='md'
            )
        elif data == 'set_batch_size':
            await event.edit('📦 **Batch Size**\nHow many numbers per batch?', buttons=[
                [Button.inline('2', b'bs_2'), Button.inline('4', b'bs_4'),
                 Button.inline('6', b'bs_6'), Button.inline('8', b'bs_8')],
                [Button.inline('🔙 Back', b'menu_settings')]
            ], parse_mode='md')
        elif data.startswith('bs_'):
            u.batch_size = int(data[3:])
            save_user(uid)
            await event.answer(f'📦 Batch size → {u.batch_size}')
            await show_settings(event, u)
        elif data == 'set_timeout':
            await event.edit('⏱ **Timeout** (seconds per batch):', buttons=[
                [Button.inline('120s', b'to_120'), Button.inline('180s', b'to_180'),
                 Button.inline('240s', b'to_240'), Button.inline('300s', b'to_300')],
                [Button.inline('🔙 Back', b'menu_settings')]
            ], parse_mode='md')
        elif data.startswith('to_'):
            u.timeout = int(data[3:])
            save_user(uid)
            await event.answer(f'⏱ Timeout → {u.timeout}s')
            await show_settings(event, u)
        elif data == 'set_match_digits':
            await event.edit('🔢 **Match Digits**\nHow many trailing digits to match OTPs?', buttons=[
                [Button.inline('Last 3', b'md_3'), Button.inline('Last 4', b'md_4'),
                 Button.inline('Last 5', b'md_5')],
                [Button.inline('🔙 Back', b'menu_settings')]
            ], parse_mode='md')
        elif data.startswith('md_'):
            u.match_digits = int(data[3:])
            save_user(uid)
            await event.answer(f'🔢 Match digits → {u.match_digits}')
            await show_settings(event, u)
        elif data == 'set_delay':
            u.awaiting = 'delay'
            await event.edit(
                '⏳ **Send Delay**\nRandom delay between messages.\n\n'
                'Send two numbers (min max) in seconds.\n'
                'Example: `1.0 3.0`',
                buttons=[[Button.inline('🔙 Back', b'menu_settings')]],
                parse_mode='md'
            )

        # ── Help ──
        elif data == 'help':
            await show_help(event)

    except Exception as e:
        log.error(f'Callback error: {e}')
        await event.answer(f'❌ Error: {str(e)[:100]}', alert=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEXT INPUT HANDLER (conversation state)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.message.text.startswith('/')))
async def text_handler(event):
    if not is_authorized(event.sender_id):
        return
    uid = event.chat_id
    u = get_user(uid)

    if not u.awaiting:
        return

    text = event.raw_text.strip()

    # ── Phone Number ──
    if u.awaiting == 'phone':
        phone = text.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not phone.startswith('+'):
            await event.respond('❌ Phone must start with `+` (e.g. `+12345678901`)', parse_mode='md')
            return
        u.phone = phone
        try:
            u.temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await u.temp_client.connect()
            result = await u.temp_client.send_code_request(phone)
            u.phone_code_hash = result.phone_code_hash
            u.awaiting = 'code'
            await event.respond(
                f'📲 Code sent to **{phone}**\n\n'
                'Enter the login code you received:',
                parse_mode='md'
            )
        except PhoneNumberInvalidError:
            await event.respond('❌ Invalid phone number. Try again:')
        except FloodWaitError as e:
            await event.respond(f'⚠️ Rate limited. Wait **{e.seconds}** seconds and try again.', parse_mode='md')
            u.awaiting = None
        except Exception as e:
            await event.respond(f'❌ Error: {e}')
            u.awaiting = None

    # ── Auth Code ──
    elif u.awaiting == 'code':
        try:
            await u.temp_client.sign_in(u.phone, text, phone_code_hash=u.phone_code_hash)
            # Success
            u.session_string = u.temp_client.session.save()
            u.client = u.temp_client
            u.temp_client = None
            u.is_authenticated = True
            u.awaiting = None
            save_user(uid)
            await event.respond(
                '✅ **Login successful!**\n\nReturning to main menu...',
                parse_mode='md'
            )
            await asyncio.sleep(1)
            await event.respond(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')
        except SessionPasswordNeededError:
            u.awaiting = '2fa'
            await event.respond('🔒 **2FA enabled.** Enter your cloud password:', parse_mode='md')
        except PhoneCodeInvalidError:
            await event.respond('❌ Invalid code. Try again:')
        except Exception as e:
            await event.respond(f'❌ Login failed: {e}')
            u.awaiting = None

    # ── 2FA Password ──
    elif u.awaiting == '2fa':
        try:
            await u.temp_client.sign_in(password=text)
            u.session_string = u.temp_client.session.save()
            u.client = u.temp_client
            u.temp_client = None
            u.is_authenticated = True
            u.awaiting = None
            save_user(uid)
            await event.respond('✅ **Login successful!** (2FA verified)', parse_mode='md')
            await asyncio.sleep(1)
            await event.respond(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')
        except Exception as e:
            await event.respond(f'❌ 2FA failed: {e}\nTry again:')

    # ── OTP Group Link ──
    elif u.awaiting == 'otp_group_link':
        u.otp_group_link = text
        u.otp_group_entity = None
        u.otp_topic_id = None
        u.awaiting = None
        save_user(uid)
        await event.respond(
            f'✅ OTP group link saved!\n`{text}`',
            buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
            parse_mode='md'
        )

    # ── Numbers (pasted) ──
    elif u.awaiting == 'numbers_input':
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            u.numbers.extend(lines)
            u.awaiting = None
            await event.respond(
                f'✅ Added **{len(lines)}** numbers (total: **{len(u.numbers)}**)',
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )
        else:
            await event.respond('❌ No valid numbers found. Try again:')

    # ── Target Bot ──
    elif u.awaiting == 'target_bot':
        u.target_bot = text.lstrip('@')
        u.awaiting = None
        save_user(uid)
        await event.respond(
            f'✅ Target bot set to **@{u.target_bot}**',
            buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
            parse_mode='md'
        )

    # ── Delay ──
    elif u.awaiting == 'delay':
        try:
            parts = text.split()
            u.delay_min = float(parts[0])
            u.delay_max = float(parts[1]) if len(parts) > 1 else u.delay_min
            if u.delay_max < u.delay_min:
                u.delay_min, u.delay_max = u.delay_max, u.delay_min
            u.awaiting = None
            save_user(uid)
            await event.respond(
                f'✅ Delay set to **{u.delay_min}s – {u.delay_max}s**',
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )
        except Exception:
            await event.respond('❌ Invalid format. Send two numbers: `1.0 3.0`', parse_mode='md')


# ─── File Upload Handler ─────────────────────────────────────

@bot.on(events.NewMessage(func=lambda e: e.is_private and e.document))
async def file_handler(event):
    if not is_authorized(event.sender_id):
        return
    uid = event.chat_id
    u = get_user(uid)

    if u.awaiting != 'numbers_input':
        return

    try:
        file_bytes = await event.download_media(bytes)
        text = file_bytes.decode('utf-8', errors='ignore')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            u.numbers.extend(lines)
            u.awaiting = None
            await event.respond(
                f'✅ Loaded **{len(lines)}** numbers from file (total: **{len(u.numbers)}**)',
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )
        else:
            await event.respond('❌ File was empty or unreadable. Try again.')
    except Exception as e:
        await event.respond(f'❌ Error reading file: {e}')


# ─── /cancel ─────────────────────────────────────────────────

@bot.on(events.NewMessage(pattern=r'/cancel'))
async def cmd_cancel(event):
    if not is_authorized(event.sender_id):
        return
    u = get_user(event.chat_id)
    u.awaiting = None
    await event.respond(main_menu_text(u), buttons=main_menu_buttons(u), parse_mode='md')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SUB-MENU SCREENS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def show_account_menu(event, u):
    if u.is_authenticated:
        text = '🔐 **Account**\n\n✅ You are logged in.'
        buttons = [
            [Button.inline('🚪 Logout', b'account_logout')],
            [Button.inline('🔙 Main Menu', b'main_menu')]
        ]
    else:
        text = '🔐 **Account**\n\n❌ Not logged in.'
        buttons = [
            [Button.inline('📲 Login', b'account_login')],
            [Button.inline('🔙 Main Menu', b'main_menu')]
        ]
    await event.edit(text, buttons=buttons, parse_mode='md')


async def start_login(event, u):
    u.awaiting = 'phone'
    await event.edit(
        '📲 **Login to Telegram**\n\n'
        'Send your phone number with country code:\n'
        'Example: `+12345678901`',
        buttons=[[Button.inline('🔙 Back', b'menu_account')]],
        parse_mode='md'
    )


async def do_logout(event, u, uid):
    if u.client:
        try:
            await u.client.disconnect()
        except Exception:
            pass
    u.client = None
    u.session_string = None
    u.is_authenticated = False
    u.awaiting = None
    save_user(uid)
    await event.answer('🚪 Logged out')
    await show_account_menu(event, u)


async def show_group_menu(event, u):
    if u.otp_group_link:
        text = f'📋 **OTP Group**\n\n✅ Set: `{u.otp_group_link}`'
        buttons = [
            [Button.inline('✏️ Change', b'group_set'), Button.inline('✅ Verify', b'group_verify')],
            [Button.inline('🗑 Clear', b'group_clear')],
            [Button.inline('🔙 Main Menu', b'main_menu')]
        ]
    else:
        text = '📋 **OTP Group**\n\n❌ No group set.'
        buttons = [
            [Button.inline('➕ Set Group', b'group_set')],
            [Button.inline('🔙 Main Menu', b'main_menu')]
        ]
    await event.edit(text, buttons=buttons, parse_mode='md')


async def verify_group(event, u):
    if not u.is_authenticated or not u.client:
        await event.answer('❌ Login first!', alert=True)
        return
    if not u.otp_group_link:
        await event.answer('❌ No group link set!', alert=True)
        return
    try:
        chat_id, topic_id = parse_telegram_link(u.otp_group_link)
        # Try to join if invite hash
        if isinstance(chat_id, str) and not str(chat_id).startswith('-'):
            try:
                await u.client(ImportChatInviteRequest(chat_id))
            except Exception:
                pass
        entity = await resolve_entity(u.client, chat_id)
        title = getattr(entity, 'title', str(chat_id))
        u.otp_group_entity = entity
        u.otp_topic_id = topic_id
        topic_text = f'\n📌 Topic ID: `{topic_id}`' if topic_id else ''
        await event.answer('✅ Group verified!')
        await event.edit(
            f'📋 **OTP Group Verified!**\n\n'
            f'📛 Name: **{title}**{topic_text}',
            buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
            parse_mode='md'
        )
    except Exception as e:
        await event.answer(f'❌ Failed: {str(e)[:100]}', alert=True)


async def show_numbers_menu(event, u):
    count = len(u.numbers)
    text = f'📁 **Numbers**\n\n📊 Loaded: **{count}**'
    buttons = [
        [Button.inline('📤 Upload / Paste', b'numbers_upload')],
        [Button.inline('👀 Preview', b'numbers_preview'), Button.inline('🔀 Shuffle', b'numbers_shuffle')],
        [Button.inline('🗑 Clear All', b'numbers_clear')],
        [Button.inline('🔙 Main Menu', b'main_menu')]
    ]
    await event.edit(text, buttons=buttons, parse_mode='md')


async def show_stats(event, u):
    s = u.stats
    total = max(s['total'], 1)
    sr = s['success'] / total * 100
    text = (
        '📊 **Statistics**\n\n'
        f'✅ Success: **{s["success"]}**\n'
        f'❌ Failed: **{s["failed"]}**\n'
        f'⏱ Timeout: **{s["timeout"]}**\n'
        f'📦 Total: **{s["total"]}**\n\n'
        f'📈 Success Rate: **{sr:.1f}%**\n'
        f'{progress_bar(s["success"], s["total"], 20)}'
    )
    buttons = [
        [Button.inline('📤 Export Results', b'stats_export'),
         Button.inline('🗑 Reset', b'stats_reset')],
        [Button.inline('🔙 Main Menu', b'main_menu')]
    ]
    await event.edit(text, buttons=buttons, parse_mode='md')


async def export_results(event, u):
    if not u.session_results:
        await event.answer('No results to export yet.', alert=True)
        return
    lines = [f'{num}\t{result}' for num, result in u.session_results.items()]
    content = 'Number\tResult\n' + '\n'.join(lines)
    buf = BytesIO(content.encode())
    buf.name = f'eden_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    await event.answer('📤 Exporting...')
    await bot.send_file(event.chat_id, buf, caption='📊 Task results export')


async def show_settings(event, u):
    text = (
        '⚙️ **Settings**\n\n'
        f'🤖 Target Bot: `@{u.target_bot}`\n'
        f'📦 Batch Size: **{u.batch_size}**\n'
        f'⏱ Timeout: **{u.timeout}s**\n'
        f'🔢 Match Digits: **last {u.match_digits}**\n'
        f'⏳ Delay: **{u.delay_min}s – {u.delay_max}s**'
    )
    buttons = [
        [Button.inline('🤖 Target Bot', b'set_target_bot'),
         Button.inline('📦 Batch Size', b'set_batch_size')],
        [Button.inline('⏱ Timeout', b'set_timeout'),
         Button.inline('🔢 Match Digits', b'set_match_digits')],
        [Button.inline('⏳ Delay', b'set_delay')],
        [Button.inline('🔙 Main Menu', b'main_menu')]
    ]
    await event.edit(text, buttons=buttons, parse_mode='md')


async def show_help(event):
    text = (
        '❓ **Eden OTP Bot — Help**\n\n'
        '**How it works:**\n'
        '1️⃣ Login with your Telegram account\n'
        '2️⃣ Set the OTP group link to monitor\n'
        '3️⃣ Upload numbers (file or paste)\n'
        '4️⃣ Start the task — numbers are sent to the target bot, '
        'OTPs are detected in the group, and auto-replied\n\n'
        '**Commands:**\n'
        '/start — Main menu\n'
        '/menu — Show menu\n'
        '/cancel — Cancel current input\n\n'
        '**Task Flow:**\n'
        '• Numbers are sent in configurable batches\n'
        '• OTP group is monitored for incoming codes\n'
        '• When a code matches (by last N digits), it\'s auto-replied\n'
        '• Random delays between sends to avoid detection\n\n'
        '**Tips:**\n'
        '• Use Live Monitor to verify the OTP group works\n'
        '• Adjust batch size & timeout in Settings\n'
        '• Shuffle numbers to randomize order\n'
        '• Export results when done for record keeping'
    )
    await event.edit(text, buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]], parse_mode='md')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def task_start_handler(event, u, uid):
    """Validate and launch the OTP task."""
    if u.task_running:
        await event.answer('⚠️ Task already running!', alert=True)
        return
    if not u.is_authenticated or not u.client:
        await event.answer('❌ Login first!', alert=True)
        return
    if not u.otp_group_link:
        await event.answer('❌ Set OTP group first!', alert=True)
        return
    if not u.numbers:
        await event.answer('❌ Upload numbers first!', alert=True)
        return

    await event.answer('🚀 Starting task...')
    u.task_running = True
    u.task_paused = False
    u.task_stop = False
    u.session_results.clear()

    # Launch in background so the callback returns immediately
    u.task_handle = asyncio.create_task(_run_task(uid, u))


async def _run_task(chat_id, u):
    """Core OTP task engine — runs as an async background task."""
    client = u.client
    status_msg = None

    try:
        # ── Resolve entities ──
        chat_id_parsed, topic_id = parse_telegram_link(u.otp_group_link)

        # Auto-join invite links
        if isinstance(chat_id_parsed, str) and not str(chat_id_parsed).startswith('-'):
            try:
                await client(ImportChatInviteRequest(chat_id_parsed))
            except Exception:
                pass

        group_entity = await resolve_entity(client, chat_id_parsed)
        bot_entity = await client.get_entity(u.target_bot)
        group_title = getattr(group_entity, 'title', '?')

        numbers_left = u.numbers.copy()
        total = len(numbers_left)
        otps = {}           # number -> otp code
        pending = set()     # numbers waiting for OTP
        last_group_activity = time.time()
        processed = 0

        # ── Send initial status message ──
        status_msg = await bot.send_message(
            chat_id,
            f'🚀 **Task Started**\n\n'
            f'📋 Group: **{group_title}**\n'
            f'🤖 Target: **@{u.target_bot}**\n'
            f'📁 Numbers: **{total}**\n'
            f'📦 Batch: **{u.batch_size}** | ⏱ Timeout: **{u.timeout}s**\n\n'
            f'{progress_bar(0, total)} 0/{total}',
            buttons=[
                [Button.inline('⏸ Pause', b'task_pause'),
                 Button.inline('🛑 Stop', b'task_stop')]
            ],
            parse_mode='md'
        )

        # ── OTP handler for group messages ──
        async def otp_handler(event_msg):
            nonlocal last_group_activity
            last_group_activity = time.time()

            # Topic filter
            if topic_id and event_msg.message.reply_to:
                if event_msg.message.reply_to.reply_to_msg_id != topic_id:
                    return

            msg_text = event_msg.raw_text
            found_otps = extract_all_otps(event_msg.message)
            if not found_otps:
                return

            for number in list(pending):
                tail = number[-u.match_digits:]
                if tail in msg_text:
                    for otp in found_otps:
                        if otps.get(number) != otp:
                            otps[number] = otp
                            log.info(f'OTP matched: {number} -> {otp}')
                            break

        handler = client.add_event_handler(
            otp_handler, events.NewMessage(chats=group_entity)
        )

        try:
            batch_num = 0
            while numbers_left and not u.task_stop:
                # ── Handle pause ──
                while u.task_paused and not u.task_stop:
                    try:
                        await status_msg.edit(
                            f'⏸ **PAUSED**\n\n'
                            f'{progress_bar(processed, total)} **{processed}/{total}**\n\n'
                            f'✅ {u.stats["success"]} | ❌ {u.stats["failed"]} | ⏱ {u.stats["timeout"]}',
                            buttons=[
                                [Button.inline('▶️ Resume', b'task_resume'),
                                 Button.inline('🛑 Stop', b'task_stop')]
                            ],
                            parse_mode='md'
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                if u.task_stop:
                    break

                # ── Pick batch ──
                batch_num += 1
                batch_size = min(u.batch_size, len(numbers_left))
                batch = numbers_left[:batch_size]
                pending.update(batch)

                log.info(f'Batch #{batch_num}: sending {len(batch)} numbers')

                # ── Send numbers to target bot ──
                for number in batch:
                    if u.task_stop:
                        break
                    try:
                        await client.send_message(bot_entity, number)
                        log.info(f'Sent: {number}')
                        delay = random.uniform(u.delay_min, u.delay_max)
                        await asyncio.sleep(delay)
                    except FloodWaitError as e:
                        log.warning(f'Flood wait: {e.seconds}s')
                        try:
                            await status_msg.edit(
                                f'⚠️ **Rate Limited** — waiting {e.seconds}s...\n\n'
                                f'{progress_bar(processed, total)} **{processed}/{total}**',
                                buttons=[[Button.inline('🛑 Stop', b'task_stop')]],
                                parse_mode='md'
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(e.seconds + 1)
                        await client.send_message(bot_entity, number)
                    except Exception as e:
                        log.error(f'Send error {number}: {e}')

                # ── Wait for OTPs & poll bot replies ──
                batch_start = time.time()
                last_update = 0

                while pending and time.time() - batch_start < u.timeout and not u.task_stop:
                    # Check bot messages for status
                    try:
                        async for msg in client.iter_messages(bot_entity, limit=25):
                            for number in list(pending):
                                if number not in msg.raw_text:
                                    continue
                                txt_lower = msg.raw_text.lower()
                                # Check if "in progress" — ready for OTP reply
                                if 'in progress' in txt_lower or 'progress' in txt_lower:
                                    if number in otps:
                                        otp = otps[number]
                                        await client.send_message(
                                            bot_entity, otp, reply_to=msg.id
                                        )
                                        u.session_results[number] = f'✅ OTP: {otp}'
                                        u.stats['success'] += 1
                                        processed += 1
                                        pending.discard(number)
                                        log.info(f'Replied OTP: {number} -> {otp}')
                                # Check for rejection/failure keywords
                                elif any(kw in txt_lower for kw in [
                                    'try later', 'submit this number again',
                                    'invalid', 'error', 'failed', 'expired',
                                    'already used', 'blocked', 'banned'
                                ]):
                                    first_line = msg.raw_text.splitlines()[0][:60]
                                    u.session_results[number] = f'❌ {first_line}'
                                    u.stats['failed'] += 1
                                    processed += 1
                                    pending.discard(number)
                                    log.info(f'Rejected: {number} — {first_line}')
                                    break
                    except Exception as e:
                        log.error(f'Poll error: {e}')

                    # ── Update status message every ~4 seconds ──
                    now = time.time()
                    if now - last_update > 4:
                        last_update = now
                        elapsed = now - batch_start
                        remaining_secs = max(0, u.timeout - elapsed)
                        group_icon = '🟢' if now - last_group_activity < 30 else '🟡'
                        pending_display = ', '.join(n[-4:] for n in list(pending)[:6])
                        if len(pending) > 6:
                            pending_display += f' +{len(pending) - 6}'

                        try:
                            await status_msg.edit(
                                f'🚀 **Task Running** — Batch #{batch_num}\n\n'
                                f'{progress_bar(processed, total)} **{processed}/{total}**\n\n'
                                f'✅ {u.stats["success"]} | '
                                f'❌ {u.stats["failed"]} | '
                                f'⏱ {u.stats["timeout"]}\n'
                                f'{group_icon} Group Monitor | '
                                f'⏳ Batch: {int(remaining_secs)}s left\n'
                                f'🔄 Pending: `{pending_display or "—"}`',
                                buttons=[
                                    [Button.inline('⏸ Pause', b'task_pause'),
                                     Button.inline('🛑 Stop', b'task_stop')]
                                ],
                                parse_mode='md'
                            )
                        except Exception:
                            pass

                    await asyncio.sleep(3)

                # ── Handle timeouts for this batch ──
                for number in list(pending):
                    u.session_results[number] = '⏱ Timeout'
                    u.stats['timeout'] += 1
                    processed += 1
                    pending.discard(number)
                    log.info(f'Timeout: {number}')

                # Remove batch from queue
                for number in batch:
                    if number in numbers_left:
                        numbers_left.remove(number)

                u.stats['total'] = processed
                save_user(chat_id)

                # Small cooldown between batches
                if numbers_left and not u.task_stop:
                    await asyncio.sleep(2)

        finally:
            client.remove_event_handler(handler)

        # ── Final Summary ──
        sr = u.stats['success'] / max(processed, 1) * 100
        summary = (
            f'{progress_bar(processed, total, 20)} **{processed}/{total}**\n\n'
            f'✅ Success: **{u.stats["success"]}**\n'
            f'❌ Failed: **{u.stats["failed"]}**\n'
            f'⏱ Timeout: **{u.stats["timeout"]}**\n\n'
            f'📈 Success Rate: **{sr:.1f}%**'
        )
        if u.task_stop:
            summary = '🛑 **Task Stopped**\n\n' + summary
        else:
            summary = '🏁 **Task Complete!**\n\n' + summary

        try:
            await status_msg.edit(
                summary,
                buttons=[
                    [Button.inline('📤 Export Results', b'stats_export')],
                    [Button.inline('🔙 Main Menu', b'main_menu')]
                ],
                parse_mode='md'
            )
        except Exception:
            await bot.send_message(
                chat_id, summary,
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )

    except Exception as e:
        log.error(f'Task error: {e}', exc_info=True)
        try:
            error_text = (
                f'❌ **Task Error**\n\n`{str(e)[:300]}`'
            )
            if status_msg:
                await status_msg.edit(
                    error_text,
                    buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                    parse_mode='md'
                )
            else:
                await bot.send_message(
                    chat_id, error_text,
                    buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                    parse_mode='md'
                )
        except Exception:
            pass
    finally:
        u.task_running = False
        u.task_paused = False
        u.task_stop = False
        save_user(chat_id)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIVE MONITOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def monitor_start_handler(event, u, uid):
    """Start live monitoring of the OTP group."""
    if not u.is_authenticated or not u.client:
        await event.answer('❌ Login first!', alert=True)
        return
    if not u.otp_group_link:
        await event.answer('❌ Set OTP group first!', alert=True)
        return
    if u.task_running:
        await event.answer('⚠️ A task is running — it already monitors the group.', alert=True)
        return

    await event.answer('👁 Starting monitor...')
    u.task_stop = False

    try:
        chat_id_parsed, topic_id = parse_telegram_link(u.otp_group_link)
        group_entity = await resolve_entity(u.client, chat_id_parsed)
        title = getattr(group_entity, 'title', '?')

        monitor_msg = await bot.send_message(
            uid,
            f'👁 **Live Monitor**\n\n'
            f'📋 Group: **{title}**\n'
            f'Listening for new messages...\n\n'
            f'_Waiting..._',
            buttons=[[Button.inline('🛑 Stop Monitor', b'monitor_stop')]],
            parse_mode='md'
        )

        msg_count = 0
        buffer = []

        async def monitor_handler(event_msg):
            nonlocal msg_count
            # Topic filter
            if topic_id and event_msg.message.reply_to:
                if event_msg.message.reply_to.reply_to_msg_id != topic_id:
                    return

            sender = await event_msg.get_sender()
            name = getattr(sender, 'first_name', '?')
            text = event_msg.raw_text.replace('\n', ' ')[:80]
            otps_found = extract_all_otps(event_msg.message)
            otp_str = f' 🔑 **{", ".join(otps_found)}**' if otps_found else ''

            msg_count += 1
            line = f'`{ts()}` **{name}**: {text}{otp_str}'
            buffer.append(line)
            if len(buffer) > 10:
                buffer.pop(0)

        handler = u.client.add_event_handler(
            monitor_handler, events.NewMessage(chats=group_entity)
        )

        try:
            last_edit = 0
            while not u.task_stop:
                now = time.time()
                if now - last_edit > 3 and buffer:
                    last_edit = now
                    display = '\n'.join(buffer[-8:])
                    try:
                        await monitor_msg.edit(
                            f'👁 **Live Monitor** | 📨 {msg_count} messages\n'
                            f'📋 **{title}**\n\n{display}',
                            buttons=[[Button.inline('🛑 Stop Monitor', b'monitor_stop')]],
                            parse_mode='md'
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1)
        finally:
            u.client.remove_event_handler(handler)

        try:
            await monitor_msg.edit(
                f'👁 **Monitor Stopped** | Total: {msg_count} messages',
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )
        except Exception:
            pass

    except Exception as e:
        await bot.send_message(
            uid, f'❌ Monitor error: `{e}`',
            buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
            parse_mode='md'
        )
    finally:
        u.task_stop = False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    log.info('Starting Eden OTP Bot...')
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    log.info(f'Bot ready: @{me.username}')
    log.info('Waiting for messages... (Ctrl+C to stop)')
    await bot.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
