"""Tests for client user CLI commands."""

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


def _seed_client(tmp_path):
    """Create a client in the DB so the user command can look it up."""
    from dmarc_msp.db import init_db
    from dmarc_msp.services.clients import ClientService

    db_path = f"sqlite:///{tmp_path / 'test.db'}"
    session_factory = init_db(db_path)
    session = session_factory()
    svc = ClientService(session)
    svc.create("Acme Corp")
    session.close()


def test_client_user_create(tmp_path):
    config = _config_file(tmp_path)
    _seed_client(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_get.return_value = mock_os

        result = runner.invoke(
            app,
            ["client", "user", "create", "Acme Corp", "testuser", "--config", config],
        )

    assert result.exit_code == 0
    assert "testuser" in result.output
    assert "Password" in result.output
    mock_os.create_internal_user.assert_called_once()
    call_kwargs = mock_os.create_internal_user.call_args[1]
    assert call_kwargs["attributes"]["role_type"] == "client"
    assert call_kwargs["attributes"]["client_tenant"] == "client_acme_corp"


def test_client_user_create_unknown_client(tmp_path):
    config = _config_file(tmp_path)
    # Don't seed — client doesn't exist

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_get.return_value = MagicMock()

        result = runner.invoke(
            app,
            ["client", "user", "create", "Nonexistent", "testuser", "--config", config],
        )

    assert result.exit_code == 1
    assert "not found" in result.output


def test_client_user_list(tmp_path):
    config = _config_file(tmp_path)
    _seed_client(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.list_internal_users.return_value = {
            "user1": {
                "attributes": {
                    "role_type": "client",
                    "client_tenant": "client_acme_corp",
                    "disabled": "false",
                },
                "description": "Client user for acme corp",
            },
            "user2": {
                "attributes": {
                    "role_type": "client",
                    "client_tenant": "client_other",
                    "disabled": "false",
                },
                "description": "Client user for other",
            },
            "analyst1": {
                "attributes": {"role_type": "analyst"},
            },
        }
        mock_get.return_value = mock_os

        # List all client users
        result = runner.invoke(app, ["client", "user", "list", "--config", config])

    assert result.exit_code == 0
    assert "user1" in result.output
    assert "user2" in result.output
    assert "analyst1" not in result.output
    assert "2 client user account" in result.output


def test_client_user_list_filtered(tmp_path):
    config = _config_file(tmp_path)
    _seed_client(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.list_internal_users.return_value = {
            "user1": {
                "attributes": {
                    "role_type": "client",
                    "client_tenant": "client_acme_corp",
                    "disabled": "false",
                },
                "description": "Client user for acme corp",
            },
            "user2": {
                "attributes": {
                    "role_type": "client",
                    "client_tenant": "client_other",
                    "disabled": "false",
                },
                "description": "Client user for other",
            },
        }
        mock_get.return_value = mock_os

        result = runner.invoke(
            app,
            ["client", "user", "list", "--client", "Acme Corp", "--config", config],
        )

    assert result.exit_code == 0
    assert "user1" in result.output
    assert "user2" not in result.output
    assert "1 client user account" in result.output


def test_client_user_delete(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.get_internal_user.return_value = {
            "attributes": {
                "roles": json.dumps(["client_acme_corp", "kibana_read_only"]),
            }
        }
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["client", "user", "delete", "testuser", "--config", config]
        )

    assert result.exit_code == 0
    assert "Deleted" in result.output
    mock_os.delete_internal_user.assert_called_once_with("testuser")


def test_client_user_reset_password_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.update_internal_user_password.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["client", "user", "reset-password", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "User 'nonexistent' not found" in result.output


def test_client_user_disable_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.disable_user.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["client", "user", "disable", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "User 'nonexistent' not found" in result.output


def test_client_user_delete_not_found(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client_user.get_opensearch_service") as mock_get:
        mock_os = MagicMock()
        mock_os.get_internal_user.side_effect = UserNotFoundError(
            "User 'nonexistent' not found"
        )
        mock_get.return_value = mock_os

        result = runner.invoke(
            app, ["client", "user", "delete", "nonexistent", "--config", config]
        )

    assert result.exit_code == 1
    assert "User 'nonexistent' not found" in result.output
