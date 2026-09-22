import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    DB_PATH: str = str(DATA_DIR / "proxy_vault.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-vpn-aggregator-2026")
    
    # Default admin credentials
    DEFAULT_USERNAME: str = os.getenv("DEFAULT_USERNAME", "admin")
    DEFAULT_PASSWORD: str = os.getenv("DEFAULT_PASSWORD", "admin")
    
    # Scheduler defaults
    DEFAULT_PARSE_INTERVAL_HOURS: int = 12
    DEFAULT_CHECK_INTERVAL_MINUTES: int = 5
    
    # Testing & Speedtest
    DEFAULT_SPEEDTEST_ENABLED: bool = False
    SPEEDTEST_MAX_BYTES: int = 50 * 1024 * 1024  # 50 MB
    TEST_TIMEOUT_SECONDS: float = 4.0
    CONCURRENT_CHECKS_LIMIT: int = 40
    PING_TEST_URL: str = "http://cp.cloudflare.com/generate_204"
    SPEEDTEST_DOWN_URL: str = "https://speed.cloudflare.com/__down?bytes=52428800"
    SPEEDTEST_UP_URL: str = "https://speed.cloudflare.com/__up"
    
    # Paths
    SINGBOX_PATH: str = os.getenv("SINGBOX_PATH", "sing-box")

    class Config:
        env_file = ".env"

settings = Settings()
