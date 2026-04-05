"""Tests for dashboard service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dmarc_msp.config import DashboardsConfig, OpenSearchConfig
from dmarc_msp.services.dashboards import DashboardService


def _make_template(tmp_path, lines=None):
    """Create a template NDJSON file and return a DashboardService."""
    template = tmp_path / "dashboards.ndjson"
    if lines is None:
        lines = [
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "dmarc_aggregate*"},
                }
            ),
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "dmarc_f*"},
                }
            ),
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "smtp_tls*"},
                }
            ),
        ]
    template.write_text("\n".join(lines) + "\n")
    dash_config = DashboardsConfig(
        url="http://localhost:5601",
        saved_objects_template=str(template),
    )
    os_config = OpenSearchConfig(password="test_password")
    return DashboardService(dash_config, os_config)


def test_rewrite_template_prepends_prefix(tmp_path):
    svc = _make_template(tmp_path)
    rewritten = svc._rewrite_template("acme_corp")
    assert '"acme_corp_dmarc_aggregate*"' in rewritten
    assert '"acme_corp_dmarc_f*"' in rewritten
    assert '"acme_corp_smtp_tls*"' in rewritten


def test_rewrite_template_does_not_double_prefix(tmp_path):
    svc = _make_template(tmp_path)
    rewritten = svc._rewrite_template("acme_corp")
    assert "acme_corp_acme_corp" not in rewritten


def test_rewrite_template_skips_blank_lines(tmp_path):
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "attributes": {"title": "dmarc_aggregate*"},
            }
        ),
        "",
        "   ",
        json.dumps({"type": "vis", "id": "some-vis"}),
    ]
    svc = _make_template(tmp_path, lines)
    rewritten = svc._rewrite_template("client1")
    # Should have exactly 2 lines (blanks skipped)
    assert len(rewritten.strip().split("\n")) == 2


def test_import_for_client_missing_template(tmp_path):
    dash_config = DashboardsConfig(
        url="https://localhost:5601",
        saved_objects_template=str(tmp_path / "nonexistent.ndjson"),
    )
    os_config = OpenSearchConfig(password="test_password")
    svc = DashboardService(dash_config, os_config)
    with pytest.raises(FileNotFoundError, match="not found"):
        svc.import_for_client("tenant", "prefix")


def test_import_for_client_success(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        assert mock_client.post.call_count == 3
        import_call = mock_client.post.call_args_list[0]
        assert "securitytenant" in import_call.kwargs.get(
            "headers", import_call[1].get("headers", {})
        )


def test_import_for_client_enables_dark_mode_by_default(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        # Three calls: saved objects import + default route + dark mode
        assert mock_client.post.call_count == 3
        dark_mode_call = mock_client.post.call_args_list[2]
        assert "settings" in dark_mode_call.args[0]
        assert dark_mode_call.kwargs["json"] == {
            "changes": {"theme:darkMode": True}
        }


def test_import_for_client_skips_dark_mode_when_disabled(tmp_path):
    template = tmp_path / "dashboards.ndjson"
    template.write_text(
        json.dumps(
            {"type": "index-pattern", "attributes": {"title": "dmarc_aggregate*"}}
        )
        + "\n"
    )
    dash_config = DashboardsConfig(
        url="http://localhost:5601",
        saved_objects_template=str(template),
        dark_mode=False,
    )
    os_config = OpenSearchConfig(password="test_password")
    svc = DashboardService(dash_config, os_config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        # Saved objects import + default route, no dark mode call
        assert mock_client.post.call_count == 2


def test_set_dark_mode(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.set_dark_mode("acme_tenant")
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["securitytenant"] == "acme_tenant"
        assert call_kwargs.kwargs["json"] == {
            "changes": {"theme:darkMode": True}
        }


def test_import_for_client_api_failure(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "errors": [{"type": "conflict"}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="import failed"):
            svc.import_for_client("acme_tenant", "acme_corp")
