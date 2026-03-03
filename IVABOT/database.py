import aiosqlite
import os
from datetime import datetime, timezone, timedelta

_db_path = None


def setup(db_path):
    """Set the database path and ensure directory exists."""
    global _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)


def _get_db():
    return aiosqlite.connect(_db_path)


async def init_db():
    """Create all tables if they don't exist."""
    async with _get_db() as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                token TEXT NOT NULL,
                group_id TEXT,
                admin_verified INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                login_verified INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL UNIQUE,
                panel_id INTEGER NOT NULL,
                is_fetching INTEGER DEFAULT 0,
                FOREIGN KEY (bot_id) REFERENCES bots(id),
                FOREIGN KEY (panel_id) REFERENCES panels(id)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT,
                start_date TEXT,
                end_date TEXT,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS processed_messages (
                link_id INTEGER NOT NULL,
                message_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (link_id, message_hash)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                user_id INTEGER PRIMARY KEY,
                referred_by INTEGER NOT NULL,
                rewarded INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id),
                FOREIGN KEY (referred_by) REFERENCES users(telegram_id)
            );
        """)
        await conn.commit()


# ============================================
# USERS
# ============================================

async def ensure_user(telegram_id, username=None, first_name=None):
    async with _get_db() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (telegram_id, username, first_name),
        )
        await conn.commit()


async def get_user_by_id(telegram_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ============================================
# BOTS
# ============================================

async def add_bot(user_id, name, token):
    async with _get_db() as conn:
        cursor = await conn.execute(
            "INSERT INTO bots (user_id, name, token) VALUES (?, ?, ?)",
            (user_id, name, token),
        )
        await conn.commit()
        return cursor.lastrowid


async def get_user_bots(user_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT b.*, l.panel_id, l.is_fetching, p.username AS panel_username "
            "FROM bots b "
            "LEFT JOIN links l ON l.bot_id = b.id "
            "LEFT JOIN panels p ON p.id = l.panel_id "
            "WHERE b.user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_bot(bot_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT b.*, l.panel_id, l.is_fetching, l.id AS link_id, p.username AS panel_username "
            "FROM bots b "
            "LEFT JOIN links l ON l.bot_id = b.id "
            "LEFT JOIN panels p ON p.id = l.panel_id "
            "WHERE b.id = ?",
            (bot_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_bot_by_user_and_id(user_id, bot_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM bots WHERE id = ? AND user_id = ?", (bot_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_bot_group(bot_id, group_id):
    async with _get_db() as conn:
        await conn.execute(
            "UPDATE bots SET group_id = ?, admin_verified = 1 WHERE id = ?",
            (group_id, bot_id),
        )
        await conn.commit()


async def delete_bot(bot_id):
    async with _get_db() as conn:
        await conn.execute(
            "DELETE FROM processed_messages WHERE link_id IN (SELECT id FROM links WHERE bot_id = ?)",
            (bot_id,),
        )
        await conn.execute("DELETE FROM links WHERE bot_id = ?", (bot_id,))
        await conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        await conn.commit()


# ============================================
# PANELS
# ============================================

async def add_panel(user_id, username, password):
    async with _get_db() as conn:
        cursor = await conn.execute(
            "INSERT INTO panels (user_id, username, password, login_verified) VALUES (?, ?, ?, 1)",
            (user_id, username, password),
        )
        await conn.commit()
        return cursor.lastrowid


async def get_user_panels(user_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM panels WHERE user_id = ?", (user_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_panel(panel_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM panels WHERE id = ?", (panel_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_panel(panel_id):
    async with _get_db() as conn:
        await conn.execute("UPDATE links SET is_fetching = 0 WHERE panel_id = ?", (panel_id,))
        await conn.execute("DELETE FROM links WHERE panel_id = ?", (panel_id,))
        await conn.execute("DELETE FROM panels WHERE id = ?", (panel_id,))
        await conn.commit()


# ============================================
# LINKS (bot <-> panel)
# ============================================

async def link_bot_panel(bot_id, panel_id):
    async with _get_db() as conn:
        await conn.execute(
            "INSERT INTO links (bot_id, panel_id) VALUES (?, ?) "
            "ON CONFLICT(bot_id) DO UPDATE SET panel_id=excluded.panel_id, is_fetching=0",
            (bot_id, panel_id),
        )
        await conn.commit()


async def unlink_bot(bot_id):
    async with _get_db() as conn:
        await conn.execute("DELETE FROM links WHERE bot_id = ?", (bot_id,))
        await conn.commit()


async def set_fetching(bot_id, is_fetching):
    async with _get_db() as conn:
        await conn.execute(
            "UPDATE links SET is_fetching = ? WHERE bot_id = ?",
            (1 if is_fetching else 0, bot_id),
        )
        await conn.commit()


async def get_active_links():
    """Get all links where is_fetching=1, joined with bot/panel/subscription data."""
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT l.id AS link_id, l.bot_id, l.panel_id, l.is_fetching, "
            "b.token AS bot_token, b.group_id, b.name AS bot_name, b.user_id, "
            "p.username AS panel_username, p.password AS panel_password, "
            "s.end_date, s.active AS sub_active "
            "FROM links l "
            "JOIN bots b ON b.id = l.bot_id "
            "JOIN panels p ON p.id = l.panel_id "
            "LEFT JOIN subscriptions s ON s.user_id = b.user_id AND s.active = 1 "
            "WHERE l.is_fetching = 1 AND b.admin_verified = 1 AND b.group_id IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================================
# SUBSCRIPTIONS
# ============================================

async def get_subscription(user_id):
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_subscription(user_id, plan, end_date):
    async with _get_db() as conn:
        await conn.execute("UPDATE subscriptions SET active = 0 WHERE user_id = ?", (user_id,))
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "INSERT INTO subscriptions (user_id, plan, start_date, end_date, active) VALUES (?, ?, ?, ?, 1)",
            (user_id, plan, now, end_date),
        )
        await conn.commit()


async def revoke_subscription(user_id):
    async with _get_db() as conn:
        await conn.execute("UPDATE subscriptions SET active = 0 WHERE user_id = ?", (user_id,))
        await conn.execute(
            "UPDATE links SET is_fetching = 0 WHERE bot_id IN (SELECT id FROM bots WHERE user_id = ?)",
            (user_id,),
        )
        await conn.commit()


async def is_subscription_active(user_id):
    sub = await get_subscription(user_id)
    if not sub:
        return False
    try:
        end = datetime.fromisoformat(sub["end_date"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return end > datetime.now(timezone.utc)
    except Exception:
        return False


async def stop_all_user_fetching(user_id):
    async with _get_db() as conn:
        await conn.execute(
            "UPDATE links SET is_fetching = 0 WHERE bot_id IN (SELECT id FROM bots WHERE user_id = ?)",
            (user_id,),
        )
        await conn.commit()


# ============================================
# PROCESSED MESSAGES
# ============================================

async def is_message_processed(link_id, message_hash):
    async with _get_db() as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM processed_messages WHERE link_id = ? AND message_hash = ?",
            (link_id, message_hash),
        )
        return await cursor.fetchone() is not None


async def mark_message_processed(link_id, message_hash):
    async with _get_db() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO processed_messages (link_id, message_hash) VALUES (?, ?)",
            (link_id, message_hash),
        )
        await conn.commit()


async def cleanup_old_processed(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with _get_db() as conn:
        await conn.execute("DELETE FROM processed_messages WHERE created_at < ?", (cutoff,))
        await conn.commit()


# ============================================
# ADMIN STATS
# ============================================

async def get_all_users():
    async with _get_db() as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT u.*, "
            "(SELECT COUNT(*) FROM bots WHERE user_id = u.telegram_id) AS bot_count, "
            "(SELECT COUNT(*) FROM subscriptions WHERE user_id = u.telegram_id AND active = 1) AS has_sub "
            "FROM users u ORDER BY u.joined_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_stats():
    async with _get_db() as conn:
        stats = {}
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = (await cursor.fetchone())[0]
        cursor = await conn.execute("SELECT COUNT(*) FROM bots")
        stats["total_bots"] = (await cursor.fetchone())[0]
        cursor = await conn.execute("SELECT COUNT(*) FROM panels")
        stats["total_panels"] = (await cursor.fetchone())[0]
        cursor = await conn.execute("SELECT COUNT(*) FROM links WHERE is_fetching = 1")
        stats["active_fetching"] = (await cursor.fetchone())[0]
        cursor = await conn.execute("SELECT COUNT(*) FROM subscriptions WHERE active = 1")
        stats["active_subs"] = (await cursor.fetchone())[0]
        return stats


# ============================================
# REFERRALS
# ============================================

async def save_referral(user_id, referred_by):
    """Save that user_id was referred by referred_by. Ignores if already exists."""
    async with _get_db() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO referrals (user_id, referred_by) VALUES (?, ?)",
            (user_id, referred_by),
        )
        await conn.commit()


async def get_referrer(user_id):
    """Get the ID of who referred this user (if any)."""
    async with _get_db() as conn:
        cursor = await conn.execute(
            "SELECT referred_by, rewarded FROM referrals WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return {"referred_by": row[0], "rewarded": row[1]} if row else None


async def mark_referral_rewarded(user_id):
    """Mark that the referral reward has been given for this user."""
    async with _get_db() as conn:
        await conn.execute(
            "UPDATE referrals SET rewarded = 1 WHERE user_id = ?", (user_id,)
        )
        await conn.commit()


async def get_referral_count(user_id):
    """Count how many users were referred by this user."""
    async with _get_db() as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referred_by = ?", (user_id,)
        )
        return (await cursor.fetchone())[0]


async def get_referral_link_id(user_id):
    """Get the link_id for a bot owned by user_id (for bulk marking)."""
    async with _get_db() as conn:
        cursor = await conn.execute(
            "SELECT l.id FROM links l JOIN bots b ON b.id = l.bot_id WHERE b.user_id = ? LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


# ============================================
# BULK MARK PROCESSED
# ============================================

async def bulk_mark_processed(link_id, message_hashes):
    """Mark multiple messages as processed at once."""
    async with _get_db() as conn:
        await conn.executemany(
            "INSERT OR IGNORE INTO processed_messages (link_id, message_hash) VALUES (?, ?)",
            [(link_id, h) for h in message_hashes],
        )
        await conn.commit()
