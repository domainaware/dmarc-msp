"""Stress tests for bulk onboarding/offboarding at MSP scale.

Exercises the DNS lifecycle paths that matter when multiple clients churn
simultaneously, verifying:
  - Bulk add/remove of 20+ domains with DNS record creation/cleanup
  - DB/DNS consistency after partial failures
  - Pre-existing authorization records (migration from another solution)
  - Interleaved onboarding and offboarding across clients
  - Multiple concurrent client offboardings don't interfere
  - Stale DNS records don't linger after re-onboarding offboarded domains
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.config import Settings
from dmarc_msp.db import DomainRow
from dmarc_msp.models import DomainStatus
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.offboarding import OffboardingService
from dmarc_msp.services.onboarding import OnboardingService


def _make_services(db_session: Session):
    """Build onboarding + offboarding services with mock externals."""
    client_svc = ClientService(db_session)
    dns = MagicMock()
    dns.create_authorization_record.return_value = MagicMock(
        record=MagicMock(record_id="rec_123"),
        already_existed=False,
    )
    dns.verify_authorization_record.return_value = True
    dns.delete_authorization_record.return_value = True
    opensearch = MagicMock()
    dashboards = MagicMock()
    retention = MagicMock()
    parsedmarc = MagicMock()

    onboard = OnboardingService(
        client_service=client_svc,
        dns=dns,
        opensearch=opensearch,
        dashboards=dashboards,
        retention=retention,
        parsedmarc=parsedmarc,
        db=db_session,
    )
    offboard = OffboardingService(
        client_service=client_svc,
        dns=dns,
        opensearch=opensearch,
        parsedmarc=parsedmarc,
        retention=retention,
        db=db_session,
    )
    return onboard, offboard, client_svc, dns, parsedmarc, opensearch


def _add_domains(onboard, client_name: str, count: int) -> list[str]:
    """Add *count* domains to a client, returning the domain list."""
    domains = [f"domain-{i}.example.com" for i in range(count)]
    for d in domains:
        onboard.add_domain(client_name, d)
    return domains


# ---------------------------------------------------------------------------
# Bulk remove: 25 domains, all succeed
# ---------------------------------------------------------------------------


class TestBulkRemoveAtScale:
    def test_bulk_remove_25_domains_cleans_all_dns(
        self, db_session: Session, tmp_path
    ):
        """Every authorization record is deleted when bulk-removing 25 domains."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")
        domains = _add_domains(onboard, "BigClient", 25)

        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="remove")

        assert len(result.succeeded) == 25
        assert len(result.failed) == 0
        assert dns.delete_authorization_record.call_count == 25

        # All domains should be offboarded in DB
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0

    def test_bulk_remove_continues_after_dns_failure(
        self, db_session: Session, tmp_path
    ):
        """If DNS delete fails on domain 10, domains 1-9 and 11-25 still process."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")
        domains = _add_domains(onboard, "BigClient", 25)

        # Fail DNS delete only for domain-9
        call_count = 0
        original_return = True

        def selective_dns_failure(domain_name):
            nonlocal call_count
            call_count += 1
            if domain_name == "domain-9.example.com":
                raise RuntimeError("DNS provider timeout")
            return original_return

        dns.delete_authorization_record.side_effect = selective_dns_failure

        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="remove")

        assert len(result.succeeded) == 24
        assert len(result.failed) == 1
        assert result.failed[0][0] == "domain-9.example.com"

        # domain-9 should still be active
        d9 = (
            db_session.query(DomainRow)
            .filter_by(domain_name="domain-9.example.com")
            .one()
        )
        assert d9.status != DomainStatus.OFFBOARDED.value

        # All others should be offboarded
        still_active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(still_active) == 1

    def test_bulk_remove_multiple_scattered_failures(
        self, db_session: Session, tmp_path
    ):
        """Multiple DNS failures at different positions don't corrupt state."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")
        domains = _add_domains(onboard, "BigClient", 30)

        fail_set = {"domain-0.example.com", "domain-14.example.com", "domain-29.example.com"}

        def selective_failure(domain_name):
            if domain_name in fail_set:
                raise RuntimeError(f"DNS error for {domain_name}")
            return True

        dns.delete_authorization_record.side_effect = selective_failure

        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="remove")

        assert len(result.succeeded) == 27
        assert len(result.failed) == 3
        failed_domains = {f[0] for f in result.failed}
        assert failed_domains == fail_set

        still_active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert {d.domain_name for d in still_active} == fail_set


