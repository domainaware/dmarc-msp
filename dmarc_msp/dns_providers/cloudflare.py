"""Cloudflare DNS provider implementation."""

from __future__ import annotations

import logging
from pathlib import Path

import cloudflare as cf

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord, parse_txt_value

logger = logging.getLogger(__name__)


class CloudflareDNSProvider(DNSProvider):
    """Manages TXT records via the Cloudflare API."""

    def __init__(self, api_token: str | None = None):
        token = api_token or self._resolve_token()
        self._client = cf.Cloudflare(api_token=token)
        self._zone_id_cache: dict[str, str] = {}

    @staticmethod
    def _resolve_token() -> str:
        import os

        token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if token:
            return token
        secret_path = Path("/run/secrets/cloudflare_api_token")
        if secret_path.exists():
            return secret_path.read_text().strip()
        raise ValueError("Cloudflare API token not found in env or /run/secrets/")

    def _get_zone_id(self, zone: str) -> str:
        if zone in self._zone_id_cache:
            return self._zone_id_cache[zone]
        zones = self._client.zones.list(name=zone)
        if not zones.result:
            raise ValueError(f"Zone '{zone}' not found in Cloudflare account")
        zone_id = zones.result[0].id  # type: ignore[union-attr]
        self._zone_id_cache[zone] = zone_id
        return zone_id

    def _fqdn(self, name: str, zone: str) -> str:
        """Ensure name is a fully qualified domain name."""
        fqdn = f"{name}.{zone}" if not name.endswith(f".{zone}") else name
        return fqdn

    def create_txt_record(
        self, zone: str, name: str, value: str, ttl: int = 3600
    ) -> DNSRecord:
        zone_id = self._get_zone_id(zone)

        # Check for existing record (idempotent)
        existing = self.get_txt_records(zone, name)
        for rec in existing:
            if rec.value == value:
                logger.info("TXT record already exists: %s -> %s", name, value)
                return rec

        fqdn = self._fqdn(name, zone)
        result = self._client.dns.records.create(
            zone_id=zone_id,
            type="TXT",
            name=fqdn,
            content=value,
            ttl=ttl,
        )
        record_id = result.id  # type: ignore[union-attr]
        logger.info("Created TXT record: %s -> %s (id=%s)", fqdn, value, record_id)
        return DNSRecord(
            fqdn=fqdn,
            value=value,
            ttl=ttl,
            record_id=record_id,
        )

    def delete_txt_record(self, zone: str, name: str, value: str | None = None) -> bool:
        zone_id = self._get_zone_id(zone)
        fqdn = self._fqdn(name, zone)
        deleted = False
        records = self._client.dns.records.list(zone_id=zone_id, type="TXT", name=fqdn)
        for rec in records:
            if value is None or rec.content == value:
                self._client.dns.records.delete(rec.id, zone_id=zone_id)  # type: ignore[arg-type]
                logger.info("Deleted TXT record: %s (id=%s)", name, rec.id)
                deleted = True
        return deleted

    def get_txt_records(self, zone: str, name: str) -> list[DNSRecord]:
        zone_id = self._get_zone_id(zone)
        fqdn = self._fqdn(name, zone)
        records = self._client.dns.records.list(
            zone_id=zone_id, type="TXT", name=fqdn
        )
        return [
            DNSRecord(
                fqdn=rec.name,
                value=parse_txt_value(str(rec.content)),
                ttl=int(rec.ttl or 3600),
                record_id=rec.id,
            )
            for rec in records
        ]

    def list_txt_records(self, zone: str) -> list[DNSRecord]:
        zone_id = self._get_zone_id(zone)
        # Iterate directly for auto-pagination (`.result` only returns
        # the first page, which would silently truncate large zones).
        return [
            DNSRecord(
                fqdn=rec.name,
                value=parse_txt_value(str(rec.content)),
                ttl=int(rec.ttl or 3600),
                record_id=rec.id,
            )
            for rec in self._client.dns.records.list(zone_id=zone_id, type="TXT")
        ]
