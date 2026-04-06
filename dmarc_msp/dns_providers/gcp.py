"""Google Cloud DNS provider implementation."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord, parse_txt_value

logger = logging.getLogger(__name__)

GCP_SECRET_PATH = "/run/secrets/gcp_sa_key"


class GCPDNSProvider(DNSProvider):
    """Manages TXT records via Google Cloud DNS."""

    def __init__(self, project: str, managed_zone: str | None = None):
        try:
            from google.cloud import dns as gdns  # type: ignore[reportMissingImports]
        except ImportError as e:
            raise ImportError(
                "Install the 'gcp' extra: pip install dmarc-msp[gcp]"
            ) from e

        # Point the Google auth library at the Docker secret if it exists
        # and GOOGLE_APPLICATION_CREDENTIALS isn't already set.
        if (
            not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            and Path(GCP_SECRET_PATH).exists()
        ):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_SECRET_PATH

        self._dns_client = gdns.Client(project=project)
        self._managed_zone_name = managed_zone
        self._zone_cache: dict[str, Any] = {}

    def _get_zone(self, zone: str):
        if zone in self._zone_cache:
            return self._zone_cache[zone]
        zone_name = self._managed_zone_name or zone.replace(".", "-")
        managed_zone = self._dns_client.zone(zone_name, zone)
        self._zone_cache[zone] = managed_zone
        return managed_zone

    def _fqdn(self, name: str, zone: str) -> str:
        """Ensure name is a fully qualified domain name with trailing dot."""
        if name.endswith(f".{zone}."):
            return name
        if name.endswith(f".{zone}"):
            return f"{name}."
        return f"{name}.{zone}."

    def create_txt_record(
        self, zone: str, name: str, value: str, ttl: int = 3600
    ) -> DNSRecord:
        fqdn = self._fqdn(name, zone)
        existing = self.get_txt_records(zone, name)
        for rec in existing:
            if rec.value == value:
                logger.info("TXT record already exists: %s", fqdn)
                return rec

        managed_zone = self._get_zone(zone)
        record_set = managed_zone.resource_record_set(fqdn, "TXT", ttl, [f'"{value}"'])
        changes = managed_zone.changes()
        changes.add_record_set(record_set)
        changes.create()
        logger.info("Created TXT record: %s -> %s", fqdn, value)
        return DNSRecord(fqdn=fqdn, value=value, ttl=ttl)

    def delete_txt_record(self, zone: str, name: str, value: str | None = None) -> bool:
        fqdn = self._fqdn(name, zone)
        managed_zone = self._get_zone(zone)
        records = list(managed_zone.list_resource_record_sets())
        deleted = False
        for rrset in records:
            if rrset.name != fqdn or rrset.record_type != "TXT":
                continue
            if value is not None:
                matching = [r for r in rrset.rrdatas if r.strip('"') == value]
                if not matching:
                    continue
            changes = managed_zone.changes()
            changes.delete_record_set(rrset)
            changes.create()
            logger.info("Deleted TXT record: %s", fqdn)
            deleted = True
        return deleted

    def get_txt_records(self, zone: str, name: str) -> list[DNSRecord]:
        fqdn = self._fqdn(name, zone)
        managed_zone = self._get_zone(zone)
        results: list[DNSRecord] = []
        for rrset in managed_zone.list_resource_record_sets():
            if rrset.name != fqdn or rrset.record_type != "TXT":
                continue
            for rdata in rrset.rrdatas:
                results.append(
                    DNSRecord(
                        fqdn=fqdn,
                        value=parse_txt_value(rdata),
                        ttl=rrset.ttl,
                    )
                )
        return results

    def list_txt_records(self, zone: str) -> list[DNSRecord]:
        managed_zone = self._get_zone(zone)
        results: list[DNSRecord] = []
        for rrset in managed_zone.list_resource_record_sets():
            if rrset.record_type != "TXT":
                continue
            for rdata in rrset.rrdatas:
                results.append(
                    DNSRecord(
                        fqdn=rrset.name,
                        value=parse_txt_value(rdata),
                        ttl=rrset.ttl,
                    )
                )
        return results
