"""Tests for the config-validate CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dmarc_msp.cli import app

runner = CliRunner()


def _make_settings(tmp_path):
    """Create a minimal config file and return its path."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "msp:\n"
        "  domain: dmarc.test.example.com\n"
        "  rua_email: reports@dmarc.test.example.com\n"
        "opensearch:\n"
        "  password: test_password\n"
        "dns:\n"
        "  provider: cloudflare\n"
        "  zone: test.example.com\n"
        "dashboards:\n"
        "  url: http://localhost:5601\n"
    )
    return str(config_file)


def test_config_validate_success(tmp_path):
    config_path = _make_settings(tmp_path)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["config-validate", "--config", config_path])

    assert result.exit_code == 0
    assert "msp_domain: dmarc.test.example.com" in result.output
    assert "cloudflare" in result.output
    assert "test_password" not in result.output


def test_config_validate_dashboards_reachable(tmp_path):
    config_path = _make_settings(tmp_path)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["config-validate", "--config", config_path])

    assert result.exit_code == 0
    assert "dashboards_url" in result.output
    assert "localhost:5601" in result.output


def test_config_validate_dashboards_unreachable(tmp_path):
    config_path = _make_settings(tmp_path)

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = ConnectionError("Name does not resolve")
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["config-validate", "--config", config_path])

    # Command still succeeds (dashboards check is non-fatal)
    assert result.exit_code == 0
    assert "Name does not resolve" in result.output


def test_config_validate_invalid_config():
    result = runner.invoke(
        app, ["config-validate", "--config", "/nonexistent/config.yaml"]
    )
    # Should still work with defaults since load_settings handles missing files
    assert result.exit_code == 0


def test_config_validate_missing_password(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "msp:\n  domain: test.example.com\nopensearch:\n  password: ''\n"
    )

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("no password")
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["config-validate", "--config", str(config_file)])

    assert result.exit_code == 0
    assert "not configured" in result.output
