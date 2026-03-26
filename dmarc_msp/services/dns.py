"""DNS record lifecycle orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dmarc_msp.config import Settings
from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord

logger = logging.getLogger(__name__)

DMARC_AUTH_VALUE = "v=DMARC1"


@dataclass
class AuthRecordResult:
    """Result of creating/checking a DMARC authorization record."""

    record: DNSRecord
    already_existed: bool


class DNSProviderError(Exception):
    """Wraps provider errors with the provider name for clarity."""


class DNSService:
    """Orchestrates DMARC authorization DNS record lifecycle."""

    def __init__(self, provider: DNSProvider, settings: Settings):
        self.provider = provider
        self.provider_name = settings.dns.provider
        self.msp_domain = settings.msp.domain
        self.zone = settings.dns.zone

    def _wrap_error(self, e: Exception) -> DNSProviderError:
        return DNSProviderError(f"[{self.provider_name}] {e}")

    def authorization_record_name(self, client_domain: str) -> str:
        """Compute the DMARC authorization record name.

        Per RFC 7489, the record name is:
            <client_domain>._report._dmarc.<msp_domain>

        The provider will append the zone automatically, so we return
        the name relative to the zone.
        """
        # If msp_domain ends with the zone, strip the zone suffix
        msp_part = self.msp_domain
        if msp_part.endswith(f".{self.zone}"):
            msp_part = msp_part[: -len(f".{self.zone}")]

        return f"{client_domain}._report._dmarc.{msp_part}"

    def create_authorization_record(self, client_domain: str) -> AuthRecordResult:
        """Create the DMARC authorization TXT record for a client domain.

        If the record already exists, returns it without calling create.
        """
        name = self.authorization_record_name(client_domain)
        try:
            # Check if the record already exists
            existing = self.provider.get_txt_records(zone=self.zone, name=name)
            for rec in existing:
                if rec.value == DMARC_AUTH_VALUE:
                    logger.info(
                        "DMARC auth record already exists: %s.%s",
                        name,
                        self.zone,
                    )
                    return AuthRecordResult(record=rec, already_existed=True)

            logger.info(
                "Creating DMARC auth record: %s.%s TXT %s",
                name,
                self.zone,
                DMARC_AUTH_VALUE,
            )
            record = self.provider.create_txt_record(
                zone=self.zone, name=name, value=DMARC_AUTH_VALUE
            )
            return AuthRecordResult(record=record, already_existed=False)
        except Exception as e:
            raise self._wrap_error(e) from e

    def delete_authorization_record(self, client_domain: str) -> bool:
        """Delete the DMARC authorization TXT record for a client domain."""
        name = self.authorization_record_name(client_domain)
        logger.info("Deleting DMARC auth record: %s.%s", name, self.zone)
        try:
            return self.provider.delete_txt_record(
                zone=self.zone, name=name, value=DMARC_AUTH_VALUE
            )
        except Exception as e:
            raise self._wrap_error(e) from e

    def verify_authorization_record(self, client_domain: str) -> bool:
        """Check if the DMARC authorization record exists and is correct."""
        name = self.authorization_record_name(client_domain)
        try:
            return self.provider.verify_record_exists(
                zone=self.zone, name=name, expected_value=DMARC_AUTH_VALUE
            )
        except Exception as e:
            raise self._wrap_error(e) from e
