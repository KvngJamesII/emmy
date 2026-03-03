"""
IVASMS Panel session client.
Handles login, CSRF tokens, and SMS fetching for a single panel account.
Extracted from the original bot.py OTP polling logic.
"""

import re
import time
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from config import PANEL_BASE_URL, PANEL_LOGIN_URL, PANEL_SMS_URL

# ============================================
# LOOKUP DATA
# ============================================

COUNTRY_FLAGS = {
    "Afghanistan": "\U0001f1e6\U0001f1eb", "Albania": "\U0001f1e6\U0001f1f1",
    "Algeria": "\U0001f1e9\U0001f1ff", "Andorra": "\U0001f1e6\U0001f1e9",
    "Angola": "\U0001f1e6\U0001f1f4", "Argentina": "\U0001f1e6\U0001f1f7",
    "Armenia": "\U0001f1e6\U0001f1f2", "Australia": "\U0001f1e6\U0001f1fa",
    "Austria": "\U0001f1e6\U0001f1f9", "Azerbaijan": "\U0001f1e6\U0001f1ff",
    "Bahrain": "\U0001f1e7\U0001f1ed", "Bangladesh": "\U0001f1e7\U0001f1e9",
    "Belarus": "\U0001f1e7\U0001f1fe", "Belgium": "\U0001f1e7\U0001f1ea",
    "Benin": "\U0001f1e7\U0001f1ef", "Bhutan": "\U0001f1e7\U0001f1f9",
    "Bolivia": "\U0001f1e7\U0001f1f4", "Brazil": "\U0001f1e7\U0001f1f7",
    "Bulgaria": "\U0001f1e7\U0001f1ec", "Burkina Faso": "\U0001f1e7\U0001f1eb",
    "Cambodia": "\U0001f1f0\U0001f1ed", "Cameroon": "\U0001f1e8\U0001f1f2",
    "Canada": "\U0001f1e8\U0001f1e6", "Chad": "\U0001f1f9\U0001f1e9",
    "Chile": "\U0001f1e8\U0001f1f1", "China": "\U0001f1e8\U0001f1f3",
    "Colombia": "\U0001f1e8\U0001f1f4", "Congo": "\U0001f1e8\U0001f1ec",
    "Croatia": "\U0001f1ed\U0001f1f7", "Cuba": "\U0001f1e8\U0001f1fa",
    "Cyprus": "\U0001f1e8\U0001f1fe", "Czech Republic": "\U0001f1e8\U0001f1ff",
    "Denmark": "\U0001f1e9\U0001f1f0", "Egypt": "\U0001f1ea\U0001f1ec",
    "Estonia": "\U0001f1ea\U0001f1ea", "Ethiopia": "\U0001f1ea\U0001f1f9",
    "Finland": "\U0001f1eb\U0001f1ee", "France": "\U0001f1eb\U0001f1f7",
    "Gabon": "\U0001f1ec\U0001f1e6", "Gambia": "\U0001f1ec\U0001f1f2",
    "Georgia": "\U0001f1ec\U0001f1ea", "Germany": "\U0001f1e9\U0001f1ea",
    "Ghana": "\U0001f1ec\U0001f1ed", "Greece": "\U0001f1ec\U0001f1f7",
    "Guatemala": "\U0001f1ec\U0001f1f9", "Guinea": "\U0001f1ec\U0001f1f3",
    "Haiti": "\U0001f1ed\U0001f1f9", "Honduras": "\U0001f1ed\U0001f1f3",
    "Hong Kong": "\U0001f1ed\U0001f1f0", "Hungary": "\U0001f1ed\U0001f1fa",
    "Iceland": "\U0001f1ee\U0001f1f8", "India": "\U0001f1ee\U0001f1f3",
    "Indonesia": "\U0001f1ee\U0001f1e9", "Iran": "\U0001f1ee\U0001f1f7",
    "Iraq": "\U0001f1ee\U0001f1f6", "Ireland": "\U0001f1ee\U0001f1ea",
    "Israel": "\U0001f1ee\U0001f1f1", "Italy": "\U0001f1ee\U0001f1f9",
    "IVORY COAST": "\U0001f1e8\U0001f1ee", "Ivory Coast": "\U0001f1e8\U0001f1ee",
    "Jamaica": "\U0001f1ef\U0001f1f2", "Japan": "\U0001f1ef\U0001f1f5",
    "Jordan": "\U0001f1ef\U0001f1f4", "Kazakhstan": "\U0001f1f0\U0001f1ff",
    "Kenya": "\U0001f1f0\U0001f1ea", "Kuwait": "\U0001f1f0\U0001f1fc",
    "Kyrgyzstan": "\U0001f1f0\U0001f1ec", "Laos": "\U0001f1f1\U0001f1e6",
    "Latvia": "\U0001f1f1\U0001f1fb", "Lebanon": "\U0001f1f1\U0001f1e7",
    "Liberia": "\U0001f1f1\U0001f1f7", "Libya": "\U0001f1f1\U0001f1fe",
    "Lithuania": "\U0001f1f1\U0001f1f9", "Luxembourg": "\U0001f1f1\U0001f1fa",
    "Madagascar": "\U0001f1f2\U0001f1ec", "Malaysia": "\U0001f1f2\U0001f1fe",
    "Mali": "\U0001f1f2\U0001f1f1", "Malta": "\U0001f1f2\U0001f1f9",
    "Mexico": "\U0001f1f2\U0001f1fd", "Moldova": "\U0001f1f2\U0001f1e9",
    "Monaco": "\U0001f1f2\U0001f1e8", "Mongolia": "\U0001f1f2\U0001f1f3",
    "Montenegro": "\U0001f1f2\U0001f1ea", "Morocco": "\U0001f1f2\U0001f1e6",
    "Mozambique": "\U0001f1f2\U0001f1ff", "Myanmar": "\U0001f1f2\U0001f1f2",
    "Namibia": "\U0001f1f3\U0001f1e6", "Nepal": "\U0001f1f3\U0001f1f5",
    "Netherlands": "\U0001f1f3\U0001f1f1", "New Zealand": "\U0001f1f3\U0001f1ff",
    "Nicaragua": "\U0001f1f3\U0001f1ee", "Niger": "\U0001f1f3\U0001f1ea",
    "Nigeria": "\U0001f1f3\U0001f1ec", "North Korea": "\U0001f1f0\U0001f1f5",
    "North Macedonia": "\U0001f1f2\U0001f1f0", "Norway": "\U0001f1f3\U0001f1f4",
    "Oman": "\U0001f1f4\U0001f1f2", "Pakistan": "\U0001f1f5\U0001f1f0",
    "Panama": "\U0001f1f5\U0001f1e6", "Paraguay": "\U0001f1f5\U0001f1fe",
    "Peru": "\U0001f1f5\U0001f1ea", "Philippines": "\U0001f1f5\U0001f1ed",
    "Poland": "\U0001f1f5\U0001f1f1", "Portugal": "\U0001f1f5\U0001f1f9",
    "Qatar": "\U0001f1f6\U0001f1e6", "Romania": "\U0001f1f7\U0001f1f4",
    "Russia": "\U0001f1f7\U0001f1fa", "Rwanda": "\U0001f1f7\U0001f1fc",
    "Saudi Arabia": "\U0001f1f8\U0001f1e6", "Senegal": "\U0001f1f8\U0001f1f3",
    "Serbia": "\U0001f1f7\U0001f1f8", "Sierra Leone": "\U0001f1f8\U0001f1f1",
    "Singapore": "\U0001f1f8\U0001f1ec", "Slovakia": "\U0001f1f8\U0001f1f0",
    "Slovenia": "\U0001f1f8\U0001f1ee", "Somalia": "\U0001f1f8\U0001f1f4",
    "South Africa": "\U0001f1ff\U0001f1e6", "South Korea": "\U0001f1f0\U0001f1f7",
    "Spain": "\U0001f1ea\U0001f1f8", "Sri Lanka": "\U0001f1f1\U0001f1f0",
    "Sudan": "\U0001f1f8\U0001f1e9", "Sweden": "\U0001f1f8\U0001f1ea",
    "Switzerland": "\U0001f1e8\U0001f1ed", "Syria": "\U0001f1f8\U0001f1fe",
    "Taiwan": "\U0001f1f9\U0001f1fc", "Tajikistan": "\U0001f1f9\U0001f1ef",
    "Tanzania": "\U0001f1f9\U0001f1ff", "Thailand": "\U0001f1f9\U0001f1ed",
    "TOGO": "\U0001f1f9\U0001f1ec", "Tunisia": "\U0001f1f9\U0001f1f3",
    "Turkey": "\U0001f1f9\U0001f1f7", "Turkmenistan": "\U0001f1f9\U0001f1f2",
    "Uganda": "\U0001f1fa\U0001f1ec", "Ukraine": "\U0001f1fa\U0001f1e6",
    "United Arab Emirates": "\U0001f1e6\U0001f1ea",
    "United Kingdom": "\U0001f1ec\U0001f1e7",
    "United States": "\U0001f1fa\U0001f1f8", "Uruguay": "\U0001f1fa\U0001f1fe",
    "Uzbekistan": "\U0001f1fa\U0001f1ff", "Venezuela": "\U0001f1fb\U0001f1ea",
    "Vietnam": "\U0001f1fb\U0001f1f3", "Yemen": "\U0001f1fe\U0001f1ea",
    "Zambia": "\U0001f1ff\U0001f1f2", "Zimbabwe": "\U0001f1ff\U0001f1fc",
}

