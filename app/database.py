import aiosqlite
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any
from app.config import settings

def hash_password(password: str) -> str:
    # SHA-256 with salt for lightweight dependency-free secure hashing
    salt = settings.SECRET_KEY[:16]
    return hashlib.sha256((salt + password).encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password

@asynccontextmanager
async def get_db_connection():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        yield db

async def has_any_users() -> bool:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cursor.fetchone()
        return (row["cnt"] if row else 0) > 0

async def init_db():
    async with get_db_connection() as db:

        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Sources table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                source_type TEXT DEFAULT 'url',
                enabled INTEGER DEFAULT 1,
                last_scraped_at TIMESTAMP,
                last_status TEXT DEFAULT 'never',
                configs_found INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Configs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                protocol TEXT NOT NULL,
                server TEXT NOT NULL,
                port INTEGER NOT NULL,
                name TEXT,
                raw_link TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                ping_ms INTEGER DEFAULT -1,
                download_mbps REAL DEFAULT 0.0,
                upload_mbps REAL DEFAULT 0.0,
                traffic_down_bytes INTEGER DEFAULT 0,
                traffic_up_bytes INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_checked_at TIMESTAMP,
                last_error TEXT,
                source_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_configs_active_ping ON configs(is_active, ping_ms);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_configs_protocol ON configs(protocol);")

        # Migration: Ensure traffic columns exist in configs for existing DBs
        cursor = await db.execute("PRAGMA table_info(configs)")
        cfg_cols = [row["name"] for row in await cursor.fetchall()]
        if "traffic_down_bytes" not in cfg_cols:
            await db.execute("ALTER TABLE configs ADD COLUMN traffic_down_bytes INTEGER DEFAULT 0;")
        if "traffic_up_bytes" not in cfg_cols:
            await db.execute("ALTER TABLE configs ADD COLUMN traffic_up_bytes INTEGER DEFAULT 0;")

        # System settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT
            )
        """)

        # Metrics & audit log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS metrics_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                total_active INTEGER DEFAULT 0,
                total_dead INTEGER DEFAULT 0,
                added_count INTEGER DEFAULT 0,
                purged_count INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0.0,
                traffic_down_bytes INTEGER DEFAULT 0,
                traffic_up_bytes INTEGER DEFAULT 0,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Ensure traffic columns exist in metrics_log for existing DBs
        cursor = await db.execute("PRAGMA table_info(metrics_log)")
        log_cols = [row["name"] for row in await cursor.fetchall()]
        if "traffic_down_bytes" not in log_cols:
            await db.execute("ALTER TABLE metrics_log ADD COLUMN traffic_down_bytes INTEGER DEFAULT 0;")
        if "traffic_up_bytes" not in log_cols:
            await db.execute("ALTER TABLE metrics_log ADD COLUMN traffic_up_bytes INTEGER DEFAULT 0;")

        # Seed initial admin user ONLY if explicitly provided via env settings
        if settings.DEFAULT_USERNAME and settings.DEFAULT_PASSWORD:
            cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
            row = await cursor.fetchone()
            if (row["cnt"] if row else 0) == 0:
                pw_hash = hash_password(settings.DEFAULT_PASSWORD)
                await db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (settings.DEFAULT_USERNAME, pw_hash)
                )

        # Seed initial settings
        default_settings = [
            ("parse_interval_hours", str(settings.DEFAULT_PARSE_INTERVAL_HOURS), "Интервал сбора ссылок (в часах)"),
            ("check_interval_minutes", str(settings.DEFAULT_CHECK_INTERVAL_MINUTES), "Интервал проверки живых конфигов (в минутах)"),
            ("speedtest_enabled", "1" if settings.DEFAULT_SPEEDTEST_ENABLED else "0", "Включение замера скорости 50МБ (1 - вкл, 0 - выкл)"),
            ("max_retries_before_purge", "3", "Количество неудачных проверок подряд перед удалением"),
            ("last_parse_time", "", "Время последнего парсинга"),
            ("last_check_time", "", "Время последней проверки"),
            ("total_traffic_down_bytes", "0", "Всего потрачено трафика на прием (байт)"),
            ("total_traffic_up_bytes", "0", "Всего потрачено трафика на передачу (байт)"),
        ]
        for key, val, desc in default_settings:
            await db.execute(
                "INSERT OR IGNORE INTO system_settings (key, value, description) VALUES (?, ?, ?)",
                (key, val, desc)
            )

        # Seed default sources (NiREvil/vless repo sources)
        initial_sources = [
            ("NiREvil SSTime (VLESS/SS/Trojan)", "https://raw.githubusercontent.com/NiREvil/vless/main/sub/SSTime", "sub"),
        ]

        for name, url, s_type in initial_sources:
            await db.execute(
                "INSERT OR IGNORE INTO sources (name, url, source_type) VALUES (?, ?, ?)",
                (name, url, s_type)
            )

        await db.commit()

async def get_setting(key: str, default: str = "") -> str:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

async def set_setting(key: str, value: str, description: Optional[str] = None):
    async with get_db_connection() as db:
        if description:
            await db.execute(
                "INSERT INTO system_settings (key, value, description) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, description=excluded.description",
                (key, value, description)
            )
        else:
            await db.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value)
            )
        await db.commit()

