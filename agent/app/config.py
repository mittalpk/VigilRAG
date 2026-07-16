import os
import logging
from typing import List
from pydantic import SecretStr, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore",
        case_sensitive=False
    )

    # LLM (Explicitly mapped to env)
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("GEMINI_API_KEY", "gemini-api-key")
    )

    # Internal Security (Explicitly mapped to Key Vault env var)
    internal_api_key: SecretStr = Field(
        default=SecretStr("change-me-in-production"),
        validation_alias=AliasChoices("INTERNAL_API_KEY", "internal-api-key", "X-Internal-API-Key")
    )

    # CORS
    allowed_origins: List[str] = []

    def __init__(self, **data):
        super().__init__(**data)
        logger.info(f"✓ Agent Settings initialized: INTERNAL_API_KEY length = {len(self.internal_api_key.get_secret_value())}")
        logger.info(f"  BACKEND_URL env var: {os.getenv('BACKEND_URL', 'NOT SET')}")


settings = Settings()

