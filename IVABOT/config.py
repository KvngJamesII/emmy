import os

# ============================================
# MAIN BOT CONFIGURATION
# ============================================

# Main IVASMS OTP Sender bot token (create a NEW bot on @BotFather for this)
BOT_TOKEN = "8505844199:AAFZrY9l3Faj5J-lga3Bb3A1dF6jPME201o"

# Your Telegram user ID (you are the admin)
ADMIN_ID = 7648364004

# Admin contact username (shown to users for subscription)
ADMIN_CONTACT = "@theidledeveloper"

# ============================================
# PATHS
# ============================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "ivasms.db")
KEY_FILE = os.path.join(DATA_DIR, "secret.key")

# ============================================
# IVASMS PANEL URLS
# ============================================
PANEL_BASE_URL = "https://ivas.tempnum.qzz.io"
PANEL_LOGIN_URL = f"{PANEL_BASE_URL}/login"
PANEL_SMS_URL = f"{PANEL_BASE_URL}/portal/sms/received/getsms"

# ============================================
# POLLING
# ============================================
POLL_INTERVAL = 5       # seconds between polls
LOGIN_REFRESH = 600     # seconds before session refresh (10 min)

# ============================================
# SUBSCRIPTION PLANS (display only)
# ============================================
PLANS_DISPLAY = [
    {"code": "1m", "label": "1 Month", "price": "$4"},
    {"code": "3m", "label": "3 Months", "price": "$10"},
]

# Duration map for admin /subscribe command
DURATION_MAP = {
    "1min": {"minutes": 1},
    "1h":   {"hours": 1},
    "1d":   {"days": 1},
    "1w":   {"weeks": 1},
    "1m":   {"days": 30},
    "2m":   {"days": 60},
    "3m":   {"days": 90},
    "6m":   {"days": 180},
    "1y":   {"days": 365},
}