# ---------------------------------------------------------------------------
# Client offboarding: 25 domains, all succeed
# ---------------------------------------------------------------------------


class TestOffboardClientAtScale:
    def test_offboard_25_domains_cleans_all_dns(self, db_session: Session):
        """Full client offboarding deletes all 25 authorization records."""
        onboard, offboard, client_svc, dns, parsedmarc, opensearch = _make_services(
            db_session
        )
        client_svc.create("BigClient")
        _add_domains(onboard, "BigClient", 25)

        dns.reset_mock()
        parsedmarc.reset_mock()

        result = offboard.offboard_client("BigClient")

        assert result.domains_removed == 25
        assert dns.delete_authorization_record.call_count == 25

        # Parsedmarc reloaded exactly once (batched), not 25 times
        assert parsedmarc.reload.call_count == 1

        # All domains offboarded
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0

        client = client_svc.get("BigClient")
        assert client.status == "offboarded"

    def test_offboard_completes_despite_dns_failure_midway(
        self, db_session: Session
    ):
        """If DNS delete fails on domain 15 of 25, offboarding still
        completes — all domains are offboarded in DB, and the failed DNS
        deletion is reported in the result."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")
        domains = _add_domains(onboard, "BigClient", 25)

        def fail_on_15th(domain_name):
            if domain_name == "domain-14.example.com":
                raise RuntimeError("DNS provider rate limit")
            return True

        dns.delete_authorization_record.side_effect = fail_on_15th

        result = offboard.offboard_client("BigClient")

        assert result.domains_removed == 25
        assert len(result.dns_failures) == 1
        assert result.dns_failures[0][0] == "domain-14.example.com"
        assert "DNS provider rate limit" in result.dns_failures[0][1]

        # Client is offboarded despite DNS failure
        client = client_svc.get("BigClient")
        assert client.status == "offboarded"

        # All domains offboarded in DB
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0

    def test_offboard_dns_already_deleted_is_idempotent(
        self, db_session: Session
    ):
        """If DNS records were already removed (e.g. manual cleanup),
        offboarding still succeeds — delete returning False is not an error."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")
        _add_domains(onboard, "BigClient", 10)

        # Simulate all DNS records already gone
        dns.delete_authorization_record.return_value = False

        result = offboard.offboard_client("BigClient")
        assert result.domains_removed == 10

        client = client_svc.get("BigClient")
        assert client.status == "offboarded"


# ---------------------------------------------------------------------------
# Multiple client churn in the same batch
# ---------------------------------------------------------------------------


