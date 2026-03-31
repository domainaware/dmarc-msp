"""Tests for the client create CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dmarc_msp.cli import app

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


def test_create_client_fails_if_opensearch_unreachable(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client.OpenSearchService") as mock_os_cls:
        mock_os = MagicMock()
        mock_os.health.side_effect = ConnectionError("Connection refused")
        mock_os_cls.return_value = mock_os

        result = runner.invoke(
            app, ["client", "create", "Acme Corp", "--config", config]
        )

    assert result.exit_code == 1
    assert "Cannot connect to OpenSearch" in result.output


def test_create_client_no_db_entry_if_opensearch_unreachable(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client.OpenSearchService") as mock_os_cls:
        mock_os = MagicMock()
        mock_os.health.side_effect = ConnectionError("Connection refused")
        mock_os_cls.return_value = mock_os

        runner.invoke(app, ["client", "create", "Acme Corp", "--config", config])

    # Verify no client was written to the DB
    from dmarc_msp.db import init_db

    session_factory = init_db(f"sqlite:///{tmp_path / 'test.db'}")
    session = session_factory()
    from dmarc_msp.services.clients import ClientService

    svc = ClientService(session)
    clients = svc.list()
    assert len(clients) == 0
    session.close()


def test_create_client_success(tmp_path):
    config = _config_file(tmp_path)

    with (
        patch("dmarc_msp.cli.client.OpenSearchService") as mock_os_cls,
        patch("dmarc_msp.cli.client.DashboardService") as mock_dash_cls,
    ):
        mock_os = MagicMock()
        mock_os_cls.return_value = mock_os
        mock_dash = MagicMock()
        mock_dash_cls.return_value = mock_dash

        result = runner.invoke(
            app, ["client", "create", "Acme Corp", "--config", config]
        )

    assert result.exit_code == 0
    assert "Created client" in result.output
    assert "acme corp" in result.output
    assert "tenant + role provisioned" in result.output
    assert "Dashboards" in result.output
    mock_os.health.assert_called_once()
    mock_os.provision_tenant.assert_called_once_with("client_acme_corp", "acme_corp")
    mock_dash.import_for_client.assert_called_once()


def test_create_client_provisioning_failure_is_hard_error(tmp_path):
    config = _config_file(tmp_path)

    with patch("dmarc_msp.cli.client.OpenSearchService") as mock_os_cls:
        mock_os = MagicMock()
        mock_os.health.return_value = {"status": "green"}
        mock_os.provision_tenant.side_effect = RuntimeError("tenant creation failed")
        mock_os_cls.return_value = mock_os

        result = runner.invoke(
            app, ["client", "create", "Acme Corp", "--config", config]
        )

    assert result.exit_code == 1
    assert "tenant creation failed" in result.output


def test_create_client_with_retention(tmp_path):
    config = _config_file(tmp_path)

    with (
        patch("dmarc_msp.cli.client.OpenSearchService") as mock_os_cls,
        patch("dmarc_msp.cli.client.DashboardService") as mock_dash_cls,
        patch("dmarc_msp.cli.client.RetentionService") as mock_ret_cls,
    ):
        mock_os = MagicMock()
        mock_os_cls.return_value = mock_os
        mock_dash_cls.return_value = MagicMock()
        mock_ret = MagicMock()
        mock_ret_cls.return_value = mock_ret

        result = runner.invoke(
            app,
            [
                "client",
                "create",
                "Acme Corp",
                "--retention-days",
                "365",
                "--config",
                config,
            ],
        )

    assert result.exit_code == 0
    mock_ret.create_client_policy.assert_called_once_with("acme_corp", 365)
