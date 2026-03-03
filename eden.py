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
    PhoneCodeExpiredError, FloodWaitError, PhoneNumberInvalidError
)
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import GetChannelsRequest
from telethon.tl.types import PeerChannel, InputChannel

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOT_TOKEN = os.environ.get('EDEN_BOT_TOKEN', '8409880931:AAGTJZQcys7Iqi2IFVNA3AbHjXqz-IV6HhI')
API_ID = int(os.environ.get('EDEN_API_ID', '24268062'))
API_HASH = os.environ.get('EDEN_API_HASH', 'aaab3d4a5ab8f7b3024a3edbd88cabf7')

# Admin user ID — full unrestricted access, manages user approvals
ADMIN_ID = 7648364004

DATA_FILE = 'eden_data.json'
ACCESS_FILE = 'eden_access.json'

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
        self.temp_session_str = None

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
    """Resolve a chat entity, handling numeric IDs for private channels/megagroups."""
    if isinstance(chat_id, int) and str(chat_id).startswith('-100'):
        channel_id = int(str(chat_id)[4:])  # strip -100 prefix
        # Method 1: Use GetChannelsRequest with InputChannel (works for megagroups)
        try:
            result = await client(GetChannelsRequest([InputChannel(channel_id, 0)]))
            if result.chats:
                return result.chats[0]
        except Exception:
            pass
        # Method 2: Try get_input_entity first, then get_entity
        try:
            inp = await client.get_input_entity(PeerChannel(channel_id))
            return await client.get_entity(inp)
        except Exception:
            pass
        # Method 3: Direct with full -100 ID
        try:
            return await client.get_entity(chat_id)
        except Exception:
            pass
        # Method 4: Iterate dialogs to find it
        async for dialog in client.iter_dialogs():
            if dialog.entity and getattr(dialog.entity, 'id', None) == channel_id:
                return dialog.entity
        raise ValueError(f'Could not resolve channel {chat_id}. Make sure the account has joined this group.')
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

def _load_access():
    if os.path.exists(ACCESS_FILE):
        with open(ACCESS_FILE, 'r') as f:
            return json.load(f)
    return {}  # { "user_id": { "granted_at": timestamp, "expires_at": timestamp_or_0, "name": "..." } }


