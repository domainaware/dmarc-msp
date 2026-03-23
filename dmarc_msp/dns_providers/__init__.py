"""Pluggable DNS provider backends."""

from dmarc_msp.dns_providers.base import DNSProvider, DNSRecord

__all__ = ["DNSProvider", "DNSRecord"]
