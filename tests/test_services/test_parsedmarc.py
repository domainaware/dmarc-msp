"""Tests for parsedmarc YAML mapping service."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dmarc_msp.services.parsedmarc import ParsedmarcService


def _make_service(tmp_path: Path) -> ParsedmarcService:
    domain_map = tmp_path / "domain_map.yaml"
    signaler = MagicMock()
    signaler.send_sighup.return_value = True
    return ParsedmarcService(str(domain_map), signaler)


def test_add_domain_mapping(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.add_domain_mapping("acme", "acme.net")

    mapping = svc.get_all_mappings()
    assert mapping["acme"] == ["acme.com", "acme.net"]


def test_add_duplicate_is_noop(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.add_domain_mapping("acme", "acme.com")

    mapping = svc.get_all_mappings()
    assert mapping["acme"] == ["acme.com"]


def test_remove_domain_mapping(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.add_domain_mapping("acme", "acme.net")
    svc.remove_domain_mapping("acme", "acme.com")

    mapping = svc.get_all_mappings()
    assert mapping["acme"] == ["acme.net"]


def test_remove_last_domain_removes_prefix(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.remove_domain_mapping("acme", "acme.com")

    mapping = svc.get_all_mappings()
    assert "acme" not in mapping


def test_move_domain_mapping(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.move_domain_mapping("acme", "other", "acme.com")

    mapping = svc.get_all_mappings()
    assert "acme" not in mapping
    assert mapping["other"] == ["acme.com"]


def test_domains_are_sorted(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "zebra.com")
    svc.add_domain_mapping("acme", "alpha.com")

    mapping = svc.get_all_mappings()
    assert mapping["acme"] == ["alpha.com", "zebra.com"]


def test_reload_calls_signaler(tmp_path):
    svc = _make_service(tmp_path)
    svc.reload()  # Should not raise
    svc.signaler.send_sighup.assert_called_once()


def test_reload_raises_on_failure(tmp_path):
    from dmarc_msp.services.parsedmarc import ParsedmarcReloadError

    svc = _make_service(tmp_path)
    svc.signaler.send_sighup.return_value = False

    with pytest.raises(ParsedmarcReloadError, match="Failed to send SIGHUP"):
        svc.reload()


def test_written_file_has_managed_header(tmp_path):
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")

    content = (tmp_path / "domain_map.yaml").read_text()
    assert content.startswith("# This file is managed by dmarcmsp.")


def test_atomic_write_no_temp_files_left(tmp_path):
    """After a successful write, no .tmp files should remain."""
    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    svc.add_domain_mapping("acme", "acme.net")
    svc.remove_domain_mapping("acme", "acme.com")

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_atomic_write_preserves_content_on_error(tmp_path):
    """If the write fails, the original file should be untouched."""
    from unittest.mock import patch

    svc = _make_service(tmp_path)
    svc.add_domain_mapping("acme", "acme.com")
    original_content = (tmp_path / "domain_map.yaml").read_text()

    # Make os.rename fail to simulate a filesystem error after writing
    # the temp file but before the atomic rename.
    with patch("os.rename", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            svc.add_domain_mapping("acme", "acme.net")

    # Original file unchanged
    assert (tmp_path / "domain_map.yaml").read_text() == original_content

    # Temp file cleaned up
    assert list(tmp_path.glob("*.tmp")) == []