class TestMultiClientChurn:
    def test_three_clients_offboarded_sequentially(self, db_session: Session):
        """Three clients churning in the same week — no cross-contamination."""
        onboard, offboard, client_svc, dns, parsedmarc, opensearch = _make_services(
            db_session
        )

        clients = {
            "Alpha Corp": 8,
            "Beta LLC": 12,
            "Gamma Inc": 20,
        }
        all_domains: dict[str, list[str]] = {}

        for name, count in clients.items():
            client_svc.create(name)
            all_domains[name] = [
                f"{name.split()[0].lower()}-{i}.example.com" for i in range(count)
            ]
            for d in all_domains[name]:
                onboard.add_domain(name, d)

        dns.reset_mock()

        # Offboard all three
        for name in clients:
            offboard.offboard_client(name)

        # Total DNS deletions = 8 + 12 + 20 = 40
        assert dns.delete_authorization_record.call_count == 40

        # Verify each client's domains were targeted
        deleted_domains = [
            call.args[0] for call in dns.delete_authorization_record.call_args_list
        ]
        for name, domain_list in all_domains.items():
            for d in domain_list:
                assert d in deleted_domains, f"{d} not deleted for {name}"

        # All clients offboarded
        for name in clients:
            assert client_svc.get(name).status == "offboarded"

        # Zero active domains in DB
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0

    def test_one_client_has_dns_failures_others_clean(self, db_session: Session):
        """Beta has DNS failures during offboarding but still completes.
        Alpha and Gamma offboard cleanly."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)

        for name in ["Alpha Corp", "Beta LLC", "Gamma Inc"]:
            client_svc.create(name)
        for i in range(5):
            onboard.add_domain("Alpha Corp", f"alpha-{i}.example.com")
            onboard.add_domain("Beta LLC", f"beta-{i}.example.com")
            onboard.add_domain("Gamma Inc", f"gamma-{i}.example.com")

        def fail_on_beta(domain_name):
            if domain_name == "beta-2.example.com":
                raise RuntimeError("DNS timeout")
            return True

        dns.delete_authorization_record.side_effect = fail_on_beta

        alpha_result = offboard.offboard_client("Alpha Corp")
        assert alpha_result.dns_failures == []
        assert client_svc.get("Alpha Corp").status == "offboarded"

        beta_result = offboard.offboard_client("Beta LLC")
        assert len(beta_result.dns_failures) == 1
        assert beta_result.dns_failures[0][0] == "beta-2.example.com"
        assert client_svc.get("Beta LLC").status == "offboarded"

        gamma_result = offboard.offboard_client("Gamma Inc")
        assert gamma_result.dns_failures == []
        assert client_svc.get("Gamma Inc").status == "offboarded"

        # All clients offboarded, zero active domains
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0


# ---------------------------------------------------------------------------
# Stale DNS record scenarios
# ---------------------------------------------------------------------------


class TestStaleDNSRecords:
    def test_re_onboard_after_offboard_creates_fresh_dns(
        self, db_session: Session
    ):
        """Domain offboarded then re-added to new client gets a fresh DNS
        record — no stale record from the old client lingers."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("OldClient")
        client_svc.create("NewClient")
        onboard.add_domain("OldClient", "migrating.example.com")

        dns.reset_mock()

        # Offboard old client
        offboard.offboard_client("OldClient")
        dns.delete_authorization_record.assert_called_with("migrating.example.com")

        dns.reset_mock()

        # Re-add to new client
        onboard.add_domain("NewClient", "migrating.example.com")
        dns.create_authorization_record.assert_called_with("migrating.example.com")

        # Domain is active under new client
        domain = (
            db_session.query(DomainRow)
            .filter_by(domain_name="migrating.example.com")
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .one()
        )
        new_client = client_svc.get("NewClient")
        assert domain.client_id == new_client.id

    def test_bulk_remove_then_re_add_subset(
        self, db_session: Session, tmp_path
    ):
        """Bulk remove 20 domains, then re-add 5 of them — only 5 DNS
        creates happen, and the other 15 stay offboarded."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("Client")
        domains = _add_domains(onboard, "Client", 20)

        domain_file = tmp_path / "remove.txt"
        domain_file.write_text("\n".join(domains) + "\n")
        onboard.bulk_import(str(domain_file), "Client", operation="remove")

        dns.reset_mock()

        # Re-add first 5
        readd = domains[:5]
        for d in readd:
            onboard.add_domain("Client", d)

        assert dns.create_authorization_record.call_count == 5

        offboarded = (
            db_session.query(DomainRow)
            .filter_by(status=DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(offboarded) == 15

        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 5


# ---------------------------------------------------------------------------
# DNS/DB consistency gap in offboarding
# ---------------------------------------------------------------------------


class TestDNSDBConsistency:
    """DNS deletions are best-effort — failures are captured in the result
    rather than aborting the entire offboarding. This keeps the DB consistent
    and surfaces stale DNS records to the operator."""

    def test_offboard_with_dns_failure_still_commits_db(
        self, db_session: Session
    ):
        """When DNS delete fails on domain 3 of 5, all 5 domains are still
        offboarded in the DB, and the failure is reported."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("Client")
        _add_domains(onboard, "Client", 5)

        deleted_dns = []

        def track_and_fail(domain_name):
            if domain_name == "domain-2.example.com":
                raise RuntimeError("DNS provider error")
            deleted_dns.append(domain_name)
            return True

        dns.delete_authorization_record.side_effect = track_and_fail

        result = offboard.offboard_client("Client")

        # DNS succeeded for 4 of 5
        assert len(deleted_dns) == 4
        assert "domain-2.example.com" not in deleted_dns

        # Failure is reported
        assert len(result.dns_failures) == 1
        assert result.dns_failures[0][0] == "domain-2.example.com"

        # DB is fully consistent — all 5 offboarded
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 0

        client = client_svc.get("Client")
        assert client.status == "offboarded"

    def test_offboard_with_all_dns_failures_still_completes(
        self, db_session: Session
    ):
        """Even if every DNS deletion fails, the client is still offboarded
        in the DB. All failures are reported."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("Client")
        _add_domains(onboard, "Client", 5)

        dns.delete_authorization_record.side_effect = RuntimeError("DNS down")

        result = offboard.offboard_client("Client")

        assert result.domains_removed == 5
        assert len(result.dns_failures) == 5

        client = client_svc.get("Client")
        assert client.status == "offboarded"

    def test_dns_failures_logged_in_audit(self, db_session: Session):
        """DNS failures are persisted in the audit log for traceability."""
        from dmarc_msp.db import AuditLogRow

        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("Client")
        _add_domains(onboard, "Client", 3)

        def fail_on_first(domain_name):
            if domain_name == "domain-0.example.com":
                raise RuntimeError("rate limited")
            return True

        dns.delete_authorization_record.side_effect = fail_on_first

        offboard.offboard_client("Client")

        audit = (
            db_session.query(AuditLogRow)
            .filter_by(action="client_offboard")
            .one()
        )
        assert len(audit.detail["dns_failures"]) == 1
        assert audit.detail["dns_failures"][0][0] == "domain-0.example.com"


# ---------------------------------------------------------------------------
# Bulk onboarding at scale
# ---------------------------------------------------------------------------


class TestBulkOnboardAtScale:
    def test_bulk_add_25_domains_creates_all_dns(
        self, db_session: Session, tmp_path
    ):
        """Every authorization record is created when bulk-adding 25 domains."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")

        domains = [f"domain-{i}.example.com" for i in range(25)]
        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="add")

        assert len(result.succeeded) == 25
        assert len(result.failed) == 0
        assert dns.create_authorization_record.call_count == 25

        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 25

    def test_bulk_add_continues_after_dns_failure(
        self, db_session: Session, tmp_path
    ):
        """If DNS create fails on domain 10, domains 1-9 and 11-25 still process."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")

        def selective_create_failure(domain_name):
            if domain_name == "domain-9.example.com":
                raise RuntimeError("DNS provider timeout")
            return MagicMock(
                record=MagicMock(record_id="rec_ok"),
                already_existed=False,
            )

        dns.create_authorization_record.side_effect = selective_create_failure

        domains = [f"domain-{i}.example.com" for i in range(25)]
        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="add")

        assert len(result.succeeded) == 24
        assert len(result.failed) == 1
        assert result.failed[0][0] == "domain-9.example.com"

        # Failed domain should not be in DB (rolled back)
        d9 = (
            db_session.query(DomainRow)
            .filter_by(domain_name="domain-9.example.com")
            .first()
        )
        assert d9 is None

    def test_bulk_add_multiple_scattered_failures(
        self, db_session: Session, tmp_path
    ):
        """Multiple DNS create failures at different positions."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("BigClient")

        fail_set = {"domain-0.example.com", "domain-14.example.com", "domain-29.example.com"}

        def selective_failure(domain_name):
            if domain_name in fail_set:
                raise RuntimeError(f"DNS error for {domain_name}")
            return MagicMock(
                record=MagicMock(record_id="rec_ok"),
                already_existed=False,
            )

        dns.create_authorization_record.side_effect = selective_failure

        domains = [f"domain-{i}.example.com" for i in range(30)]
        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "BigClient", operation="add")

        assert len(result.succeeded) == 27
        assert len(result.failed) == 3
        failed_domains = {f[0] for f in result.failed}
        assert failed_domains == fail_set

    def test_bulk_add_provisions_tenant_only_once(
        self, db_session: Session, tmp_path
    ):
        """OpenSearch tenant is provisioned on first domain, not repeated for 24 more."""
        onboard, _, client_svc, dns, _, opensearch = _make_services(db_session)
        client_svc.create("BigClient")

        domains = [f"domain-{i}.example.com" for i in range(25)]
        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        onboard.bulk_import(str(domain_file), "BigClient", operation="add")

        opensearch.provision_tenant.assert_called_once()


