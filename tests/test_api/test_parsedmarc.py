"""Tests for the parsedmarc reload API endpoint."""

from __future__ import annotations

from unittest.mock import patch

# --- POST /api/v1/parsedmarc/reload ---


def test_reload_parsedmarc_success(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with patch("dmarc_msp.api.routers.parsedmarc.DockerSignaler") as mock_cls:
        mock_cls.return_value.send_sighup.return_value = True
        resp = client.post("/api/v1/parsedmarc/reload")
    assert resp.status_code == 200
    assert "reloaded" in resp.json()["message"]


def test_reload_parsedmarc_failure(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with patch("dmarc_msp.api.routers.parsedmarc.DockerSignaler") as mock_cls:
        mock_cls.return_value.send_sighup.return_value = False
        resp = client.post("/api/v1/parsedmarc/reload")
    assert resp.status_code == 500
    assert "Failed" in resp.json()["detail"]
