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
            json.dumps({"type": "index-pattern", "id": "dmarc-aggregate"}),
            json.dumps({
                "type": "visualization", "attributes": {"title": "dmarc_overview"}}),
        ]
    template.write_text("\n".join(lines) + "\n")
    dash_config = DashboardsConfig(
        url="https://localhost:5601",
        saved_objects_template=str(template),
    )
    os_config = OpenSearchConfig(password="test_password")
    return DashboardService(dash_config, os_config)


def test_rewrite_template_replaces_prefix(tmp_path):
    svc = _make_template(tmp_path)
    rewritten = svc._rewrite_template("acme_corp")
    assert '"acme_corp-aggregate"' in rewritten
    assert '"acme_corp_overview"' in rewritten
    assert '"dmarc-' not in rewritten
    assert '"dmarc_' not in rewritten


def test_rewrite_template_skips_blank_lines(tmp_path):
    lines = [
        json.dumps({"type": "index-pattern", "id": "dmarc-agg"}),
        "",
        "   ",
        json.dumps({"type": "vis", "id": "dmarc-vis"}),
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
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "securitytenant" in call_kwargs.kwargs.get(
            "headers",call_kwargs[1].get("headers", {}))


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
