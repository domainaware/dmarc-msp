"""Abstract base class for DNS providers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


def parse_txt_value(raw: str | list[str]) -> str:
    """Normalize a raw DNS TXT record value.

    Accepts either a raw string (potentially with quoted segments) or a
    pre-split list of unquoted strings (as returned by Azure's SDK).

    TXT records may be returned as one or more quoted segments:
        ``"v=DMARC1"``  or  ``"v=spf1 " "include:example.com " "-all"``

    This function splits on quoted segments, concatenates them, and
    returns a single unquoted string.  A value with no quotes is
    returned as-is (stripped).
    """
    if isinstance(raw, list):
        return "".join(raw)
    raw = raw.strip()
    segments = re.findall(r'"([^"]*)"', raw)
    if segments:
        return "".join(segments)
    return raw


@dataclass
class DNSRecord:
    """Represents a TXT record."""

    fqdn: str
    value: str
    ttl: int = 3600
    record_id: str | None = None


class DNSProvider(ABC):
    """Abstract base for DNS providers.

    All providers manage records on the MSP's domain only.
    Client-side _dmarc records are the client's responsibility.
    """

    @abstractmethod
    def create_txt_record(
        self, zone: str, name: str, value: str, ttl: int = 3600
    ) -> DNSRecord:
        """Create a TXT record. Idempotent — no-op if it already exists
        with the same value."""
        ...

    @abstractmethod
    def delete_txt_record(self, zone: str, name: str, value: str | None = None) -> bool:
        """Delete a TXT record. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    def get_txt_records(self, zone: str, name: str) -> list[DNSRecord]:
        """Retrieve all TXT records for a given name."""
        ...

    def verify_record_exists(self, zone: str, name: str, expected_value: str) -> bool:
        """Check whether the expected record exists."""
        records = self.get_txt_records(zone, name)
        return any(r.value == expected_value for r in records)