SERVICE_KEYWORDS = {
    "Facebook": ["facebook"], "Google": ["google", "gmail"],
    "WhatsApp": ["whatsapp"], "Telegram": ["telegram"],
    "Instagram": ["instagram"], "Amazon": ["amazon"],
    "Netflix": ["netflix"], "LinkedIn": ["linkedin"],
    "Microsoft": ["microsoft", "outlook", "live.com"],
    "Apple": ["apple", "icloud"], "Twitter": ["twitter"],
    "Snapchat": ["snapchat"], "TikTok": ["tiktok"],
    "Discord": ["discord"], "Signal": ["signal"],
    "Viber": ["viber"], "IMO": ["imo"], "PayPal": ["paypal"],
    "Binance": ["binance"], "Uber": ["uber"], "Bolt": ["bolt"],
    "Airbnb": ["airbnb"], "Yahoo": ["yahoo"], "Steam": ["steam"],
    "Spotify": ["spotify"], "Stripe": ["stripe"], "Coinbase": ["coinbase"],
}

SERVICE_EMOJIS = {
    "Telegram": "\U0001f4e9", "WhatsApp": "\U0001f7e2",
    "Facebook": "\U0001f4d8", "Instagram": "\U0001f4f8",
    "Google": "\U0001f50d", "Gmail": "\u2709\ufe0f",
    "Twitter": "\U0001f426", "TikTok": "\U0001f3b5",
    "Snapchat": "\U0001f47b", "Amazon": "\U0001f6d2",
    "Microsoft": "\U0001fa9f", "Netflix": "\U0001f3ac",
    "Spotify": "\U0001f3b6", "Apple": "\U0001f34f",
    "PayPal": "\U0001f4b0", "Binance": "\U0001fa99",
    "Discord": "\U0001f5e8\ufe0f", "Steam": "\U0001f3ae",
    "LinkedIn": "\U0001f4bc", "Uber": "\U0001f697",
    "Bolt": "\U0001f696", "Stripe": "\U0001f4b3",
    "Coinbase": "\U0001fa99", "Signal": "\U0001f510",
    "Viber": "\U0001f4de", "Yahoo": "\U0001f7e3",
    "Airbnb": "\U0001f3e0", "IMO": "\U0001f4ac",
    "Unknown": "\u2753",
}


