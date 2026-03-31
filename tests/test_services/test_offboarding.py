"""Tests for offboarding service."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.offboarding import OffboardingService
from dmarc_msp.services.onboarding import OnboardingService


def _make_services(db_session: Session):
    client_svc = ClientService(db_session)
    dns = MagicMock()
    dns.create_authorization_record.return_value = MagicMock(
        record=MagicMock(record_id="rec_123"),
        already_existed=False,
    )
    dns.verify_authorization_record.return_value = True
    dns.delete_authorization_record.return_value = True
    opensearch = MagicMock()
    dashboards = MagicMock()
    retention = MagicMock()
    parsedmarc = MagicMock()

    onboard_svc = OnboardingService(
        client_service=client_svc,
        dns=dns,
        opensearch=opensearch,
        dashboards=dashboards,
        retention=retention,
        parsedmarc=parsedmarc,
        db=db_session,
    )
    offboard_svc = OffboardingService(
        client_service=client_svc,
        dns=dns,
        opensearch=opensearch,
        parsedmarc=parsedmarc,
        retention=retention,
        db=db_session,
    )
    return onboard_svc, offboard_svc, client_svc


def test_offboard_client(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")
    onboard.add_domain("Acme Corp", "acme.net")

    result = offboard.offboard_client("Acme Corp")
    assert result.client_name == "acme corp"
    assert result.domains_removed == 2

    client = client_svc.get("Acme Corp")
    assert client.status == "offboarded"
    assert client.offboarded_at is not None


def test_offboard_client_purges_dns(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")

    offboard.offboard_client("Acme Corp", purge_dns=True)
    offboard.dns.delete_authorization_record.assert_called_with("acme.com")


def test_offboard_client_skips_dns_purge(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")
    offboard.dns.reset_mock()

    offboard.offboard_client("Acme Corp", purge_dns=False)
    offboard.dns.delete_authorization_record.assert_not_called()


def test_offboard_client_purges_indices(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")

    offboard.offboard_client("Acme Corp", purge_indices=True)
    offboard.opensearch.delete_client_indices.assert_called_once_with("acme_corp")


def test_offboard_client_no_index_purge_by_default(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")

    offboard.offboard_client("Acme Corp")
    offboard.opensearch.delete_client_indices.assert_not_called()


def test_offboard_deprovisions_tenant_and_role(db_session: Session):
    onboard, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")
    onboard.add_domain("Acme Corp", "acme.com")

    offboard.offboard_client("Acme Corp")
    offboard.opensearch.deprovision_tenant.assert_called_once_with("client_acme_corp")
    offboard.retention.delete_client_policy.assert_called_once_with("acme_corp")


def test_offboard_client_with_no_domains(db_session: Session):
    _, offboard, client_svc = _make_services(db_session)
    client_svc.create("Acme Corp")

    result = offboard.offboard_client("Acme Corp")
    assert result.domains_removed == 0
