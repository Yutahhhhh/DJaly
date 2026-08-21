"""Configuration management for Rekordbox MCP Server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="REKORDBOX_",
        case_sensitive=False,
        extra="ignore",
    )

    # Database Configuration
    db_path: str | None = Field(
        default=None,
        description="Path to rekordbox master.db (auto-detected if not set)",
    )
    db_key: str | None = Field(
        default=None,
        description="Database encryption key (auto-extracted if not set)",
    )
    db_dir: str | None = Field(
        default=None,
        description="Rekordbox database directory (for ANLZ files, auto-detected if not set)",
    )

    # Operation Mode
    mode: Literal["readonly", "xml", "masterdb"] = Field(
        default="readonly",
        description="Operation mode: readonly (read-only), xml (XML export), masterdb (direct DB writes)",
    )

    xml_path: str = Field(
        default="~/rekordbox-collection.xml",
        description="Output path for Rekordbox collection XML in xml mode",
    )

    # Backup Configuration
    backup_dir: str = Field(
        default="~/rekordbox-backups",
        description="Directory for backup storage",
    )
    backup_max_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Maximum age of backups in days",
    )
    backup_max_generations: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of backup generations to keep",
    )
    backup_max_size_gb: float = Field(
        default=2.0,
        ge=0.1,
        le=100.0,
        description="Maximum total backup size in GB",
    )
    backup_compression_level: int = Field(
        default=3,
        ge=1,
        le=22,
        description="zstd compression level (1-22)",
    )

    # Cue Profile Configuration
    cue_profile: str = Field(
        default="default",
        description="Cue profile name or path to cue-system.csv",
    )
    cue_memory_offset_bars: int = Field(
        default=16,
        ge=0,
        le=64,
        description="Memory cue offset in bars from hot cue position",
    )
    cue_loop_length_bars: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Default loop length in bars",
    )

    # Analysis Configuration
    phrase_min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for phrase detection",
    )
    vocal_min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for vocal detection",
    )

    # Web API Configuration
    webapi_host: str = Field(
        default="127.0.0.1",
        description="Web API host",
    )
    webapi_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Web API port",
    )
    webapi_enabled: bool = Field(
        default=False,
        description="Enable Web API server",
    )

    # Web UI Configuration
    webui_host: str = Field(
        default="127.0.0.1",
        description="Web UI host",
    )
    webui_port: int = Field(
        default=3000,
        ge=1,
        le=65535,
        description="Web UI port",
    )
    webui_enabled: bool = Field(
        default=False,
        description="Enable Web UI server",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_file: str | None = Field(
        default=None,
        description="Log file path (None for stdout only)",
    )

    @field_validator("backup_dir", mode="before")
    @classmethod
    def expand_backup_dir(cls, v: str) -> str:
        return str(Path(v).expanduser())

    @field_validator("db_path", "db_dir", "xml_path", mode="before")
    @classmethod
    def expand_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return str(Path(v).expanduser())

    @property
    def backup_dir_path(self) -> Path:
        return Path(self.backup_dir).expanduser()

    @property
    def db_path_obj(self) -> Path | None:
        if self.db_path:
            return Path(self.db_path).expanduser()
        return None

    @property
    def db_dir_obj(self) -> Path | None:
        if self.db_dir:
            return Path(self.db_dir).expanduser()
        return None

    @property
    def xml_path_obj(self) -> Path:
        return Path(self.xml_path).expanduser()


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
