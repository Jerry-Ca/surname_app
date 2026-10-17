"""配置：所有可配置项只从环境变量与仓库根目录的 .env 读取。

密钥永不写入代码（AGENTS.md 铁律 4）。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 从 backend/ 启动时读取仓库根目录的 .env
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    api_port: int = 8000
    api_version: str = "0.1.0"

    # 本地调试可用 SQLite；正式环境必须是 PostgreSQL（见 docs/architecture.md）
    database_url: str = "sqlite:///./dev.db"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    embedding_provider: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 1024

    admin_token: str = ""
    cors_origins: str = ""

    @property
    def model_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_api_key.strip() and self.embedding_model.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
