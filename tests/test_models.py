"""Tests for Pydantic models."""

from __future__ import annotations

from dmarc_msp.models import BulkResult


def test_bulk_result_total_empty():
    result = BulkResult()
    assert result.total == 0


def test_bulk_result_total_mixed():
    result = BulkResult(
        succeeded=["a.com", "b.com"],
        skipped=["c.com"],
        failed=[("d.com", "error")],
    )
    assert result.total == 4


def test_bulk_result_total_only_succeeded():
    result = BulkResult(succeeded=["a.com", "b.com", "c.com"])
    assert result.total == 3
