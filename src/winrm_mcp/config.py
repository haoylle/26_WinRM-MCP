from __future__ import annotations

import os
from functools import lru_cache

import yaml
from pydantic import BaseModel, Field, ValidationError


class GuestConfig(BaseModel):
    host: str
    username: str
    password: str | None = None
    transport: str = "ntlm"
    scheme: str = "http"
    port: int = 5985
    server_cert_validation: str = "ignore"
    operation_timeout_sec: int = 60
    read_timeout_sec: int = 90
    allow_unencrypted: bool = True
    path: str = "/wsman"


class LimitsConfig(BaseModel):
    max_stdout_chars: int = 200000
    copy_chunk_bytes: int = 8192
    command_timeout_sec: int = 300


class SecurityConfig(BaseModel):
    allowed_command_prefixes: list[str] = Field(default_factory=list)
    denied_patterns: list[str] = Field(default_factory=list)


class KdnetConfig(BaseModel):
    host_ip: str
    port: int = 50000
    key: str
    state_file: str = r"C:\mcp-state\kd-session.json"
    bcdedit_path: str = "bcdedit.exe"


class Config(BaseModel):
    guest: GuestConfig
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    kdnet: KdnetConfig | None = None


@lru_cache(maxsize=1)
def load_config() -> Config:
    cfg_path = os.environ.get("WINRM_MCP_CONFIG") or "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid config file {cfg_path}: {e}") from e
    if not cfg.guest.password:
        cfg.guest.password = os.environ.get("WINRM_PASSWORD")
    if not cfg.guest.password:
        raise RuntimeError("Missing guest password. Set guest.password in config.yaml or WINRM_PASSWORD env var.")
    return cfg


def clear_config_cache() -> None:
    load_config.cache_clear()
