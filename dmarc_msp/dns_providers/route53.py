"""AWS Route 53 DNS provider implementation."""

from __future__ import annotations

import logging

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord

logger = logging.getLogger(__name__)


class Route53DNSProvider(DNSProvider):
    """Manages TXT records via AWS Route 53."""

    def __init__(self, hosted_zone_id: str):
        try:
            import boto3
        except ImportError as e:
            raise ImportError(
                "Install the 'aws' extra: pip install dmarc-msp[aws]"
            ) from e
        self._client = boto3.client("route53")
        self._hosted_zone_id = hosted_zone_id

    def _fqdn(self, name: str, zone: str) -> str:
        return f"{name}.{zone}." if not name.endswith(".") else name

    def create_txt_record(
        self, zone: str, name: str, value: str, ttl: int = 3600
    ) -> DNSRecord:
        fqdn = self._fqdn(name, zone)

        # Check existing (idempotent)
        existing = self.get_txt_records(zone, name)
        for rec in existing:
            if rec.value == value:
                logger.info("TXT record already exists: %s", fqdn)
                return rec

        self._client.change_resource_record_sets(
            HostedZoneId=self._hosted_zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": fqdn,
                            "Type": "TXT",
                            "TTL": ttl,
                            "ResourceRecords": [{"Value": f'"{value}"'}],
                        },
                    }
                ]
            },
        )
        logger.info("Created/updated TXT record: %s -> %s", fqdn, value)
        return DNSRecord(fqdn=fqdn, value=value, ttl=ttl)

    def delete_txt_record(self, zone: str, name: str, value: str | None = None) -> bool:
        fqdn = self._fqdn(name, zone)
        records = self.get_txt_records(zone, name)
        if not records:
            return False

        for rec in records:
            if value is not None and rec.value != value:
                continue
            self._client.change_resource_record_sets(
                HostedZoneId=self._hosted_zone_id,
                ChangeBatch={
                    "Changes": [
                        {
                            "Action": "DELETE",
                            "ResourceRecordSet": {
                                "Name": fqdn,
                                "Type": "TXT",
                                "TTL": rec.ttl,
                                "ResourceRecords": [{"Value": f'"{rec.value}"'}],
                            },
                        }
                    ]
                },
            )
            logger.info("Deleted TXT record: %s", fqdn)
        return True

    def get_txt_records(self, zone: str, name: str) -> list[DNSRecord]:
        fqdn = self._fqdn(name, zone)
        response = self._client.list_resource_record_sets(
            HostedZoneId=self._hosted_zone_id,
            StartRecordName=fqdn,
            StartRecordType="TXT",
            MaxItems="1",
        )
        results: list[DNSRecord] = []
        for rrset in response.get("ResourceRecordSets", []):
            if rrset["Name"].rstrip(".") != fqdn.rstrip("."):
                continue
            if rrset["Type"] != "TXT":
                continue
            for rr in rrset.get("ResourceRecords", []):
                val = rr["Value"].strip('"')
                results.append(
                    DNSRecord(fqdn=fqdn, value=val, ttl=rrset.get("TTL", 3600))
                )
        return results
