"""Configuration: secrets (.env) and the user-editable config files.

- ``Settings``      -> secrets + connection strings from environment / .env
- ``ICPConfig``     -> config/icp.yaml (WHO to target)
- ``ValuePropConfig`` -> config/value_prop.yaml (WHAT you offer)
- ``AppSettings``   -> settings.toml (non-secret knobs; optional)

All loaders validate and raise a clear error on bad input.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Secrets (.env / environment) ───────────────────────────────────────────


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str | None = None
    lusha_api_key: str | None = None
    prospeo_api_key: str | None = None
    instantly_api_key: str | None = None
    instantly_campaign_id: str | None = None
    apify_token: str | None = None
    unipile_api_key: str | None = None
    unipile_dsn: str | None = None
    database_url: str | None = None

    # Supabase (hosted auth + Postgres). The anon key is safe to expose to the
    # browser; the JWT secret is private and used server-side to verify logins.
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_jwt_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── ICP config (config/icp.yaml) ───────────────────────────────────────────


class CompanySize(BaseModel):
    min: int | None = None
    max: int | None = None


class ICPConfig(BaseModel):
    name: str
    version: int = 1
    industries: list[str] = Field(default_factory=list)
    company_size: CompanySize = Field(default_factory=CompanySize)
    seniorities: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    score_threshold: int = 60

    @field_validator("score_threshold")
    @classmethod
    def _threshold_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("score_threshold must be between 0 and 100")
        return v


# ── Value proposition (config/value_prop.yaml) ─────────────────────────────


class ValuePropConfig(BaseModel):
    offer: str
    proof_points: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    cta: str


# ── Non-secret app settings (settings.toml) ────────────────────────────────


class ModelSettings(BaseModel):
    brain: str = "claude-opus-4-8"
    prefilter: str = "claude-haiku-4-5"


class LimitSettings(BaseModel):
    daily_spend_cap_usd: float = 5.0
    max_prospects_per_run: int = 100
    daily_send_cap: int = 25


class ScoringSettings(BaseModel):
    use_prefilter: bool = False


class PathSettings(BaseModel):
    icp: str = "config/icp.yaml"
    value_prop: str = "config/value_prop.yaml"
    message_guidelines: str = "config/message_guidelines.md"


class LushaSettings(BaseModel):
    max_prospects: int = 100
    signals_days_back: int = 90
    signal_types: list[str] = Field(default_factory=lambda: ["promotion", "companyChange"])


class AppSettings(BaseModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    lusha: LushaSettings = Field(default_factory=LushaSettings)


# ── Loaders ────────────────────────────────────────────────────────────────


def _load_yaml_mapping(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {p} must be a YAML mapping (key: value pairs)")
    return data


def load_icp(path: str | Path = "config/icp.yaml") -> ICPConfig:
    return ICPConfig.model_validate(_load_yaml_mapping(path))


def load_value_prop(path: str | Path = "config/value_prop.yaml") -> ValuePropConfig:
    return ValuePropConfig.model_validate(_load_yaml_mapping(path))


def load_message_guidelines(path: str | Path = "config/message_guidelines.md") -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Message guidelines not found: {p}")
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Message guidelines file {p} is empty")
    return text


def load_app_settings(path: str | Path = "settings.toml") -> AppSettings:
    p = Path(path)
    if not p.exists():
        return AppSettings()  # defaults
    with p.open("rb") as f:
        data = tomllib.load(f)
    return AppSettings.model_validate(data)