# ---------------------------------------------------------------------------
# Pre-existing authorization records
# ---------------------------------------------------------------------------


class TestPreExistingAuthRecords:
    def test_onboard_domain_with_preexisting_record(self, db_session: Session):
        """Domain previously monitored by another DMARC solution already has
        an authorization record. Onboarding succeeds with already_existed=True."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("NewClient")

        dns.create_authorization_record.return_value = MagicMock(
            record=MagicMock(record_id="rec_preexisting"),
            already_existed=True,
        )

        result = onboard.add_domain("NewClient", "legacy.example.com")

        assert result.dns_record_existed is True
        assert result.domain == "legacy.example.com"

    def test_bulk_add_mix_of_new_and_preexisting(
        self, db_session: Session, tmp_path
    ):
        """Bulk add where some domains have pre-existing records and some don't."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)
        client_svc.create("NewClient")

        preexisting = {"legacy-0.example.com", "legacy-1.example.com"}

        def mixed_create(domain_name):
            existed = domain_name in preexisting
            return MagicMock(
                record=MagicMock(record_id=f"rec_{domain_name}"),
                already_existed=existed,
            )

        dns.create_authorization_record.side_effect = mixed_create

        domains = [f"legacy-{i}.example.com" for i in range(5)]
        domain_file = tmp_path / "domains.txt"
        domain_file.write_text("\n".join(domains) + "\n")

        result = onboard.bulk_import(str(domain_file), "NewClient", operation="add")

        assert len(result.succeeded) == 5
        assert len(result.failed) == 0


