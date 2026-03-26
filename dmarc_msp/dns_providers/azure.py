"""Azure DNS provider implementation."""

from __future__ import annotations

import logging

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord

# Azure SDK raises ResourceNotFoundError for missing records, but we
# import it lazily to avoid requiring the azure extra at import time.
_AZURE_NOT_FOUND_CODES = {"ResourceNotFound", "NotFound"}

logger = logging.getLogger(__name__)


class AzureDNSProvider(DNSProvider):
    """Manages TXT records via Azure DNS."""

    def __init__(self, subscription_id: str, resource_group: str, zone_name: str):
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.dns import DnsManagementClient
        except ImportError as e:
            raise ImportError(
                "Install the 'azure' extra: pip install dmarc-msp[azure]"
            ) from e
        credential = DefaultAzureCredential()
        self._client = DnsManagementClient(credential, subscription_id)
        self._resource_group = resource_group
        self._zone_name = zone_name

    def create_txt_record(
        self, zone: str, name: str, value: str, ttl: int = 3600
    ) -> DNSRecord:
        existing = self.get_txt_records(zone, name)
        for rec in existing:
            if rec.value == value:
                logger.info("TXT record already exists: %s.%s", name, zone)
                return rec

        from azure.mgmt.dns.models import RecordSet, TxtRecord

        self._client.record_sets.create_or_update(
            self._resource_group,
            self._zone_name,
            name,
            "TXT",
            RecordSet(ttl=ttl, txt_records=[TxtRecord(value=[value])]),
        )
        fqdn = f"{name}.{zone}"
        logger.info("Created TXT record: %s -> %s", fqdn, value)
        return DNSRecord(fqdn=fqdn, value=value, ttl=ttl)

    @staticmethod
    def _is_not_found(e: Exception) -> bool:
        """Check if an Azure SDK exception is a not-found error."""
        error_code = getattr(e, "error_code", None) or getattr(e, "code", None)
        if error_code and error_code in _AZURE_NOT_FOUND_CODES:
            return True
        # HttpResponseError with status 404
        status = getattr(e, "status_code", None)
        return status == 404

    def delete_txt_record(self, zone: str, name: str, value: str | None = None) -> bool:
        try:
            self._client.record_sets.delete(
                self._resource_group, self._zone_name, name, "TXT"
            )
            logger.info("Deleted TXT record: %s.%s", name, zone)
            return True
        except Exception as e:
            if self._is_not_found(e):
                logger.debug("TXT record not found: %s.%s", name, zone)
                return False
            raise

    def get_txt_records(self, zone: str, name: str) -> list[DNSRecord]:
        try:
            record_set = self._client.record_sets.get(
                self._resource_group, self._zone_name, name, "TXT"
            )
        except Exception as e:
            if self._is_not_found(e):
                return []
            raise

        results: list[DNSRecord] = []
        for txt_rec in record_set.txt_records or []:
            val = " ".join(txt_rec.value)
            results.append(
                DNSRecord(
                    fqdn=f"{name}.{zone}",
                    value=val,
                    ttl=record_set.ttl or 3600,
                )
            )
        return results
