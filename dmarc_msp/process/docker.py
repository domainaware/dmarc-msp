"""Docker-based process signaling for parsedmarc."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class DockerSignaler:
    """Sends SIGHUP to the parsedmarc container to reload config."""

    def __init__(self, container_name: str = "parsedmarc"):
        self.container_name = container_name

    def send_sighup(self) -> bool:
        """Send SIGHUP to reload configuration. Returns True on success."""
        try:
            subprocess.run(
                ["docker", "kill", "-s", "HUP", self.container_name],
                check=True,
                capture_output=True,
            )
            logger.info("Sent SIGHUP to container '%s'", self.container_name)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to send SIGHUP to '%s': %s",
                self.container_name,
                e.stderr.decode() if e.stderr else str(e),
            )
            return False
        except FileNotFoundError:
            logger.error("Docker CLI not found — is Docker installed?")
            return False
