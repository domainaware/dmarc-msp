"""Offboarding orchestrator — full client teardown."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from dmarc_msp.db import AuditLogRow
from dmarc_msp.models import DomainStatus, OffboardingResult
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dns import DNSService
from dmarc_msp.services.opensearch import OpenSearchService
from dmarc_msp.services.parsedmarc import ParsedmarcReloadError, ParsedmarcService
from dmarc_msp.services.retention import RetentionService

logger = logging.getLogger(__name__)


class OffboardingService:
    def __init__(
        self,
        client_service: ClientService,
        dns: DNSService,
        opensearch: OpenSearchService,
        parsedmarc: ParsedmarcService,
        retention: RetentionService,
        db: Session,
    ):
        self.client_service = client_service
        self.dns = dns
        self.opensearch = opensearch
        self.parsedmarc = parsedmarc
        self.retention = retention
        self.db = db

    def offboard_client(
        self,
        client_name: str,
        purge_dns: bool = True,
        purge_indices: bool = False,
    ) -> OffboardingResult:
        """Full client offboarding.

        Transactional — rolls back on failure.
        """
        client = self.client_service.get(client_name)
        active_domains = client.active_domains
        domains_removed = len(active_domains)

        dns_failures: list[tuple[str, str]] = []
        yaml_removed: list[str] = []

        try:
            # Best-effort DNS cleanup — continue on individual failures so
            # that one provider error doesn't leave the DB/DNS state split.
            for domain_row in active_domains:
                if purge_dns:
                    try:
                        self.dns.delete_authorization_record(
                            domain_row.domain_name
                        )
                    except Exception as e:
                        logger.error(
                            "DNS delete failed for %s: %s",
                            domain_row.domain_name,
                            e,
                        )
                        dns_failures.append((domain_row.domain_name, str(e)))

                self.parsedmarc.remove_domain_mapping(
                    client.index_prefix, domain_row.domain_name
                )
                yaml_removed.append(domain_row.domain_name)
                domain_row.status = DomainStatus.OFFBOARDED.value
                domain_row.offboarded_at = datetime.now(UTC)

            # Reload parsedmarc — best-effort during offboarding.
            # The YAML is already updated, so parsedmarc will pick up the
            # changes on its next restart even if the signal fails now.
            try:
                self.parsedmarc.reload()
            except ParsedmarcReloadError:
                logger.warning(
                    "parsedmarc reload failed during offboarding of '%s' — "
                    "YAML is updated but parsedmarc has not reloaded",
                    client.name,
                )

            # Deprovision OpenSearch tenant, role, and role mapping
            self.opensearch.deprovision_tenant(client.tenant_name)
            self.retention.delete_client_policy(client.index_prefix)

            # Optionally purge data indices
            if purge_indices:
                self.opensearch.delete_client_indices(client.index_prefix)

            # Mark client as offboarded
            client.status = "offboarded"
            client.offboarded_at = datetime.now(UTC)

            self.db.add(
                AuditLogRow(
                    client_id=client.id,
                    action="client_offboard",
                    detail={
                        "domains_removed": domains_removed,
                        "purge_dns": purge_dns,
                        "purge_indices": purge_indices,
                        "dns_failures": dns_failures,
                    },
                    success=True,
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            # Restore YAML mappings that were already removed so the
            # domain map stays consistent with the rolled-back DB state.
            for domain_name in yaml_removed:
                try:
                    self.parsedmarc.add_domain_mapping(
                        client.index_prefix, domain_name
                    )
                except Exception:
                    logger.error(
                        "Failed to restore YAML mapping for '%s' after "
                        "rollback — manual cleanup may be needed",
                        domain_name,
                    )
            raise

        if dns_failures:
            logger.warning(
                "Client '%s' offboarded with %d DNS cleanup failure(s): %s",
                client.name,
                len(dns_failures),
                ", ".join(d for d, _ in dns_failures),
            )

        return OffboardingResult(
            client_name=client.name,
            domains_removed=domains_removed,
            dns_failures=dns_failures,
        )
