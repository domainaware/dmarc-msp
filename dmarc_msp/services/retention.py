"""ISM policy management and email retention."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from opensearchpy import OpenSearch

from dmarc_msp.config import OpenSearchConfig, RetentionConfig

logger = logging.getLogger(__name__)


class RetentionService:
    """Manages ISM policies for index retention and Maildir email cleanup."""

    def __init__(
        self,
        opensearch_config: OpenSearchConfig,
        retention_config: RetentionConfig,
    ):
        self.client = OpenSearch(
            hosts=[opensearch_config.hosts],
            http_auth=(
                opensearch_config.username,
                opensearch_config.resolved_password,
            ),
            use_ssl=opensearch_config.ssl,
            verify_certs=opensearch_config.verify_certs,
            ssl_show_warn=False,
        )
        self.default_days = retention_config.index_default_days
        self.email_days = retention_config.email_days

    def ensure_default_policy(self) -> None:
        """Create or update the default ISM policy for DMARC indices."""
        self._create_policy("dmarc_default_retention", self.default_days, "dmarc-*")

    def create_client_policy(self, index_prefix: str, retention_days: int) -> None:
        """Create an ISM policy for a specific client's indices."""
        policy_id = f"dmarc_retention_{index_prefix}"
        index_pattern = f"{index_prefix}-*"
        self._create_policy(policy_id, retention_days, index_pattern)

    def delete_client_policy(self, index_prefix: str) -> None:
        """Delete a client-specific ISM policy."""
        policy_id = f"dmarc_retention_{index_prefix}"
        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_ism/policies/{policy_id}",
            )
            logger.info("Deleted ISM policy: %s", policy_id)
        except Exception:
            logger.debug("ISM policy '%s' not found for deletion", policy_id)

    def _create_policy(
        self, policy_id: str, retention_days: int, index_pattern: str
    ) -> None:
        body = {
            "policy": {
                "description": (
                    f"Auto-delete indices older than {retention_days} days"
                ),
                "default_state": "hot",
                "states": [
                    {
                        "name": "hot",
                        "actions": [],
                        "transitions": [
                            {
                                "state_name": "delete",
                                "conditions": {
                                    "min_index_age": f"{retention_days}d"
                                },
                            }
                        ],
                    },
                    {
                        "name": "delete",
                        "actions": [{"delete": {}}],
                        "transitions": [],
                    },
                ],
                "ism_template": [
                    {
                        "index_patterns": [index_pattern],
                        "priority": 100,
                    }
                ],
            }
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_ism/policies/{policy_id}",
            body=body,
        )
        logger.info(
            "Created ISM policy: %s (%d days, pattern=%s)",
            policy_id,
            retention_days,
            index_pattern,
        )

    def cleanup_emails(self, maildir_path: str) -> int:
        """Delete processed email files older than email_days.

        Returns the number of files deleted.
        """
        maildir = Path(maildir_path)
        if not maildir.exists():
            logger.warning("Maildir path does not exist: %s", maildir_path)
            return 0

        cutoff = time.time() - (self.email_days * 86400)
        deleted = 0

        for filepath in maildir.rglob("*"):
            if not filepath.is_file():
                continue
            try:
                if filepath.stat().st_mtime < cutoff:
                    filepath.unlink()
                    deleted += 1
            except OSError as e:
                logger.warning("Failed to delete %s: %s", filepath, e)

        logger.info(
            "Email cleanup: deleted %d files older than %d days from %s",
            deleted,
            self.email_days,
            maildir_path,
        )
        return deleted
