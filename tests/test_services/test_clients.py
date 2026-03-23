"""Tests for client service."""

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.models import ClientStatus
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
