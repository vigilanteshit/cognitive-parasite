"""Validated local configuration. Credentials never enter model profiles or API output."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    provider: Literal["demo", "openai", "azure", "anthropic"]
    model: str
    label: str = ""
    context_window: int = Field(default=16384, ge=2048)
    max_output_tokens: int = Field(default=1024, ge=64)
    temperature_supported: bool = False
    structured_output: bool = True
    streaming: bool = True

    @model_validator(mode="after")
    def check_budget(self):
        if self.max_output_tokens + 1024 >= self.context_window:
            raise ValueError("Output reserve leaves insufficient context for input")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARASITE_", env_file=".env", extra="ignore")
    data_dir: Path = Path(".local/data")
    models_file: Path = Path("models.toml")
    memory_backend: Literal["sqlite", "neo4j"] = "sqlite"
    openai_api_key: SecretStr | None = None
    azure_api_key: SecretStr | None = None
    azure_endpoint: str = ""
    azure_api_version: str = "2024-10-21"
    anthropic_api_key: SecretStr | None = None
    embedding_provider: Literal["demo", "openai", "azure"] = "demo"
    embedding_model: str = "hash-v1"
    embedding_dimensions: int = Field(default=64, ge=1, le=65536)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr | None = None
    neo4j_database: str = "neo4j"
    request_timeout: float = Field(default=30, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_steps: int = Field(default=16, ge=2, le=50)
    max_run_tokens: int = Field(default=120000, ge=2048, le=1000000)
    max_run_seconds: float = Field(default=120, ge=5, le=1800)
    frontend_dir: Path = Path("frontend/dist")

    @model_validator(mode="after")
    def check_embeddings(self):
        if self.embedding_provider == "demo" and (
            self.embedding_model != "hash-v1" or self.embedding_dimensions != 64
        ):
            raise ValueError("Demo embeddings require hash-v1 with 64 dimensions")
        if self.embedding_provider != "demo" and self.embedding_model == "hash-v1":
            raise ValueError(
                "Choose an explicit embedding model and dimensions for live embeddings"
            )
        return self
