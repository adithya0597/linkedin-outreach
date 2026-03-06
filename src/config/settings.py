from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    project_root: Path = Path(__file__).parent.parent.parent
    db_path: str = "data/outreach.db"
    config_dir: Path = Path(__file__).parent.parent.parent / "config"
    template_dir: Path = Path(__file__).parent.parent / "outreach" / "templates"

    # Notion
    notion_api_key: str = ""
    notion_database_id: str = "0c412604-a409-47ab-8c04-29f112c2c683"

    # Apify
    apify_api_key: str = ""

    # LLM (thin personalizer only)
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Chrome
    chrome_user_data_dir: str = "/Users/adithya/Library/Application Support/Google/Chrome"

    # Rate limits
    notion_requests_per_second: float = 3.0
    linkedin_searches_per_day: int = 100

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
