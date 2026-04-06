"""AWS Route 53 DNS provider implementation."""

from __future__ import annotations

import logging

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord, parse_txt_value

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
        # Route53 bundles all values for a Name/Type into one record set.
        # DELETE must specify the exact record set as it exists, so we
        # fetch the full record set and either delete it entirely or
        # UPSERT with the remaining values.
        response = self._client.list_resource_record_sets(
            HostedZoneId=self._hosted_zone_id,
            StartRecordName=fqdn,
            StartRecordType="TXT",
            MaxItems="1",
        )
        for rrset in response.get("ResourceRecordSets", []):
            if rrset["Name"].rstrip(".") != fqdn.rstrip("."):
                continue
            if rrset["Type"] != "TXT":
                continue

            all_rrs = rrset.get("ResourceRecords", [])
            ttl = rrset.get("TTL", 3600)

            if value is None:
                # Delete the entire record set.
                keep: list[dict] = []
            else:
                keep = [
                    rr for rr in all_rrs
                    if parse_txt_value(rr["Value"]) != value
                ]
                if len(keep) == len(all_rrs):
                    return False  # value not found

            changes: list[dict] = []
            # Always delete the existing record set first.
            changes.append({
                "Action": "DELETE",
                "ResourceRecordSet": {
                    "Name": fqdn,
                    "Type": "TXT",
                    "TTL": ttl,
                    "ResourceRecords": all_rrs,
                },
            })
            # Re-create with remaining values if any.
            if keep:
                changes.append({
                    "Action": "CREATE",
                    "ResourceRecordSet": {
                        "Name": fqdn,
                        "Type": "TXT",
                        "TTL": ttl,
                        "ResourceRecords": keep,
                    },
                })

            self._client.change_resource_record_sets(
                HostedZoneId=self._hosted_zone_id,
                ChangeBatch={"Changes": changes},
            )
            logger.info("Deleted TXT record: %s", fqdn)
            return True
        return False

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
                val = parse_txt_value(rr["Value"])
                results.append(
                    DNSRecord(fqdn=fqdn, value=val, ttl=rrset.get("TTL", 3600))
                )
        return results

    def list_txt_records(self, zone: str) -> list[DNSRecord]:
        results: list[DNSRecord] = []
        params: dict = {"HostedZoneId": self._hosted_zone_id}
        while True:
            response = self._client.list_resource_record_sets(**params)
            for rrset in response.get("ResourceRecordSets", []):
                if rrset["Type"] != "TXT":
                    continue
                fqdn = rrset["Name"].rstrip(".")
                for rr in rrset.get("ResourceRecords", []):
                    val = parse_txt_value(rr["Value"])
                    results.append(
                        DNSRecord(fqdn=fqdn, value=val, ttl=rrset.get("TTL", 3600))
                    )
            if not response.get("IsTruncated"):
                break
            params["StartRecordName"] = response["NextRecordName"]
            params["StartRecordType"] = response["NextRecordType"]
        return results
