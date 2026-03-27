"""Tests for configuration management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dmarc_msp.config import OpenSearchConfig, load_settings


class TestResolvedPassword:
    def test_returns_password_when_set(self):
        config = OpenSearchConfig(password="my_password")
        assert config.resolved_password == "my_password"

    def test_reads_docker_secret(self, tmp_path):
        secret_file = tmp_path / "opensearch_admin_password"
        secret_file.write_text("  secret_from_file  \n")
        config = OpenSearchConfig(password="")
        with patch(
            "dmarc_msp.config.Path",
        ) as mock_path:
            mock_path.return_value = secret_file
            assert config.resolved_password == "secret_from_file"

    def test_raises_when_no_password(self):
        config = OpenSearchConfig(password="")
        fake_path = Path("/nonexistent/path/that/does/not/exist")
        with patch("dmarc_msp.config.Path", return_value=fake_path):
            with pytest.raises(ValueError, match="not configured"):
                config.resolved_password


class TestLoadSettings:
    def test_load_from_yaml_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "msp:\n  domain: test.example.com\nopensearch:\n  password: yaml_password\n"
        )
        settings = load_settings(config_file)
        assert settings.msp.domain == "test.example.com"
        assert settings.opensearch.password == "yaml_password"

    def test_load_with_no_config_file(self):
        settings = load_settings(Path("/nonexistent/config.yaml"))
        # Should return defaults when file doesn't exist
        assert settings.msp.domain == "dmarc.msp-example.com"

    def test_env_override_opensearch_password(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("msp:\n  domain: test.example.com\n")
        with patch.dict(
            "os.environ",
            {"OPENSEARCH_ADMIN_PASSWORD": "env_password"},
            clear=False,
        ):
            settings = load_settings(config_file)
            assert settings.opensearch.password == "env_password"

    def test_env_override_opensearch_password_no_opensearch_section(self, tmp_path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        with patch.dict(
            "os.environ",
            {"OPENSEARCH_ADMIN_PASSWORD": "env_password"},
            clear=False,
        ):
            settings = load_settings(config_file)
            assert settings.opensearch.password == "env_password"

    def test_env_override_cloudflare_token(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("opensearch:\n  password: test\n")
        with patch.dict(
            "os.environ",
            {"CLOUDFLARE_API_TOKEN": "cf_token_123"},
            clear=False,
        ):
            settings = load_settings(config_file)
            assert settings.dns.cloudflare["api_token"] == "cf_token_123"

    def test_auto_discover_config_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "dmarc-msp.yml"
        config_file.write_text(
            "msp:\n  domain: discovered.example.com\nopensearch:\n  password: test\n"
        )
        settings = load_settings(None)
        assert settings.msp.domain == "discovered.example.com"
