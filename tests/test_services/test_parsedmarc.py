"""Tests for parsedmarc YAML mapping service."""

from pathlib import Path
from unittest.mock import MagicMock

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
    assert svc.reload() is True
    svc.signaler.send_sighup.assert_called_once()
