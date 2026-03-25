"""Tests for DNS service."""

from unittest.mock import MagicMock

import pytest

from dmarc_msp.config import Settings
from dmarc_msp.services.dns import DNSProviderError, DNSService
from tests.test_dns_providers.test_base import FakeDNSProvider


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

    record = svc.create_authorization_record("client.example.com")
    assert record.value == "v=DMARC1"

    assert svc.verify_authorization_record("client.example.com")


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
