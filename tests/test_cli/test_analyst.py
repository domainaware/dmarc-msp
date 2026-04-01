"""Tests for analyst CLI commands."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dmarc_msp.cli import app
from dmarc_msp.services.opensearch import UserNotFoundError

runner = CliRunner()


def _config_file(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "msp:\n"
        "  domain: dmarc.test.example.com\n"
        "opensearch:\n"
        "  password: test_password\n"
        "  verify_certs: false\n"
        "dashboards:\n"
        "  url: http://opensearch-dashboards:5601\n"
        "  saved_objects_template: /dev/null\n"
        f"database:\n"
        f"  url: sqlite:///{tmp_path / 'test.db'}\n"
    )
    return str(config)


def test_analyst_create(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "create", "testanalyst", "--config", config]
        )

    assert result.exit_code == 0
    assert "testanalyst" in result.output
    assert "Password" in result.output
    mock_os.ensure_analyst_role.assert_called_once()
    mock_os.create_internal_user.assert_called_once()
    # Should map to analyst, kibana_user, and kibana_read_only roles
    assert mock_os.add_user_to_role_mapping.call_count == 3


def test_analyst_create_opensearch_unreachable(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.health.side_effect = ConnectionError("refused")
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "create", "testanalyst", "--config", config]
        )

    assert result.exit_code == 1
    assert "Cannot connect" in result.output


def test_analyst_reset_password(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "reset-password", "testanalyst", "--config", config]
        )

    assert result.exit_code == 0
    assert "Password" in result.output
    mock_os.update_internal_user_password.assert_called_once()


def test_analyst_disable(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.disable_user.return_value = ["analyst", "kibana_read_only"]
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "disable", "testanalyst", "--config", config]
        )

    assert result.exit_code == 0
    assert "Disabled" in result.output
    assert "Password changed" in result.output
    assert "reset-password" in result.output


def test_analyst_delete(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.get_internal_user.return_value = {
            "attributes": {
                "roles": json.dumps(["analyst", "kibana_read_only"]),
            }
        }
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "delete", "testanalyst", "--config", config]
        )

    assert result.exit_code == 0
    assert "Deleted" in result.output
    mock_os.delete_internal_user.assert_called_once_with("testanalyst")


def test_analyst_list(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.list_internal_users.return_value = {
            "admin": {"attributes": {}},
            "analyst1": {
                "attributes": {"role_type": "analyst", "disabled": "false"},
                "description": "Analyst account",
            },
            "client_user1": {
                "attributes": {"role_type": "client"},
            },
        }
        mock_get.return_value = mock_os

        result = runner.invoke(app, ["analyst", "list", "--config", config])

    assert result.exit_code == 0
    assert "analyst1" in result.output
    assert "admin" not in result.output
    assert "client_user1" not in result.output
    assert "1 analyst account" in result.output


def test_analyst_reset_password_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.update_internal_user_password.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "reset-password", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "not found" in result.output


def test_analyst_disable_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.disable_user.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "disable", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "not found" in result.output


def test_analyst_delete_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.analyst.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.get_internal_user.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["analyst", "delete", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "User 'nonexistent' not found" in result.output
