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
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed initial admin user if not exists
        cursor = await db.execute("SELECT id FROM users WHERE username = ?", (settings.DEFAULT_USERNAME,))
        user = await cursor.fetchone()
        if not user:
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

