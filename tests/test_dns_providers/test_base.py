"""Tests for DNS provider base class."""

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord


class FakeDNSProvider(DNSProvider):
    """In-memory DNS provider for testing."""

    def __init__(self):
        self.records: dict[str, list[DNSRecord]] = {}

    def create_txt_record(self, zone, name, value, ttl=3600):
        key = f"{name}.{zone}"
        if key not in self.records:
            self.records[key] = []
        for rec in self.records[key]:
            if rec.value == value:
                return rec
        record = DNSRecord(fqdn=key, value=value, ttl=ttl,
                           record_id=f"id-{len(self.records[key])}")
        self.records[key].append(record)
        return record

    def delete_txt_record(self, zone, name, value=None):
        key = f"{name}.{zone}"
        if key not in self.records:
            return False
        if value is None:
            del self.records[key]
            return True
        before = len(self.records[key])
        self.records[key] = [r for r in self.records[key] if r.value != value]
        if not self.records[key]:
            del self.records[key]
        return len(self.records.get(key, [])) < before

    def get_txt_records(self, zone, name):
        key = f"{name}.{zone}"
        return self.records.get(key, [])


def test_create_and_get():
    provider = FakeDNSProvider()
    record = provider.create_txt_record("example.com", "test", "v=DMARC1")
    assert record.fqdn == "test.example.com"
    assert record.value == "v=DMARC1"

    records = provider.get_txt_records("example.com", "test")
    assert len(records) == 1
    assert records[0].value == "v=DMARC1"


def test_create_is_idempotent():
    provider = FakeDNSProvider()
    r1 = provider.create_txt_record("example.com", "test", "v=DMARC1")
    r2 = provider.create_txt_record("example.com", "test", "v=DMARC1")
    assert r1.record_id == r2.record_id
    assert len(provider.get_txt_records("example.com", "test")) == 1


def test_delete():
    provider = FakeDNSProvider()
    provider.create_txt_record("example.com", "test", "v=DMARC1")
    assert provider.delete_txt_record("example.com", "test", "v=DMARC1")
    assert len(provider.get_txt_records("example.com", "test")) == 0


def test_delete_nonexistent():
    provider = FakeDNSProvider()
    assert not provider.delete_txt_record("example.com", "test")


def test_verify_record_exists():
    provider = FakeDNSProvider()
    provider.create_txt_record("example.com", "test", "v=DMARC1")
    assert provider.verify_record_exists("example.com", "test", "v=DMARC1")
    assert not provider.verify_record_exists("example.com", "test", "wrong")
