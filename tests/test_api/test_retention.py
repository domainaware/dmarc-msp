"""Tests for the retention policy API endpoints."""

from __future__ import annotations

# --- POST /api/v1/retention/ensure-default ---


def test_ensure_default_policy(api_client_with_mocks):
    client, _, _, mock_ret = api_client_with_mocks
    resp = client.post("/api/v1/retention/ensure-default")
    assert resp.status_code == 200
    assert "ensured" in resp.json()["message"]
    mock_ret.ensure_default_policy.assert_called_once()
