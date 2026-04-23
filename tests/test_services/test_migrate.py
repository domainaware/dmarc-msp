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
    passing one silently failed every IP and produced zero enrichment."""
    assert "parallel" not in _PARSEDMARC_LOOKUP_SCRIPT
    assert "offline=True" in _PARSEDMARC_LOOKUP_SCRIPT


def test_lookup_script_does_not_swallow_exceptions():
    """A per-IP try/except masked programming errors (bad kwargs, missing
    imports) as {ip: None}, which showed up as silent zero-updates. The
    script must let exceptions propagate out of the subprocess so the
    surrounding CalledProcessError handler surfaces them."""
    assert "except" not in _PARSEDMARC_LOOKUP_SCRIPT


def test_lookup_raises_when_subprocess_fails():
    """A broken lookup helper exits non-zero. _lookup_enrichment must
    re-raise with the subprocess stderr attached, not silently drop IPs."""
    svc = _make_service()
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["docker", "exec"],
        output="",
        stderr="TypeError: got an unexpected keyword argument 'parallel'",
    )
    with patch("dmarc_msp.services.migrate.subprocess.run", side_effect=err):
        with pytest.raises(RuntimeError, match="parallel"):
            svc._lookup_enrichment(["1.2.3.4", "5.6.7.8"])


def test_lookup_returns_dict_per_ip():
    """Successful run returns {ip: info_dict} for every input IP."""
    svc = _make_service()
    stdout = json.dumps(
        {
            "1.2.3.4": {"country": "US", "name": "Google", "type": "mailer"},
            "10.0.0.1": {"country": None, "name": None, "type": None},
        }
    )
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=""
    )
    with patch("dmarc_msp.services.migrate.subprocess.run", return_value=completed):
        result = svc._lookup_enrichment(["1.2.3.4", "10.0.0.1"])
    assert result["1.2.3.4"]["country"] == "US"
    assert result["10.0.0.1"]["country"] is None
