"""
Configuration management using Pydantic Settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "sandbox_rpg"
    postgres_user: str = "rpg_user"
    postgres_password: str = "dev_password"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_log_level: str = "INFO"
    secret_key: str = "change_me_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # CORS
    enable_cors: bool = True
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # LLM - Cloud
    llm_cloud_provider: str = "minimax"
    llm_cloud_api_key: str = ""
    llm_cloud_base_url: str = "https://api.minimax.chat/v1"
    llm_cloud_model: str = "MiniMax-M3"
    llm_cloud_temperature: float = 1.0
    llm_cloud_top_p: float = 0.95
    llm_cloud_max_tokens: int = 4000
    llm_cloud_timeout_seconds: int = 60

    # LLM - Local
    llm_local_enabled: bool = True
    llm_local_base_url: str = "http://127.0.0.1:1234/v1"
    llm_local_model: str = "qwen2.5-14b-instruct"
    llm_local_temperature: float = 0.9
    llm_local_top_p: float = 0.9
    llm_local_max_tokens: int = 2000
    llm_local_timeout_seconds: int = 120

    # Game Settings
    round_duration_minutes: int = 15
    daily_etl_hour: int = 0
    daily_etl_minute: int = 0
    world_parameter_fluctuation_limit: float = 0.15
    max_tags_per_character: int = 8
    max_shift_per_semantic_level: int = 1

    # LanceDB
    lancedb_uri: str = "./lancedb_data"
    lancedb_table_name: str = "world_lore"
    embedding_model: str = "nomic-embed-text-v1.5"
    embedding_dim: int = 768
    embedding_base_url: str = "http://127.0.0.1:1234/v1"

    # Development
    debug: bool = False
    enable_api_docs: bool = True

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


settings = Settings()
