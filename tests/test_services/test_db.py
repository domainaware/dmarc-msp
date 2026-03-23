"""Tests for database utilities."""

from dmarc_msp.db import slugify


def test_slugify_basic():
    assert slugify("Acme Corp") == "acme_corp"


def test_slugify_special_chars():
    assert slugify("Health & Co.") == "health_co"


def test_slugify_multiple_spaces():
    assert slugify("  Some   Name  ") == "some_name"


def test_slugify_already_clean():
    assert slugify("simple") == "simple"
