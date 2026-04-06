"""Tests for DNS service."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.config import Settings
from dmarc_msp.db import ClientRow, DomainRow
from dmarc_msp.models import DomainStatus
from dmarc_msp.services.dns import DNSProviderError, DNSService
from tests.test_dns_providers.test_base import FakeDNSProvider


def _make_svc(provider=None):
    """Create a DNSService with default test settings."""
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com"},
        opensearch={"password": "test"},
    )
    return DNSService(provider or FakeDNSProvider(), settings)


def test_authorization_record_name():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com"},
        opensearch={"password": "test"},
    )
    provider = FakeDNSProvider()
    svc = DNSService(provider, settings)

    name = svc.authorization_record_name("client.example.com")
    assert name == "client.example.com._report._dmarc.dmarc"


def test_create_and_verify_authorization_record():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com"},
        opensearch={"password": "test"},
    )
    provider = FakeDNSProvider()
    svc = DNSService(provider, settings)

    result = svc.create_authorization_record("client.example.com")
    assert result.record.value == "v=DMARC1"
    assert result.already_existed is False

    assert svc.verify_authorization_record("client.example.com")


def test_create_authorization_record_already_exists():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com"},
        opensearch={"password": "test"},
    )
    provider = FakeDNSProvider()
    svc = DNSService(provider, settings)

    # First creation
    svc.create_authorization_record("client.example.com")

    # Second creation should detect existing record
    result = svc.create_authorization_record("client.example.com")
    assert result.record.value == "v=DMARC1"
    assert result.already_existed is True


def test_delete_authorization_record():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com"},
        opensearch={"password": "test"},
    )
    provider = FakeDNSProvider()
    svc = DNSService(provider, settings)

    svc.create_authorization_record("client.example.com")
    assert svc.delete_authorization_record("client.example.com")
    assert not svc.verify_authorization_record("client.example.com")


def test_create_error_includes_provider_name():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com", "provider": "cloudflare"},
        opensearch={"password": "test"},
    )
    provider = MagicMock()
    provider.get_txt_records.return_value = []
    provider.create_txt_record.side_effect = RuntimeError("record exists")
    svc = DNSService(provider, settings)

    with pytest.raises(DNSProviderError, match=r"\[cloudflare\].*record exists"):
        svc.create_authorization_record("client.example.com")


def test_delete_error_includes_provider_name():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com", "provider": "route53"},
        opensearch={"password": "test"},
    )
    provider = MagicMock()
    provider.delete_txt_record.side_effect = RuntimeError("access denied")
    svc = DNSService(provider, settings)

    with pytest.raises(DNSProviderError, match=r"\[route53\].*access denied"):
        svc.delete_authorization_record("client.example.com")


def test_verify_error_includes_provider_name():
    settings = Settings(
        msp={"domain": "dmarc.msp-example.com"},
        dns={"zone": "msp-example.com", "provider": "gcp"},
        opensearch={"password": "test"},
    )
    provider = MagicMock()
    provider.verify_record_exists.side_effect = ConnectionError("timeout")
    svc = DNSService(provider, settings)

    with pytest.raises(DNSProviderError, match=r"\[gcp\].*timeout"):
        svc.verify_authorization_record("client.example.com")


# --- _extract_client_domain ---


def test_extract_client_domain_normal():
    svc = _make_svc()
    fqdn = "client.com._report._dmarc.dmarc.msp-example.com"
    assert svc._extract_client_domain(fqdn) == "client.com"


def test_extract_client_domain_trailing_dot():
    svc = _make_svc()
    fqdn = "client.com._report._dmarc.dmarc.msp-example.com."
    assert svc._extract_client_domain(fqdn) == "client.com"


def test_extract_client_domain_non_matching():
    svc = _make_svc()
    assert svc._extract_client_domain("unrelated.msp-example.com") is None


def test_extract_client_domain_subdomain_client():
    svc = _make_svc()
    fqdn = "sub.client.com._report._dmarc.dmarc.msp-example.com"
    assert svc._extract_client_domain(fqdn) == "sub.client.com"


# --- cleanup_stale_records ---


def _add_client_domain(db: Session, client_name: str, domain: str, status: str):
    """Helper to add a client + domain row to the test database."""
    client = db.query(ClientRow).filter_by(name=client_name).first()
    if not client:
        from dmarc_msp.db import slugify

        client = ClientRow(
            name=client_name,
            index_prefix=slugify(client_name),
            tenant_name=slugify(client_name),
        )
        db.add(client)
        db.flush()

    domain_row = DomainRow(
        domain_name=domain,
        client_id=client.id,
        status=status,
    )
    db.add(domain_row)
    db.commit()


def test_cleanup_dry_run(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    # Create auth records for 3 domains.
    svc.create_authorization_record("active.com")
    svc.create_authorization_record("pending.com")
    svc.create_authorization_record("orphan.com")

    # Only 2 domains exist in the DB.
    _add_client_domain(db_session, "acme", "active.com", DomainStatus.ACTIVE)
    _add_client_domain(db_session, "acme", "pending.com", DomainStatus.PENDING_DNS)

    result = svc.cleanup_stale_records(db_session, dry_run=True)

    assert result.dry_run is True
    assert result.stale == ["orphan.com"]
    assert result.active_skipped == 2
    assert result.failed == []
    # DNS records should NOT have been deleted.
    assert svc.verify_authorization_record("orphan.com")


def test_cleanup_deletes_stale(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    svc.create_authorization_record("active.com")
    svc.create_authorization_record("orphan.com")

    _add_client_domain(db_session, "acme", "active.com", DomainStatus.ACTIVE)

    result = svc.cleanup_stale_records(db_session, dry_run=False)

    assert result.stale == ["orphan.com"]
    assert result.active_skipped == 1
    assert not svc.verify_authorization_record("orphan.com")
    assert svc.verify_authorization_record("active.com")


def test_cleanup_offboarded_domain_is_stale(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    svc.create_authorization_record("old.com")
    _add_client_domain(db_session, "acme", "old.com", DomainStatus.OFFBOARDED)

    result = svc.cleanup_stale_records(db_session, dry_run=True)

    assert "old.com" in result.stale


def test_cleanup_pending_dns_is_not_stale(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    svc.create_authorization_record("new.com")
    _add_client_domain(db_session, "acme", "new.com", DomainStatus.PENDING_DNS)

    result = svc.cleanup_stale_records(db_session, dry_run=True)

    assert result.stale == []
    assert result.active_skipped == 1


def test_cleanup_no_stale_records(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    svc.create_authorization_record("only.com")
    _add_client_domain(db_session, "acme", "only.com", DomainStatus.ACTIVE)

    result = svc.cleanup_stale_records(db_session, dry_run=False)

    assert result.stale == []
    assert result.active_skipped == 1
    assert result.failed == []


def test_cleanup_ignores_non_dmarc_records(db_session: Session):
    provider = FakeDNSProvider()
    svc = _make_svc(provider)

    # Add a non-DMARC TXT record directly.
    provider.create_txt_record("msp-example.com", "spf", "v=spf1 -all")

    result = svc.cleanup_stale_records(db_session, dry_run=True)

    assert result.stale == []
    assert result.active_skipped == 0
