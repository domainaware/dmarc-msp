"""Tests for onboarding service."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.onboarding import (
    DomainAlreadyExistsError,
    DomainNotFoundError,
    OnboardingService,
)


def _make_service(db_session: Session):
    client_svc = ClientService(db_session)
    dns = MagicMock()
    dns.create_authorization_record.return_value = MagicMock(record_id="rec_123")
    dns.verify_authorization_record.return_value = True
    dns.delete_authorization_record.return_value = True
    opensearch = MagicMock()
    dashboards = MagicMock()
    retention = MagicMock()
    parsedmarc = MagicMock()

    svc = OnboardingService(
        client_service=client_svc,
        dns=dns,
        opensearch=opensearch,
        dashboards=dashboards,
        retention=retention,
        parsedmarc=parsedmarc,
        db=db_session,
    )
    return svc, client_svc


def test_add_domain_creates_client_if_missing(db_session: Session):
    svc, _ = _make_service(db_session)
    result = svc.add_domain("NewClient", "example.com")
    assert result.client_name == "newclient"
    assert result.domain == "example.com"
    assert result.dns_verified is True


def test_add_domain_to_existing_client(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    result = svc.add_domain("Acme Corp", "acme.com")
    assert result.client_name == "acme corp"
    assert result.index_prefix == "acme_corp"


def test_add_domain_provisions_on_first_domain(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.opensearch.provision_tenant.assert_called_once()
    svc.opensearch.create_client_role.assert_called_once()


def test_add_domain_skips_provisioning_on_subsequent_domains(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.opensearch.reset_mock()
    svc.add_domain("Acme Corp", "acme.net")
    svc.opensearch.provision_tenant.assert_not_called()


def test_add_domain_creates_retention_policy_if_client_has_custom(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp", retention_days=365)
    svc.add_domain("Acme Corp", "acme.com")
    svc.retention.create_client_policy.assert_called_once_with("acme_corp", 365)


def test_add_domain_duplicate_raises(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    with pytest.raises(DomainAlreadyExistsError, match="already monitored"):
        svc.add_domain("Acme Corp", "acme.com")


def test_add_domain_reactivates_offboarded(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.remove_domain("acme.com")

    result = svc.add_domain("Acme Corp", "acme.com")
    assert result.domain == "acme.com"


def test_add_domain_handles_dashboard_template_missing(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.dashboards.import_for_client.side_effect = FileNotFoundError
    # Should not raise
    result = svc.add_domain("Acme Corp", "acme.com")
    assert result.domain == "acme.com"


def test_add_domain_dns_not_verified(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.dns.verify_authorization_record.return_value = False
    result = svc.add_domain("Acme Corp", "acme.com")
    assert result.dns_verified is False


def test_remove_domain(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    client_name = svc.remove_domain("acme.com")
    assert client_name == "acme corp"
    svc.dns.delete_authorization_record.assert_called_with("acme.com")
    svc.parsedmarc.remove_domain_mapping.assert_called()


def test_remove_domain_keep_dns(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.dns.reset_mock()
    svc.remove_domain("acme.com", purge_dns=False)
    svc.dns.delete_authorization_record.assert_not_called()


def test_remove_nonexistent_domain(db_session: Session):
    svc, _ = _make_service(db_session)
    with pytest.raises(DomainNotFoundError):
        svc.remove_domain("nonexistent.com")


def test_remove_already_offboarded_domain(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.remove_domain("acme.com")
    with pytest.raises(DomainNotFoundError, match="already offboarded"):
        svc.remove_domain("acme.com")


def test_move_domain(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    client_svc.create("HealthCo")
    svc.add_domain("Acme Corp", "acme.com")
    svc.opensearch.reset_mock()

    result = svc.move_domain("acme.com", "HealthCo")
    assert result.from_client == "acme corp"
    assert result.to_client == "healthco"
    svc.parsedmarc.move_domain_mapping.assert_called()


def test_move_domain_provisions_dest_if_first(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    client_svc.create("HealthCo")
    svc.add_domain("Acme Corp", "acme.com")
    svc.opensearch.reset_mock()

    svc.move_domain("acme.com", "HealthCo")
    svc.opensearch.provision_tenant.assert_called_once()


def test_move_domain_to_offboarded_client_raises(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    dest = client_svc.create("HealthCo")
    dest.status = "offboarded"
    db_session.commit()

    svc.add_domain("Acme Corp", "acme.com")
    with pytest.raises(Exception, match="offboarded"):
        svc.move_domain("acme.com", "HealthCo")


def test_move_domain_to_same_client_raises(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    with pytest.raises(DomainAlreadyExistsError, match="already belongs"):
        svc.move_domain("acme.com", "Acme Corp")


def test_move_domain_with_retention_and_missing_dashboard(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    client_svc.create("HealthCo", retention_days=730)
    svc.add_domain("Acme Corp", "acme.com")
    svc.opensearch.reset_mock()
    svc.dashboards.import_for_client.side_effect = FileNotFoundError

    result = svc.move_domain("acme.com", "HealthCo")
    assert result.to_client == "healthco"
    svc.retention.create_client_policy.assert_called_with("healthco", 730)


def test_move_nonexistent_domain(db_session: Session):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    with pytest.raises(DomainNotFoundError):
        svc.move_domain("nonexistent.com", "Acme Corp")


def test_bulk_import_add(db_session: Session, tmp_path):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")

    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("acme.com\nacme.net\n# comment\n\nacme.org\n")

    result = svc.bulk_import(str(domain_file), "Acme Corp", operation="add")
    assert len(result.succeeded) == 3
    assert result.total == 3


def test_bulk_import_skips_duplicates(db_session: Session, tmp_path):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")

    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("acme.com\nacme.net\n")

    result = svc.bulk_import(str(domain_file), "Acme Corp", operation="add")
    assert len(result.skipped) == 1
    assert len(result.succeeded) == 1


def test_bulk_import_remove(db_session: Session, tmp_path):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    svc.add_domain("Acme Corp", "acme.com")
    svc.add_domain("Acme Corp", "acme.net")

    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("acme.com\nacme.net\n")

    result = svc.bulk_import(str(domain_file), "Acme Corp", operation="remove")
    assert len(result.succeeded) == 2


def test_bulk_import_move(db_session: Session, tmp_path):
    svc, client_svc = _make_service(db_session)
    client_svc.create("Acme Corp")
    client_svc.create("HealthCo")
    svc.add_domain("Acme Corp", "acme.com")

    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("acme.com\n")

    result = svc.bulk_import(str(domain_file), "HealthCo", operation="move")
    assert len(result.succeeded) == 1


def test_bulk_import_handles_errors(db_session: Session, tmp_path):
    svc, client_svc = _make_service(db_session)
    svc.dns.create_authorization_record.side_effect = RuntimeError("DNS failure")

    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("fail.com\n")

    result = svc.bulk_import(str(domain_file), "NewClient", operation="add")
    assert len(result.failed) == 1
    assert "DNS failure" in result.failed[0][1]


def test_parse_domain_file_deduplicates(db_session: Session, tmp_path):
    svc, _ = _make_service(db_session)
    domain_file = tmp_path / "domains.txt"
    domain_file.write_text("acme.com\nacme.com\nACME.COM\n")

    domains = svc._parse_domain_file(str(domain_file))
    assert domains == ["acme.com"]
