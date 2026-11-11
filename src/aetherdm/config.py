"""Configuration loader from environment and .env files."""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env if present
load_dotenv()


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    # LLM
    llm_mode: Literal["qwen", "kobold"] = Field(default="qwen", alias="LLM_MODE")

    # Qwen
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")
    qwen_model: str = Field(default="qwen-turbo", alias="QWEN_MODEL")
    qwen_base_url: str | None = Field(default=None, alias="QWEN_BASE_URL")
    qwen_narrative_model: str = Field(default="qwen-plus", alias="QWEN_NARRATIVE_MODEL")

    # KoboldCPP
    kobold_base_url: str = Field(default="http://localhost:5001/v1", alias="KOBOLD_BASE_URL")
    kobold_model: str = Field(default="local-model", alias="KOBOLD_MODEL")
    kobold_narrative_model: str = Field(default="local-model", alias="KOBOLD_NARRATIVE_MODEL")

    # Database
    db_path: str = Field(default="./aetherdm.db", alias="DB_PATH")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def db_path_pathlib(self) -> Path:
        return Path(self.db_path)

    @property
    def resolution_model(self) -> str:
        """Model for structured resolution (cheap/fast, called every round)."""
        return self.qwen_model if self.llm_mode == "qwen" else self.kobold_model

    @property
    def narrative_model(self) -> str:
        """Model for verbose narration (expensive, called only for PC locations)."""
        return self.qwen_narrative_model if self.llm_mode == "qwen" else self.kobold_narrative_model


settings = Settings()
