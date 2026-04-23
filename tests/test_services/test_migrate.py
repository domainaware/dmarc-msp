"""Tests for migration service."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from dmarc_msp.config import OpenSearchConfig
from dmarc_msp.services.migrate import _PARSEDMARC_LOOKUP_SCRIPT, MigrationService


def _make_service() -> MigrationService:
    os_config = OpenSearchConfig(password="test_password", verify_certs=False)
    with patch("dmarc_msp.services.migrate.OpenSearch"):
        svc = MigrationService(os_config)
    svc.client = MagicMock()
    return svc


def test_lookup_script_does_not_pass_unknown_kwargs():
    """parsedmarc.utils.get_ip_address_info has no ``parallel`` kwarg;
    passing one silently fails every IP and produces zero enrichment."""
    assert "parallel" not in _PARSEDMARC_LOOKUP_SCRIPT
    assert "offline=True" in _PARSEDMARC_LOOKUP_SCRIPT


def test_lookup_raises_when_all_ips_fail():
    """Surface errors loudly when every IP in a chunk returns None, so a
    broken lookup script can't silently produce zero updates."""
    svc = _make_service()
    stdout = json.dumps({"1.2.3.4": None, "5.6.7.8": None})
    stderr = "lookup-failed 1.2.3.4: TypeError: bad kwarg\n"
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr
    )
    with patch("dmarc_msp.services.migrate.subprocess.run", return_value=completed):
        with pytest.raises(RuntimeError, match="returned no results"):
            svc._lookup_enrichment(["1.2.3.4", "5.6.7.8"])


def test_lookup_returns_partial_results():
    """A mix of resolved and failed IPs must not raise — partial failures
    are normal (e.g., private IPs not in GeoIP)."""
    svc = _make_service()
    stdout = json.dumps(
        {
            "1.2.3.4": {"country": "US", "name": "Google", "type": "mailer"},
            "10.0.0.1": None,
        }
    )
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=""
    )
    with patch("dmarc_msp.services.migrate.subprocess.run", return_value=completed):
        result = svc._lookup_enrichment(["1.2.3.4", "10.0.0.1"])
    assert result["1.2.3.4"]["country"] == "US"
    assert result["10.0.0.1"] is None
