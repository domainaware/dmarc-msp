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

    # The default index prefix used in the template NDJSON
    TEMPLATE_PREFIX = "dmarc"

    def __init__(
        self,
        dashboards_config: DashboardsConfig,
        opensearch_config: OpenSearchConfig,
    ):
        self.dashboards_url = dashboards_config.url.rstrip("/")
        self.template_path = Path(dashboards_config.saved_objects_template)
        self.auth = (opensearch_config.username, opensearch_config.resolved_password)

    def import_for_client(self, tenant_name: str, index_prefix: str) -> None:
        """Rewrite the template NDJSON with the client's index prefix
        and import into their tenant."""
        if not self.template_path.exists():
            raise FileNotFoundError(
                f"Dashboard template not found: {self.template_path}"
            )

        rewritten = self._rewrite_template(index_prefix)
        self._import_saved_objects(tenant_name, rewritten)
        logger.info(
            "Imported dashboards for tenant=%s prefix=%s", tenant_name, index_prefix
        )

    def _rewrite_template(self, index_prefix: str) -> str:
        """Replace the template index prefix with the client's prefix."""
        content = self.template_path.read_text()
        lines = content.strip().split("\n")
        rewritten_lines = []

        for line in lines:
            if not line.strip():
                continue
            obj = json.loads(line)
            rewritten = json.dumps(obj).replace(
                f'"{self.TEMPLATE_PREFIX}-', f'"{index_prefix}-'
            )
            rewritten = rewritten.replace(
                f'"{self.TEMPLATE_PREFIX}_', f'"{index_prefix}_'
            )
            rewritten_lines.append(rewritten)

        return "\n".join(rewritten_lines)

    def _import_saved_objects(self, tenant_name: str, ndjson: str) -> None:
        """POST the NDJSON to the Dashboards saved objects API."""
        url = (
            f"{self.dashboards_url}/api/saved_objects/_import"
            "?overwrite=true"
        )
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
