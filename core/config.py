from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    notion_api_base: str = "https://api.notion.com/v1"
    notion_version: str = os.getenv("NOTION_VERSION", "2022-06-28")
    notion_token: str = os.getenv("NOTION_API_KEY", "")
    timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT", "30"))

    def validate(self) -> None:
        if not self.notion_token:
            raise RuntimeError("NOTION_API_KEY is not set. Create a .env or export the variable.")

settings = Settings()