# ---------------------------------------------------------------------------
# DNS create resilience (race condition / provider conflict handling)
# ---------------------------------------------------------------------------


class TestDNSCreateResilience:
    """Tests for the DNSService.create_authorization_record retry logic:
    if create_txt_record raises but the record actually exists (race condition
    or provider that doesn't handle duplicates gracefully), treat as success."""

    def test_create_fails_but_record_exists_on_recheck(self, db_session: Session):
        """Provider raises on create, but re-check finds the record — success."""
        from dmarc_msp.dns_providers.base import DNSRecord
        from dmarc_msp.services.dns import DMARC_AUTH_VALUE, DNSService

        from tests.test_dns_providers.test_base import FakeDNSProvider

        provider = FakeDNSProvider()
        settings = Settings(
            database={"url": "sqlite:///:memory:"},
            opensearch={"password": "test"},
            msp={"domain": "dmarc.test.example.com", "rua_email": "r@test.example.com"},
            dns={"provider": "cloudflare", "zone": "test.example.com"},
        )
        dns_svc = DNSService(provider=provider, settings=settings)

        # Simulate: get_txt_records returns empty on first call (pre-check),
        # create_txt_record raises, then get_txt_records finds the record
        # on re-check (another process created it in between).
        call_count = {"get": 0}
        original_get = provider.get_txt_records
        original_create = provider.create_txt_record

        def get_with_race(zone, name):
            call_count["get"] += 1
            if call_count["get"] == 1:
                return []  # first check: nothing there
            # re-check after failed create: record appeared
            return [DNSRecord(fqdn=f"{name}.{zone}", value=DMARC_AUTH_VALUE)]

        def create_raises(zone, name, value, ttl=3600):
            raise RuntimeError("409 Conflict: record already exists")

        provider.get_txt_records = get_with_race
        provider.create_txt_record = create_raises

        result = dns_svc.create_authorization_record("client.example.com")

        assert result.already_existed is True
        assert result.record.value == DMARC_AUTH_VALUE

    def test_create_fails_and_record_still_missing(self, db_session: Session):
        """Provider raises on create and re-check confirms record doesn't
        exist — genuine failure, re-raises."""
        from dmarc_msp.services.dns import DNSProviderError, DNSService

        from tests.test_dns_providers.test_base import FakeDNSProvider

        provider = FakeDNSProvider()
        settings = Settings(
            database={"url": "sqlite:///:memory:"},
            opensearch={"password": "test"},
            msp={"domain": "dmarc.test.example.com", "rua_email": "r@test.example.com"},
            dns={"provider": "cloudflare", "zone": "test.example.com"},
        )
        dns_svc = DNSService(provider=provider, settings=settings)

        provider.get_txt_records = lambda zone, name: []

        def create_always_fails(zone, name, value, ttl=3600):
            raise RuntimeError("API rate limit")

        provider.create_txt_record = create_always_fails

        with pytest.raises(DNSProviderError, match="API rate limit"):
            dns_svc.create_authorization_record("client.example.com")

    def test_preexisting_record_found_on_initial_check(self, db_session: Session):
        """Record already exists from a previous DMARC solution — found on
        the initial get_txt_records check, create is never called."""
        from dmarc_msp.services.dns import DMARC_AUTH_VALUE, DNSService

        from tests.test_dns_providers.test_base import FakeDNSProvider

        provider = FakeDNSProvider()
        settings = Settings(
            database={"url": "sqlite:///:memory:"},
            opensearch={"password": "test"},
            msp={"domain": "dmarc.test.example.com", "rua_email": "r@test.example.com"},
            dns={"provider": "cloudflare", "zone": "test.example.com"},
        )
        dns_svc = DNSService(provider=provider, settings=settings)

        # Pre-populate the record (as if left by a previous tool)
        provider.create_txt_record(
            zone="test.example.com",
            name="client.example.com._report._dmarc.dmarc",
            value=DMARC_AUTH_VALUE,
        )

        create_called = False
        original_create = provider.create_txt_record

        def track_create(*args, **kwargs):
            nonlocal create_called
            create_called = True
            return original_create(*args, **kwargs)

        provider.create_txt_record = track_create

        result = dns_svc.create_authorization_record("client.example.com")

        assert result.already_existed is True
        assert create_called is False


