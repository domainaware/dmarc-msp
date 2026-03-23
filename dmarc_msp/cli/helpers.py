"""Shared CLI helpers for dependency wiring."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from dmarc_msp.config import Settings, load_settings
from dmarc_msp.db import init_db
from dmarc_msp.dns_providers.base import DNSProvider
from dmarc_msp.process.docker import DockerSignaler
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.dns import DNSService
from dmarc_msp.services.offboarding import OffboardingService
from dmarc_msp.services.onboarding import OnboardingService
from dmarc_msp.services.opensearch import OpenSearchService
from dmarc_msp.services.parsedmarc import ParsedmarcService
from dmarc_msp.services.retention import RetentionService


@lru_cache
def get_settings(config_path: str | None = None) -> Settings:
    return load_settings(config_path)


def get_db_session(settings: Settings) -> Session:
    session_factory = init_db(settings.database.url)
    return session_factory()


def get_dns_provider(settings: Settings) -> DNSProvider:
    provider_name = settings.dns.provider.lower()
    if provider_name == "cloudflare":
        from dmarc_msp.dns_providers.cloudflare import CloudflareDNSProvider

        token = settings.dns.cloudflare.get("api_token")
        return CloudflareDNSProvider(api_token=token)
    elif provider_name == "route53":
        from dmarc_msp.dns_providers.route53 import Route53DNSProvider

        zone_id = settings.dns.route53.get("hosted_zone_id", "")
        return Route53DNSProvider(hosted_zone_id=zone_id)
    elif provider_name == "gcp":
        from dmarc_msp.dns_providers.gcp import GCPDNSProvider

        project = settings.dns.gcp.get("project", "")
        return GCPDNSProvider(project=project)
    elif provider_name == "azure":
        from dmarc_msp.dns_providers.azure import AzureDNSProvider

        return AzureDNSProvider(
            subscription_id=settings.dns.azure.get("subscription_id", ""),
            resource_group=settings.dns.azure.get("resource_group", ""),
            zone_name=settings.dns.azure.get("zone_name", ""),
        )
    else:
        raise ValueError(f"Unknown DNS provider: {provider_name}")


def get_onboarding_service(
    settings: Settings, db: Session
) -> OnboardingService:
    dns_provider = get_dns_provider(settings)
    signaler = DockerSignaler(settings.parsedmarc.container)

    return OnboardingService(
        client_service=ClientService(db),
        dns=DNSService(dns_provider, settings),
        opensearch=OpenSearchService(settings.opensearch),
        dashboards=DashboardService(settings.dashboards, settings.opensearch),
        retention=RetentionService(settings.opensearch, settings.retention),
        parsedmarc=ParsedmarcService(
            settings.parsedmarc.domain_map_file, signaler
        ),
        db=db,
    )


def get_offboarding_service(
    settings: Settings, db: Session
) -> OffboardingService:
    dns_provider = get_dns_provider(settings)
    signaler = DockerSignaler(settings.parsedmarc.container)

    return OffboardingService(
        client_service=ClientService(db),
        dns=DNSService(dns_provider, settings),
        opensearch=OpenSearchService(settings.opensearch),
        parsedmarc=ParsedmarcService(
            settings.parsedmarc.domain_map_file, signaler
        ),
        retention=RetentionService(settings.opensearch, settings.retention),
        db=db,
    )