def _save_access(data):
    with open(ACCESS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def grant_access(user_id, name, duration_seconds=0):
    """Grant access to a user. duration_seconds=0 means infinite."""
    data = _load_access()
    now = time.time()
    expires = 0 if duration_seconds == 0 else now + duration_seconds
    data[str(user_id)] = {
        'granted_at': now,
        'expires_at': expires,
        'name': name
    }
    _save_access(data)


def revoke_access(user_id):
    """Revoke access from a user."""
    data = _load_access()
    data.pop(str(user_id), None)
    _save_access(data)


def is_authorized(user_id):
    """Check if user has active access."""
    if user_id == ADMIN_ID:
        return True
    data = _load_access()
    entry = data.get(str(user_id))
    if not entry:
        return False
    expires = entry.get('expires_at', 0)
    if expires == 0:
        return True  # infinite access
    if time.time() > expires:
        return False  # expired
    return True


def get_access_info(user_id):
    """Return access details or None."""
    data = _load_access()
    return data.get(str(user_id))


def get_remaining_time(user_id):
    """Return human-readable remaining access time."""
    entry = get_access_info(user_id)
    if not entry:
        return None
    expires = entry.get('expires_at', 0)
    if expires == 0:
        return '♾ Unlimited'
    remaining = expires - time.time()
    if remaining <= 0:
        return '⛔ Expired'
    hours = int(remaining // 3600)
    mins = int((remaining % 3600) // 60)
    if hours > 24:
        days = hours // 24
        return f'{days}d {hours % 24}h'
    return f'{hours}h {mins}m'


def list_all_access():
    """Return all access entries."""
    return _load_access()


# Track pending access requests: { user_id: { 'name': '...', 'username': '...', 'time': timestamp } }
pending_requests = {}

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
        '🌿 **Eden OTP Bot**\n'
        '━━━━━━━━━━━━━━\n\n'
        f'🔐 Account: {auth}\n'
        f'📋 Group: {group}\n'
        f'📁 Numbers: {nums}\n'
        f'🤖 Target: {bot_name}\n\n'
        'Select an option 👇'
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOT CLIENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bot = TelegramClient('eden_bot', API_ID, API_HASH)

# ─── /start ──────────────────────────────────────────────────

@bot.on(events.NewMessage(pattern=r'/start'))
async def cmd_start(event):
    uid = event.sender_id

    # ── Unauthorized user ──
    if not is_authorized(uid):
        sender = await event.get_sender()
        name = getattr(sender, 'first_name', 'Unknown')
        # Check if they already have a pending request
        if uid in pending_requests:
            await event.respond(
                '⏳ **Access Pending**\n\n'
                'Your request has been sent to the admin.\n'
                'Please wait for approval.',
                parse_mode='md'
            )
        else:
            # Check if expired
            info = get_access_info(uid)
            if info and info.get('expires_at', 0) != 0 and time.time() > info['expires_at']:
                await event.respond(
                    '⛔ **Access Expired**\n\n'
                    'Your access has expired. You can request a renewal below.',
                    buttons=[[Button.inline('🔑 Request Access', b'request_access')]],
                    parse_mode='md'
                )
            else:
                await event.respond(
                    '🔒 **Access Required**\n\n'
                    'You don\'t have access to this bot.\n'
                    'Click below to request access from the admin.',
                    buttons=[[Button.inline('🔑 Request Access', b'request_access')]],
                    parse_mode='md'
                )
        return

    u = get_user(event.chat_id)
    u.awaiting = None

    # Show remaining time for non-admin users
    access_line = ''
    if uid != ADMIN_ID:
        remaining = get_remaining_time(uid)
        if remaining:
            access_line = f'\n⏳ Access: {remaining}'

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

    text = main_menu_text(u)
    if access_line:
        text += access_line
    btns = main_menu_buttons(u)
    # Admin gets extra button
    if uid == ADMIN_ID:
        btns.append([Button.inline('👑 Admin Panel', b'admin_panel')])
    await event.respond(text, buttons=btns, parse_mode='md')


@bot.on(events.NewMessage(pattern=r'/menu'))
async def cmd_menu(event):
    if not is_authorized(event.sender_id):
        return
    u = get_user(event.chat_id)
    u.awaiting = None
    btns = main_menu_buttons(u)
    if event.sender_id == ADMIN_ID:
        btns.append([Button.inline('👑 Admin Panel', b'admin_panel')])
    await event.respond(main_menu_text(u), buttons=btns, parse_mode='md')

# ─── CALLBACK QUERY ROUTER ──────────────────────────────────

@bot.on(events.CallbackQuery)
async def callback_router(event):
    uid = event.chat_id
    data = event.data.decode()

    # ── Allow request_access callback for unauthorized users ──
    if data == 'request_access':
        await handle_request_access(event)
        return

    # ── Admin-only callbacks (approve/reject/revoke etc.) ──
    if data.startswith('admin_') or data.startswith('approve_') or data.startswith('reject_') or data.startswith('grant_'):
        if event.sender_id != ADMIN_ID:
            await event.answer('⛔ Admin only', alert=True)
            return
        await handle_admin_callback(event, data)
        return

    # ── Normal auth check ──
    if not is_authorized(event.sender_id):
        await event.answer('⛔ Not authorized. Send /start to request access.', alert=True)
        return

    u = get_user(uid)
    data_str = data

    try:
        # ── Main Menu ──
        if data_str == 'main_menu':
            u.awaiting = None
            btns = main_menu_buttons(u)
            if event.sender_id == ADMIN_ID:
                btns.append([Button.inline('👑 Admin Panel', b'admin_panel')])
            text = main_menu_text(u)
            if event.sender_id != ADMIN_ID:
                remaining = get_remaining_time(event.sender_id)
                if remaining:
                    text += f'\n⏳ Access: {remaining}'
            await event.edit(text, buttons=btns, parse_mode='md')

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
#  ACCESS REQUEST & ADMIN PANEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_request_access(event):
    """Handle when a user clicks 'Request Access'."""
    uid = event.sender_id
    if is_authorized(uid):
        await event.answer('✅ You already have access!')
        return
    if uid in pending_requests:
        await event.answer('⏳ Request already pending.', alert=True)
        return

    sender = await event.get_sender()
    name = getattr(sender, 'first_name', 'Unknown')
    username = getattr(sender, 'username', None)
    username_str = f'@{username}' if username else 'No username'

    pending_requests[uid] = {
        'name': name,
        'username': username_str,
        'time': time.time()
    }

    await event.answer('✅ Request sent!')
    await event.edit(
        '⏳ **Access Requested**\n\n'
        'Your request has been sent to the admin.\n'
        'You will be notified when it is approved.',
        parse_mode='md'
    )

    # Notify admin
    await bot.send_message(
        ADMIN_ID,
        f'🔔 **New Access Request**\n\n'
        f'👤 Name: **{name}**\n'
        f'🆔 ID: `{uid}`\n'
        f'📛 Username: {username_str}\n'
        f'⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        buttons=[
            [Button.inline('✅ Approve', f'approve_{uid}'.encode()),
             Button.inline('❌ Reject', f'reject_{uid}'.encode())]
        ],
        parse_mode='md'
    )
    log.info(f'Access request from {name} ({uid})')


async def handle_admin_callback(event, data):
    """Handle all admin-related callbacks."""

    # ── Approve user ──
    if data.startswith('approve_'):
        target_uid = int(data.split('_')[1])
        # Show timeframe options
        await event.edit(
            f'⏱ **Set Access Duration**\n\n'
            f'User: `{target_uid}`\n'
            f'How long should they have access?',
            buttons=[
                [Button.inline('1 Hour', f'grant_{target_uid}_3600'.encode()),
                 Button.inline('3 Hours', f'grant_{target_uid}_10800'.encode())],
                [Button.inline('6 Hours', f'grant_{target_uid}_21600'.encode()),
                 Button.inline('12 Hours', f'grant_{target_uid}_43200'.encode())],
                [Button.inline('24 Hours', f'grant_{target_uid}_86400'.encode()),
                 Button.inline('3 Days', f'grant_{target_uid}_259200'.encode())],
                [Button.inline('7 Days', f'grant_{target_uid}_604800'.encode()),
                 Button.inline('30 Days', f'grant_{target_uid}_2592000'.encode())],
                [Button.inline('♾ Unlimited', f'grant_{target_uid}_0'.encode())],
                [Button.inline('❌ Cancel', b'admin_panel')]
            ],
            parse_mode='md'
        )

    # ── Grant with duration ──
    elif data.startswith('grant_'):
        parts = data.split('_')
        target_uid = int(parts[1])
        duration = int(parts[2])

        req = pending_requests.pop(target_uid, {})
        name = req.get('name', 'Unknown')

        grant_access(target_uid, name, duration)

        if duration == 0:
            dur_text = '♾ Unlimited'
        elif duration >= 86400:
            dur_text = f'{duration // 86400} day(s)'
        else:
            dur_text = f'{duration // 3600} hour(s)'

        await event.edit(
            f'✅ **Access Granted**\n\n'
            f'👤 {name} (`{target_uid}`)\n'
            f'⏱ Duration: **{dur_text}**',
            buttons=[[Button.inline('🔙 Admin Panel', b'admin_panel')]],
            parse_mode='md'
        )

        # Notify the user
        try:
            await bot.send_message(
                target_uid,
                f'🎉 **Access Granted!**\n\n'
                f'You now have access to Eden OTP Bot.\n'
                f'⏱ Duration: **{dur_text}**\n\n'
                f'Send /start to begin!',
                parse_mode='md'
            )
        except Exception:
            pass
        log.info(f'Access granted to {name} ({target_uid}) for {dur_text}')

    # ── Reject user ──
    elif data.startswith('reject_'):
        target_uid = int(data.split('_')[1])
        req = pending_requests.pop(target_uid, {})
        name = req.get('name', 'Unknown')

        await event.edit(
            f'❌ **Request Rejected**\n\n'
            f'👤 {name} (`{target_uid}`)',
            buttons=[[Button.inline('🔙 Admin Panel', b'admin_panel')]],
            parse_mode='md'
        )

        # Notify the user
        try:
            await bot.send_message(
                target_uid,
                '❌ **Access Denied**\n\n'
                'Your request was not approved by the admin.',
                parse_mode='md'
            )
        except Exception:
            pass
        log.info(f'Access rejected for {name} ({target_uid})')

    # ── Admin Panel ──
    elif data == 'admin_panel':
        await show_admin_panel(event)

    # ── Revoke specific user ──
    elif data.startswith('admin_revoke_'):
        target_uid = int(data.split('_')[2])
        revoke_access(target_uid)
        await event.answer(f'🗑 Access revoked for {target_uid}')
        await show_admin_panel(event)

    # ── View all users ──
    elif data == 'admin_users':
        access = list_all_access()
        if not access:
            await event.edit(
                '👥 **Authorized Users**\n\nNo users have access yet.',
                buttons=[[Button.inline('🔙 Admin Panel', b'admin_panel')]],
                parse_mode='md'
            )
            return

        lines = []
        for uid_str, info in access.items():
            name = info.get('name', '?')
            expires = info.get('expires_at', 0)
            if expires == 0:
                status = '♾'
            elif time.time() > expires:
                status = '⛔ Expired'
            else:
                remaining = expires - time.time()
                hours = int(remaining // 3600)
                status = f'{hours}h left'
            lines.append(f'• {name} (`{uid_str}`) — {status}')

        text = '👥 **Authorized Users**\n\n' + '\n'.join(lines)

        # Build revoke buttons (up to 6 users shown)
        btns = []
        for uid_str in list(access.keys())[:6]:
            name = access[uid_str].get('name', uid_str)
            btns.append([Button.inline(f'🗑 Revoke {name}', f'admin_revoke_{uid_str}'.encode())])
        btns.append([Button.inline('🔙 Admin Panel', b'admin_panel')])

        await event.edit(text, buttons=btns, parse_mode='md')

    # ── View pending requests ──
    elif data == 'admin_pending':
        if not pending_requests:
            await event.edit(
                '📋 **Pending Requests**\n\nNo pending requests.',
                buttons=[[Button.inline('🔙 Admin Panel', b'admin_panel')]],
                parse_mode='md'
            )
            return

        lines = []
        btns = []
        for req_uid, info in pending_requests.items():
            name = info.get('name', '?')
            uname = info.get('username', '?')
            lines.append(f'• {name} ({uname}) — `{req_uid}`')
            btns.append([
                Button.inline(f'✅ {name}', f'approve_{req_uid}'.encode()),
                Button.inline(f'❌ {name}', f'reject_{req_uid}'.encode())
            ])
        btns.append([Button.inline('🔙 Admin Panel', b'admin_panel')])

        text = '📋 **Pending Requests**\n\n' + '\n'.join(lines)
        await event.edit(text, buttons=btns, parse_mode='md')


async def show_admin_panel(event):
    """Show the admin panel."""
    access = list_all_access()
    active = sum(1 for v in access.values()
                 if v.get('expires_at', 0) == 0 or time.time() < v.get('expires_at', 0))
    pending = len(pending_requests)

    await event.edit(
        '👑 **Admin Panel**\n\n'
        f'👥 Active Users: **{active}**\n'
        f'📋 Pending Requests: **{pending}**\n'
        f'📊 Total Registered: **{len(access)}**',
        buttons=[
            [Button.inline(f'👥 Users ({active})', b'admin_users'),
             Button.inline(f'📋 Pending ({pending})', b'admin_pending')],
            [Button.inline('🔙 Main Menu', b'main_menu')]
        ],
        parse_mode='md'
    )

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
            # Save session after send_code to preserve auth key + DC after potential migration
            u.temp_session_str = u.temp_client.session.save()
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
            # Ensure client is still properly connected (handles DC migration / reconnect)
            if not u.temp_client.is_connected():
                u.temp_client = TelegramClient(StringSession(u.temp_session_str), API_ID, API_HASH)
                await u.temp_client.connect()
            await u.temp_client.sign_in(u.phone, text, phone_code_hash=u.phone_code_hash)
            # Success
            u.session_string = u.temp_client.session.save()
            u.client = u.temp_client
            u.temp_client = None
            u.temp_session_str = None
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
        except PhoneCodeExpiredError:
            # Resend the code automatically
            try:
                u.temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
                await u.temp_client.connect()
                result = await u.temp_client.send_code_request(u.phone)
                u.phone_code_hash = result.phone_code_hash
                u.temp_session_str = u.temp_client.session.save()
                await event.respond(
                    '⚠️ **Code expired.** A new code has been sent.\n\n'
                    'Enter the new login code:',
                    parse_mode='md'
                )
            except Exception as resend_err:
                await event.respond(f'❌ Code expired and resend failed: {resend_err}')
                u.awaiting = None
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
        numbers = _extract_numbers(text)
        if numbers:
            u.numbers.extend(numbers)
            u.awaiting = None
            await event.respond(
                f'✅ Added **{len(numbers)}** numbers (total: **{len(u.numbers)}**)',
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

def _decode_file(raw: bytes) -> str:
    """Auto-detect encoding and decode file bytes to string."""
    # Check for BOM markers first
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8', errors='ignore')
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', errors='ignore')
    # Try UTF-8 strict
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    # Try UTF-16 (handles null bytes between chars)
    if b'\x00' in raw[:100]:
        try:
            return raw.decode('utf-16')
        except Exception:
            try:
                return raw.decode('utf-16-le')
            except Exception:
                pass
    # Fallback to latin-1 (never fails)
    return raw.decode('latin-1')


def _extract_numbers(text: str) -> list:
    """Extract phone numbers from text, handling various formats."""
    # First try splitting by lines
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # If only 1 line or no lines, try splitting by comma, semicolon, tab, space
    if len(lines) <= 1:
        flat = lines[0] if lines else text
        for sep in [',', ';', '\t', '|']:
            parts = [p.strip() for p in flat.split(sep) if p.strip()]
            if len(parts) > 1:
                lines = parts
                break

    # If still 1 entry and it's very long, try splitting by spaces
    if len(lines) <= 1 and lines:
        raw = lines[0]
        if len(raw) > 30:
            parts = raw.split()
            if len(parts) > 1 and all(any(c.isdigit() for c in p) for p in parts[:5]):
                lines = parts

    # Clean each number: keep only digits and leading +
    cleaned = []
    for line in lines:
        # Remove common labels/prefixes
        line = re.sub(r'^[\d]+[.):\-]\s*', '', line)  # strip "1. " or "1) " prefixes
        # Keep only phone-number characters
        num = re.sub(r'[^\d+]', '', line)
        if num and len(num) >= 4:  # at least 4 digits to be a phone number
            cleaned.append(num)

    return cleaned


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
        text = _decode_file(file_bytes)
        numbers = _extract_numbers(text)
        if numbers:
            u.numbers.extend(numbers)
            u.awaiting = None
            preview = numbers[0] + (' ...' if len(numbers) > 1 else '')
            await event.respond(
                f'✅ Loaded **{len(numbers)}** numbers from file\n'
                f'📊 Total: **{len(u.numbers)}**\n'
                f'🔍 Preview: `{preview}`',
                buttons=[[Button.inline('🔙 Main Menu', b'main_menu')]],
                parse_mode='md'
            )
        else:
            await event.respond(
                '❌ No valid numbers found in file.\n\n'
                'Make sure the file contains phone numbers\n'
                '(one per line, with or without `+`).',
                parse_mode='md'
            )
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