# ---------------------------------------------------------------------------
# Interleaved onboarding and offboarding
# ---------------------------------------------------------------------------


class TestInterleavedOnboardOffboard:
    """Simulate the real-world scenario: one client onboards while another
    offboards, using the same DNS provider and DB session."""

    def test_onboard_client_while_offboarding_another(
        self, db_session: Session
    ):
        """Client A offboards 10 domains while Client B onboards 10 domains.
        No interference between the two."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)

        client_svc.create("Departing")
        client_svc.create("Arriving")
        departing_domains = _add_domains(onboard, "Departing", 10)

        dns.reset_mock()

        # Offboard Departing
        off_result = offboard.offboard_client("Departing")
        assert off_result.domains_removed == 10
        assert off_result.dns_failures == []

        # Onboard Arriving
        arriving_domains = []
        for i in range(10):
            d = f"arriving-{i}.example.com"
            onboard.add_domain("Arriving", d)
            arriving_domains.append(d)

        # Verify final state
        assert client_svc.get("Departing").status == "offboarded"
        assert client_svc.get("Arriving").status == "active"

        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 10
        assert {d.domain_name for d in active} == set(arriving_domains)

        # DNS: 10 deletes + 10 creates
        assert dns.delete_authorization_record.call_count == 10
        assert dns.create_authorization_record.call_count == 10

    def test_offboarded_domain_immediately_re_onboarded_to_new_client(
        self, db_session: Session
    ):
        """Domain removed from Client A and immediately added to Client B
        in the same session — no stale state."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)

        client_svc.create("OldMSP")
        client_svc.create("NewMSP")

        domains = _add_domains(onboard, "OldMSP", 5)

        # Offboard OldMSP
        offboard.offboard_client("OldMSP")

        dns.reset_mock()

        # Re-add all 5 to NewMSP
        for d in domains:
            onboard.add_domain("NewMSP", d)

        assert dns.create_authorization_record.call_count == 5

        # All 5 active under NewMSP
        new_client = client_svc.get("NewMSP")
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 5
        assert all(d.client_id == new_client.id for d in active)

    def test_bulk_add_and_remove_interleaved(
        self, db_session: Session, tmp_path
    ):
        """Bulk add to Client A, then bulk remove from Client B, then bulk
        add to Client C — all in the same session."""
        onboard, _, client_svc, dns, *_ = _make_services(db_session)

        client_svc.create("ClientA")
        client_svc.create("ClientB")
        client_svc.create("ClientC")

        # Seed Client B with domains to remove
        b_domains = _add_domains(onboard, "ClientB", 15)

        dns.reset_mock()

        # Bulk add 20 to A
        a_domains = [f"a-{i}.example.com" for i in range(20)]
        f_a = tmp_path / "add_a.txt"
        f_a.write_text("\n".join(a_domains) + "\n")
        result_a = onboard.bulk_import(str(f_a), "ClientA", operation="add")
        assert len(result_a.succeeded) == 20

        # Bulk remove 15 from B
        f_b = tmp_path / "remove_b.txt"
        f_b.write_text("\n".join(b_domains) + "\n")
        result_b = onboard.bulk_import(str(f_b), "ClientB", operation="remove")
        assert len(result_b.succeeded) == 15

        # Bulk add 10 to C
        c_domains = [f"c-{i}.example.com" for i in range(10)]
        f_c = tmp_path / "add_c.txt"
        f_c.write_text("\n".join(c_domains) + "\n")
        result_c = onboard.bulk_import(str(f_c), "ClientC", operation="add")
        assert len(result_c.succeeded) == 10

        # Final state: A has 20, B has 0 active, C has 10
        active = (
            db_session.query(DomainRow)
            .filter(DomainRow.status != DomainStatus.OFFBOARDED.value)
            .all()
        )
        assert len(active) == 30

        assert dns.create_authorization_record.call_count == 30
        assert dns.delete_authorization_record.call_count == 15

    def test_parsedmarc_reload_failure_rolls_back_onboarding(
        self, db_session: Session
    ):
        """If parsedmarc reload fails, the domain add is rolled back —
        domain is not committed to DB, and the DNS record is cleaned up."""
        from dmarc_msp.services.parsedmarc import ParsedmarcReloadError

        onboard, _, client_svc, dns, parsedmarc, _ = _make_services(db_session)
        client_svc.create("Client")

        parsedmarc.reload.side_effect = ParsedmarcReloadError("SIGHUP failed")

        with pytest.raises(ParsedmarcReloadError):
            onboard.add_domain("Client", "new.example.com")

        # Domain should not exist in DB (rolled back)
        assert (
            db_session.query(DomainRow)
            .filter_by(domain_name="new.example.com")
            .first()
        ) is None

        # DNS record should be cleaned up
        dns.delete_authorization_record.assert_called_with("new.example.com")

    def test_parsedmarc_reload_failure_during_offboard_does_not_abort(
        self, db_session: Session
    ):
        """Parsedmarc reload failure during offboarding is best-effort —
        the offboard still completes."""
        from dmarc_msp.services.parsedmarc import ParsedmarcReloadError

        onboard, offboard, client_svc, dns, parsedmarc, _ = _make_services(
            db_session
        )
        client_svc.create("Client")
        _add_domains(onboard, "Client", 5)

        parsedmarc.reload.side_effect = ParsedmarcReloadError("SIGHUP failed")

        result = offboard.offboard_client("Client")
        assert result.domains_removed == 5
        assert client_svc.get("Client").status == "offboarded"

    def test_dns_failure_during_onboard_doesnt_affect_concurrent_offboard(
        self, db_session: Session
    ):
        """DNS failures while onboarding Client B don't interfere with
        offboarding Client A."""
        onboard, offboard, client_svc, dns, *_ = _make_services(db_session)

        client_svc.create("Departing")
        client_svc.create("Arriving")
        _add_domains(onboard, "Departing", 5)

        # Offboard succeeds
        off_result = offboard.offboard_client("Departing")
        assert off_result.domains_removed == 5

        # Onboard fails on DNS
        dns.create_authorization_record.side_effect = RuntimeError("DNS down")

        with pytest.raises(RuntimeError, match="DNS down"):
            onboard.add_domain("Arriving", "new.example.com")

        # Departing is still cleanly offboarded
        assert client_svc.get("Departing").status == "offboarded"

        # Arriving has no domains (rolled back)
        arriving = client_svc.get("Arriving")
        assert len(arriving.active_domains) == 0
