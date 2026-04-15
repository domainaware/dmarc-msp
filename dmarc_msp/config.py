"""Configuration management using Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MSPConfig(BaseModel):
    domain: str = "dmarc.msp-example.com"
    rua_email: str = "reports@dmarc.msp-example.com"


class DNSProviderConfig(BaseModel):
    provider: str = "cloudflare"
    zone: str = "msp.example.com"
    cloudflare: dict[str, Any] = Field(default_factory=dict)
    gcp: dict[str, Any] = Field(default_factory=dict)
    route53: dict[str, Any] = Field(default_factory=dict)
    azure: dict[str, Any] = Field(default_factory=dict)


class OpenSearchConfig(BaseModel):
    hosts: str = "https://opensearch:9200"
    username: str = "admin"
    password: str = ""
    ssl: bool = True
    verify_certs: bool = True

    @property
    def resolved_password(self) -> str:
        if self.password:
            return self.password
        secret_path = Path("/run/secrets/opensearch_admin_password")
        if secret_path.exists():
            return secret_path.read_text().strip()
        raise ValueError("OpenSearch password not configured")


class DashboardsConfig(BaseModel):
    url: str = "http://opensearch-dashboards:5601"
    saved_objects_template: str = "/etc/dmarc-msp/opensearch_dashboards.ndjson"
    dark_mode: bool = True
    import_failure_reports: bool = False


class ParsedmarcConfig(BaseModel):
    config_file: str = "/etc/parsedmarc.ini"
    domain_map_file: str = "/etc/parsedmarc_domain_map.yaml"
    container: str = "parsedmarc"


class RetentionConfig(BaseModel):
    index_default_days: int = 180
    email_days: int = 30


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///dmarc_msp.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DMARCMSP_",
        env_nested_delimiter="__",
    )

    msp: MSPConfig = Field(default_factory=MSPConfig)
    dns: DNSProviderConfig = Field(default_factory=DNSProviderConfig)
    opensearch: OpenSearchConfig = Field(default_factory=OpenSearchConfig)
    dashboards: DashboardsConfig = Field(default_factory=DashboardsConfig)
    parsedmarc: ParsedmarcConfig = Field(default_factory=ParsedmarcConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    @model_validator(mode="before")
    @classmethod
    def load_config_file(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        return data


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from a YAML config file, with env var overrides."""
    if config_path is None:
        candidates = [
            Path("/etc/dmarc-msp/config.yml"),
            Path("dmarc-msp.yml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    file_data: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                file_data = yaml.safe_load(f) or {}

    # Resolve OpenSearch password from env if available
    import os

    os_password = os.environ.get("OPENSEARCH_ADMIN_PASSWORD", "")
    if os_password and "opensearch" not in file_data:
        file_data["opensearch"] = {}
    if os_password:
        file_data.setdefault("opensearch", {})["password"] = os_password

    # Resolve Cloudflare token from env
    cf_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if cf_token:
        file_data.setdefault("dns", {}).setdefault("cloudflare", {})["api_token"] = (
            cf_token
        )

    return Settings(**file_data)