# ============================================
# HELPERS
# ============================================

def detect_service(sms_text):
    lower = sms_text.lower()
    for service, keywords in SERVICE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return service
    return "Unknown"


def extract_otp(sms_text):
    m = re.search(r"(\d{3}-\d{3})", sms_text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{4,8})\b", sms_text)
    if m:
        return m.group(1)
    return "N/A"


def get_flag(country):
    return (
        COUNTRY_FLAGS.get(country)
        or COUNTRY_FLAGS.get(country.title())
        or COUNTRY_FLAGS.get(country.upper())
        or COUNTRY_FLAGS.get(country.capitalize())
        or "\U0001f3f3\ufe0f"
    )


# ============================================
# PANEL SESSION
# ============================================

class PanelSession:
    """Manages a login session for one IVASMS panel account."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.client = None
        self.csrf = None
        self.last_login = 0

    async def login(self):
        """Log into the panel. Returns True on success."""
        try:
            if self.client:
                try:
                    await self.client.aclose()
                except Exception:
                    pass

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Connection": "keep-alive",
            }
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
            self.client = httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, headers=headers, limits=limits
            )

            login_page = await self.client.get(PANEL_LOGIN_URL)
            soup = BeautifulSoup(login_page.text, "html.parser")
            token_input = soup.find("input", {"name": "_token"})

            login_data = {"email": self.username, "password": self.password}
            if token_input:
                login_data["_token"] = token_input["value"]

            login_res = await self.client.post(PANEL_LOGIN_URL, data=login_data)

            if "login" in str(login_res.url):
                self.csrf = None
                return False

            dash_soup = BeautifulSoup(login_res.text, "html.parser")
            csrf_meta = dash_soup.find("meta", {"name": "csrf-token"})
            if not csrf_meta:
                self.csrf = None
                return False

            self.csrf = csrf_meta.get("content")
            self.last_login = time.time()
            return True

        except Exception:
            self.csrf = None
            return False

    async def fetch_sms(self):
        """Fetch SMS messages from the panel. Returns a list of message dicts."""
        messages = []
        try:
            today = datetime.now(timezone.utc)
            start_date = today - timedelta(days=1)
            from_str = start_date.strftime("%m/%d/%Y")
            to_str = today.strftime("%m/%d/%Y")

            payload = {"from": from_str, "to": to_str, "_token": self.csrf}
            summary_res = await self.client.post(PANEL_SMS_URL, data=payload)
            summary_res.raise_for_status()

            soup = BeautifulSoup(summary_res.text, "html.parser")
            group_divs = soup.find_all("div", {"class": "pointer"})
            if not group_divs:
                return []

            group_ids = []
            for div in group_divs:
                match = re.search(r"getDetials\('(.+?)'\)", div.get("onclick", ""))
                if match:
                    group_ids.append(match.group(1))

            numbers_url = urljoin(PANEL_BASE_URL, "/portal/sms/received/getsms/number")
            sms_detail_url = urljoin(PANEL_BASE_URL, "/portal/sms/received/getsms/number/sms")

            for group_id in group_ids:
                try:
                    num_payload = {
                        "start": from_str, "end": to_str,
                        "range": group_id, "_token": self.csrf,
                    }
                    num_res = await self.client.post(numbers_url, data=num_payload)
                    num_soup = BeautifulSoup(num_res.text, "html.parser")
                    number_divs = num_soup.select("div[onclick*='getDetialsNumber']")
                    if not number_divs:
                        continue

                    for num_div in number_divs:
                        phone = num_div.text.strip()
                        try:
                            sms_payload = {
                                "start": from_str, "end": to_str,
                                "Number": phone, "Range": group_id,
                                "_token": self.csrf,
                            }
                            sms_res = await self.client.post(sms_detail_url, data=sms_payload)
                            sms_soup = BeautifulSoup(sms_res.text, "html.parser")
                            cards = sms_soup.find_all("div", class_="card-body")

                            for card in cards:
                                text_p = card.find("p", class_="mb-0")
                                if text_p:
                                    sms_text = text_p.get_text(separator="\n").strip()
                                    country_match = re.match(r"([a-zA-Z\s]+)", group_id)
                                    country = (
                                        country_match.group(1).strip()
                                        if country_match
                                        else group_id.strip()
                                    )
                                    messages.append({
                                        "id": f"{phone}-{sms_text}",
                                        "number": phone,
                                        "country": country,
                                        "sms": sms_text,
                                        "service": detect_service(sms_text),
                                        "otp": extract_otp(sms_text),
                                        "flag": get_flag(country),
                                    })
                        except Exception:
                            pass
                except Exception:
                    pass

            return messages
        except Exception:
            return []

    async def close(self):
        """Close the HTTP client session."""
        if self.client:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
