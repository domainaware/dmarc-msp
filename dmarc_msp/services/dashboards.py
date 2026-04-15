"""OpenSearch Dashboards saved object management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from dmarc_msp.config import DashboardsConfig, OpenSearchConfig

logger = logging.getLogger(__name__)


class DashboardService:
    """Rewrites and imports saved objects into per-client tenants."""

    # Index pattern names used in the template NDJSON (without prefix).
    # parsedmarc creates indices like {prefix}_{pattern} when using
    # index_prefix_domain_map, so rewriting prepends the client prefix.
    TEMPLATE_PATTERNS = ["dmarc_aggregate", "dmarc_f", "smtp_tls"]

    def __init__(
        self,
        dashboards_config: DashboardsConfig,
        opensearch_config: OpenSearchConfig,
    ):
        self.dashboards_url = dashboards_config.url.rstrip("/")
        self.template_path = Path(dashboards_config.saved_objects_template)
        self.auth = (opensearch_config.username, opensearch_config.resolved_password)
        self.dark_mode = dashboards_config.dark_mode
        self.import_failure_reports = dashboards_config.import_failure_reports

    def import_for_client(self, tenant_name: str, index_prefix: str) -> None:
        """Rewrite the template NDJSON with the client's index prefix
        and import into their tenant."""
        if not self.template_path.exists():
            raise FileNotFoundError(
                f"Dashboard template not found: {self.template_path}"
            )

        rewritten = self._rewrite_template(index_prefix)
        self._import_saved_objects(tenant_name, rewritten)
        if self.dark_mode:
            self.set_dark_mode(tenant_name, enabled=True)
        logger.info(
            "Imported dashboards for tenant=%s prefix=%s", tenant_name, index_prefix
        )

    def set_dark_mode(self, tenant_name: str, enabled: bool = True) -> None:
        """Set dark mode in a tenant's advanced settings."""
        url = f"{self.dashboards_url}/api/opensearch-dashboards/settings"
        headers = {
            "osd-xsrf": "true",
            "securitytenant": tenant_name,
        }
        with httpx.Client(verify=False, auth=self.auth, timeout=30) as client:
            response = client.post(
                url,
                headers=headers,
                json={"changes": {"theme:darkMode": enabled}},
            )
            response.raise_for_status()
        state = "enabled" if enabled else "disabled"
        logger.info("Dark mode %s for tenant=%s", state, tenant_name)

    def _rewrite_template(self, index_prefix: str) -> str:
        """Prepend the client's index prefix to all known index patterns.

        When ``import_failure_reports`` is disabled, objects related to the
        ``dmarc_f`` (forensic/failure) index pattern are excluded.
        """
        content = self.template_path.read_text()
        lines = content.strip().split("\n")
        objects = []
        for line in lines:
            if not line.strip():
                continue
            objects.append(json.loads(line))

        if not self.import_failure_reports:
            objects = self._exclude_failure_objects(objects)

        patterns = self.TEMPLATE_PATTERNS
        if not self.import_failure_reports:
            patterns = [p for p in patterns if p != "dmarc_f"]

        rewritten_lines = []
        for obj in objects:
            rewritten = json.dumps(obj)
            for pattern in patterns:
                rewritten = rewritten.replace(
                    f'"{pattern}', f'"{index_prefix}_{pattern}'
                )
            rewritten_lines.append(rewritten)

        return "\n".join(rewritten_lines)

    @staticmethod
    def _exclude_failure_objects(
        objects: list[dict],
    ) -> list[dict]:
        """Remove the ``dmarc_f`` index-pattern and all objects that
        depend on it (transitively via saved-object references)."""
        # Find failure index-pattern IDs.
        failure_ids: set[str] = set()
        for obj in objects:
            oid = obj.get("id")
            if (
                oid
                and obj.get("type") == "index-pattern"
                and obj.get("attributes", {})
                .get("title", "")
                .startswith("dmarc_f")
            ):
                failure_ids.add(oid)

        if not failure_ids:
            return objects

        # Phase 1: forward — any object referencing a failure object is
        # itself failure-related (e.g. a viz using the failure index
        # pattern, or a dashboard embedding that viz).
        changed = True
        while changed:
            changed = False
            for obj in objects:
                oid = obj.get("id")
                if not oid or oid in failure_ids:
                    continue
                refs = obj.get("references", [])
                if any(r["id"] in failure_ids for r in refs):
                    failure_ids.add(oid)
                    changed = True

        # Phase 2: reverse — objects referenced *only* by failure objects
        # are orphaned and should also be excluded (e.g. a markdown viz
        # embedded exclusively in the failure dashboard).
        kept_refs: set[str] = set()
        for obj in objects:
            if obj.get("id") not in failure_ids:
                for r in obj.get("references", []):
                    kept_refs.add(r["id"])

        failure_refs: set[str] = set()
        for obj in objects:
            if obj.get("id") in failure_ids:
                for r in obj.get("references", []):
                    failure_refs.add(r["id"])

        for oid in failure_refs - kept_refs:
            if oid not in failure_ids:
                failure_ids.add(oid)

        return [obj for obj in objects if obj.get("id") not in failure_ids]

    def _import_saved_objects(self, tenant_name: str, ndjson: str) -> None:
        """POST the NDJSON to the Dashboards saved objects API."""
        url = f"{self.dashboards_url}/api/saved_objects/_import?overwrite=true"
        headers = {
            "osd-xsrf": "true",
            "securitytenant": tenant_name,
        }

        with httpx.Client(verify=False, auth=self.auth, timeout=30) as client:
            response = client.post(
                url,
                headers=headers,
                files={"file": ("dashboards.ndjson", ndjson, "application/ndjson")},
            )
            response.raise_for_status()
            result = response.json()

        if not result.get("success", False):
            errors = result.get("errors", [])
            logger.error("Dashboard import errors: %s", errors)
            raise RuntimeError(f"Dashboard import failed: {errors}")
