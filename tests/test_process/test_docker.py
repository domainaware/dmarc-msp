"""Tests for Docker process signaling."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from dmarc_msp.process.docker import DockerSignaler


def test_send_sighup_success():
    signaler = DockerSignaler("parsedmarc")
    with patch("dmarc_msp.process.docker.subprocess.run") as mock_run:
        assert signaler.send_sighup() is True
        mock_run.assert_called_once_with(
            ["docker", "kill", "-s", "HUP", "parsedmarc"],
            check=True,
            capture_output=True,
        )


def test_send_sighup_called_process_error():
    signaler = DockerSignaler("parsedmarc")
    with patch(
        "dmarc_msp.process.docker.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "docker", stderr=b"not found"),
    ):
        assert signaler.send_sighup() is False


def test_send_sighup_called_process_error_no_stderr():
    signaler = DockerSignaler("parsedmarc")
    with patch(
        "dmarc_msp.process.docker.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "docker", stderr=None),
    ):
        assert signaler.send_sighup() is False


def test_send_sighup_docker_not_found():
    signaler = DockerSignaler("parsedmarc")
    with patch(
        "dmarc_msp.process.docker.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert signaler.send_sighup() is False


def test_custom_container_name():
    signaler = DockerSignaler("my_container")
    assert signaler.container_name == "my_container"
