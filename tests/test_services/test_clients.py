"""Tests for client service."""

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.services.clients import (
    ClientAlreadyExistsError,
    ClientNotFoundError,
    ClientService,
)


def test_create_client(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp", contact_email="test@acme.com")
    assert client.name == "acme corp"
    assert client.index_prefix == "acme_corp"
    assert client.tenant_name == "acme_corp"
    assert client.contact_email == "test@acme.com"


def test_create_duplicate_raises(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    with pytest.raises(ClientAlreadyExistsError):
        svc.create("Acme Corp")


def test_get_client(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    client = svc.get("Acme Corp")
    assert client.name == "acme corp"


def test_get_nonexistent_raises(db_session: Session):
    svc = ClientService(db_session)
    with pytest.raises(ClientNotFoundError):
        svc.get("Nonexistent")


def test_list_clients(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    svc.create("HealthCo")
    clients = svc.list()
    assert len(clients) == 2


def test_update_client(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    client = svc.update("Acme Corp", contact_email="new@acme.com")
    assert client.contact_email == "new@acme.com"


def test_create_with_custom_prefix(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp", index_prefix="custom_prefix")
    assert client.index_prefix == "custom_prefix"


def test_rename_client(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    client = svc.rename("Acme Corp", "Acme Inc")
    assert client.name == "acme inc"
    assert client.index_prefix == "acme_corp"  # unchanged
    assert client.tenant_name == "acme_corp"  # unchanged

    # Old name no longer works
    with pytest.raises(ClientNotFoundError):
        svc.get("Acme Corp")

    # New name works
    assert svc.get("Acme Inc").name == "acme inc"


def test_rename_to_existing_raises(db_session: Session):
    svc = ClientService(db_session)
    svc.create("Acme Corp")
    svc.create("HealthCo")
    with pytest.raises(ClientAlreadyExistsError):
        svc.rename("Acme Corp", "HealthCo")


def test_reactivate_offboarded_client(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp", contact_email="old@acme.com")
    client.status = "offboarded"
    db_session.commit()

    reactivated = svc.create("Acme Corp", contact_email="new@acme.com")
    assert reactivated.status == "active"
    assert reactivated.contact_email == "new@acme.com"
    assert reactivated.offboarded_at is None


def test_reactivate_preserves_retention_when_not_specified(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp", retention_days=365)
    client.status = "offboarded"
    db_session.commit()

    reactivated = svc.create("Acme Corp")
    assert reactivated.retention_days == 365


def test_get_by_id(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp")
    found = svc.get_by_id(client.id)
    assert found.name == "acme corp"


def test_get_by_id_not_found(db_session: Session):
    svc = ClientService(db_session)
    with pytest.raises(ClientNotFoundError, match="id 9999"):
        svc.get_by_id(9999)


def test_to_info(db_session: Session):
    svc = ClientService(db_session)
    client = svc.create("Acme Corp", contact_email="test@acme.com")
    info = svc.to_info(client)
    assert info.name == "acme corp"
    assert info.contact_email == "test@acme.com"
    assert info.index_prefix == "acme_corp"
