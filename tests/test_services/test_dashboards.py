"""Tests for dashboard service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dmarc_msp.config import DashboardsConfig, OpenSearchConfig
from dmarc_msp.services.dashboards import DashboardService


def _make_template(tmp_path, lines=None):
    """Create a template NDJSON file and return a DashboardService."""
    template = tmp_path / "dashboards.ndjson"
    if lines is None:
        lines = [
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "dmarc_aggregate*"},
                }
            ),
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "dmarc_f*"},
                }
            ),
            json.dumps(
                {
                    "type": "index-pattern",
                    "attributes": {"title": "smtp_tls*"},
                }
            ),
        ]
    template.write_text("\n".join(lines) + "\n")
    dash_config = DashboardsConfig(
        url="http://localhost:5601",
        saved_objects_template=str(template),
    )
    os_config = OpenSearchConfig(password="test_password")
    return DashboardService(dash_config, os_config)


def test_rewrite_template_prepends_prefix(tmp_path):
    svc = _make_template(tmp_path)
    svc.import_failure_reports = True
    rewritten = svc._rewrite_template("acme_corp")
    assert '"acme_corp_dmarc_aggregate*"' in rewritten
    assert '"acme_corp_dmarc_f*"' in rewritten
    assert '"acme_corp_smtp_tls*"' in rewritten


def test_rewrite_template_excludes_failure_objects_by_default(tmp_path):
    """Failure index-pattern, its dependents, and orphaned objects
    referenced only by the failure dashboard are all excluded."""
    aggregate_pattern = json.dumps(
        {
            "type": "index-pattern",
            "id": "agg-idx",
            "attributes": {"title": "dmarc_aggregate*"},
            "references": [],
        }
    )
    failure_index_pattern = json.dumps(
        {
            "type": "index-pattern",
            "id": "fp-idx",
            "attributes": {"title": "dmarc_f*"},
            "references": [],
        }
    )
    # Markdown viz with no index-pattern reference — only used by the
    # failure dashboard, so it should be treated as an orphan.
    failure_markdown_vis = json.dumps(
        {
            "type": "visualization",
            "id": "fp-md",
            "attributes": {"title": "About DMARC failure reports (RUF)"},
            "references": [],
        }
    )
    failure_table_vis = json.dumps(
        {
            "type": "visualization",
            "id": "fp-vis",
            "attributes": {"title": "Failure samples"},
            "references": [{"id": "fp-idx", "name": "index", "type": "index-pattern"}],
        }
    )
    failure_dashboard = json.dumps(
        {
            "type": "dashboard",
            "id": "fp-dash",
            "attributes": {"title": "DMARC failure reports"},
            "references": [
                {"id": "fp-md", "name": "panel_0", "type": "visualization"},
                {"id": "fp-vis", "name": "panel_1", "type": "visualization"},
            ],
        }
    )
    lines = [
        aggregate_pattern,
        failure_index_pattern,
        failure_markdown_vis,
        failure_table_vis,
        failure_dashboard,
    ]
    svc = _make_template(tmp_path, lines)
    rewritten = svc._rewrite_template("acme_corp")
    assert '"acme_corp_dmarc_aggregate*"' in rewritten
    assert "dmarc_f" not in rewritten
    assert "fp-idx" not in rewritten
    assert "fp-md" not in rewritten
    assert "fp-vis" not in rewritten
    assert "fp-dash" not in rewritten


def test_rewrite_template_does_not_double_prefix(tmp_path):
    svc = _make_template(tmp_path)
    rewritten = svc._rewrite_template("acme_corp")
    assert "acme_corp_acme_corp" not in rewritten


def test_rewrite_template_skips_blank_lines(tmp_path):
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "attributes": {"title": "dmarc_aggregate*"},
            }
        ),
        "",
        "   ",
        json.dumps({"type": "vis", "id": "some-vis"}),
    ]
    svc = _make_template(tmp_path, lines)
    rewritten = svc._rewrite_template("client1")
    # Should have exactly 2 lines (blanks skipped)
    assert len(rewritten.strip().split("\n")) == 2


def test_import_for_client_missing_template(tmp_path):
    dash_config = DashboardsConfig(
        url="https://localhost:5601",
        saved_objects_template=str(tmp_path / "nonexistent.ndjson"),
    )
    os_config = OpenSearchConfig(password="test_password")
    svc = DashboardService(dash_config, os_config)
    with pytest.raises(FileNotFoundError, match="not found"):
        svc.import_for_client("tenant", "prefix")


def test_import_for_client_success(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        assert mock_client.post.call_count == 2
        import_call = mock_client.post.call_args_list[0]
        assert "securitytenant" in import_call.kwargs.get(
            "headers", import_call[1].get("headers", {})
        )


def test_import_for_client_enables_dark_mode_by_default(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        # Two calls: saved objects import + dark mode settings
        assert mock_client.post.call_count == 2
        dark_mode_call = mock_client.post.call_args_list[1]
        assert "settings" in dark_mode_call.args[0]
        assert dark_mode_call.kwargs["json"] == {"changes": {"theme:darkMode": True}}


def test_import_for_client_skips_dark_mode_when_disabled(tmp_path):
    template = tmp_path / "dashboards.ndjson"
    template.write_text(
        json.dumps(
            {"type": "index-pattern", "attributes": {"title": "dmarc_aggregate*"}}
        )
        + "\n"
    )
    dash_config = DashboardsConfig(
        url="http://localhost:5601",
        saved_objects_template=str(template),
        dark_mode=False,
    )
    os_config = OpenSearchConfig(password="test_password")
    svc = DashboardService(dash_config, os_config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        # Only saved objects import, no dark mode call
        assert mock_client.post.call_count == 1


def test_import_deletes_failure_objects_from_existing_tenant(tmp_path):
    """Re-importing with import_failure_reports=False deletes old failure
    saved objects via the Dashboards API before importing the new set."""
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "id": "agg-id",
                "attributes": {"title": "dmarc_aggregate*"},
                "references": [],
            }
        ),
        json.dumps(
            {
                "type": "index-pattern",
                "id": "fail-id",
                "attributes": {"title": "dmarc_f*"},
                "references": [],
            }
        ),
        json.dumps(
            {
                "type": "visualization",
                "id": "fail-vis",
                "attributes": {"title": "Failure samples"},
                "references": [
                    {"id": "fail-id", "name": "index", "type": "index-pattern"}
                ],
            }
        ),
    ]
    svc = _make_template(tmp_path, lines)

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client.delete.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")

        # Should have DELETE calls for the two failure objects
        delete_calls = mock_client.delete.call_args_list
        deleted_urls = [call.args[0] for call in delete_calls]
        assert any("index-pattern/fail-id" in url for url in deleted_urls)
        assert any("visualization/fail-vis" in url for url in deleted_urls)
        assert not any("agg-id" in url for url in deleted_urls)


def test_import_for_client_replace_deletes_all_template_ids(tmp_path):
    """With ``replace=True`` every template object is deleted from the
    tenant by (type, id) before import. Used to bypass OSD's silent
    failure mode when _import?overwrite=true skips updates."""
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "id": "agg-id",
                "attributes": {"title": "dmarc_aggregate*"},
                "references": [],
            }
        ),
        json.dumps(
            {
                "type": "visualization",
                "id": "viz-id",
                "attributes": {"title": "Some viz"},
                "references": [
                    {"id": "agg-id", "name": "index", "type": "index-pattern"}
                ],
            }
        ),
        json.dumps(
            {
                "type": "dashboard",
                "id": "dash-id",
                "attributes": {"title": "Some dashboard"},
                "references": [
                    {"id": "viz-id", "name": "panel_0", "type": "visualization"}
                ],
            }
        ),
    ]
    svc = _make_template(tmp_path, lines)

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client.delete.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp", replace=True)

        deleted_urls = [call.args[0] for call in mock_client.delete.call_args_list]
        assert any("index-pattern/agg-id" in u for u in deleted_urls)
        assert any("visualization/viz-id" in u for u in deleted_urls)
        assert any("dashboard/dash-id" in u for u in deleted_urls)


def test_import_for_client_no_replace_does_not_delete_template(tmp_path):
    """Without ``replace=True`` the template IDs are not deleted. Only
    failure objects (which are deleted by a separate path when
    import_failure_reports=False) should be removed."""
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "id": "agg-id",
                "attributes": {"title": "dmarc_aggregate*"},
                "references": [],
            }
        ),
        json.dumps(
            {
                "type": "visualization",
                "id": "viz-id",
                "attributes": {"title": "Some viz"},
                "references": [
                    {"id": "agg-id", "name": "index", "type": "index-pattern"}
                ],
            }
        ),
    ]
    svc = _make_template(tmp_path, lines)

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client.delete.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")  # replace defaults False

        deleted_urls = [call.args[0] for call in mock_client.delete.call_args_list]
        assert not any("agg-id" in u for u in deleted_urls)
        assert not any("viz-id" in u for u in deleted_urls)


@pytest.mark.parametrize("replace", [True, False])
def test_import_for_client_refreshes_index_pattern_fields(tmp_path, replace):
    """Every import — plain or ``replace=True`` — re-runs the index-pattern
    field refresh. The template's baked-in ``attributes.fields`` list goes
    stale whenever parsedmarc adds or renames fields, and OSD never
    auto-refreshes, so leaving this to the operator means visualizations
    silently break on freshly-imported tenants."""
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "id": "agg-id",
                "attributes": {"title": "dmarc_aggregate*"},
                "references": [],
            }
        ),
    ]
    svc = _make_template(tmp_path, lines)

    import_response = MagicMock()
    import_response.json.return_value = {"success": True}
    import_response.raise_for_status = MagicMock()
    import_response.status_code = 200

    find_response = MagicMock()
    find_response.json.return_value = {
        "saved_objects": [
            {"id": "agg-id", "attributes": {"title": "acme_corp_dmarc_aggregate*"}},
        ]
    }
    find_response.raise_for_status = MagicMock()

    fields_response = MagicMock()
    fields_response.json.return_value = {"fields": [{"name": "source_asn"}]}
    fields_response.raise_for_status = MagicMock()

    put_response = MagicMock()
    put_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = import_response
        mock_client.delete.return_value = import_response

        def _get(url, *args, **kwargs):
            if "/_find" in url:
                return find_response
            return fields_response

        mock_client.get.side_effect = _get
        mock_client.put.return_value = put_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp", replace=replace)

        # The index-pattern's attributes.fields is PUT back with the live
        # mapping — that's how refresh_index_pattern_fields writes its
        # result.
        put_urls = [call.args[0] for call in mock_client.put.call_args_list]
        assert any("index-pattern/agg-id" in u for u in put_urls)


def test_import_for_client_sets_default_index(tmp_path):
    """The aggregate index-pattern ID is set as defaultIndex during import."""
    lines = [
        json.dumps(
            {
                "type": "index-pattern",
                "id": "agg-id",
                "attributes": {"title": "dmarc_aggregate*"},
            }
        ),
        json.dumps(
            {
                "type": "index-pattern",
                "id": "tls-id",
                "attributes": {"title": "smtp_tls*"},
            }
        ),
    ]
    svc = _make_template(tmp_path, lines)
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.import_for_client("acme_tenant", "acme_corp")
        # Two calls: saved objects import + settings (defaultIndex + dark mode)
        assert mock_client.post.call_count == 2
        settings_call = mock_client.post.call_args_list[1]
        changes = settings_call.kwargs["json"]["changes"]
        assert changes["defaultIndex"] == "agg-id"
        assert changes["theme:darkMode"] is True


def test_set_dark_mode(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        svc.set_dark_mode("acme_tenant")
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["securitytenant"] == "acme_tenant"
        assert call_kwargs.kwargs["json"] == {"changes": {"theme:darkMode": True}}


def test_import_for_client_api_failure(tmp_path):
    svc = _make_template(tmp_path)
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "errors": [{"type": "conflict"}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch("dmarc_msp.services.dashboards.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="import failed"):
            svc.import_for_client("acme_tenant", "acme_corp")
