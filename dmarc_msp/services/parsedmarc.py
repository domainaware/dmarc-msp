"""parsedmarc YAML domain mapping management + process reload."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from dmarc_msp.process.docker import DockerSignaler

logger = logging.getLogger(__name__)


class ParsedmarcService:
    def __init__(self, domain_map_file: str, signaler: DockerSignaler):
        self.domain_map_file = Path(domain_map_file)
        self.signaler = signaler

    def add_domain_mapping(self, index_prefix: str, domain: str) -> None:
        """Add a domain under an index prefix."""
        mapping = self._read()
        prefix = index_prefix.lower()
        domain = domain.lower()
        if prefix not in mapping:
            mapping[prefix] = []
        if domain not in mapping[prefix]:
            mapping[prefix].append(domain)
            mapping[prefix].sort()
        self._write(mapping)
        logger.info("Added domain mapping: %s -> %s", prefix, domain)

    def remove_domain_mapping(self, index_prefix: str, domain: str) -> None:
        """Remove a domain from a prefix. Removes empty prefixes."""
        mapping = self._read()
        prefix = index_prefix.lower()
        domain = domain.lower()
        if prefix in mapping:
            mapping[prefix] = [d for d in mapping[prefix] if d != domain]
            if not mapping[prefix]:
                del mapping[prefix]
        self._write(mapping)
        logger.info("Removed domain mapping: %s -> %s", prefix, domain)

    def move_domain_mapping(
        self, from_prefix: str, to_prefix: str, domain: str
    ) -> None:
        """Atomically move a domain between prefixes in a single read-write."""
        mapping = self._read()
        from_p = from_prefix.lower()
        to_p = to_prefix.lower()
        domain = domain.lower()

        # Remove from source
        if from_p in mapping:
            mapping[from_p] = [d for d in mapping[from_p] if d != domain]
            if not mapping[from_p]:
                del mapping[from_p]

        # Add to destination
        if to_p not in mapping:
            mapping[to_p] = []
        if domain not in mapping[to_p]:
            mapping[to_p].append(domain)
            mapping[to_p].sort()

        self._write(mapping)
        logger.info("Moved domain mapping: %s/%s -> %s", from_p, domain, to_p)

    def get_all_mappings(self) -> dict[str, list[str]]:
        """Return all current mappings."""
        return self._read()

    def reload(self) -> bool:
        """Send SIGHUP to parsedmarc to reload config."""
        return self.signaler.send_sighup()

    def _read(self) -> dict[str, list[str]]:
        if not self.domain_map_file.exists():
            return {}
        with open(self.domain_map_file) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    def _write(self, mapping: dict[str, list[str]]) -> None:
        sorted_mapping = dict(sorted(mapping.items()))
        with open(self.domain_map_file, "w") as f:
            yaml.dump(sorted_mapping, f, default_flow_style=False, sort_keys=True)
