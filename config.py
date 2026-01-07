import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/plan"
    )
    
    TGTRACK: str = os.getenv("TGTRACK")

    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "your_bot_username")

    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")
    CHANNEL_URL: str = os.getenv("CHANNEL_URL", "https://t.me/your_channel")

    ADMIN_IDS: List[int] = [
        int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",")
        if admin_id.strip()
    ]
    
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tashkent")
    
    BOT_API_SERVER: str = os.getenv("BOT_API_SERVER", "https://api.telegram.org")
    USE_LOCAL_SERVER: bool = os.getenv("USE_LOCAL_SERVER", "false").lower() == "true"


    
    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not set")
        if not self.CHANNEL_ID:
            raise ValueError("CHANNEL_ID is not set")
        if not self.ADMIN_IDS:
            raise ValueError("ADMIN_IDS is not set")

config = Config()