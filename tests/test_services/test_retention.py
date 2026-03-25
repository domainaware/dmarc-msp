"""Tests for retention service."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from dmarc_msp.config import OpenSearchConfig, RetentionConfig
from dmarc_msp.services.retention import RetentionService


def _make_service(default_days=180, email_days=30):
    os_config = OpenSearchConfig(password="test_password", verify_certs=False)
    ret_config = RetentionConfig(index_default_days=default_days, email_days=email_days)
    with patch("dmarc_msp.services.retention.OpenSearch"):
        svc = RetentionService(os_config, ret_config)
    svc.client = MagicMock()
    return svc


def test_ensure_default_policy():
    svc = _make_service(default_days=180)
    svc.ensure_default_policy()
    call = svc.client.transport.perform_request.call_args
    assert call[0][0] == "PUT"
    assert "dmarc_default_retention" in call[0][1]
    body = call[1]["body"]
    assert "180d" in str(body)
    assert "dmarc-*" in str(body)


def test_create_client_policy():
    svc = _make_service()
    svc.create_client_policy("acme", 365)
    call = svc.client.transport.perform_request.call_args
    assert "dmarc_retention_acme" in call[0][1]
    body = call[1]["body"]
    assert "365d" in str(body)
    assert "acme-*" in str(body)


def test_delete_client_policy():
    svc = _make_service()
    svc.delete_client_policy("acme")
    svc.client.transport.perform_request.assert_called_once_with(
        "DELETE",
        "/_plugins/_ism/policies/dmarc_retention_acme",
    )


def test_delete_client_policy_not_found():
    svc = _make_service()
    svc.client.transport.perform_request.side_effect = Exception("not found")
    # Should not raise
    svc.delete_client_policy("acme")


def test_cleanup_emails_nonexistent_maildir():
    svc = _make_service()
    result = svc.cleanup_emails("/nonexistent/maildir")
    assert result == 0


def test_cleanup_emails_deletes_old_files(tmp_path):
    svc = _make_service(email_days=1)

    # Create an old file (2 days ago)
    old_file = tmp_path / "old_email"
    old_file.write_text("old")
    old_mtime = time.time() - (2 * 86400)
    import os
    os.utime(old_file, (old_mtime, old_mtime))

    # Create a recent file
    new_file = tmp_path / "new_email"
    new_file.write_text("new")

    deleted = svc.cleanup_emails(str(tmp_path))
    assert deleted == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_emails_skips_directories(tmp_path):
    svc = _make_service(email_days=1)
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    deleted = svc.cleanup_emails(str(tmp_path))
    assert deleted == 0
    assert subdir.exists()


def test_cleanup_emails_handles_oserror(tmp_path):
    svc = _make_service(email_days=0)  # 0 days = delete everything

    old_file = tmp_path / "locked_email"
    old_file.write_text("data")

    with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
        deleted = svc.cleanup_emails(str(tmp_path))
    assert deleted == 0
