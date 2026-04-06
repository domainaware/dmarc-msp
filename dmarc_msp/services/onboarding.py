"""Onboarding orchestrator — full pipeline for adding domains and clients."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from dmarc_msp.db import AuditLogRow, DomainRow
from dmarc_msp.models import (
    BulkResult,
    ClientStatus,
    DomainStatus,
    MoveResult,
    OnboardingResult,
)
from dmarc_msp.services.clients import ClientNotFoundError, ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.dns import DNSService
from dmarc_msp.services.opensearch import OpenSearchService
from dmarc_msp.services.parsedmarc import ParsedmarcService
from dmarc_msp.services.retention import RetentionService

logger = logging.getLogger(__name__)


class DomainAlreadyExistsError(Exception):
    pass


class DomainNotFoundError(Exception):
    pass


class OnboardingService:
    def __init__(
        self,
        client_service: ClientService,
        dns: DNSService,
        opensearch: OpenSearchService,
        dashboards: DashboardService,
        retention: RetentionService,
        parsedmarc: ParsedmarcService,
        db: Session,
    ):
        self.client_service = client_service
        self.dns = dns
        self.opensearch = opensearch
        self.dashboards = dashboards
        self.retention = retention
        self.parsedmarc = parsedmarc
        self.db = db

    def add_domain(
        self,
        client_name: str,
        domain: str,
        index_prefix: str | None = None,
        contact_email: str | None = None,
        create_client: bool = False,
    ) -> OnboardingResult:
        """Full onboarding pipeline for a single domain. Idempotent.

        If the client doesn't exist and create_client is False,
        raises ClientNotFoundError. Pass create_client=True to
        auto-create the client.

        The entire operation is transactional — if any step fails, all
        database changes are rolled back.
        """
        domain = domain.lower().strip()

        # Check for duplicate domain across all clients
        existing = (
            self.db.query(DomainRow).filter(DomainRow.domain_name == domain).first()
        )
        if existing and existing.status != DomainStatus.OFFBOARDED.value:
            existing_client = self.client_service.get_by_id(existing.client_id)
            raise DomainAlreadyExistsError(
                f"Domain '{domain}' is already monitored "
                f"under client '{existing_client.name}'"
            )

        dns_created = False

        try:
            # Ensure client exists
            try:
                client = self.client_service.get(client_name)
            except ClientNotFoundError:
                if not create_client:
                    raise ClientNotFoundError(
                        f"Client '{client_name}' not found. "
                        f"Use --create-client to create it automatically."
                    )
                client = self.client_service.create(
                    name=client_name,
                    contact_email=contact_email,
                    index_prefix=index_prefix,
                    commit=False,
                )

            is_first = len(client.active_domains) == 0

            # Create DMARC authorization DNS record
            auth_result = self.dns.create_authorization_record(domain)
            dns_record = auth_result.record
            dns_created = not auth_result.already_existed

            # Store domain in DB
            if existing and existing.status == DomainStatus.OFFBOARDED.value:
                existing.client_id = client.id
                existing.status = DomainStatus.PENDING_DNS.value
                existing.dns_record_id = dns_record.record_id
                existing.dns_verified = False
                existing.dns_verified_at = None
                existing.offboarded_at = None
                domain_row = existing
            else:
                domain_row = DomainRow(
                    client_id=client.id,
                    domain_name=domain,
                    dns_record_id=dns_record.record_id,
                    status=DomainStatus.PENDING_DNS.value,
                )
                self.db.add(domain_row)

            # Update parsedmarc YAML mapping
            self.parsedmarc.add_domain_mapping(client.index_prefix, domain)

            # Signal parsedmarc to reload
            self.parsedmarc.reload()

            # Provision OpenSearch tenant + role if first domain
            if is_first:
                self.opensearch.provision_tenant(
                    client.tenant_name, client.index_prefix
                )
                if client.retention_days:
                    self.retention.create_client_policy(
                        client.index_prefix, client.retention_days
                    )

            # Import dashboards into tenant
            try:
                self.dashboards.import_for_client(
                    client.tenant_name, client.index_prefix
                )
            except FileNotFoundError:
                logger.warning("Dashboard template not found, skipping import")

            # Verify DNS propagation
            dns_verified = self.dns.verify_authorization_record(domain)
            if dns_verified:
                domain_row.dns_verified = True
                domain_row.dns_verified_at = datetime.now(UTC)
                domain_row.status = DomainStatus.ACTIVE.value

            # Audit
            self.db.add(
                AuditLogRow(
                    client_id=client.id,
                    domain=domain,
                    action="domain_add",
                    detail={"dns_verified": dns_verified},
                    success=True,
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            # Clean up the DNS record we created so it doesn't become
            # a stale orphan.  Best-effort — if this also fails, log it
            # but don't mask the original exception.
            if dns_created:
                try:
                    self.dns.delete_authorization_record(domain)
                except Exception:
                    logger.error(
                        "Failed to clean up DNS record for '%s' after "
                        "rollback — manual cleanup may be needed",
                        domain,
                    )
            raise

        return OnboardingResult(
            client_name=client.name,
            domain=domain,
            dns_verified=dns_verified,
            dns_record_existed=auth_result.already_existed,
            tenant=client.tenant_name,
            index_prefix=client.index_prefix,
        )

    def remove_domain(self, domain: str, purge_dns: bool = True) -> str:
        """Remove a single domain from monitoring. Returns client name.

        Transactional — rolls back on failure.
        """
        domain = domain.lower().strip()
        domain_row = (
            self.db.query(DomainRow).filter(DomainRow.domain_name == domain).first()
        )
        if not domain_row:
            raise DomainNotFoundError(f"Domain '{domain}' not found")
        if domain_row.status == DomainStatus.OFFBOARDED.value:
            raise DomainNotFoundError(f"Domain '{domain}' is already offboarded")

        try:
            client = self.client_service.get_by_id(domain_row.client_id)

            if purge_dns:
                self.dns.delete_authorization_record(domain)

            self.parsedmarc.remove_domain_mapping(client.index_prefix, domain)
            self.parsedmarc.reload()

            domain_row.status = DomainStatus.OFFBOARDED.value
            domain_row.offboarded_at = datetime.now(UTC)

            self.db.add(
                AuditLogRow(
                    client_id=client.id,
                    domain=domain,
                    action="domain_remove",
                    success=True,
                )
            )
            self.db.commit()
            return client.name
        except Exception:
            self.db.rollback()
            raise

    def move_domain(self, domain: str, to_client: str) -> MoveResult:
        """Move a domain from one client to another.

        Transactional — rolls back on failure.
        """
        domain = domain.lower().strip()

        domain_row = (
            self.db.query(DomainRow).filter(DomainRow.domain_name == domain).first()
        )
        if not domain_row or domain_row.status == DomainStatus.OFFBOARDED.value:
            raise DomainNotFoundError(f"Domain '{domain}' not found or offboarded")

        source_client = self.client_service.get_by_id(domain_row.client_id)
        dest_client = self.client_service.get(to_client)

        if dest_client.status == ClientStatus.OFFBOARDED.value:
            raise ClientNotFoundError(f"Client '{to_client}' is offboarded")

        if source_client.id == dest_client.id:
            raise DomainAlreadyExistsError(
                f"Domain '{domain}' already belongs to '{dest_client.name}'"
            )

        try:
            is_first_for_dest = len(dest_client.active_domains) == 0

            # Move in YAML mapping (atomic)
            self.parsedmarc.move_domain_mapping(
                source_client.index_prefix, dest_client.index_prefix, domain
            )
            self.parsedmarc.reload()

            # Update DB
            domain_row.client_id = dest_client.id

            # Provision destination tenant if first domain
            if is_first_for_dest:
                self.opensearch.provision_tenant(
                    dest_client.tenant_name, dest_client.index_prefix
                )
                if dest_client.retention_days:
                    self.retention.create_client_policy(
                        dest_client.index_prefix, dest_client.retention_days
                    )
                try:
                    self.dashboards.import_for_client(
                        dest_client.tenant_name, dest_client.index_prefix
                    )
                except FileNotFoundError:
                    logger.warning("Dashboard template not found, skipping import")

            self.db.add(
                AuditLogRow(
                    client_id=dest_client.id,
                    domain=domain,
                    action="domain_move",
                    detail={
                        "from_client": source_client.name,
                        "to_client": dest_client.name,
                    },
                    success=True,
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return MoveResult(
            domain=domain,
            from_client=source_client.name,
            to_client=dest_client.name,
        )

    def bulk_import(
        self,
        file_path: str,
        client_name: str,
        operation: str = "add",
        create_client: bool = False,
    ) -> BulkResult:
        """Process domains from a newline-separated text file."""
        domains = self._parse_domain_file(file_path)
        results = BulkResult()

        for domain in domains:
            try:
                if operation == "add":
                    self.add_domain(
                        client_name,
                        domain,
                        create_client=create_client,
                    )
                    results.succeeded.append(domain)
                elif operation == "remove":
                    self.remove_domain(domain)
                    results.succeeded.append(domain)
                elif operation == "move":
                    self.move_domain(domain, client_name)
                    results.succeeded.append(domain)
            except DomainAlreadyExistsError:
                results.skipped.append(domain)
            except Exception as e:
                results.failed.append((domain, str(e)))

        return results

    def _parse_domain_file(self, file_path: str) -> list[str]:
        seen: set[str] = set()
        domains: list[str] = []
        with open(file_path) as f:
            for line in f:
                domain = line.strip().lower()
                if not domain or domain.startswith("#"):
                    continue
                if domain not in seen:
                    seen.add(domain)
                    domains.append(domain)
        return domains
